"""Resumable artifact transfer API acceptance tests."""
import hashlib
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key


class ResumableArtifactUploadApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(slug="resumable-upload", name="Resumable Upload")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="owner", role=Role.OWNER, secret_hash=digest)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        content = b"resumable artifact contents"
        self.artifact = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id,
            storage_location_id="local",
            object_key="outputs/resume.bin",
            sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            media_type="application/octet-stream",
        )

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_create_transfer_session_for_staging_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                response = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/",
                    {},
                    format="json",
                    **self.auth,
                )

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(body["transfer_id"])
        self.assertEqual(body["state"], "open")
        self.assertEqual(body["bytes_verified"], 0)

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_upload_parts_out_of_order_and_replay_without_double_counting(self):
        part_one = b"part one "
        part_two = b"part two"
        complete = part_one + part_two
        self.artifact.sha256 = hashlib.sha256(complete).hexdigest()
        self.artifact.byte_size = len(complete)
        self.artifact.save(update_fields=("sha256", "byte_size", "updated_at"))
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                start = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/",
                    {}, format="json", **self.auth,
                )
                self.assertEqual(start.status_code, 201, start.content)
                transfer_id = start.json()["transfer_id"]

                def upload_part(number, body):
                    return self.client.put(
                        f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/parts/{number}/",
                        {"file": SimpleUploadedFile(f"part-{number}", body)},
                        format="multipart",
                        HTTP_X_PART_SHA256=hashlib.sha256(body).hexdigest(),
                        **self.auth,
                    )

                second = upload_part(2, part_two)
                self.assertEqual(second.status_code, 200, second.content)
                self.assertEqual(second.json()["bytes_verified"], len(part_two))
                first = upload_part(1, part_one)
                self.assertEqual(first.status_code, 200, first.content)
                self.assertEqual(first.json()["bytes_verified"], len(complete))
                replay = upload_part(1, part_one)
                self.assertEqual(replay.status_code, 200, replay.content)
                self.assertEqual(replay.json()["bytes_verified"], len(complete))

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_complete_transfer_commits_verified_parts_idempotently(self):
        content = b"first resumed " + b"second resumed"
        self.artifact.sha256 = hashlib.sha256(content).hexdigest()
        self.artifact.byte_size = len(content)
        self.artifact.save(update_fields=("sha256", "byte_size", "updated_at"))
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                start = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/",
                    {}, format="json", **self.auth,
                )
                transfer_id = start.json()["transfer_id"]
                for number, part in enumerate((b"first resumed ", b"second resumed"), start=1):
                    uploaded = self.client.put(
                        f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/parts/{number}/",
                        {"file": SimpleUploadedFile(f"part-{number}", part)},
                        format="multipart",
                        HTTP_X_PART_SHA256=hashlib.sha256(part).hexdigest(),
                        **self.auth,
                    )
                    self.assertEqual(uploaded.status_code, 200, uploaded.content)

                completed = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/complete/",
                    {}, format="json", **self.auth,
                )
                self.assertEqual(completed.status_code, 200, completed.content)
                self.assertEqual(completed.json()["state"], "completed")
                self.artifact.refresh_from_db()
                self.assertEqual(self.artifact.state, Artifact.State.COMMITTED)
                stored = Path(root) / str(self.tenant.tenant_id) / self.artifact.object_key
                self.assertEqual(stored.read_bytes(), content)

                replay = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/complete/",
                    {}, format="json", **self.auth,
                )
                self.assertEqual(replay.status_code, 200, replay.content)
                self.assertEqual(replay.json()["state"], "completed")

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_incomplete_transfer_does_not_publish_artifact(self):
        content = b"missing first part"
        self.artifact.sha256 = hashlib.sha256(content).hexdigest()
        self.artifact.byte_size = len(content)
        self.artifact.save(update_fields=("sha256", "byte_size", "updated_at"))
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                start = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/",
                    {}, format="json", **self.auth,
                )
                transfer_id = start.json()["transfer_id"]
                part = b"part two only"
                self.client.put(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/parts/2/",
                    {"file": SimpleUploadedFile("part-2", part)},
                    format="multipart",
                    HTTP_X_PART_SHA256=hashlib.sha256(part).hexdigest(),
                    **self.auth,
                )
                response = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/complete/",
                    {}, format="json", **self.auth,
                )
                self.assertEqual(response.status_code, 409, response.content)
                self.artifact.refresh_from_db()
                self.assertEqual(self.artifact.state, Artifact.State.STAGING)

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_transfer_status_resumes_and_abort_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                start = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/",
                    {}, format="json", **self.auth,
                )
                transfer_id = start.json()["transfer_id"]
                part = b"persisted part"
                uploaded = self.client.put(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/parts/1/",
                    {"file": SimpleUploadedFile("part-1", part)},
                    format="multipart",
                    HTTP_X_PART_SHA256=hashlib.sha256(part).hexdigest(),
                    **self.auth,
                )
                self.assertEqual(uploaded.status_code, 200, uploaded.content)
                status_response = self.client.get(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/",
                    **self.auth,
                )
                self.assertEqual(status_response.status_code, 200, status_response.content)
                self.assertEqual(status_response.json()["bytes_verified"], len(part))

                abort_url = f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/abort/"
                aborted = self.client.post(abort_url, {}, format="json", **self.auth)
                self.assertEqual(aborted.status_code, 200, aborted.content)
                self.assertEqual(aborted.json()["state"], "aborted")
                replay = self.client.post(abort_url, {}, format="json", **self.auth)
                self.assertEqual(replay.status_code, 200, replay.content)
                self.assertEqual(replay.json()["state"], "aborted")

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_resume_repairs_a_part_missing_from_storage(self):
        part = b"retry after object loss"
        with tempfile.TemporaryDirectory() as root:
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                start = self.client.post(
                    f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/",
                    {}, format="json", **self.auth,
                )
                transfer_id = start.json()["transfer_id"]
                url = f"/api/v1/artifacts/{self.artifact.artifact_id}/transfers/{transfer_id}/parts/1/"

                def upload():
                    return self.client.put(
                        url,
                        {"file": SimpleUploadedFile("part-1", part)},
                        format="multipart",
                        HTTP_X_PART_SHA256=hashlib.sha256(part).hexdigest(),
                        **self.auth,
                    )

                first = upload()
                self.assertEqual(first.status_code, 200, first.content)
                stored_part = (
                    Path(root)
                    / str(self.tenant.tenant_id)
                    / f"staging/transfers/{transfer_id}/parts/00001"
                )
                stored_part.unlink()

                resumed = upload()
                self.assertEqual(resumed.status_code, 200, resumed.content)
                self.assertEqual(stored_part.read_bytes(), part)
                self.assertEqual(resumed.json()["bytes_verified"], len(part))
