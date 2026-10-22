"""HTTP subset integrity and real queued publication using synthetic source bytes."""

import io
import json
import tempfile
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact, Dataset, LineageEdge
from modelanvil.data.bank import http_snapshot as http
from modelanvil.data.bank.acquisition import (
    bank_acquisition_executor,
    git_blob_digest,
    launch_acquisition,
    preview_samples,
    resume_acquisition,
)
from modelanvil.data.bank.catalog import DatasetBankCatalog
from modelanvil.data.models import SourceSnapshot
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Worker, WorkerPool, claim_job


TEXT_SAMPLES = {
    "math-gsm8k": {"question": "What is 2 + 2?", "answer": "2 + 2 = 4. #### 4"},
    "code-mbpp": {
        "task_id": 1, "text": "Return café.", "code": "def cafe(): return 'café'",
        "test_list": ["assert cafe() == 'café'"], "test_setup_code": "",
        "challenge_test_list": [],
    },
    "text-dolly15k": {
        "instruction": "Name a café drink.", "context": "", "response": "Coffee.",
        "category": "open_qa",
    },
}


class RangeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.corrupt = False

    def __call__(self, url, headers):
        self.calls += 1
        start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
        raw = self.payload[start : end + 1]
        if self.corrupt:
            raw = bytes([raw[0] ^ 1]) + raw[1:]
        return 206, raw, {"Content-Range": f"bytes {start}-{end}/{len(self.payload)}"}


def container(raw):
    return {
        "url": "https://archive.ics.uci.edu/fixture",
        "size": len(raw),
        "segments": [{"start": 0, "length": len(raw), "sha256": http.digest(raw)}],
    }


class PinnedRangeTests(SimpleTestCase):
    def test_tampered_and_unqualified_ranges_are_refused(self):
        transport = RangeTransport(b"0123456789")
        source = container(transport.payload)
        stream = http.RangeFile(source, transport)
        stream.seek(3)
        self.assertEqual(stream.read(2), b"34")
        transport.corrupt = True
        with self.assertRaisesMessage(http.SnapshotError, "SHA-256"):
            http.RangeFile(source, transport).read(1)
        transport.corrupt = False
        source["segments"][0]["length"] = 2
        source["segments"][0]["sha256"] = http.digest(b"01")
        with self.assertRaisesMessage(http.SnapshotError, "outside"):
            http.RangeFile(source, transport).read(3)

    def test_range_response_and_resource_bounds_are_enforced(self):
        bad = lambda url, headers: (206, b"abc", {"Content-Range": "bytes 1-3/5"})
        with self.assertRaisesMessage(http.SnapshotError, "exact"):
            http.fetch_range(container(b"abcde")["url"], 5, 0, 3, bad)
        with self.assertRaisesMessage(http.SnapshotError, "bounds"):
            http.fetch_range(container(b"abcde")["url"], 5, 0, http.MAX_TRANSFER_BYTES + 1, bad)
        with self.assertRaisesMessage(http.SnapshotError, "HTTPS"):
            http.fetch_range("http://127.0.0.1/private", 5, 0, 1, bad)

    def test_zip_csv_and_media_are_decoded_without_extracting_files(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("table.csv", "a;b\n1;2\n3;4\n")
            archive.writestr("image.png", b"\x89PNG\r\n\x1a\nfixture")
            archive.writestr(
                "questions.json",
                '{"questions":[{"image_index":0,"question":"What?","answer":"cube"}]}',
            )
        raw = buffer.getvalue()
        transport = http.cached_transport(RangeTransport(raw))

        def decode(reader):
            return json.loads(
                http.decode_record(
                    {"reader": {"container": "data", **reader}},
                    {"data": http.RangeFile(container(raw), transport)},
                )
            )

        self.assertEqual(
            decode(
                {
                    "kind": "zip_csv_row",
                    "member": "table.csv",
                    "delimiter": ";",
                    "row_index": 1,
                    "numeric_fields": ["a", "b"],
                }
            ),
            {"a": 3.0, "b": 4.0},
        )
        value = decode(
            {
                "kind": "zip_bundle",
                "members": [
                    {"name": "image.png", "field": "image_hex", "encoding": "hex"},
                    {
                        "name": "questions.json",
                        "field": "questions",
                        "encoding": "json_prefix_filter",
                        "prefix_bytes": 1024,
                        "selection": {
                            "key": "questions",
                            "match_field": "image_index",
                            "match_value": 0,
                        },
                    },
                ],
            }
        )
        self.assertEqual(http.validate_sample("image-clevr", http.canonical_json(value)), value)

    def test_parquet_row_selection_and_decode_bound(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        buffer = io.BytesIO()
        pq.write_table(pa.Table.from_pylist([{"value": 1}, {"value": 2}]), buffer)
        raw = buffer.getvalue()
        record = {
            "reader": {"kind": "parquet_row", "container": "data", "row_group": 0, "row_index": 1}
        }
        stream = lambda: {"data": http.RangeFile(container(raw), RangeTransport(raw))}
        self.assertEqual(json.loads(http.decode_record(record, stream())), {"value": 2})
        with patch.object(http, "MAX_EXPANDED_BYTES", 1):
            with self.assertRaisesMessage(http.SnapshotError, "decode bound"):
                http.decode_record(record, stream())

    def test_tar_pairing_and_expansion_bound(self):
        buffer = io.BytesIO()
        members = {"speech.wav": b"RIFF0000WAVEfixture", "speech.txt": b"A paired transcript."}
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, payload in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        raw = buffer.getvalue()
        record = {
            "reader": {
                "kind": "tar_bundle",
                "container": "data",
                "prefix_bytes": len(raw),
                "members": [
                    {"name": "speech.wav", "field": "audio_hex", "encoding": "hex"},
                    {"name": "speech.txt", "field": "text", "encoding": "text"},
                ],
            }
        }
        stream = lambda: {"data": http.RangeFile(container(raw), RangeTransport(raw))}
        decoded = http.decode_record(record, stream())
        self.assertEqual(
            http.validate_sample("audio-libritts-r", decoded)["text"], "A paired transcript."
        )
        with patch.object(http, "MAX_EXPANDED_BYTES", 10):
            with self.assertRaisesMessage(http.SnapshotError, "expansion bound"):
                http.decode_record(record, stream())

    def test_new_text_source_schemas_preserve_fields_and_reject_invalid_rows(self):
        for source_id, value in TEXT_SAMPLES.items():
            with self.subTest(source=source_id):
                self.assertEqual(http.validate_sample(source_id, http.canonical_json(value)), value)
                for field in value:
                    invalid = {**value, field: None}
                    with self.subTest(field=field), self.assertRaisesMessage(http.SnapshotError, "schema"):
                        http.validate_sample(source_id, http.canonical_json(invalid))
                required = {
                    "math-gsm8k": ["question", "answer"],
                    "code-mbpp": ["text", "code", "test_list"],
                    "text-dolly15k": ["instruction", "response", "category"],
                }[source_id]
                for field in required:
                    with self.subTest(empty=field), self.assertRaisesMessage(http.SnapshotError, "schema"):
                        http.validate_sample(source_id, http.canonical_json({**value, field: ""}))
        for invalid in ({"task_id": True}, {"test_list": [1]}, {"challenge_test_list": [False]}):
            with self.assertRaisesMessage(http.SnapshotError, "schema"):
                http.validate_sample("code-mbpp", http.canonical_json({**TEXT_SAMPLES["code-mbpp"], **invalid}))

    def test_new_hf_sources_qualify_and_refetch_only_training_records(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from scripts import qualify_bank_subsets as qualifier

        path = Path(__file__).resolve().parents[3] / "catalog/dataset-presets.json"
        catalog = json.loads(path.read_text())
        for source_id, value in TEXT_SAMPLES.items():
            with self.subTest(source=source_id), tempfile.TemporaryDirectory() as root:
                source = next(s for s in catalog["sources"] if s["id"] == source_id)
                repo, prefix = qualifier.HF_SOURCES[source_id]
                rows = [{**value, "fixture_index": i} for i in range(20)]
                if source_id == "text-dolly15k":
                    raw = b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in rows)
                    # The incomplete suffix must never enter the frozen sample inventory.
                    raw += b'{"instruction":'
                    data_path = prefix
                else:
                    buffer = io.BytesIO()
                    pq.write_table(pa.Table.from_pylist(rows), buffer)
                    raw = buffer.getvalue()
                    data_path = prefix + "-of-00001.parquet"
                def metadata(url):
                    if url.endswith("/revision/main"):
                        return http.canonical_json({"sha": "a" * 40})
                    if "/tree/" in url:
                        entries = [{"path": data_path, "type": "file", "size": len(raw)}]
                        if "train-" in data_path:
                            entries.insert(0, {"path": data_path.replace("train-", "test-"), "type": "file", "size": 99})
                        return http.canonical_json(entries)
                    return b"Publisher license notice"
                with (
                    patch.object(qualifier, "get", metadata),
                    patch.object(qualifier, "transport", RangeTransport(raw)),
                    patch.object(qualifier, "CATALOG_ROOT", Path(root)),
                ):
                    report = qualifier.qualify(source, "2026-10-17")
                self.assertEqual(report["records"], 20)
                manifest = json.loads((Path(root) / (source_id + ".json")).read_text())
                self.assertEqual(manifest["upstream"]["commit"], "a" * 40)
                self.assertEqual({r["metadata"]["upstream_split"] for r in manifest["records"]}, {"train"})
                stream = {"data": http.RangeFile(manifest["containers"]["data"], RangeTransport(raw))}
                self.assertEqual([json.loads(http.decode_record(r, stream)) for r in manifest["records"]], rows)

    def test_new_text_groups_do_not_depend_on_answers(self):
        from scripts.qualify_bank_subsets import group_for

        for source_id, answer in (("math-gsm8k", "answer"), ("code-mbpp", "code"), ("text-dolly15k", "response")):
            row = TEXT_SAMPLES[source_id]
            self.assertEqual(group_for(source_id, row), group_for(source_id, {**row, answer: "Alternative answer"}))

    def test_question_prefix_and_answer_offsets_are_checked(self):
        self.assertEqual(
            http.json_prefix_rows(b'{"questions":[{"answer":"cube"},{"unfinished":', "questions"),
            [{"answer": "cube"}],
        )
        value = {
            "context": "red cube",
            "question": "What?",
            "answers": {"text": ["cube"], "answer_start": [4]},
        }
        http.validate_sample("text-squad", http.canonical_json(value))
        value["answers"]["answer_start"] = [0]
        with self.assertRaisesMessage(http.SnapshotError, "schema"):
            http.validate_sample("text-squad", http.canonical_json(value))

    def test_failed_requalification_preserves_existing_manifest_and_notice(self):
        from scripts import qualify_bank_subsets as qualifier

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("iris.data", "1,2,3,4,Iris-setosa\n2,2,3,4,Iris-setosa\n")
        raw = buffer.getvalue()
        path = Path(__file__).resolve().parents[3] / "catalog/dataset-presets.json"
        source = next(
            s for s in json.loads(path.read_text())["sources"] if s["id"] == "numeric-iris"
        )
        decode = qualifier.decode_record

        def refuse_refetch(record, files):
            if not next(iter(files.values())).capture:
                raise ValueError("Independent refetch failed")
            return decode(record, files)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "notices").mkdir()
            manifest = root / "numeric-iris.json"
            notice = root / "notices/numeric-iris-publisher-declaration.txt"
            manifest.write_bytes(b"existing manifest")
            notice.write_bytes(b"existing notice")
            with (
                patch.object(qualifier, "CATALOG_ROOT", root),
                patch.object(qualifier, "transport", RangeTransport(raw)),
                patch.object(qualifier, "size_at", return_value=(len(raw), {})),
                patch.object(qualifier, "get", return_value=("<h2>License</h2><p>" + qualifier.UCI_LICENSE_DECLARATION + "</p>").encode()),
                patch.object(qualifier, "decode_record", side_effect=refuse_refetch),
            ):
                with self.assertRaisesMessage(ValueError, "Independent refetch failed"):
                    qualifier.qualify(source, "2026-10-11")
            self.assertEqual(manifest.read_bytes(), b"existing manifest")
            self.assertEqual(notice.read_bytes(), b"existing notice")

    def test_uci_notices_exclude_contacts_and_script_metadata(self):
        from scripts.qualify_bank_subsets import UCI_LICENSE_DECLARATION, uci_license_notice

        page = (
            '<h2>License</h2><p>' + UCI_LICENSE_DECLARATION + '</p>'
            '<script>{"email":"private@example.test"}</script><p>Contact: other@example.test</p>'
        ).encode()
        for source_id in ("numeric-iris", "numeric-wine-quality"):
            url = "https://archive.ics.uci.edu/dataset/53/iris" if source_id == "numeric-iris" else "https://archive.ics.uci.edu/dataset/186/wine+quality"
            notice = uci_license_notice(source_id, page, url).decode()
            self.assertIn(UCI_LICENSE_DECLARATION, notice)
            self.assertIn(url, notice)
            self.assertIn("https://doi.org/10.24432/", notice)
            self.assertNotIn("@", notice)
            self.assertNotIn("<script", notice)
        for page in (b"<h2>License</h2><p>All rights reserved.</p>",
                     ("<script>License " + UCI_LICENSE_DECLARATION + "</script>").encode()):
            with self.assertRaisesMessage(ValueError, "license declaration changed"):
                uci_license_notice("numeric-iris", page, "https://archive.ics.uci.edu/dataset/53/iris")

    def test_all_committed_manifests_and_notices_match_catalog_pins(self):
        catalog = DatasetBankCatalog.load_from_file()
        sources = [
            s for s in catalog.qualified_sources() if s.acquisition.connector == http.CONNECTOR
        ]
        self.assertEqual(len(sources), 13)
        self.assertEqual(sum(s.record_count for s in sources), 320)
        for source in sources:
            with self.subTest(source=source.id):
                catalog.assert_acquirable(source.id)
                manifest = http.load_manifest(source)
                self.assertEqual(source.record_count, len(manifest["records"]))
                for notice in manifest["licenses"]:
                    raw = (http.CATALOG_ROOT / "notices" / notice["archive_name"]).read_bytes()
                    self.assertEqual(http.digest(raw), notice["sha256"])
                    self.assertEqual(len(raw), notice["size"])


@override_settings(ALLOWED_HOSTS=["testserver"])
class HttpPublicationTests(TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        override = override_settings(
            MODELANVIL={
                **settings.MODELANVIL,
                "artifact_backend": "filesystem",
                "artifact_root": str(self.root / "artifacts"),
            }
        )
        override.enable()
        self.addCleanup(override.disable)
        patcher = patch.object(http, "CATALOG_ROOT", self.root / "catalog")
        patcher.start()
        self.addCleanup(patcher.stop)
        (http.CATALOG_ROOT / "notices").mkdir(parents=True)
        self.tenant = Tenant.objects.create(slug="http-bank", name="HTTP bank")
        self.other = Tenant.objects.create(slug="other-http-bank", name="Other")
        pool = WorkerPool.objects.create(
            tenant_id=self.tenant.pk, name="dataset-acquisition", queue_name="bank-acquisition"
        )
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.pk,
            pool=pool,
            name="http-worker",
            slots=1,
            capabilities={"dataset_acquisition": True},
        )
        self.client = APIClient()
        secret, digest = generate_api_key()
        ApiKey.objects.create(
            tenant=self.tenant, name="engineer", role=Role.ENGINEER, secret_hash=digest
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        secret, digest = generate_api_key()
        ApiKey.objects.create(
            tenant=self.other, name="viewer", role=Role.VIEWER, secret_hash=digest
        )
        self.other_auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}

    def fixture(self, source_id="numeric-iris"):
        values = [
            {
                "sepal_length": float(i + 1),
                "sepal_width": 2.0,
                "petal_length": 3.0,
                "petal_width": 1.0,
                "species": "Iris-setosa",
            }
            for i in range(4)
        ]
        if source_id == "image-clevr":
            values = [
                {
                    "image_hex": (b"\x89PNG\r\n\x1a\n" + bytes([i])).hex(),
                    "questions": [{"image_index": i, "question": "What shape?", "answer": "cube"}],
                }
                for i in range(4)
            ]
        if source_id in TEXT_SAMPLES:
            values = [{**TEXT_SAMPLES[source_id], "fixture_index": i} for i in range(4)]
        rows = [http.canonical_json(value) for value in values]
        raw = b"".join(rows)
        self.upstream = RangeTransport(raw)
        records, start = [], 0
        for i, row in enumerate(rows):
            records.append(
                {
                    "path": f"row-{i}",
                    "size": len(row),
                    "sha256": http.digest(row),
                    "blob_sha1": git_blob_digest(row),
                    "source_group_id": f"group-{i}",
                    "metadata": {"upstream_split": "train"},
                    "reader": {
                        "kind": "json_slice",
                        "container": "data",
                        "start": start,
                        "length": len(row),
                    },
                }
            )
            start += len(row)
        notice = b"CC BY 4.0 fixture notice"
        (http.CATALOG_ROOT / "notices" / "license.txt").write_bytes(notice)
        manifest = {
            "schema_version": "1.0",
            "source_id": source_id,
            "upstream": {},
            "containers": {"data": container(raw)},
            "records": records,
            "licenses": [
                {
                    "path": "notice/license",
                    "archive_name": "license.txt",
                    "upstream_url": "https://example.org/license",
                    "size": len(notice),
                    "sha256": http.digest(notice),
                    "blob_sha1": git_blob_digest(notice),
                }
            ],
        }
        (http.CATALOG_ROOT / (source_id + ".json")).write_bytes(http.canonical_json(manifest))
        path = Path(__file__).resolve().parents[3] / "catalog/dataset-presets.json"
        data = json.loads(path.read_text())
        source = next(s for s in data["sources"] if s["id"] == source_id)
        source["acquisition"].update(
            pinned_revision=http.digest(http.canonical_json(manifest)),
            qualified_revisions=[http.digest(http.canonical_json(manifest))],
            record_limit=4,
            record_limit_max=4,
            include_patterns=[r["path"] for r in records],
            license_paths=["notice/license"],
        )
        self.catalog = DatasetBankCatalog.from_dict(data)
        self.source_id = source_id
        return rows

    def launch(self):
        return launch_acquisition(
            tenant_id=self.tenant.pk,
            source_id=self.source_id,
            catalog=self.catalog,
            transport=self.upstream,
            project_policy={"allow_share_alike": True},
        )

    def work(self):
        descriptor = claim_job(self.worker)
        with (
            patch.object(DatasetBankCatalog, "load_from_file", return_value=self.catalog),
            patch("modelanvil.data.bank.acquisition.https_transport", self.upstream),
        ):
            return execute_claim(self.worker, descriptor, bank_acquisition_executor)

    def test_numeric_preview_publication_download_and_tenant_isolation(self):
        rows = self.fixture()
        preview = preview_samples(self.catalog.get_source(self.source_id), transport=self.upstream)
        self.assertTrue(preview)
        result = self.launch()
        self.assertEqual(self.work()["status"], "succeeded")
        snapshot = SourceSnapshot.all_objects.get(snapshot_id=result.snapshot.snapshot_id)
        self.assertEqual(snapshot.state, "ready")
        self.assertEqual(snapshot.item_count, 4)
        self.assertEqual(
            Dataset.all_objects.get(tenant_id=self.tenant.pk).current_revision.state, "published"
        )
        artifact = Artifact.all_objects.get(
            tenant_id=self.tenant.pk, metadata__kind="dataset_bank_acquisition"
        )
        downloaded = self.client.get(
            f"/api/v1/artifacts/{artifact.artifact_id}/download/", **self.auth
        )
        self.assertEqual(downloaded.status_code, 200)
        envelopes = [
            json.loads(line) for line in b"".join(downloaded.streaming_content).splitlines()
        ]
        self.assertEqual(
            {http.canonical_json(e["blocks"][0]["value"]) for e in envelopes}, set(rows)
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/artifacts/{artifact.artifact_id}/download/", **self.other_auth
            ).status_code,
            404,
        )

    def test_new_text_sources_preview_publish_and_download_original_fields(self):
        for source_id in TEXT_SAMPLES:
            with self.subTest(source=source_id):
                rows = self.fixture(source_id)
                previews = preview_samples(self.catalog.get_source(source_id), transport=self.upstream)
                self.assertTrue(previews)
                launched = self.launch()
                self.assertEqual(self.work()["status"], "succeeded")
                launched.snapshot.refresh_from_db()
                self.assertEqual(launched.snapshot.state, "ready")
                self.assertEqual(launched.snapshot.item_count, 4)
                artifact = Artifact.all_objects.get(
                    tenant_id=self.tenant.pk, metadata__kind="dataset_bank_acquisition",
                    metadata__source_id=source_id,
                )
                response = self.client.get(f"/api/v1/artifacts/{artifact.artifact_id}/download/", **self.auth)
                self.assertEqual(response.status_code, 200)
                envelopes = [json.loads(line) for line in b"".join(response.streaming_content).splitlines()]
                self.assertEqual({http.canonical_json(e["blocks"][0]["value"]) for e in envelopes}, set(rows))
                self.assertTrue(all(e["metadata"]["upstream_split"] == "train" for e in envelopes))

    def test_media_bytes_are_committed_downloadable_and_linked(self):
        self.fixture("image-clevr")
        self.launch()
        self.assertEqual(self.work()["status"], "succeeded")
        media = list(
            Artifact.all_objects.filter(
                tenant_id=self.tenant.pk, metadata__kind="dataset_bank_media"
            )
        )
        self.assertEqual(len(media), 4)
        self.assertEqual(
            LineageEdge.all_objects.filter(tenant_id=self.tenant.pk, relation="bank_media").count(),
            4,
        )
        for artifact in media:
            self.assertEqual(artifact.state, "committed")
            downloaded = self.client.get(
                f"/api/v1/artifacts/{artifact.artifact_id}/download/", **self.auth
            )
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded["Content-Type"], "image/png")
            self.assertEqual(http.digest(b"".join(downloaded.streaming_content)), artifact.sha256)

    def test_digest_failure_does_not_publish_and_can_resume(self):
        self.fixture()
        result = self.launch()
        self.upstream.corrupt = True
        self.assertEqual(self.work()["status"], "failed")
        snapshot = SourceSnapshot.all_objects.get(snapshot_id=result.snapshot.snapshot_id)
        self.assertEqual(snapshot.state, "failed")
        self.assertFalse(Dataset.all_objects.filter(tenant_id=self.tenant.pk).exists())
        self.upstream.corrupt = False
        with patch.object(DatasetBankCatalog, "load_from_file", return_value=self.catalog):
            resume_acquisition(snapshot)
        self.assertEqual(self.work()["status"], "succeeded")

    def test_modified_manifest_is_refused_before_job_admission(self):
        self.fixture()
        path = http.CATALOG_ROOT / (self.source_id + ".json")
        data = json.loads(path.read_text())
        data["records"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(data))
        with self.assertRaisesMessage(ValidationError, "manifest"):
            self.launch()
