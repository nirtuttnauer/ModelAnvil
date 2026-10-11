"""Curated SVG starter preset preparation, rendering isolation, deduplication, and split grouping (WP-06 / TECH-010)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from django.core.exceptions import ValidationError

from modelanvil.data.isolation import sanitize_svg_for_rendering


@dataclass
class SVGIconItem:
    """An individual SVG icon record with source XML, renderable pair, and provenance."""

    source_library: str  # e.g. "lucide", "feather", "tabler"
    icon_name: str       # e.g. "arrow-right", "arrow-right-circle"
    svg_raw: str
    svg_clean: str
    concept_group: str   # normalized concept root, e.g. "arrow-right"
    variant_type: str    # e.g. "outline", "filled", "bold"
    label: str           # e.g. "arrow right"
    label_provenance: str  # "filename_derived" vs "reviewed_caption"
    license: str
    attribution_notice: str
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.svg_clean.encode("utf-8")).hexdigest()


@dataclass
class PreparedSVGDataset:
    """Prepared SVG dataset with variant-grouped splits and attribution manifests."""

    items: list[SVGIconItem]
    splits: dict[str, list[SVGIconItem]]  # "train", "val", "test"
    attribution_manifest: dict[str, Any]
    lineage_manifest: dict[str, Any]
    deduplication_summary: dict[str, Any]


# Canonical attribution notices for curated libraries (BANK04)
ATTRIBUTION_NOTICES: dict[str, dict[str, str]] = {
    "lucide": {
        "spdx": "ISC AND MIT",
        "notice": "Lucide icons licensed under ISC. Includes Feather icons derived under MIT License.",
    },
    "feather": {
        "spdx": "MIT",
        "notice": "Feather Icons (c) Cole Bemis, licensed under the MIT License.",
    },
    "tabler": {
        "spdx": "MIT",
        "notice": "Tabler Icons (c) Paweł Kuna, licensed under the MIT License.",
    },
    "heroicons": {
        "spdx": "MIT",
        "notice": "Heroicons (c) Tailwind Labs, Inc., licensed under the MIT License.",
    },
    "bootstrap": {
        "spdx": "MIT",
        "notice": "Bootstrap Icons (c) The Bootstrap Authors, licensed under the MIT License.",
    },
    "phosphor": {
        "spdx": "MIT",
        "notice": "Phosphor Icons (c) Phosphor Icons, licensed under the MIT License.",
    },
    "material": {
        "spdx": "Apache-2.0",
        "notice": "Material Design Icons (c) Google LLC, licensed under the Apache License 2.0.",
    },
}


def normalize_icon_concept(name: str) -> tuple[str, str]:
    """Extract root concept and variant style from icon filename/slug.

    Examples:
    - 'arrow-right-bold' -> ('arrow-right', 'bold')
    - 'arrow-right-outline' -> ('arrow-right', 'outline')
    - 'arrow-right-filled' -> ('arrow-right', 'filled')
    - 'circle-24' -> ('circle', 'size_24')
    """
    clean_name = name.lower().strip()
    variant = "regular"

    # Known variant suffixes
    for suffix in ("-bold", "-filled", "-outline", "-duotone", "-light", "-thin", "-round", "-sharp"):
        if clean_name.endswith(suffix):
            clean_name = clean_name[: -len(suffix)]
            variant = suffix.lstrip("-")
            break

    # Numeric size suffixes (e.g. -16, -20, -24)
    size_match = re.search(r"-(\d{2})$", clean_name)
    if size_match:
        variant = f"size_{size_match.group(1)}"
        clean_name = clean_name[: -len(size_match.group(0))]

    return clean_name, variant


def extract_weak_description(name: str) -> str:
    """Derive weak description from filename, ensuring it is not claimed as human-reviewed."""
    concept, variant = normalize_icon_concept(name)
    parts = concept.replace("-", " ").replace("_", " ").split()
    if variant != "regular":
        parts.append(variant)
    return " ".join(parts)


def prepare_svg_record(
    *,
    source_library: str,
    icon_name: str,
    svg_content: str,
    custom_label: Optional[str] = None,
) -> SVGIconItem:
    """Validate, sanitize, and construct a prepared SVG record with isolated render pairs."""
    lib_key = source_library.lower()
    attr_info = ATTRIBUTION_NOTICES.get(lib_key, {
        "spdx": "MIT",
        "notice": f"{source_library} icons under open license.",
    })

    # Validate XML and sanitize for render isolation (strips scripts, XXE, external links)
    clean_svg = sanitize_svg_for_rendering(svg_content)

    concept, variant = normalize_icon_concept(icon_name)
    if custom_label:
        label = custom_label
        provenance = "reviewed_caption"
    else:
        label = extract_weak_description(icon_name)
        provenance = "filename_derived"

    return SVGIconItem(
        source_library=source_library,
        icon_name=icon_name,
        svg_raw=svg_content,
        svg_clean=clean_svg,
        concept_group=concept,
        variant_type=variant,
        label=label,
        label_provenance=provenance,
        license=attr_info["spdx"],
        attribution_notice=attr_info["notice"],
    )


def prepare_svg_starter_dataset(
    records: list[dict[str, Any]],
    *,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    deduplicate_cross_source: bool = True,
) -> PreparedSVGDataset:
    """Prepare curated SVG starter preset with variant-group splits and cross-library deduplication.

    Guarantees:
    - Raw SVG XML is preserved alongside isolated clean SVG.
    - Icons with identical normalized concept (e.g. Feather & Lucide 'check' or variants of 'arrow-right')
      stay together in the exact same split, preventing leakage.
    - Retains attribution manifests across all participating libraries.
    """
    prepared_items: list[SVGIconItem] = []
    seen_content_hashes: dict[str, str] = {}
    dedup_dropped: int = 0
    cross_library_pairs: list[dict[str, str]] = []

    for rec in records:
        item = prepare_svg_record(
            source_library=rec["source_library"],
            icon_name=rec["icon_name"],
            svg_content=rec["svg_content"],
            custom_label=rec.get("custom_label"),
        )

        if deduplicate_cross_source:
            # Check exact duplicate content
            if item.content_hash in seen_content_hashes:
                prior_lib = seen_content_hashes[item.content_hash]
                dedup_dropped += 1
                cross_library_pairs.append({
                    "kept_library": prior_lib,
                    "dropped_library": item.source_library,
                    "icon_name": item.icon_name,
                    "hash": item.content_hash,
                })
                continue
            seen_content_hashes[item.content_hash] = item.source_library

        prepared_items.append(item)

    # Group items by concept_group so variants stay in the same split (BANK05)
    concept_groups: dict[str, list[SVGIconItem]] = {}
    for item in prepared_items:
        concept_groups.setdefault(item.concept_group, []).append(item)

    # Deterministic split allocation by sorting concept groups
    sorted_concepts = sorted(concept_groups.keys())
    total_concepts = len(sorted_concepts)

    train_cutoff = int(total_concepts * train_ratio)
    val_cutoff = int(total_concepts * (train_ratio + val_ratio))

    splits: dict[str, list[SVGIconItem]] = {"train": [], "val": [], "test": []}

    for idx, concept in enumerate(sorted_concepts):
        group_items = concept_groups[concept]
        if idx < train_cutoff:
            splits["train"].extend(group_items)
        elif idx < val_cutoff:
            splits["val"].extend(group_items)
        else:
            splits["test"].extend(group_items)

    # Attribution manifest (BANK04)
    libraries_present = sorted({item.source_library.lower() for item in prepared_items})
    attributions = [
        ATTRIBUTION_NOTICES.get(lib, {"spdx": "Open", "notice": f"{lib} icons"})
        for lib in libraries_present
    ]

    attribution_manifest = {
        "dataset_name": "svg-starter-permissive",
        "libraries": libraries_present,
        "notices": attributions,
        "policy": "Preserve all original copyright notices and license texts upon export or model release.",
    }

    lineage_manifest = {
        "total_records_processed": len(records),
        "total_items_prepared": len(prepared_items),
        "distinct_concepts": len(concept_groups),
        "split_counts": {k: len(v) for k, v in splits.items()},
    }

    deduplication_summary = {
        "deduplicated_count": dedup_dropped,
        "cross_library_overlaps": cross_library_pairs,
    }

    return PreparedSVGDataset(
        items=prepared_items,
        splits=splits,
        attribution_manifest=attribution_manifest,
        lineage_manifest=lineage_manifest,
        deduplication_summary=deduplication_summary,
    )
