"""Retrieval engine supporting Lexical, Dense, and Hybrid (RRF) modes with permission/tombstone filtering (TECH-022, TECH-024)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.rag.models import DocumentChunk, IndexVersion, SourceDocument, KnowledgeBase


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
    try:
        left, right = [float(v) for v in v1], [float(v) for v in v2]
    except (TypeError, ValueError):
        raise ValueError('Embedding coordinates must be finite numbers.') from None
    if not all(math.isfinite(v) for v in (*left, *right)):
        raise ValueError('Embedding coordinates must be finite numbers.')
    scale1, scale2 = max(map(abs,left)), max(map(abs,right))
    if not scale1 or not scale2:
        return 0.0
    left, right = [v/scale1 for v in left], [v/scale2 for v in right]
    dot = sum(a*b for a,b in zip(left,right))
    norm1, norm2 = math.sqrt(sum(v*v for v in left)), math.sqrt(sum(v*v for v in right))
    return max(-1.0,min(1.0,dot/(norm1*norm2)))



class RetrievalEngine:
    """Executes lexical, dense, and hybrid queries against authorized, non-tombstoned chunks."""

    def __init__(self, index_version: IndexVersion) -> None:
        self.index_version = index_version
        self.tenant_id = index_version.tenant_id
        self.execution = {}

    def eligible_queryset(self):
        """Keep current access, frozen membership and deletion checks in the ranking SQL."""
        from django.db.models import Exists, OuterRef, Q, CharField
        from django.db.models.functions import Cast, Replace
        from django.db.models import Value
        from django.db import connection
        from modelanvil.identity.models import ProjectGrant, _model_uuid_field_name
        from modelanvil.core.tenancy import get_active_tenant, get_active_project
        tenant, project = get_active_tenant(), get_active_project()
        if tenant is not None and str(tenant) != str(self.tenant_id):
            return DocumentChunk.all_objects.none()

        def accessible(model):
            rows = model.all_objects.filter(tenant_id=self.tenant_id)
            if project is None:
                return rows
            grants = ProjectGrant.all_objects.filter(tenant_id=self.tenant_id,
                project_id=OuterRef('project_id'), granted_to_project_id=project).filter(
                Q(resource_type='all') | Q(resource_type=model._meta.model_name, resource_id__isnull=True)
                | Q(resource_type=model._meta.model_name, resource_id=OuterRef(_model_uuid_field_name(model))))
            return rows.alias(has_grant=Exists(grants)).filter(
                Q(project_id=project) | Q(project_id__isnull=True) | Q(has_grant=True))

        current = IndexVersion.all_objects.filter(pk=self.index_version.pk,tenant_id=self.tenant_id).first()
        if current is None:
            return DocumentChunk.all_objects.none()
        self.index_version = current
        indexes = accessible(IndexVersion).filter(pk=current.pk,status='ready')
        bases = accessible(KnowledgeBase)
        chunks = DocumentChunk.all_objects.filter(tenant_id=self.tenant_id,
            document__tenant_id=self.tenant_id,document__knowledge_base=current.knowledge_base_id,
            document__knowledge_base_id__in=bases.values('pk'),document__is_revoked=False,document__is_deleted=False
        ).filter(Exists(indexes))
        if current.configuration.get('embedding_profile'):
            from modelanvil.rag.models import EmbeddingSpace
            chunks = chunks.filter(Exists(accessible(EmbeddingSpace).filter(pk=current.embedding_space_id)))
        if 'chunk_ids' in current.configuration:
            chunks = chunks.filter(chunk_id__in=current.configuration['chunk_ids'])
        tombstones = DeletionTombstone.all_objects.filter(tenant_id=self.tenant_id)
        chunk_uuid, doc_uuid = Cast(OuterRef('chunk_id'),CharField()), Cast(OuterRef('document__doc_id'),CharField())
        if connection.vendor=='sqlite':
            # SQLite stores UUIDs without hyphens; PostgreSQL casts retain them.
            tombstones=tombstones.annotate(uuid_key=Replace('resource_id',Value('-'),Value('')))
            uuid_filter=Q(uuid_key=chunk_uuid) | Q(uuid_key=doc_uuid)
        else:
            uuid_filter=Q(resource_id=chunk_uuid) | Q(resource_id=doc_uuid)
        tombstones=tombstones.filter(uuid_filter | Q(resource_id=OuterRef('content_hash'))
            | Q(resource_id=OuterRef('document__content_hash')))
        return chunks.filter(~Exists(tombstones)).select_related('document').order_by('chunk_id')

    def get_eligible_chunks(self) -> list[DocumentChunk]:
        return list(self.eligible_queryset())

    def settings(self, top_k=10, dense_search=None, ef_search=None):
        from django.db import connection
        config = self.index_version.configuration.get('retrieval_settings',{})
        strategy = dense_search or config.get('dense_search','hnsw')
        if strategy not in ('exact','hnsw'):
            raise ValueError('Dense search must be exact or hnsw.')
        ef=ef_search if ef_search is not None else config.get('hnsw',{}).get('ef_search',100)
        if type(ef) is not int or not 1<=ef<=1000:
            raise ValueError('HNSW ef_search must be an integer between 1 and 1000.')
        return {'backend':'postgresql' if connection.vendor=='postgresql' else 'sqlite_compatibility',
            'lexical':'postgresql-ts-rank-cd-simple-v1' if connection.vendor=='postgresql' else 'lexical-token-overlap-v1',
            'dense_search':strategy,'operator':'cosine','hnsw':{'m':16,'ef_construction':64,
                'ef_search':ef,'iterative_scan':'strict_order','max_scan_tuples':20000},
            'execution':dict(self.execution),'underfill_policy':'exact_fallback','rrf_k':60,'candidate_count':min(200,top_k*2),'candidate_count_per_channel':True}

    def retrieve_lexical(self, query: str, top_k: int = 10) -> list[ScoredChunk]:
        """PostgreSQL full-text ranking, with an explicit SQLite compatibility path."""
        from django.db import connection
        if connection.vendor == 'postgresql':
            from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
            vector = SearchVector('text',config='simple')
            parsed = SearchQuery(query,config='simple',search_type='websearch')
            rows = self.eligible_queryset().annotate(search=vector).filter(search=parsed).annotate(
                score=SearchRank(vector,parsed,cover_density=True)).order_by('-score','chunk_id')[:top_k]
            return [ScoredChunk(str(row.chunk_id),row,float(row.score),rank,'lexical') for rank,row in enumerate(rows,1)]
        # Compatibility only: SQLite has no PostgreSQL full-text implementation.
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

    def retrieve_dense(self, query_embedding: Sequence[float], top_k: int = 10, *, dense_search=None, ef_search=None, allow_exact_fallback=True) -> list[ScoredChunk]:
        """Dense vector search using embedding cosine similarity."""
        expected_dim = self.index_version.embedding_space.dimension
        if len(query_embedding) != expected_dim:
            raise ValueError(
                f"Query embedding dimension {len(query_embedding)} does not match index space dimension {expected_dim}."
            )

        if self.index_version.configuration.get('embeddings_generated'):
            from django.db import connection
            from django.db.models.functions import Cast
            from pgvector.django import VectorField, CosineDistance
            from modelanvil.rag.models import ChunkEmbedding
            from modelanvil.rag.embedding_adapter import validate_vectors, vector_digest
            eligible = self.eligible_queryset()
            vectors = ChunkEmbedding.all_objects.filter(tenant_id=self.tenant_id,
                space=self.index_version.embedding_space,
                chunk_id__in=eligible.values('pk'))
            if vectors.count() != eligible.count():
                raise ValueError('The ready index has missing vectors; rebuild it before querying.')
            if connection.vendor != 'postgresql':
                raise ValueError('Real vector search requires PostgreSQL with pgvector.')
            from django.db import transaction
            from django.db.models import F, Value
            settings = self.settings(top_k,dense_search,ef_search)
            distances = vectors.annotate(
                distance=CosineDistance(Cast('vector',VectorField(dimensions=expected_dim)),list(query_embedding)))
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
                extension=cursor.fetchone()
                if extension is None or tuple(int(v) for v in extension[0].split('.')[:2])<(0,8):
                    raise ValueError('SQL retrieval requires pgvector 0.8 or newer for filtered iterative scans.')
                names = ['hnsw.ef_search','hnsw.iterative_scan','hnsw.max_scan_tuples']
                values = [str(settings['hnsw']['ef_search']),'strict_order','20000']
                if settings['dense_search']=='hnsw':
                    # Explicit ANN mode prefers its ordered index over a filter-and-sort plan.
                    names.append('enable_sort');values.append('off')
                defaults={'hnsw.ef_search':'40','hnsw.iterative_scan':'off','hnsw.max_scan_tuples':'20000','enable_sort':'on'}
                previous = []
                for name,value in zip(names,values):
                    cursor.execute('SELECT current_setting(%s,true)',[name]);previous.append(cursor.fetchone()[0] or defaults[name])
                    cursor.execute('SELECT set_config(%s,%s,true)',[name,value])
                order = 'distance' if settings['dense_search']=='hnsw' else F('distance')+Value(0.0)
                self.execution={'exact_fallback_enabled':allow_exact_fallback,'exact_fallback_used':False,'pgvector_version':extension[0]}
                ranked = list(distances.order_by(order)[:top_k])
                if allow_exact_fallback and settings['dense_search']=='hnsw' and len(ranked)<min(top_k,eligible.count()):
                    self.execution['exact_fallback_used']=True
                    ranked = list(distances.order_by(F('distance')+Value(0.0),'chunk_id')[:top_k])
                # Exceptions roll the local settings back with this atomic block.
                for name,value in zip(names,previous):
                    cursor.execute('SELECT set_config(%s,%s,true)',[name,value])
            current_chunks={chunk.pk:chunk for chunk in eligible.filter(pk__in=[row.chunk_id for row in ranked])}
            result=[]
            for row in ranked:
                chunk=current_chunks.get(row.chunk_id)
                if chunk is None:continue
                validate_vectors([row.vector],1)
                if (row.content_hash!=chunk.content_hash or vector_digest(row.vector)!=row.vector_digest
                        or row.runtime_digest!=self.index_version.configuration['embedding_build_runtime']):
                    raise ValueError('Stored vector checksums changed; rebuild this index.')
                result.append(ScoredChunk(chunk_id=str(chunk.chunk_id),chunk=chunk,
                    score=1-float(row.distance),rank=len(result)+1,channel='dense'))
            return result

        from django.db import connection
        if connection.vendor=='postgresql':
            raise ValueError('Legacy JSON vectors are not a PostgreSQL semantic index; build a native embedding index.')
        scored = []
        for c in self.get_eligible_chunks():
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
        *, dense_search=None, ef_search=None,
    ) -> list[ScoredChunk]:
        """Hybrid search combining lexical and dense lists via Reciprocal Rank Fusion (RRF).

        RRF formula: score(d) = sum(1 / (rrf_constant + rank_i(d)))
        """
        lex_results = self.retrieve_lexical(query, top_k=top_k * 2)
        dense_results = self.retrieve_dense(query_embedding, top_k=top_k * 2,dense_search=dense_search,ef_search=ef_search)

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
