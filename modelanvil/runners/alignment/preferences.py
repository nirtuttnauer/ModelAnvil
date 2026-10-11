"""Preference pair construction, tie/abstention handling, and score distribution analysis (TECH-018)."""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class PreferencePair:
    prompt: str
    chosen: str
    rejected: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "chosen": self.chosen,
            "rejected": self.rejected,
            "metadata": self.metadata,
        }


@dataclass
class PreferenceDataset:
    pairs: list[PreferencePair]
    digest: str
    total_raw: int
    ties_count: int
    abstentions_count: int
    valid_pairs_count: int

    def __len__(self) -> int:
        return len(self.pairs)


def compute_pairs_digest(pairs: Sequence[PreferencePair]) -> str:
    hasher = hashlib.sha256()
    for p in pairs:
        payload = json.dumps(p.to_dict(), sort_keys=True)
        hasher.update(payload.encode("utf-8"))
    return hasher.hexdigest()


def build_preference_dataset_from_records(
    records: Sequence[Any],
    held_out_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[PreferenceDataset, PreferenceDataset]:
    """Parse raw annotation records or dictionaries into validated train and held-out preference datasets.

    Ties and abstentions are separated and recorded. Valid pairs must have distinct chosen/rejected responses.
    """
    valid_pairs: list[PreferencePair] = []
    ties_count = 0
    abstentions_count = 0
    total_raw = len(records)

    for item in records:
        if hasattr(item, "is_blind_preference"):
            # Django AnnotationRecord model instance
            choice = item.preference_choice
            task_content = item.task.content if item.task else {}
            prompt = task_content.get("prompt", "")
            cand_a = task_content.get("candidate_a", "")
            cand_b = task_content.get("candidate_b", "")
            meta = {
                "record_id": str(item.record_id),
                "reviewer_id": item.reviewer_id,
            }
        elif isinstance(item, dict):
            choice = item.get("preference_choice") or item.get("choice", "")
            prompt = item.get("prompt", "")
            cand_a = item.get("candidate_a", "")
            cand_b = item.get("candidate_b", "")
            meta = item.get("metadata", {})
        else:
            continue

        if choice in ("tie", "equality"):
            ties_count += 1
            continue
        if choice in ("abstain", "skipped", "uncertain", ""):
            abstentions_count += 1
            continue

        if choice == "candidate_a":
            chosen, rejected = cand_a, cand_b
        elif choice == "candidate_b":
            chosen, rejected = cand_b, cand_a
        elif "chosen" in item and "rejected" in item:
            chosen, rejected = item["chosen"], item["rejected"]
        else:
            abstentions_count += 1
            continue

        if not prompt or not chosen or not rejected or chosen == rejected:
            abstentions_count += 1
            continue

        valid_pairs.append(PreferencePair(prompt=prompt, chosen=chosen, rejected=rejected, metadata=meta))

    rng = random.Random(seed)
    shuffled = list(valid_pairs)
    rng.shuffle(shuffled)

    split_idx = int(len(shuffled) * (1.0 - held_out_ratio))
    train_pairs = shuffled[:split_idx]
    held_out_pairs = shuffled[split_idx:]

    train_ds = PreferenceDataset(
        pairs=train_pairs,
        digest=compute_pairs_digest(train_pairs),
        total_raw=total_raw,
        ties_count=ties_count,
        abstentions_count=abstentions_count,
        valid_pairs_count=len(train_pairs),
    )
    held_out_ds = PreferenceDataset(
        pairs=held_out_pairs,
        digest=compute_pairs_digest(held_out_pairs),
        total_raw=total_raw,
        ties_count=ties_count,
        abstentions_count=abstentions_count,
        valid_pairs_count=len(held_out_pairs),
    )

    return train_ds, held_out_ds


def score_distribution_summary(
    chosen_scores: Sequence[float], rejected_scores: Sequence[float]
) -> dict[str, Any]:
    """Compute Bradley-Terry or reward model score distribution statistics."""
    if not chosen_scores or not rejected_scores:
        return {
            "count": 0,
            "chosen_mean": 0.0,
            "rejected_mean": 0.0,
            "margin_mean": 0.0,
            "accuracy": 0.0,
        }

    n = len(chosen_scores)
    c_mean = sum(chosen_scores) / n
    r_mean = sum(rejected_scores) / n

    c_var = sum((s - c_mean) ** 2 for s in chosen_scores) / n
    r_var = sum((s - r_mean) ** 2 for s in rejected_scores) / n

    margins = [c - r for c, r in zip(chosen_scores, rejected_scores)]
    m_mean = sum(margins) / n
    m_var = sum((m - m_mean) ** 2 for m in margins) / n

    wins = sum(1 for m in margins if m > 0)
    acc = wins / n

    return {
        "count": n,
        "chosen_mean": round(c_mean, 4),
        "chosen_std": round(math.sqrt(c_var), 4),
        "chosen_min": round(min(chosen_scores), 4),
        "chosen_max": round(max(chosen_scores), 4),
        "rejected_mean": round(r_mean, 4),
        "rejected_std": round(math.sqrt(r_var), 4),
        "rejected_min": round(min(rejected_scores), 4),
        "rejected_max": round(max(rejected_scores), 4),
        "margin_mean": round(m_mean, 4),
        "margin_std": round(math.sqrt(m_var), 4),
        "accuracy": round(acc, 4),
    }
