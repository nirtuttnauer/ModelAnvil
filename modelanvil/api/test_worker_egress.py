"""Tenant-admin configuration and worker result-egress enforcement."""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from unittest.mock import patch

from modelanvil.core.models import AuditEvent
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerCredential, WorkerPool, commit_result, generate_worker_credential
from modelanvil.jobs.test_remote_worker import result_fixture


@override_settings(ALLOWED_HOSTS=["testserver"])
class WorkerEgressApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(slug="egress", name="Egress")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name="private")
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="private-worker")
        self.job = Job.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="private-job")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="owner", role=Role.OWNER, secret_hash=digest)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        self.url = f"/api/v1/workers/pools/{self.pool.pk}/egress/"

    def post(self, url, payload, auth=None):
        return self.client.post(url, payload, format="json", **(self.auth if auth is None else auth))

    def configure(self):
        response = self.post(self.url, {"result_egress": "metadata_only"})
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def claim(self):
        response = self.post("/api/v1/workers/claim/", {"worker_id": self.worker.pk, "pool": self.pool.name})
        self.assertEqual(response.status_code, 200, response.content)
        descriptor = response.json()
        return {"worker_id": self.worker.pk, "attempt_id": descriptor["attempt_id"],
                "fencing_token": descriptor["fencing_token"], "status": "succeeded"}

    def test_admin_sets_tenant_pool_policy_and_audits_only_metadata(self):
        response = self.configure()
        self.assertEqual(response.json()["result_egress"], "metadata_only")
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.result_egress, "metadata_only")
        audit = AuditEvent.all_objects.filter(resource_type="worker_pool").get()
        self.assertEqual(audit.input_snapshot, {"pool_id": self.pool.pk, "result_egress": "metadata_only"})

    def test_engineer_cannot_weaken_policy(self):
        self.configure()
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="engineer", role=Role.ENGINEER, secret_hash=digest)
        response = self.post(self.url, {"result_egress": "envelope"},
                             {"HTTP_AUTHORIZATION": f"Bearer {secret}"})
        self.assertEqual(response.status_code, 403)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.result_egress, "metadata_only")

    def test_scoped_worker_cannot_change_policy(self):
        self.configure()
        secret, digest = generate_worker_credential()
        WorkerCredential.objects.create(tenant_id=self.tenant.pk, worker=self.worker, secret_hash=digest)
        response = self.post(self.url, {"result_egress": "envelope"},
                             {"HTTP_AUTHORIZATION": f"Bearer {secret}"})
        self.assertEqual(response.status_code, 401)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.result_egress, "metadata_only")

    def test_other_tenant_pool_is_concealed(self):
        other = Tenant.objects.create(slug="egress-other", name="Other")
        pool = WorkerPool.objects.create(tenant_id=other.pk, name="private")
        response = self.post(f"/api/v1/workers/pools/{pool.pk}/egress/", {"result_egress": "metadata_only"})
        self.assertEqual(response.status_code, 404)
        pool.refresh_from_db()
        self.assertEqual(pool.result_egress, "envelope")

    def test_invalid_configuration_cannot_relax_policy(self):
        self.configure()
        response = self.post(self.url, {"result_egress": "typo"})
        self.assertEqual(response.status_code, 400)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.result_egress, "metadata_only")

    def test_metadata_only_refuses_envelopes_and_artifact_descriptors(self):
        self.configure()
        payload = self.claim()
        for extra in [{"result_envelope": result_fixture()}, {"result_envelope": {}},
                      {"artifacts": [{"private_path": "/private/output"}]}]:
            with self.subTest(field=next(iter(extra))):
                response = self.post("/api/v1/workers/result/", {**payload, **extra})
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(JobAttempt.all_objects.get(job=self.job).status, JobAttempt.Status.RUNNING)

    def test_metadata_only_status_commit_releases_slot(self):
        self.configure()
        response = self.post("/api/v1/workers/result/", self.claim())
        self.assertEqual(response.status_code, 200, response.content)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.slots, 1)
        attempt = JobAttempt.all_objects.get(job=self.job)
        self.assertEqual(attempt.status, JobAttempt.Status.SUCCEEDED)
        self.assertIsNone(attempt.result_envelope)
        self.assertEqual(attempt.error, "")

    def test_unknown_stored_policy_fails_closed(self):
        payload = self.claim()
        WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="unknown")
        response = self.post("/api/v1/workers/result/", payload)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(JobAttempt.all_objects.get(job=self.job).status, JobAttempt.Status.RUNNING)

    def test_metadata_only_pool_rejects_free_form_errors_without_mutation(self):
        self.configure()
        payload = self.claim()
        response = self.post("/api/v1/workers/result/", {**payload, "status": "failed", "error": "private diagnostic"})
        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotIn("private diagnostic", response.content.decode())
        attempt = JobAttempt.all_objects.get(job=self.job)
        self.assertEqual(attempt.status, JobAttempt.Status.RUNNING)
        self.assertEqual(attempt.error, "")
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.slots, 0)

    def test_claim_discloses_the_admin_configured_policy(self):
        self.configure()
        response = self.post("/api/v1/workers/claim/", {"worker_id": self.worker.pk, "pool": self.pool.name})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json().get("result_egress"), "metadata_only")

    def test_registration_discloses_current_pool_policy(self):
        self.configure()
        response = self.post("/api/v1/workers/register/", {"worker_name": "new-private", "pool": self.pool.name})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json().get("result_egress"), "metadata_only")

    def test_policy_is_rechecked_at_transactional_commit_boundary(self):
        payload = self.claim()

        def tighten_then_commit(*args, **kwargs):
            WorkerPool.objects.filter(pk=self.pool.pk).update(result_egress="metadata_only")
            return commit_result(*args, **kwargs)

        with patch("modelanvil.api.views.workers.commit_result", side_effect=tighten_then_commit):
            response = self.post("/api/v1/workers/result/", {**payload, "result_envelope": result_fixture()})
        self.assertEqual(response.status_code, 403, response.content)
        attempt = JobAttempt.all_objects.get(job=self.job)
        self.assertIsNone(attempt.result_envelope)
        self.assertEqual(attempt.status, JobAttempt.Status.RUNNING)
