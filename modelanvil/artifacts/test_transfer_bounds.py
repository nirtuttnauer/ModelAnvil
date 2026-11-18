"""Fail-closed bounds for resumable transfer parts."""
import hashlib
import io
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.test import TestCase
from django.utils import timezone

from modelanvil.artifacts.models import Artifact, TransferSession
from modelanvil.artifacts.storage import LocalArtifactStorage
from modelanvil.artifacts.transfers import (
    MAX_TRANSFER_PART_BYTES,
    MAX_TRANSFER_PARTS,
    TransferConflict,
    TransferExpired,
    add_transfer_part,
    complete_transfer,
)
from modelanvil.identity.models import Tenant


def _sha256_filled(size: int) -> str:
    """SHA-256 of ``size`` bytes of ``b"x"``."""
    digest = hashlib.sha256()
    remaining = size
    chunk = b"x" * (1024 * 1024)
    while remaining:
        take = min(remaining, len(chunk))
        digest.update(chunk[:take])
        remaining -= take
    return digest.hexdigest()


class _FilledStream(io.RawIOBase):
    """Yield ``size`` copies of ``b"x"`` without holding the body in memory."""

    def __init__(self, size: int) -> None:
        self._left = size

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self._left <= 0:
            return b""
        if size is None or size < 0:
            size = self._left
        take = min(int(size), self._left)
        self._left -= take
        return b"x" * take


class TransferBoundsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="transfer-bounds", name="Transfer Bounds")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.backend = LocalArtifactStorage(self.root)

    def _session(self, payload: bytes = b"part") -> tuple[Artifact, TransferSession]:
        digest = hashlib.sha256(payload).hexdigest()
        artifact = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id,
            storage_location_id="local",
            object_key=f"outputs/bounds-{uuid.uuid4().hex}.bin",
            sha256=digest,
            byte_size=len(payload),
            media_type="application/octet-stream",
        )
        transfer = TransferSession.objects.create(tenant_id=self.tenant.tenant_id, artifact=artifact)
        return artifact, transfer

    def _stored_files(self) -> list[str]:
        return sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file())

    def _add(self, transfer: TransferSession, part_number: int, payload: bytes):
        digest = hashlib.sha256(payload).hexdigest()
        return add_transfer_part(
            transfer,
            part_number,
            io.BytesIO(payload),
            expected_sha256=digest,
            expected_size=len(payload),
            backend=self.backend,
        )

    def _reject(self, part_number: int, stream, *, digest: str, size: int, pattern: str) -> None:
        _artifact, transfer = self._session()
        before = self._stored_files()
        with self.assertRaisesRegex(ValueError, pattern) as caught:
            add_transfer_part(
                transfer,
                part_number,
                stream,
                expected_sha256=digest,
                expected_size=size,
                backend=self.backend,
            )
        self.assertNotIsInstance(caught.exception, TransferConflict)
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, TransferSession.State.OPEN)
        self.assertEqual(transfer.part_manifest, {})
        self.assertEqual(transfer.bytes_verified, 0)
        self.assertEqual(self._stored_files(), before)

    def test_part_number_below_one_is_rejected_and_stores_nothing(self):
        payload = b"bounded"
        digest = hashlib.sha256(payload).hexdigest()
        pattern = rf"part_number must be between 1 and {MAX_TRANSFER_PARTS}"
        for part_number in (0, -1):
            with self.subTest(part_number=part_number):
                self._reject(part_number, io.BytesIO(payload), digest=digest, size=len(payload), pattern=pattern)

    def test_part_number_above_maximum_is_rejected_and_stores_nothing(self):
        payload = b"bounded"
        digest = hashlib.sha256(payload).hexdigest()
        pattern = rf"part_number must be between 1 and {MAX_TRANSFER_PARTS}"
        for part_number in (MAX_TRANSFER_PARTS + 1, MAX_TRANSFER_PARTS + 10_000):
            with self.subTest(part_number=part_number):
                self._reject(part_number, io.BytesIO(payload), digest=digest, size=len(payload), pattern=pattern)

    def test_part_number_at_maximum_is_accepted(self):
        payload = b"last"
        _artifact, transfer = self._session(payload)
        saved = self._add(transfer, MAX_TRANSFER_PARTS, payload)
        saved.refresh_from_db()
        self.assertEqual(saved.state, TransferSession.State.OPEN)
        part = saved.part_manifest[str(MAX_TRANSFER_PARTS)]
        self.assertEqual(part["byte_size"], len(payload))
        self.assertEqual(part["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertTrue(part["object_key"].endswith(f"/parts/{MAX_TRANSFER_PARTS:05d}"))
        with self.backend.open(self.tenant.tenant_id, part["object_key"]) as stored:
            self.assertEqual(stored.read(), payload)

    def test_declared_size_zero_is_rejected_and_stores_nothing(self):
        digest = hashlib.sha256(b"").hexdigest()
        self._reject(
            1,
            io.BytesIO(b""),
            digest=digest,
            size=0,
            pattern=rf"part size must be between 1 and {MAX_TRANSFER_PART_BYTES}",
        )

    def test_declared_size_above_maximum_is_rejected_and_stores_nothing(self):
        size = MAX_TRANSFER_PART_BYTES + 1
        self._reject(
            1,
            _FilledStream(size),
            digest=_sha256_filled(size),
            size=size,
            pattern=rf"part size must be between 1 and {MAX_TRANSFER_PART_BYTES}",
        )

    def test_malformed_sha256_is_rejected_and_stores_nothing(self):
        payload = b"digest"
        malformed = (
            "",
            "abc",
            "g" * 64,
            "a" * 63,
            "a" * 65,
            "a" * 64 + "\n",
            "a" * 32 + " " + "a" * 31,
        )
        for digest in malformed:
            with self.subTest(digest=digest):
                self._reject(1, io.BytesIO(payload), digest=digest, size=len(payload), pattern="lowercase SHA-256")

    def test_uppercase_sha256_is_rejected_and_stores_nothing(self):
        payload = b"digest"
        digest = hashlib.sha256(payload).hexdigest()
        letter = next(index for index, char in enumerate(digest) if char in "abcdef")
        mixed = digest[:letter] + digest[letter].upper() + digest[letter + 1 :]
        for presented in (digest.upper(), mixed):
            with self.subTest(presented=presented):
                self._reject(
                    1,
                    io.BytesIO(payload),
                    digest=presented,
                    size=len(payload),
                    pattern="lowercase SHA-256",
                )

    def test_expired_open_session_rejects_a_new_part(self):
        first = b"kept"
        second = b"late"
        _artifact, transfer = self._session(first)
        self._add(transfer, 1, first)
        TransferSession.objects.filter(pk=transfer.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, TransferSession.State.OPEN)
        before = self._stored_files()
        with self.assertRaises(TransferExpired):
            self._add(transfer, 2, second)
        transfer.refresh_from_db()
        self.assertEqual(transfer.state, TransferSession.State.EXPIRED)
        self.assertEqual(set(transfer.part_manifest), {"1"})
        self.assertEqual(transfer.bytes_verified, len(first))
        self.assertEqual(self._stored_files(), before)
        part = transfer.part_manifest["1"]
        with self.backend.open(self.tenant.tenant_id, part["object_key"]) as stored:
            self.assertEqual(stored.read(), first)

    def test_expired_open_session_cannot_be_completed(self):
        payload = b"complete-me"
        artifact, transfer = self._session(payload)
        self._add(transfer, 1, payload)
        TransferSession.objects.filter(pk=transfer.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        with self.assertRaises(TransferExpired):
            complete_transfer(transfer, backend=self.backend)
        transfer.refresh_from_db()
        artifact.refresh_from_db()
        self.assertEqual(transfer.state, TransferSession.State.EXPIRED)
        self.assertEqual(artifact.state, Artifact.State.STAGING)
        with self.assertRaises(FileNotFoundError):
            self.backend.open(self.tenant.tenant_id, artifact.object_key)
        part = transfer.part_manifest["1"]
        with self.backend.open(self.tenant.tenant_id, part["object_key"]) as stored:
            self.assertEqual(stored.read(), payload)

    def test_valid_small_part_and_exact_retry_succeed(self):
        payload = b"small-part"
        _artifact, transfer = self._session(payload)
        first = self._add(transfer, 1, payload)
        first.refresh_from_db()
        self.assertEqual(first.state, TransferSession.State.OPEN)
        self.assertEqual(first.bytes_verified, len(payload))
        part = first.part_manifest["1"]
        self.assertEqual(part["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(part["byte_size"], len(payload))
        self.assertTrue(part["object_key"].endswith("/parts/00001"))
        with self.backend.open(self.tenant.tenant_id, part["object_key"]) as stored:
            self.assertEqual(stored.read(), payload)

        retried = self._add(first, 1, payload)
        retried.refresh_from_db()
        self.assertEqual(retried.state, TransferSession.State.OPEN)
        self.assertEqual(retried.part_manifest, first.part_manifest)
        self.assertEqual(retried.bytes_verified, len(payload))
        self.assertEqual(len(self._stored_files()), 1)
        with self.backend.open(self.tenant.tenant_id, part["object_key"]) as stored:
            self.assertEqual(stored.read(), payload)

    def test_conflicting_retry_fails_and_keeps_the_original_part(self):
        original = b"original"
        conflict = b"conflict!"
        _artifact, transfer = self._session(original)
        saved = self._add(transfer, 1, original)
        saved.refresh_from_db()
        manifest = dict(saved.part_manifest)
        with self.assertRaises(TransferConflict) as caught:
            self._add(saved, 1, conflict)
        self.assertIn("different bytes", str(caught.exception))
        saved.refresh_from_db()
        self.assertEqual(saved.state, TransferSession.State.OPEN)
        self.assertEqual(saved.part_manifest, manifest)
        self.assertEqual(saved.bytes_verified, len(original))
        self.assertEqual(len(self._stored_files()), 1)
        with self.backend.open(self.tenant.tenant_id, manifest["1"]["object_key"]) as stored:
            self.assertEqual(stored.read(), original)
