"""Dataset revision comparison and export manifests (WP-05)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from modelanvil.artifacts.models import DatasetRevision


@dataclass
class RevisionComparison:
    """Differences between two dataset revisions."""

    base_revision_no: int
    target_revision_no: int
    row_count_base: Optional[int]
    row_count_target: Optional[int]
    row_count_delta: Optional[int]
    manifest_digest_changed: bool
    recipe_digest_changed: bool
    recipe_diff: dict[str, Any] = field(default_factory=dict)
    snapshots_added: list[str] = field(default_factory=list)
    snapshots_removed: list[str] = field(default_factory=list)
    drop_report_diff: dict[str, int] = field(default_factory=dict)


def compare_revisions(base: DatasetRevision, target: DatasetRevision) -> RevisionComparison:
    """Compute structured delta between base and target revisions."""
    base_rows = base.row_count
    target_rows = target.row_count
    row_delta = (target_rows - base_rows) if (base_rows is not None and target_rows is not None) else None

    # Source snapshots diff
    base_snaps = set(base.source_snapshots or [])
    target_snaps = set(target.source_snapshots or [])
    added_snaps = sorted(list(target_snaps - base_snaps))
    removed_snaps = sorted(list(base_snaps - target_snaps))

    # Drop reports diff
    base_drop_counts = (base.metadata or {}).get("drop_report", {}).get("drop_reason_counts", {})
    target_drop_counts = (target.metadata or {}).get("drop_report", {}).get("drop_reason_counts", {})
    all_reasons = set(base_drop_counts.keys()) | set(target_drop_counts.keys())
    drop_diff = {
        reason: target_drop_counts.get(reason, 0) - base_drop_counts.get(reason, 0)
        for reason in sorted(all_reasons)
    }

    # Recipe diff
    recipe_diff: dict[str, Any] = {}
    base_meta_recipe = (base.metadata or {}).get("recipe", {})
    target_meta_recipe = (target.metadata or {}).get("recipe", {})
    for key in set(base_meta_recipe.keys()) | set(target_meta_recipe.keys()):
        b_val = base_meta_recipe.get(key)
        t_val = target_meta_recipe.get(key)
        if b_val != t_val:
            recipe_diff[key] = {"base": b_val, "target": t_val}

    return RevisionComparison(
        base_revision_no=base.revision_no,
        target_revision_no=target.revision_no,
        row_count_base=base_rows,
        row_count_target=target_rows,
        row_count_delta=row_delta,
        manifest_digest_changed=(base.manifest_digest != target.manifest_digest),
        recipe_digest_changed=(base.recipe_digest != target.recipe_digest),
        recipe_diff=recipe_diff,
        snapshots_added=added_snaps,
        snapshots_removed=removed_snaps,
        drop_report_diff=drop_diff,
    )


def export_revision_manifest(revision: DatasetRevision) -> dict[str, Any]:
    """Generate an immutable export manifest for offline or downstream serving."""
    metadata = dict(revision.metadata or {})
    export_doc = {
        "export_format": "modelanvil_dataset_manifest_v1",
        "dataset_name": revision.dataset.name,
        "revision_no": revision.revision_no,
        "revision_id": str(revision.revision_id),
        "schema_version": revision.schema_version,
        "manifest_digest": revision.manifest_digest,
        "recipe_digest": revision.recipe_digest,
        "row_count": revision.row_count,
        "source_snapshots": revision.source_snapshots,
        "published_at": revision.published_at.isoformat() if revision.published_at else None,
        "metadata": metadata,
    }
    manifest_bytes = json.dumps(export_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    export_doc["export_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    return export_doc
