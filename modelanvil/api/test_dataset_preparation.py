"""Acceptance for the bounded upload -> prepare -> publish data slice."""
import hashlib
import io
import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings, tag
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision, LineageEdge
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key


@override_settings(ALLOWED_HOSTS=["testserver"])
class DatasetPreparationApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL,
            "artifact_backend": "filesystem", "artifact_root": root.name})
        override.enable()
        self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug="dataset-preparation", name="Dataset preparation")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="owner", role=Role.OWNER, secret_hash=digest)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        self.dataset = Dataset.objects.create(tenant_id=self.tenant.pk, name="Prepared local text")
        self.documents = []
        for number, text in enumerate(("A first training example.", "A second training example."), 1):
            self.documents.append({
                "schema_version": "1.0", "sample_id": str(uuid.uuid4()),
                "source_group_id": f"source-group-{number}",
                "blocks": [{"block_id": "text", "type": "text", "text": text}],
                "provenance": {"source_snapshot_ref": "uploaded-fixture",
                    "source_record_key": str(number),
                    "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
            })
        self.raw = b"".join(json.dumps(document, ensure_ascii=False).encode("utf-8") + b"\n"
                            for document in self.documents)
        self.input_artifact = Artifact.objects.create(
            tenant_id=self.tenant.pk, storage_location_id="local", object_key="inputs/training.jsonl",
            sha256=hashlib.sha256(self.raw).hexdigest(), byte_size=len(self.raw),
            media_type="application/x-ndjson")
        upload_staged_artifact(self.input_artifact, io.BytesIO(self.raw), backend=artifact_storage_backend())
        self.url = f"/api/v1/datasets/{self.dataset.dataset_id}/prepare/"

    def test_committed_upload_becomes_a_verified_published_dataset_revision(self):
        response = self.client.post(self.url, {
            "input_artifact_id": str(self.input_artifact.artifact_id), "split_seed": "fixture-seed",
            "validation_percent": 10, "test_percent": 10,
        }, format="json", **self.auth)
        self.assertEqual(response.status_code, 201)
        revision = DatasetRevision.all_objects.get(revision_id=response.json()["revision_id"])
        self.assertEqual(revision.tenant_id, self.tenant.pk)
        self.assertEqual(revision.dataset_id, self.dataset.pk)
        self.assertEqual(revision.state, DatasetRevision.State.PUBLISHED)
        self.assertEqual(revision.row_count, len(self.documents))
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.current_revision_id, revision.pk)
        artifact = revision.manifest_artifact
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.state, Artifact.State.COMMITTED)
        with artifact_storage_backend().open(self.tenant.pk, str(artifact.object_key)) as stream:
            raw = stream.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact.sha256)
        self.assertEqual(len(raw), artifact.byte_size)
        self.assertEqual(revision.manifest_digest, artifact.sha256)
        prepared = json.loads(raw)
        self.assertEqual(prepared["rows"], self.documents)
        self.assertEqual(prepared["row_count"], len(self.documents))
        self.assertEqual(prepared["recipe_digest"], revision.recipe_digest)
        ids = [sample_id for values in prepared["split_manifest"].values() for sample_id in values]
        self.assertCountEqual(ids, [document["sample_id"] for document in self.documents])

    def test_publication_preserves_project_scope_on_manifest_and_revision(self):
        team = Team.objects.create(tenant_id=self.tenant.pk, name="Data", slug="data")
        project = Project.objects.create(tenant_id=self.tenant.pk, team=team, name="Scoped data", slug="scoped-data")
        self.dataset.project = project
        self.dataset.save(update_fields=["project"])
        response = self.client.post(self.url, {"input_artifact_id": str(self.input_artifact.artifact_id)},
            format="json", HTTP_X_PROJECT_ID=str(project.pk), **self.auth)
        self.assertEqual(response.status_code, 201, response.content)
        revision = DatasetRevision.all_objects.get(revision_id=response.json()["revision_id"])
        self.assertEqual(revision.project_id, project.pk)
        self.assertEqual(revision.manifest_artifact.project_id, project.pk)

    def test_staging_input_is_refused_without_publishing(self):
        staging = Artifact.objects.create(
            tenant_id=self.tenant.pk, storage_location_id="local", object_key="inputs/staging.jsonl",
            sha256=hashlib.sha256(self.raw).hexdigest(), byte_size=len(self.raw),
            media_type="application/x-ndjson")
        response = self.client.post(self.url, {"input_artifact_id": str(staging.artifact_id)},
                                    format="json", **self.auth)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(DatasetRevision.all_objects.filter(dataset=self.dataset).exists())

    def test_another_tenants_input_is_not_found(self):
        other = Tenant.objects.create(slug="other-data", name="Other data")
        foreign = Artifact.objects.create(
            tenant_id=other.pk, storage_location_id="local", object_key="inputs/foreign.jsonl",
            sha256=hashlib.sha256(self.raw).hexdigest(), byte_size=len(self.raw),
            media_type="application/x-ndjson")
        response = self.client.post(self.url, {"input_artifact_id": str(foreign.artifact_id)},
                                    format="json", **self.auth)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(DatasetRevision.all_objects.filter(dataset=self.dataset).exists())

    def post_prepare(self, artifact=None, **options):
        return self.client.post(self.url, {
            "input_artifact_id": str((artifact or self.input_artifact).artifact_id), **options,
        }, format="json", **self.auth)

    def committed_input(self, raw, media_type="application/x-ndjson"):
        artifact = Artifact.all_objects.create(
            tenant_id=self.tenant.pk, storage_location_id="local",
            object_key=f"inputs/{uuid.uuid4()}.jsonl", sha256=hashlib.sha256(raw).hexdigest(),
            byte_size=len(raw), media_type=media_type)
        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
        return artifact

    def assert_no_publication(self, artifact_count):
        self.assertFalse(DatasetRevision.all_objects.filter(dataset=self.dataset).exists())
        self.assertEqual(Artifact.all_objects.filter(tenant_id=self.tenant.pk).count(), artifact_count)
        self.assertFalse(LineageEdge.all_objects.filter(tenant_id=self.tenant.pk).exists())
        self.dataset.refresh_from_db()
        self.assertIsNone(self.dataset.current_revision_id)

    def test_unknown_recipe_fields_are_not_silently_ignored(self):
        response = self.post_prepare(validation_precent=25)
        self.assertEqual(response.status_code, 400)
        self.assert_no_publication(1)

    def test_csv_and_json_import_publish_pinned_extraction_and_split_protection(self):
        from modelanvil.data.source_import import MEDIA_TYPES
        sources = [("csv", b'text,group\nFirst text,source-a\nSecond text,source-a\n'),
                   ("json", b'[{"text":"First text","group":"source-a"},{"text":"Second text","group":"source-a"}]')]
        for fmt, raw in sources:
            artifact = self.committed_input(raw, media_type=MEDIA_TYPES[fmt])
            response = self.post_prepare(artifact, source_format=fmt, group_field="group")
            self.assertEqual(response.status_code, 201, response.content)
            revision = DatasetRevision.all_objects.get(revision_id=response.json()["revision_id"])
            with artifact_storage_backend().open(self.tenant.pk, revision.manifest_artifact.object_key) as stream:
                prepared = json.load(stream)
            self.assertEqual(prepared["recipe"]["extraction"]["input_sha256"], artifact.sha256)
            self.assertEqual(prepared["row_count"], 2)
            self.assertEqual(prepared["source_group_count"], 1)
            self.assertEqual(sum(bool(ids) for ids in prepared["split_manifest"].values()), 1)
            self.assertEqual(prepared["recipe_digest"], revision.recipe_digest)
            self.assertEqual(hashlib.sha256(json.dumps(prepared["recipe"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(), revision.recipe_digest)

    def test_source_format_mismatch_and_invalid_csv_do_not_publish_or_echo(self):
        self.assertEqual(self.post_prepare(source_format="csv").status_code, 400)
        artifact = self.committed_input(b'text\n"PRIVATE_MARKER', media_type="text/csv")
        response = self.post_prepare(artifact, source_format="csv")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("PRIVATE_MARKER", response.content.decode())
        self.assert_no_publication(2)

    def test_chunking_preserves_parent_checks_source_positions_and_split_groups(self):
        from modelanvil.data.detection import build_protected_set
        parents = [dict(self.documents[0]), dict(self.documents[1])]
        parents[0]["blocks"] = [{"block_id": "text", "type": "text", "text": "Protected source content. " * 30}]
        parents[1]["blocks"] = [{"block_id": "text", "type": "text", "text": "Allowed source content with diverse symbols 日本語. " * 30}]
        artifact = self.committed_input(b'\n'.join(json.dumps(row).encode() for row in parents))
        response = self.post_prepare(artifact, chunk_characters=128, protected=build_protected_set(parents[:1]), near_threshold=0)
        self.assertEqual(response.status_code, 201, response.content)
        revision = DatasetRevision.all_objects.get(revision_id=response.json()["revision_id"])
        with artifact_storage_backend().open(self.tenant.pk, revision.manifest_artifact.object_key) as stream:
            prepared = json.load(stream)
        self.assertEqual(prepared["source_row_count"], 1)
        self.assertEqual(prepared["source_dropped"][0]["sample_id"], parents[0]["sample_id"])
        self.assertEqual("".join(row["blocks"][0]["text"] for row in prepared["rows"]), parents[1]["blocks"][0]["text"])
        self.assertEqual({row["source_group_id"] for row in prepared["rows"]}, {parents[1]["source_group_id"]})
        self.assertEqual(sum(bool(ids) for ids in prepared["split_manifest"].values()), 1)
        self.assertEqual(prepared["recipe"]["chunking"]["character_limit"], 128)
        self.assertEqual(prepared["recipe_digest"], revision.recipe_digest)

    def test_invalid_chunk_limit_or_chat_structure_cannot_publish(self):
        for value in [True, "128", 0, 4097, 128.5]:
            self.assertEqual(self.post_prepare(chunk_characters=value).status_code, 400)
        row = dict(self.documents[0]); row["blocks"] = [{"block_id": "text", "type": "text", "text": "Chat source text", "role": "user"}]
        artifact = self.committed_input(json.dumps(row).encode())
        self.assertEqual(self.post_prepare(artifact, chunk_characters=128).status_code, 400)
        self.assert_no_publication(2)

    def test_parent_privacy_detection_cannot_be_evaded_by_chunk_boundaries(self):
        parents = [dict(self.documents[0]), dict(self.documents[1])]
        parents[0]["blocks"] = [{"block_id": "text", "type": "text", "text": "p" * 28 + "a@b.co" + "y" * 30}]
        parents[1]["blocks"] = [{"block_id": "text", "type": "text", "text": "Allowed plain source content. " * 10}]
        artifact = self.committed_input(b'\n'.join(json.dumps(row).encode() for row in parents))
        response = self.post_prepare(artifact, chunk_characters=32, detect={"privacy": True, "quality": False})
        self.assertEqual(response.status_code, 201, response.content)
        revision = DatasetRevision.all_objects.get(revision_id=response.json()["revision_id"])
        self.assertEqual(revision.metadata["source_drop_report"]["drop_reason_counts"]["pii.email"], 1)

    def test_docx_import_publishes_and_bad_xml_leaves_no_revision(self):
        from modelanvil.data.test_source_import import docx
        from modelanvil.data.source_import import MEDIA_TYPES
        bad = self.committed_input(docx('<!DOCTYPE private [<!ENTITY e "PRIVATE_MARKER">]><private/>'), media_type=MEDIA_TYPES["docx"])
        response = self.post_prepare(bad, source_format="docx")
        self.assertEqual(response.status_code, 400)
        self.assert_no_publication(2)
        raw = docx('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Actual body text.</w:t></w:r></w:p></w:body></w:document>')
        artifact = self.committed_input(raw, media_type=MEDIA_TYPES["docx"])
        response = self.post_prepare(artifact, source_format="docx")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["row_count"], 1)

    def test_corrupted_or_missing_committed_bytes_cannot_publish(self):
        backend = artifact_storage_backend()
        for mode in ("corrupt", "missing"):
            with self.subTest(mode=mode):
                if mode == "corrupt":
                    path = backend._path(self.tenant.pk, self.input_artifact.object_key, create_parent=False)
                    path.write_bytes(b"x" * len(self.raw))
                else:
                    backend.delete(self.tenant.pk, self.input_artifact.object_key)
                self.assertEqual(self.post_prepare().status_code, 400)
                self.assert_no_publication(1)

    def test_invalid_jsonl_never_publishes_or_echoes_input(self):
        invalid = dict(self.documents[0], schema_version="PRIVATE_MARKER")
        duplicate_key = json.dumps(self.documents[0]).replace(
            '"schema_version": "1.0"', '"schema_version":"1.0","schema_version":"1.0"')
        values = [b"PRIVATE_MARKER\n", b"\xffPRIVATE_MARKER\n", b"\n",
                  json.dumps(invalid).encode() + b"\n", self.raw + b"\n",
                  json.dumps(self.documents[0]).encode() + b"\n" + json.dumps(self.documents[0]).encode(),
                  duplicate_key.encode() + b"\n",
                  json.dumps(dict(self.documents[0], metadata={"private": float("nan")})).encode()]
        for number, raw in enumerate(values):
            with self.subTest(kind=number):
                artifact = self.committed_input(raw)
                count = Artifact.all_objects.filter(tenant_id=self.tenant.pk).count()
                response = self.post_prepare(artifact)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("PRIVATE_MARKER", response.content.decode())
                self.assert_no_publication(count)

    def test_recipe_parameters_are_literal_and_strict(self):
        invalid = [{"split_seed": 1}, {"split_seed": False}, {"split_seed": None},
                   {"split_seed": "x" * 1025}, {"validation_percent": True},
                   {"validation_percent": "10"}, {"validation_percent": 1.5},
                   {"test_percent": -1}, {"test_percent": None},
                   {"validation_percent": 50, "test_percent": 50}]
        for options in invalid:
            with self.subTest(options=options):
                self.assertEqual(self.post_prepare(**options).status_code, 400)
                self.assert_no_publication(1)
        response = self.post_prepare(split_seed=" 007 ", validation_percent=0, test_percent=0)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["metadata"]["recipe"]["seed"], " 007 ")

    def test_only_local_unversioned_jsonl_is_supported(self):
        for field, value in (("storage_location_id", "elsewhere"), ("object_version", "v1"),
                             ("media_type", "text/plain")):
            with self.subTest(field=field):
                Artifact.all_objects.filter(pk=self.input_artifact.pk).update(**{field: value})
                self.assertEqual(self.post_prepare().status_code, 400)
                self.assert_no_publication(1)
                Artifact.all_objects.filter(pk=self.input_artifact.pk).update(
                    storage_location_id="local", object_version=None, media_type="application/x-ndjson")

    def test_input_byte_and_row_caps_are_enforced(self):
        oversized = Artifact.all_objects.create(
            tenant_id=self.tenant.pk, storage_location_id="local", object_key="inputs/oversized.jsonl",
            sha256="a" * 64, byte_size=16 * 1024 * 1024 + 1, media_type="application/x-ndjson")
        oversized.mark_verified(verified_sha256=oversized.sha256, verified_size=oversized.byte_size)
        self.assertEqual(self.post_prepare(oversized).status_code, 400)
        self.assert_no_publication(2)
        with patch("modelanvil.data.publication.MAX_ROWS", 1):
            self.assertEqual(self.post_prepare().status_code, 400)
        self.assert_no_publication(2)

    def test_new_preparation_keeps_the_previous_revision_unchanged(self):
        response = self.post_prepare()
        self.assertEqual(response.status_code, 201)
        first = response.json()
        original = DatasetRevision.all_objects.get(revision_id=first["revision_id"])
        with artifact_storage_backend().open(self.tenant.pk, original.manifest_artifact.object_key) as stream:
            original_bytes = stream.read()
        second = self.post_prepare()
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["revision_no"], first["revision_no"] + 1)
        self.assertNotEqual(second.json()["revision_id"], first["revision_id"])
        self.assertEqual(second.json()["manifest_digest"], first["manifest_digest"])
        self.dataset.refresh_from_db()
        original.refresh_from_db()
        self.assertEqual(self.dataset.current_revision.revision_id, uuid.UUID(second.json()["revision_id"]))
        with artifact_storage_backend().open(self.tenant.pk, original.manifest_artifact.object_key) as stream:
            self.assertEqual(stream.read(), original_bytes)
        self.assertEqual(LineageEdge.all_objects.filter(parent_artifact=self.input_artifact).count(), 2)

    def test_viewer_and_unauthenticated_requests_cannot_prepare(self):
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="viewer", role=Role.VIEWER, secret_hash=digest)
        payload = {"input_artifact_id": str(self.input_artifact.artifact_id)}
        response = self.client.post(self.url, payload, format="json", HTTP_AUTHORIZATION=f"Bearer {secret}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post(self.url, payload, format="json").status_code, 401)
        self.assert_no_publication(1)

    @tag("pg")
    def test_concurrent_preparation_allocates_distinct_revisions_and_advances_to_latest(self):
        barrier = Barrier(2)

        def prepare():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = APIClient().post(self.url, {
                    "input_artifact_id": str(self.input_artifact.artifact_id),
                }, format="json", **self.auth)
                return response.status_code, response.json()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(prepare) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual([code for code, _ in results], [201, 201])
        self.assertEqual(sorted(body["revision_no"] for _, body in results), [1, 2])
        revisions = DatasetRevision.all_objects.filter(dataset=self.dataset, tenant_id=self.tenant.pk)
        self.assertEqual(revisions.count(), 2)
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.current_revision.revision_no, 2)
        self.assertTrue(all(revision.manifest_artifact.state == Artifact.State.COMMITTED for revision in revisions))

    # ------------------------------------------------------------------
    # Detection options (WP-05 increment)
    # ------------------------------------------------------------------
    def make_doc(self, number, text, group="source-group-1"):
        return {
            "schema_version": "1.0", "sample_id": str(uuid.uuid4()),
            "source_group_id": group,
            "blocks": [{"block_id": "text", "type": "text", "text": text}],
            "provenance": {"source_snapshot_ref": "uploaded-fixture",
                            "source_record_key": str(number),
                            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
        }

    def committed_documents(self, *documents):
        raw = b"".join(json.dumps(document, ensure_ascii=False).encode("utf-8") + b"\n"
                       for document in documents)
        return self.committed_input(raw)

    def read_manifest(self, revision):
        with artifact_storage_backend().open(self.tenant.pk, revision.manifest_artifact.object_key) as stream:
            return json.loads(stream.read())

    def test_detection_options_flow_into_revision_and_manifest(self):
        clean = self.make_doc(1, "The quick brown fox jumps over the lazy dog.")
        pii = self.make_doc(2, "Contact alice@example.com, ssn 123-45-6789.", "source-group-2")
        short = self.make_doc(3, "hi", "source-group-3")
        twin = dict(clean)
        twin["sample_id"] = str(uuid.uuid4())
        artifact = self.committed_documents(clean, pii, short, twin)
        response = self.post_prepare(artifact, detect=True, dedup=True)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["row_count"], 1)
        self.assertEqual(body["metadata"]["drop_report"], {
            "input_rows": 4, "kept": 1, "dropped": 3,
            "drop_reason_counts": {"pii.email": 1, "pii.ssn": 1,
                                   "quality.short": 1, "duplicate.exact": 1}})
        self.assertEqual(body["metadata"]["recipe"]["detect"],
                         {"privacy": True, "quality": True, "min_text_chars": 8})
        self.assertEqual(body["metadata"]["recipe"]["dedup"],
                         {"exact": True, "near": True, "near_threshold": 3})
        revision = DatasetRevision.all_objects.get(revision_id=body["revision_id"])
        self.assertEqual(revision.row_count, 1)
        self.assertEqual(revision.metadata["drop_report"]["dropped"], 3)
        manifest = self.read_manifest(revision)
        self.assertEqual(manifest["row_count"], 1)
        self.assertEqual([row["sample_id"] for row in manifest["rows"]], [clean["sample_id"]])
        dropped = {entry["sample_id"]: entry["reasons"] for entry in manifest["dropped"]}
        self.assertEqual(dropped[pii["sample_id"]], ["pii.email", "pii.ssn"])
        self.assertEqual(dropped[short["sample_id"]], ["quality.short"])
        self.assertEqual(dropped[twin["sample_id"]], ["duplicate.exact"])

    def test_invalid_detection_options_refuse_before_publication(self):
        cases = [{"detect": "yes"}, {"detect": {"privacy": "yes"}},
                 {"detect": {"min_text_chars": -1}},
                 {"dedup": "yes"}, {"dedup": {"exact": 1}},
                 {"near_threshold": -1}, {"near_threshold": 1.5},
                 {"min_text_chars": -1}, {"min_text_chars": "x"},
                 {"protected": {"digests": "nope"}},
                 {"protected": {"digests": ["x" * 63]}},
                 {"protected": {"simhashes": [-1]}}]
        for options in cases:
            with self.subTest(options=options):
                self.assertEqual(self.post_prepare(**options).status_code, 400)
                self.assert_no_publication(1)

    def test_protected_set_records_counts_not_content(self):
        from modelanvil.data.detection import build_protected_set
        protected_doc = self.make_doc(9, "Protected evaluation question number one.")
        protected_set = build_protected_set([protected_doc])
        leak = self.make_doc(1, "Protected evaluation question number one.")
        clean = self.make_doc(2, "Ordinary training text.")
        artifact = self.committed_documents(leak, clean)
        response = self.post_prepare(artifact, protected=protected_set)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["row_count"], 1)
        self.assertEqual(body["metadata"]["recipe"]["protected"],
                         {"exact_count": 1, "near_count": 1, "near_threshold": 3})
        # Protected evaluation content must never appear in the API response.
        self.assertNotIn("Protected evaluation question", json.dumps(body))
        revision = DatasetRevision.all_objects.get(revision_id=body["revision_id"])
        manifest = self.read_manifest(revision)
        self.assertEqual(manifest["dropped"][0]["reasons"], ["overlap.protected_exact"])
        self.assertEqual([row["sample_id"] for row in manifest["rows"]], [clean["sample_id"]])

    def test_default_prepare_keeps_historical_recipe_shape(self):
        response = self.post_prepare()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        for key in ("detect", "dedup", "protected"):
            self.assertNotIn(key, body["metadata"]["recipe"])
        self.assertNotIn("drop_report", body["metadata"])
        revision = DatasetRevision.all_objects.get(revision_id=body["revision_id"])
        manifest = self.read_manifest(revision)
        self.assertNotIn("dropped", manifest)
        self.assertNotIn("report", manifest)
