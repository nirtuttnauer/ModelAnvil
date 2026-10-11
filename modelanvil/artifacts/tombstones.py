"""Tombstone hooks and authorization fail-closed enforcement (WP-04)."""
from __future__ import annotations

from typing import Any, Optional
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.jobs.models import OutboxEvent


@transaction.atomic
def register_tombstone(
    tenant_id: Any,
    resource_type: str,
    resource_id: str,
    *,
    reason: str = "",
    detail: Optional[dict[str, Any]] = None,
) -> DeletionTombstone:
    """Mark a resource as tombstoned within the tenant.

    If the resource is a committed Artifact, marks it TOMBSTONED.
    Emits a transactional policy.tombstoned outbox event.
    """
    detail = detail or {}

    # If the resource is an artifact, call artifact.tombstone() if committed
    if resource_type == "artifact":
        try:
            art_uuid = uuid.UUID(str(resource_id))
            art = Artifact.objects.filter(tenant_id=tenant_id, artifact_id=art_uuid).first()
        except ValueError:
            art = Artifact.objects.filter(tenant_id=tenant_id, pk=resource_id).first()

        if art is not None and art.state == Artifact.State.COMMITTED:
            art.tombstone()

    tombstone, _ = DeletionTombstone.objects.update_or_create(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=str(resource_id),
        defaults={
            "reason": reason,
            "detail": detail,
            "tombstoned_at": timezone.now(),
        },
    )

    OutboxEvent.objects.create(
        tenant_id=tenant_id,
        topic=f"tenant.{tenant_id}.policy.tombstoned",
        payload={
            "event_type": "policy.tombstoned",
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "reason": reason,
            "tombstoned_at": tombstone.tombstoned_at.isoformat(),
        },
    )

    return tombstone


def is_resource_tombstoned(tenant_id: Any, resource_type: str, resource_id: str) -> bool:
    """Check if a resource has been tombstoned."""
    return DeletionTombstone.objects.filter(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=str(resource_id),
    ).exists()


def enforce_resource_active(tenant_id: Any, resource_type: str, resource_id: str) -> None:
    """Fail closed if the resource has been tombstoned."""
    if is_resource_tombstoned(tenant_id, resource_type, resource_id):
        raise PermissionDenied(
            f"Resource {resource_type}:{resource_id} has been tombstoned and cannot be accessed or used."
        )
