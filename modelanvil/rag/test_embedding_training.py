import copy
import hashlib
import io
import json
import tempfile
from django.test import TestCase, override_settings
from modelanvil.core.tenancy import reset_context, set_active_tenant, set_active_project
from modelanvil.identity.models import Tenant,Team,Project
from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import upload_staged_artifact
from modelanvil.rag import embedding_training as training, embedding_adapter as adapter


def fixture():
    documents=[{'id':key,'text':content,'source_group':group,'split':split} for key,content,group,split in [
        ('reset','Recover your account with the reset password link.','accounts','train'),
        ('router','Restart the router to restore wireless connectivity.','networking','train'),
        ('refund','A purchase can be refunded within thirty days.','billing','dev'),
        ('deliver','Track the delivery package with your shipping number.','shipping','held_out')]]
    return {'schema':training.SCHEMA,'license':'CC0-1.0; authored software fixture','source_uri':'fixture:modelanvil-embedding-triplets-v1',
        'documents':documents,'triplets':[{'id':'train-1','query':'How do I reset a password?','source_group':'accounts',
            'positive':'reset','negative':'router','negative_provenance':{'kind':'manual_reviewed','model_revision':adapter.PINS['revision'],
                'pool_split':'train','document_id':'router'}}],
        'qrels':[{'id':key,'query':query,'source_group':group,'split':split,'grades':{doc:1}} for key,query,group,split,doc in [
            ('dev-1','How long do refunds take?','billing','dev','refund'),
            ('test-1','Where is my shipped parcel?','shipping','held_out','deliver')]]}


class EmbeddingSplitTests(TestCase):
    def setUp(self):
        reset_context();self.addCleanup(reset_context)
        self.tenant=Tenant.objects.create(name='Embedding split tests',slug='embedding-splits')
        team=Team.all_objects.create(tenant_id=self.tenant.pk,name='Team',slug='team')
        self.project=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,name='Project',slug='project')
        set_active_tenant(self.tenant.pk);set_active_project(self.project.pk)

    def test_split_aliases_negative_provenance_and_strict_input(self):
        value=fixture();training.validate_manifest(value)
        for mutate in [lambda v:v['documents'][3].update(source_group='accounts'),
                       lambda v:v['documents'][3].update(text=v['documents'][0]['text'].upper()),
                       lambda v:v['triplets'][0].update(negative='deliver'),
                       lambda v:v['triplets'][0].update(negative=['not-an-id']),
                       lambda v:v['triplets'][0]['negative_provenance'].update(pool_split='held_out'),
                       lambda v:v['qrels'][1].update(query=v['triplets'][0]['query'])]:
            changed=copy.deepcopy(value);mutate(changed)
            with self.assertRaises(ValueError):training.validate_manifest(changed)

    def test_persistent_training_and_heldout_roles_and_future_suite_registration(self):
        value=fixture();training.protect_splits(self.project,value)
        from modelanvil.annotation.feedback import assert_uninspected_cases
        for case in [{'source_group_id':'accounts','input_prompt':'unrelated prompt'},
                     {'source_group_id':'renamed-group','input_prompt':value['triplets'][0]['query'].upper()}]:
            with self.assertRaisesMessage(ValueError,'embedding training'):assert_uninspected_cases(self.tenant.pk,[case])
        swapped=copy.deepcopy(value)
        swapped['documents'][0]['source_group']='shipping'
        with self.assertRaisesMessage(ValueError,'previously protected'):training.protect_splits(self.project,swapped)
        # No exposed text or groups are stored as raw customer content.
        from modelanvil.rag.models import EmbeddingTrainingExposure
        self.assertFalse('reset password' in json.dumps(list(EmbeddingTrainingExposure.all_objects.values()),default=str))

    def test_registered_final_groups_and_prompts_cannot_train(self):
        from modelanvil.runners.models import EvaluationSuite,EvaluationSuiteVersion
        suite=EvaluationSuite.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Protected')
        EvaluationSuiteVersion.all_objects.create(tenant_id=self.tenant.pk,project=self.project,suite=suite,
            protected_role='protected_eval',cases=[{'source_group_id':'accounts','input_prompt':'Protected unrelated prompt'}])
        with self.assertRaisesMessage(ValueError,'Registered protected'):training.protect_splits(self.project,fixture())


from django.test import tag, TransactionTestCase
from django.conf import settings
from pathlib import Path
import os
import subprocess
import sys


@tag('pg')
@override_settings(ALLOWED_HOSTS=['testserver'])
class ActualEmbeddingCandidateTests(TransactionTestCase):
    def setUp(self):
        EmbeddingSplitTests.setUp(self)

    def test_real_cpu_weights_independent_export_private_serve_and_protected_roles(self):
        folder=tempfile.TemporaryDirectory(prefix='embedding-candidate-test-');self.addCleanup(folder.cleanup)
        self.enterContext(override_settings(MODELANVIL={**settings.MODELANVIL,'artifact_root':folder.name}))
        value=fixture();raw=json.dumps(value).encode()
        source=Artifact.all_objects.create(tenant_id=self.tenant.pk,project=self.project,storage_location_id='local',
            object_key='embedding-source/manifest.json',sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),media_type='application/json')
        upload_staged_artifact(source,io.BytesIO(raw))
        before=adapter.encode(['How do I reset a password?'])
        candidate=training.publish(project=self.project,source=source,name='Actually trained MiniLM',steps=2)
        self.assertNotEqual(candidate.space.model_revision,adapter.PINS['files']['model.safetensors']['sha256'])
        self.assertEqual(candidate.report['baseline']['held_out']['queries_total'],1)
        self.assertEqual(candidate.report['candidate']['held_out']['cutoff'],3)
        from modelanvil.rag.embedding_candidates import encode,checked
        import numpy as np
        vectors=encode(['How do I reset a password?'],candidate.space)
        self.assertEqual(vectors.shape,(1,384))
        self.assertFalse(np.allclose(vectors,before,atol=1e-7))
        self.assertTrue(np.allclose(before,adapter.encode(['How do I reset a password?']),atol=1e-6))
        self.assertTrue(np.allclose(vectors,encode(['How do I reset a password?'],candidate.space),atol=1e-6))
        from modelanvil.artifacts.storage import artifact_storage_backend
        backend=artifact_storage_backend();archive=Path(folder.name)/'downloaded-candidate.zip'
        with backend.open(self.tenant.pk,candidate.export.object_key) as stream:archive.write_bytes(stream.read())
        env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
        result=subprocess.run([sys.executable,'scripts/verify_embedding_export.py','--archive',str(archive),
            '--sha256',candidate.export_digest],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(result.stdout.strip().splitlines()[-1])['registry_used'])
        print('TASK30_ACTUAL '+json.dumps({'candidate_weight_sha256':candidate.space.model_revision,
            'export_sha256':candidate.export_digest,'report':candidate.report,'independent':json.loads(result.stdout.strip().splitlines()[-1])}))
        from rest_framework.test import APIClient
        from modelanvil.identity.models import ApiKey,generate_api_key,Role
        from modelanvil.jobs.models import WorkerPool,Worker
        from modelanvil.jobs.executor import execute_one
        from modelanvil.budgets.models import BudgetPolicy
        from modelanvil.rag.models import IndexVersion,EmbeddingSpace,DocumentChunk,ChunkEmbedding
        from modelanvil.rag import embedding_jobs as builds
        from modelanvil.runners.training.runtime import digest
        from django.utils import timezone
        secret,hashed=generate_api_key();ApiKey.objects.create(tenant=self.tenant,name='Candidate tests',role=Role.OWNER,secret_hash=hashed)
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+secret,HTTP_X_PROJECT_ID=str(self.project.pk))
        response=client.get(f'/api/v1/embedding-candidates/{candidate.candidate_id}/')
        self.assertEqual(response.status_code,200,response.content)
        response=client.post(f'/api/v1/embedding-spaces/{candidate.space.space_id}/encode/',{'texts':['A reset password link.']},format='json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['pins']['candidate_export_sha256'],candidate.export_digest)
        response=client.post('/api/v1/knowledge-bases/',{'name':'Actual embedding comparison'},format='json')
        self.assertEqual(response.status_code,201,response.content);kb=response.json()['knowledge_base_id']
        response=client.post(f'/api/v1/knowledge-bases/{kb}/index/',{'documents':[
            {'title':d['id'],'source_uri':'fixture:'+d['id'],'content':d['text']} for d in value['documents']],
            'chunk_size':100,'chunk_overlap':0},format='json')
        self.assertEqual(response.status_code,201,response.content)
        source_index=IndexVersion.all_objects.get(index_id=response.json()['index_id'])
        baseline=EmbeddingSpace.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Actual baseline',
            model_name=adapter.PINS['model'],model_revision=adapter.PINS['revision'],license_expression='apache-2.0',
            dimension=384,normalized=True,distance_metric='cosine',metadata={'profile_digest':digest(adapter.PINS)})
        pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='Actual candidate index pool',result_egress='envelope')
        worker=Worker.all_objects.create(tenant_id=self.tenant.pk,pool=pool,name='Actual encoder',slots=1,
            capabilities={'embedding_runtime':builds.runtime_digest()},last_heartbeat_at=timezone.now())
        policy=BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,name='Candidate index attempts',unit='embedding_attempts',period='lifetime',limit_amount=20)
        indexes=[]
        for i,space in enumerate([baseline,candidate.space]):
            response=client.post('/api/v1/embedding-builds/',{'source_index':str(source_index.index_id),'space':str(space.space_id),
                'pool':pool.pk,'budget_policy':str(policy.policy_id),'idempotency_key':f'candidate-index-{i}'},format='json')
            self.assertEqual(response.status_code,202,response.content)
            from modelanvil.rag.models import EmbeddingBuild
            build=EmbeddingBuild.all_objects.get(build_id=response.json()['build_id'])
            self.assertTrue(execute_one(worker,builds.embedding_executor)['committed'])
            build.index.refresh_from_db();self.assertEqual(build.index.status,'ready');indexes.append(build.index)
        self.assertNotEqual(indexes[0].embedding_space_id,indexes[1].embedding_space_id)
        self.assertEqual(ChunkEmbedding.all_objects.filter(space=baseline).count(),4)
        self.assertEqual(ChunkEmbedding.all_objects.filter(space=candidate.space).count(),4)
        judged=DocumentChunk.all_objects.get(document__source_uri='fixture:deliver',document__knowledge_base=source_index.knowledge_base)
        response=client.post(f'/api/v1/index-versions/{indexes[1].index_id}/comparisons/',{
            'baseline_index_id':str(indexes[0].index_id),'qrels_version':'protected-embedding-candidate-v1','modes':['dense'],'top_k':3,
            'cases':[{'query_id':'test-1','query':value['qrels'][1]['query'],'qrels':{str(judged.chunk_id):1}}]},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(len(response.json()['results']),2)
        self.assertEqual(len({row['qrels_digest'] for row in response.json()['results']}),1)
        with self.assertRaises(ValueError):encode(['word '*300],candidate.space)
        # Private candidate does not become available just because its space ID is known.
        team=self.project.team
        other=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,name='Other',slug='other')
        set_active_project(other.pk)
        with self.assertRaises(ValueError):checked(candidate.space)
        set_active_project(self.project.pk)
        original=candidate.space.dimension;candidate.space.dimension=768
        with self.assertRaises(ValueError):checked(candidate.space)
        candidate.space.dimension=original
        source.state='tombstoned';source.save()
        with self.assertRaises(ValueError):checked(candidate.space)
