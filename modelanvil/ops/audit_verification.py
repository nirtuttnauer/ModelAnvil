"""Audit event and telemetry correlation verification (TECH-032).

Ensures all administrative actions, permission mutations, worker operations,
and model promotions record immutable audit entries with correlated context.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from modelanvil.core.models import AuditEvent


REQUIRED_AUDIT_FIELDS = {
    "event_id",
    "created_at",
    "tenant_id",
    "actor_id",
    "action",
    "resource_type",
    "input_snapshot",
}


def verify_audit_record(event: AuditEvent) -> Dict[str, Any]:
    """Verifies that an audit event contains full provenance and context."""
    missing = []
    for field in ["event_id", "created_at", "tenant_id", "actor_id", "action", "resource_type"]:
        val = getattr(event, field, None)
        if val is None or val == "":
            missing.append(field)

    if missing:
        return {
            "valid": False,
            "error": f"Missing required audit fields: {', '.join(missing)}",
            "event_id": str(getattr(event, "event_id", "unknown")),
        }

    return {
        "valid": True,
        "event_id": str(event.event_id),
        "resource_type": event.resource_type,
        "action": event.action,
        "actor_id": str(event.actor_id),
    }


def verify_tenant_audit_trail(tenant_id: Any) -> Dict[str, Any]:
    """Scans and verifies the integrity of a tenant's audit trail."""
    events = list(AuditEvent.all_objects.filter(tenant_id=tenant_id).order_by("created_at"))
    invalid = []
    for ev in events:
        res = verify_audit_record(ev)
        if not res["valid"]:
            invalid.append(res)

    return {
        "total_events": len(events),
        "valid_events": len(events) - len(invalid),
        "invalid_count": len(invalid),
        "all_valid": len(invalid) == 0,
        "invalid_details": invalid,
    }
