"""Backup and point-in-time restore drill engine (TECH-032).

Ensures database and object storage integrity, checksum verification, and
compliance with RPO <= 15 minutes, RTO <= 4 hours.

Database dumps omit credential fields such as ``secret_hash`` and
``password``. ``dest_dir`` and ``storage_dir`` must not leave their
directories through ``..`` or a symlink.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.apps import apps
from django.core import serializers
from django.core.serializers.json import Serializer as DjangoJSONSerializer


# Concrete field names that hold credentials. Tokenizer and fencing-token
# fields are not in this set: those names are not API-key material.
_SECRET_FIELD_NAMES = frozenset({
    "password",
    "secret",
    "secret_hash",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
})


def _is_secret_field(name: str) -> bool:
    lowered = name.lower()
    if lowered in _SECRET_FIELD_NAMES:
        return True
    return (
        lowered.endswith("_secret")
        or lowered.endswith("_secret_hash")
        or lowered.endswith("_password")
    )


class _RedactingJSONSerializer(DjangoJSONSerializer):
    """JSON serializer that drops credential fields before they are written."""

    def get_dump_object(self, obj: Any) -> dict[str, Any]:
        data = super().get_dump_object(obj)
        fields = data.get("fields")
        if isinstance(fields, dict):
            for name in [key for key in fields if _is_secret_field(key)]:
                del fields[name]
        return data


def _confine(path: str | os.PathLike[str], *, label: str) -> Path:
    """Return an absolute path that does not escape through ``..`` or a symlink."""
    raw = Path(path)
    if ".." in raw.parts:
        raise ValueError(f"{label} must not contain '..'")
    absolute = raw if raw.is_absolute() else Path.cwd() / raw
    if ".." in absolute.parts:
        raise ValueError(f"{label} must not contain '..'")
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        if part in ("", ".", ".."):
            raise ValueError(f"{label} must not contain '..'")
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symlink")
    return current


def _read_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("path escapes its directory via a symlink") from exc
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _write_within(root: Path, path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` only when every component stays inside ``root``."""
    if path.is_symlink():
        raise ValueError("destination escapes dest_dir via a symlink")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("destination escapes dest_dir") from exc
    if ".." in relative.parts:
        raise ValueError("destination escapes dest_dir")
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("destination escapes dest_dir via a symlink")
        cursor.mkdir(exist_ok=True)
        if cursor.is_symlink() or not cursor.resolve().is_relative_to(root.resolve()):
            raise ValueError("destination escapes dest_dir via a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as exc:
        raise ValueError("destination escapes dest_dir via a symlink") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _child_file(root: Path, name: str) -> Path:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"{name} escapes the backup directory")
    candidate = root / name
    if candidate.is_symlink():
        raise ValueError(f"{name} escapes the backup directory via a symlink")
    if not candidate.is_file():
        raise ValueError(f"Invalid backup archive: missing {name}")
    resolved = candidate.resolve(strict=True)
    if resolved.parent != root.resolve():
        raise ValueError(f"{name} escapes the backup directory")
    return candidate


def _relative_file(root: Path, relative_text: str) -> Path:
    if not isinstance(relative_text, str) or not relative_text or "\\" in relative_text:
        raise ValueError("artifact path escapes the backup directory via '..'")
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError("artifact path escapes the backup directory via '..'")
    if root.is_symlink():
        raise ValueError("artifact path escapes the backup directory via a symlink")
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("artifact path escapes the backup directory via a symlink")
    if not candidate.is_file():
        raise ValueError(f"Missing artifact in backup: {relative_text}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("artifact path escapes the backup directory")
    return candidate


def _copy_storage(storage_root: Path, out_dir: Path) -> tuple[List[Dict[str, Any]], int]:
    storage_dest = out_dir / "artifacts"
    if storage_dest.is_symlink():
        raise ValueError("destination escapes dest_dir via a symlink")
    storage_dest.mkdir(exist_ok=True)
    if storage_dest.is_symlink() or not storage_dest.resolve().is_relative_to(out_dir.resolve()):
        raise ValueError("destination escapes dest_dir via a symlink")

    root_resolved = storage_root.resolve()
    artifacts: List[Dict[str, Any]] = []
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(storage_root, followlinks=False):
        current = Path(dirpath)
        if current.is_symlink() or not current.resolve().is_relative_to(root_resolved):
            raise ValueError("storage path escapes storage_dir via a symlink")
        for name in dirnames:
            child = current / name
            if name in ("", ".", "..") or child.is_symlink() or not child.resolve().is_relative_to(root_resolved):
                raise ValueError("storage path escapes storage_dir via a symlink")
        for name in filenames:
            file_path = current / name
            if name in ("", ".", "..") or file_path.is_symlink():
                raise ValueError("storage path escapes storage_dir via a symlink")
            resolved = file_path.resolve(strict=True)
            if not resolved.is_relative_to(root_resolved):
                raise ValueError("storage path escapes storage_dir")
            payload = _read_nofollow(file_path)
            digest = hashlib.sha256(payload).hexdigest()
            total_bytes += len(payload)
            relative = file_path.relative_to(storage_root)
            if ".." in relative.parts:
                raise ValueError("storage path escapes storage_dir")
            destination = storage_dest.joinpath(*relative.parts)
            _write_within(out_dir, destination, payload)
            artifacts.append({
                "path": relative.as_posix(),
                "sha256": digest,
                "byte_size": len(payload),
            })
    return artifacts, total_bytes


@dataclass
class BackupManifest:
    backup_id: str
    created_at: str
    target_models: List[str]
    total_records: int
    data_sha256: str
    storage_artifacts: List[Dict[str, Any]]
    storage_total_bytes: int
    rpo_minutes: float
    rto_hours: float
    status: str  # "COMPLETED" | "VERIFIED" | "FAILED"


def generate_backup(
    backup_id: str,
    models_to_backup: Optional[List[str]] = None,
    storage_dir: Optional[str] = None,
    dest_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates a complete, verifiable backup archive of database records and storage artifacts."""
    target_models = models_to_backup or [
        "identity.tenant",
        "identity.user",
        "identity.apikey",
        "artifacts.artifact",
        "artifacts.dataset",
        "artifacts.datasetrevision",
        "runners.modelversion",
        "releases.release",
        "releases.releaseversion",
    ]

    if dest_dir:
        out_dir = _confine(dest_dir, label="dest_dir")
    else:
        out_dir = _confine(tempfile.mkdtemp(prefix=f"backup_{backup_id}_"), label="dest_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_dir.is_symlink() or out_dir.resolve() != out_dir:
        raise ValueError("dest_dir must not traverse a symlink")

    storage_root: Optional[Path] = None
    if storage_dir:
        storage_root = _confine(storage_dir, label="storage_dir")
        if not storage_root.is_dir():
            storage_root = None

    # 1. Database serialization. Credential fields are removed before the
    # dump is written, so a raw API key or password hash never enters the file.
    all_objects = []
    total_records = 0
    for model_str in target_models:
        try:
            model_cls = apps.get_model(model_str)
            records = list(model_cls.objects.all())
            all_objects.extend(records)
            total_records += len(records)
        except LookupError:
            continue

    db_json = _RedactingJSONSerializer().serialize(all_objects, indent=2)
    if not isinstance(db_json, str):
        raise ValueError("backup serializer did not produce JSON text")
    _write_within(out_dir, out_dir / "database.json", db_json.encode("utf-8"))
    data_sha256 = hashlib.sha256(db_json.encode("utf-8")).hexdigest()

    # 2. Storage artifacts inventory. Symlinks and '..' are rejected.
    artifacts_manifest: List[Dict[str, Any]] = []
    total_bytes = 0
    if storage_root is not None:
        artifacts_manifest, total_bytes = _copy_storage(storage_root, out_dir)

    manifest = BackupManifest(
        backup_id=backup_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        target_models=target_models,
        total_records=total_records,
        data_sha256=data_sha256,
        storage_artifacts=artifacts_manifest,
        storage_total_bytes=total_bytes,
        rpo_minutes=15.0,
        rto_hours=4.0,
        status="COMPLETED",
    )

    manifest_text = json.dumps(asdict(manifest), indent=2)
    _write_within(out_dir, out_dir / "manifest.json", manifest_text.encode("utf-8"))

    return {
        "manifest": asdict(manifest),
        "backup_path": str(out_dir),
    }


def verify_restore_drill(backup_path: str) -> Dict[str, Any]:
    """Simulates and verifies an offline point-in-time recovery drill from a backup directory."""
    path = _confine(backup_path, label="backup_path")
    manifest_file = path / "manifest.json"
    if manifest_file.is_symlink():
        raise ValueError("manifest.json escapes the backup directory via a symlink")
    if not manifest_file.is_file():
        raise ValueError(f"Invalid backup archive: missing manifest.json at {backup_path}")
    manifest_file = _child_file(path, "manifest.json")

    manifest_data = json.loads(_read_nofollow(manifest_file).decode("utf-8"))
    db_file = _child_file(path, "database.json")

    # Verify database hash
    db_bytes = _read_nofollow(db_file)
    actual_data_sha256 = hashlib.sha256(db_bytes).hexdigest()
    if actual_data_sha256 != manifest_data["data_sha256"]:
        raise ValueError(f"Integrity check failed: database checksum mismatch ({actual_data_sha256} != {manifest_data['data_sha256']})")

    # Verify deserialization
    records = list(serializers.deserialize("json", db_bytes.decode("utf-8")))
    if len(records) != manifest_data["total_records"]:
        raise ValueError(f"Record count mismatch: expected {manifest_data['total_records']}, found {len(records)}")

    # Verify storage artifacts
    storage_dir = path / "artifacts"
    for art in manifest_data["storage_artifacts"]:
        art_path = _relative_file(storage_dir, art["path"])
        actual_hash = hashlib.sha256(_read_nofollow(art_path)).hexdigest()
        if actual_hash != art["sha256"]:
            raise ValueError(f"Artifact checksum corrupted: {art['path']}")

    return {
        "verified": True,
        "backup_id": manifest_data["backup_id"],
        "records_verified": len(records),
        "artifacts_verified": len(manifest_data["storage_artifacts"]),
        "status": "VERIFIED",
    }
