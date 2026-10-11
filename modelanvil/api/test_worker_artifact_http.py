"""Real HTTP qualification for bounded worker input artifact access."""
import hashlib
import io
import json
import tempfile
import uuid
from http.client import IncompleteRead
from threading import Event
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from django.conf import settings
from django.test import LiveServerTestCase, override_settings

from modelanvil.artifacts.models import Artifact, WorkerArtifactGrant
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.artifacts.worker_access import GrantDownload
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.models import Job, Worker, WorkerCredential, WorkerPool, generate_worker_credential
from modelanvil.worker_agent import RemoteExecutionContext, RemoteWorkerAgent, WorkerProtocolError


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "testserver"])
class WorkerArtifactHttpTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        config = override_settings(MODELANVIL={**settings.MODELANVIL,
                                             "artifact_backend": "filesystem", "artifact_root": root.name})
        config.enable()
        self.addCleanup(config.disable)
        self.tenant = Tenant.objects.create(slug="artifact-http", name="Artifact HTTP")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name="http-inputs")
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="http-worker")
        Job.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="http-input-job")
        self.admin_secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="owner", role=Role.OWNER, secret_hash=digest)
        self.worker_secret, digest = generate_worker_credential()
        WorkerCredential.objects.create(tenant_id=self.tenant.pk, worker=self.worker, secret_hash=digest)
        self.content = b"real HTTP artifact input\n" * 8192
        self.artifact = Artifact.objects.create(tenant_id=self.tenant.pk, storage_location_id="local",
                                               object_key="input/http.bin", sha256=hashlib.sha256(self.content).hexdigest(),
                                               byte_size=len(self.content), media_type="application/octet-stream")
        upload_staged_artifact(self.artifact, io.BytesIO(self.content), backend=artifact_storage_backend())
        self.opener = build_opener(ProxyHandler({}))

    def post(self, path, payload, secret):
        request = Request(self.live_server_url + path, data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"})
        with self.opener.open(request, timeout=5) as response:
            return response.status, json.load(response)

    def get(self, path, secret):
        return self.opener.open(Request(self.live_server_url + path,
                                       headers={"Authorization": f"Bearer {secret}"}), timeout=5)

    def claim_and_issue(self):
        status, claim = self.post("/api/v1/workers/claim/", {"worker_id": self.worker.pk, "pool": self.pool.name},
                                  self.worker_secret)
        self.assertEqual(status, 200)
        status, grant = self.post("/api/v1/workers/artifact-grants/", {
            "worker_id": self.worker.pk, "attempt_id": claim["attempt_id"],
            "artifact_id": str(self.artifact.artifact_id), "ttl_seconds": 60,
        }, self.admin_secret)
        self.assertEqual(status, 201)
        return grant

    def agent(self, **kwargs):
        return RemoteWorkerAgent(
            endpoint_url=self.live_server_url + "/api/v1/workers/", worker_token=self.worker_secret,
            worker_id=self.worker.pk, pool=self.pool.name, allow_loopback_http=True, **kwargs,
        )

    def issue_for_context(self, context):
        status, grant = self.post("/api/v1/workers/artifact-grants/", {
            "worker_id": self.worker.pk, "attempt_id": context.descriptor["attempt_id"],
            "artifact_id": str(self.artifact.artifact_id), "ttl_seconds": 60,
        }, self.admin_secret)
        self.assertEqual(status, 201)
        return grant

    def test_standalone_executor_receives_verified_input_bytes(self):
        self.assertTrue(callable(getattr(RemoteExecutionContext, "download_artifact", None)),
                        "Standalone executor has no verified input download operation")
        observed = {}

        def executor(_descriptor, context):
            grant = self.issue_for_context(context)
            observed["content"] = context.download_artifact(
                grant["grant_id"], sha256=self.artifact.sha256, byte_size=self.artifact.byte_size,
            )

        self.assertEqual(self.agent().run_once(executor),
                         {"claimed": True, "committed": True, "status": "succeeded"})
        self.assertEqual(observed["content"], self.content)

    def test_standalone_discovers_and_consumes_an_explicit_input_grant(self):
        self.assertTrue(callable(getattr(RemoteExecutionContext, "discover_artifacts", None)),
                        "Standalone context cannot discover its already-issued grants")
        observed = {}

        def executor(_descriptor, context):
            issued = self.issue_for_context(context)
            page = context.discover_artifacts()
            observed["page"] = page
            self.assertEqual(page["grants"][0]["grant_id"], issued["grant_id"])
            reference = page["grants"][0]
            observed["content"] = context.download_artifact(
                reference["grant_id"], sha256=reference["sha256"], byte_size=reference["byte_size"],
            )

        self.assertEqual(self.agent().run_once(executor),
                         {"claimed": True, "committed": True, "status": "succeeded"})
        self.assertEqual(observed["content"], self.content)
        self.assertIsNone(observed["page"]["next_cursor"])

    def test_standalone_explicit_cursor_traversal_discovers_all_issued_grants(self):
        observed = []

        def executor(_descriptor, context):
            issued_ids = {self.issue_for_context(context)["grant_id"] for _ in range(35)}
            page = context.discover_artifacts()
            self.assertEqual(len(page["grants"]), 32)
            received = [grant["grant_id"] for grant in page["grants"]]
            pages = 1
            while page["next_cursor"] is not None:
                pages += 1
                self.assertLessEqual(pages, 2)
                page = context.discover_artifacts(cursor=page["next_cursor"])
                received.extend(grant["grant_id"] for grant in page["grants"])
            self.assertEqual(received, sorted(issued_ids))
            self.assertEqual(len(received), 35)
            observed.append("complete")

        self.assertEqual(self.agent().run_once(executor)["status"], "succeeded")
        self.assertEqual(observed, ["complete"])

    def test_standalone_context_rejects_another_attempts_grant(self):
        observed = []

        def executor(_descriptor, context):
            grant = self.issue_for_context(context)
            other = RemoteExecutionContext(context.agent, {**context.descriptor, "attempt_id": str(uuid.uuid4())})
            with self.assertRaises(WorkerProtocolError):
                other.download_artifact(grant["grant_id"], sha256=self.artifact.sha256,
                                        byte_size=self.artifact.byte_size)
            observed.append("rejected")

        self.assertEqual(self.agent().run_once(executor)["status"], "succeeded")
        self.assertEqual(observed, ["rejected"])

    def test_standalone_client_rejects_corrupted_bytes_despite_matching_headers(self):
        observed = []
        original = GrantDownload.__next__

        def corrupt_chunk(stream):
            chunk = original(stream)
            return bytes([chunk[0] ^ 1]) + chunk[1:]

        def executor(_descriptor, context):
            grant = self.issue_for_context(context)
            with patch.object(GrantDownload, "__next__", corrupt_chunk):
                with self.assertRaises(WorkerProtocolError) as denied:
                    context.download_artifact(grant["grant_id"], sha256=self.artifact.sha256,
                                              byte_size=self.artifact.byte_size)
            observed.append(str(denied.exception))

        self.assertEqual(self.agent().run_once(executor)["status"], "succeeded")
        self.assertEqual(observed, ["Artifact integrity verification failed."])

    def test_standalone_client_discards_revoked_partial_download(self):
        observed = []
        release = Event()
        original_next = GrantDownload.__next__

        def gated_next(stream):
            if getattr(stream, "sent_chunk", False) and not release.wait(5):
                raise TimeoutError("Download synchronization timed out.")
            chunk = original_next(stream)
            stream.sent_chunk = True
            return chunk

        def executor(_descriptor, context):
            grant = self.issue_for_context(context)
            original_open = context.agent._opener.open

            def open_download(request, **kwargs):
                response = original_open(request, **kwargs)
                original_read = response.read1

                def read(size):
                    chunk = original_read(size)
                    if chunk and not release.is_set():
                        status, _ = self.post(
                            f"/api/v1/workers/artifact-grants/{grant['grant_id']}/revoke/", {}, self.admin_secret,
                        )
                        self.assertEqual(status, 200)
                        release.set()
                    return chunk

                response.read1 = read
                return response

            with patch.object(GrantDownload, "__next__", gated_next), \
                    patch.object(context.agent._opener, "open", side_effect=open_download):
                try:
                    with self.assertRaises(WorkerProtocolError):
                        context.download_artifact(grant["grant_id"], sha256=self.artifact.sha256,
                                                  byte_size=self.artifact.byte_size)
                    observed.append("discarded")
                finally:
                    release.set()

        self.assertEqual(self.agent().run_once(executor)["status"], "succeeded")
        self.assertEqual(observed, ["discarded"])

    def test_standalone_client_enforces_size_before_http(self):
        observed = []

        def executor(_descriptor, context):
            grant = self.issue_for_context(context)
            with patch.object(context.agent._opener, "open") as transport:
                with self.assertRaises(WorkerProtocolError):
                    context.download_artifact(grant["grant_id"], sha256=self.artifact.sha256,
                                              byte_size=self.artifact.byte_size)
                transport.assert_not_called()
            observed.append("refused")

        self.assertEqual(self.agent(artifact_max_bytes=64).run_once(executor)["status"], "succeeded")
        self.assertEqual(observed, ["refused"])

    def test_standalone_client_can_verify_empty_artifact(self):
        self.artifact = Artifact.objects.create(
            tenant_id=self.tenant.pk, storage_location_id="local", object_key="input/empty.bin",
            sha256=hashlib.sha256(b"").hexdigest(), byte_size=0, media_type="application/octet-stream",
        )
        upload_staged_artifact(self.artifact, io.BytesIO(b""), backend=artifact_storage_backend())
        observed = []

        def executor(_descriptor, context):
            grant = self.issue_for_context(context)
            observed.append(context.download_artifact(grant["grant_id"], sha256=self.artifact.sha256, byte_size=0))

        self.assertEqual(self.agent().run_once(executor)["status"], "succeeded")
        self.assertEqual(observed, [b""])

    def test_real_http_download_and_revocation(self):
        grant = self.claim_and_issue()
        with self.get(grant["download_path"], self.worker_secret) as response:
            self.assertEqual(response.headers.get("X-ModelAnvil-Attempt-ID"),
                             str(WorkerArtifactGrant.all_objects.get(grant_id=grant["grant_id"]).attempt.attempt_id))
            downloaded = response.read()
            self.assertEqual(downloaded, self.content)
            self.assertEqual(hashlib.sha256(downloaded).hexdigest(), self.artifact.sha256)
        status, _ = self.post(f"/api/v1/workers/artifact-grants/{grant['grant_id']}/revoke/", {}, self.admin_secret)
        self.assertEqual(status, 200)
        with self.assertRaises(HTTPError) as denied:
            self.get(grant["download_path"], self.worker_secret)
        try:
            self.assertEqual(denied.exception.code, 403)
        finally:
            denied.exception.close()

    def test_real_http_revocation_truncates_an_in_flight_download(self):
        grant = self.claim_and_issue()
        first_read = Event()
        release = Event()
        original = GrantDownload.__next__

        def gated_next(stream):
            if getattr(stream, "first_chunk_sent", False):
                if not release.wait(5):
                    raise TimeoutError("Download synchronization timed out.")
            chunk = original(stream)
            stream.first_chunk_sent = True
            first_read.set()
            return chunk

        with patch.object(GrantDownload, "__next__", gated_next):
            try:
                with self.get(grant["download_path"], self.worker_secret) as response:
                    self.assertTrue(first_read.wait(5))
                    self.assertEqual(response.read(64 * 1024), self.content[:64 * 1024])
                    status, _ = self.post(f"/api/v1/workers/artifact-grants/{grant['grant_id']}/revoke/", {},
                                         self.admin_secret)
                    self.assertEqual(status, 200)
                    release.set()
                    with self.assertRaises(IncompleteRead) as truncated:
                        response.read()
                    self.assertEqual(truncated.exception.partial, b"")
            finally:
                release.set()
