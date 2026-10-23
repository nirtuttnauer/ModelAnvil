"""Actual local encoding plus Postgres publication, recovery and access boundaries."""
import os
import threading
from unittest.mock import patch
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase, tag, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.core.tenancy import reset_context
from modelanvil.identity.models import Tenant, Team, Project, ApiKey, Role, generate_api_key
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
from modelanvil.jobs.models import Worker, WorkerPool, Job, JobAttempt, claim_job, publish_outbox_batch, dispatch_topic
from modelanvil.jobs.executor import execute_one, execute_claim
from modelanvil.rag import embedding_adapter as adapter, embedding_jobs as builds
from modelanvil.rag.models import ChunkEmbedding, EmbeddingSpace, EmbeddingBuild, IndexVersion, KnowledgeBase
from modelanvil.runners.training.runtime import digest


@tag('pg')
@override_settings(ALLOWED_HOSTS=['testserver'])
class EmbeddingWorkerTests(TransactionTestCase):
    def setUp(self):
        reset_context()
        self.tenant=Tenant.objects.create(slug='embedding-tests',name='Embedding tests')
        team=Team.all_objects.create(tenant_id=self.tenant.pk,slug='team',name='Team')
        self.project=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,slug='one',name='One')
        self.other=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,slug='two',name='Two')
        secret,hashed=generate_api_key()
        ApiKey.objects.create(tenant=self.tenant,name='embedding-test',role=Role.OWNER,secret_hash=hashed)
        self.client=APIClient();self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret,HTTP_X_PROJECT_ID=str(self.project.pk))
        response=self.client.post('/api/v1/knowledge-bases/',{'name':'Frozen documents'},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.base=KnowledgeBase.all_objects.get(kb_id=response.json()['knowledge_base_id'])
        response=self.client.post(f'/api/v1/knowledge-bases/{self.base.kb_id}/index/',{'documents':[
            {'title':f'Source {i}','source_uri':f'fixture:{i}','content':f'The orange cat sleeps on the warm sofa. Source number {i}.'} for i in range(18)],'chunk_size':100,'chunk_overlap':0},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.source=IndexVersion.all_objects.get(index_id=response.json()['index_id'])
        self.space=EmbeddingSpace.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Pinned model',
            model_name=adapter.PINS['model'],model_revision=adapter.PINS['revision'],license_expression=adapter.PINS['license'],
            dimension=384,normalized=True,distance_metric='cosine',metadata={'profile_digest':digest(adapter.PINS)})
        self.pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='CPU embeddings',result_egress='envelope')
        self.worker=Worker.all_objects.create(tenant_id=self.tenant.pk,pool=self.pool,name='CPU encoder',slots=1,
            capabilities={'embedding_runtime':builds.runtime_digest()},last_heartbeat_at=timezone.now())
        self.policy=BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,name='Embedding attempts',period='lifetime',
            unit=builds.UNIT,limit_amount=30)

    def queue(self,key='build-1'):
        response=self.client.post('/api/v1/embedding-builds/',{'source_index':str(self.source.index_id),
            'space':str(self.space.space_id),'pool':self.pool.pk,'budget_policy':str(self.policy.policy_id),'idempotency_key':key},format='json')
        self.assertEqual(response.status_code,202,response.content)
        return EmbeddingBuild.all_objects.get(build_id=response.json()['build_id'])

    @staticmethod
    def vectors(texts):
        return adapter.validate_vectors([[1.]+[0.]*383 for _ in texts],len(texts))

    def assert_state(self,build,job,index):
        build.refresh_from_db();build.job.refresh_from_db();build.index.refresh_from_db()
        self.assertEqual(build.job.status,job);self.assertEqual(build.index.status,index)

    def test_actual_encoder_dimensions_norm_determinism_and_context_refusal(self):
        vectors=adapter.encode(['A cat rests on a sofa.','A dog runs in a park.'])
        self.assertEqual(vectors.shape,(2,384));adapter.validate_vectors(vectors,2)
        repeated=adapter.encode(['A cat rests on a sofa.'])[0]
        self.assertTrue(__import__('numpy').allclose(vectors[0],repeated,atol=1e-6))
        with self.assertRaisesMessage(ValueError,'256-token'):adapter.encode(['word '*300])
        with self.assertRaises(ValueError):adapter.validate_vectors([[0.]*384],1)
        with self.assertRaises(ValueError):adapter.validate_vectors([[float('nan')]*384],1)
        with self.assertRaises(ValueError):adapter.validate_vectors([[1.,0.]],1)

    def test_queue_is_async_idempotent_then_actual_pgvector_query_and_pca(self):
        build=self.queue();self.assertEqual(self.queue().pk,build.pk)
        self.assertEqual(ChunkEmbedding.all_objects.count(),0)
        self.assert_state(build,'queued','building')
        self.assertTrue(execute_one(self.worker,builds.embedding_executor)['committed'])
        self.assert_state(build,'succeeded','ready')
        self.assertEqual(ChunkEmbedding.all_objects.count(),18)
        self.assertEqual(build.completed_chunks,18)
        with connection.cursor() as cursor:
            cursor.execute('SELECT indexdef FROM pg_indexes WHERE indexname=%s',[f'embedding_space_{self.space.pk}_hnsw'])
            definition=cursor.fetchone()[0]
        self.assertIn('vector(384)',definition);self.assertIn('USING hnsw',definition);self.assertIn('WHERE (space_id =',definition)
        response=self.client.post(f'/api/v1/index-versions/{build.index.index_id}/query/',{'query':'A sleeping feline on a couch','mode':'dense','top_k':3},format='json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(len(response.json()['results']),3)
        self.assertEqual(response.json()['results'][0]['metadata']['query_embedding_source'],'pinned_local_cpu')
        self.assertEqual(response.json()['retrieval_config']['dense_search'],'hnsw')
        exact=self.client.post(f'/api/v1/index-versions/{build.index.index_id}/query/',{'query':'A sleeping feline on a couch','mode':'dense','top_k':3,'dense_search':'exact','ef_search':10},format='json')
        self.assertEqual(exact.status_code,200,exact.content)
        self.assertEqual(exact.json()['retrieval_config']['dense_search'],'exact')
        from modelanvil.rag.models import QueryTrace
        trace=QueryTrace.all_objects.get(trace_id=exact.json()['trace_id'])
        self.assertEqual(trace.retrieval_config,exact.json()['retrieval_config'])
        self.assertEqual(trace.retrieval_config['execution']['exact_fallback_used'],False)
        self.assertEqual(trace.retrieval_config['hnsw']['ef_search'],10)
        comparison=self.client.post(f'/api/v1/index-versions/{build.index.index_id}/comparisons/',{
            'baseline_index_id':str(self.source.index_id),'qrels_version':'real-encoder-control-v1','modes':['dense'],
            'cases':[{'query_id':'control','query':'sleeping cat','qrels':{self.source.configuration['chunk_ids'][0]:1}}]},format='json')
        self.assertEqual(comparison.status_code,201,comparison.content)
        self.assertEqual({row['mode'] for row in comparison.json()['results']},{'lexical','dense'})
        self.assertEqual(len({row['qrels_digest'] for row in comparison.json()['results']}),1)
        projection=self.client.post(f'/api/v1/index-versions/{build.index.index_id}/projection/',{},format='json')
        self.assertEqual(projection.status_code,200,projection.content)
        self.assertEqual(len(projection.json()['points']),18)
        reservation=BudgetReservation.all_objects.get(job_id=build.job.job_id)
        self.assertEqual(reservation.settled_amount,1)

    def test_cancel_after_checkpoint_and_resume_encodes_only_remaining_chunks(self):
        build=self.queue();calls=[]
        def encode(texts):
            calls.append(len(texts))
            if len(calls)==2:builds.cancel(build)
            return self.vectors(texts)
        with patch.object(adapter,'encode',side_effect=encode):execute_one(self.worker,builds.embedding_executor)
        self.assert_state(build,'cancelled','failed');self.assertEqual(ChunkEmbedding.all_objects.count(),16)
        builds.retry(build)
        with patch.object(adapter,'encode',side_effect=self.vectors) as encoder:execute_one(self.worker,builds.embedding_executor)
        self.assert_state(build,'succeeded','ready');self.assertEqual(len(encoder.call_args.args[0]),2)
        self.assertEqual(ChunkEmbedding.all_objects.count(),18)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=build.job.job_id).settled_amount,2)

    def test_bad_dimension_failure_and_fenced_attempt_never_publish_ready(self):
        build=self.queue()
        with patch.object(adapter,'encode',return_value=[[1.,0.]]*16):execute_one(self.worker,builds.embedding_executor)
        self.assert_state(build,'failed','failed')
        builds.retry(build);descriptor=claim_job(self.worker)
        Job.all_objects.filter(pk=build.job_id).update(fencing_token='new-owner')
        outcome=execute_claim(self.worker,descriptor,builds.embedding_executor)
        self.assertFalse(outcome['committed']);build.index.refresh_from_db();self.assertEqual(build.index.status,'building')

    def test_publication_rechecks_source_and_checksum_and_generic_job_routes_are_closed(self):
        build=self.queue();descriptor=claim_job(self.worker)
        def corrupt_after_encode(desc,context):
            builds.embedding_executor(desc,context)
            ChunkEmbedding.all_objects.filter(space=self.space).update(vector_digest='0'*64)
        with patch.object(adapter,'encode',side_effect=self.vectors):execute_claim(self.worker,descriptor,corrupt_after_encode)
        self.assert_state(build,'failed','failed')
        self.assertFalse(build.index.configuration['embeddings_generated'])
        for method,path,data in [('patch',f'/api/v1/jobs/{build.job.job_id}/',{'name':'override'}),
                                 ('post',f'/api/v1/jobs/{build.job.job_id}/cancel/',{}),
                                 ('delete',f'/api/v1/jobs/{build.job.job_id}/',{})]:
            response=getattr(self.client,method)(path,data,format='json')
            self.assertIn(response.status_code,(400,409),response.content)
        self.client.credentials(HTTP_AUTHORIZATION=self.client._credentials['HTTP_AUTHORIZATION'],HTTP_X_PROJECT_ID=str(self.other.pk))
        self.assertEqual(self.client.get(f'/api/v1/embedding-builds/{build.build_id}/').status_code,404)
        self.assertEqual(self.client.get(f'/api/v1/jobs/{build.job.job_id}/').status_code,404)
        self.assertEqual(self.client.post(f'/api/v1/embedding-spaces/{self.space.space_id}/encode/',{'texts':['private source']},format='json').status_code,404)
        self.assertEqual(self.client.get(f'/api/v1/index-versions/{build.index.index_id}/').status_code,404)

    def test_cancel_queued_leaves_no_ready_index_and_zero_attempt_charge(self):
        build=self.queue();builds.cancel(build);self.assert_state(build,'cancelled','failed')
        self.assertEqual(BudgetReservation.all_objects.get(job_id=build.job.job_id).settled_amount,0)
        self.assertFalse(execute_one(self.worker,builds.embedding_executor)['claimed'])

    @skipUnless(os.environ.get('RABBITMQ_URL'),'Requires the real RabbitMQ evidence service')
    def test_registered_profile_real_outbox_broker_worker_and_vector_publication(self):
        from modelanvil.jobs.setup import observe_local_worker
        from modelanvil.jobs.broker import WorkerBrokerConsumer
        from modelanvil.jobs.management.commands.flush_outbox import RabbitPublisher
        response=self.client.post('/api/v1/workers/setup/',{'profile':'cpu-embeddings','pool':self.pool.name,'worker_name':'Broker encoder'},format='json')
        self.assertEqual(response.status_code,201,response.content)
        self.assertIn('consume_worker',response.json()['startup_command'])
        worker=Worker.all_objects.select_related('pool').get(pk=response.json()['worker_id'])
        observer=lambda:observe_local_worker(worker,'cpu-embeddings',response.json()['worker_token'])
        observer();build=self.queue()
        consumer=WorkerBrokerConsumer(worker,dispatch_topic(self.tenant.pk,self.pool.queue_name,self.pool.name),builds.embedding_executor,observer=observer)
        errors=[]
        def run():
            try:consumer.run()
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=run,daemon=True);thread.start()
        publisher=RabbitPublisher(os.environ['RABBITMQ_URL'])
        try:
            self.assertTrue(consumer.wait_until_ready(20),errors)
            self.assertGreater(publish_outbox_batch(publisher),0)
            import time
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                build.job.refresh_from_db()
                if build.job.status in ('succeeded','failed'):break
                time.sleep(.1)
            self.assert_state(build,'succeeded','ready')
            self.assertEqual(build.job.attempt_count,1)
            self.assertEqual(ChunkEmbedding.all_objects.count(),18)
        finally:
            publisher.close();consumer.stop();thread.join(20)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_attempt_cap_and_new_space_never_reuse_another_space_cache(self):
        build=self.queue()
        for attempt in range(3):
            with patch.object(adapter,'encode',side_effect=ValueError('controlled failure')):
                outcome=execute_one(self.worker,builds.embedding_executor)
            self.assertEqual(outcome['status'],'failed');self.assert_state(build,'failed','failed')
            if attempt<2:builds.retry(build)
        with self.assertRaisesMessage(ValueError,'remaining attempts'):builds.retry(build)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=build.job.job_id).settled_amount,3)
        # A separate registered space owns independent chunk vectors, even with
        # identical model weights. No dimension/runtime cache is silently reused.
        first=self.queue('cache-one')
        with patch.object(adapter,'encode',side_effect=self.vectors):execute_one(self.worker,builds.embedding_executor)
        old_space=self.space
        self.space=EmbeddingSpace.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Second pinned space',
            model_name=old_space.model_name,model_revision=old_space.model_revision,license_expression=old_space.license_expression,
            dimension=384,normalized=True,distance_metric='cosine',metadata=old_space.metadata)
        second=self.queue('cache-two')
        self.assertEqual(ChunkEmbedding.all_objects.filter(space=self.space).count(),0)
        with patch.object(adapter,'encode',side_effect=self.vectors) as encoder:execute_one(self.worker,builds.embedding_executor)
        self.assertEqual(sum(len(call.args[0]) for call in encoder.call_args_list),18)
        self.assertNotEqual(first.index_id,second.index_id);self.assertEqual(ChunkEmbedding.all_objects.count(),36)
        self.space.dimension=2;self.space.save(update_fields=['dimension'])
        with self.assertRaisesMessage(ValueError,'immutable'):builds.space_pins(self.space)
