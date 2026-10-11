"""Lease fencing and reconciliation regressions."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import (
    Job,
    JobAttempt,
    OutboxEvent,
    Worker,
    WorkerPool,
    claim_job,
    commit_result,
    reconcile_expired_leases,
    renew_lease,
)


class LeaseReconciliationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="lease-reconcile", name="Lease Reconcile")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="cpu")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id, pool=self.pool, name="worker-1", slots=1,
        )
        self.job = Job.objects.create(
            tenant_id=self.tenant.tenant_id, pool=self.pool, name="task", max_attempts=2,
        )
        descriptor = claim_job(self.worker, self.job)
        self.attempt = JobAttempt.objects.get(attempt_id=descriptor["attempt_id"])
        self.token = descriptor["fencing_token"]

    def expire_attempt(self):
        expired_at = timezone.now() - timedelta(seconds=1)
        JobAttempt.objects.filter(pk=self.attempt.pk).update(lease_expires_at=expired_at)
        Job.objects.filter(pk=self.job.pk).update(lease_expires_at=expired_at)
        self.attempt.refresh_from_db()
        self.job.refresh_from_db()

    def test_expired_attempt_cannot_renew_or_commit_result(self):
        self.expire_attempt()

        self.assertFalse(renew_lease(self.attempt, self.token, progress=0.9))
        self.assertFalse(
            commit_result(
                self.attempt,
                self.token,
                JobAttempt.Status.SUCCEEDED,
                result_envelope={"ok": True},
            )
        )
        self.job.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.RUNNING)
        self.assertEqual(self.attempt.status, JobAttempt.Status.RUNNING)
        self.worker.refresh_from_db()
        self.assertIsNone(self.worker.last_heartbeat_at)

    def test_successful_lease_renewal_records_worker_heartbeat(self):
        self.assertIsNone(self.worker.last_heartbeat_at)

        self.assertTrue(renew_lease(self.attempt, self.token, progress=0.5))

        self.worker.refresh_from_db()
        self.assertIsNotNone(self.worker.last_heartbeat_at)
        self.assertLessEqual(self.worker.last_heartbeat_at, timezone.now())

    def test_expired_cancellation_stays_interrupted_until_worker_stop_is_known(self):
        self.job.desired_action = Job.DesiredAction.CANCEL
        self.job.save(update_fields=("desired_action", "updated_at"))
        self.expire_attempt()
        event_count = OutboxEvent.objects.count()

        self.assertEqual(reconcile_expired_leases(), 1)

        self.job.refresh_from_db()
        self.attempt.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.INTERRUPTED)
        self.assertEqual(self.job.desired_action, Job.DesiredAction.CANCEL)
        self.assertEqual(self.attempt.status, JobAttempt.Status.EXPIRED)
        self.assertEqual(self.worker.status, Worker.Status.OFFLINE)
        self.assertEqual(self.worker.slots, 0)
        self.assertEqual(OutboxEvent.objects.count(), event_count)

    def test_reconciliation_is_idempotent_and_releases_worker_slot_once(self):
        self.expire_attempt()
        events_before = OutboxEvent.objects.count()

        self.assertEqual(reconcile_expired_leases(), 1)
        self.assertEqual(OutboxEvent.objects.count(), events_before + 1)
        self.assertEqual(reconcile_expired_leases(), 0)
        self.worker.refresh_from_db()
        self.job.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertEqual(self.worker.slots, 1)
        self.assertEqual(self.job.status, Job.Status.QUEUED)
        self.assertEqual(self.attempt.status, JobAttempt.Status.EXPIRED)
        queued_event = OutboxEvent.objects.latest("created_at")
        self.assertEqual(queued_event.payload["event_type"], "job.queued")
        self.assertEqual(queued_event.payload["job_id"], str(self.job.job_id))
        self.assertEqual(queued_event.topic, f"tenant.{self.tenant.tenant_id}.cpu")

    def test_management_command_runs_reconciliation_and_reports_count(self):
        output = StringIO()
        with patch(
            "modelanvil.jobs.management.commands.reconcile_leases.reconcile_expired_leases",
            return_value=3,
        ) as reconcile:
            call_command("reconcile_leases", stdout=output)

        reconcile.assert_called_once_with()
        self.assertIn("reconciled=3", output.getvalue())
