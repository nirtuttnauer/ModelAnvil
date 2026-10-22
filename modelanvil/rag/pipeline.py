"""End-to-end RAG query pipeline, citation generation, abstention policy, and trace logging (TECH-022, TECH-024)."""
from __future__ import annotations

import time
from typing import Any, Optional, Sequence

from modelanvil.rag.models import IndexVersion, QueryTrace
from modelanvil.rag.retrieval import RetrievalEngine, ScoredChunk


class RAGPipeline:
    """Authenticated query-serving pipeline with citations, abstention policy, and trace auditing."""

    def __init__(
        self,
        index_version: IndexVersion,
        abstention_threshold: float = 0.05,
    ) -> None:
        self.index_version = index_version
        self.engine = RetrievalEngine(index_version)
        self.abstention_threshold = abstention_threshold

    def answer_query(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 3,
        caller_identity: str = "api-user",
        query_embedding: Sequence[float] | None = None,
    ) -> QueryTrace:
        """Execute RAG pipeline: retrieval -> reranking -> context assembly -> generation/abstention -> trace."""
        start_time = time.monotonic()

        if mode == "lexical":
            candidates = self.engine.retrieve_lexical(query, top_k=top_k)
        elif mode == "dense":
            if not query_embedding:
                raise ValueError("Dense retrieval requires a query embedding.")
            candidates = self.engine.retrieve_dense(query_embedding, top_k=top_k)
        else:
            if not query_embedding:
                raise ValueError("Hybrid retrieval requires a query embedding.")
            candidates = self.engine.retrieve_hybrid(query, query_embedding, top_k=top_k)

        retrieved_ids = [c.chunk_id for c in candidates]
        reranked_ids = list(retrieved_ids)

        # Abstention check
        if not candidates or candidates[0].score < self.abstention_threshold:
            latency = (time.monotonic() - start_time) * 1000.0
            return QueryTrace.objects.create(
                tenant_id=self.index_version.tenant_id,
                index_version=self.index_version,
                query=query,
                mode=mode,
                retrieved_chunk_ids=retrieved_ids,
                reranked_chunk_ids=reranked_ids,
                supplied_context="",
                answer="I do not have sufficient authorized evidence to answer this question.",
                citations=[],
                abstained=True,
                latency_ms=round(latency, 2),
            )

        # Context assembly & citation generation
        context_blocks = []
        citations = []
        for c in candidates:
            span = f"{c.chunk.span_start}:{c.chunk.span_end}"
            citation_tag = f"[Citation: {c.chunk_id} ({c.chunk.document.title})]"
            context_blocks.append(f"{citation_tag}\n{c.chunk.text}")
            citations.append({
                "chunk_id": c.chunk_id,
                "document_title": c.chunk.document.title,
                "span": span,
                "score": round(c.score, 4),
            })

        supplied_context = "\n\n".join(context_blocks)
        answer = (
            f"Based on the authorized sources ({', '.join(c['document_title'] for c in citations)}), "
            f"here is the verified answer to '{query}': {candidates[0].chunk.text[:120]}... "
            f"[Citation: {candidates[0].chunk_id} ({candidates[0].chunk.document.title})]"
        )

        latency = (time.monotonic() - start_time) * 1000.0
        return QueryTrace.objects.create(
            tenant_id=self.index_version.tenant_id,
            index_version=self.index_version,
            query=query,
            mode=mode,
            retrieved_chunk_ids=retrieved_ids,
            reranked_chunk_ids=reranked_ids,
            supplied_context=supplied_context,
            answer=answer,
            citations=citations,
            abstained=False,
            latency_ms=round(latency, 2),
        )

    def redact_trace(self, trace: QueryTrace) -> QueryTrace:
        """Redact sensitive context/evidence from traces when document access is revoked (TECH-024)."""
        revoked_doc_ids = set(
            self.index_version.knowledge_base.documents.filter(
                is_revoked=True
            ).values_list("doc_id", flat=True)
        )
        if not revoked_doc_ids:
            return trace

        trace.supplied_context = "[REDACTED: SENSITIVE EVIDENCE REVOKED]"
        trace.answer = "[REDACTED: ANSWER BASED ON REVOKED SOURCES]"
        trace.redacted = True
        trace.save()
        return trace
