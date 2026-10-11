"""Attempt-scoped input downloads, never tenant-wide storage credentials."""
import hashlib
import io
import tempfile
import uuid
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings as django_settings
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied

from modelanvil.artifacts.models import Artifact, WorkerArtifactGrant
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.core.models import AuditEvent
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerCredential, WorkerPool, generate_worker_credential


@override_settings(ALLOWED_HOSTS=["testserver"])
class WorkerArtifactApiTests(TransactionTestCase):
    def setUp(self):
        self.client = APIClient()
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        settings = override_settings(MODELANVIL={**django_settings.MODELANVIL,
                                               "artifact_backend": "filesystem", "artifact_root": root.name})
        settings.enable()
        self.addCleanup(settings.disable)
        self.tenant = Tenant.objects.create(slug="worker-artifacts", name="Worker Artifacts")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name="private", result_egress="metadata_only")
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="worker")
        self.job = Job.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="input-job")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="owner", role=Role.OWNER, secret_hash=digest)
        self.admin_auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        secret, digest = generate_worker_credential()
        self.credential = WorkerCredential.objects.create(tenant_id=self.tenant.pk, worker=self.worker, secret_hash=digest)
        self.worker_auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        claim = self.client.post("/api/v1/workers/claim/", {"worker_id": self.worker.pk, "pool": self.pool.name},
                                 format="json", **self.worker_auth)
        self.assertEqual(claim.status_code, 200, claim.content)
        self.descriptor = claim.json()
        self.content = b"pinned input bytes\n"
        self.artifact = Artifact.objects.create(
            tenant_id=self.tenant.pk, storage_location_id="local", object_key="inputs/pinned.bin",
            sha256=hashlib.sha256(self.content).hexdigest(), byte_size=len(self.content),
            media_type="application/octet-stream",
        )
        upload_staged_artifact(self.artifact, io.BytesIO(self.content), backend=artifact_storage_backend())
        self.issue_url = "/api/v1/workers/artifact-grants/"
        self.payload = {"worker_id": self.worker.pk, "attempt_id": self.descriptor["attempt_id"],
                        "artifact_id": str(self.artifact.artifact_id), "ttl_seconds": 60}

    def issue(self, payload=None, auth=None):
        return self.client.post(self.issue_url, self.payload if payload is None else payload,
                                format="json", **(self.admin_auth if auth is None else auth))

    def test_admin_grants_worker_one_committed_input_download(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        grant = issued.json()
        self.assertEqual(grant["artifact_id"], str(self.artifact.artifact_id))
        response = self.client.get(grant["download_path"], **self.worker_auth)
        self.assertEqual(response.status_code, 200, response.content if not response.streaming else "")
        try:
            self.assertEqual(b"".join(response.streaming_content), self.content)
            self.assertEqual(response["Content-Length"], str(len(self.content)))
            self.assertEqual(response["ETag"], f'"{self.artifact.sha256}"')
            self.assertEqual(response["Cache-Control"], "private, no-store")
        finally:
            response.close()
        # A grant never enables the general tenant artifact API.
        denied = self.client.get(f"/api/v1/artifacts/{self.artifact.artifact_id}/download/", **self.worker_auth)
        self.assertEqual(denied.status_code, 401)

    def discover(self, payload=None, auth=None):
        identity = {"worker_id": self.worker.pk, "attempt_id": self.descriptor["attempt_id"],
                    "fencing_token": self.descriptor["fencing_token"]}
        return self.client.post(self.issue_url + "discover/", identity if payload is None else payload,
                                format="json", **(self.worker_auth if auth is None else auth))

    def discovery_identity(self, **changes):
        return {"worker_id": self.worker.pk, "attempt_id": self.descriptor["attempt_id"],
                "fencing_token": self.descriptor["fencing_token"], **changes}

    def test_worker_discovers_only_explicitly_authorized_input_metadata(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        before = WorkerArtifactGrant.all_objects.count()
        with patch("modelanvil.artifacts.worker_access.artifact_storage_backend") as storage:
            response = self.discover()
            self.assertEqual(response.status_code, 200, response.content)
            storage.assert_not_called()
        self.assertEqual(response.json(), {
            "attempt_id": self.descriptor["attempt_id"], "next_cursor": None,
            "grants": [{"grant_id": issued.json()["grant_id"], "artifact_id": str(self.artifact.artifact_id),
                        "sha256": self.artifact.sha256, "byte_size": self.artifact.byte_size,
                        "expires_at": issued.json()["expires_at"]}],
        })
        self.assertEqual(WorkerArtifactGrant.all_objects.count(), before)

    def test_discovery_has_bounded_stable_cursor_pages(self):
        issued_ids = []
        for _ in range(35):
            response = self.issue()
            self.assertEqual(response.status_code, 201, response.content)
            issued_ids.append(response.json()["grant_id"])
        expected = sorted(issued_ids)
        first = self.discover()
        self.assertEqual(first.status_code, 200, first.content)
        page = first.json()
        self.assertEqual([grant["grant_id"] for grant in page["grants"]], expected[:32])
        self.assertEqual(page["next_cursor"], expected[31])
        second = self.discover({"worker_id": self.worker.pk, "attempt_id": self.descriptor["attempt_id"],
                                "fencing_token": self.descriptor["fencing_token"], "cursor": page["next_cursor"]})
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual([grant["grant_id"] for grant in second.json()["grants"]], expected[32:])
        self.assertIsNone(second.json()["next_cursor"])

    def test_discovery_never_auto_issues_grants(self):
        response = self.discover()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"attempt_id": self.descriptor["attempt_id"],
                                          "grants": [], "next_cursor": None})
        self.assertEqual(WorkerArtifactGrant.all_objects.count(), 0)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_discovery_requires_bound_worker_credentials_and_post(self):
        self.assertEqual(self.discover(auth=self.admin_auth).status_code, 403)
        self.assertEqual(self.client.post(self.issue_url + "discover/", self.discovery_identity(),
                                         format="json").status_code, 401)
        self.assertEqual(self.client.get(self.issue_url + "discover/", **self.worker_auth).status_code, 405)
        self.assertEqual(self.discover(self.discovery_identity(worker_id=self.worker.pk + 100)).status_code, 403)
        self.assertEqual(self.discover(self.discovery_identity(attempt_id=str(uuid.uuid4()))).status_code, 404)
        self.assertEqual(self.discover(self.discovery_identity(fencing_token="wrong-fence")).status_code, 403)

    def test_worker_execution_endpoints_do_not_repair_padded_fencing_identity(self):
        fence = self.descriptor["fencing_token"]
        for value in (" " + fence, fence + " "):
            for operation in ("artifact-grants/discover/", "heartbeat/", "result/"):
                with self.subTest(operation=operation, padding="prefix" if value.startswith(" ") else "suffix"):
                    payload = self.discovery_identity(fencing_token=value)
                    if operation == "result/":
                        payload["status"] = "succeeded"
                    response = self.client.post("/api/v1/workers/" + operation, payload,
                                                format="json", **self.worker_auth)
                    self.assertEqual(response.status_code, 403)

    def test_discovery_excludes_revoked_expired_and_tombstoned_grants(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201)
        grant = WorkerArtifactGrant.all_objects.get(grant_id=issued.json()["grant_id"])
        for model, pk, changes in (
            (WorkerArtifactGrant, grant.pk, {"revoked_at": timezone.now()}),
            (WorkerArtifactGrant, grant.pk, {"expires_at": timezone.now() - timedelta(seconds=1)}),
            (Artifact, self.artifact.pk, {"state": Artifact.State.TOMBSTONED}),
            (Artifact, self.artifact.pk, {"object_key": "changed-private-path"}),
        ):
            previous = model.all_objects.filter(pk=pk).values(*changes).get()
            try:
                model.all_objects.filter(pk=pk).update(**changes)
                response = self.discover()
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["grants"], [])
            finally:
                model.all_objects.filter(pk=pk).update(**previous)

    def test_discovery_checks_authority_even_without_grants(self):
        for model, pk, changes, expected in (
            (Job, self.job.pk, {"desired_action": Job.DesiredAction.CANCEL}, 403),
            (Job, self.job.pk, {"status": Job.Status.SUCCEEDED}, 403),
            (Worker, self.worker.pk, {"status": Worker.Status.OFFLINE}, 403),
            (WorkerCredential, self.credential.pk, {"revoked_at": timezone.now()}, 401),
        ):
            previous = model.all_objects.filter(pk=pk).values(*changes).get()
            try:
                model.all_objects.filter(pk=pk).update(**changes)
                self.assertEqual(self.discover().status_code, expected)
            finally:
                model.all_objects.filter(pk=pk).update(**previous)

    def test_discovery_rechecks_credential_after_initial_authentication(self):
        from modelanvil.artifacts.worker_access import _locked_execution

        def revoke_after_execution_check(*args, **kwargs):
            attempt = _locked_execution(*args, **kwargs)
            WorkerCredential.all_objects.filter(pk=self.credential.pk).update(revoked_at=timezone.now())
            return attempt

        with patch("modelanvil.artifacts.worker_access._locked_execution", side_effect=revoke_after_execution_check):
            self.assertEqual(self.discover().status_code, 403)

    def test_discovery_does_not_return_metadata_if_lease_expires_during_page_validation(self):
        from modelanvil.artifacts.worker_access import authorized_download

        self.assertEqual(self.issue().status_code, 201)
        with patch("modelanvil.artifacts.worker_access.timezone.now", return_value=timezone.now()) as clock:
            @contextmanager
            def expire_after_validation(**scope):
                with authorized_download(**scope) as authorized:
                    yield authorized
                clock.return_value = parse_datetime(self.descriptor["lease_expires_at"])

            with patch("modelanvil.artifacts.worker_access.authorized_download", expire_after_validation):
                self.assertEqual(self.discover().status_code, 403)

    def test_discovery_does_not_return_metadata_if_credential_expires_during_page_validation(self):
        from modelanvil.artifacts.worker_access import authorized_download

        self.assertEqual(self.issue().status_code, 201)
        self.credential.expires_at = timezone.now() + timedelta(seconds=1)
        self.credential.save(update_fields=("expires_at",))
        with patch("modelanvil.artifacts.worker_access.timezone.now", return_value=timezone.now()) as clock:
            @contextmanager
            def expire_after_validation(**scope):
                with authorized_download(**scope) as authorized:
                    yield authorized
                clock.return_value = self.credential.expires_at

            with patch("modelanvil.artifacts.worker_access.authorized_download", expire_after_validation):
                self.assertEqual(self.discover().status_code, 403)

    def test_discovery_omits_a_grant_that_expires_during_page_validation(self):
        from modelanvil.artifacts.worker_access import authorized_download

        with patch("modelanvil.artifacts.worker_access.timezone.now", return_value=timezone.now()) as clock:
            issued = self.issue({**self.payload, "ttl_seconds": 1})
            self.assertEqual(issued.status_code, 201)
            expires_at = parse_datetime(issued.json()["expires_at"])

            @contextmanager
            def expire_after_validation(**scope):
                with authorized_download(**scope) as authorized:
                    yield authorized
                clock.return_value = expires_at

            with patch("modelanvil.artifacts.worker_access.authorized_download", expire_after_validation):
                response = self.discover()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["grants"], [])

    def test_discovery_cursor_is_not_repaired(self):
        for cursor in ("../private", "F" * 32, str(uuid.uuid4()).upper(), " " + str(uuid.uuid4()), None):
            self.assertEqual(self.discover(self.discovery_identity(cursor=cursor)).status_code, 400)

    def test_discovery_conceals_attempts_from_other_workers_and_tenants(self):
        self.assertEqual(self.issue().status_code, 201)
        foreign_tenant = Tenant.objects.create(slug="foreign-discovery", name="Other")
        foreign_pool = WorkerPool.objects.create(tenant_id=foreign_tenant.pk, name="foreign")
        for tenant, pool in ((self.tenant, self.pool), (foreign_tenant, foreign_pool)):
            other = Worker.objects.create(tenant_id=tenant.pk, pool=pool, name="other-discovery")
            secret, digest = generate_worker_credential()
            WorkerCredential.objects.create(tenant_id=tenant.pk, worker=other, secret_hash=digest)
            response = self.discover(self.discovery_identity(worker_id=other.pk),
                                     auth={"HTTP_AUTHORIZATION": f"Bearer {secret}"})
            self.assertEqual(response.status_code, 404, response.content)

    def test_discovery_excludes_other_attempts_on_the_same_worker(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201)
        Worker.all_objects.filter(pk=self.worker.pk).update(slots=1)
        Job.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="second-input-job")
        claim = self.client.post("/api/v1/workers/claim/", {"worker_id": self.worker.pk, "pool": self.pool.name},
                                 format="json", **self.worker_auth)
        self.assertEqual(claim.status_code, 200, claim.content)
        self.assertTrue(claim.json()["claimed"])
        second_grant = self.issue({**self.payload, "attempt_id": claim.json()["attempt_id"]})
        self.assertEqual(second_grant.status_code, 201, second_grant.content)
        response = self.discover()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([grant["grant_id"] for grant in response.json()["grants"]], [issued.json()["grant_id"]])

    def test_discovery_advances_cursor_past_a_page_of_ineligible_grants(self):
        old_artifact = self.artifact
        for _ in range(32):
            self.assertEqual(self.issue().status_code, 201)
        self.large_artifact()
        issued = self.issue()
        self.assertEqual(issued.status_code, 201)
        last_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        WorkerArtifactGrant.all_objects.filter(grant_id=issued.json()["grant_id"]).update(grant_id=last_id)
        Artifact.all_objects.filter(pk=old_artifact.pk).update(state=Artifact.State.TOMBSTONED)
        first = self.discover()
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["grants"], [])
        self.assertIsNotNone(first.json()["next_cursor"])
        second = self.discover(self.discovery_identity(cursor=first.json()["next_cursor"]))
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual([grant["grant_id"] for grant in second.json()["grants"]], [last_id])
        self.assertIsNone(second.json()["next_cursor"])

    def large_artifact(self):
        self.content = b"x" * (128 * 1024)
        self.artifact = Artifact.objects.create(
            tenant_id=self.tenant.pk, storage_location_id="local", object_key="inputs/large.bin",
            sha256=hashlib.sha256(self.content).hexdigest(), byte_size=len(self.content),
            media_type="application/octet-stream",
        )
        upload_staged_artifact(self.artifact, io.BytesIO(self.content), backend=artifact_storage_backend())
        self.payload["artifact_id"] = str(self.artifact.artifact_id)

    def test_revocation_stops_an_already_open_download(self):
        self.large_artifact()
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        grant = issued.json()
        response = self.client.get(grant["download_path"], **self.worker_auth)
        self.assertEqual(response.status_code, 200)
        try:
            chunks = iter(response.streaming_content)
            self.assertEqual(next(chunks), self.content[:64 * 1024])
            revoked = self.client.post(f"{self.issue_url}{grant['grant_id']}/revoke/", {},
                                       format="json", **self.admin_auth)
            self.assertEqual(revoked.status_code, 200, revoked.content)
            self.assertEqual(b"".join(chunks), b"")
        finally:
            response.close()
        denied = self.client.get(grant["download_path"], **self.worker_auth)
        self.assertEqual(denied.status_code, 403)

    def test_worker_credential_revocation_stops_an_already_open_download(self):
        self.large_artifact()
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        response = self.client.get(issued.json()["download_path"], **self.worker_auth)
        self.assertEqual(response.status_code, 200)
        try:
            chunks = iter(response.streaming_content)
            self.assertEqual(next(chunks), self.content[:64 * 1024])
            revoked = self.client.post(f"/api/v1/workers/{self.worker.pk}/credential/revoke/", {},
                                       format="json", **self.admin_auth)
            self.assertEqual(revoked.status_code, 200, revoked.content)
            self.assertEqual(b"".join(chunks), b"")
        finally:
            response.close()

    def test_tenant_suspension_stops_an_already_open_download(self):
        self.large_artifact()
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        response = self.client.get(issued.json()["download_path"], **self.worker_auth)
        self.assertEqual(response.status_code, 200)
        try:
            chunks = iter(response.streaming_content)
            self.assertEqual(next(chunks), self.content[:64 * 1024])
            self.tenant.status = "suspended"
            self.tenant.save(update_fields=("status",))
            self.assertEqual(b"".join(chunks), b"")
        finally:
            response.close()

    def test_grant_scope_and_expiry_cannot_be_changed_after_issue(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        grant = WorkerArtifactGrant.all_objects.get(grant_id=issued.json()["grant_id"])
        grant.expires_at += timedelta(seconds=30)
        with self.assertRaisesRegex(ValueError, "immutable"):
            grant.save()

    def test_closing_a_response_before_iteration_prevents_further_reads(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        response = self.client.get(issued.json()["download_path"], **self.worker_auth)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(b"".join(response.streaming_content), b"")

    def test_grant_issue_rolls_back_if_its_audit_record_fails(self):
        with patch("modelanvil.api.views.worker_artifacts.record_audit", side_effect=PermissionDenied()):
            response = self.issue()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkerArtifactGrant.all_objects.count(), 0)

    def test_grant_audit_identifies_the_administrator_without_content_or_credentials(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        audit = AuditEvent.all_objects.get(resource_type="worker_artifact_grant", action="create")
        administrator = ApiKey.objects.get(tenant=self.tenant, name="owner")
        self.assertEqual(audit.actor_id, administrator.pk)
        self.assertEqual(audit.actor_kind, "api_key")
        self.assertEqual(audit.input_snapshot, {"worker_id": self.worker.pk,
                                              "attempt_id": self.descriptor["attempt_id"],
                                              "artifact_id": str(self.artifact.artifact_id)})

    def test_unmapped_storage_location_cannot_receive_a_local_download_grant(self):
        Artifact.all_objects.filter(pk=self.artifact.pk).update(storage_location_id="unmapped-private-storage")
        response = self.issue()
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(WorkerArtifactGrant.all_objects.count(), 0)

    def test_offline_worker_cannot_use_a_grant(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        Worker.all_objects.filter(pk=self.worker.pk).update(status=Worker.Status.OFFLINE)
        response = self.client.get(issued.json()["download_path"], **self.worker_auth)
        self.assertEqual(response.status_code, 403)

    def test_unknown_execution_action_fails_closed(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        Job.all_objects.filter(pk=self.job.pk).update(desired_action="unknown")
        self.assertEqual(self.client.get(issued.json()["download_path"], **self.worker_auth).status_code, 403)

    def test_pool_tenant_scope_is_rechecked_at_download(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        other = Tenant.objects.create(slug="reassigned-pool", name="Other")
        WorkerPool.all_objects.filter(pk=self.pool.pk).update(tenant_id=other.pk)
        self.assertEqual(self.client.get(issued.json()["download_path"], **self.worker_auth).status_code, 403)

    def test_download_grant_never_enables_uploads_or_credentialless_access(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        path = issued.json()["download_path"]
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post(path, {}, format="json", **self.worker_auth).status_code, 405)
        for action in ("upload", "transfers"):
            with self.subTest(action=action):
                response = self.client.post(f"/api/v1/artifacts/{self.artifact.artifact_id}/{action}/", {},
                                            format="json", **self.worker_auth)
                self.assertEqual(response.status_code, 401)

    def test_foreign_administrator_cannot_revoke_a_grant(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        other = Tenant.objects.create(slug="foreign-revoker", name="Other")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=other, name="owner", role=Role.OWNER, secret_hash=digest)
        response = self.client.post(f"{self.issue_url}{issued.json()['grant_id']}/revoke/", {}, format="json",
                                    HTTP_AUTHORIZATION=f"Bearer {secret}")
        self.assertEqual(response.status_code, 404)
        grant = WorkerArtifactGrant.all_objects.get(grant_id=issued.json()["grant_id"])
        self.assertIsNone(grant.revoked_at)

    def test_only_administrators_issue_and_revoke_grants(self):
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="engineer", role=Role.ENGINEER, secret_hash=digest)
        engineer_auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        self.assertEqual(self.issue(auth=engineer_auth).status_code, 403)
        self.assertEqual(self.issue(auth=self.worker_auth).status_code, 401)
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        revoke_path = f"{self.issue_url}{issued.json()['grant_id']}/revoke/"
        for auth, expected in [(engineer_auth, 403), (self.worker_auth, 401)]:
            with self.subTest(role=expected):
                response = self.client.post(revoke_path, {}, format="json", **auth)
                self.assertEqual(response.status_code, expected)
        self.assertEqual(self.client.get(issued.json()["download_path"], **self.admin_auth).status_code, 403)

    def test_grant_is_not_authority_for_another_worker_or_tenant(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        download_path = issued.json()["download_path"]
        other = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="other-worker")
        secret, digest = generate_worker_credential()
        WorkerCredential.objects.create(tenant_id=self.tenant.pk, worker=other, secret_hash=digest)
        response = self.client.get(download_path, HTTP_AUTHORIZATION=f"Bearer {secret}")
        self.assertEqual(response.status_code, 404)
        other_tenant = Tenant.objects.create(slug="other-worker-artifacts", name="Other")
        other_pool = WorkerPool.objects.create(tenant_id=other_tenant.pk, name="other")
        foreign = Worker.objects.create(tenant_id=other_tenant.pk, pool=other_pool, name="foreign-worker")
        secret, digest = generate_worker_credential()
        WorkerCredential.objects.create(tenant_id=other_tenant.pk, worker=foreign, secret_hash=digest)
        response = self.client.get(download_path, HTTP_AUTHORIZATION=f"Bearer {secret}")
        self.assertEqual(response.status_code, 404)

    def test_foreign_artifacts_and_execution_references_are_concealed(self):
        other = Tenant.objects.create(slug="foreign-input", name="Other")
        artifact = Artifact.objects.create(tenant_id=other.pk, storage_location_id="local", object_key="input.bin",
                                           sha256=self.artifact.sha256, byte_size=len(self.content), media_type="text/plain")
        self.assertEqual(self.issue({**self.payload, "artifact_id": str(artifact.artifact_id)}).status_code, 404)
        other_worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="different-owner")
        self.assertEqual(self.issue({**self.payload, "worker_id": other_worker.pk}).status_code, 404)
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=other, name="owner", role=Role.OWNER, secret_hash=digest)
        self.assertEqual(self.issue(auth={"HTTP_AUTHORIZATION": f"Bearer {secret}"}).status_code, 404)
        self.assertEqual(WorkerArtifactGrant.all_objects.count(), 0)

    def test_ttl_is_bounded_and_does_not_outlive_the_issued_lease(self):
        for ttl in (0, 301, True, 1.5):
            with self.subTest(ttl=ttl):
                self.assertEqual(self.issue({**self.payload, "ttl_seconds": ttl}).status_code, 400)
        issued = self.issue({**self.payload, "ttl_seconds": 300})
        self.assertEqual(issued.status_code, 201, issued.content)
        self.assertLessEqual(parse_datetime(issued.json()["expires_at"]),
                             parse_datetime(self.descriptor["lease_expires_at"]))

    def test_heartbeat_cannot_extend_a_short_lived_grant(self):
        issued = self.issue({**self.payload, "ttl_seconds": 1})
        self.assertEqual(issued.status_code, 201, issued.content)
        grant = WorkerArtifactGrant.all_objects.get(grant_id=issued.json()["grant_id"])
        heartbeat = self.client.post("/api/v1/workers/heartbeat/", {
            "worker_id": self.worker.pk, "attempt_id": self.descriptor["attempt_id"],
            "fencing_token": self.descriptor["fencing_token"], "progress": 0,
        }, format="json", **self.worker_auth)
        self.assertEqual(heartbeat.status_code, 200, heartbeat.content)
        grant.attempt.refresh_from_db()
        self.assertLess(grant.expires_at, grant.attempt.lease_expires_at)
        with patch("modelanvil.artifacts.worker_access.timezone.now", return_value=grant.expires_at):
            self.assertEqual(self.client.get(issued.json()["download_path"], **self.worker_auth).status_code, 403)

    def test_staging_versioned_or_tombstoned_artifacts_are_denied(self):
        for field, value in [("state", Artifact.State.STAGING), ("state", Artifact.State.TOMBSTONED),
                             ("object_version", "unsupported-version")]:
            with self.subTest(field=field, value=value):
                Artifact.all_objects.filter(pk=self.artifact.pk).update(state=Artifact.State.COMMITTED,
                                                                       object_version=None)
                Artifact.all_objects.filter(pk=self.artifact.pk).update(**{field: value})
                self.assertEqual(self.issue().status_code, 403)
        self.assertEqual(WorkerArtifactGrant.all_objects.count(), 0)

    def test_backend_change_invalidates_an_existing_grant(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        with tempfile.TemporaryDirectory() as other_root:
            with override_settings(MODELANVIL={**django_settings.MODELANVIL, "artifact_root": other_root}):
                self.assertEqual(self.client.get(issued.json()["download_path"], **self.worker_auth).status_code, 403)
        with override_settings(MODELANVIL={**django_settings.MODELANVIL, "artifact_backend": "s3"}):
            self.assertEqual(self.issue().status_code, 403)
            self.assertEqual(self.client.get(issued.json()["download_path"], **self.worker_auth).status_code, 403)

    def test_live_authority_changes_stop_future_chunks(self):
        self.large_artifact()
        issued = self.issue({**self.payload, "ttl_seconds": 60})
        self.assertEqual(issued.status_code, 201, issued.content)
        grant = WorkerArtifactGrant.all_objects.get(grant_id=issued.json()["grant_id"])
        mutations = [
            (Job, self.job.pk, {"desired_action": Job.DesiredAction.CANCEL}),
            (JobAttempt, grant.attempt_id, {"lease_expires_at": timezone.now() - timedelta(seconds=1)}),
            (Artifact, self.artifact.pk, {"state": Artifact.State.TOMBSTONED}),
            (Artifact, self.artifact.pk, {"object_key": "different-object.bin"}),
            (WorkerCredential, self.credential.pk, {"expires_at": timezone.now() - timedelta(seconds=1)}),
        ]
        for model, pk, update in mutations:
            with self.subTest(model=model.__name__, field=next(iter(update))):
                previous = model.all_objects.filter(pk=pk).values(*update.keys()).get()
                response = self.client.get(issued.json()["download_path"], **self.worker_auth)
                self.assertEqual(response.status_code, 200)
                try:
                    chunks = iter(response.streaming_content)
                    self.assertEqual(next(chunks), self.content[:64 * 1024])
                    model.all_objects.filter(pk=pk).update(**update)
                    self.assertEqual(b"".join(chunks), b"")
                finally:
                    model.all_objects.filter(pk=pk).update(**previous)
                    response.close()
        response = self.client.get(issued.json()["download_path"], **self.worker_auth)
        self.assertEqual(response.status_code, 200)
        try:
            chunks = iter(response.streaming_content)
            next(chunks)
            with patch("modelanvil.artifacts.worker_access.timezone.now", return_value=grant.expires_at):
                self.assertEqual(b"".join(chunks), b"")
        finally:
            response.close()

    def test_fencing_and_successful_commit_invalidate_grants(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        download_path = issued.json()["download_path"]
        Job.all_objects.filter(pk=self.job.pk).update(fencing_token="replacement-fence")
        self.assertEqual(self.client.get(download_path, **self.worker_auth).status_code, 403)
        Job.all_objects.filter(pk=self.job.pk).update(fencing_token=self.descriptor["fencing_token"])
        result = self.client.post("/api/v1/workers/result/", {
            "worker_id": self.worker.pk, "attempt_id": self.descriptor["attempt_id"],
            "fencing_token": self.descriptor["fencing_token"], "status": "succeeded",
        }, format="json", **self.worker_auth)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(self.client.get(download_path, **self.worker_auth).status_code, 403)

    def test_revocation_is_idempotent_and_cannot_be_restored(self):
        issued = self.issue()
        self.assertEqual(issued.status_code, 201, issued.content)
        grant = WorkerArtifactGrant.all_objects.get(grant_id=issued.json()["grant_id"])
        revoke_path = f"{self.issue_url}{grant.grant_id}/revoke/"
        self.assertEqual(self.client.post(revoke_path, {}, format="json", **self.admin_auth).status_code, 200)
        self.assertEqual(self.client.post(revoke_path, {}, format="json", **self.admin_auth).status_code, 200)
        grant.refresh_from_db()
        grant.revoked_at = None
        with self.assertRaisesRegex(ValueError, "immutable"):
            grant.save()
