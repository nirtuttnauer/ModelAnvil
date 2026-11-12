"""In-process authorization for administrator-issued worker artifact grants.

``WorkerArtifactGrant.expires_at`` is the existing expiry field. These tests
call ``authorized_download`` with fixtures. They do not add a storage URL helper.
"""
import ast
import hashlib
import io
import re
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings as django_settings
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

import modelanvil.artifacts.worker_access as worker_access
from modelanvil.artifacts.models import Artifact, WorkerArtifactGrant
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.artifacts.worker_access import authorized_download, issue_download_grant
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import (
    Job,
    JobAttempt,
    Worker,
    WorkerCredential,
    WorkerPool,
    generate_worker_credential,
)

_SIGNATURE_MARKERS = (
    "generate_presigned",
    "presigned_url",
    "X-Amz-Signature",
    "X-Amz-Algorithm",
    "X-Amz-Credential",
    "AWSAccessKeyId",
    "AWS4-HMAC-SHA256",
)
_HELPER_NAME = re.compile(r"presign|signed_url|sign_url|query_signature", re.IGNORECASE)


@override_settings(ALLOWED_HOSTS=["testserver"])
class WorkerGrantAuthorizationTests(TransactionTestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        settings = override_settings(MODELANVIL={
            **django_settings.MODELANVIL,
            "artifact_backend": "filesystem",
            "artifact_root": root.name,
        })
        settings.enable()
        self.addCleanup(settings.disable)
        self.tenant = Tenant.objects.create(slug="worker-grants", name="Worker Grants")
        self.pool = WorkerPool.objects.create(
            tenant_id=self.tenant.pk, name="private", result_egress="metadata_only",
        )
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name="worker")
        lease = timezone.now() + timedelta(minutes=10)
        fence = "fence-token-for-grant-tests"
        self.job = Job.objects.create(
            tenant_id=self.tenant.pk,
            pool=self.pool,
            name="input-job",
            status=Job.Status.RUNNING,
            desired_action=Job.DesiredAction.RUN,
            claimed_by=self.worker,
            fencing_token=fence,
            lease_expires_at=lease,
        )
        self.attempt = JobAttempt.objects.create(
            tenant_id=self.tenant.pk,
            job=self.job,
            worker=self.worker,
            fencing_token=fence,
            status=JobAttempt.Status.RUNNING,
            lease_expires_at=lease,
        )
        _, digest = generate_worker_credential()
        self.credential = WorkerCredential.objects.create(
            tenant_id=self.tenant.pk, worker=self.worker, secret_hash=digest,
        )
        self.content = b"pinned input bytes\n"
        self.artifact = Artifact.objects.create(
            tenant_id=self.tenant.pk,
            storage_location_id="local",
            object_key="inputs/pinned.bin",
            sha256=hashlib.sha256(self.content).hexdigest(),
            byte_size=len(self.content),
            media_type="application/octet-stream",
        )
        upload_staged_artifact(self.artifact, io.BytesIO(self.content), backend=artifact_storage_backend())
        self.artifact.refresh_from_db()

    def _scope(self, grant_id):
        return {
            "tenant_id": self.tenant.pk,
            "grant_id": grant_id,
            "worker_id": self.worker.pk,
            "credential_id": self.credential.pk,
        }

    def _issue(self, ttl_seconds=60):
        return issue_download_grant(
            tenant_id=self.tenant.pk,
            attempt_id=self.attempt.attempt_id,
            worker_id=self.worker.pk,
            artifact_id=self.artifact.artifact_id,
            ttl_seconds=ttl_seconds,
        )

    def test_authorized_download_refuses_a_missing_grant(self):
        missing = uuid.uuid4()
        self.assertFalse(WorkerArtifactGrant.all_objects.filter(grant_id=missing).exists())
        with self.assertRaises(NotFound):
            with authorized_download(**self._scope(missing)):
                self.fail("a grant that was never issued was authorized")
        self.assertEqual(WorkerArtifactGrant.all_objects.count(), 0)

    def test_authorized_download_refuses_an_expired_grant(self):
        grant = self._issue()
        expired_at = timezone.now() - timedelta(seconds=1)
        WorkerArtifactGrant.all_objects.filter(pk=grant.pk).update(expires_at=expired_at)
        grant.refresh_from_db()
        self.attempt.refresh_from_db()
        self.assertLessEqual(grant.expires_at, timezone.now())
        self.assertGreater(self.attempt.lease_expires_at, timezone.now())
        with self.assertRaises(PermissionDenied) as caught:
            with authorized_download(**self._scope(grant.grant_id)):
                self.fail("an expired grant was authorized")
        self.assertEqual(caught.exception.detail, "Artifact grant is no longer valid.")

    def test_issued_grant_is_authorized_in_process(self):
        grant = self._issue()
        self.assertGreater(grant.expires_at, timezone.now())
        with authorized_download(**self._scope(grant.grant_id)) as (authorized, artifact):
            self.assertEqual(authorized.pk, grant.pk)
            self.assertEqual(authorized.grant_id, grant.grant_id)
            self.assertEqual(artifact.pk, self.artifact.pk)
            self.assertEqual(artifact.sha256, self.artifact.sha256)
            self.assertEqual(artifact.byte_size, len(self.content))
            self.assertEqual(authorized.artifact_snapshot, worker_access.artifact_snapshot(artifact))
            self.assertGreater(authorized.expires_at, timezone.now())


class WorkerAccessSourceTests(SimpleTestCase):
    def test_worker_access_does_not_build_a_presigned_url(self):
        source = Path(worker_access.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        self.assertFalse(any(_HELPER_NAME.search(name) for name in names))
        constants = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        presigned = [value for value in constants if "presigned" in value.lower()]
        self.assertEqual(
            presigned,
            ["Explicit administrator-issued input access; no upload or presigned URLs."],
        )
        for marker in _SIGNATURE_MARKERS:
            self.assertNotIn(marker, source)
        self.assertIsNone(re.search(r"[?&](?:Signature|X-Amz-Signature)=", source))
