"""Backup archives omit API-key material and stay inside their directories.

The planted values below are throwaway fixtures. They are not credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from django.core import serializers
from django.test import TestCase

from modelanvil.identity.models import ApiKey, Role, Tenant, User
from modelanvil.ops.backup import generate_backup, verify_restore_drill

# Low-entropy fixtures. A full serializer of the API-key row includes the
# first value because it is stored on secret_hash. The archive must not.
PLANTED_MATERIAL = "mkv_anvil079_fixture_raw_token"
PLANTED_PASSWORD = "anvil079-fixture-password"
OUTSIDE_SENTINEL = b"outside-sentinel-anvil079"
WEIGHTS = b"model-weights-ok"


def _archive_bytes(root: Path) -> bytes:
    if not root.exists():
        return b""
    chunks: list[bytes] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        dirnames[:] = [name for name in dirnames if not (base / name).is_symlink()]
        for name in sorted(filenames):
            file = base / name
            if file.is_symlink() or not file.is_file():
                continue
            chunks.append(file.read_bytes())
    return b"\n".join(chunks)


def _assert_absent(test: TestCase, needle: str | bytes, blob: bytes) -> None:
    encoded = needle.encode("utf-8") if isinstance(needle, str) else needle
    if encoded and encoded in blob:
        test.fail("archive contains planted secret material")


class BackupRedactionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="backup-redaction", name="Backup Redaction")
        self.user = User.objects.create(email="backup-redaction@example.com", name="Backup Redaction")
        self.user.set_password(PLANTED_PASSWORD)
        self.user.save()
        self.api_key = ApiKey.objects.create(
            tenant=self.tenant,
            name="backup-probe",
            role=Role.ENGINEER,
            secret_hash=PLANTED_MATERIAL,
        )

    def test_planted_api_key_material_is_absent_and_archive_verifies(self):
        """A row that holds the fixture token must not copy it into the archive.

        Django's unredacted serializer still emits the token, so a backup that
        writes that dump turns this test red. Non-secret fields stay, and the
        redacted archive still passes verify_restore_drill.
        """
        unredacted = serializers.serialize("json", [self.api_key, self.user])
        self.assertIn(PLANTED_MATERIAL, unredacted)
        self.assertIn(self.user.password, unredacted)

        with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as dest_dir:
            weights = Path(storage_dir) / "nested" / "weights.bin"
            weights.parent.mkdir(parents=True)
            weights.write_bytes(WEIGHTS)

            backup = generate_backup(
                backup_id="redaction-anvil079",
                storage_dir=storage_dir,
                dest_dir=dest_dir,
            )
            archive = Path(backup["backup_path"])
            blob = _archive_bytes(archive)
            _assert_absent(self, PLANTED_MATERIAL, blob)
            _assert_absent(self, PLANTED_PASSWORD, blob)
            _assert_absent(self, self.user.password, blob)

            database = (archive / "database.json").read_text(encoding="utf-8")
            self.assertIn(self.tenant.slug, database)
            self.assertIn(self.user.email, database)
            self.assertIn(self.api_key.name, database)
            self.assertIn(WEIGHTS, blob)

            drill = verify_restore_drill(backup["backup_path"])
            self.assertTrue(drill["verified"])
            self.assertEqual(drill["status"], "VERIFIED")
            self.assertGreaterEqual(drill["records_verified"], 3)
            self.assertEqual(drill["artifacts_verified"], 1)

    def test_clean_non_secret_backup_verifies(self):
        with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as dest_dir:
            weights = Path(storage_dir) / "weights.bin"
            weights.write_bytes(WEIGHTS)
            backup = generate_backup(
                backup_id="clean-anvil079",
                models_to_backup=["identity.tenant", "identity.user"],
                storage_dir=storage_dir,
                dest_dir=dest_dir,
            )
            drill = verify_restore_drill(backup["backup_path"])
            self.assertTrue(drill["verified"])
            self.assertEqual(drill["status"], "VERIFIED")
            self.assertEqual(drill["artifacts_verified"], 1)
            database = Path(backup["backup_path"], "database.json").read_text(encoding="utf-8")
            self.assertIn(self.tenant.slug, database)
            self.assertNotIn(PLANTED_MATERIAL, database)

    def test_dest_dir_parent_segment_cannot_escape(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            intended = root_path / "intended"
            outside = root_path / "outside"
            intended.mkdir()
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_bytes(OUTSIDE_SENTINEL)
            escape = intended / ".." / "outside"
            with self.assertRaises(ValueError) as ctx:
                generate_backup(
                    backup_id="dest-dotdot",
                    models_to_backup=["identity.tenant"],
                    dest_dir=str(escape),
                )
            self.assertIn("..", str(ctx.exception))
            self.assertFalse((outside / "database.json").exists())
            self.assertFalse((outside / "manifest.json").exists())
            self.assertEqual(sentinel.read_bytes(), OUTSIDE_SENTINEL)
            self.assertNotIn(OUTSIDE_SENTINEL, _archive_bytes(intended))

    def test_dest_file_symlink_is_not_written(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            dest = root_path / "dest"
            dest.mkdir()
            outside = root_path / "outside.json"
            outside.write_bytes(OUTSIDE_SENTINEL)
            (dest / "database.json").symlink_to(outside)
            with self.assertRaises(ValueError) as ctx:
                generate_backup(
                    backup_id="dest-file-symlink",
                    models_to_backup=["identity.tenant"],
                    dest_dir=str(dest),
                )
            self.assertIn("symlink", str(ctx.exception).lower())
            self.assertEqual(outside.read_bytes(), OUTSIDE_SENTINEL)
            self.assertNotIn(OUTSIDE_SENTINEL, _archive_bytes(dest))

    def test_dest_dir_symlink_cannot_escape(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            outside = root_path / "outside"
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_bytes(OUTSIDE_SENTINEL)
            link = root_path / "dest-link"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError) as ctx:
                generate_backup(
                    backup_id="dest-symlink",
                    models_to_backup=["identity.tenant"],
                    dest_dir=str(link),
                )
            self.assertIn("symlink", str(ctx.exception).lower())
            self.assertFalse((outside / "database.json").exists())
            self.assertFalse((outside / "manifest.json").exists())
            self.assertEqual(sentinel.read_bytes(), OUTSIDE_SENTINEL)

    def test_storage_dir_parent_segment_cannot_escape(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            secret_dir = root_path / "secret"
            storage = root_path / "storage"
            dest = root_path / "dest"
            secret_dir.mkdir()
            storage.mkdir()
            dest.mkdir()
            (secret_dir / "key.bin").write_bytes(OUTSIDE_SENTINEL)
            escape = storage / ".." / "secret"
            with self.assertRaises(ValueError) as ctx:
                generate_backup(
                    backup_id="storage-dotdot",
                    models_to_backup=["identity.tenant"],
                    storage_dir=str(escape),
                    dest_dir=str(dest),
                )
            self.assertIn("..", str(ctx.exception))
            self.assertNotIn(OUTSIDE_SENTINEL, _archive_bytes(dest))
            self.assertEqual((secret_dir / "key.bin").read_bytes(), OUTSIDE_SENTINEL)

    def test_storage_dir_symlink_cannot_escape(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            outside = root_path / "outside-storage"
            dest = root_path / "dest"
            outside.mkdir()
            dest.mkdir()
            (outside / "secret.bin").write_bytes(OUTSIDE_SENTINEL)
            link = root_path / "storage-link"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError) as ctx:
                generate_backup(
                    backup_id="storage-symlink",
                    models_to_backup=["identity.tenant"],
                    storage_dir=str(link),
                    dest_dir=str(dest),
                )
            self.assertIn("symlink", str(ctx.exception).lower())
            self.assertNotIn(OUTSIDE_SENTINEL, _archive_bytes(dest))
            self.assertEqual((outside / "secret.bin").read_bytes(), OUTSIDE_SENTINEL)

    def test_storage_symlink_file_is_not_copied(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            storage = root_path / "storage"
            dest = root_path / "dest"
            storage.mkdir()
            dest.mkdir()
            outside = root_path / "secret.bin"
            outside.write_bytes(OUTSIDE_SENTINEL)
            (storage / "alias.bin").symlink_to(outside)
            with self.assertRaises(ValueError) as ctx:
                generate_backup(
                    backup_id="storage-file-symlink",
                    models_to_backup=["identity.tenant"],
                    storage_dir=str(storage),
                    dest_dir=str(dest),
                )
            self.assertIn("symlink", str(ctx.exception).lower())
            self.assertNotIn(OUTSIDE_SENTINEL, _archive_bytes(dest))
            self.assertEqual(outside.read_bytes(), OUTSIDE_SENTINEL)

    def test_storage_symlink_directory_is_not_walked(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            storage = root_path / "storage"
            dest = root_path / "dest"
            outside = root_path / "outside-dir"
            storage.mkdir()
            dest.mkdir()
            outside.mkdir()
            (outside / "secret.bin").write_bytes(OUTSIDE_SENTINEL)
            (storage / "linked").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError) as ctx:
                generate_backup(
                    backup_id="storage-dir-symlink",
                    models_to_backup=["identity.tenant"],
                    storage_dir=str(storage),
                    dest_dir=str(dest),
                )
            self.assertIn("symlink", str(ctx.exception).lower())
            self.assertNotIn(OUTSIDE_SENTINEL, _archive_bytes(dest))

    def test_verify_rejects_artifact_parent_segment(self):
        with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as dest_dir:
            (Path(storage_dir) / "weights.bin").write_bytes(WEIGHTS)
            backup = generate_backup(
                backup_id="verify-dotdot",
                models_to_backup=["identity.tenant"],
                storage_dir=storage_dir,
                dest_dir=dest_dir,
            )
            archive = Path(backup["backup_path"])
            outside = archive.parent / "sentinel-anvil079.txt"
            outside.write_bytes(OUTSIDE_SENTINEL)
            manifest_path = archive / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["storage_artifacts"] = [{
                "path": "../../sentinel-anvil079.txt",
                "sha256": hashlib.sha256(OUTSIDE_SENTINEL).hexdigest(),
                "byte_size": len(OUTSIDE_SENTINEL),
            }]
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                verify_restore_drill(str(archive))
            self.assertIn("..", str(ctx.exception))
            self.assertEqual(outside.read_bytes(), OUTSIDE_SENTINEL)

    def test_verify_rejects_artifact_symlink(self):
        with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as dest_dir:
            (Path(storage_dir) / "weights.bin").write_bytes(WEIGHTS)
            backup = generate_backup(
                backup_id="verify-symlink",
                models_to_backup=["identity.tenant"],
                storage_dir=storage_dir,
                dest_dir=dest_dir,
            )
            archive = Path(backup["backup_path"])
            outside = archive.parent / "secret.bin"
            outside.write_bytes(OUTSIDE_SENTINEL)
            artifact = archive / "artifacts" / "weights.bin"
            artifact.unlink()
            artifact.symlink_to(outside)
            manifest_path = archive / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["storage_artifacts"][0]["sha256"] = hashlib.sha256(OUTSIDE_SENTINEL).hexdigest()
            manifest["storage_artifacts"][0]["byte_size"] = len(OUTSIDE_SENTINEL)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                verify_restore_drill(str(archive))
            self.assertIn("symlink", str(ctx.exception).lower())
            self.assertEqual(outside.read_bytes(), OUTSIDE_SENTINEL)
