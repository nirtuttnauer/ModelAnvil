"""Outbound worker protocol exercised over the actual HTTP API."""
import importlib
import importlib.util
import inspect
import uuid
import threading
import io
import os
import subprocess
import sys
from datetime import timedelta
from django.utils import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from django.test import LiveServerTestCase, SimpleTestCase, override_settings

from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerCredential, WorkerPool, generate_worker_credential


def result_fixture():
    return {
        "schema_version": "1.0", "sample_id": str(uuid.uuid4()),
        "source_group_id": "remote-fixture",
        "blocks": [{"block_id": "b1", "type": "text", "text": "done"}],
        "provenance": {"source_snapshot_ref": "fixture", "source_record_key": "record",
                       "content_sha256": "0" * 64},
    }


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class RemoteWorkerApiTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        self.tenant = Tenant.objects.create(slug="remote-worker", name="Remote Worker")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name="cpu")
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="remote", slots=1)
        self.token, digest = generate_worker_credential()
        self.credential = WorkerCredential.objects.create(
            tenant_id=self.tenant.pk, worker=self.worker, secret_hash=digest,
        )
        self.job = Job.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="remote task", payload={"x": 7})

    def agent(self, **kwargs):
        self.assertIsNotNone(importlib.util.find_spec("modelanvil.worker_agent"),
                             "Standalone HTTP worker agent is missing")
        module = importlib.import_module("modelanvil.worker_agent")
        return module.RemoteWorkerAgent(
            endpoint_url=self.live_server_url + "/api/v1/workers/", worker_token=self.token,
            worker_id=self.worker.pk, pool=self.pool.name, allow_loopback_http=True, **kwargs,
        )

    def test_claim_heartbeat_and_commit_use_real_http(self):
        observed = {}
        result = result_fixture()

        def executor(descriptor, context):
            observed["payload"] = descriptor["payload"]
            observed["heartbeat"] = context.heartbeat(0.5)
            return result

        outcome = self.agent().run_once(executor)
        self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "succeeded"})
        self.assertEqual(observed, {"payload": {"x": 7}, "heartbeat": True})
        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        attempt = JobAttempt.all_objects.get(job=self.job)
        self.assertEqual(self.job.status, Job.Status.SUCCEEDED)
        self.assertEqual(self.worker.slots, 1)
        self.assertEqual(attempt.progress, 0.5)
        self.assertEqual(attempt.result_envelope, result)

    def test_remote_cancel_stops_success_and_commits_interruption(self):
        observed = {}

        def executor(_descriptor, context):
            Job.all_objects.filter(pk=self.job.pk).update(desired_action=Job.DesiredAction.CANCEL)
            observed["continue"] = context.heartbeat()
            return result_fixture()

        outcome = self.agent().run_once(executor)
        self.assertFalse(observed["continue"])
        self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "interrupted"})
        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.CANCELLED)
        self.assertEqual(self.worker.slots, 1)
        self.assertIsNone(JobAttempt.all_objects.get(job=self.job).result_envelope)

    def test_executor_failure_is_reported_without_exception_contents(self):
        def executor(_descriptor, _context):
            raise ValueError("private executor content")

        outcome = self.agent().run_once(executor)
        self.assertEqual(outcome["status"], "failed")
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.FAILED)
        self.assertNotIn("private", JobAttempt.all_objects.get(job=self.job).error)

    def test_invalid_result_fails_without_committing_an_invalid_envelope(self):
        outcome = self.agent().run_once(lambda _descriptor, _context: {"invalid": True})
        self.assertEqual(outcome["status"], "failed")
        attempt = JobAttempt.all_objects.get(job=self.job)
        self.assertIsNone(attempt.result_envelope)

    def test_fence_loss_abandons_result(self):
        observed = {}

        def executor(_descriptor, context):
            JobAttempt.all_objects.filter(job=self.job).update(fencing_token="replacement")
            observed["heartbeat"] = context.heartbeat()
            return result_fixture()

        outcome = self.agent().run_once(executor)
        self.assertFalse(observed["heartbeat"])
        self.assertEqual(outcome, {"claimed": True, "committed": False, "status": "lease_lost"})
        attempt = JobAttempt.all_objects.get(job=self.job)
        self.assertIsNone(attempt.result_envelope)
        self.assertEqual(attempt.status, JobAttempt.Status.RUNNING)

    def test_background_heartbeats_renew_during_executor(self):
        agent = self.agent(heartbeat_interval=0.02)
        heartbeats = []
        renewed = threading.Event()
        original_post = agent._post

        def post(operation, payload):
            response = original_post(operation, payload)
            if operation == "heartbeat/":
                heartbeats.append(response)
                if len(heartbeats) >= 2:
                    renewed.set()
            return response

        def executor(_descriptor, _context):
            self.assertTrue(renewed.wait(3))
            return result_fixture()

        with patch.object(agent, "_post", side_effect=post):
            outcome = agent.run_once(executor)
        self.assertTrue(outcome["committed"])
        self.assertEqual(outcome["status"], "succeeded")
        self.assertGreaterEqual(len(heartbeats), 2)
        self.assertGreater(heartbeats[-1]["lease_expires_at"], heartbeats[0]["lease_expires_at"])

    def test_expired_descriptor_never_runs_or_commits(self):
        agent = self.agent()
        original_post = agent._post

        def post(operation, payload):
            result = original_post(operation, payload)
            if operation == "claim/":
                result["lease_expires_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
            return result

        executor = Mock()
        with patch.object(agent, "_post", side_effect=post):
            outcome = agent.run_once(executor)
        executor.assert_not_called()
        self.assertEqual(outcome, {"claimed": True, "committed": False, "status": "lease_lost"})
        self.assertEqual(JobAttempt.all_objects.get(job=self.job).status, JobAttempt.Status.RUNNING)

    def test_revoked_worker_cannot_claim(self):
        self.credential.revoked_at = timezone.now()
        self.credential.save(update_fields=["revoked_at"])
        with self.assertRaises(RuntimeError) as caught:
            self.agent().run_once(lambda _descriptor, _context: None)
        self.assertNotIn(self.token, str(caught.exception))
        self.assertFalse(JobAttempt.all_objects.filter(job=self.job).exists())

    def test_once_cli_uses_trusted_executor_and_environment_credential(self):
        module = importlib.import_module("modelanvil.worker_agent")
        with patch.dict(os.environ, {"MODELANVIL_WORKER_TOKEN": self.token}), \
                patch.object(module, "load_executor", return_value=lambda _descriptor, _context: result_fixture()), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            code = module.main(["--endpoint", self.live_server_url + "/api/v1/workers/",
                                "--worker-id", str(self.worker.pk), "--pool", self.pool.name,
                                "--executor", "trusted.module:execute", "--once", "--allow-loopback-http"])
        self.assertEqual(code, 0)
        self.assertIn('"committed": true', output.getvalue())
        self.assertNotIn(self.token, output.getvalue())

    def test_lost_commit_response_does_not_rerun_executor(self):
        agent = self.agent()
        original_post = agent._post
        module = importlib.import_module("modelanvil.worker_agent")

        def post(operation, payload):
            response = original_post(operation, payload)
            if operation == "result/":
                raise module.WorkerProtocolError("Lost acknowledgement.")
            return response

        executor = Mock(return_value=result_fixture())
        with patch.object(agent, "_post", side_effect=post):
            outcome = agent.run_once(executor)
        executor.assert_called_once()
        self.assertEqual(outcome, {"claimed": True, "committed": False, "status": "commit_unconfirmed"})
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.SUCCEEDED)


    def test_pool_metadata_policy_withholds_result_before_http(self):
        WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="metadata_only")
        agent = self.agent()
        original_post = agent._post
        transmitted = []

        def post(operation, payload):
            if operation == "result/":
                transmitted.append(dict(payload))
            return original_post(operation, payload)

        result = result_fixture()
        result["blocks"][0]["text"] = "private sample must not leave worker"
        with patch.object(agent, "_post", side_effect=post):
            outcome = agent.run_once(lambda _descriptor, _context: result)
        self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "failed"})
        self.assertEqual(set(transmitted[0]), {"worker_id", "attempt_id", "fencing_token", "status"})
        self.assertNotIn("private sample", str(transmitted))
        attempt = JobAttempt.all_objects.get(job=self.job)
        self.assertIsNone(attempt.result_envelope)
        self.assertEqual(attempt.error, "")


    def test_local_metadata_policy_cannot_be_weakened_by_pool_or_job(self):
        module = importlib.import_module("modelanvil.worker_agent")
        self.assertIn("result_egress", inspect.signature(module.RemoteWorkerAgent).parameters)
        Job.all_objects.filter(pk=self.job.pk).update(payload={"result_egress": "envelope"})
        agent = self.agent(result_egress="metadata_only")
        observed = []
        original_post = agent._post

        def post(operation, payload):
            if operation == "result/":
                observed.append(dict(payload))
            return original_post(operation, payload)

        with patch.object(agent, "_post", side_effect=post):
            outcome = agent.run_once(lambda _descriptor, _context: result_fixture())
        self.assertEqual(outcome["status"], "failed")
        self.assertTrue(outcome["committed"])
        self.assertEqual(set(observed[0]), {"worker_id", "attempt_id", "fencing_token", "status"})

    def test_pool_policy_tightening_is_observed_before_result_http(self):
        def executor(_descriptor, _context):
            WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="metadata_only")
            return result_fixture()

        self.assertEqual(self.agent().run_once(executor),
                         {"claimed": True, "committed": True, "status": "failed"})
        self.assertIsNone(JobAttempt.all_objects.get(job=self.job).result_envelope)


    def test_cli_can_pin_local_metadata_only_policy(self):
        module = importlib.import_module("modelanvil.worker_agent")
        with patch.dict(os.environ, {"MODELANVIL_WORKER_TOKEN": self.token}), \
                patch.object(module, "load_executor", return_value=lambda _descriptor, _context: result_fixture()), \
                patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
            try:
                code = module.main(["--endpoint", self.live_server_url + "/api/v1/workers/",
                                    "--worker-id", str(self.worker.pk), "--pool", self.pool.name,
                                    "--executor", "trusted.module:execute", "--once", "--allow-loopback-http",
                                    "--result-egress", "metadata_only"])
            except SystemExit:
                self.fail("CLI must accept the local result-egress policy option")
        self.assertEqual(code, 0)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.FAILED)
        self.assertIsNone(JobAttempt.all_objects.get(job=self.job).result_envelope)


    def test_cli_sets_operator_artifact_byte_cap(self):
        module = importlib.import_module("modelanvil.worker_agent")
        observed = []

        def executor(_descriptor, context):
            observed.append(context.agent.artifact_max_bytes)

        with patch.dict(os.environ, {"MODELANVIL_WORKER_TOKEN": self.token}), \
                patch.object(module, "load_executor", return_value=executor), \
                patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
            try:
                code = module.main(["--endpoint", self.live_server_url + "/api/v1/workers/",
                                    "--worker-id", str(self.worker.pk), "--pool", self.pool.name,
                                    "--executor", "trusted.module:execute", "--once", "--allow-loopback-http",
                                    "--artifact-max-bytes", "4096"])
            except SystemExit:
                self.fail("CLI must accept the operator artifact cap")
        self.assertEqual(code, 0)
        self.assertEqual(observed, [4096])

    def test_metadata_only_executor_failure_sends_no_free_form_error(self):
        WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="metadata_only")

        def executor(_descriptor, _context):
            raise ValueError("private diagnostic")

        self.assertEqual(self.agent().run_once(executor),
                         {"claimed": True, "committed": True, "status": "failed"})
        self.assertEqual(JobAttempt.all_objects.get(job=self.job).error, "")

    def test_metadata_only_executor_can_commit_status_without_a_sample(self):
        WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="metadata_only")
        self.assertEqual(self.agent().run_once(lambda _descriptor, _context: None),
                         {"claimed": True, "committed": True, "status": "succeeded"})

    def test_unknown_pool_policy_never_executes(self):
        WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="unknown")
        executor = Mock()
        with self.assertRaises(RuntimeError):
            self.agent().run_once(executor)
        executor.assert_not_called()
        self.assertIsNone(JobAttempt.all_objects.get(job=self.job).result_envelope)

    def test_pool_relaxation_does_not_relax_this_attempt(self):
        WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="metadata_only")

        def executor(_descriptor, _context):
            WorkerPool.all_objects.filter(pk=self.pool.pk).update(result_egress="envelope")
            return result_fixture()

        self.assertEqual(self.agent().run_once(executor),
                         {"claimed": True, "committed": True, "status": "failed"})
        self.assertIsNone(JobAttempt.all_objects.get(job=self.job).result_envelope)


class RemoteWorkerSecurityTests(SimpleTestCase):
    def agent(self, endpoint="https://worker.example/api/v1/workers/", **kwargs):
        return importlib.import_module("modelanvil.worker_agent").RemoteWorkerAgent(
            endpoint_url=endpoint, worker_token="mkw_" + "a" * 43,
            worker_id=1, pool="cpu", **kwargs,
        )

    def test_http_requires_explicit_loopback_opt_in(self):
        with self.assertRaises(ValueError):
            self.agent("http://127.0.0.1:8000/api/v1/workers/")
        self.agent("http://127.0.0.1:8000/api/v1/workers/", allow_loopback_http=True)
        with self.assertRaises(ValueError):
            self.agent("http://example.org/api/v1/workers/", allow_loopback_http=True)

    def test_artifact_cap_is_operator_configured_and_bounded(self):
        module = importlib.import_module("modelanvil.worker_agent")
        self.assertIn("artifact_max_bytes", inspect.signature(module.RemoteWorkerAgent).parameters,
                      "Worker has no operator-configured artifact size boundary")
        self.assertEqual(self.agent().artifact_max_bytes, 16 * 1024 * 1024)
        self.assertEqual(self.agent(artifact_max_bytes=64).artifact_max_bytes, 64)
        self.assertEqual(self.agent(artifact_max_bytes=64 * 1024 * 1024).artifact_max_bytes, 64 * 1024 * 1024)
        for size in (0, -1, True, False, 1.5, "64", None, 64 * 1024 * 1024 + 1):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    self.agent(artifact_max_bytes=size)

    def test_urls_cannot_contain_credentials_queries_or_fragments(self):
        for url in ["https://secret@example.org/api/v1/workers/",
                    "https://example.org/api/v1/workers/?token=secret",
                    "https://example.org/api/v1/workers/#secret",
                    "file:///api/v1/workers/", "https:///api/v1/workers/"]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError) as caught:
                    self.agent(url)
                self.assertNotIn("secret", str(caught.exception))

    def test_redirect_is_not_followed_or_given_the_worker_credential(self):
        paths = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                paths.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/credential-leak")
                self.end_headers()

            def do_GET(self):
                paths.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            agent = self.agent(f"http://127.0.0.1:{server.server_port}/api/v1/workers/",
                               allow_loopback_http=True)
            with self.assertRaises(RuntimeError) as caught:
                agent.run_once(lambda _descriptor, _context: None)
            self.assertNotIn("mkw_", str(caught.exception))
            self.assertEqual(paths, ["/api/v1/workers/claim/"])
        finally:
            server.shutdown()
            thread.join(2)
            server.server_close()

    def test_import_does_not_initialize_django(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; import modelanvil.worker_agent; "
             "assert not any(k == 'django' or k.startswith('django.') for k in sys.modules)"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_transport_rejects_non_objects_and_oversized_json(self):
        agent = self.agent()
        for body in [b'[]', b'{bad-json', b' ' * (1024 * 1024 + 1)]:
            with self.subTest(size=len(body)):
                with patch.object(agent._opener, "open", return_value=io.BytesIO(body)):
                    with self.assertRaises(RuntimeError):
                        agent._post("claim/", {"worker_id": 1, "pool": "cpu"})
