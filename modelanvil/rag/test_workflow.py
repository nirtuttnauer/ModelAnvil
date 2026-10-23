"""Actual frozen-source retrieval, judgments, measured geometry and revocation."""
import math
from unittest.mock import patch
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.identity.models import Tenant, ApiKey, Role, generate_api_key
from modelanvil.rag.explorer import ClusterExplorer
from modelanvil.rag.models import DocumentChunk, EmbeddingSpace, IndexVersion, KnowledgeBase, ProjectionArtifact, QueryTrace, RetrievalRun, SourceDocument


@override_settings(ALLOWED_HOSTS=['testserver'])
class RagWorkflowTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(slug='rag-workflow',name='RAG workflow')
        self.foreign=Tenant.objects.create(slug='rag-foreign',name='Other')
        self.client=self.client_for(self.tenant)
        response=self.client.post('/api/v1/knowledge-bases/',{'name':'Pinned sources'},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.base=KnowledgeBase.all_objects.get(kb_id=response.json()['knowledge_base_id'])
        self.index=self.build([{'title':'Alpha','source_uri':'local:alpha','content':'alpha alpha source'},
                              {'title':'Beta','source_uri':'local:beta','content':'beta source'}])
        self.alpha=DocumentChunk.all_objects.get(document__knowledge_base=self.base,document__title='Alpha')

    def client_for(self,tenant):
        secret,hashed=generate_api_key();ApiKey.objects.create(tenant=tenant,name='workflow',role=Role.OWNER,secret_hash=hashed)
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+secret);return client

    def build(self,documents):
        response=self.client.post(f'/api/v1/knowledge-bases/{self.base.kb_id}/index/',{'documents':documents,'chunk_size':100,'chunk_overlap':0},format='json')
        self.assertEqual(response.status_code,201,response.content)
        return IndexVersion.all_objects.get(index_id=response.json()['index_id'])

    def path(self,index=None,action='query'):
        return f'/api/v1/index-versions/{(index or self.index).index_id}/{action}/'

    def judgments(self):
        return {'qrels_version':'human-fixture-v1','top_k':2,'modes':['lexical'],'cases':[
            {'query_id':'judged','query':'alpha','qrels':{str(self.alpha.chunk_id):1}},
            {'query_id':'unjudged','query':'nothing','qrels':{}}]}

    def test_query_freezes_actual_spans_mode_and_non_generation_trace(self):
        response=self.client.post(self.path(),{'query':'alpha','mode':'hybrid','top_k':2},format='json')
        self.assertEqual(response.status_code,200,response.content)
        data=response.json();self.assertEqual(data['mode'],'lexical');self.assertEqual(data['generation'],'not_executed')
        row=data['results'][0];self.assertEqual(row['text'],self.alpha.text)
        self.assertEqual(row['metadata']['span'],'0:18')
        self.assertEqual(row['metadata']['document_revision'],1)
        trace=QueryTrace.all_objects.get(trace_id=data['trace_id'])
        self.assertEqual(trace.retrieved_chunk_ids,[str(self.alpha.chunk_id)])
        self.assertEqual(trace.answer,'');self.assertEqual(trace.reranked_chunk_ids,[])
        self.assertEqual(self.index.configuration['chunk_recipe'],'character-slices-v1')
        self.assertTrue(self.index.configuration['source_scope']['current_permissions_required'])
        self.assertEqual(len(self.index.configuration['source_revisions']),2)
        history=self.client.get(self.path(action='traces')).json()['results']
        self.assertEqual(history[0]['trace_id'],data['trace_id'])

    def test_versioned_qrels_metrics_cutoff_coverage_and_na(self):
        response=self.client.post(self.path(action='comparisons'),self.judgments(),format='json')
        self.assertEqual(response.status_code,201,response.content)
        report=response.json()['results'][0]
        self.assertEqual(report['unit'],'fraction');self.assertEqual(report['cutoff'],2)
        self.assertEqual(report['metrics']['precision@2'],0.5)
        self.assertEqual(report['metrics']['recall@2'],1)
        self.assertEqual(report['coverage']['queries_with_positive_qrels'],1)
        self.assertEqual(report['coverage']['queries_total'],2)
        self.assertTrue(all(value is None for value in report['queries'][1]['metrics'].values()))
        self.assertEqual(len(report['qrels_digest']),64)
        self.assertEqual(report['qrels_version'],'human-fixture-v1')

    def test_paired_indexes_share_judgment_digest_and_survive_reopen(self):
        later=self.build([{'title':'Gamma','source_uri':'local:gamma','content':'gamma source'}])
        data={**self.judgments(),'baseline_index_id':str(self.index.index_id)}
        response=self.client.post(self.path(later,'comparisons'),data,format='json')
        self.assertEqual(response.status_code,201,response.content)
        reports=response.json()['results'];self.assertEqual(len(reports),2)
        self.assertEqual(len({r['qrels_digest'] for r in reports}),1)
        self.assertEqual(len({r['comparison_id'] for r in reports}),1)
        reopened=self.client.get(self.path(later,'comparisons')).json()['results']
        self.assertEqual({r['run_id'] for r in reopened},{r['run_id'] for r in reports})
        self.assertNotIn(str(DocumentChunk.all_objects.get(document__title='Gamma').chunk_id),self.index.configuration['chunk_ids'])

    def test_revocation_removes_old_traces_and_withholds_saved_metrics(self):
        self.assertEqual(self.client.post(self.path(),{'query':'alpha','mode':'lexical'},format='json').status_code,200)
        self.assertEqual(self.client.post(self.path(action='comparisons'),self.judgments(),format='json').status_code,201)
        response=self.client.post(f'/api/v1/knowledge-bases/{self.base.kb_id}/revoke-document/',{'document_id':str(self.alpha.document.doc_id)},format='json')
        self.assertEqual(response.status_code,200,response.content)
        history=self.client.get(self.path(action='traces')).json()['results']
        self.assertTrue(all(row['query']!='alpha' and not row['results'] for row in history))
        reports=self.client.get(self.path(action='comparisons')).json()['results']
        self.assertFalse(reports[0]['valid']);self.assertNotIn('metrics',reports[0]);self.assertNotIn('queries',reports[0])
        self.assertEqual(self.client.post(self.path(),{'query':'alpha','mode':'lexical'},format='json').json()['results'],[])
        pool=self.client.get(self.path(action='judgment-pool')).json()['results']
        self.assertNotIn(str(self.alpha.chunk_id),{row['chunk_id'] for row in pool})

    def test_foreign_ids_and_partial_comparison_never_publish(self):
        foreign=self.client_for(self.foreign)
        self.assertEqual(foreign.get(self.path(action='comparisons')).status_code,404)
        bad={**self.judgments(),'modes':['lexical','dense']}
        self.assertEqual(self.client.post(self.path(action='comparisons'),bad,format='json').status_code,400)
        self.assertEqual(RetrievalRun.all_objects.count(),0)
        self.assertEqual(QueryTrace.all_objects.count(),0)
        bad=self.judgments();bad['cases'][0]['qrels']={'00000000-0000-4000-8000-000000000000':1}
        self.assertEqual(self.client.post(self.path(action='comparisons'),bad,format='json').status_code,400)

    def test_interrupted_ingestion_is_atomic_and_building_indexes_are_not_queryable(self):
        before=SourceDocument.all_objects.count();versions=IndexVersion.all_objects.count()
        with patch('modelanvil.rag.ingestion.DocumentChunk.objects.bulk_create',side_effect=RuntimeError('Injected build interruption')):
            response=self.client.post(f'/api/v1/knowledge-bases/{self.base.kb_id}/index/',{'documents':[{'title':'Interrupted','content':'uncommitted source'}]},format='json')
            self.assertEqual(response.status_code,500,response.content)
        self.assertEqual(SourceDocument.all_objects.count(),before)
        self.assertEqual(IndexVersion.all_objects.count(),versions)
        self.index.status='building';self.index.save(update_fields=['status'])
        self.assertEqual(self.client.post(self.path(),{'query':'alpha'},format='json').status_code,409)

    def vector_index(self):
        index=self.build([{'title':'Gamma','source_uri':'local:gamma','content':'gamma source'}])
        space=EmbeddingSpace.all_objects.create(tenant_id=self.tenant.pk,name='Provided test vectors',model_name='fixture-only',dimension=2)
        index.embedding_space=space;index.save(update_fields=['embedding_space'])
        for chunk in DocumentChunk.all_objects.filter(document__knowledge_base=self.base):
            chunk.embedding={'Alpha':[0.,0.],'Beta':[3.,0.],'Gamma':[0.,4.]}[chunk.document.title]
            chunk.save(update_fields=['embedding'])
        return index

    def test_measured_pca_preserves_rank_two_geometry_and_has_no_fake_query_point(self):
        index=self.vector_index();explorer=ClusterExplorer(index)
        artifact=explorer.build_and_save_projection(num_clusters=2)
        points={p['title']:p for p in artifact.coordinates}
        distance=lambda a,b:math.hypot(points[a]['x']-points[b]['x'],points[a]['y']-points[b]['y'])
        self.assertAlmostEqual(distance('Alpha','Beta'),3,places=5)
        self.assertAlmostEqual(distance('Alpha','Gamma'),4,places=5)
        self.assertAlmostEqual(distance('Beta','Gamma'),5,places=5)
        self.assertEqual(artifact.method,'pca');self.assertEqual(artifact.settings['method_version'],'pca-svd-v1')
        overlay=explorer.overlay_query_and_relevance(artifact,'alpha',[],[])
        self.assertIsNone(overlay['query_point'])
        overlay=explorer.overlay_query_and_relevance(artifact,'alpha',[],[],query_embedding=[0.,0.])
        self.assertAlmostEqual(overlay['query_point']['x'],points['Alpha']['x'],places=5)
        self.assertEqual(len(explorer.export_accessible_table(artifact)),3)
        with self.assertRaises(ValueError):explorer.build_and_save_projection(method='umap')

    def test_cached_explorer_and_legacy_hash_projection_refuse_changed_or_revoked_inputs(self):
        index=self.vector_index();explorer=ClusterExplorer(index);artifact=explorer.build_and_save_projection()
        old=ProjectionArtifact.objects.create(tenant_id=self.tenant.pk,index_version=index,method='pca',coordinates=artifact.coordinates)
        with self.assertRaises(ValueError):explorer.export_accessible_table(old)
        DeletionTombstone.objects.create(tenant_id=self.tenant.pk,resource_type='document',resource_id=str(self.alpha.document.doc_id),reason='test deletion')
        with self.assertRaises(ValueError):explorer.export_accessible_table(artifact)
        with self.assertRaises(ValueError):explorer.overlay_query_and_relevance(artifact,'alpha',[],[])
        with self.assertRaises(ValueError):explorer.get_original_space_neighbors(str(self.alpha.chunk_id))
        response=self.client.get(self.path(index,'projection'));self.assertEqual(response.status_code,409)
