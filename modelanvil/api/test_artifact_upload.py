import hashlib
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key


class ArtifactUploadApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(slug="artifact-upload", name="Artifact Upload")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="owner", role=Role.OWNER, secret_hash=digest)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        viewer_secret, viewer_digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="viewer", role=Role.VIEWER, secret_hash=viewer_digest)
        self.viewer_auth = {"HTTP_AUTHORIZATION": f"Bearer {viewer_secret}"}

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_upload_commits_only_verified_bytes(self):
        content = b"manifest contents\n"
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                artifact = Artifact.objects.create(
                    tenant_id=self.tenant.tenant_id, storage_location_id="local",
                    object_key="staging/one/manifest.json", sha256=hashlib.sha256(content).hexdigest(),
                    byte_size=len(content), media_type="application/json",
                )
                response = self.client.post(
                    f"/api/v1/artifacts/{artifact.artifact_id}/upload/",
                    {"file": SimpleUploadedFile("manifest.json", content)}, format="multipart", **self.auth,
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["state"], Artifact.State.COMMITTED)
                stored = Path(root) / str(self.tenant.tenant_id) / artifact.object_key
                self.assertEqual(stored.read_bytes(), content)

                bad = Artifact.objects.create(
                    tenant_id=self.tenant.tenant_id, storage_location_id="local",
                    object_key="staging/two/manifest.json", sha256="0" * 64,
                    byte_size=len(content), media_type="application/json",
                )
                response = self.client.post(
                    f"/api/v1/artifacts/{bad.artifact_id}/upload/",
                    {"file": SimpleUploadedFile("bad.json", content)}, format="multipart", **self.auth,
                )
                self.assertEqual(response.status_code, 400, response.content)
                bad.refresh_from_db()
                self.assertEqual(bad.state, Artifact.State.STAGING)
                self.assertFalse((Path(root) / str(self.tenant.tenant_id) / bad.object_key).exists())

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_upload_cannot_target_another_tenants_artifact(self):
        other = Tenant.objects.create(slug="other-artifact-upload", name="Other")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=other, name="other", role=Role.OWNER, secret_hash=digest)
        artifact = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id, storage_location_id="local",
            object_key="staging/private.bin", sha256=hashlib.sha256(b"private").hexdigest(),
            byte_size=7, media_type="application/octet-stream",
        )
        response = self.client.post(
            f"/api/v1/artifacts/{artifact.artifact_id}/upload/",
            {"file": SimpleUploadedFile("private.bin", b"private")}, format="multipart",
            HTTP_AUTHORIZATION=f"Bearer {secret}",
        )
        self.assertEqual(response.status_code, 404)
        artifact.refresh_from_db()
        self.assertEqual(artifact.state, Artifact.State.STAGING)

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_viewer_can_download_committed_artifact_through_current_tenant_access(self):
        content = b"private artifact payload"
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                artifact = Artifact.objects.create(
                    tenant_id=self.tenant.tenant_id, storage_location_id="local",
                    object_key="outputs/report.json", sha256=hashlib.sha256(content).hexdigest(),
                    byte_size=len(content), media_type="application/json",
                )
                uploaded = self.client.post(
                    f"/api/v1/artifacts/{artifact.artifact_id}/upload/",
                    {"file": SimpleUploadedFile("report.json", content)}, format="multipart", **self.auth,
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.content)
                response = self.client.get(
                    f"/api/v1/artifacts/{artifact.artifact_id}/download/", **self.viewer_auth,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), content)
                self.assertEqual(response["Content-Type"], "application/json")
                self.assertEqual(response["Content-Length"], str(len(content)))
                self.assertIn("attachment", response["Content-Disposition"])

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_staging_and_tombstoned_artifacts_are_not_downloadable(self):
        content = b"staged bytes"
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                artifact = Artifact.objects.create(
                    tenant_id=self.tenant.tenant_id, storage_location_id="local",
                    object_key="outputs/staged.bin", sha256=hashlib.sha256(content).hexdigest(),
                    byte_size=len(content), media_type="application/octet-stream",
                )
                path = f"/api/v1/artifacts/{artifact.artifact_id}/download/"
                response = self.client.get(path, **self.viewer_auth)
                self.assertEqual(response.status_code, 409)

                uploaded = self.client.post(
                    f"/api/v1/artifacts/{artifact.artifact_id}/upload/",
                    {"file": SimpleUploadedFile("staged.bin", content)}, format="multipart", **self.auth,
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.content)
                artifact.refresh_from_db()
                artifact.tombstone()
                response = self.client.get(path, **self.viewer_auth)
                self.assertEqual(response.status_code, 404)

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_viewer_cannot_download_another_tenants_artifact(self):
        other = Tenant.objects.create(slug="private-download", name="Private Download")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=other, name="other", role=Role.OWNER, secret_hash=digest)
        artifact = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id, storage_location_id="local",
            object_key="outputs/tenant-secret.txt", sha256=hashlib.sha256(b"secret").hexdigest(),
            byte_size=6, media_type="text/plain",
        )
        response = self.client.get(
            f"/api/v1/artifacts/{artifact.artifact_id}/download/",
            HTTP_AUTHORIZATION=f"Bearer {secret}",
        )
        self.assertEqual(response.status_code, 404)
