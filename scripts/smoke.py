"""End-to-end control-plane smoke test. Run: PYTHONPATH=. .venv/bin/python -m scripts.smoke"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")

import django

django.setup()

from django.test import Client, TestCase, override_settings

from modelanvil.identity.models import ApiKey, Membership, Role, Tenant, User, generate_api_key
from modelanvil.jobs.models import Job, WorkerPool


@override_settings(ALLOWED_HOSTS=["testserver"])
class ControlPlaneSmokeTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.acme = Tenant.objects.create(slug="acme", name="Acme Corp")
        self.globex = Tenant.objects.create(slug="globex", name="Globex")
        owner = User.objects.create(email="owner@acme.test", name="Owner")
        Membership.objects.create(tenant=self.acme, user=owner, role=Role.OWNER)
        self.owner_auth = {"HTTP_AUTHORIZATION": f"Bearer {self.make_key(self.acme, 'owner', Role.OWNER)}"}

    @staticmethod
    def make_key(tenant: Tenant, name: str, role: str) -> str:
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name=name, role=role, secret_hash=digest)
        return secret

    def test_health_and_structured_unauthenticated_error(self) -> None:
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/api/v1/tenants/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")

    def test_tenant_list_is_scoped_to_key(self) -> None:
        response = self.client.get("/api/v1/tenants/", **self.owner_auth)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        tenants = data.get("results", data) if isinstance(data, dict) else data
        ids = {tenant["tenant_id"] for tenant in tenants}
        self.assertIn(str(self.acme.tenant_id), ids)
        self.assertNotIn(str(self.globex.tenant_id), ids)

    def test_identity_creation_and_viewer_role_enforcement(self) -> None:
        response = self.client.post("/api/v1/users/", {"email": "eng@acme.test", "role": Role.ENGINEER}, content_type="application/json", **self.owner_auth)
        self.assertEqual(response.status_code, 201, response.content)
        response = self.client.post("/api/v1/api-keys/", {"name": "viewer", "role": Role.VIEWER}, content_type="application/json", **self.owner_auth)
        self.assertEqual(response.status_code, 201, response.content)
        secret = response.json()["secret"]
        self.assertTrue(secret.startswith("mkv_"))
        response = self.client.post("/api/v1/users/", {"email": "denied@acme.test"}, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {secret}")
        self.assertEqual(response.status_code, 403, response.content)

    def test_worker_lifecycle_and_tenant_isolation(self) -> None:
        response = self.client.post("/api/v1/workers/register/", {"worker_name": "w1", "pool": "cpu", "slots": 2}, content_type="application/json", **self.owner_auth)
        self.assertEqual(response.status_code, 201, response.content)
        worker_id = response.json()["worker_id"]
        pool = WorkerPool.objects.get(tenant_id=self.acme.tenant_id, name="cpu")
        job = Job.objects.create(tenant_id=self.acme.tenant_id, name="train", pool=pool, payload={"x": 1})

        response = self.client.post("/api/v1/workers/claim/", {"worker_id": worker_id, "pool": "cpu"}, content_type="application/json", **self.owner_auth)
        self.assertEqual(response.status_code, 200, response.content)
        claim = response.json()
        self.assertTrue(claim["claimed"])
        attempt_id, token = claim["attempt_id"], claim["fencing_token"]

        response = self.client.post("/api/v1/workers/heartbeat/", {"worker_id": worker_id, "attempt_id": attempt_id, "fencing_token": token, "progress": 0.5}, content_type="application/json", **self.owner_auth)
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.post("/api/v1/workers/heartbeat/", {"worker_id": worker_id, "attempt_id": attempt_id, "fencing_token": "stale"}, content_type="application/json", **self.owner_auth)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "stale_fence_token")

        response = self.client.post("/api/v1/workers/result/", {"worker_id": worker_id, "attempt_id": attempt_id, "fencing_token": token, "status": "succeeded"}, content_type="application/json", **self.owner_auth)
        self.assertEqual(response.status_code, 200, response.content)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.SUCCEEDED)

        globex_owner_key = self.make_key(self.globex, "owner", Role.OWNER)
        globex_auth = {"HTTP_AUTHORIZATION": f"Bearer {globex_owner_key}"}
        response = self.client.post("/api/v1/workers/register/", {"worker_name": "gw", "pool": "cpu", "slots": 1}, content_type="application/json", **globex_auth)
        self.assertEqual(response.status_code, 201, response.content)
        worker_id = response.json()["worker_id"]
        worker_auth = {"HTTP_AUTHORIZATION": f"Bearer {response.json()['worker_token']}"}
        response = self.client.post("/api/v1/workers/claim/", {"worker_id": worker_id, "pool": "cpu", "job_id": str(job.job_id)}, content_type="application/json", **worker_auth)
        self.assertEqual(response.status_code, 404, response.content)


def main() -> int:
    from django.core.management import call_command

    failures = call_command("test", "scripts.smoke", verbosity=2, interactive=False)
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
