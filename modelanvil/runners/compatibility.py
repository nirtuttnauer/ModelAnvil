"""Model, tokenizer, and evaluation compatibility validation (WP-07 / TECH-015, TECH-020)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ValidationError

from modelanvil.data.detection import content_digest, hamming_distance, sample_text, simhash
from modelanvil.runners.models import ModelVersion, TokenizerVersion


@dataclass
class ContaminationReport:
    """Report of evaluation cases detected in training data."""

    contaminated_count: int = 0
    total_eval_cases: int = 0
    contaminated_cases: list[dict[str, Any]] = field(default_factory=list)
    is_contaminated: bool = False


def validate_model_tokenizer_compatibility(
    model_version: ModelVersion,
    tokenizer: TokenizerVersion,
) -> dict[str, Any]:
    """Validate model and tokenizer compatibility before compute allocation (TECH-015).

    Blocks allocation on:
    - Vocabulary size mismatch.
    - Missing special tokens required by the architecture.
    - Chat template drift or missing role variables.
    """
    errors: dict[str, str] = {}
    details: dict[str, Any] = {}

    # 1. Vocabulary size compatibility
    expected_vocab = (model_version.metadata or {}).get("vocab_size")
    if expected_vocab is not None and expected_vocab != tokenizer.vocabulary_size:
        errors["vocab_size"] = (
            f"Vocabulary size mismatch: model specifies {expected_vocab}, "
            f"but tokenizer provides {tokenizer.vocabulary_size}."
        )

    # 2. Required special tokens validation
    required_special_tokens = ["eos_token"]
    if "chat" in (model_version.model.intended_tasks or []):
        required_special_tokens.extend(["bos_token", "pad_token"])

    missing_tokens = [tok for tok in required_special_tokens if not tokenizer.special_tokens.get(tok)]
    if missing_tokens:
        errors["special_tokens"] = f"Missing required special tokens: {', '.join(missing_tokens)}."

    # 3. Chat template validation
    if "chat" in (model_version.model.intended_tasks or []):
        if not tokenizer.chat_template:
            errors["chat_template"] = "Chat model requires a defined chat_template on the tokenizer."
        else:
            template = tokenizer.chat_template
            # Check for Jinja / role syntax drift
            if "{% for message in messages %}" not in template and "{{ messages }}" not in template and "messages" not in template:
                errors["chat_template"] = "Chat template does not iterate over 'messages' variable."
            if "role" not in template or "content" not in template:
                errors["chat_template"] = "Chat template does not handle 'role' and 'content' fields."

    if errors:
        raise ValidationError(errors)

    details["status"] = "compatible"
    details["vocabulary_size"] = tokenizer.vocabulary_size
    details["special_tokens"] = tokenizer.special_tokens
    return details


def _extract_item_text(item: Any) -> str:
    """Extract full normalized text from a sample envelope or raw dictionary."""
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return str(item).strip()
    if "blocks" in item:
        text = sample_text(item)
        if text:
            return text.strip()
    # Check text / content / prompt fields
    t = item.get("text") or item.get("content") or ""
    if not t and ("input_prompt" in item or "input" in item):
        inp = item.get("input_prompt") or item.get("input") or ""
        out = item.get("expected_output") or ""
        t = f"{inp} {out}".strip()
    return str(t).strip()


def detect_eval_contamination(
    training_rows: list[dict[str, Any]],
    eval_cases: list[dict[str, Any]],
    *,
    near_threshold: int = 3,
) -> ContaminationReport:
    """Detect leakage / contamination of benchmark evaluation cases in training sets.

    Uses exact text match / SHA-256 and near-duplicate simhashes. Contaminated benchmark
    records block qualification (TECH-020).
    """
    train_text_hashes: set[str] = set()
    train_texts: list[str] = []
    train_texts: list[str] = []
    train_simhashes: list[int] = []

    for row in training_rows:
        text = _extract_item_text(row)
        if text:
            train_texts.append(text)
            train_text_hashes.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
            if len(text) >= 32:
                train_simhashes.append(simhash(text))

        if isinstance(row, dict) and "blocks" in row:
            train_text_hashes.add(content_digest(row))

    report = ContaminationReport(total_eval_cases=len(eval_cases))

    for case in eval_cases:
        case_id = str(case.get("case_id") or "")
        case_input = str(case.get("input_prompt") or case.get("input") or "")
        case_expected = str(case.get("expected_output") or "")
        full_text = f"{case_input} {case_expected}".strip()
        if not full_text:
            full_text = _extract_item_text(case)

        if not full_text:
            continue

        c_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

        # Check exact hash or exact containment
        if c_hash in train_text_hashes or any(full_text in t for t in train_texts) or any(full_text and full_text in t for t in train_texts):
            report.contaminated_count += 1
            report.contaminated_cases.append({
                "case_id": case_id,
                "reason": "exact_match",
                "preview": full_text[:100],
            })
            continue

        # Check near duplicate simhash only for sufficiently long strings (>= 32 chars)
        if len(full_text) >= 32 and train_simhashes:
            c_simhash = simhash(full_text)
            if any(hamming_distance(c_simhash, h) <= near_threshold for h in train_simhashes):
                report.contaminated_count += 1
                report.contaminated_cases.append({
                    "case_id": case_id,
                    "reason": "near_duplicate",
                    "preview": full_text[:100],
                })

    report.is_contaminated = (report.contaminated_count > 0)
    return report
