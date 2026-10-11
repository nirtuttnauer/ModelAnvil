"""Resumable download workflow, snapshot management, and isolation enforcement (WP-06 / TECH-005, TECH-010)."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from django.core.exceptions import PermissionDenied, ValidationError

from modelanvil.data.bank.catalog import DatasetBankCatalog
from modelanvil.data.models import DataSource, SourceSnapshot


@dataclass
class TransferProgress:
    total_bytes: int
    transferred_bytes: int
    completed: bool = False
    interrupted: bool = False


class ResumablePresetDownloader:
    """Manages resumable downloads of bank presets into tenant-scoped source snapshots."""

    def __init__(self, catalog: Optional[DatasetBankCatalog] = None) -> None:
        self.catalog = catalog or DatasetBankCatalog.load_from_file()

    def initiate_download(
        self,
        *,
        tenant_id: str | uuid.UUID,
        source_id: str,
        project_id: Any = None,
        revision: Optional[str] = None,
        project_policy: Optional[dict[str, Any]] = None,
        source_revision: Optional[str] = None,
    ) -> SourceSnapshot:
        """Initiate or get existing immutable snapshot for a given source and revision.

        ``revision`` / ``source_revision`` request a specific upstream revision;
        only revisions carrying qualification evidence are accepted, and the
        qualified default is used when neither is given.
        """
        tid = uuid.UUID(str(tenant_id)) if not isinstance(tenant_id, uuid.UUID) else tenant_id
        requested_revision = revision or source_revision

        # 1. Preflight check (enforces open content policy, share-alike opt-in, quotas,
        #    and acquisition qualification with its pinned upstream revision)
        preflight = self.catalog.preflight_download(
            source_id, tenant_id=str(tid), project_policy=project_policy,
            source_revision=requested_revision,
        )
        resolved_revision = preflight.get("source_revision") or revision

        # 2. Get or create tenant-scoped DataSource
        source_card = self.catalog.get_source(source_id)
        source_name = source_card.name if source_card else source_id

        data_source, _ = DataSource.all_objects.get_or_create(
            tenant_id=tid,
            name=f"bank-{source_id}" + (f"@{project_id}" if project_id else ""),
            defaults={
                "project_id": project_id,
                "kind": DataSource.Kind.REPOSITORY,
                "configuration": {
                    "source_id": source_id,
                    "catalog_name": source_name,
                    "license": preflight["license"],
                    "upstream_repository": source_card.acquisition.upstream_repository if source_card else "",
                    "connector": source_card.acquisition.connector if source_card else "",
                },
                "enabled": True,
            },
        )

        # 3. Check for existing snapshot for this exact revision
        existing = SourceSnapshot.all_objects.filter(
            tenant_id=tid, source=data_source, source_revision=resolved_revision
        ).first()

        if existing:
            return existing

        # Create new ingesting snapshot
        return SourceSnapshot.all_objects.create(
            tenant_id=tid,
            source=data_source,
            source_revision=resolved_revision,
            state=SourceSnapshot.State.INGESTING,
            detail={
                "source_id": source_id,
                "preflight": preflight,
                "bytes_transferred": 0,
            },
        )

    def execute_chunked_transfer(
        self,
        snapshot: SourceSnapshot,
        chunks: list[bytes],
        *,
        interrupt_after_chunk: Optional[int] = None,
    ) -> TransferProgress:
        """Exercise the snapshot checkpoint lifecycle over caller-supplied bytes.

        This transfers no upstream bytes and proves nothing about a connector;
        real acquisition is :func:`modelanvil.data.bank.acquisition.execute_acquisition`.
        """
        if snapshot.state == SourceSnapshot.State.READY:
            raise ValueError("Snapshot is already complete and immutable.")

        bytes_transferred = snapshot.detail.get("bytes_transferred", 0)
        hasher = hashlib.sha256()

        # Resume from recorded bytes if any
        progress = TransferProgress(
            total_bytes=sum(len(c) for c in chunks),
            transferred_bytes=bytes_transferred,
        )

        for idx, chunk in enumerate(chunks):
            if interrupt_after_chunk is not None and idx >= interrupt_after_chunk:
                progress.interrupted = True
                # Persist partial checkpoint
                snapshot.detail["bytes_transferred"] = progress.transferred_bytes
                snapshot.save(update_fields=["detail", "updated_at"])
                return progress

            hasher.update(chunk)
            progress.transferred_bytes += len(chunk)

        # Full transfer completed successfully
        progress.completed = True
        digest = hasher.hexdigest()
        snapshot.detail["bytes_transferred"] = progress.transferred_bytes
        snapshot.detail["content_sha256"] = digest
        snapshot.mark_ready(manifest_digest=digest, item_count=len(chunks), failure_count=0)
        return progress

    def access_snapshot(
        self,
        snapshot_id: uuid.UUID,
        *,
        requesting_tenant_id: str | uuid.UUID,
    ) -> SourceSnapshot:
        """Retrieve snapshot enforcing organization / tenant isolation (BANK06)."""
        req_tid = (
            uuid.UUID(str(requesting_tenant_id))
            if not isinstance(requesting_tenant_id, uuid.UUID)
            else requesting_tenant_id
        )

        snapshot = SourceSnapshot.objects.filter(snapshot_id=snapshot_id).first()
        if not snapshot:
            raise ValidationError("Snapshot not found.")

        if snapshot.tenant_id != req_tid:
            raise PermissionDenied(
                "Access denied: cannot access source snapshots or caches belonging to another organization."
            )

        return snapshot
