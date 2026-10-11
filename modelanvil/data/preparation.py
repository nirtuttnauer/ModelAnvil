"""Pure sample-envelope preparation; no storage, authorization or training.

The kernel validates canonical sample envelopes, optionally runs privacy and
quality detectors, removes exact/near duplicates, enforces protected-evaluation
overlap, and emits a group-aware split manifest. It is a bounded kernel:
``max_rows`` caps input consumption, and near-duplicate comparison is
linear in the number of kept rows. A blocking/streaming index for corpus-scale
execution is a separate pipeline (WP-05 streaming increment).

New options (``detect``, ``dedup``, ``protected``) default to off and preserve
the historical result shape exactly; when any is enabled the result gains
``dropped`` (per-sample reasons) and ``report`` (aggregate counts), and the
recipe (and therefore its digest) records the enabled settings. Protected
content is never embedded in the recipe — only counts.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any, Generator

from contracts.validate import validate_envelope

from modelanvil.data.detection import (
    build_protected_set,
    content_digest,
    hamming_distance,
    privacy_flags,
    protected_overlap,
    quality_flags,
    sample_text,
    simhash,
)


def _check_json(value):
    """Reject Python-only values rather than silently coercing them to JSON."""
    if type(value) in (str, int, bool, type(None)):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Nonfinite JSON number.")
        return
    if type(value) is list:
        for item in value:
            _check_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings.")
            _check_json(item)
        return
    raise ValueError("Non-JSON value.")


def _normalize_detect(detect):
    """Normalize the ``detect`` option to ``(privacy, quality, min_text_chars)``."""
    if detect is None:
        return False, False, 8
    if detect is True:
        return True, True, 8
    if detect is False:
        return False, False, 8
    if not isinstance(detect, dict):
        raise ValueError("detect must be true, false, or an options object.")
    privacy = detect.get("privacy", True)
    quality = detect.get("quality", True)
    min_text_chars = detect.get("min_text_chars", 8)
    if not isinstance(privacy, bool) or not isinstance(quality, bool):
        raise ValueError("detect privacy/quality must be booleans.")
    if not isinstance(min_text_chars, int) or isinstance(min_text_chars, bool) or min_text_chars < 0:
        raise ValueError("detect.min_text_chars must be a nonnegative integer.")
    return privacy, quality, min_text_chars


def _normalize_dedup(dedup):
    """Normalize the ``dedup`` option to ``(exact, near)``."""
    if dedup is None:
        return False, False
    if dedup is True:
        return True, True
    if dedup is False:
        return False, False
    if not isinstance(dedup, dict):
        raise ValueError("dedup must be true, false, or an options object.")
    exact = dedup.get("exact", True)
    near = dedup.get("near", True)
    if not isinstance(exact, bool) or not isinstance(near, bool):
        raise ValueError("dedup exact/near must be booleans.")
    return exact, near


def _normalize_protected(protected):
    """Normalize ``protected`` to a protected set, or None when disabled."""
    if protected is None:
        return None
    if isinstance(protected, dict):
        digests = protected.get("digests", [])
        simhashes = protected.get("simhashes", [])
        if not isinstance(digests, list) or not isinstance(simhashes, list):
            raise ValueError("protected must be an object with digest and simhash lists.")
        if any(not isinstance(d, str) or len(d) != 64 for d in digests):
            raise ValueError("protected digests must be 64-character hex strings.")
        if any(not isinstance(h, int) or isinstance(h, bool) or h < 0 for h in simhashes):
            raise ValueError("protected simhashes must be nonnegative integers.")
        return {"digests": list(digests), "simhashes": list(simhashes)}
    try:
        return build_protected_set(protected)
    except Exception:
        raise ValueError("protected must be a protected set object or an iterable of envelopes.") from None


def prepare_envelopes(documents, *, split_seed="0", validation_percent=10,
                      test_percent=10, max_rows=10000,
                      detect=None, dedup=None, protected=None,
                      near_threshold=3, min_text_chars=None):
    """Validate envelopes and produce rows, a split manifest, and drop reports.

    Base behavior (unchanged): validate each envelope against the canonical
    schema, require canonical lowercase UUID sample IDs, reject duplicate
    sample IDs, and assign each source group to one split via a seeded
    SHA-256 bucket. ``max_rows`` bounds input consumption: the (max_rows+1)th
    item is consumed only to detect overflow and raises.

    Optional features (all default off, preserving the historical result):
    - ``detect``: True/False or {"privacy": bool, "quality": bool,
      "min_text_chars": int}. Flagged samples are dropped with their reasons.
    - ``dedup``: True/False or {"exact": bool, "near": bool}. Exact
      duplicates (same content digest) and near duplicates (simhash within
      ``near_threshold`` Hamming distance of a kept row) are dropped; the
      first occurrence in input order is kept.
    - ``protected``: a set from :func:`modelanvil.data.detection.
      build_protected_set` or an iterable of protected envelopes. Samples
      overlapping the protected evaluation set are dropped.

    Dropped samples never enter the split manifest and never serve as
    duplicate references. When any feature is enabled, the result adds
    ``dropped`` (sample_id + reasons) and ``report`` (counts), and the recipe
    records the enabled settings (protected content is never embedded).
    """
    if not isinstance(split_seed, str):
        raise ValueError("split_seed must be a string.")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
           for value in (validation_percent, test_percent)):
        raise ValueError("Split percentages must be nonnegative integers.")
    if validation_percent + test_percent >= 100:
        raise ValueError("Split percentages must sum to less than 100.")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows <= 0:
        raise ValueError("max_rows must be a positive integer.")
    if not isinstance(near_threshold, int) or isinstance(near_threshold, bool) or near_threshold < 0:
        raise ValueError("near_threshold must be a nonnegative integer.")
    detect_privacy, detect_quality, detect_min_chars = _normalize_detect(detect)
    if min_text_chars is not None:
        if not isinstance(min_text_chars, int) or isinstance(min_text_chars, bool) or min_text_chars < 0:
            raise ValueError("min_text_chars must be a nonnegative integer.")
        detect_min_chars = min_text_chars
    dedup_exact, dedup_near = _normalize_dedup(dedup)
    protected_set = _normalize_protected(protected)
    features_enabled = detect_privacy or detect_quality or dedup_exact or dedup_near or protected_set is not None

    recipe = {
        "algorithm": "source_group_sha256_v1",
        "seed": split_seed,
        "validation_percent": validation_percent,
        "test_percent": test_percent,
    }
    if detect is not None:
        recipe["detect"] = {"privacy": detect_privacy, "quality": detect_quality,
                            "min_text_chars": detect_min_chars}
    if dedup is not None:
        recipe["dedup"] = {"exact": dedup_exact, "near": dedup_near,
                           "near_threshold": near_threshold}
    if protected_set is not None:
        # Counts only: protected evaluation content must never enter the recipe.
        recipe["protected"] = {"exact_count": len(protected_set["digests"]),
                               "near_count": len(protected_set["simhashes"]),
                               "near_threshold": near_threshold}
    try:
        recipe_digest = hashlib.sha256(json.dumps(
            recipe, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")).hexdigest()
    except Exception:
        raise ValueError("Preparation recipe is not valid UTF-8 JSON.") from None

    rows = []
    dropped = []
    sample_ids = set()
    seen_digests = set()
    kept_fingerprints = []
    groups = {}
    manifest = {"train": [], "validation": [], "test": []}
    drop_reason_counts = {}
    consumed = 0
    try:
        iterator = iter(documents)
    except Exception:
        raise ValueError("Envelope input must be iterable.") from None
    while True:
        try:
            document = next(iterator)
        except StopIteration:
            break
        except Exception:
            raise ValueError("Envelope input iteration failed.") from None
        consumed += 1
        if consumed > max_rows:
            raise ValueError("Envelope row limit exceeded.")
        try:
            _check_json(document)
            serialized = json.dumps(document, ensure_ascii=False, allow_nan=False)
            serialized.encode("utf-8")
            row = json.loads(serialized)
            validate_envelope(row)
            sample_id = row["sample_id"]
            if str(uuid.UUID(sample_id)) != sample_id:
                raise ValueError("Noncanonical sample ID.")
        except Exception:
            # Schema details, source values and chained exceptions are private.
            raise ValueError("Envelope is invalid or is not finite JSON.") from None
        if sample_id in sample_ids:
            raise ValueError("Duplicate sample IDs are not allowed.")
        sample_ids.add(sample_id)

        reasons = []
        text = None
        if detect_privacy or detect_quality:
            text = sample_text(row)
            if detect_privacy:
                reasons.extend(privacy_flags(text))
            if detect_quality:
                reasons.extend(quality_flags(row, min_text_chars=detect_min_chars))
        if protected_set is not None:
            reasons.extend(protected_overlap(row, protected_set, near_threshold=near_threshold))
        digest = None
        fingerprint = None
        if dedup_exact or dedup_near:
            digest = content_digest(row)
            if dedup_exact and digest in seen_digests:
                reasons.append("duplicate.exact")
            if dedup_near and not reasons:
                if text is None:
                    text = sample_text(row)
                fingerprint = simhash(text)
                if any(hamming_distance(fingerprint, kept) <= near_threshold
                       for kept in kept_fingerprints):
                    reasons.append("duplicate.near")
        if reasons:
            unique_reasons = sorted(set(reasons))
            dropped.append({"sample_id": sample_id, "reasons": unique_reasons})
            for reason in unique_reasons:
                drop_reason_counts[reason] = drop_reason_counts.get(reason, 0) + 1
            continue

        group = row["source_group_id"]
        if group not in groups:
            payload = json.dumps([split_seed, group], ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
            bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 100
            groups[group] = ("test" if bucket < test_percent else
                             "validation" if bucket < test_percent + validation_percent
                             else "train")
        manifest[groups[group]].append(row["sample_id"])
        rows.append(row)
        if dedup_exact:
            seen_digests.add(digest)
        if dedup_near:
            if fingerprint is None:
                fingerprint = simhash(sample_text(row))
            kept_fingerprints.append(fingerprint)
    if not rows and not dropped:
        raise ValueError("At least one envelope is required.")

    result = {
        "schema_version": "1.0", "recipe": recipe, "recipe_digest": recipe_digest,
        "rows": rows, "split_manifest": manifest, "row_count": len(rows),
        "source_group_count": len(groups),
    }
    if features_enabled:
        result["dropped"] = dropped
        result["report"] = {
            "input_rows": consumed,
            "kept": len(rows),
            "dropped": len(dropped),
            "drop_reason_counts": drop_reason_counts,
        }
    return result


def stream_prepare_envelopes(
    documents,
    *,
    split_seed: str = "0",
    validation_percent: int = 10,
    test_percent: int = 10,
    max_rows: int = 100000,
    detect: Any = None,
    dedup: Any = None,
    protected: Any = None,
    near_threshold: int = 3,
    min_text_chars: Optional[int] = None,
) -> Generator[tuple[str, Any, Any], None, None]:
    """Streaming sample-envelope preparation.

    Yields items one by one without accumulating the entire dataset in memory:
    - ("kept", row, split_name)
    - ("dropped", sample_id, reasons)
    """
    detect_privacy, detect_quality, detect_min_chars = _normalize_detect(detect)
    if min_text_chars is not None:
        detect_min_chars = min_text_chars
    dedup_exact, dedup_near = _normalize_dedup(dedup)
    protected_set = _normalize_protected(protected)

    sample_ids: set[str] = set()
    seen_digests: set[str] = set()
    kept_fingerprints: list[int] = []
    groups: dict[str, str] = {}
    consumed = 0

    for document in documents:
        consumed += 1
        if consumed > max_rows:
            raise ValueError("Envelope row limit exceeded.")

        _check_json(document)
        serialized = json.dumps(document, ensure_ascii=False, allow_nan=False)
        row = json.loads(serialized)
        validate_envelope(row)
        sample_id = row["sample_id"]
        if str(uuid.UUID(sample_id)) != sample_id:
            raise ValueError("Noncanonical sample ID.")
        if sample_id in sample_ids:
            raise ValueError("Duplicate sample IDs are not allowed.")
        sample_ids.add(sample_id)

        reasons = []
        text = None
        if detect_privacy or detect_quality:
            text = sample_text(row)
            if detect_privacy:
                reasons.extend(privacy_flags(text))
            if detect_quality:
                reasons.extend(quality_flags(row, min_text_chars=detect_min_chars))
        if protected_set is not None:
            reasons.extend(protected_overlap(row, protected_set, near_threshold=near_threshold))
        digest = None
        fingerprint = None
        if dedup_exact or dedup_near:
            digest = content_digest(row)
            if dedup_exact and digest in seen_digests:
                reasons.append("duplicate.exact")
            if dedup_near and not reasons:
                if text is None:
                    text = sample_text(row)
                fingerprint = simhash(text)
                if any(hamming_distance(fingerprint, kept) <= near_threshold for kept in kept_fingerprints):
                    reasons.append("duplicate.near")

        if reasons:
            unique_reasons = sorted(set(reasons))
            yield ("dropped", sample_id, unique_reasons)
            continue

        group = row["source_group_id"]
        if group not in groups:
            payload = json.dumps([split_seed, group], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 100
            groups[group] = (
                "test" if bucket < test_percent else "validation" if bucket < test_percent + validation_percent else "train"
            )

        split_name = groups[group]
        if dedup_exact:
            seen_digests.add(digest)
        if dedup_near:
            if fingerprint is None:
                fingerprint = simhash(sample_text(row))
            kept_fingerprints.append(fingerprint)

        yield ("kept", row, split_name)
