"""Deterministic retrieval evaluation metrics: Recall@K, Precision@K, Hit@K, MRR@K, nDCG@K (TECH-023)."""
from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> Optional[float]:
    """Recall@K: fraction of relevant documents retrieved within the top K results.

    Returns None (N/A) if no relevant judgments exist for the query.
    """
    if not relevant_ids:
        return None
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return round(hits / len(relevant_ids), 4)


def precision_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> Optional[float]:
    """Precision@K: fraction of top K retrieved results that are relevant.

    Denominator is strictly K even if fewer results are returned.
    """
    if not relevant_ids:
        return None
    if k <= 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return round(hits / k, 4)


def hit_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> Optional[float]:
    """Hit@K: 1.0 if at least one relevant document is found in top K, else 0.0."""
    if not relevant_ids:
        return None
    if k <= 0:
        return 0.0
    top_k = retrieved_ids[:k]
    return 1.0 if any(doc_id in relevant_ids for doc_id in top_k) else 0.0


def mrr_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> Optional[float]:
    """MRR@K (Reciprocal Rank): 1 / rank of first relevant result in top K (1-indexed), or 0.0."""
    if not relevant_ids:
        return None
    if k <= 0:
        return 0.0
    top_k = retrieved_ids[:k]
    for rank, doc_id in enumerate(top_k, start=1):
        if doc_id in relevant_ids:
            return round(1.0 / rank, 4)
    return 0.0


def ndcg_at_k(
    retrieved_ids: Sequence[str],
    graded_relevance: Mapping[str, float],
    k: int,
) -> Optional[float]:
    """nDCG@K: Normalized Discounted Cumulative Gain at rank K.

    Uses standard formulation: DCG = sum((2^rel - 1) / log2(rank + 1)).
    Returns None (N/A) if no positive relevance grades are available.
    """
    if not graded_relevance or all(g <= 0 for g in graded_relevance.values()) or k <= 0:
        return None

    top_k = retrieved_ids[:k]

    # Compute DCG
    dcg = 0.0
    for rank, doc_id in enumerate(top_k, start=1):
        rel = graded_relevance.get(doc_id, 0.0)
        if rel > 0:
            dcg += (2.0 ** rel - 1.0) / math.log2(rank + 1.0)

    # Compute Ideal DCG (IDCG)
    sorted_grades = sorted(graded_relevance.values(), reverse=True)[:k]
    idcg = 0.0
    for rank, rel in enumerate(sorted_grades, start=1):
        if rel > 0:
            idcg += (2.0 ** rel - 1.0) / math.log2(rank + 1.0)

    if idcg <= 0.0:
        return None

    return round(dcg / idcg, 4)


def compute_all_retrieval_metrics(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    graded_relevance: Mapping[str, float],
    k: int,
) -> dict[str, Optional[float]]:
    """Compute standard IR metric suite at cutoff K."""
    return {
        f"recall@{k}": recall_at_k(retrieved_ids, relevant_ids, k),
        f"precision@{k}": precision_at_k(retrieved_ids, relevant_ids, k),
        f"hit@{k}": hit_at_k(retrieved_ids, relevant_ids, k),
        f"mrr@{k}": mrr_at_k(retrieved_ids, relevant_ids, k),
        f"ndcg@{k}": ndcg_at_k(retrieved_ids, graded_relevance, k),
    }
