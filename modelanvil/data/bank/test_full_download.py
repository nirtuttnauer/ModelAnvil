"""Complete releases: content fencing, resumable parts, and scoped streaming exports."""

import json
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact, TransferSession
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.data.bank import full_download as full
from modelanvil.data.bank.acquisition import (
    AcquisitionCancelled,
    UpstreamError,
    access_acquisition,
    acquisition_state,
    execute_acquisition,
    launch_acquisition,
    resume_acquisition,
)
from modelanvil.data.bank.catalog import DatasetBankCatalog
from modelanvil.data.bank.http_snapshot import SnapshotError, canonical_json, digest
from modelanvil.data.bank.test_acquisition import CancellingContext
from modelanvil.data.bank.test_http_snapshot import RangeTransport
from modelanvil.data.models import SourceSnapshot
from modelanvil.identity.models import (
    ApiKey,
    Project,
    Role,
    Team,
    Tenant,
    generate_api_key,
)
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Job, Worker, WorkerPool, claim_job


@override_settings(ALLOWED_HOSTS=["testserver"])
class FullReleaseTests(TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        config = override_settings(
            MODELANVIL={
                **settings.MODELANVIL,
                "artifact_root": str(self.root / "artifacts"),
                "artifact_backend": "filesystem",
            }
        )
        config.enable()
        self.addCleanup(config.disable)
        self.tenant = Tenant.objects.create(slug="full-release", name="Full release")
        self.pool = WorkerPool.objects.create(
            tenant_id=self.tenant.pk, name="dataset-acquisition", queue_name="full"
        )
        Worker.objects.create(
            tenant_id=self.tenant.pk,
            pool=self.pool,
            name="full-worker",
            slots=1,
            capabilities={"dataset_acquisition": True},
        )
        self.catalog = DatasetBankCatalog.load_from_file()
        source = self.catalog.get_source("numeric-iris")
        self.raw = b"complete source bytes, including the end"
        self.transport = RangeTransport(self.raw)
        notice = b"Publisher notice retained."
        (self.root / "license.txt").write_bytes(notice)
        self.manifest = {
            "source_id": source.id,
            "files": [
                {
                    "path": "complete.zip",
                    "url": "https://archive.ics.uci.edu/complete.zip",
                    "size": len(self.raw),
                    "sha256": digest(self.raw),
                    "format": "zip",
                    "chunks": [
                        {
                            "start": i,
                            "length": len(self.raw[i : i + 10]),
                            "sha256": digest(self.raw[i : i + 10]),
                        }
                        for i in range(0, len(self.raw), 10)
                    ],
                    "validation": {"all_content_read": True},
                }
            ],
            "licenses": [
                {
                    "archive_name": "license.txt",
                    "sha256": digest(notice),
                    "size": len(notice),
                }
            ],
        }
        self.write_manifest()
        self.catalog._sources[source.id] = replace(
            source,
            full_acquisition=replace(
                source.acquisition,
                connector=full.CONNECTOR,
                pinned_revision=self.pin,
                qualified_revisions=[self.pin],
                record_limit=1,
                record_limit_max=1,
                measured_selected_bytes=len(self.raw),
                measured_selected_records=1,
            ),
        )
        for target, value in [("MANIFEST_ROOT", self.root), ("NOTICE_ROOT", self.root)]:
            p = patch.object(full, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch(
            "modelanvil.data.bank.acquisition.DatasetBankCatalog.load_from_file",
            return_value=self.catalog,
        )
        p.start()
        self.addCleanup(p.stop)
        p = patch("modelanvil.data.bank.acquisition.https_transport", self.transport)
        p.start()
        self.addCleanup(p.stop)

    def write_manifest(self):
        self.pin = digest(canonical_json(self.manifest))
        (self.root / "numeric-iris.json").write_text(json.dumps(self.manifest))

    def launch(self, **kwargs):
        return launch_acquisition(
            tenant_id=self.tenant.pk,
            source_id="numeric-iris",
            catalog=self.catalog,
            download_scope="full",
            **kwargs,
        )

    def execute(self, launch, context=None):
        return execute_acquisition(
            {"job_id": str(launch.job.job_id), "payload": launch.job.payload},
            context or CancellingContext(),
        )

    def test_every_byte_is_committed_and_streamed_with_manifest(self):
        launch = self.launch()
        self.execute(launch)
        launch.snapshot.refresh_from_db()
        state = acquisition_state(launch.snapshot)
        self.assertEqual(state["state"], "ready")
        self.assertEqual(state["download_scope"], "full")
        self.assertEqual(state["transferred_bytes"], len(self.raw))
        self.assertIsNone(state["revision_id"])
        self.assertEqual(len(state["source_files"]), 1)
        self.assertTrue(state["manifest_artifact_id"])
        artifact = Artifact.all_objects.get(
            artifact_id=state["source_files"][0]["artifact_id"]
        )
        with artifact_storage_backend().open(
            self.tenant.pk, artifact.object_key
        ) as stream:
            self.assertEqual(stream.read(), self.raw)
        key, secret_hash = generate_api_key()
        ApiKey.objects.create(
            tenant_id=self.tenant.pk,
            name="download",
            secret_hash=secret_hash,
            role=Role.VIEWER,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")
        response = client.get(f"/api/v1/artifacts/{artifact.artifact_id}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.raw)
        other = Tenant.objects.create(slug="foreign-full", name="Other")
        with self.assertRaises(PermissionDenied):
            access_acquisition(
                launch.snapshot.snapshot_id, requesting_tenant_id=other.pk
            )

    def test_cancel_resume_rechecks_and_reuses_parts(self):
        launch = self.launch()
        with self.assertRaises(AcquisitionCancelled):
            self.execute(launch, CancellingContext(cancel_after=2))
        launch.snapshot.refresh_from_db()
        state = acquisition_state(launch.snapshot)
        self.assertEqual(state["verified_records"], 0)
        self.assertEqual(state["transferred_bytes"], 10)
        self.assertFalse(state["source_files"])
        self.assertFalse(Artifact.all_objects.filter(state="committed").exists())
        launch.job.status = Job.Status.CANCELLED
        launch.job.save()
        transfer = TransferSession.all_objects.get()
        transfer.expires_at = timezone.now()
        transfer.save()
        resumed = resume_acquisition(launch.snapshot)
        self.execute(resumed)
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, SourceSnapshot.State.READY)
        self.assertEqual(self.transport.calls, len(self.manifest["files"][0]["chunks"]))

    def test_tampered_upstream_never_publishes(self):
        launch = self.launch()
        self.transport.corrupt = True
        with self.assertRaisesMessage(UpstreamError, "digest"):
            self.execute(launch)
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, "failed")
        self.assertFalse(Artifact.all_objects.filter(state="committed").exists())

    def test_missing_manifest_partial_scope_bad_revision_and_quota_refuse_before_network(
        self,
    ):
        for kwargs in (
            {"record_limit": 2},
            {"source_revision": "wrong"},
            {"project_policy": {"max_storage_quota_bytes": len(self.raw)}},
            {"project_policy": {"max_storage_quota_bytes": True}},
        ):
            with self.assertRaises((SnapshotError, ValidationError)):
                self.launch(**kwargs)
        (self.root / "numeric-iris.json").unlink()
        with self.assertRaises(ValidationError):
            self.launch()
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(Job.all_objects.count(), 0)

    def test_unqualified_full_source_and_tampered_notice_fail_closed(self):
        with self.assertRaises(ValidationError):
            self.catalog.source_for_full_download("svg-lucide")
        (self.root / "license.txt").write_bytes(b"Tampered")
        with self.assertRaisesMessage(ValidationError, "notice"):
            self.launch()
        self.assertEqual(self.transport.calls, 0)

    def test_full_file_budget_and_project_scope_are_preserved(self):
        team = Team.objects.create(tenant_id=self.tenant.pk, name="Team", slug="team")
        project = Project.objects.create(
            tenant_id=self.tenant.pk, team=team, name="Project A", slug="project-a"
        )
        other = Project.objects.create(
            tenant_id=self.tenant.pk, team=team, name="Project B", slug="project-b"
        )
        policy = BudgetPolicy.objects.create(
            tenant_id=self.tenant.pk,
            name="Files",
            period="monthly",
            unit="bank_acquisition_records",
            limit_amount=Decimal(10),
        )
        launch = self.launch(
            project_id=project.pk,
            budget_policy_id=policy.policy_id,
            estimated_amount=Decimal(1),
        )
        self.execute(launch)
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.project_id, project.pk)
        state = acquisition_state(launch.snapshot)
        for file in state["source_files"]:
            artifact = Artifact.all_objects.get(artifact_id=file["artifact_id"])
            self.assertEqual(artifact.project_id, project.pk)
        reservation = BudgetReservation.all_objects.get(job_id=launch.job.job_id)
        self.assertEqual(reservation.settled_amount, Decimal(1))
        event = UsageEvent.all_objects.get(reservation=reservation)
        self.assertEqual(
            event.detail["quantity_basis"], "verified complete source files"
        )
        with self.assertRaises(PermissionDenied):
            access_acquisition(
                launch.snapshot.snapshot_id,
                requesting_tenant_id=self.tenant.pk,
                project_id=other.pk,
            )

    def test_real_claimed_worker_completes_full_release(self):
        launch = self.launch()
        worker = Worker.all_objects.get(tenant_id=self.tenant.pk)
        descriptor = claim_job(worker, launch.job)
        result = execute_claim(worker, descriptor, execute_acquisition)
        self.assertTrue(result["committed"])
        self.assertEqual(result["status"], "succeeded")
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, "ready")

    def test_saved_part_corruption_refuses_resume(self):
        launch = self.launch()
        with self.assertRaises(AcquisitionCancelled):
            self.execute(launch, CancellingContext(cancel_after=2))
        transfer = TransferSession.all_objects.get()
        key = transfer.part_manifest["1"]["object_key"]
        backend = artifact_storage_backend()
        backend._path(self.tenant.pk, key, create_parent=False).write_bytes(
            b"corrupted!"
        )
        launch.job.status = Job.Status.CANCELLED
        launch.job.save()
        launch.snapshot.refresh_from_db()
        resumed = resume_acquisition(launch.snapshot)
        with self.assertRaisesMessage(ValueError, "Stored part"):
            self.execute(resumed)
        self.assertFalse(Artifact.all_objects.filter(state="committed").exists())

    def test_qualified_mirror_falls_back_only_on_transport_failure(self):
        file = self.manifest["files"][0]
        file["mirrors"] = ["https://openslr.elda.org/resources/141/fixture.zip"]
        self.write_manifest()
        source = self.catalog.get_source("numeric-iris")
        self.catalog._sources[source.id] = replace(
            source,
            full_acquisition=replace(
                source.full_acquisition,
                pinned_revision=self.pin,
                qualified_revisions=[self.pin],
            ),
        )
        calls = []

        def transport(url, headers):
            calls.append(url)
            if "elda.org" in url:
                raise UpstreamError("Mirror unreachable.")
            return self.transport(url, headers)

        launch = self.launch()
        with patch("modelanvil.data.bank.acquisition.https_transport", transport):
            self.execute(launch)
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, "ready")
        self.assertEqual(len(calls), 2 * len(file["chunks"]))

    def test_forged_foreign_job_cannot_mutate_snapshot_or_download_cache(self):
        launch = self.launch()
        other = Tenant.objects.create(slug="foreign-worker", name="Foreign worker")
        pool = WorkerPool.objects.create(
            tenant_id=other.pk, name="foreign", queue_name="foreign"
        )
        forged = Job.all_objects.create(
            tenant_id=other.pk, pool=pool, name="forged", payload=launch.job.payload
        )
        with self.assertRaises(UpstreamError):
            execute_acquisition(
                {"job_id": str(forged.job_id), "payload": forged.payload},
                CancellingContext(),
            )
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, "ingesting")
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(Artifact.all_objects.count(), 0)

    def test_corrupted_complete_cached_file_cannot_publish_on_resume(self):
        class CancelAfterFileCommit:
            def heartbeat(self, progress=None):
                return not Artifact.all_objects.filter(state="committed").exists()

        launch = self.launch()
        with self.assertRaises(AcquisitionCancelled):
            self.execute(launch, CancelAfterFileCommit())
        artifact = Artifact.all_objects.get(state="committed")
        backend = artifact_storage_backend()
        backend._path(
            self.tenant.pk, artifact.object_key, create_parent=False
        ).write_bytes(b"corrupted complete file")
        launch.job.status = Job.Status.CANCELLED
        launch.job.save()
        launch.snapshot.refresh_from_db()
        resumed = resume_acquisition(launch.snapshot)
        with self.assertRaisesMessage(UpstreamError, "Cached complete-release"):
            self.execute(resumed)
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, "failed")
        self.assertFalse(acquisition_state(launch.snapshot)["source_files"])


class QualificationParserTests(TestCase):
    def test_full_json_array_checks_every_record_and_rejects_missing_separators(self):
        import io

        from scripts.qualify_bank_full_releases import json_array, safe

        self.assertEqual(
            json_array(
                io.StringIO(
                    '[{"system":"first","chat":"a"},{"system":"last","chat":"b"}]'
                )
            ),
            2,
        )
        for body in (
            '[{"system":"first","chat":"a"}{"system":"last","chat":"b"}]',
            '[{"system":"first","chat":"a"},]',
            '[{"system":"first","chat":1}]',
        ):
            with self.assertRaises(AssertionError):
                json_array(io.StringIO(body))
        for path in (
            "/outside",
            "../outside",
            "folder/../../outside",
            "folder\\outside",
        ):
            with self.assertRaises(AssertionError):
                safe(path)


class CommittedFullQualificationTests(TestCase):
    def test_every_admitted_full_release_has_complete_pinned_inventory_and_notices(
        self,
    ):
        catalog = DatasetBankCatalog.load_from_file()
        for original in catalog._sources.values():
            if not original.full_acquisition.qualified:
                continue
            source = catalog.source_for_full_download(original.id)
            manifest = full.load_manifest(source)
            self.assertEqual(manifest["download_scope"], "full")
            self.assertFalse(manifest["training_recipe_qualified"])
            self.assertEqual(len(manifest["files"]), source.acquisition.record_limit)
            self.assertEqual(
                sum(f["size"] for f in manifest["files"]), source.size_bytes
            )
            for file in manifest["files"]:
                self.assertTrue(file["validation"]["whole_file_sha256_verified"])
                if file.get("publisher_sha256"):
                    self.assertEqual(file["sha256"], file["publisher_sha256"])
            self.assertTrue(full.verify_notices(manifest))
