"""Frozen public relevance controls and raw ANN-neighbor recall on actual PostgreSQL."""
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

from django.db import connection
from modelanvil.core.ids import uuid7
from modelanvil.core.tenancy import get_active_tenant,get_active_project,set_active_tenant,set_active_project
from modelanvil.identity.models import Tenant,Team,Project
from modelanvil.rag.benchmark_corpus import load,select,PINS,PROTOCOL,ordered_key
from modelanvil.rag import embedding_adapter as adapter
from modelanvil.rag.ingestion import index_documents
from modelanvil.rag.models import KnowledgeBase,DocumentChunk,EmbeddingSpace,ChunkEmbedding,IndexVersion,QueryTrace,RetrievalRun
from modelanvil.rag.embedding_jobs import create_hnsw,runtime_digest
from modelanvil.rag.retrieval import RetrievalEngine
from modelanvil.rag.metrics import compute_all_retrieval_metrics
from modelanvil.runners.training.runtime import digest


def random_vector(identity):
    import numpy as np
    seed=int(hashlib.sha256((str(PROTOCOL['random_seed'])+':'+identity).encode()).hexdigest()[:16],16)
    vector=np.random.default_rng(seed).normal(size=384).astype('float32')
    return (vector/np.linalg.norm(vector)).tolist()


def aggregate(rows,cutoff):
    keys=list(rows[0]['metrics'])
    means={key:(sum(r['metrics'][key] for r in rows if r['metrics'][key] is not None)/sum(r['metrics'][key] is not None for r in rows)
                if any(r['metrics'][key] is not None for r in rows) else None) for key in keys}
    return {'queries_total':len(rows),'queries_judged':sum(r['positive_qrels']>0 for r in rows),
        'cutoff':cutoff,'metrics':means,'queries':rows,'na_semantics':'No positive qrels means N/A and is excluded from means.'}


def native_index(source,project,chunks,kind,vectors):
    space=EmbeddingSpace.all_objects.create(tenant_id=project.tenant_id,project=project,name=kind,
        model_name=adapter.PINS['model'] if kind=='real' else 'negative-control:gaussian-seed69',
        model_revision=adapter.PINS['revision'] if kind=='real' else digest(PROTOCOL),dimension=384,normalized=True,distance_metric='cosine',
        metadata={'profile_digest':digest(adapter.PINS) if kind=='real' else digest(PROTOCOL),'purpose':'public benchmark only'})
    runtime=runtime_digest() if kind=='real' else digest({'negative_control':PROTOCOL['random_seed']})
    ChunkEmbedding.all_objects.bulk_create([ChunkEmbedding(tenant_id=project.tenant_id,space=space,chunk=c,vector=v,
        content_hash=c.content_hash,vector_digest=adapter.vector_digest(v),runtime_digest=runtime) for c,v in zip(chunks,vectors)])
    name=create_hnsw(space)
    return IndexVersion.all_objects.create(tenant_id=project.tenant_id,project=project,knowledge_base=source.knowledge_base,
        embedding_space=space,revision_no=2 if kind=='real' else 3,adapter_type='dense',status='ready',chunks_count=len(chunks),
        manifest_digest=source.manifest_digest,configuration={**source.configuration,'embeddings_generated':True,
            'embedding_profile':{'purpose':'real_model' if kind=='real' else 'negative_control'},'embedding_build_runtime':runtime,
            'hnsw_index':name,'retrieval_settings':{'dense_search':'hnsw','hnsw':{'ef_search':100}}})


def benchmark():
    if connection.vendor!='postgresql':raise ValueError('The retrieval control report requires actual PostgreSQL/pgvector.')
    adapter.environment();adapter.verified_directory()
    import torch
    torch.set_num_threads(1)
    corpus,claims=load();documents,queries=select(corpus,claims)
    frozen={'protocol':PROTOCOL,'pins':PINS,'corpus_ids':[str(d['doc_id']) for d in documents],
        'queries':[{k:v for k,v in row.items() if k!='query'} for row in queries]}
    # Sampling and parameters are fixed before any model/control result is produced.
    frozen_digest=digest(frozen)
    previous=(get_active_tenant(),get_active_project());tenant=None;started=time.monotonic()
    try:
        tenant=Tenant.objects.create(slug='retrieval-control-'+uuid7().hex,name='Temporary public retrieval qualification')
        set_active_tenant(tenant.pk);set_active_project(None)
        team=Team.all_objects.create(tenant_id=tenant.pk,name='Temporary benchmark',slug='temporary')
        project=Project.all_objects.create(tenant_id=tenant.pk,team=team,name='Temporary public controls',slug='controls')
        set_active_project(project.pk)
        base=KnowledgeBase.all_objects.create(tenant_id=tenant.pk,project=project,name='Pinned public SciFact subset')
        source=index_documents(base,[{'title':d['title'],'source_uri':'scifact:'+str(d['doc_id']),
            'content':d['title']+'\n'+' '.join(d['abstract'])} for d in documents],PROTOCOL['chunk_size'],PROTOCOL['chunk_overlap'])
        chunks=list(DocumentChunk.all_objects.filter(tenant_id=tenant.pk).select_related('document').order_by('document__source_uri','chunk_index'))
        if len(chunks)>PROTOCOL['max_chunks']:raise ValueError('Frozen corpus exceeds the declared embedding bound.')
        stable={str(c.chunk_id):c.document.source_uri.split(':',1)[1]+':'+str(c.chunk_index) for c in chunks}
        vectors=[]
        for start in range(0,len(chunks),16):vectors.extend(adapter.encode([c.text for c in chunks[start:start+16]]).tolist())
        real=native_index(source,project,chunks,'real',vectors)
        random=native_index(source,project,chunks,'random',[random_vector('document:'+stable[str(c.chunk_id)]) for c in chunks])
        encoded={}
        for start in range(0,len(queries),16):
            batch=queries[start:start+16];matrix=adapter.encode([row['query'] for row in batch])
            encoded.update({row['id']:v.tolist() for row,v in zip(batch,matrix)})
        def relevance(rows):
            result={}
            for mode in ['real','random','full_text']:
                scored=[]
                for q in rows:
                    if mode=='full_text':ranked=RetrievalEngine(source).retrieve_lexical(q['query'],PROTOCOL['candidate_chunks'])
                    else:
                        engine=RetrievalEngine(real if mode=='real' else random)
                        vector=encoded[q['id']] if mode=='real' else random_vector('query:'+q['id'])
                        ranked=engine.retrieve_dense(vector,PROTOCOL['candidate_chunks'],dense_search='exact')
                    ids=[]
                    for row in ranked:
                        doc=row.chunk.document.source_uri.split(':',1)[1]
                        if doc not in ids:ids.append(doc)
                    ids=ids[:PROTOCOL['cutoff_documents']]
                    metrics=compute_all_retrieval_metrics(ids,set(q['relevant']),{key:1 for key in q['relevant']},PROTOCOL['cutoff_documents'])
                    scored.append({'query_id':q['id'],'retrieved_documents':ids,'positive_qrels':len(q['relevant']),
                        'returned_documents':len(ids),'metrics':metrics})
                result[mode]=aggregate(scored,PROTOCOL['cutoff_documents'])
            return result
        def ann(rows):
            result=[]
            for percent in PROTOCOL['ann_filter_percent']:
                members=[c for c in chunks if int(ordered_key('ann-filter',stable[str(c.chunk_id)])[:8],16)%100<percent]
                if not members:raise ValueError('Frozen ANN filter has no eligible chunks.')
                original=dict(real.configuration)
                try:
                    real.configuration={**original,'chunk_ids':[str(c.chunk_id) for c in members]};real.save(update_fields=['configuration'])
                    for ef in PROTOCOL['ef_search']:
                        observations=[]
                        for q in rows[:PROTOCOL['ann_queries_per_split']]:
                            engine=RetrievalEngine(real)
                            exact=engine.retrieve_dense(encoded[q['id']],PROTOCOL['ann_cutoff_chunks'],dense_search='exact')
                            actual=engine.retrieve_dense(encoded[q['id']],PROTOCOL['ann_cutoff_chunks'],dense_search='hnsw',ef_search=ef,allow_exact_fallback=False)
                            expected={row.chunk_id for row in exact};found={row.chunk_id for row in actual}
                            observations.append({'query_id':q['id'],'recall':len(expected&found)/len(expected),
                                'exact_count':len(expected),'ann_count':len(found),'exact_neighbor_ids':[stable[row.chunk_id] for row in exact],
                                'ann_neighbor_ids':[stable[row.chunk_id] for row in actual],'execution':dict(engine.execution)})
                        result.append({'filter_percent':percent,'eligible_chunks':len(members),'ef_search':ef,
                            'mean_neighbor_recall':sum(r['recall'] for r in observations)/len(observations),'queries':observations})
                finally:real.configuration=original;real.save(update_fields=['configuration'])
            return result
        dev_queries=[q for q in queries if q['role']=='development'];held_queries=[q for q in queries if q['role']=='held_out']
        development=relevance(dev_queries);development_ann=ann(dev_queries)
        primary=PROTOCOL['primary_metric']
        minimum=max(development[mode]['metrics'][primary] for mode in ['random','full_text'])
        qualified_ef=[ef for ef in PROTOCOL['ef_search'] if all(r['mean_neighbor_recall']>=.95 for r in development_ann if r['ef_search']==ef)]
        chosen_ef=min(qualified_ef) if qualified_ef else None
        thresholds={'minimum_relevance':minimum,'chosen_ef_search':chosen_ef,'source':'development controls and development ANN only'}
        # The held-out set is evaluated only after development thresholds are frozen.
        held=relevance(held_queries);held_ann=ann(held_queries)
        quality=held['real']['metrics'][primary]
        passes=chosen_ef is not None and quality>minimum and all(quality>held[m]['metrics'][primary] for m in ['random','full_text'])
        try:commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        except (OSError,subprocess.CalledProcessError):commit='unavailable'
        with connection.cursor() as cursor:
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname='vector'");pgvector=cursor.fetchone()[0]
            cursor.execute('SHOW server_version');postgres=cursor.fetchone()[0]
        report={'schema':'modelanvil.retrieval-controls.v1','commit':commit,'protocol':PROTOCOL,'frozen_input_digest':frozen_digest,
            'corpus_pins':PINS,'documents':len(documents),'chunks':len(chunks),'model_pins':adapter.PINS,
            'runtime':adapter.environment(),'hardware':{'system':platform.system(),'release':platform.release(),'architecture':platform.machine(),
                'processor':platform.processor(),'cpu_threads':torch.get_num_threads(),'gpu_used':False},
            'database':{'postgresql':postgres,'pgvector':pgvector},'index_parameters':RetrievalEngine(real).settings(PROTOCOL['ann_cutoff_chunks'])['hnsw'],
            'qrels_digest':digest([{k:v for k,v in q.items() if k!='query'} for q in queries]),
            'development':development,'frozen_thresholds':thresholds,'held_out':held,
            'ann_neighbor_recall':{'development':development_ann,'held_out':held_ann,'exact_fallback_enabled':False,
                'unit':'chunk-neighbor overlap, separate from document relevance'},'elapsed_seconds':round(time.monotonic()-started,3),
            'passed':passes,'fixture_cleanup':'owned temporary tenant/corpus/indexes removed after evaluation'}
        return report
    finally:
        if tenant:
            # Only this newly generated, unkeyed benchmark tenant is owned by this run.
            for model in [QueryTrace,RetrievalRun,ChunkEmbedding,IndexVersion,KnowledgeBase,EmbeddingSpace,Project,Team]:
                model.all_objects.filter(tenant_id=tenant.pk).delete()
            tenant.delete()
        set_active_tenant(previous[0]);set_active_project(previous[1])
