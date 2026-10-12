import io
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from datetime import timedelta
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, TransactionTestCase, override_settings
from django.db import connection, close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.budgets.models import BudgetPolicy
from modelanvil.compute.models import ComputeAllocation
from modelanvil.compute.plugins import PluginError, ProviderError, definition, task_executor, validate_configuration
from modelanvil.compute.runpod import RunpodProvider, SPEC_SCHEMA
from modelanvil.compute.service import allocate, allocation_name, reconcile
from modelanvil.core.models import AuditEvent
from modelanvil.identity.models import ApiKey, Project, Team, Role, Tenant, generate_api_key
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerCredential, WorkerPool, claim_job


def compute_entry(tenant):
    return {"contract_version": "1.0", "kind": "compute", "name": "Runpod",
            "tenant_ids": [str(tenant)], "factory": "modelanvil.compute.runpod:RunpodProvider",
            "credential_env": "TEST_RUNPOD_TOKEN", "configuration_schema": SPEC_SCHEMA,
            "image": "example/worker@sha256:" + "a" * 64, "worker_endpoint": "https://control.example/api/v1/workers/",
            "worker_executor": "modelanvil.compute.task_worker:execute", "task_plugin": "uppercase"}


def task_entry(tenant):
    return {"contract_version": "1.0", "kind": "task", "tenant_ids": [str(tenant)],
            "executor": "modelanvil.compute.examples:uppercase", "configuration_schema": {
                "type": "object", "additionalProperties": False, "required": ["text"],
                "properties": {"text": {"type": "string", "maxLength": 1000}}}}


@override_settings(ALLOWED_HOSTS=["testserver"])
class ComputeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Compute", slug="compute")
        self.other = Tenant.objects.create(name="Other", slug="other-compute")
        self.pool = WorkerPool.all_objects.create(tenant_id=self.tenant.tenant_id, name="gpu")
        self.policy = BudgetPolicy.all_objects.create(tenant_id=self.tenant.tenant_id, name="allocations", unit="allocation_seconds",
                                                     period="lifetime", limit_amount=7200)
        self.key = self.make_key(self.tenant)
        self.auth = {"HTTP_AUTHORIZATION": "Bearer " + self.key}
        self.settings_override = override_settings(MODELANVIL_PLUGINS={"runpod": compute_entry(self.tenant.tenant_id),
                                                                     "uppercase": task_entry(self.tenant.tenant_id)})
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"TEST_RUNPOD_TOKEN": "provider-secret"}).start()
        self.provider = MagicMock()
        self.create_patch = patch("modelanvil.compute.service.compute_provider", return_value=self.provider).start()
        def create(name, spec, bootstrap):
            self.name = name
            self.bootstrap = bootstrap
            return {"id": "pod-1", "name": name, "status": "PROVISIONING"}
        self.provider.create.side_effect = create
        self.provider.inspect.side_effect = lambda resource: {"id": "pod-1", "name": self.name, "status": "RUNNING"}
        self.payload = {"request_id": str(uuid.uuid4()), "plugin_id": "runpod", "pool": self.pool.pk,
                        "policy_id": str(self.policy.policy_id), "lifetime_seconds": 600,
                        "spec": {"gpu_id": "NVIDIA H100 PCIe", "gpu_count": 1, "disk_gb": 50,
                                 "cloud": "SECURE", "data_center_ids": ["EU-1"]}}

    @staticmethod
    def make_key(tenant, role=Role.OWNER, project=None):
        token, digest = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name=str(uuid.uuid4()), role=role, secret_hash=digest, project=project)
        return token

    def allocate(self, payload=None):
        return self.client.post("/api/v1/compute-allocations/", payload or self.payload, format="json", **self.auth)

    def test_create_bootstraps_scoped_worker_and_replay_does_not_rent_again(self):
        first, second = self.allocate(), self.allocate()
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.json(), second.json())
        self.provider.create.assert_called_once()
        allocation = ComputeAllocation.all_objects.get()
        self.assertEqual(allocation.state, "active")
        self.assertFalse(first.json()["worker_connected"])
        self.assertEqual(allocation.reservation.estimated_amount, 600)
        credential = WorkerCredential.all_objects.get(worker=allocation.worker)
        token = self.bootstrap["env"]["MODELANVIL_WORKER_TOKEN"]
        self.assertNotEqual(credential.secret_hash, token)
        self.assertNotIn(token, json.dumps(first.json()))
        self.assertNotIn(token, json.dumps(list(AuditEvent.all_objects.values("input_snapshot"))))
        self.assertEqual(AuditEvent.all_objects.get(resource_type="compute_allocation").actor_kind, "api_key")
        self.assertNotIn("provider-secret", json.dumps(self.bootstrap))
        self.assertEqual(allocation.worker.capabilities["task_plugin"], "uppercase")
        changed = self.allocate({**self.payload, "lifetime_seconds": 601})
        self.assertEqual(changed.status_code, 400)
        self.provider.create.assert_called_once()

    def test_timeout_is_reconciled_without_duplicate_create(self):
        self.provider.create.side_effect = ProviderError("provider_transport_uncertain")
        response = self.allocate()
        self.assertEqual(response.json()["state"], "uncertain")
        allocation = ComputeAllocation.all_objects.get()
        self.provider.find.return_value = [{"id": "pod-1", "name": allocation_name(allocation), "status": "RUNNING"}]
        recovered = reconcile(allocation)
        self.assertEqual(recovered.provider_resource_id, "pod-1")
        self.allocate()
        self.provider.create.assert_called_once()

    def test_no_matches_and_duplicate_names_remain_uncertain(self):
        self.provider.create.side_effect = ProviderError()
        self.allocate()
        allocation = ComputeAllocation.all_objects.get()
        for matches in ([], [{}, {}]):
            self.provider.find.return_value = matches
            result = reconcile(allocation, release=True)
            self.assertEqual(result.state, "releasing")
            self.assertEqual(result.error_code, "provider_create_unresolved")
        self.provider.release.assert_not_called()
        self.assertIsNotNone(WorkerCredential.all_objects.get().revoked_at)

    def test_release_requires_observed_termination_and_settles_once(self):
        self.allocate()
        allocation = ComputeAllocation.all_objects.get()
        result = reconcile(allocation, release=True)
        self.assertEqual(result.state, "releasing")
        self.assertIsNone(result.released_at)
        self.assertEqual(result.reservation.state, "reserved")
        self.provider.inspect.return_value = None
        self.provider.inspect.side_effect = None
        result = reconcile(result)
        self.assertEqual(result.state, "released")
        self.assertEqual(result.reservation.state, "settled")
        calls = self.provider.release.call_count
        reconcile(result, release=True)
        self.assertEqual(self.provider.release.call_count, calls)
        self.assertEqual(Worker.all_objects.get().status, "offline")

    def test_expiry_cleanup_command_revokes_and_releases(self):
        self.allocate()
        allocation = ComputeAllocation.all_objects.get()
        ComputeAllocation.all_objects.filter(pk=allocation.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.provider.inspect.side_effect = [{"id": "pod-1", "name": self.name, "status": "RUNNING"}, None]
        call_command("reconcile_compute", stdout=io.StringIO())
        allocation.refresh_from_db()
        self.assertEqual(allocation.state, "released")
        self.assertIsNotNone(WorkerCredential.all_objects.get().revoked_at)

    def test_rejection_releases_reservation_but_transport_does_not(self):
        self.provider.create.side_effect = ProviderError("provider_request_rejected", uncertain=False)
        response = self.allocate()
        self.assertEqual(response.json()["state"], "failed")
        self.assertEqual(ComputeAllocation.all_objects.get().reservation.state, "released")

    def test_foreign_resource_is_never_deleted(self):
        self.allocate()
        allocation = ComputeAllocation.all_objects.get()
        self.provider.inspect.side_effect = None
        self.provider.inspect.return_value = {"id": "pod-1", "name": "someone-elses-pod", "status": "RUNNING"}
        result = reconcile(allocation, release=True)
        self.assertEqual(result.error_code, "provider_identity_mismatch")
        self.provider.release.assert_not_called()

    def test_invalid_config_and_budget_refuse_before_provider_create(self):
        for update in ({"gpu_count": 0}, {"image": "untrusted:latest"}, {"env": {"secret": "x"}}):
            response = self.allocate({**self.payload, "spec": {**self.payload["spec"], **update}})
            self.assertEqual(response.status_code, 400, response.content)
        self.policy.limit_amount = 1
        self.policy.save()
        self.assertEqual(self.allocate().status_code, 400)
        self.policy.limit_amount = 7200
        self.policy.currency = "USD"
        self.policy.save()
        self.assertEqual(self.allocate().status_code, 400)
        self.assertFalse(Worker.all_objects.exists())
        self.provider.create.assert_not_called()

    def test_tenant_and_role_boundaries(self):
        self.allocate()
        allocation = ComputeAllocation.all_objects.get()
        foreign_auth = {"HTTP_AUTHORIZATION": "Bearer " + self.make_key(self.other)}
        self.assertEqual(self.client.get("/api/v1/compute-plugins/", **foreign_auth).json()["results"], [])
        self.assertEqual(self.client.get(f"/api/v1/compute-allocations/{allocation.allocation_id}/", **foreign_auth).status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/compute-allocations/{allocation.allocation_id}/release/", {}, format="json", **foreign_auth).status_code, 404)
        engineer = {"HTTP_AUTHORIZATION": "Bearer " + self.make_key(self.tenant, Role.ENGINEER)}
        self.assertEqual(self.client.post("/api/v1/compute-allocations/", self.payload, format="json", **engineer).status_code, 403)
        team = Team.all_objects.create(tenant_id=self.tenant.tenant_id, name="Team")
        project = Project.all_objects.create(tenant_id=self.tenant.tenant_id, name="Restricted", team=team)
        scoped = {"HTTP_AUTHORIZATION": "Bearer " + self.make_key(self.tenant, project=project)}
        self.assertEqual(self.client.post(f"/api/v1/compute-allocations/{allocation.allocation_id}/release/", {}, format="json", **scoped).status_code, 403)

    def test_task_plugin_executes_a_real_fenced_job_and_bad_revision_is_refused(self):
        _, digest = definition("uppercase", self.tenant.tenant_id, "task")
        worker = Worker.all_objects.create(tenant_id=self.tenant.tenant_id, pool=self.pool, name="custom-worker",
            capabilities={"task_plugin": "uppercase", "task_plugin_digest": digest})
        payload = {"name": "Custom uppercase", "pool": self.pool.pk,
            "requirements": {"task_plugin": "uppercase", "task_plugin_digest": digest},
            "payload": {"configuration": {"text": "hello"}},
            "budget_policy_id": str(self.policy.policy_id), "estimated_amount": "10"}
        response = self.client.post("/api/v1/jobs/", payload, format="json", HTTP_IDEMPOTENCY_KEY="custom-job", **self.auth)
        self.assertEqual(response.status_code, 201, response.content)
        call_command("run_plugin_worker", worker_id=worker.pk, plugin_id="uppercase", once=True, stdout=io.StringIO())
        job = Job.all_objects.get(job_id=response.json()["job_id"])
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(JobAttempt.all_objects.get(job=job).result_envelope["blocks"][0]["text"], "HELLO")
        payload["requirements"]["task_plugin_digest"] = "bad"
        response = self.client.post("/api/v1/jobs/", payload, format="json", HTTP_IDEMPOTENCY_KEY="bad-revision", **self.auth)
        self.assertEqual(response.status_code, 400)

    def test_dedicated_plugin_worker_cannot_consume_generic_or_wrong_revision_jobs(self):
        _, digest = definition("uppercase", self.tenant.tenant_id, "task")
        worker = Worker.all_objects.create(tenant_id=self.tenant.tenant_id, pool=self.pool, name="dedicated",
            capabilities={"task_plugin": "uppercase", "task_plugin_digest": digest})
        for requirements in ({}, {"task_plugin": "uppercase", "task_plugin_digest": "wrong"}):
            Job.all_objects.create(tenant_id=self.tenant.tenant_id, pool=self.pool, name="Other job", requirements=requirements)
        self.assertIsNone(claim_job(worker))

    def test_plugin_revision_change_retains_cleanup_intent_and_reservation(self):
        self.allocate()
        allocation = ComputeAllocation.all_objects.get()
        self.create_patch.side_effect = PluginError("changed")
        result = reconcile(allocation, release=True)
        self.assertEqual(result.state, "releasing")
        self.assertTrue(result.release_requested)
        self.assertEqual(result.error_code, "plugin_unavailable")
        self.assertEqual(result.reservation.state, "reserved")
        self.assertIsNotNone(WorkerCredential.all_objects.get().revoked_at)


class RunpodTransportTests(SimpleTestCase):
    def setUp(self):
        self.provider = RunpodProvider("private-token")
        self.provider._opener = MagicMock()

    def response(self, value, status=200):
        response = MagicMock()
        response.status = status
        response.read.return_value = json.dumps(value).encode()
        response.__enter__.return_value = response
        self.provider._opener.open.return_value = response

    def test_v2_create_uses_exec_arguments_and_only_scoped_bootstrap(self):
        self.response({"id": "pod-1", "name": "owned", "status": "PROVISIONING"}, 201)
        spec = {"gpu_id": "H100", "gpu_count": 1, "disk_gb": 50, "cloud": "SECURE", "data_center_ids": ["EU-1"]}
        self.provider.create("owned", spec, {"image": "worker@sha256:" + "a" * 64, "env": {"MODELANVIL_WORKER_TOKEN": "scoped"}})
        request = self.provider._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.runpod.io/v2/pods")
        body = json.loads(request.data)
        self.assertEqual(body["gpu"], {"id": "H100", "count": 1})
        self.assertEqual(body["entrypoint"], ["python", "-m", "modelanvil.compute.worker"])
        self.assertNotIn("private-token", request.data.decode())

    def test_catalog_and_paginated_recovery(self):
        self.response({"gpus": [{"id": "gpu-1", "memory": 80, "secret": "omit"}]})
        self.assertEqual(self.provider.catalog(), [{"id": "gpu-1", "memory": 80}])
        with patch.object(self.provider, "_request", side_effect=[
            {"pods": [], "pagination": {"hasNextPage": True, "nextCursor": "a/b?secret"}},
            {"pods": [{"id": "pod-1", "name": "owned", "status": "RUNNING"}], "pagination": {"hasNextPage": False}},
        ]) as call:
            self.assertEqual(self.provider.find("owned")[0]["id"], "pod-1")
            self.assertIn("cursor=a%2Fb%3Fsecret", call.call_args.args[1])

    def test_error_bodies_are_sanitized_and_create_never_retried(self):
        for code, uncertain in ((401, False), (429, False), (500, True), (302, True)):
            self.provider._opener.open.side_effect = HTTPError("https://api.runpod.io", code, "secret", {}, io.BytesIO(b"private-token"))
            with self.assertRaises(ProviderError) as failure:
                self.provider._request("POST", "pods", {})
            self.assertEqual(failure.exception.uncertain, uncertain)
            self.assertNotIn("private-token", str(failure.exception))
        self.provider._opener.open.side_effect = URLError("private-token")
        with self.assertRaises(ProviderError):
            self.provider._request("POST", "pods", {})

    def test_delete_204_and_inspect_404(self):
        self.response(None, 204)
        self.provider.release("pod-1")
        self.provider._opener.open.side_effect = HTTPError("https://api.runpod.io", 404, "gone", {}, io.BytesIO())
        self.assertIsNone(self.provider.inspect("pod-1"))
        with self.assertRaises(ProviderError):
            self.provider.inspect("../account")

    def test_plugin_schema_cannot_resolve_remote_references(self):
        with self.assertRaises(PluginError):
            validate_configuration({"$ref": "https://example.com/schema"}, {})

    def test_cancelled_task_does_not_invoke_installed_code(self):
        tenant = uuid.uuid4()
        with override_settings(MODELANVIL_PLUGINS={"uppercase": task_entry(tenant)}):
            _, digest = definition("uppercase", tenant, "task")
            with patch("modelanvil.compute.plugins.load_callable") as load:
                context = MagicMock(); context.heartbeat.return_value = False
                executor = task_executor("uppercase", {"text": "hello"}, tenant_id=tenant, digest=digest)
                self.assertIsNone(executor({"tenant_id": str(tenant)}, context))
                load.return_value.assert_not_called()
                with self.assertRaises(PluginError):
                    executor({"tenant_id": str(uuid.uuid4())}, context)


@skipUnless(connection.vendor == "postgresql", "Concurrent allocation qualification requires PostgreSQL.")
class ConcurrentAllocationTests(TransactionTestCase):
    def test_concurrent_replays_create_one_provider_resource_and_one_reservation(self):
        tenant = Tenant.objects.create(slug="concurrent-compute", name="Concurrent")
        pool = WorkerPool.all_objects.create(tenant_id=tenant.tenant_id, name="gpu")
        policy = BudgetPolicy.all_objects.create(tenant_id=tenant.tenant_id, name="capacity", unit="allocation_seconds",
                                                 period="lifetime", limit_amount=7200)
        provider = MagicMock()
        provider.create.side_effect = lambda name, spec, bootstrap: {"id": "pod-1", "name": name, "status": "PROVISIONING"}
        request_id = uuid.uuid4()
        def submit(_):
            close_old_connections()
            try:
                return allocate(tenant_id=tenant.tenant_id, request_id=request_id, plugin_id="runpod", pool=pool,
                    spec={"gpu_id": "H100", "gpu_count": 1, "disk_gb": 50, "cloud": "SECURE", "data_center_ids": ["EU-1"]},
                    lifetime_seconds=600, policy_id=policy.policy_id).allocation_id
            finally:
                close_old_connections()
        with override_settings(MODELANVIL_PLUGINS={"runpod": compute_entry(tenant.tenant_id), "uppercase": task_entry(tenant.tenant_id)}):
            with patch("modelanvil.compute.service.compute_provider", return_value=provider):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(submit, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(ComputeAllocation.all_objects.count(), 1)
        self.assertEqual(Worker.all_objects.count(), 1)
        provider.create.assert_called_once()
