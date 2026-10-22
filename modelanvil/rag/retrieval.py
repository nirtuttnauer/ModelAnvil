"""Retrieval engine supporting Lexical, Dense, and Hybrid (RRF) modes with permission/tombstone filtering (TECH-022, TECH-024)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.rag.models import DocumentChunk, IndexVersion, SourceDocument


@dataclass
class ScoredChunk:
    chunk_id: str
    chunk: DocumentChunk
    score: float
    rank: int = 0
    channel: str = "hybrid"


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Cosine similarity between two numerical vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


class RetrievalEngine:
    """Executes lexical, dense, and hybrid queries against authorized, non-tombstoned chunks."""

    def __init__(self, index_version: IndexVersion) -> None:
        self.index_version = index_version
        self.tenant_id = index_version.tenant_id

    def get_eligible_chunks(self) -> list[DocumentChunk]:
        """Fetch all eligible chunks, enforcing tenant scope, access revocations, and tombstones (TECH-024)."""
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_tenant
        tenant = get_active_tenant()
        current = IndexVersion.all_objects.select_related('knowledge_base').filter(
            pk=self.index_version.pk, tenant_id=self.tenant_id, status='ready').first()
        if ((tenant is not None and str(tenant) != str(self.tenant_id))
                or current is None
                or not check_resource_access(current.knowledge_base, tenant_id=self.tenant_id)):
            return []
        self.index_version = current
        chunks = DocumentChunk.objects.filter(
            tenant_id=self.tenant_id,
            document__knowledge_base=self.index_version.knowledge_base,
            document__is_revoked=False,
            document__is_deleted=False,
        ).select_related("document").order_by("chunk_id")
        if "chunk_ids" in self.index_version.configuration:
            chunks = chunks.filter(chunk_id__in=self.index_version.configuration["chunk_ids"])

        # Tombstone check using resource_id (chunk_id, doc_id, or content hash)
        tombstone_ids = set(
            DeletionTombstone.objects.filter(tenant_id=self.tenant_id).values_list("resource_id", flat=True)
        )

        eligible = []
        for c in chunks:
            if (
                str(c.chunk_id) in tombstone_ids
                or str(c.document.doc_id) in tombstone_ids
                or c.content_hash in tombstone_ids
                or c.document.content_hash in tombstone_ids
            ):
                continue
            eligible.append(c)
        return eligible

    def retrieve_lexical(self, query: str, top_k: int = 10) -> list[ScoredChunk]:
        """Lexical token-overlap search (BM25 surrogate)."""
        chunks = self.get_eligible_chunks()
        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return []

        scored = []
        for c in chunks:
            text_tokens = re.findall(r"\w+", c.text.lower())
            if not text_tokens:
                continue
            token_count = len(text_tokens)
            matches = sum(1 for t in text_tokens if t in query_tokens)
            if matches > 0:
                # Term frequency weighted score
                score = matches / (token_count ** 0.5)
                scored.append(ScoredChunk(chunk_id=str(c.chunk_id), chunk=c, score=score, channel="lexical"))

        scored.sort(key=lambda x: x.score, reverse=True)
        results = scored[:top_k]
        for rank, item in enumerate(results, start=1):
            item.rank = rank
        return results

    def retrieve_dense(self, query_embedding: Sequence[float], top_k: int = 10) -> list[ScoredChunk]:
        """Dense vector search using embedding cosine similarity."""
        chunks = self.get_eligible_chunks()
        expected_dim = self.index_version.embedding_space.dimension
        if len(query_embedding) != expected_dim:
            raise ValueError(
                f"Query embedding dimension {len(query_embedding)} does not match index space dimension {expected_dim}."
            )

        scored = []
        for c in chunks:
            if not c.embedding or len(c.embedding) != expected_dim:
                continue
            sim = cosine_similarity(query_embedding, c.embedding)
            scored.append(ScoredChunk(chunk_id=str(c.chunk_id), chunk=c, score=sim, channel="dense"))

        scored.sort(key=lambda x: x.score, reverse=True)
        results = scored[:top_k]
        for rank, item in enumerate(results, start=1):
            item.rank = rank
        return results

    def retrieve_hybrid(
        self,
        query: str,
        query_embedding: Sequence[float],
        top_k: int = 10,
        rrf_constant: int = 60,
    ) -> list[ScoredChunk]:
        """Hybrid search combining lexical and dense lists via Reciprocal Rank Fusion (RRF).

        RRF formula: score(d) = sum(1 / (rrf_constant + rank_i(d)))
        """
        lex_results = self.retrieve_lexical(query, top_k=top_k * 2)
        dense_results = self.retrieve_dense(query_embedding, top_k=top_k * 2)

        fused_scores: dict[str, float] = {}
        chunk_map: dict[str, DocumentChunk] = {}

        for item in lex_results:
            cid = item.chunk_id
            chunk_map[cid] = item.chunk
            fused_scores[cid] = fused_scores.get(cid, 0.0) + (1.0 / (rrf_constant + item.rank))

        for item in dense_results:
            cid = item.chunk_id
            chunk_map[cid] = item.chunk
            fused_scores[cid] = fused_scores.get(cid, 0.0) + (1.0 / (rrf_constant + item.rank))

        fused = [
            ScoredChunk(chunk_id=cid, chunk=chunk_map[cid], score=score, channel="hybrid")
            for cid, score in fused_scores.items()
        ]
        fused.sort(key=lambda x: x.score, reverse=True)
        results = fused[:top_k]
        for rank, item in enumerate(results, start=1):
            item.rank = rank
        return results

    def rerank(
        self,
        candidates: Sequence[ScoredChunk],
        query: str,
        rerank_fn: Callable[[str, str], float],
        top_k: int = 5,
    ) -> list[ScoredChunk]:
        """Apply a cross-encoder or neural reranker to candidates."""
        reranked = []
        for c in candidates:
            cross_score = rerank_fn(query, c.chunk.text)
            reranked.append(
                ScoredChunk(chunk_id=c.chunk_id, chunk=c.chunk, score=cross_score, channel="reranked")
            )
        reranked.sort(key=lambda x: x.score, reverse=True)
        results = reranked[:top_k]
        for rank, item in enumerate(results, start=1):
            item.rank = rank
        return results
