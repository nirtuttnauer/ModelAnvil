"""Real PostgreSQL ranking plans and current access filters, with no model mocks."""
import json
import math
from django.db import connection
from django.test import TestCase, tag
from modelanvil.core.tenancy import reset_context, set_active_tenant, set_active_project
from modelanvil.identity.models import Tenant, Team, Project, ProjectGrant
from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.rag.models import KnowledgeBase, SourceDocument, DocumentChunk, EmbeddingSpace, ChunkEmbedding, IndexVersion
from modelanvil.rag.retrieval import RetrievalEngine
from modelanvil.rag.embedding_jobs import create_hnsw
from modelanvil.rag.embedding_adapter import vector_digest


@tag('pg')
class SQLRetrievalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        reset_context()
        cls.tenant=Tenant.objects.create(slug='sql-retrieval',name='SQL retrieval')
        team=Team.all_objects.create(tenant_id=cls.tenant.pk,slug='team',name='Team')
        cls.project=Project.all_objects.create(tenant_id=cls.tenant.pk,team=team,slug='one',name='One')
        cls.other=Project.all_objects.create(tenant_id=cls.tenant.pk,team=team,slug='two',name='Two')
        cls.base=KnowledgeBase.all_objects.create(tenant_id=cls.tenant.pk,project=cls.project,name='Plan fixture')
        cls.space=EmbeddingSpace.all_objects.create(tenant_id=cls.tenant.pk,project=cls.project,name='SQL fixture',model_name='SQL unit fixture',dimension=384)
        docs=SourceDocument.all_objects.bulk_create([SourceDocument(tenant_id=cls.tenant.pk,knowledge_base=cls.base,
            title=f'Fixture {i}',source_uri=f'fixture:{i}',content='orange cat',content_hash=f'{i:064x}') for i in range(1000)])
        chunks=DocumentChunk.all_objects.bulk_create([DocumentChunk(tenant_id=cls.tenant.pk,document=doc,
            chunk_index=0,text='orange cat' if i%2 else 'cat orange cat',content_hash=f'{i+1000:064x}') for i,doc in enumerate(docs)])
        rows=[]
        for i,chunk in enumerate(chunks):
            theta=i/1000
            vector=[math.cos(theta),math.sin(theta)]+[0.]*382
            rows.append(ChunkEmbedding(tenant_id=cls.tenant.pk,space=cls.space,chunk=chunk,vector=vector,
                content_hash=chunk.content_hash,vector_digest=vector_digest(vector),runtime_digest='sql-fixture'))
        ChunkEmbedding.all_objects.bulk_create(rows)
        cls.chunks=chunks
        with connection.cursor() as cursor:cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        name=create_hnsw(cls.space)
        cls.index=IndexVersion.all_objects.create(tenant_id=cls.tenant.pk,project=cls.project,
            knowledge_base=cls.base,embedding_space=cls.space,chunks_count=len(chunks),configuration={
                'chunk_ids':[str(c.chunk_id) for c in chunks],'embeddings_generated':True,
                'embedding_profile':{'fixture':True},'embedding_build_runtime':'sql-fixture','hnsw_index':name})
        with connection.cursor() as cursor:
            cursor.execute('ANALYZE rag_chunkembedding');cursor.execute('ANALYZE rag_documentchunk')
            cursor.execute('ANALYZE rag_sourcedocument');cursor.execute('ANALYZE rag_indexversion')
            cursor.execute('ANALYZE rag_embeddingspace');cursor.execute('ANALYZE rag_knowledgebase')

    def setUp(self):
        reset_context();set_active_tenant(self.tenant.pk);set_active_project(self.project.pk)
        self.addCleanup(reset_context)
        self.engine=RetrievalEngine(self.index)
        self.query=[1.]+[0.]*383

    def test_exact_hnsw_plans_and_transaction_settings(self):
        plans=[]
        def capture(execute,sql,params,many,context):
            if not sql.startswith('EXPLAIN') and 'rag_chunkembedding' in sql and 'ORDER BY' in sql and '<=>' in sql:
                with connection.cursor() as cursor:
                    cursor.execute('EXPLAIN (FORMAT JSON) '+sql,params);plans.append(cursor.fetchone()[0])
            return execute(sql,params,many,context)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = 41")
        with connection.execute_wrapper(capture):
            exact=self.engine.retrieve_dense(self.query,5,dense_search='exact')
            approximate=self.engine.retrieve_dense(self.query,5,dense_search='hnsw')
        self.assertEqual([c.chunk_id for c in exact],[c.chunk_id for c in approximate])
        with connection.cursor() as cursor:
            cursor.execute('SHOW hnsw.ef_search');self.assertEqual(cursor.fetchone()[0],'41')
            cursor.execute('SHOW enable_sort');self.assertEqual(cursor.fetchone()[0],'on')
        self.assertNotIn(self.index.configuration['hnsw_index'],json.dumps(plans[0]))
        self.assertIn(self.index.configuration['hnsw_index'],json.dumps(plans[1]))
        print('TASK68_EXPLAIN '+json.dumps({'exact':plans[0],'hnsw':plans[1]}))

    def test_sql_full_text_rank_hybrid_and_parameters(self):
        captured=[]
        def capture(execute,sql,params,many,context):
            captured.append(sql);return execute(sql,params,many,context)
        with connection.execute_wrapper(capture):rows=self.engine.retrieve_lexical('"orange cat"',5)
        self.assertEqual(len(rows),5)
        sql='\n'.join(captured)
        self.assertIn('to_tsvector',sql);self.assertIn('ts_rank_cd',sql);self.assertIn('websearch_to_tsquery',sql)
        hybrid=self.engine.retrieve_hybrid('orange cat',self.query,5)
        self.assertEqual(len(hybrid),5)
        self.assertEqual(self.engine.settings(5)['candidate_count'],10)
        self.assertEqual(self.engine.settings()['rrf_k'],60)
        with self.assertRaises(ValueError):self.engine.retrieve_dense(self.query,dense_search='unknown')
        from modelanvil.rag.workflow import trace_query
        trace,rows=trace_query(self.index,'unmatchablelexicaltoken','lexical',5)
        self.assertEqual(rows,[])
        trace.refresh_from_db()
        self.assertEqual(trace.retrieval_config['lexical'],'postgresql-ts-rank-cd-simple-v1')

    def test_narrow_membership_tombstones_and_revocations_stay_inside_ranking(self):
        # Nearest vectors are all excluded; only the last few frozen chunks survive.
        ids=[str(c.chunk_id) for c in self.chunks[-4:]]
        self.index.configuration={**self.index.configuration,'chunk_ids':ids};self.index.save()
        DeletionTombstone.all_objects.create(tenant_id=self.tenant.pk,resource_type='document_chunk',resource_id=ids[0])
        DeletionTombstone.all_objects.create(tenant_id=self.tenant.pk,resource_type='content',resource_id=self.chunks[-3].document.content_hash)
        SourceDocument.all_objects.filter(pk=self.chunks[-2].document_id).update(is_revoked=True)
        for strategy in ['exact','hnsw']:
            rows=self.engine.retrieve_dense(self.query,5,dense_search=strategy)
            self.assertEqual([row.chunk_id for row in rows],[ids[-1]])
        self.assertEqual([row.chunk_id for row in self.engine.retrieve_lexical('cat',5)],[ids[-1]])
        SourceDocument.all_objects.filter(pk=self.chunks[-1].document_id).update(is_deleted=True)
        self.assertEqual(self.engine.retrieve_hybrid('cat',self.query,5),[])

    def test_grant_revocation_and_tenant_scope_on_already_created_queryset(self):
        set_active_project(self.other.pk)
        grants=[ProjectGrant.all_objects.create(tenant_id=self.tenant.pk,project=self.project,
            granted_to_project=self.other,resource_type='all')]
        pending=self.engine.eligible_queryset()
        self.assertTrue(pending.exists())
        ProjectGrant.all_objects.filter(pk=grants[0].pk).delete()
        self.assertEqual(list(pending),[])
        self.assertEqual(self.engine.retrieve_dense(self.query,5),[])
        set_active_tenant(Tenant.objects.create(slug='foreign',name='Foreign').pk)
        self.assertEqual(self.engine.retrieve_lexical('cat',5),[])

    def test_all_tombstone_identities_and_wrong_resource_grants(self):
        chunk=self.chunks[0]
        self.index.configuration={**self.index.configuration,'chunk_ids':[str(chunk.chunk_id)]};self.index.save()
        for key in [str(chunk.chunk_id),str(chunk.document.doc_id),chunk.content_hash,chunk.document.content_hash]:
            tombstone=DeletionTombstone.all_objects.create(tenant_id=self.tenant.pk,resource_type='retrieval',resource_id=key)
            self.assertEqual(self.engine.retrieve_dense(self.query,5),[])
            self.assertEqual(self.engine.retrieve_lexical('cat',5),[])
            tombstone.delete()
        set_active_project(self.other.pk)
        ProjectGrant.all_objects.create(tenant_id=self.tenant.pk,project=self.project,granted_to_project=self.other,
            resource_type='knowledgebase',resource_id=self.base.kb_id)
        self.assertEqual(self.engine.retrieve_lexical('cat',5),[])
        ProjectGrant.all_objects.create(tenant_id=self.tenant.pk,project=self.project,granted_to_project=self.other,
            resource_type='indexversion',resource_id=self.index.index_id)
        self.assertEqual(self.engine.retrieve_dense(self.query,5),[])
        grant=ProjectGrant.all_objects.create(tenant_id=self.tenant.pk,project=self.project,granted_to_project=self.other,
            resource_type='embeddingspace',resource_id=self.space.space_id)
        self.assertEqual(len(self.engine.retrieve_dense(self.query,5)),1)
        grant.delete()
        self.assertEqual(self.engine.retrieve_dense(self.query,5),[])
