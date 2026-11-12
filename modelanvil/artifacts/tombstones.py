"""Tombstone hooks and authorization fail-closed enforcement (WP-04)."""
from __future__ import annotations

from typing import Any, Optional
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.jobs.models import OutboxEvent


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _missing(*values: Any) -> bool:
    return any(_text(value) == "" for value in values)


def _artifact_for(tenant_id: Any, resource_id: Any) -> Optional[Artifact]:
    """Resolve an artifact by public id or primary key. Lookup errors resolve to nothing."""
    if _missing(tenant_id, resource_id):
        return None
    text = _text(resource_id)
    try:
        parsed = uuid.UUID(text)
    except (ValueError, TypeError, AttributeError):
        parsed = None
    if parsed is not None:
        try:
            return Artifact.objects.filter(tenant_id=tenant_id, artifact_id=parsed).first()
        except (ValueError, ValidationError, TypeError):
            return None
    keys = [resource_id] if text == resource_id else [resource_id, text]
    for key in keys:
        try:
            found = Artifact.objects.filter(tenant_id=tenant_id, pk=key).first()
        except (ValueError, ValidationError, TypeError):
            continue
        if found is not None:
            return found
    return None


def _has_tombstone_row(tenant_id: Any, resource_type: Any, resource_id: Any) -> bool:
    if _missing(tenant_id, resource_type, resource_id):
        return False
    try:
        return DeletionTombstone.objects.filter(
            tenant_id=tenant_id,
            resource_type=_text(resource_type),
            resource_id=_text(resource_id),
        ).exists()
    except (ValueError, ValidationError, TypeError):
        return True


def _artifact_is_tombstoned(tenant_id: Any, resource_id: Any) -> bool:
    artifact = _artifact_for(tenant_id, resource_id)
    if artifact is None:
        return False
    if artifact.state == Artifact.State.TOMBSTONED:
        return True
    return _has_tombstone_row(tenant_id, "artifact", artifact.artifact_id)


def _refused_as_tombstoned(tenant_id: Any, resource_type: Any, resource_id: Any) -> bool:
    if _has_tombstone_row(tenant_id, resource_type, resource_id):
        return True
    if _text(resource_type) == "artifact":
        return _artifact_is_tombstoned(tenant_id, resource_id)
    return False


def _write_tombstone(
    tenant_id: Any,
    resource_type: str,
    resource_id: str,
    *,
    reason: str,
    detail: dict[str, Any],
) -> DeletionTombstone:
    tombstone, _ = DeletionTombstone.objects.update_or_create(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
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
            "resource_id": resource_id,
            "reason": reason,
            "tombstoned_at": tombstone.tombstoned_at.isoformat(),
        },
    )
    return tombstone


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
    A missing tenant, resource type, or resource id is refused. An id that
    does not resolve still records a tombstone so a later check fails closed.
    """
    if _missing(tenant_id, resource_type, resource_id):
        raise PermissionDenied("Resource identifier is missing; tombstone registration is refused.")

    detail = detail or {}
    stored_type = _text(resource_type)
    stored_id = _text(resource_id)
    artifact = _artifact_for(tenant_id, resource_id) if stored_type == "artifact" else None
    if artifact is not None and artifact.state == Artifact.State.COMMITTED:
        artifact.tombstone()

    tombstone = _write_tombstone(
        tenant_id,
        stored_type,
        stored_id,
        reason=reason,
        detail=detail,
    )
    canonical_id = str(artifact.artifact_id) if artifact is not None else ""
    if canonical_id and canonical_id != stored_id:
        _write_tombstone(
            tenant_id,
            "artifact",
            canonical_id,
            reason=reason,
            detail=detail,
        )
    return tombstone


def is_resource_tombstoned(tenant_id: Any, resource_type: str, resource_id: str) -> bool:
    """Check if a resource has been tombstoned.

    Missing identifiers and unresolved artifact ids return True so a caller
    that only consults this predicate still fails closed. A non-artifact id
    with no tombstone row returns False.
    """
    if _missing(tenant_id, resource_type, resource_id):
        return True
    if _refused_as_tombstoned(tenant_id, resource_type, resource_id):
        return True
    if _text(resource_type) == "artifact" and _artifact_for(tenant_id, resource_id) is None:
        return True
    return False


def enforce_resource_active(tenant_id: Any, resource_type: str, resource_id: str) -> None:
    """Fail closed if the resource has been tombstoned, or the id is missing or unknown.

    Raises PermissionDenied. A resolved artifact that is not tombstoned, and a
    non-artifact id with no tombstone row, are left unchanged.
    """
    if _missing(tenant_id, resource_type, resource_id):
        raise PermissionDenied("Resource identifier is missing; access is refused.")
    if _refused_as_tombstoned(tenant_id, resource_type, resource_id):
        raise PermissionDenied(
            f"Resource {resource_type}:{resource_id} has been tombstoned and cannot be accessed or used."
        )
    if _text(resource_type) == "artifact" and _artifact_for(tenant_id, resource_id) is None:
        raise PermissionDenied(
            f"Resource {resource_type}:{resource_id} is unknown and cannot be accessed or used."
        )
