"""Complete content-pinned releases, downloaded in bounded resumable parts."""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
from datetime import timedelta
from pathlib import Path, PurePosixPath

from django.db import transaction
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.artifacts.models import Artifact, LineageEdge, TransferSession
from modelanvil.artifacts.storage import (
    artifact_storage_backend,
    upload_staged_artifact,
)
from modelanvil.artifacts.transfers import (
    MAX_TRANSFER_PART_BYTES,
    add_transfer_part,
    complete_transfer,
)
from modelanvil.data.bank.http_snapshot import (
    SnapshotError,
    _url,
    canonical_json,
    digest,
    fetch_range,
)

CONNECTOR = "qualified_full_http_release_v1"
MANIFEST_ROOT = Path(__file__).resolve().parents[3] / "catalog" / "full-datasets"
NOTICE_ROOT = MANIFEST_ROOT.parent / "qualified-datasets" / "notices"
MAX_FILES = 1000
MAX_FILE_BYTES = 128 * 1024**3


def load_manifest(source):
    try:
        if not re.fullmatch(r"[a-z0-9-]+", source.id):
            raise ValueError()
        raw = (MANIFEST_ROOT / (source.id + ".json")).read_bytes()
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError()
        manifest = json.loads(raw)
        if (
            digest(canonical_json(manifest)) != source.acquisition.pinned_revision
            or manifest["source_id"] != source.id
        ):
            raise ValueError()
        files = manifest["files"]
        if (
            not 1 <= len(files) <= MAX_FILES
            or len({f["path"] for f in files}) != len(files)
            or not manifest["licenses"]
        ):
            raise ValueError()
        for file in files:
            _url(file["url"])
            for mirror in file.get("mirrors", []):
                _url(mirror)
            if file["format"] not in ("parquet", "json", "zip", "tar.gz"):
                raise ValueError()
            path = PurePosixPath(file["path"])
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in file["path"]
                or not file["path"]
            ):
                raise ValueError()
            if (
                type(file["size"]) is not int
                or not 1 <= file["size"] <= MAX_FILE_BYTES
                or not re.fullmatch(r"[a-f0-9]{64}", file["sha256"])
            ):
                raise ValueError()
            position = 0
            for chunk in file["chunks"]:
                if (
                    type(chunk["start"]) is not int
                    or chunk["start"] != position
                    or type(chunk["length"]) is not int
                    or not 1 <= chunk["length"] <= MAX_TRANSFER_PART_BYTES
                    or not re.fullmatch(r"[a-f0-9]{64}", chunk["sha256"])
                ):
                    raise ValueError()
                position += chunk["length"]
            if (
                position != file["size"]
                or len(file["chunks"]) > 10000
                or file.get("validation", {}).get("all_content_read") is not True
            ):
                raise ValueError()
        return manifest
    except (OSError, ValueError, TypeError, KeyError):
        raise SnapshotError(
            "The full-release qualification manifest is invalid or unavailable."
        ) from None


def verify_notices(manifest):
    notices = []
    for notice in manifest["licenses"]:
        name = notice["archive_name"]
        if Path(name).name != name:
            raise SnapshotError("Invalid archived publisher notice path.")
        raw = (NOTICE_ROOT / name).read_bytes()
        if digest(raw) != notice["sha256"] or len(raw) != notice["size"]:
            raise SnapshotError(
                "Publisher notice differs from the full-release qualification."
            )
        notices.append({**notice, "text": raw.decode("utf-8")})
    return notices


def preflight(
    catalog, source_id, *, tenant_id, project_policy=None, source_revision=None
):
    # Apply the same license gate as sample acquisition before touching storage/network.
    policy = dict(project_policy or {})
    base = catalog.preflight_download(
        source_id,
        tenant_id=tenant_id,
        project_policy={
            k: v
            for k, v in policy.items()
            if k not in ("record_limit", "max_storage_quota_bytes")
        },
    )
    source = catalog.source_for_full_download(source_id)
    manifest = load_manifest(source)
    verify_notices(manifest)
    if source_revision and source_revision != source.acquisition.pinned_revision:
        raise SnapshotError("Requested revision is not the qualified full release.")
    count = len(manifest["files"])
    if policy.get("record_limit") not in (None, count):
        raise SnapshotError(
            "A full download must include every file in the qualified release."
        )
    total = sum(file["size"] for file in manifest["files"])
    quota = policy.get("max_storage_quota_bytes", 100 * 1024**3)
    if type(quota) is not int or quota < 0 or 2 * total > quota:
        raise SnapshotError(
            "Full download and retained transfer parts exceed the storage quota; allow at least twice the release bytes."
        )
    return {
        **base,
        "download_scope": "full",
        "source_revision": source.acquisition.pinned_revision,
        "access": {**base["access"], "license_paths": source.acquisition.license_paths},
        "estimated_bytes": total,
        "storage_required_bytes": 2 * total,
        "scope": {
            "record_limit": count,
            "record_limit_max": count,
            "available_records": count,
            "record_selection": "all qualified release files",
            "record_unit": "source_files",
        },
        "qualification_evidence": vars(source.acquisition),
    }


def execute(descriptor, context, source, snapshot):
    from modelanvil.data.bank.acquisition import (
        AcquisitionCancelled,
        AcquisitionLeaseLost,
        UpstreamError,
        _checkpoint,
        _settle_budget,
        https_transport,
    )
    from modelanvil.data.models import SourceSnapshot

    manifest = load_manifest(source)
    notices = verify_notices(manifest)
    backend = artifact_storage_backend()
    detail = dict(snapshot.detail)
    plan = dict(detail["acquisition"])
    verified = dict(plan.get("verified") or {})
    total = sum(file["size"] for file in manifest["files"])
    resumed = int(descriptor["payload"].get("resumed_from_records") or 0)

    last_heartbeat = 0.0

    def heartbeat(progress, force=False):
        nonlocal last_heartbeat
        if not force and time.monotonic() - last_heartbeat < 2:
            return
        last_heartbeat = time.monotonic()
        if not context.heartbeat(min(0.99, progress)):
            if getattr(context, "lease_lost", False):
                raise AcquisitionLeaseLost("Full download lost its worker lease.")
            raise AcquisitionCancelled(
                "Full download was cancelled before publication."
            )

    def verify_cached(artifact):
        sha256 = hashlib.sha256()
        size = 0
        with backend.open(snapshot.tenant_id, artifact.object_key) as stream:
            while raw := stream.read(1024 * 1024):
                heartbeat(0.99)
                sha256.update(raw)
                size += len(raw)
        if sha256.hexdigest() != artifact.sha256 or size != artifact.byte_size:
            raise UpstreamError(
                "Cached complete-release file failed its qualified digest."
            )

    for file in manifest["files"]:
        heartbeat(sum(entry["size"] for entry in verified.values()) / total, force=True)
        entry = verified.get(file["path"])
        artifact = (
            Artifact.all_objects.filter(
                artifact_id=entry.get("artifact_id"),
                tenant_id=snapshot.tenant_id,
                project_id=snapshot.project_id,
                state=Artifact.State.COMMITTED,
            ).first()
            if entry
            else None
        )
        if (
            artifact
            and artifact.sha256 == file["sha256"]
            and artifact.byte_size == file["size"]
        ):
            verify_cached(artifact)
            continue
        artifact, _ = Artifact.all_objects.get_or_create(
            tenant_id=snapshot.tenant_id,
            storage_location_id="local",
            object_key=f"bank/{source.id}/{snapshot.snapshot_id}/full/{file['path']}",
            defaults={
                "project_id": snapshot.project_id,
                "sha256": file["sha256"],
                "byte_size": file["size"],
                "media_type": {
                    "parquet": "application/vnd.apache.parquet",
                    "json": "application/json",
                    "zip": "application/zip",
                    "tar.gz": "application/gzip",
                }[file["format"]],
                "metadata": {
                    "kind": "dataset_bank_full_file",
                    "source_id": source.id,
                    "source_revision": source.acquisition.pinned_revision,
                    "source_path": file["path"],
                },
            },
        )
        if (
            artifact.project_id != snapshot.project_id
            or artifact.sha256 != file["sha256"]
            or artifact.byte_size != file["size"]
        ):
            raise UpstreamError(
                "Full-download artifact differs from its qualified file or project."
            )
        if artifact.state == Artifact.State.COMMITTED:
            verify_cached(artifact)
        else:
            transfer, _ = TransferSession.all_objects.get_or_create(
                tenant_id=snapshot.tenant_id,
                artifact=artifact,
                defaults={
                    "staging_prefix": f"bank/{source.id}/{snapshot.snapshot_id}/parts/{artifact.artifact_id}",
                    "source_ref": file["url"],
                },
            )
            if transfer.state in (
                TransferSession.State.OPEN,
                TransferSession.State.EXPIRED,
            ):
                transfer.state = TransferSession.State.OPEN
                transfer.expires_at = timezone.now() + timedelta(days=1)
                transfer.save(update_fields=["state", "expires_at", "updated_at"])
            else:
                raise UpstreamError("Full-download transfer session is closed.")
            for number, chunk in enumerate(file["chunks"], 1):
                heartbeat(
                    (
                        sum(e["size"] for e in verified.values())
                        + transfer.bytes_verified
                    )
                    / total,
                    force=True,
                )
                known = transfer.part_manifest.get(str(number))
                if known:
                    # Re-verify cached bytes on retry through the existing transfer contract.
                    try:
                        with backend.open(
                            snapshot.tenant_id, known["object_key"]
                        ) as stored:
                            transfer = add_transfer_part(
                                transfer,
                                number,
                                stored,
                                expected_sha256=chunk["sha256"],
                                expected_size=chunk["length"],
                                backend=backend,
                            )
                        continue
                    except FileNotFoundError:
                        pass
                urls = [*file.get("mirrors", []), file["url"]]
                for index, url in enumerate(urls):
                    try:
                        raw = fetch_range(
                            url,
                            file["size"],
                            chunk["start"],
                            chunk["length"],
                            https_transport,
                        )
                        break
                    except UpstreamError:
                        if index == len(urls) - 1:
                            raise
                if digest(raw) != chunk["sha256"]:
                    raise UpstreamError(
                        "Full-release download failed its qualified chunk digest."
                    )
                transfer = add_transfer_part(
                    transfer,
                    number,
                    io.BytesIO(raw),
                    expected_sha256=chunk["sha256"],
                    expected_size=chunk["length"],
                    backend=backend,
                )
                plan["partial_bytes"] = transfer.bytes_verified
                detail["acquisition"] = plan
                _checkpoint(snapshot, detail)
            heartbeat(
                (sum(e["size"] for e in verified.values()) + file["size"]) / total
            )
            complete_transfer(
                transfer, backend=backend, heartbeat=lambda: heartbeat(0.99)
            )
            artifact.refresh_from_db()
        verified[file["path"]] = {
            "size": file["size"],
            "sha256": file["sha256"],
            "artifact_id": str(artifact.artifact_id),
        }
        plan["verified"] = verified
        plan["partial_bytes"] = 0
        detail["acquisition"] = plan
        _checkpoint(snapshot, detail)
    heartbeat(0.99, force=True)
    body = canonical_json(
        {
            "schema_version": "1.0",
            "source_id": source.id,
            "source_revision": source.acquisition.pinned_revision,
            "download_scope": "full",
            "files": [
                {
                    "path": f["path"],
                    **verified[f["path"]],
                    "validation": f["validation"],
                }
                for f in manifest["files"]
            ],
            "license": source.license_expression,
            "publisher_notices": notices,
            "training_recipe_qualified": False,
        }
    )
    receipt, _ = Artifact.all_objects.get_or_create(
        tenant_id=snapshot.tenant_id,
        storage_location_id="local",
        object_key=f"bank/{source.id}/{snapshot.snapshot_id}/full-release.json",
        defaults={
            "project_id": snapshot.project_id,
            "sha256": digest(body),
            "byte_size": len(body),
            "media_type": "application/json",
            "metadata": {"kind": "dataset_bank_full_manifest", "source_id": source.id},
        },
    )
    if (
        receipt.project_id != snapshot.project_id
        or receipt.sha256 != digest(body)
        or receipt.byte_size != len(body)
    ):
        raise UpstreamError(
            "Full-release receipt differs from its verified files or project."
        )
    if receipt.state != Artifact.State.COMMITTED:
        upload_staged_artifact(receipt, io.BytesIO(body), backend=backend)
    with transaction.atomic():
        locked = SourceSnapshot.all_objects.select_for_update().get(
            pk=snapshot.pk, tenant_id=snapshot.tenant_id
        )
        if locked.state != SourceSnapshot.State.INGESTING:
            raise AcquisitionCancelled("Full download was cancelled before completion.")
        heartbeat(0.99, force=True)
        for file in verified.values():
            parent = Artifact.all_objects.get(
                artifact_id=file["artifact_id"],
                tenant_id=snapshot.tenant_id,
                project_id=snapshot.project_id,
                state="committed",
            )
            LineageEdge.all_objects.get_or_create(
                tenant_id=snapshot.tenant_id,
                parent_artifact=parent,
                child_artifact=receipt,
                relation="full_release_file",
            )
        plan["manifest_artifact_id"] = str(receipt.artifact_id)
        plan["partial_bytes"] = 0
        detail["acquisition"] = plan
        locked.detail = detail
        locked.save(update_fields=["detail", "updated_at"])
        locked.mark_ready(manifest_digest=receipt.sha256, item_count=len(verified))
        _settle_budget(
            descriptor.get("job_id"),
            snapshot.tenant_id,
            max(0, len(verified) - resumed),
            download_scope="full",
        )
    return {
        "schema_version": "1.0",
        "sample_id": str(uuid7()),
        "source_group_id": str(snapshot.snapshot_id),
        "blocks": [
            {
                "block_id": "full-release",
                "type": "json",
                "value": {
                    "status": "downloaded",
                    "manifest_artifact_id": str(receipt.artifact_id),
                    "files_verified": len(verified),
                    "byte_size": total,
                },
            }
        ],
        "provenance": {
            "source_snapshot_ref": str(snapshot.snapshot_id),
            "source_record_key": source.id,
            "content_sha256": receipt.sha256,
        },
    }
