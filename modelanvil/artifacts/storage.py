"""Safe local implementation of the immutable artifact object contract."""
from __future__ import annotations

import hashlib
import base64
import os
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from django.conf import settings

from modelanvil.artifacts.models import Artifact


class LocalArtifactStorage:
    """Store opaque tenant-scoped object keys with atomic no-overwrite writes.

    This filesystem backend is for development and self-hosted single-node
    use. It does not implement S3 multipart transfers or cross-host locking.
    """

    def __init__(self, root: str | os.PathLike[str] | None = None, *, chunk_size: int = 1024 * 1024):
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        configured = root if root is not None else settings.MODELANVIL["artifact_root"]
        self.root = Path(configured).expanduser().resolve()
        self.chunk_size = chunk_size

    @staticmethod
    def _tenant_id(value: object) -> str:
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("tenant_id must be a UUID") from exc

    @staticmethod
    def _object_key(value: str) -> PurePosixPath:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ValueError("object_key must be a non-empty POSIX relative path")
        parts = value.split("/")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in ("", ".", "..") for part in parts):
            raise ValueError("object_key must not escape its tenant prefix")
        return path

    def _path(self, tenant_id: object, object_key: str, *, create_parent: bool) -> Path:
        tenant = self._tenant_id(tenant_id)
        key = self._object_key(object_key)
        tenant_root = self.root / tenant
        target = tenant_root.joinpath(*key.parts)
        boundary = tenant_root.resolve(strict=False)
        if not boundary.is_relative_to(self.root):
            raise ValueError("tenant storage prefix escapes artifact root")
        resolved = target.resolve(strict=False)
        if not resolved.is_relative_to(boundary):
            raise ValueError("resolved object path escapes its tenant storage prefix")
        if create_parent:
            target.parent.mkdir(parents=True, exist_ok=True)
            resolved = target.resolve(strict=False)
            if not resolved.is_relative_to(boundary):
                raise ValueError("resolved object path escapes its tenant storage prefix")
        return resolved

    def put(
        self,
        tenant_id: object,
        object_key: str,
        stream: BinaryIO,
        *,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
    ) -> dict[str, int | str]:
        """Stream bytes atomically; refuse invalid or existing objects."""
        target = self._path(tenant_id, object_key, create_parent=True)
        digest = hashlib.sha256()
        size = 0
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=".upload-", delete=False) as staged:
                temp_path = staged.name
                while True:
                    block = stream.read(self.chunk_size)
                    if block == b"":
                        break
                    if not isinstance(block, bytes):
                        raise TypeError("artifact stream must yield bytes")
                    staged.write(block)
                    digest.update(block)
                    size += len(block)
                staged.flush()
                os.fsync(staged.fileno())
            if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
                raise ValueError("Uploaded bytes do not match the staged SHA-256 digest.")
            if expected_size is not None and size != expected_size:
                raise ValueError("Uploaded bytes do not match the staged byte size.")
            # A hard-link is an atomic create-if-absent on the same filesystem.
            # It prevents a concurrent uploader from silently replacing bytes.
            os.link(temp_path, target)
            return {"sha256": digest.hexdigest(), "byte_size": size}
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    def open(self, tenant_id: object, object_key: str):
        """Open an object only within the requested tenant prefix."""
        path = self._path(tenant_id, object_key, create_parent=False)
        return path.open("rb")

    def delete(self, tenant_id: object, object_key: str) -> None:
        """Delete an object within the tenant prefix; a missing object is harmless."""
        path = self._path(tenant_id, object_key, create_parent=False)
        path.unlink(missing_ok=True)


class S3ArtifactStorage:
    """S3-compatible immutable object store with verified streaming uploads."""

    MIN_PART_SIZE = 5 * 1024 * 1024

    class ConditionalConflict(RuntimeError):
        """A transient S3 conditional-write race that may be retried."""

    def __init__(
        self,
        bucket: str | None = None,
        *,
        client=None,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        multipart_threshold: int = 8 * 1024 * 1024,
        part_size: int = 8 * 1024 * 1024,
    ):
        config = settings.MODELANVIL
        self.bucket = bucket or config.get("s3_bucket")
        if not self.bucket:
            raise ValueError("An S3 bucket must be configured.")
        if multipart_threshold < 1 or part_size < self.MIN_PART_SIZE:
            raise ValueError("multipart_threshold must be positive and part_size at least 5 MiB.")
        self.multipart_threshold = multipart_threshold
        self.part_size = part_size
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url or config.get("s3_endpoint_url") or None,
                region_name=region_name or config.get("s3_region") or None,
                aws_access_key_id=config.get("s3_access_key") or None,
                aws_secret_access_key=config.get("s3_secret_key") or None,
            )
        self.client = client

    @staticmethod
    def _key(tenant_id: object, object_key: str) -> str:
        tenant = LocalArtifactStorage._tenant_id(tenant_id)
        key = LocalArtifactStorage._object_key(object_key)
        return f"{tenant}/{key.as_posix()}"

    @staticmethod
    def _raise_storage_error(exc: Exception, key: str) -> None:
        from botocore.exceptions import ClientError

        if isinstance(exc, ClientError):
            code = str(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if code == "412" or error_code == "PreconditionFailed":
                raise FileExistsError(f"S3 object already exists: {key}") from exc
            if code == "409" or error_code == "ConditionalRequestConflict":
                raise S3ArtifactStorage.ConditionalConflict(
                    "S3 reported a conditional-write conflict; retry the upload."
                ) from exc
        raise exc

    @staticmethod
    def _is_conditional_conflict(exc: Exception) -> bool:
        from botocore.exceptions import ClientError

        if not isinstance(exc, ClientError):
            return False
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        error_code = exc.response.get("Error", {}).get("Code")
        return status_code == 409 or error_code == "ConditionalRequestConflict"

    def put(
        self,
        tenant_id: object,
        object_key: str,
        stream: BinaryIO,
        *,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
    ) -> dict[str, int | str]:
        """Hash to a bounded-memory spool, then conditionally create the S3 key."""
        key = self._key(tenant_id, object_key)
        digest = hashlib.sha256()
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=self.part_size, mode="w+b") as staged:
            while True:
                block = stream.read(self.part_size)
                if block == b"":
                    break
                if not isinstance(block, bytes):
                    raise TypeError("artifact stream must yield bytes")
                staged.write(block)
                digest.update(block)
                size += len(block)
            checksum = digest.hexdigest()
            if expected_sha256 is not None and checksum != expected_sha256:
                raise ValueError("Uploaded bytes do not match the staged SHA-256 digest.")
            if expected_size is not None and size != expected_size:
                raise ValueError("Uploaded bytes do not match the staged byte size.")
            metadata = {"sha256": checksum}
            staged.seek(0)
            for attempt in range(2):
                try:
                    if size < self.multipart_threshold or size == 0:
                        self.client.put_object(
                            Bucket=self.bucket,
                            Key=key,
                            Body=staged,
                            ContentLength=size,
                            Metadata=metadata,
                            ChecksumSHA256=base64.b64encode(digest.digest()).decode("ascii"),
                            IfNoneMatch="*",
                        )
                    else:
                        self._multipart_put(key, staged, metadata)
                    break
                except Exception as exc:
                    if attempt == 0 and self._is_conditional_conflict(exc):
                        staged.seek(0)
                        continue
                    self._raise_storage_error(exc, key)
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            if head.get("ContentLength") != size or head.get("Metadata", {}).get("sha256") != checksum:
                raise IOError("S3 object metadata did not match the uploaded artifact.")
        return {"sha256": checksum, "byte_size": size}

    def _multipart_put(self, key: str, staged, metadata: dict[str, str]) -> None:
        response = self.client.create_multipart_upload(
            Bucket=self.bucket, Key=key, Metadata=metadata, ChecksumAlgorithm="SHA256"
        )
        upload_id = response["UploadId"]
        parts = []
        try:
            part_number = 1
            while True:
                body = staged.read(self.part_size)
                if not body:
                    break
                part_checksum = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
                uploaded = self.client.upload_part(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=body,
                    ChecksumSHA256=part_checksum,
                )
                parts.append({
                    "PartNumber": part_number,
                    "ETag": uploaded["ETag"],
                    "ChecksumSHA256": uploaded.get("ChecksumSHA256", part_checksum),
                })
                part_number += 1
            self.client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
                IfNoneMatch="*",
            )
        except Exception:
            try:
                self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)
            except Exception:
                pass
            raise

    def open(self, tenant_id: object, object_key: str):
        key = self._key(tenant_id, object_key)
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except Exception as exc:
            from botocore.exceptions import ClientError

            if isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in {
                "NoSuchKey", "NotFound", "404",
            }:
                raise FileNotFoundError(f"S3 artifact does not exist: {key}") from exc
            raise

    def delete(self, tenant_id: object, object_key: str) -> None:
        """Delete the tenant-scoped key; S3 treats deletion of a missing key as success."""
        key = self._key(tenant_id, object_key)
        self.client.delete_object(Bucket=self.bucket, Key=key)


def artifact_storage_backend():
    """Build the configured artifact backend for an API operation."""
    config = settings.MODELANVIL
    backend = config.get("artifact_backend", "filesystem")
    if backend == "filesystem":
        return LocalArtifactStorage(config["artifact_root"])
    if backend == "s3":
        return S3ArtifactStorage()
    raise ValueError(f"Unsupported artifact backend: {backend}")


def upload_staged_artifact(
    artifact: Artifact,
    stream: BinaryIO,
    *,
    backend: LocalArtifactStorage | S3ArtifactStorage | None = None,
) -> dict[str, int | str]:
    """Store bytes and commit metadata only after exact digest/size verification."""
    if artifact.state != Artifact.State.STAGING:
        raise ValueError("Only staging artifacts accept uploaded bytes.")
    storage = backend or LocalArtifactStorage()
    observed = storage.put(
        artifact.tenant_id,
        str(artifact.object_key),
        stream,
        expected_sha256=str(artifact.sha256),
        expected_size=int(getattr(artifact, "byte_size")),
    )
    if observed["sha256"] != artifact.sha256 or observed["byte_size"] != artifact.byte_size:
        raise ValueError("Uploaded bytes do not match staged artifact checksum and size.")
    artifact.mark_verified(
        verified_sha256=str(observed["sha256"]),
        verified_size=int(observed["byte_size"]),
    )
    return observed
