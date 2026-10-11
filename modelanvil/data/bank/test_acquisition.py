"""Queued, resumable, digest-verified Dataset Bank acquisition (TASK-9).

The upstream bytes in these tests are a local fixture served through an
injected transport; they are not fetched from GitHub. The only live evidence
for the qualified source is recorded in ``catalog/dataset-presets.json`` and
in ``docs/engineering/verification/``.
"""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.data.bank.acquisition import (
    AcquisitionCapacityError,
    JOB_TYPE,
    RecordStore,
    access_acquisition,
    acquisition_state,
    bank_acquisition_executor,
    cancel_acquisition,
    git_blob_digest,
    launch_acquisition,
    preview_samples,
    execute_acquisition,
    resume_acquisition,
    select_records,
    UpstreamRecord,
)
from modelanvil.data.bank.catalog import DatasetBankCatalog
from modelanvil.data.models import SourceSnapshot
from modelanvil.identity.models import Tenant
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import (
    Job,
    JobAttempt,
    Worker,
    WorkerPool,
    claim_job,
    reconcile_expired_leases,
)

PINNED = "0" * 39 + "1"
LICENSE_BYTES = b"ISC License\n\nCopyright (c) 2026 Fixture Contributors\n"
ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
    '<path d="M{i} 12h14"/></svg>'
)


class FakeUpstream:
    """Injected transport over a synthetic git tree at the pinned revision."""

    def __init__(self, *, record_count: int = 12, corrupt: set[str] | None = None) -> None:
        self.blobs: dict[str, bytes] = {}
        self.corrupt = corrupt or set()
        for index in range(record_count):
            self.blobs[f"icons/icon-{index:02d}.svg"] = ICON.format(i=index).encode("utf-8")
        self.blobs["LICENSE"] = LICENSE_BYTES
        self.fetches: list[str] = []

    def add(self, path: str, payload: bytes) -> None:
        self.blobs[path] = payload

    def __call__(self, url: str, headers: dict[str, str]) -> "tuple[int, bytes, dict[str, str]]":
        self.fetches.append(url)
        if "/git/ref/heads/" in url:
            body = {"object": {"type": "commit", "sha": PINNED}}
            return 200, json.dumps(body).encode("utf-8"), {}
        if "/git/trees/" in url:
            entries = [
                {"path": path, "type": "blob", "sha": git_blob_digest(payload), "size": len(payload)}
                for path, payload in sorted(self.blobs.items())
                if path == "LICENSE" or path.endswith(".svg")
            ]
            return 200, json.dumps({"truncated": False, "tree": entries}).encode("utf-8"), {}
        path = url.split("/", 6)[-1]
        payload = self.blobs.get(path)
        if payload is None:
            return 404, b"not found", {}
        if path in self.corrupt:
            return 200, payload + b"<!-- tampered -->", {}
        return 200, payload, {}


class CancellingContext:
    """Execution context that reports cancellation after ``cancel_after`` heartbeats."""

    def __init__(self, cancel_after: int | None = None) -> None:
        self.beats = 0
        self.cancel_after = cancel_after

    def heartbeat(self, progress=None) -> bool:
        self.beats += 1
        if self.cancel_after is not None and self.beats > self.cancel_after:
            return False
        return True


class CrashingContext:
    """Execution context that simulates a worker process dying mid-transfer."""

    def __init__(self, crash_after: int) -> None:
        self.beats = 0
        self.crash_after = crash_after

    def heartbeat(self, progress=None) -> bool:
        self.beats += 1
        if self.beats > self.crash_after:
            raise RuntimeError("worker process lost")
        return True


@override_settings(ALLOWED_HOSTS=["testserver"])
class BankAcquisitionTests(TestCase):
    def setUp(self) -> None:
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={
            **settings.MODELANVIL, "artifact_backend": "filesystem", "artifact_root": root.name,
        })
        override.enable()
        self.addCleanup(override.disable)

        self.tenant = Tenant.objects.create(slug="bank-acquisition", name="Bank acquisition")
        self.other_tenant = Tenant.objects.create(slug="bank-other", name="Other org")
        self.pool = WorkerPool.objects.create(
            tenant_id=self.tenant.pk, name="dataset-acquisition", queue_name="bank-acquisition")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.pk, pool=self.pool, name="acquisition-worker",
            slots=2, capabilities={"dataset_acquisition": True},
        )
        self.catalog = DatasetBankCatalog.load_from_file()
        self.upstream = FakeUpstream()

    def launch(self, **kwargs):
        with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
            return launch_acquisition(
                tenant_id=self.tenant.pk, source_id="svg-lucide",
                catalog=self.catalog, transport=self.upstream, **kwargs,
            )

    def run_worker(self, context=None):
        descriptor = claim_job(self.worker)
        if descriptor is None:
            return {"claimed": False}
        with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
            if context is not None:
                with self.assertRaises(Exception):
                    execute_acquisition(descriptor, context)
                return {"claimed": True, "stopped": True}
            outcome = execute_claim(self.worker, descriptor, bank_acquisition_executor)
        self.worker.refresh_from_db()
        return outcome

    def catalog_with_revisions(self, *revisions: str) -> DatasetBankCatalog:
        data = json.loads(json.dumps(self.catalog_data()))
        for source in data["sources"]:
            if source["id"] != "svg-lucide":
                continue
            source["acquisition"]["pinned_revision"] = revisions[-1]
            source["acquisition"]["qualified_revisions"] = list(revisions)
        return DatasetBankCatalog.from_dict(data)

    def catalog_data(self) -> dict:
        path = Path(__file__).resolve().parents[3] / "catalog" / "dataset-presets.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # -- admission -----------------------------------------------------------
    def test_launch_requires_registered_acquisition_worker(self):
        self.worker.delete()
        with self.assertRaises(AcquisitionCapacityError):
            self.launch()
        self.assertEqual(SourceSnapshot.all_objects.count(), 0)
        self.assertEqual(Job.all_objects.count(), 0)

    def test_launch_refuses_unqualified_source(self):
        with self.assertRaises(ValidationError) as ctx:
            with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
                launch_acquisition(
                    tenant_id=self.tenant.pk, source_id="svg-tabler",
                    catalog=self.catalog, transport=self.upstream,
                )
        self.assertIn("not qualified", str(ctx.exception))
        self.assertEqual(Job.all_objects.count(), 0)

    def test_launch_refuses_unqualified_upstream_revision(self):
        with self.assertRaises(ValidationError) as ctx:
            self.launch(source_revision="f" * 40)
        self.assertIn("not qualified", str(ctx.exception))

    def test_launch_refuses_scope_beyond_the_qualified_bound(self):
        with self.assertRaises(ValidationError) as ctx:
            self.launch(record_limit=100000)
        self.assertIn("exceeds the qualified bound", str(ctx.exception))

    def test_launch_queues_a_job_and_persists_the_plan(self):
        launch = self.launch(record_limit=6)
        self.assertTrue(launch.created)
        self.assertEqual(launch.snapshot.state, SourceSnapshot.State.INGESTING)
        self.assertEqual(launch.job.status, Job.Status.QUEUED)
        self.assertEqual(launch.job.requirements, {"dataset_acquisition": True, "slots": 1})
        plan = launch.snapshot.detail["acquisition"]
        self.assertEqual(len(plan["records"]), 6)
        self.assertEqual(plan["source_revision"], self.catalog.get_source("svg-lucide").acquisition.pinned_revision)
        self.assertEqual([record["path"] for record in plan["license_records"]], ["LICENSE"])
        self.assertEqual(plan["verified"], {})

    def test_launch_requires_budget_policy_when_the_tenant_enables_one(self):
        policy = BudgetPolicy.objects.create(
            tenant_id=self.tenant.pk, name="acquisition-budget", period="monthly",
            unit="bank_acquisition_records", limit_amount=Decimal("10"),
        )
        with self.assertRaises(ValidationError) as ctx:
            self.launch(record_limit=4)
        self.assertIn("budget_policy_id", str(ctx.exception))

        with self.assertRaises(ValidationError):
            self.launch(record_limit=4, budget_policy_id=policy.policy_id, estimated_amount=Decimal("99"))
        self.assertEqual(Job.all_objects.count(), 0)

        launch = self.launch(record_limit=4, budget_policy_id=policy.policy_id, estimated_amount=Decimal("4"))
        reservation = BudgetReservation.all_objects.get(job_id=launch.job.job_id)
        self.assertEqual(reservation.state, BudgetReservation.State.RESERVED)
        self.assertEqual(reservation.estimated_amount, Decimal("4"))

    def test_launch_is_idempotent_while_a_job_is_queued(self):
        first = self.launch(record_limit=4)
        second = self.launch(record_limit=4)
        self.assertFalse(second.created)
        self.assertEqual(first.job.job_id, second.job.job_id)
        self.assertEqual(Job.all_objects.count(), 1)

    # -- execution -----------------------------------------------------------
    def test_worker_publishes_a_verified_immutable_version(self):
        policy = BudgetPolicy.objects.create(
            tenant_id=self.tenant.pk, name="acquisition-budget", period="monthly",
            unit="bank_acquisition_records", limit_amount=Decimal("100"),
        )
        launch = self.launch(record_limit=8, budget_policy_id=policy.policy_id, estimated_amount=Decimal("8"))
        outcome = self.run_worker()
        self.assertEqual(outcome["status"], "succeeded")
        launch.job.refresh_from_db()
        self.assertEqual(launch.job.status, Job.Status.SUCCEEDED)

        snapshot = SourceSnapshot.all_objects.get(pk=launch.snapshot.pk)
        self.assertEqual(snapshot.state, SourceSnapshot.State.READY)
        self.assertEqual(snapshot.item_count, 8)
        self.assertEqual(len(snapshot.manifest_digest), 64)

        state = acquisition_state(snapshot)
        self.assertEqual(state["verified_records"], 8)
        self.assertEqual(state["row_count"], 8)
        self.assertEqual(state["job"]["status"], Job.Status.SUCCEEDED)

        dataset = Dataset.all_objects.get(dataset_id=state["dataset_id"])
        revision = DatasetRevision.all_objects.get(revision_id=state["revision_id"])
        self.assertEqual(revision.revision_no, 1)
        self.assertEqual(revision.state, DatasetRevision.State.PUBLISHED)
        self.assertEqual(dataset.current_revision_id, revision.pk)

        # Attribution and transformations survive publication.
        attribution = dataset.metadata["latest_attribution"]
        self.assertEqual(attribution["source_revision"], self.catalog.get_source("svg-lucide").acquisition.pinned_revision)
        self.assertEqual(attribution["artifact_sha256"], revision.metadata["input_sha256"])
        self.assertEqual(attribution["license_notices"][0]["path"], "LICENSE")
        self.assertTrue(attribution["license_notices"][0]["digest_verified"])
        self.assertIn("ISC License", attribution["license_notices"][0]["text"])
        steps = {entry["step"] for entry in dataset.metadata["transformations"]}
        self.assertIn("git_blob_digest_verification", steps)
        self.assertIn("protected_split_enforcement", steps)

        # Per-sample provenance points at the real upstream records.
        with artifact_storage_backend().open(dataset.tenant_id, str(revision.manifest_artifact.object_key)) as stream:
            manifest = json.loads(stream.read())
        rows = manifest["rows"]
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(row["provenance"]["source_snapshot_ref"], str(snapshot.snapshot_id))
            self.assertTrue(row["provenance"]["source_record_key"].startswith("icons/"))
            self.assertEqual(len(row["provenance"]["content_sha256"]), 64)
            self.assertIn("attribution_notice", row["metadata"])

        # Concept groups never straddle splits.
        group_splits = {}
        for split, ids in manifest["split_manifest"].items():
            for sample_id in ids:
                row = next(item for item in rows if item["sample_id"] == sample_id)
                group_splits.setdefault(row["source_group_id"], set()).add(split)
        self.assertTrue(all(len(splits) == 1 for splits in group_splits.values()))

        # Budget settled against verified records with an explicit quantity basis.
        reservation = BudgetReservation.all_objects.get(job_id=launch.job.job_id)
        self.assertEqual(reservation.state, BudgetReservation.State.SETTLED)
        self.assertEqual(reservation.settled_amount, Decimal("8"))
        usage = UsageEvent.all_objects.get(provider_event_key=f"bank-acquisition-{launch.job.job_id}")
        self.assertEqual(usage.detail["unit_kind"], "bank_acquisition_verified_records")

    def test_crashed_transfer_resumes_from_persisted_state_without_refetching(self):
        launch = self.launch(record_limit=10)
        first = self.run_worker(context=CrashingContext(crash_after=3))

        snapshot = SourceSnapshot.all_objects.get(pk=launch.snapshot.pk)
        self.assertEqual(snapshot.state, SourceSnapshot.State.INGESTING)
        verified_after_crash = acquisition_state(snapshot)["verified_records"]
        self.assertGreater(verified_after_crash, 0)
        self.assertLess(verified_after_crash, 10)
        self.assertEqual(Dataset.all_objects.count(), 0)
        self.assertEqual(DatasetRevision.all_objects.count(), 0)
        fetches_after_crash = len([url for url in self.upstream.fetches if url.endswith(".svg")])

        # Lease reconciliation re-queues the interrupted transfer.
        JobAttempt.all_objects.filter(job_id=launch.job.pk).update(
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=30)
        )
        self.assertEqual(reconcile_expired_leases(), 1)
        launch.job.refresh_from_db()
        self.assertEqual(launch.job.status, Job.Status.QUEUED)

        outcome = self.run_worker()
        self.assertEqual(outcome["status"], "succeeded")

        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, SourceSnapshot.State.READY)
        state = acquisition_state(snapshot)
        self.assertEqual(state["verified_records"], 10)
        self.assertEqual(state["row_count"], 10)
        fetches_on_resume = len([url for url in self.upstream.fetches if url.endswith(".svg")]) - fetches_after_crash
        self.assertEqual(
            fetches_on_resume, 10 - verified_after_crash,
            "resumption must not re-fetch already verified upstream records",
        )

    def test_cancelled_transfer_is_not_resumed_by_reconciliation(self):
        launch = self.launch(record_limit=10)
        self.run_worker(context=CrashingContext(crash_after=3))
        snapshot = SourceSnapshot.all_objects.get(pk=launch.snapshot.pk)
        cancel_acquisition(snapshot)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, SourceSnapshot.State.CANCELLED)
        JobAttempt.all_objects.filter(job_id=launch.job.pk).update(
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=30)
        )
        reconcile_expired_leases()
        self.assertEqual(claim_job(self.worker), None)

    def test_resume_requeues_a_cancelled_transfer_from_its_checkpoint(self):
        launch = self.launch(record_limit=10)
        self.run_worker(context=CrashingContext(crash_after=3))
        snapshot = SourceSnapshot.all_objects.get(pk=launch.snapshot.pk)
        verified = acquisition_state(snapshot)["verified_records"]
        JobAttempt.all_objects.filter(job_id=launch.job.pk).update(
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=30)
        )
        reconcile_expired_leases()
        cancel_acquisition(snapshot)
        snapshot.refresh_from_db()
        resumed = resume_acquisition(snapshot)
        self.assertEqual(resumed.job.status, Job.Status.QUEUED)
        self.assertEqual(resumed.job.payload["resumed_from_records"], verified)
        outcome = self.run_worker()
        self.assertEqual(outcome["status"], "succeeded")
        snapshot.refresh_from_db()
        self.assertEqual(acquisition_state(snapshot)["verified_records"], 10)

    def test_operator_cancellation_mid_transfer_interrupts_the_job(self):
        launch = self.launch(record_limit=10)
        descriptor = claim_job(self.worker)
        Job.all_objects.filter(pk=launch.job.pk).update(desired_action=Job.DesiredAction.CANCEL)
        with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
            outcome = execute_claim(self.worker, descriptor, bank_acquisition_executor)
        self.assertEqual(outcome["status"], "interrupted")
        launch.job.refresh_from_db()
        self.assertEqual(launch.job.status, Job.Status.CANCELLED)
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, SourceSnapshot.State.CANCELLED)
        self.assertEqual(Dataset.all_objects.count(), 0)

    def test_expired_worker_lease_requeues_the_transfer(self):
        launch = self.launch(record_limit=6)
        descriptor = claim_job(self.worker)
        JobAttempt.all_objects.filter(attempt_id=descriptor["attempt_id"]).update(
            lease_expires_at=timezone.now() - timezone.timedelta(seconds=30)
        )
        self.assertEqual(reconcile_expired_leases(), 1)
        launch.job.refresh_from_db()
        self.assertEqual(launch.job.status, Job.Status.QUEUED)
        self.assertEqual(launch.snapshot.state, SourceSnapshot.State.INGESTING)
        self.assertEqual(Dataset.all_objects.count(), 0)
        outcome = self.run_worker()
        self.assertEqual(outcome["status"], "succeeded")
        launch.snapshot.refresh_from_db()
        self.assertEqual(acquisition_state(launch.snapshot)["verified_records"], 6)

    def test_tampered_upstream_bytes_fail_the_transfer_and_publish_nothing(self):
        inventory = [
            UpstreamRecord(path, git_blob_digest(payload), len(payload))
            for path, payload in sorted(self.upstream.blobs.items()) if path.endswith(".svg")
        ]
        self.upstream.corrupt = {select_records(inventory, 6)[0].path}
        launch = self.launch(record_limit=6)
        outcome = self.run_worker()
        self.assertEqual(outcome["status"], "failed")
        snapshot = SourceSnapshot.all_objects.get(pk=launch.snapshot.pk)
        self.assertEqual(snapshot.state, SourceSnapshot.State.FAILED)
        self.assertTrue(acquisition_state(snapshot)["failures"])
        self.assertEqual(Dataset.all_objects.count(), 0)
        self.assertEqual(Artifact.all_objects.filter(metadata__kind="dataset_bank_acquisition").count(), 0)

    def test_cancelled_queue_never_becomes_a_ready_dataset(self):
        launch = self.launch(record_limit=6)
        result = cancel_acquisition(launch.snapshot)
        self.assertEqual(result["job_status"], Job.Status.CANCELLED)
        launch.snapshot.refresh_from_db()
        self.assertEqual(launch.snapshot.state, SourceSnapshot.State.CANCELLED)
        self.assertEqual(claim_job(self.worker), None)
        self.assertEqual(Dataset.all_objects.count(), 0)

    def test_resume_refuses_a_complete_snapshot(self):
        launch = self.launch(record_limit=4)
        self.run_worker()
        launch.snapshot.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            resume_acquisition(launch.snapshot)
        self.assertIn("already complete", str(ctx.exception))

    def test_worker_capacity_gates_the_transfer(self):
        self.worker.slots = 0
        self.worker.save(update_fields=("slots", "updated_at"))
        with self.assertRaises(AcquisitionCapacityError):
            self.launch(record_limit=4)
        self.assertEqual(Job.all_objects.count(), 0)

        # A saturated worker pool cannot claim a queued acquisition.
        self.worker.slots = 1
        self.worker.save(update_fields=("slots", "updated_at"))
        self.launch(record_limit=4)
        self.assertIsNotNone(claim_job(self.worker))
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.slots, 0)
        self.assertEqual(claim_job(self.worker), None)

    # -- isolation and revisions --------------------------------------------
    def test_cross_tenant_transfer_cache_is_refused(self):
        launch = self.launch(record_limit=4)
        with self.assertRaises(PermissionDenied):
            access_acquisition(launch.snapshot.snapshot_id, requesting_tenant_id=self.other_tenant.pk)
        with self.assertRaises(ValidationError):
            access_acquisition("22222222-2222-4222-8222-222222222222", requesting_tenant_id=self.tenant.pk)
        recovered = access_acquisition(
            launch.snapshot.snapshot_id, requesting_tenant_id=self.tenant.pk)
        self.assertEqual(recovered.snapshot_id, launch.snapshot.snapshot_id)

    def test_new_upstream_revision_publishes_a_new_version_without_overwriting(self):
        first_revision = "1" * 40
        second_revision = "2" * 40
        catalog = self.catalog_with_revisions(first_revision, second_revision)
        self.upstream.blobs["icons/extra-01.svg"] = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M1 1"/></svg>'

        with patch.object(DatasetBankCatalog, "load_from_file", staticmethod(lambda *a, **k: catalog)):
            with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
                first = launch_acquisition(
                    tenant_id=self.tenant.pk, source_id="svg-lucide", catalog=catalog,
                    source_revision=first_revision, record_limit=6, transport=self.upstream,
                )
            self.run_worker()
            self.upstream.fetches.clear()
            second = launch_acquisition(
                tenant_id=self.tenant.pk, source_id="svg-lucide", catalog=catalog,
                source_revision=second_revision, record_limit=6, transport=self.upstream,
            )
            self.run_worker()

        self.assertNotEqual(first.snapshot.snapshot_id, second.snapshot.snapshot_id)
        dataset = Dataset.all_objects.get()
        revisions = list(dataset.revisions.order_by("revision_no"))
        self.assertEqual([revision.revision_no for revision in revisions], [1, 2])
        self.assertNotEqual(
            revisions[0].metadata["input_artifact_id"], revisions[1].metadata["input_artifact_id"]
        )
        first_state = acquisition_state(SourceSnapshot.all_objects.get(pk=first.snapshot.pk))
        self.assertEqual(first_state["revision_no"], 1)
        self.assertEqual(first_state["source_revision"], first_revision)

        # The earlier version is untouched and still published.
        first_digest = revisions[0].manifest_digest
        self.assertEqual(revisions[0].state, DatasetRevision.State.PUBLISHED)
        self.assertEqual(DatasetRevision.all_objects.get(pk=revisions[0].pk).manifest_digest, first_digest)
        self.assertEqual(dataset.current_revision_id, revisions[1].pk)

        # Nothing held out by version 1 leaks into version 2.
        def manifest_of(revision):
            with artifact_storage_backend().open(
                dataset.tenant_id, str(revision.manifest_artifact.object_key)
            ) as stream:
                return json.loads(stream.read())

        first_manifest, second_manifest = manifest_of(revisions[0]), manifest_of(revisions[1])
        held = set(first_manifest["split_manifest"]["validation"]) | set(first_manifest["split_manifest"]["test"])
        if held:
            from modelanvil.data.detection import content_digest

            protected_digests = {
                content_digest(row) for row in first_manifest["rows"] if row["sample_id"] in held
            }
            second_digests = {content_digest(row) for row in second_manifest["rows"]}
            self.assertFalse(protected_digests & second_digests)
            self.assertTrue(second_manifest.get("report"))
            steps = {entry["step"]: entry["detail"] for entry in dataset.metadata["transformations"]}
            self.assertIn("were dropped from this version", steps["published_version_protection"])

    # -- preview -------------------------------------------------------------
    def test_preview_returns_real_verified_upstream_records(self):
        source = self.catalog.get_source("svg-lucide")
        samples = preview_samples(source, limit=3, transport=self.upstream)
        self.assertEqual(len(samples), 3)
        for sample in samples:
            self.assertTrue(sample["upstream_path"].startswith("icons/"))
            self.assertTrue(sample["digest_verified"])
            self.assertEqual(len(sample["content_sha256"]), 64)
            self.assertIn("<svg", sample["svg_raw"])
            self.assertEqual(sample["label_provenance"], "filename_derived")
            self.assertIn("lucide", sample["attribution_notice"].lower())
            self.assertIn(self.catalog.get_source("svg-lucide").acquisition.pinned_revision, sample["upstream_url"])

    def test_record_selection_is_deterministic_and_evenly_spaced(self):
        inventory = [UpstreamRecord(f"icons/{index:03d}.svg", "0" * 40, 10) for index in range(100)]
        selected = select_records(inventory, 10)
        self.assertEqual(len(selected), 10)
        self.assertEqual(selected[0].path, "icons/000.svg")
        self.assertEqual(selected[-1].path, "icons/090.svg")
        self.assertEqual(select_records(inventory, 10), selected)
        self.assertEqual(len(select_records(inventory, 1000)), 100)

    def test_record_store_drops_unverifiable_lines(self):
        store = RecordStore(self.tenant.pk, "11111111-1111-4111-8111-111111111111")
        payload = b"<svg/>"
        store.append(
            f"{self.tenant.pk}/11111111-1111-4111-8111-111111111111", "icons/a.svg", payload,
            sha256=hashlib.sha256(payload).hexdigest(), blob_sha1="a" * 40,
        )
        recovered = store.load({"icons/a.svg": {"blob_sha1": "a" * 40}})
        self.assertEqual(len(recovered), 1)
        self.assertEqual(store.load({"icons/a.svg": {"blob_sha1": "b" * 40}}), {})
        store.discard()
        self.assertEqual(store.load({"icons/a.svg": {"blob_sha1": "a" * 40}}), {})