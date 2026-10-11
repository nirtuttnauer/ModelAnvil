"""Filesystem and S3 artifact storage contract tests."""
import base64
import hashlib
import importlib.util
import io
import tempfile
import uuid
from pathlib import Path

from django.test import TestCase, override_settings
from modelanvil.artifacts.models import Artifact
from modelanvil.identity.models import Tenant


class LocalArtifactStorageTests(TestCase):
    def test_streams_content_into_tenant_scoped_immutable_object(self):
        self.assertIsNotNone(importlib.util.find_spec("modelanvil.artifacts.storage"))
        from modelanvil.artifacts.storage import LocalArtifactStorage

        content = b"line one\nline two\n"
        tenant_id = uuid.uuid4()
        with tempfile.TemporaryDirectory() as root:
            store = LocalArtifactStorage(root)
            result = store.put(tenant_id, "staging/job-1/output.txt", io.BytesIO(content))
            self.assertEqual(result, {"sha256": hashlib.sha256(content).hexdigest(), "byte_size": len(content)})
            with store.open(tenant_id, "staging/job-1/output.txt") as stored:
                self.assertEqual(stored.read(), content)
            self.assertTrue((Path(root) / str(tenant_id) / "staging/job-1/output.txt").is_file())
            with self.assertRaises(FileExistsError):
                store.put(tenant_id, "staging/job-1/output.txt", io.BytesIO(b"overwrite"))

    def test_rejects_path_traversal(self):
        from modelanvil.artifacts.storage import LocalArtifactStorage

        with tempfile.TemporaryDirectory() as root:
            store = LocalArtifactStorage(root)
            with self.assertRaises(ValueError):
                store.put(uuid.uuid4(), "../../outside", io.BytesIO(b"no"))

    def test_rejects_tenant_prefix_symlink_escape(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            tenant_id = uuid.uuid4()
            (Path(root) / str(tenant_id)).symlink_to(outside, target_is_directory=True)
            from modelanvil.artifacts.storage import LocalArtifactStorage
            store = LocalArtifactStorage(root)
            with self.assertRaises(ValueError):
                store.put(tenant_id, "not-allowed.bin", io.BytesIO(b"no"))

    def test_delete_is_idempotent_and_tenant_scoped(self):
        from modelanvil.artifacts.storage import LocalArtifactStorage

        tenant_one = uuid.uuid4()
        tenant_two = uuid.uuid4()
        with tempfile.TemporaryDirectory() as root:
            store = LocalArtifactStorage(root)
            store.put(tenant_one, "staging/part.bin", io.BytesIO(b"one"))
            store.put(tenant_two, "staging/part.bin", io.BytesIO(b"two"))

            store.delete(tenant_one, "staging/part.bin")
            store.delete(tenant_one, "staging/part.bin")

            with self.assertRaises(FileNotFoundError):
                store.open(tenant_one, "staging/part.bin")
            with store.open(tenant_two, "staging/part.bin") as stored:
                self.assertEqual(stored.read(), b"two")

    def test_artifact_commits_only_when_uploaded_bytes_match_staged_metadata(self):
        from modelanvil.artifacts import storage

        tenant = Tenant.objects.create(slug="stored-artifact", name="Stored Artifact")
        content = b"verified object"
        with tempfile.TemporaryDirectory() as root:
            store = storage.LocalArtifactStorage(root)
            artifact = Artifact.objects.create(
                tenant_id=tenant.tenant_id, storage_location_id="local", object_key="staging/a.bin",
                sha256=hashlib.sha256(content).hexdigest(), byte_size=len(content), media_type="application/octet-stream",
            )
            storage.upload_staged_artifact(artifact, io.BytesIO(content), backend=store)
            artifact.refresh_from_db()
            self.assertEqual(artifact.state, Artifact.State.COMMITTED)

            mismatch = Artifact.objects.create(
                tenant_id=tenant.tenant_id, storage_location_id="local", object_key="staging/b.bin",
                sha256=hashlib.sha256(content).hexdigest(), byte_size=len(content), media_type="application/octet-stream",
            )
            with self.assertRaises(ValueError):
                storage.upload_staged_artifact(mismatch, io.BytesIO(b"wrong content"), backend=store)
            mismatch.refresh_from_db()
            self.assertEqual(mismatch.state, Artifact.State.STAGING)
            with self.assertRaises(FileNotFoundError):
                store.open(tenant.tenant_id, mismatch.object_key)
            storage.upload_staged_artifact(mismatch, io.BytesIO(content), backend=store)
            mismatch.refresh_from_db()
            self.assertEqual(mismatch.state, Artifact.State.COMMITTED)


class S3ArtifactStorageTests(TestCase):
    class FakeS3:
        def __init__(self):
            self.objects = {}
            self.calls = []
            self.multipart = {}
            self.transient_conflicts = 0

        def put_object(self, **kwargs):
            self.calls.append(("put_object", kwargs))
            key = (kwargs["Bucket"], kwargs["Key"])
            if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")
            body = kwargs["Body"].read()
            self.objects[key] = {"body": body, "Metadata": kwargs["Metadata"], "ContentLength": len(body)}
            return {"ETag": '"etag-1"'}

        def head_object(self, **kwargs):
            self.calls.append(("head_object", kwargs))
            return self.objects[(kwargs["Bucket"], kwargs["Key"])]

        def get_object(self, **kwargs):
            self.calls.append(("get_object", kwargs))
            key = (kwargs["Bucket"], kwargs["Key"])
            if key not in self.objects:
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")
            return {"Body": io.BytesIO(self.objects[key]["body"])}

        def delete_object(self, **kwargs):
            self.calls.append(("delete_object", kwargs))
            self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
            return {}

        def create_multipart_upload(self, **kwargs):
            self.calls.append(("create_multipart_upload", kwargs))
            upload_id = "upload-1"
            self.multipart[upload_id] = {"key": (kwargs["Bucket"], kwargs["Key"]), "parts": [], "metadata": kwargs["Metadata"]}
            return {"UploadId": upload_id}

        def upload_part(self, **kwargs):
            self.calls.append(("upload_part", kwargs))
            data = kwargs["Body"]
            self.multipart[kwargs["UploadId"]]["parts"].append(data)
            return {
                "ETag": f'"part-{kwargs["PartNumber"]}"',
                "ChecksumSHA256": kwargs["ChecksumSHA256"],
            }

        def complete_multipart_upload(self, **kwargs):
            self.calls.append(("complete_multipart_upload", kwargs))
            upload = self.multipart[kwargs["UploadId"]]
            key = upload["key"]
            if self.transient_conflicts:
                self.transient_conflicts -= 1
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "ConditionalRequestConflict"}, "ResponseMetadata": {"HTTPStatusCode": 409}}, "CompleteMultipartUpload")
            if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
                from botocore.exceptions import ClientError
                raise ClientError({"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}}, "CompleteMultipartUpload")
            body = b"".join(upload["parts"])
            self.objects[key] = {"body": body, "Metadata": upload["metadata"], "ContentLength": len(body)}
            return {"ETag": '"multipart-etag"'}

        def abort_multipart_upload(self, **kwargs):
            self.calls.append(("abort_multipart_upload", kwargs))
            self.multipart.pop(kwargs["UploadId"], None)

    def test_s3_store_puts_under_tenant_prefix_and_verifies_metadata(self):
        import modelanvil.artifacts.storage as storage
        self.assertTrue(hasattr(storage, "S3ArtifactStorage"))
        tenant_id = uuid.uuid4()
        content = b"s3 artifact bytes"
        client = self.FakeS3()
        backend = storage.S3ArtifactStorage(bucket="artifacts", client=client)
        result = backend.put(tenant_id, "datasets/a.jsonl", io.BytesIO(content))
        key = f"{tenant_id}/datasets/a.jsonl"
        self.assertEqual(result, {"sha256": hashlib.sha256(content).hexdigest(), "byte_size": len(content)})
        call = next(args for name, args in client.calls if name == "put_object")
        self.assertEqual(call["Bucket"], "artifacts")
        self.assertEqual(call["Key"], key)
        self.assertEqual(call["IfNoneMatch"], "*")
        self.assertEqual(call["Metadata"]["sha256"], result["sha256"])
        with backend.open(tenant_id, "datasets/a.jsonl") as stream:
            self.assertEqual(stream.read(), content)
        with self.assertRaises(FileExistsError):
            backend.put(tenant_id, "datasets/a.jsonl", io.BytesIO(content))

    def test_missing_s3_object_raises_file_not_found(self):
        import modelanvil.artifacts.storage as storage

        backend = storage.S3ArtifactStorage(bucket="artifacts", client=self.FakeS3())
        with self.assertRaises(FileNotFoundError):
            backend.open(uuid.uuid4(), "missing.bin")

    def test_s3_delete_is_tenant_scoped_and_idempotent(self):
        from modelanvil.artifacts.storage import S3ArtifactStorage

        tenant_id = uuid.uuid4()
        other_tenant_id = uuid.uuid4()
        client = self.FakeS3()
        backend = S3ArtifactStorage(bucket="artifacts", client=client)
        backend.put(tenant_id, "staging/part.bin", io.BytesIO(b"one"))
        backend.put(other_tenant_id, "staging/part.bin", io.BytesIO(b"two"))

        backend.delete(tenant_id, "staging/part.bin")
        backend.delete(tenant_id, "staging/part.bin")

        self.assertNotIn(("artifacts", f"{tenant_id}/staging/part.bin"), client.objects)
        self.assertIn(("artifacts", f"{other_tenant_id}/staging/part.bin"), client.objects)
        delete_call = next(args for name, args in client.calls if name == "delete_object")
        self.assertEqual(delete_call, {"Bucket": "artifacts", "Key": f"{tenant_id}/staging/part.bin"})

    def test_s3_multipart_completes_with_conditional_create(self):
        import modelanvil.artifacts.storage as storage
        self.assertTrue(hasattr(storage, "S3ArtifactStorage"))
        tenant_id = uuid.uuid4()
        content = b"multipart sample"
        client = self.FakeS3()
        backend = storage.S3ArtifactStorage(
            bucket="artifacts", client=client, multipart_threshold=1, part_size=5 * 1024 * 1024,
        )
        result = backend.put(tenant_id, "checkpoints/model.bin", io.BytesIO(content))
        self.assertEqual(result["byte_size"], len(content))
        complete = next(args for name, args in client.calls if name == "complete_multipart_upload")
        self.assertEqual(complete["IfNoneMatch"], "*")
        self.assertEqual(client.objects[("artifacts", f"{tenant_id}/checkpoints/model.bin")]["body"], content)

    def test_s3_retries_transient_multipart_conditional_conflict(self):
        import modelanvil.artifacts.storage as storage

        tenant_id = uuid.uuid4()
        client = self.FakeS3()
        client.transient_conflicts = 1
        backend = storage.S3ArtifactStorage(
            bucket="artifacts", client=client, multipart_threshold=1, part_size=5 * 1024 * 1024,
        )
        result = backend.put(tenant_id, "checkpoint.bin", io.BytesIO(b"artifact"))
        self.assertEqual(result["byte_size"], len(b"artifact"))
        self.assertEqual(sum(name == "create_multipart_upload" for name, _ in client.calls), 2)

    def test_mismatched_staged_artifact_does_not_create_poisoned_s3_object(self):
        from modelanvil.artifacts import storage

        tenant = Tenant.objects.create(slug="s3-mismatch", name="S3 Mismatch")
        expected = b"expected"
        client = self.FakeS3()
        backend = storage.S3ArtifactStorage(bucket="artifacts", client=client)
        artifact = Artifact.objects.create(
            tenant_id=tenant.tenant_id, storage_location_id="s3", object_key="staging/retry.bin",
            sha256=hashlib.sha256(expected).hexdigest(), byte_size=len(expected), media_type="application/octet-stream",
        )
        with self.assertRaises(ValueError):
            storage.upload_staged_artifact(artifact, io.BytesIO(b"wrong"), backend=backend)
        self.assertEqual(client.objects, {})
        storage.upload_staged_artifact(artifact, io.BytesIO(expected), backend=backend)
        artifact.refresh_from_db()
        self.assertEqual(artifact.state, Artifact.State.COMMITTED)

    def test_single_put_parameters_are_accepted_by_boto3_service_model(self):
        import boto3
        from botocore.stub import ANY, Stubber
        from modelanvil.artifacts.storage import S3ArtifactStorage

        tenant_id = uuid.uuid4()
        content = b"validated by botocore"
        checksum = hashlib.sha256(content).hexdigest()
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test"
        )
        expected = {
            "Bucket": "artifacts",
            "Key": f"{tenant_id}/verified.txt",
            "Body": ANY,
            "ContentLength": len(content),
            "Metadata": {"sha256": checksum},
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(content).digest()).decode("ascii"),
            "IfNoneMatch": "*",
        }
        with Stubber(client) as stubber:
            stubber.add_response("put_object", {"ETag": '"ok"'}, expected)
            stubber.add_response(
                "head_object",
                {"ContentLength": len(content), "Metadata": {"sha256": checksum}},
                {"Bucket": "artifacts", "Key": f"{tenant_id}/verified.txt"},
            )
            backend = S3ArtifactStorage(bucket="artifacts", client=client)
            result = backend.put(tenant_id, "verified.txt", io.BytesIO(content))
            self.assertEqual(result, {"sha256": checksum, "byte_size": len(content)})

    def test_multipart_parameters_are_accepted_by_boto3_service_model(self):
        import boto3
        from botocore.stub import ANY, Stubber
        from modelanvil.artifacts.storage import S3ArtifactStorage

        tenant_id = uuid.uuid4()
        content = b"multipart checksum"
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
        key = f"{tenant_id}/large.bin"
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test"
        )
        with Stubber(client) as stubber:
            stubber.add_response(
                "create_multipart_upload",
                {"UploadId": "upload-id"},
                {"Bucket": "artifacts", "Key": key, "Metadata": {"sha256": hashlib.sha256(content).hexdigest()}, "ChecksumAlgorithm": "SHA256"},
            )
            stubber.add_response(
                "upload_part",
                {"ETag": '"part"', "ChecksumSHA256": checksum},
                {"Bucket": "artifacts", "Key": key, "UploadId": "upload-id", "PartNumber": 1, "Body": ANY, "ChecksumSHA256": checksum},
            )
            stubber.add_response(
                "complete_multipart_upload",
                {"ETag": '"complete"'},
                {"Bucket": "artifacts", "Key": key, "UploadId": "upload-id", "MultipartUpload": {"Parts": [{"PartNumber": 1, "ETag": '"part"', "ChecksumSHA256": checksum}]}, "IfNoneMatch": "*"},
            )
            stubber.add_response(
                "head_object",
                {"ContentLength": len(content), "Metadata": {"sha256": hashlib.sha256(content).hexdigest()}},
                {"Bucket": "artifacts", "Key": key},
            )
            backend = S3ArtifactStorage(bucket="artifacts", client=client, multipart_threshold=1)
            result = backend.put(tenant_id, "large.bin", io.BytesIO(content))
            self.assertEqual(result["byte_size"], len(content))

    def test_configured_backend_builds_s3_client_from_platform_settings(self):
        from unittest.mock import patch
        from modelanvil.artifacts.storage import S3ArtifactStorage, artifact_storage_backend

        config = {
            "artifact_backend": "s3",
            "s3_bucket": "platform-artifacts",
            "s3_endpoint_url": "http://storage.example.test",
            "s3_region": "eu-west-1",
            "s3_access_key": "test-access",
            "s3_secret_key": "test-secret",
        }
        fake = self.FakeS3()
        with override_settings(MODELANVIL=config), patch("boto3.client", return_value=fake) as client_factory:
            backend = artifact_storage_backend()
        self.assertIsInstance(backend, S3ArtifactStorage)
        self.assertEqual(getattr(backend, "bucket"), "platform-artifacts")
        client_factory.assert_called_once_with(
            "s3",
            endpoint_url="http://storage.example.test",
            region_name="eu-west-1",
            aws_access_key_id="test-access",
            aws_secret_access_key="test-secret",
        )
