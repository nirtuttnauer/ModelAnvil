"""Measured retrieval traces and versioned, permission-checked qrels comparisons."""
import hashlib
import json
import math
import time
from django.db import transaction
from modelanvil.rag.metrics import compute_all_retrieval_metrics
from modelanvil.rag.models import QueryTrace, RetrievalMetric, RetrievalRun
from modelanvil.rag.retrieval import RetrievalEngine


def chunk_payload(row):
    chunk = row.chunk
    return {'chunk_id':str(chunk.chunk_id), 'text':chunk.text, 'score':round(row.score,6),
        'metadata':{**chunk.metadata, 'document_title':chunk.document.title, 'source_uri':chunk.document.source_uri,
            'document_revision':chunk.document.revision_no, 'content_hash':chunk.content_hash,
            'span':f'{chunk.span_start}:{chunk.span_end}', 'span_start':chunk.span_start,
            'span_end':chunk.span_end, 'rank':row.rank, 'channel':row.channel}}


def retrieve(index, query, mode, top_k, embedding=None):
    engine = RetrievalEngine(index)
    if mode == 'lexical':
        return engine.retrieve_lexical(query, top_k=top_k)
    if index.configuration.get('embedding_profile') and index.configuration.get('embeddings_generated'):
        if embedding is not None:
            raise ValueError('Pinned vector indexes encode queries locally; omit caller-provided vectors.')
        from modelanvil.rag import embedding_adapter, embedding_jobs
        from modelanvil.identity.models import check_resource_access
        if not check_resource_access(index.embedding_space):
            raise ValueError('Embedding space is unavailable in this project.')
        if embedding_jobs.space_pins(index.embedding_space) != index.configuration['embedding_profile']:
            raise ValueError('The embedding-space pins changed.')
        if embedding_jobs.runtime_digest() != index.configuration['embedding_build_runtime']:
            raise ValueError('This embedding index requires its pinned runtime; rebuild under the current profile.')
        embedding = embedding_adapter.encode([query])[0].tolist()
    if index.adapter_type == 'lexical' or embedding is None:
        raise ValueError('Dense/hybrid retrieval needs a compatible vector index and actual query embedding.')
    if len(embedding) != index.embedding_space.dimension or not all(math.isfinite(v) for v in embedding):
        raise ValueError('Query vector must be finite and match the index embedding dimension.')
    return engine.retrieve_dense(embedding,top_k=top_k) if mode == 'dense' else engine.retrieve_hybrid(query,embedding,top_k=top_k)


def trace_query(index, query, mode, top_k, embedding=None):
    started = time.monotonic()
    rows = retrieve(index,query,mode,top_k,embedding)
    payload = [chunk_payload(row) for row in rows]
    if mode != 'lexical' and index.configuration.get('embedding_profile'):
        for row in payload:
            row['metadata'].update(embedding_space=index.configuration['embedding_profile'],query_embedding_source='pinned_local_cpu')
    trace = QueryTrace.objects.create(tenant_id=index.tenant_id,index_version=index,query=query,mode=mode,
        retrieved_chunk_ids=[row['chunk_id'] for row in payload], reranked_chunk_ids=[],
        supplied_context='',answer='',citations=[{'chunk_id':row['chunk_id'], 'score':row['score'], **row['metadata']} for row in payload],
        abstained=not bool(payload),latency_ms=round((time.monotonic()-started)*1000,3))
    return trace,payload


def visible_traces(index, limit=50):
    eligible = {str(chunk.chunk_id):chunk for chunk in RetrievalEngine(index).get_eligible_chunks()}
    result = []
    for trace in QueryTrace.objects.filter(index_version=index,tenant_id=index.tenant_id).order_by('-created_at','-id')[:limit]:
        if trace.redacted or any(key not in eligible for key in trace.retrieved_chunk_ids):
            continue
        rows=[]
        for ref in trace.citations:
            if ref.get('chunk_id') not in eligible:
                continue
            chunk=eligible[ref['chunk_id']]
            rows.append({'chunk_id':str(chunk.chunk_id),'text':chunk.text,'score':ref.get('score'),
                'metadata':{**chunk.metadata,'document_title':chunk.document.title,'document_revision':chunk.document.revision_no,
                    'source_uri':chunk.document.source_uri,'content_hash':chunk.content_hash,
                    'span':f'{chunk.span_start}:{chunk.span_end}',
                    **({k:ref[k] for k in ('embedding_space','query_embedding_source') if k in ref})}})
        result.append({'trace_id':str(trace.trace_id),'query':trace.query,'mode':trace.mode,
            'created_at':trace.created_at.isoformat(),'latency_ms':trace.latency_ms,'results':rows,
            'reranker':'none','generation':'not_executed','context_chunk_ids':[r['chunk_id'] for r in rows]})
    return result


@transaction.atomic
def compare(index, *, qrels_version, cases, modes, top_k, comparison_id=None):
    eligible = {str(chunk.chunk_id) for chunk in RetrievalEngine(index).get_eligible_chunks()}
    if index.status != 'ready' or not index.manifest_digest or 'chunk_ids' not in index.configuration:
        raise ValueError('Build a frozen index revision before comparing retrieval.')
    for case in cases:
        if set(case['qrels']) - eligible:
            raise ValueError('Every judged chunk must belong to the current authorized index.')
    judgments = [{'query_id':c['query_id'],'query':c['query'],'qrels':c['qrels']} for c in cases]
    digest = hashlib.sha256(json.dumps(sorted(judgments,key=lambda c:c['query_id']),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    reports=[]
    for mode in modes:
        run = RetrievalRun.objects.create(tenant_id=index.tenant_id,index_version=index,mode=mode,
            top_k=top_k,status='running',qrels_version=qrels_version,qrels_digest=digest)
        per_query=[]
        for case in cases:
            trace,rows=trace_query(index,case['query'],mode,top_k,case.get('query_embedding'))
            grades=case['qrels'];relevant={key for key,value in grades.items() if value>0}
            per_query.append({'query_id':case['query_id'],'query':case['query'],'trace_id':str(trace.trace_id),
                'retrieved_ids':[row['chunk_id'] for row in rows], 'metrics':compute_all_retrieval_metrics(
                    [row['chunk_id'] for row in rows],relevant,grades,top_k),'judged':bool(relevant)})
        judged=sum(row['judged'] for row in per_query)
        keys=list(per_query[0]['metrics'])
        means={}
        for key in keys:
            values=[row['metrics'][key] for row in per_query if row['metrics'][key] is not None]
            means[key]=sum(values)/len(values) if values else None
        run.metrics_summary={'metrics':means,'unit':'fraction','cutoff':top_k,'coverage':{'queries_total':len(cases),
            'queries_with_positive_qrels':judged,'queries_without_positive_qrels':len(cases)-judged},
            'na_semantics':'No positive qrels means N/A; unjudged cases are excluded from aggregate means.',
            'profile':'lexical-token-overlap-v1' if mode=='lexical' else 'pinned-local-minilm-pgvector-cosine-v1' if index.configuration.get('embedding_profile') else 'caller-provided-vectors; semantic qualification not inferred'}
        run.protocol_ref={'comparison_id':comparison_id,'index_manifest_digest':index.manifest_digest,'input_chunk_ids':sorted(eligible),
            'judgments':judgments,'queries':per_query,'reranker':'none','generation':'not_executed',
            'embedding_profile':index.configuration.get('embedding_profile'),'embedding_runtime':index.configuration.get('embedding_build_runtime')}
        run.status='completed';run.save(update_fields=['metrics_summary','protocol_ref','status','updated_at'])
        for key,value in means.items():
            RetrievalMetric.objects.create(tenant_id=index.tenant_id,run=run,key=key,k=top_k,
                value=value,is_na=value is None,sample_count=judged)
        reports.append(report(run))
    return reports


def report(run):
    from modelanvil.rag.models import IndexVersion
    from modelanvil.identity.models import check_resource_access
    index=IndexVersion.all_objects.select_related('knowledge_base').get(pk=run.index_version_id)
    eligible={str(c.chunk_id) for c in RetrievalEngine(index).get_eligible_chunks()}
    valid=(index.status=='ready' and check_resource_access(index.knowledge_base,tenant_id=index.tenant_id)
        and run.status=='completed' and bool(run.qrels_digest)
        and run.protocol_ref.get('index_manifest_digest')==index.manifest_digest
        and set(run.protocol_ref.get('input_chunk_ids',[]))<=eligible)
    if not valid:
        return {'run_id':str(run.run_id),'valid':False,'reason':'Inputs are unavailable, changed or unqualified; metrics and query content are withheld.'}
    return {'run_id':str(run.run_id),'valid':True,'index_id':str(index.index_id),'index_revision':index.revision_no,'mode':run.mode,
        'comparison_id':run.protocol_ref.get('comparison_id'),'qrels_version':run.qrels_version,'qrels_digest':run.qrels_digest,'top_k':run.top_k,
        **run.metrics_summary,'queries':run.protocol_ref['queries'],'reranker':'none','generation':'not_executed'}
