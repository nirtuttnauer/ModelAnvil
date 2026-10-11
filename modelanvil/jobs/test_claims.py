"""Worker and pool admission rules for durable job claims."""
from django.test import TestCase

from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import (
    Job,
    JobAttempt,
    Worker,
    WorkerPool,
    claim_job,
    commit_result,
    reconcile_expired_leases,
)


class ClaimEligibilityTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="claim-eligibility", name="Claim Eligibility")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="cpu")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id, pool=self.pool, name="worker-1", slots=2,
        )
        self.job = Job.objects.create(
            tenant_id=self.tenant.tenant_id, pool=self.pool, name="task",
        )

    def test_offline_worker_cannot_claim_using_a_stale_worker_instance(self):
        Worker.objects.filter(pk=self.worker.pk).update(status=Worker.Status.OFFLINE)

        descriptor = claim_job(self.worker, self.job)

        self.assertIsNone(descriptor)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.QUEUED)

    def test_worker_cannot_claim_when_its_pool_is_draining(self):
        WorkerPool.objects.filter(pk=self.pool.pk).update(status="draining")

        descriptor = claim_job(self.worker, self.job)

        self.assertIsNone(descriptor)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.QUEUED)

    def test_slot_capacity_is_enforced_across_stale_worker_instances(self):
        Worker.objects.filter(pk=self.worker.pk).update(slots=1)
        second_job = Job.objects.create(
            tenant_id=self.tenant.tenant_id, pool=self.pool, name="second task",
        )
        first_worker_view = Worker.objects.get(pk=self.worker.pk)
        second_worker_view = Worker.objects.get(pk=self.worker.pk)

        first_claim = claim_job(first_worker_view, self.job)
        second_claim = claim_job(second_worker_view, second_job)

        self.assertIsNotNone(first_claim)
        self.assertIsNone(second_claim)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.slots, 0)

    def test_worker_cannot_claim_a_job_from_another_pool(self):
        other_pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="gpu")
        other_job = Job.objects.create(
            tenant_id=self.tenant.tenant_id, pool=other_pool, name="gpu task",
        )

        descriptor = claim_job(self.worker, other_job)

        self.assertIsNone(descriptor)
        other_job.refresh_from_db()
        self.assertEqual(other_job.status, Job.Status.QUEUED)

    def test_worker_skips_higher_priority_jobs_with_incompatible_capabilities(self):
        self.worker.capabilities = {"accelerator": "cpu", "precision": "fp32"}
        self.worker.save(update_fields=("capabilities", "updated_at"))
        self.job.requirements = {"accelerator": "gpu"}
        self.job.priority = 100
        self.job.save(update_fields=("requirements", "priority", "updated_at"))
        compatible = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="cpu task",
            requirements={"accelerator": "cpu"},
            priority=0,
        )

        descriptor = claim_job(self.worker)

        self.assertEqual(descriptor["job_id"], str(compatible.job_id))
        self.job.refresh_from_db()
        compatible.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.QUEUED)
        self.assertEqual(compatible.status, Job.Status.RUNNING)

    def test_multi_slot_resource_group_reservation_and_release(self):
        multi_slot_job = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="distributed training",
            requirements={"slots": 2},
        )
        self.assertEqual(self.worker.slots, 2)

        descriptor = claim_job(self.worker, multi_slot_job)

        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor["slots_reserved"], 2)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.slots, 0)

        attempt = JobAttempt.objects.get(attempt_id=descriptor["attempt_id"])
        self.assertEqual(attempt.slots_reserved, 2)

        ok = commit_result(attempt, descriptor["fencing_token"], JobAttempt.Status.SUCCEEDED)
        self.assertTrue(ok)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.slots, 2)

    def test_worker_with_insufficient_slots_cannot_claim_multi_slot_job(self):
        Worker.objects.filter(pk=self.worker.pk).update(slots=1)
        multi_slot_job = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="heavy job",
            requirements={"slots": 2},
        )

        descriptor = claim_job(self.worker, multi_slot_job)

        self.assertIsNone(descriptor)
        multi_slot_job.refresh_from_db()
        self.assertEqual(multi_slot_job.status, Job.Status.QUEUED)
