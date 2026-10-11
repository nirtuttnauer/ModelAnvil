"""Durable, checksummed parts for resumable artifact uploads."""
from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import BinaryIO, cast

from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact, TransferSession
from modelanvil.artifacts.storage import (
    LocalArtifactStorage,
    S3ArtifactStorage,
    upload_staged_artifact,
)

MAX_TRANSFER_PART_BYTES = 16 * 1024 * 1024
MAX_TRANSFER_PARTS = 10_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
StorageBackend = LocalArtifactStorage | S3ArtifactStorage


class TransferConflict(ValueError):
    """The session state or an existing part conflicts with this operation."""


class TransferExpired(TransferConflict):
    """The transfer session has expired."""


def _stored_part_digest(backend: StorageBackend, tenant_id, object_key: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    stored = backend.open(tenant_id, object_key)
    try:
        while True:
            block = stored.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    finally:
        stored.close()
    return digest.hexdigest(), size


class _PartStream:
    """Read ordered part objects as one bounded-memory stream."""

    def __init__(self, backend: StorageBackend, tenant_id, object_keys: list[str]):
        self.backend = backend
        self.tenant_id = tenant_id
        self.object_keys = iter(object_keys)
        self.current = None
        self.finished = False

    def _advance(self) -> bool:
        if self.current is not None:
            self.current.close()
            self.current = None
        try:
            key = next(self.object_keys)
        except StopIteration:
            self.finished = True
            return False
        self.current = self.backend.open(self.tenant_id, key)
        return True

    def read(self, size: int = -1) -> bytes:
        if size == 0 or self.finished:
            return b""
        if size < 0:
            blocks = []
            while not self.finished:
                block = self.read(1024 * 1024)
                if block:
                    blocks.append(block)
            return b"".join(blocks)
        blocks = []
        remaining = size
        while remaining and not self.finished:
            if self.current is None and not self._advance():
                break
            current = self.current
            if current is None:
                break
            block = current.read(remaining)
            if block:
                blocks.append(block)
                remaining -= len(block)
            else:
                self._advance()
        return b"".join(blocks)

    def close(self) -> None:
        if self.current is not None:
            self.current.close()
            self.current = None
        self.finished = True


def add_transfer_part(
    transfer: TransferSession,
    part_number: int,
    stream: BinaryIO,
    *,
    expected_sha256: str,
    expected_size: int,
    backend: StorageBackend,
) -> TransferSession:
    """Persist one part; exact retries are idempotent and conflicting retries fail."""
    if not 1 <= part_number <= MAX_TRANSFER_PARTS:
        raise ValueError(f"part_number must be between 1 and {MAX_TRANSFER_PARTS}.")
    if not _SHA256.fullmatch(expected_sha256):
        raise ValueError("X-Part-SHA256 must be a lowercase SHA-256 digest.")
    if not 1 <= expected_size <= MAX_TRANSFER_PART_BYTES:
        raise ValueError(f"part size must be between 1 and {MAX_TRANSFER_PART_BYTES} bytes.")

    expired = False
    with transaction.atomic():
        current = TransferSession.all_objects.select_for_update().select_related("artifact").get(
            pk=transfer.pk,
            transfer_id=transfer.transfer_id,
            tenant_id=transfer.tenant_id,
        )
        if current.state != TransferSession.State.OPEN:
            raise TransferConflict(f"Transfer session is {current.state}, not open.")
        if current.expires_at <= timezone.now():
            current.state = TransferSession.State.EXPIRED
            current.save(update_fields=("state", "updated_at"))
            expired = True
        elif current.artifact.state != Artifact.State.STAGING:
            raise TransferConflict("The target artifact is no longer staging.")
        else:
            part_key = str(part_number)
            existing = current.part_manifest.get(part_key)
            if existing is not None:
                if existing.get("sha256") != expected_sha256 or existing.get("byte_size") != expected_size:
                    raise TransferConflict("This part number already contains different bytes.")
                try:
                    stored_sha256, stored_size = _stored_part_digest(
                        backend, current.tenant_id, str(existing["object_key"])
                    )
                except FileNotFoundError:
                    manifest = dict(current.part_manifest)
                    manifest.pop(part_key)
                    current.part_manifest = manifest
                    current.bytes_verified = sum(
                        int(part["byte_size"]) for part in manifest.values()
                    )
                    current.save(update_fields=("part_manifest", "bytes_verified", "updated_at"))
                else:
                    if stored_sha256 != expected_sha256 or stored_size != expected_size:
                        raise TransferConflict("Stored part bytes no longer match the verified manifest.")
                    return current

            object_key = f"{current.staging_prefix}/parts/{part_number:05d}"
            try:
                observed = backend.put(
                    current.tenant_id,
                    object_key,
                    stream,
                    expected_sha256=expected_sha256,
                    expected_size=expected_size,
                )
            except FileExistsError:
                observed_sha256, observed_size = _stored_part_digest(
                    backend, current.tenant_id, object_key
                )
                if observed_sha256 != expected_sha256 or observed_size != expected_size:
                    raise TransferConflict("A previously stored part conflicts with this upload.")
                observed = {"sha256": observed_sha256, "byte_size": observed_size}

            manifest = dict(current.part_manifest)
            manifest[part_key] = {
                "object_key": object_key,
                "sha256": str(observed["sha256"]),
                "byte_size": int(observed["byte_size"]),
            }
            current.part_manifest = manifest
            current.bytes_verified = sum(int(part["byte_size"]) for part in manifest.values())
            current.save(update_fields=("part_manifest", "bytes_verified", "updated_at"))
    if expired:
        raise TransferExpired("Transfer session has expired.")
    return current


def complete_transfer(
    transfer: TransferSession,
    *,
    backend: StorageBackend,
) -> TransferSession:
    """Verify ordered part manifest and atomically publish the target artifact."""
    expired = False
    checksum_failure = None
    with transaction.atomic():
        current = TransferSession.all_objects.select_for_update().select_related("artifact").get(
            pk=transfer.pk,
            transfer_id=transfer.transfer_id,
            tenant_id=transfer.tenant_id,
        )
        if current.state == TransferSession.State.COMPLETED:
            return current
        if current.state != TransferSession.State.OPEN:
            raise TransferConflict(f"Transfer session is {current.state}, not open.")
        if current.expires_at <= timezone.now():
            current.state = TransferSession.State.EXPIRED
            current.save(update_fields=("state", "updated_at"))
            expired = True
        elif current.artifact.state != Artifact.State.STAGING:
            raise TransferConflict("The target artifact is no longer staging.")
        else:
            try:
                ordered_numbers = sorted(int(number) for number in current.part_manifest)
            except (TypeError, ValueError) as exc:
                raise TransferConflict("Stored part manifest is invalid.") from exc
            if ordered_numbers != list(range(1, len(ordered_numbers) + 1)):
                raise TransferConflict("All parts from 1 through the final part must be uploaded.")
            if current.bytes_verified != current.artifact.byte_size:
                raise TransferConflict("Verified part sizes do not match the target artifact size.")
            keys = [current.part_manifest[str(number)]["object_key"] for number in ordered_numbers]
            stream = _PartStream(backend, current.tenant_id, keys)
            observed: dict[str, int | str] = {}
            try:
                try:
                    observed = upload_staged_artifact(
                        current.artifact, cast(BinaryIO, stream), backend=backend
                    )
                except FileExistsError:
                    sha256, byte_size = _stored_part_digest(
                        backend, current.tenant_id, current.artifact.object_key
                    )
                    if sha256 != current.artifact.sha256 or byte_size != current.artifact.byte_size:
                        raise TransferConflict("An immutable object already conflicts with this artifact.")
                    current.artifact.mark_verified(verified_sha256=sha256, verified_size=byte_size)
                    observed = {"sha256": sha256, "byte_size": byte_size}
            except TransferConflict:
                raise
            except ValueError as exc:
                current.state = TransferSession.State.FAILED
                current.save(update_fields=("state", "updated_at"))
                checksum_failure = exc
            finally:
                stream.close()
            if checksum_failure is None:
                current.state = TransferSession.State.COMPLETED
                current.bytes_verified = int(observed["byte_size"])
                current.save(update_fields=("state", "bytes_verified", "updated_at"))
    if expired:
        raise TransferExpired("Transfer session has expired.")
    if checksum_failure is not None:
        raise ValueError(str(checksum_failure)) from checksum_failure
    return current


@transaction.atomic
def abort_transfer(transfer: TransferSession) -> TransferSession:
    """Abort an unfinished transfer; repeated abort requests are harmless."""
    current = TransferSession.all_objects.select_for_update().get(
        pk=transfer.pk,
        transfer_id=transfer.transfer_id,
        tenant_id=transfer.tenant_id,
    )
    if current.state == TransferSession.State.ABORTED:
        return current
    if current.state == TransferSession.State.COMPLETED:
        raise TransferConflict("A completed transfer cannot be aborted.")
    current.state = TransferSession.State.ABORTED
    current.save(update_fields=("state", "updated_at"))
    return current


def prune_transfer_parts(*, retention_days: int, backend: StorageBackend) -> dict[str, int]:
    """Purge retained part objects for old terminal sessions, preserving manifests."""
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    now = timezone.now()
    cutoff = now - timedelta(days=retention_days)
    TransferSession.all_objects.filter(
        state=TransferSession.State.OPEN,
        expires_at__lte=now,
    ).update(state=TransferSession.State.EXPIRED, updated_at=now)

    terminal_states = (
        TransferSession.State.COMPLETED,
        TransferSession.State.ABORTED,
        TransferSession.State.EXPIRED,
        TransferSession.State.FAILED,
    )
    candidate_ids = TransferSession.all_objects.filter(
        state__in=terminal_states,
        updated_at__lte=cutoff,
        parts_purged_at__isnull=True,
    ).values_list("pk", flat=True)
    sessions_purged = 0
    parts_purged = 0
    for session_id in candidate_ids.iterator():
        with transaction.atomic():
            current = TransferSession.all_objects.select_for_update().filter(pk=session_id).first()
            if (
                current is None
                or current.state not in terminal_states
                or current.updated_at > cutoff
                or current.parts_purged_at is not None
            ):
                continue
            manifest = current.part_manifest
            if not isinstance(manifest, dict):
                raise ValueError(f"Transfer {current.transfer_id} has an invalid part manifest.")
            prefix = f"{current.staging_prefix}/parts/"
            for part_number, part in manifest.items():
                try:
                    number = int(part_number)
                    object_key = part["object_key"]
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Transfer {current.transfer_id} has an invalid part entry.") from exc
                expected_key = f"{prefix}{number:05d}"
                if number < 1 or object_key != expected_key:
                    raise ValueError(f"Transfer {current.transfer_id} part key is outside its staging prefix.")
                backend.delete(current.tenant_id, object_key)
                parts_purged += 1
            current.parts_purged_at = now
            current.save(update_fields=("parts_purged_at", "updated_at"))
            sessions_purged += 1
    return {"sessions_purged": sessions_purged, "parts_purged": parts_purged}
