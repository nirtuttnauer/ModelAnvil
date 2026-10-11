"""Worker claim endpoint admission regressions."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.budgets.models import UsageEvent
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.models import Job, Worker, WorkerCredential, WorkerPool


@override_settings(ALLOWED_HOSTS=["testserver"])
class WorkerClaimApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(slug="worker-claim-api", name="Worker Claim API")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="cpu")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id, pool=self.pool, name="worker-1", slots=2,
        )
        self.job = Job.objects.create(
            tenant_id=self.tenant.tenant_id, pool=self.pool, name="task",
        )
        secret, secret_hash = generate_api_key()
        ApiKey.objects.create(
            tenant=self.tenant, name="worker", role=Role.OWNER, secret_hash=secret_hash,
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}

    def test_claim_rejects_a_pool_name_that_does_not_match_worker(self):
        response = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": "gpu"},
            format="json",
            **self.auth,
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.QUEUED)
        self.assertEqual(self.worker.slots, 2)

    def test_registration_returns_the_tenant_scoped_dispatch_queue(self):
        response = self.client.post(
            "/api/v1/workers/register/",
            {"worker_name": "worker-registered", "pool": self.pool.name, "slots": 1},
            format="json",
            **self.auth,
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            response.json()["queue_name"],
            f"tenant.{self.tenant.tenant_id}.{self.pool.name}",
        )

    def test_registration_returns_worker_bound_credential(self):
        registered = self.client.post(
            "/api/v1/workers/register/",
            {"worker_name": "credential-worker", "pool": self.pool.name, "slots": 1},
            format="json",
            **self.auth,
        )
        self.assertEqual(registered.status_code, 201, registered.content)
        worker_id = int(registered.json()["worker_id"])
        worker_token = registered.json()["worker_token"]
        self.assertTrue(worker_token.startswith("mkw_"))

        outside_protocol = self.client.post(
            "/api/v1/workers/register/",
            {"worker_name": "should-not-register", "pool": self.pool.name, "slots": 1},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {worker_token}",
        )
        self.assertEqual(outside_protocol.status_code, 401, outside_protocol.content)

        other_worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="credential-worker-other",
        )
        forbidden = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": other_worker.pk, "pool": self.pool.name},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {worker_token}",
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.content)

        claimed = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": worker_id, "pool": self.pool.name},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {worker_token}",
        )
        self.assertEqual(claimed.status_code, 200, claimed.content)

    def test_admin_can_revoke_worker_credential(self):
        registered = self.client.post(
            "/api/v1/workers/register/",
            {"worker_name": "revocable-worker", "pool": self.pool.name, "slots": 1},
            format="json",
            **self.auth,
        )
        self.assertEqual(registered.status_code, 201, registered.content)
        worker_id = int(registered.json()["worker_id"])
        worker_token = registered.json()["worker_token"]

        revoked = self.client.post(
            f"/api/v1/workers/{worker_id}/credential/revoke/",
            {}, format="json", **self.auth,
        )
        self.assertEqual(revoked.status_code, 200, revoked.content)

        rejected = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": worker_id, "pool": self.pool.name},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {worker_token}",
        )
        self.assertEqual(rejected.status_code, 401, rejected.content)

    def test_expired_worker_credential_is_rejected(self):
        registered = self.client.post(
            "/api/v1/workers/register/",
            {"worker_name": "expired-worker", "pool": self.pool.name, "slots": 1},
            format="json",
            **self.auth,
        )
        self.assertEqual(registered.status_code, 201, registered.content)
        worker_id = int(registered.json()["worker_id"])
        credential = WorkerCredential.objects.get(worker_id=worker_id)
        credential.expires_at = timezone.now() - timedelta(seconds=1)
        credential.save(update_fields=["expires_at"])

        rejected = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": worker_id, "pool": self.pool.name},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {registered.json()['worker_token']}",
        )
        self.assertEqual(rejected.status_code, 401, rejected.content)

    def test_claim_response_includes_job_capability_requirements(self):
        self.worker.capabilities = {"accelerator": "cpu"}
        self.worker.save(update_fields=("capabilities", "updated_at"))
        self.job.requirements = {"accelerator": "cpu"}
        self.job.save(update_fields=("requirements", "updated_at"))

        response = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["requirements"], {"accelerator": "cpu"})

    def test_offline_worker_claim_returns_conflict_instead_of_no_work(self):
        Worker.objects.filter(pk=self.worker.pk).update(status=Worker.Status.OFFLINE)

        response = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.QUEUED)

    def test_draining_pool_claim_returns_conflict_instead_of_no_work(self):
        WorkerPool.objects.filter(pk=self.pool.pk).update(status="draining")

        response = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )

        self.assertEqual(response.status_code, 409, response.content)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.QUEUED)

    def test_running_job_cancellation_is_observed_by_worker_before_terminal_state(self):
        claimed = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )
        self.assertEqual(claimed.status_code, 200, claimed.content)
        attempt = claimed.json()

        cancellation = self.client.post(
            f"/api/v1/jobs/{self.job.job_id}/cancel/", {}, format="json", **self.auth,
        )
        self.assertEqual(cancellation.status_code, 202, cancellation.content)
        self.assertEqual(cancellation.json()["status"], Job.Status.RUNNING)
        self.assertEqual(cancellation.json()["desired_action"], "cancel")

        heartbeat = self.client.post(
            "/api/v1/workers/heartbeat/",
            {"worker_id": self.worker.pk, "attempt_id": attempt["attempt_id"],
             "fencing_token": attempt["fencing_token"]},
            format="json",
            **self.auth,
        )
        self.assertEqual(heartbeat.status_code, 200, heartbeat.content)
        self.assertEqual(heartbeat.json()["desired_action"], "cancel")

        result = self.client.post(
            "/api/v1/workers/result/",
            {"worker_id": self.worker.pk, "attempt_id": attempt["attempt_id"],
             "fencing_token": attempt["fencing_token"], "status": "interrupted"},
            format="json",
            **self.auth,
        )
        self.assertEqual(result.status_code, 200, result.content)
        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.CANCELLED)
        self.assertEqual(self.job.desired_action, "cancel")
        self.assertEqual(self.worker.slots, 2)

    def test_drain_and_activate_worker(self):
        drain_res = self.client.post(
            f"/api/v1/workers/{self.worker.pk}/drain/", {}, format="json", **self.auth,
        )
        self.assertEqual(drain_res.status_code, 200)
        self.assertEqual(drain_res.json()["status"], "draining")

        # Claim while draining is rejected with 409
        claim_res = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )
        self.assertEqual(claim_res.status_code, 409)

        # Activate worker
        act_res = self.client.post(
            f"/api/v1/workers/{self.worker.pk}/activate/", {}, format="json", **self.auth,
        )
        self.assertEqual(act_res.status_code, 200)
        self.assertEqual(act_res.json()["status"], "available")

        # Claim succeeds now
        claim_res2 = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )
        self.assertEqual(claim_res2.status_code, 200)

    def test_drain_and_activate_pool(self):
        drain_res = self.client.post(
            f"/api/v1/workers/pools/{self.pool.pk}/drain/", {}, format="json", **self.auth,
        )
        self.assertEqual(drain_res.status_code, 200)
        self.assertEqual(drain_res.json()["status"], "draining")

        # Claim while pool draining is rejected with 409
        claim_res = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )
        self.assertEqual(claim_res.status_code, 409)

        # Activate pool
        act_res = self.client.post(
            f"/api/v1/workers/pools/{self.pool.pk}/activate/", {}, format="json", **self.auth,
        )
        self.assertEqual(act_res.status_code, 200)
        self.assertEqual(act_res.json()["status"], "active")

        # Claim succeeds now
        claim_res2 = self.client.post(
            "/api/v1/workers/claim/",
            {"worker_id": self.worker.pk, "pool": self.pool.name},
            format="json",
            **self.auth,
        )
        self.assertEqual(claim_res2.status_code, 200)

    def test_usage_events_summary(self):
        UsageEvent.objects.create(
            tenant_id=self.tenant.tenant_id,
            provider_event_key="evt-001",
            quantity=Decimal("10.5"),
            unit="gpu_hours",
            amount=Decimal("21.00"),
            currency="USD",
        )
        response = self.client.get(
            "/api/v1/usage-events/summary/",
            **self.auth,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["tenant_id"], str(self.tenant.tenant_id))
        self.assertTrue(len(data["usage_by_unit"]) >= 1)
        gpu_stat = next(u for u in data["usage_by_unit"] if u["unit"] == "gpu_hours")
        self.assertEqual(gpu_stat["event_count"], 1)
        self.assertEqual(gpu_stat["total_quantity"], "10.500000")
        self.assertEqual(gpu_stat["total_amount"], "21.000000")
