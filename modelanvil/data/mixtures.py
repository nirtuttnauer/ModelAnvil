"""Dataset mixtures with weighted sampling and deterministic lineage (WP-05)."""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MixtureComponent:
    """One dataset revision component in a mixture."""

    revision_id: str
    weight: float
    rows: list[dict[str, Any]]
    max_samples: Optional[int] = None


@dataclass
class MixtureResult:
    """Deterministic output of a multi-source mixture."""

    mixture_id: str
    rows: list[dict[str, Any]]
    row_count: int
    component_weights: dict[str, float]
    component_sample_counts: dict[str, int]
    recipe: dict[str, Any]
    recipe_digest: str
    split_manifest: dict[str, list[str]]


def build_mixture(
    components: list[MixtureComponent],
    *,
    total_samples: Optional[int] = None,
    seed: str = "0",
    validation_percent: int = 10,
    test_percent: int = 10,
) -> MixtureResult:
    """Deterministically combine multiple dataset components according to weights.

    Preserves source lineage, computes recipe digest, and partitions
    into train/validation/test splits by source group.
    """
    if not components:
        raise ValueError("At least one mixture component is required.")

    if any(c.weight <= 0 for c in components):
        raise ValueError("Mixture component weights must be strictly positive.")

    if validation_percent + test_percent >= 100:
        raise ValueError("Split percentages must sum to less than 100.")

    total_weight = sum(c.weight for c in components)
    normalized_weights = {c.revision_id: c.weight / total_weight for c in components}

    # Determine sample count per component
    component_quotas: dict[str, int] = {}
    if total_samples is not None:
        if total_samples <= 0:
            raise ValueError("total_samples must be positive.")
        allocated = 0
        for i, c in enumerate(components):
            if i == len(components) - 1:
                quota = total_samples - allocated
            else:
                quota = int(round(total_samples * normalized_weights[c.revision_id]))
                allocated += quota
            if c.max_samples is not None:
                quota = min(quota, c.max_samples)
            quota = min(quota, len(c.rows))
            component_quotas[c.revision_id] = quota
    else:
        for c in components:
            quota = len(c.rows)
            if c.max_samples is not None:
                quota = min(quota, c.max_samples)
            component_quotas[c.revision_id] = quota

    # Seeded PRNG for deterministic sampling
    prng = random.Random(seed)

    selected_rows: list[dict[str, Any]] = []
    component_counts: dict[str, int] = {}

    for c in components:
        quota = component_quotas[c.revision_id]
        if quota >= len(c.rows):
            sampled = list(c.rows)
        else:
            # Deterministic reservoir/sample without replacement
            indices = sorted(prng.sample(range(len(c.rows)), quota))
            sampled = [c.rows[i] for i in indices]

        # Tag provenance with mixture revision
        for row in sampled:
            row_copy = dict(row)
            if "provenance" in row_copy and isinstance(row_copy["provenance"], dict):
                prov = dict(row_copy["provenance"])
                prov["mixture_source_revision"] = c.revision_id
                row_copy["provenance"] = prov
            selected_rows.append(row_copy)
        component_counts[c.revision_id] = len(sampled)

    # Deterministic interleave / shuffle using seed
    prng.shuffle(selected_rows)

    # Build group-based split manifest
    groups: dict[str, str] = {}
    manifest: dict[str, list[str]] = {"train": [], "validation": [], "test": []}

    for row in selected_rows:
        group = row.get("source_group_id", "default")
        if group not in groups:
            payload = json.dumps([seed, group], sort_keys=True).encode("utf-8")
            bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 100
            groups[group] = (
                "test"
                if bucket < test_percent
                else "validation"
                if bucket < test_percent + validation_percent
                else "train"
            )
        manifest[groups[group]].append(row["sample_id"])

    recipe = {
        "type": "dataset_mixture_v1",
        "seed": seed,
        "components": [
            {"revision_id": c.revision_id, "weight": c.weight, "quota": component_quotas[c.revision_id]}
            for c in components
        ],
        "validation_percent": validation_percent,
        "test_percent": test_percent,
        "total_samples": len(selected_rows),
    }

    recipe_digest = hashlib.sha256(
        json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    mixture_id = f"mix-{recipe_digest[:16]}"

    return MixtureResult(
        mixture_id=mixture_id,
        rows=selected_rows,
        row_count=len(selected_rows),
        component_weights=normalized_weights,
        component_sample_counts=component_counts,
        recipe=recipe,
        recipe_digest=recipe_digest,
        split_manifest=manifest,
    )
