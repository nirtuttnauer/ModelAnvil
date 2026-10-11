"""Pure content-detection kernel for dataset preparation (WP-05).

No storage, authorization, or training. Every function is deterministic and
operates on already-validated canonical sample envelopes (see
``contracts/schemas/sample-envelope.schema.json``). Callers are responsible
for schema validation; these functions assume the envelope shape and sanitize
nothing — they flag.

Detectors emit stable, machine-readable flag codes:

- ``pii.*``       privacy signals found in block content
- ``quality.*``   degenerate-content signals
- ``duplicate.*`` handled by the preparation kernel, not here

Content model: for near-duplicate and privacy scanning, a block's *text
content* is its ``text`` (text/code blocks) or the canonical JSON of its
``value`` (json/table/tool_call/tool_result/custom blocks). Asset blocks
(image/audio/video/svg/document) contribute no text; their ``asset_ref`` is
part of the exact content digest only.
"""
from __future__ import annotations

import hashlib
import json
import re


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------
def _canonical_value(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        return ""


def block_content_text(block: dict) -> str:
    """Return the text content of a block, or "" for asset-only blocks."""
    btype = block.get("type")
    if btype in ("text", "code"):
        text = block.get("text")
        return text if isinstance(text, str) else ""
    if btype in ("json", "table", "tool_call", "tool_result"):
        return _canonical_value(block.get("value")) if block.get("value") is not None else ""
    if btype == "custom":
        value = block.get("value")
        if isinstance(value, str):
            return value
        if value is not None:
            return _canonical_value(value)
        text = block.get("text")
        return text if isinstance(text, str) else ""
    return ""


def sample_text(envelope: dict) -> str:
    """Concatenate block text content in block order, whitespace-separated."""
    parts = [block_content_text(block) for block in envelope.get("blocks", [])]
    return "\n".join(part for part in parts if part)


def content_digest(envelope: dict) -> str:
    """SHA-256 over the ordered, identity-free content of every block.

    Covers ``type``, ``role``, ``text``, ``value`` and ``asset_ref`` per
    block. ``block_id``, provenance and metadata are volatile identity, not
    content, and are excluded. Two envelopes with identical content (same
    block order and fields) always share a digest; block order is content.
    """
    blocks = []
    for block in envelope.get("blocks", []):
        blocks.append({
            "type": block.get("type"),
            "role": block.get("role"),
            "text": block.get("text"),
            "value": block.get("value"),
            "asset_ref": block.get("asset_ref"),
        })
    payload = json.dumps(blocks, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Privacy detectors
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
)
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CC_CANDIDATE_RE = re.compile(r"(?<!\d)\d(?:[\s-]?\d){12,18}(?!\d)")
_IP_RE = re.compile(r"(?<!\d)((?:\d{1,3}\.){3}\d{1,3})(?!\d)")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _is_public_ip(candidate: str) -> bool:
    return all(0 <= int(octet) <= 255 for octet in candidate.split("."))


def privacy_flags(text: str) -> list[str]:
    """Flag privacy signals in arbitrary text. Returns sorted, deduped codes."""
    flags = set()
    if not text:
        return []
    if _EMAIL_RE.search(text):
        flags.add("pii.email")
    if _PHONE_RE.search(text):
        flags.add("pii.phone")
    if _SSN_RE.search(text):
        flags.add("pii.ssn")
    if _IP_RE.search(text) and any(_is_public_ip(m.group(1)) for m in _IP_RE.finditer(text)):
        flags.add("pii.ip_address")
    for match in _CC_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[\s-]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            flags.add("pii.credit_card")
            break
    return sorted(flags)


# ---------------------------------------------------------------------------
# Quality detectors
# ---------------------------------------------------------------------------
def _is_repetitive(text: str) -> bool:
    """True when the text is a single repeated character or a short repeated unit."""
    stripped = text.strip()
    if len(stripped) < 8:
        return False
    if len(set(stripped)) == 1:
        return True
    for period in range(1, 9):
        if len(stripped) % period == 0:
            unit = stripped[:period]
            if unit * (len(stripped) // period) == stripped:
                return True
    return False


def quality_flags(envelope: dict, *, min_text_chars: int = 8) -> list[str]:
    """Flag degenerate samples. Returns sorted, deduped codes.

    - ``quality.empty``: no non-whitespace text content in any block.
    - ``quality.short``: text content below ``min_text_chars`` characters.
    - ``quality.repetitive``: a block whose content is a repeated character
      or a unit of at most 8 characters repeated three or more times.
    """
    if not isinstance(min_text_chars, int) or isinstance(min_text_chars, bool) or min_text_chars < 0:
        raise ValueError("min_text_chars must be a nonnegative integer.")
    flags = set()
    joined = " ".join(block_content_text(block) for block in envelope.get("blocks", []))
    stripped = joined.strip()
    if not stripped:
        flags.add("quality.empty")
    elif len(stripped) < min_text_chars:
        flags.add("quality.short")
    for block in envelope.get("blocks", []):
        text = block_content_text(block)
        if _is_repetitive(text):
            flags.add("quality.repetitive")
            break
    return sorted(flags)


# ---------------------------------------------------------------------------
# Near-duplicate fingerprints
# ---------------------------------------------------------------------------
def simhash(text: str, *, ngram: int = 3, bits: int = 64) -> int:
    """Deterministic simhash fingerprint over character n-grams.

    Whitespace is collapsed first so formatting differences do not change the
    fingerprint. Empty input fingerprints as 0. ``bits`` must be a multiple
    of 8 in [8, 128]; each gram is hashed with SHA-256 and the leading
    ``bits`` bits vote.
    """
    if not isinstance(ngram, int) or isinstance(ngram, bool) or ngram < 1:
        raise ValueError("ngram must be a positive integer.")
    if not isinstance(bits, int) or isinstance(bits, bool) or bits % 8 or not 8 <= bits <= 128:
        raise ValueError("bits must be a multiple of 8 between 8 and 128.")
    normalized = " ".join(text.split())
    if not normalized:
        return 0
    if len(normalized) < ngram:
        grams = [normalized]
    else:
        grams = [normalized[i:i + ngram] for i in range(len(normalized) - ngram + 1)]
    width = bits // 8
    votes = {}
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()[:width]
        gram_hash = int.from_bytes(digest, "big")
        for bit in range(bits):
            votes[bit] = votes.get(bit, 0) + (1 if (gram_hash >> bit) & 1 else -1)
    fingerprint = 0
    for bit, vote in votes.items():
        if vote > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two fixed-width fingerprints."""
    if a < 0 or b < 0:
        raise ValueError("Fingerprints must be nonnegative.")
    return (a ^ b).bit_count()


def build_protected_set(envelopes, *, ngram: int = 3, bits: int = 64) -> dict:
    """Build a protected-evaluation set from envelopes.

    Returns ``{"digests": [...], "simhashes": [...]}`` — exact content
    digests plus near-duplicate fingerprints, both for whole samples.
    """
    digests = []
    simhashes = []
    for envelope in envelopes:
        digests.append(content_digest(envelope))
        simhashes.append(simhash(sample_text(envelope), ngram=ngram, bits=bits))
    return {"digests": digests, "simhashes": simhashes}


def protected_overlap(envelope: dict, protected: dict, *, near_threshold: int = 3,
                      ngram: int = 3, bits: int = 64) -> list[str]:
    """Flag overlap with a protected set built by :func:`build_protected_set`.

    Returns ``["overlap.protected_exact"]`` when the content digest matches a
    protected sample (which subsumes near overlap), else
    ``["overlap.protected_near"]`` when the sample simhash is within
    ``near_threshold`` Hamming distance of a protected simhash, else ``[]``.
    """
    if not isinstance(near_threshold, int) or isinstance(near_threshold, bool) or near_threshold < 0:
        raise ValueError("near_threshold must be a nonnegative integer.")
    if content_digest(envelope) in protected.get("digests", []):
        # Exact overlap subsumes near overlap: one reason is enough.
        return ["overlap.protected_exact"]
    if near_threshold > 0 and protected.get("simhashes"):
        fingerprint = simhash(sample_text(envelope), ngram=ngram, bits=bits)
        if any(hamming_distance(fingerprint, protected_hash) <= near_threshold
               for protected_hash in protected["simhashes"]):
            return ["overlap.protected_near"]
    return []
