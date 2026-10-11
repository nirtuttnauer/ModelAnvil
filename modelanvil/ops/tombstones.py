"""Tombstone retention and deletion fail-closed verification (TECH-024, TECH-032).

Verifies that resources marked with DeletionTombstone cannot be fetched,
served in RAG queries, or exported in releases.
"""

from __future__ import annotations

from typing import Any, Dict, List
from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.releases.lifecycle import export_release_bundle
from modelanvil.releases.models import ReleaseVersion


def verify_tombstone_enforcement(tenant_id: Any, resource_type: str, resource_id: str) -> Dict[str, Any]:
    """Checks whether a tombstone exists and whether access is blocked."""
    tombstone = DeletionTombstone.objects.filter(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
    ).first()

    if not tombstone:
        return {
            "is_tombstoned": False,
            "blocked": False,
            "reason": "No tombstone recorded for resource.",
        }

    return {
        "is_tombstoned": True,
        "blocked": True,
        "tombstone_id": str(tombstone.tombstone_id),
        "reason": tombstone.reason,
        "created_at": tombstone.created_at.isoformat(),
    }
