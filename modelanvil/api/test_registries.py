"""Tenant isolation checks for the versioned resource API."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.data.models import DataSource
from modelanvil.jobs.models import Job, OutboxEvent, WorkerPool
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation


@override_settings(ALLOWED_HOSTS=["testserver"])
class RegistryApiIsolationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.one = Tenant.objects.create(slug="one-api", name="One")
        self.two = Tenant.objects.create(slug="two-api", name="Two")
        self.auth_one = {"HTTP_AUTHORIZATION": f"Bearer {self.make_key(self.one)}"}
        DataSource.objects.create(tenant_id=self.one.tenant_id, name="visible", kind="upload")
        DataSource.objects.create(tenant_id=self.two.tenant_id, name="hidden", kind="upload")

    @staticmethod
    def make_key(tenant):
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name="test", role=Role.OWNER, secret_hash=digest)
        return secret

    def test_registry_lists_only_current_tenant_and_creates_in_scope(self):
        response = self.client.get("/api/v1/data-sources/", **self.auth_one)
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json().get("results", response.json())
        self.assertEqual([row["name"] for row in rows], ["visible"])
        response = self.client.post(
            "/api/v1/data-sources/", {"name": "new", "kind": "repository"},
            format="json", **self.auth_one,
        )
        self.assertEqual(response.status_code, 201, response.content)
        created = DataSource.objects.get(name="new")
        self.assertEqual(created.tenant_id, self.one.tenant_id)

    def test_job_admission_reserves_configured_budget_atomically(self):
        pool = WorkerPool.objects.create(tenant_id=self.one.tenant_id, name="cpu")
        policy = BudgetPolicy.objects.create(
            tenant_id=self.one.tenant_id, name="compute", period="monthly",
            unit="gpu_seconds", limit_amount=100,
        )
        response = self.client.post(
            "/api/v1/jobs/", {"name": "unbudgeted", "pool": pool.pk, "payload": {}},
            format="json", **{**self.auth_one, "HTTP_IDEMPOTENCY_KEY": "unbudgeted"},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/v1/jobs/", {"name": "oversized", "pool": pool.pk, "payload": {},
                               "budget_policy_id": str(policy.policy_id), "estimated_amount": "101"},
            format="json", **{**self.auth_one, "HTTP_IDEMPOTENCY_KEY": "oversized"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Job.objects.filter(tenant_id=self.one.tenant_id).exists())
        response = self.client.post(
            "/api/v1/jobs/", {"name": "bounded", "pool": pool.pk, "payload": {},
                               "requirements": {"accelerator": "cpu"},
                               "budget_policy_id": str(policy.policy_id), "estimated_amount": "70"},
            format="json", **{**self.auth_one, "HTTP_IDEMPOTENCY_KEY": "bounded"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["requirements"], {"accelerator": "cpu"})
        self.assertEqual(BudgetReservation.objects.filter(tenant_id=self.one.tenant_id).count(), 1)
        self.assertEqual(OutboxEvent.objects.filter(tenant_id=self.one.tenant_id).count(), 1)

    def test_job_creation_idempotency_replays_and_is_principal_scoped(self):
        pool = WorkerPool.objects.create(tenant_id=self.one.tenant_id, name="idempotent-cpu")
        payload = {"name": "stable job", "pool": pool.pk, "payload": {"seed": 7}}
        missing_key = self.client.post(
            "/api/v1/jobs/", payload, format="json", **self.auth_one,
        )
        self.assertEqual(missing_key.status_code, 400)
        self.assertEqual(missing_key.json()["error"]["code"], "validation_failed")

        first = self.client.post(
            "/api/v1/jobs/", payload, format="json",
            **{**self.auth_one, "HTTP_IDEMPOTENCY_KEY": "client-request-1"},
        )
        replay = self.client.post(
            "/api/v1/jobs/", payload, format="json",
            **{**self.auth_one, "HTTP_IDEMPOTENCY_KEY": "client-request-1"},
        )
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(first["Idempotency-Retention"], "604800")
        self.assertEqual(replay["Idempotency-Retention"], "604800")
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(Job.objects.filter(tenant_id=self.one.tenant_id).count(), 1)
        self.assertEqual(OutboxEvent.objects.filter(tenant_id=self.one.tenant_id).count(), 1)

        changed = {**payload, "name": "different job"}
        conflict = self.client.post(
            "/api/v1/jobs/", changed, format="json",
            **{**self.auth_one, "HTTP_IDEMPOTENCY_KEY": "client-request-1"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.content)
        self.assertEqual(conflict.json()["error"]["code"], "idempotency_conflict")

        other_key = self.make_key(self.one)
        other_principal = self.client.post(
            "/api/v1/jobs/", payload, format="json",
            **{"HTTP_IDEMPOTENCY_KEY": "client-request-1", "HTTP_AUTHORIZATION": f"Bearer {other_key}"},
        )
        self.assertEqual(other_principal.status_code, 201, other_principal.content)
        self.assertNotEqual(other_principal.json()["job_id"], first.json()["job_id"])
        self.assertEqual(Job.objects.filter(tenant_id=self.one.tenant_id).count(), 2)

    def test_cancelling_queued_job_releases_budget_and_is_idempotent(self):
        pool = WorkerPool.objects.create(tenant_id=self.one.tenant_id, name="cancel-cpu")
        policy = BudgetPolicy.objects.create(
            tenant_id=self.one.tenant_id, name="cancel-budget", period="monthly",
            unit="gpu_seconds", limit_amount=100,
        )
        create = self.client.post(
            "/api/v1/jobs/", {"name": "cancel me", "pool": pool.pk, "payload": {},
                               "budget_policy_id": str(policy.policy_id), "estimated_amount": "25"},
            format="json", **{**self.auth_one, "HTTP_IDEMPOTENCY_KEY": "cancel-create"},
        )
        self.assertEqual(create.status_code, 201, create.content)
        job_id = create.json()["job_id"]
        reservation = BudgetReservation.objects.get(job_id=job_id)

        cancel = self.client.post(f"/api/v1/jobs/{job_id}/cancel/", {}, format="json", **self.auth_one)
        self.assertEqual(cancel.status_code, 200, cancel.content)
        reservation.refresh_from_db()
        self.assertEqual(reservation.state, BudgetReservation.State.RELEASED)

        retry = self.client.post(f"/api/v1/jobs/{job_id}/cancel/", {}, format="json", **self.auth_one)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json()["status"], Job.Status.CANCELLED)
