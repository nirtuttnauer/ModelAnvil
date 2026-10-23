"""Citation, budget, authorization and real local model RAG checks."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from modelanvil.rag.generation import citation_result,budget


def chunk(key):
    return SimpleNamespace(chunk_id=key,text='The access code is WILLOW.',content_hash='fixed',span_start=0,span_end=25,
        document=SimpleNamespace(title='Beacon',source_uri='fixture:beacon'))


class GenerationGuards(SimpleTestCase):
    def test_citations_are_subsets_and_unanswerable_and_format_refusals_are_distinct(self):
        source=chunk('known-chunk')
        status,answer,citations,reason=citation_result('WILLOW [1]',[source],'retrieved')
        self.assertEqual(status,'answered');self.assertEqual({c['chunk_id'] for c in citations},{'known-chunk'})
        for output in ['WILLOW [2]','WILLOW [1] [unknown]','WILLOW [1] ［9］']:
            self.assertEqual(citation_result(output,[source],'retrieved')[0],'validation_refusal')
        self.assertEqual(citation_result('I do not know.',[source],'retrieved')[0],'model_abstain')
        self.assertEqual(citation_result('WILLOW',[source],'retrieved')[3],'missing_citation')
        self.assertEqual(citation_result('WILLOW',[],'none')[0],'answered')
        self.assertEqual(citation_result('WILLOW [1]',[],'none')[3],'unknown_citation')

    def test_required_question_and_output_reserve_never_silently_truncated(self):
        tokenizer=SimpleNamespace(chat_template='test',encode=lambda text,**kwargs:list(text))
        session={'tokenizer':tokenizer,'config':SimpleNamespace(max_position_embeddings=100)}
        with patch('modelanvil.rag.generation.inference.rendered_prompt',side_effect=lambda t,m,f:'\n'.join(r['content'] for r in m)):
            with self.assertRaises(ValueError):budget(session,'Q'*90,[chunk('one')],'retrieved',10,'omit_optional_evidence')
            session['config'].max_position_embeddings=1024
            one,two=chunk('one'),chunk('two');one.text=two.text='Fact '*300
            messages,rows,receipt=budget(session,'question',[one,two],'retrieved',20,'omit_optional_evidence')
            self.assertEqual(set(receipt['omitted_chunk_ids']),{'one','two'})
            self.assertLessEqual(receipt['total_reserved_tokens'],receipt['runtime_limit_tokens'])
            self.assertIn('question',messages[-1]['content'])

from django.test import TransactionTestCase,tag,override_settings
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient
import tempfile
import json
import os
from modelanvil.core.tenancy import reset_context,set_active_tenant,set_active_project
from modelanvil.identity.models import Tenant,Team,Project,ApiKey,Role,generate_api_key
from modelanvil.rag.models import KnowledgeBase,IndexVersion,SourceDocument,RAGGeneration,EmbeddingSpace,EmbeddingBuild,DocumentChunk
from modelanvil.rag import decoder,embedding_adapter as adapter,embedding_jobs as builds
from modelanvil.runners.training.runtime import digest
from modelanvil.jobs.models import WorkerPool,Worker
from modelanvil.jobs.executor import execute_one
from modelanvil.budgets.models import BudgetPolicy


@tag('pg')
@override_settings(ALLOWED_HOSTS=['testserver'])
class ActualGroundedGenerationTests(TransactionTestCase):
    def setUp(self):
        reset_context();self.addCleanup(reset_context)
        self.folder=tempfile.TemporaryDirectory(prefix='rag-generation-test-');self.addCleanup(self.folder.cleanup)
        self.enterContext(override_settings(MODELANVIL={**settings.MODELANVIL,'artifact_root':self.folder.name}))
        self.tenant=Tenant.objects.create(slug='actual-rag-generation',name='Actual RAG generation')
        team=Team.all_objects.create(tenant_id=self.tenant.pk,name='Team',slug='team')
        self.project=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,name='Project',slug='project')
        set_active_tenant(self.tenant.pk);set_active_project(self.project.pk)
        self.model=decoder.register(self.project)
        secret,hashed=generate_api_key();ApiKey.objects.create(tenant=self.tenant,name='RAG tests',role=Role.OWNER,secret_hash=hashed)
        self.client=APIClient();self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret,HTTP_X_PROJECT_ID=str(self.project.pk))
        response=self.client.post('/api/v1/knowledge-bases/',{'name':'Authored CC0 evidence'},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.base=KnowledgeBase.all_objects.get(kb_id=response.json()['knowledge_base_id'])
        response=self.client.post(f'/api/v1/knowledge-bases/{self.base.kb_id}/index/',{'chunk_size':100,'chunk_overlap':0,
            'documents':[{'title':title,'source_uri':uri,'content':content} for title,uri,content in [
                ('Island beacon','fixture:island-beacon','The access code for the island beacon is WILLOW.'),
                ('Valley station','fixture:valley-station','The access code for the valley station is CEDAR.'),
                ('Harbor tower','fixture:harbor-tower','The access code for the harbor tower is MAPLE.')]]},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.source=IndexVersion.all_objects.get(index_id=response.json()['index_id'])
        space=EmbeddingSpace.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Pinned MiniLM',model_name=adapter.PINS['model'],
            model_revision=adapter.PINS['revision'],license_expression='apache-2.0',dimension=384,normalized=True,distance_metric='cosine',
            metadata={'profile_digest':digest(adapter.PINS)})
        pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='Real embedding pool',result_egress='envelope')
        worker=Worker.all_objects.create(tenant_id=self.tenant.pk,pool=pool,name='Encoder',slots=1,capabilities={'embedding_runtime':builds.runtime_digest()},last_heartbeat_at=timezone.now())
        policy=BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,name='Embedding attempts',unit='embedding_attempts',period='lifetime',limit_amount=10)
        response=self.client.post('/api/v1/embedding-builds/',{'source_index':str(self.source.index_id),'space':str(space.space_id),
            'pool':pool.pk,'budget_policy':str(policy.policy_id),'idempotency_key':'generation-index'},format='json')
        self.assertEqual(response.status_code,202,response.content)
        build=EmbeddingBuild.all_objects.get(build_id=response.json()['build_id'])
        self.assertTrue(execute_one(worker,builds.embedding_executor)['committed']);build.index.refresh_from_db()
        self.assertEqual(build.index.status,'ready');self.index=build.index

    def test_actual_three_conditions_usage_citation_scope_abstention_and_revocation(self):
        import torch
        torch.set_num_threads(1)
        question='What is the access code for the island beacon?'
        chosen=str(DocumentChunk.all_objects.get(document__source_uri='fixture:island-beacon',document__knowledge_base=self.base).chunk_id)
        actual=[]
        for condition in ['none','retrieved','human']:
            values={'query':question,'model_version':str(self.model.model_version_id),'condition':condition,
                    'retrieval_mode':'dense','top_k':2,'max_tokens':64}
            if condition=='human':values['human_chunk_ids']=[chosen]
            response=self.client.post(f'/api/v1/index-versions/{self.index.index_id}/generations/',values,format='json')
            self.assertEqual(response.status_code,201,response.content)
            row=response.json();self.assertTrue(row['receipt']['generation_executed'])
            self.assertEqual(row['receipt']['usage']['prompt_tokens'],row['receipt']['budget']['input_tokens'])
            self.assertLessEqual(row['receipt']['usage']['total_tokens'],row['receipt']['budget']['runtime_limit_tokens'])
            self.assertTrue({c['chunk_id'] for c in row['citations']}<=set(row['receipt']['budget']['supplied_chunk_ids']))
            if condition=='none':self.assertEqual(row['receipt']['budget']['supplied_chunk_ids'],[])
            actual.append(row)
        # A known absent entity under literal lexical retrieval is a policy abstention, not a model answer.
        response=self.client.post(f'/api/v1/index-versions/{self.index.index_id}/generations/',{'query':'unlisted winter observatory access code',
            'model_version':str(self.model.model_version_id),'condition':'retrieved','retrieval_mode':'lexical'},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['status'],'policy_abstain');self.assertFalse(response.json()['receipt']['generation_executed'])
        actual.append(response.json())
        # With nonempty but irrelevant retrieved context, measure the actual model separately.
        response=self.client.post(f'/api/v1/index-versions/{self.index.index_id}/generations/',{'query':'What is the access code for the unlisted winter observatory?',
            'model_version':str(self.model.model_version_id),'condition':'retrieved','retrieval_mode':'dense','top_k':2},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.assertTrue(response.json()['receipt']['generation_executed']);actual.append(response.json())
        labels=[{'run_id':r['run_id'],'answerable':i<3,'reference':'WILLOW' if i<3 else None} for i,r in enumerate(actual)]
        abstention={'known_unanswerable':2,'model_executed':sum(r['receipt']['generation_executed'] for r in actual[3:]),
            'model_declared_abstentions':sum(r['status']=='model_abstain' for r in actual[3:]),
            'policy_abstentions':sum(r['status']=='policy_abstain' for r in actual[3:]),
            'validation_refusals':sum(r['status']=='validation_refusal' for r in actual[3:]),
            'delivered_false_answers':sum(r['status']=='answered' for r in actual[3:])}
        relevance={'answerable_queries':1,'hit_at_2':int(chosen in actual[1]['receipt']['retrieved_chunk_ids'])}
        path=os.environ.get('MODELANVIL_RAG_GENERATION_REPORT')
        if path:
            from pathlib import Path
            with Path(path).open('x') as stream:json.dump({'runs':actual,'labels':labels,'abstention':abstention,'retrieval_relevance':relevance,'model':decoder.PINS,'fixture_license':'CC0-1.0 authored software qualification'},stream,indent=2)
        print('TASK70_ACTUAL '+json.dumps([{'condition':r['condition'],'status':r['status'],'answer':r['answer'],'raw_output':r['raw_output'],
            'usage':r['receipt'].get('usage'),'reason':r['receipt']['reason']} for r in actual]))
        # Revoke a source after actual generation but before publication: nothing escapes.
        from modelanvil.runners import inference
        original=inference.generate
        def revoke_during_generation(*args,**kwargs):
            yield from original(*args,**kwargs)
            SourceDocument.all_objects.filter(knowledge_base=self.base,source_uri='fixture:island-beacon').update(is_revoked=True)
        before=RAGGeneration.all_objects.count()
        with patch('modelanvil.rag.generation.inference.generate',side_effect=revoke_during_generation):
            response=self.client.post(f'/api/v1/index-versions/{self.index.index_id}/generations/',values,format='json')
        self.assertEqual(response.status_code,400,response.content)
        self.assertEqual(RAGGeneration.all_objects.count(),before)
        # Current source authorization governs saved model output on reload.
        SourceDocument.all_objects.filter(knowledge_base=self.base,source_uri='fixture:island-beacon').update(is_revoked=True)
        response=self.client.get(f'/api/v1/index-versions/{self.index.index_id}/generations/')
        self.assertEqual(response.status_code,200,response.content)
        visible_ids={r['run_id'] for r in response.json()['results']}
        self.assertNotIn(actual[2]['run_id'],visible_ids)
        invalid={**values,'condition':'human','human_chunk_ids':[str(__import__('uuid').uuid4())]}
        response=self.client.post(f'/api/v1/index-versions/{self.index.index_id}/generations/',invalid,format='json')
        self.assertEqual(response.status_code,400)
