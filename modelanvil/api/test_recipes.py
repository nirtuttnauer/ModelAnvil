"""Recipe versions, real deterministic jobs, preview gates and fenced recovery."""
import io
import json
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from modelanvil.api import test_specialists as fixtures
from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.data import recipe_jobs
from modelanvil.data.models import RecipeRun
from modelanvil.data.test_recipes import definition
from modelanvil.jobs.executor import execute_one, ExecutionContext
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job, commit_result, reconcile_expired_leases
from modelanvil.runners.model_catalog import _store


class RecipeApiTests(TestCase):
    version=fixtures.SpecialistApiTests.version
    def setUp(self):
        fixtures.SpecialistApiTests.setUp(self)
        self.pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='recipes')
        self.worker=Worker.all_objects.create(tenant_id=self.tenant.pk,pool=self.pool,name='recipes',
            capabilities={'recipe_runtime':recipe_jobs.runtime_digest(),'recipe_device':'cpu','recipe_generation':True})
        self.policy=BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,name='recipe quota',unit='recipe_attempts',period='lifetime',limit_amount=100)
        self.source=_store(io.BytesIO(json.dumps([{'text':'Maintenance window starts at 14:30 UTC.'},
            {'text':'Power checks passed for the primary server.'},{'text':'Document retention is thirty days.'}]).encode()),
            tenant=self.tenant.pk,project=self.project.pk,name='source.json',media_type='application/json')
        r=self.client.post('/api/v1/recipes/',definition(),format='json');self.assertEqual(r.status_code,201,r.data);self.recipe=r.data
        self.body={'recipe':self.recipe['artifact_id'],'sources':{'source':self.source['artifact_id']},'device':'cpu',
            'pool':self.pool.pk,'budget_policy':str(self.policy.policy_id),'idempotency_key':'preview','preview':True}

    def submit(self):
        r=self.client.post('/api/v1/recipes/runs/',self.body,format='json');self.assertEqual(r.status_code,202,r.data)
        return RecipeRun.all_objects.get(run_id=r.data['run_id'])

    def complete(self):
        result=execute_one(self.worker,recipe_jobs.recipe_executor)
        self.assertTrue(result['committed'],result);self.assertEqual(result['status'],'succeeded',result)

    def test_stale_draining_and_zero_slot_workers_cannot_reserve_recipe_quota(self):
        for changes in ({'last_heartbeat_at':timezone.now()-timezone.timedelta(seconds=61)},
                        {'drain_requested':True}, {'slots':0}):
            Worker.all_objects.filter(pk=self.worker.pk).update(last_heartbeat_at=None, drain_requested=False, slots=1)
            Worker.all_objects.filter(pk=self.worker.pk).update(**changes)
            response=self.client.post('/api/v1/recipes/runs/',self.body,format='json')
            self.assertEqual(response.status_code,400,response.json())
            self.assertEqual(Job.all_objects.count(),0)
            self.assertEqual(BudgetReservation.all_objects.count(),0)

    def test_version_export_is_verified_and_identical_import_reuses_version(self):
        r=self.client.post('/api/v1/recipes/',definition(),format='json');self.assertEqual(r.data,self.recipe)
        exported=self.client.get(f'/api/v1/recipes/versions/{self.recipe["artifact_id"]}/')
        self.assertEqual(exported.data['definition'],definition())
        self.assertEqual(self.client.patch(f'/api/v1/recipes/{self.recipe["artifact_id"]}/',{},format='json').status_code,405)

    def test_preview_gate_full_publication_idempotency_and_source_groups(self):
        preview=self.submit();self.assertEqual(self.submit().pk,preview.pk);self.complete()
        self.assertEqual(DatasetRevision.all_objects.count(),0)
        preview.refresh_from_db();self.assertEqual(preview.result['row_count'],3)
        target=Dataset.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='recipe output')
        self.body.update(preview=False,dataset=str(target.dataset_id),preview_run=str(preview.run_id),idempotency_key='full')
        self.assertEqual(self.client.post('/api/v1/recipes/runs/',self.body,format='json').status_code,400)
        self.body['reviewed_preview']=True
        run=self.submit();self.complete();run.refresh_from_db()
        self.assertEqual(DatasetRevision.all_objects.count(),1);self.assertEqual(run.result['row_count'],3)
        self.assertEqual(self.submit().pk,run.pk);self.assertEqual(DatasetRevision.all_objects.count(),1)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.job.job_id).settled_amount,1)
        report=recipe_jobs.read_json(run.result['report'],self.tenant.pk,self.project.pk)
        self.assertEqual(len({r['source_group_id'] for r in report['rows']}),1)
        attempt=run.job.attempts.first();self.assertFalse(commit_result(attempt,attempt.fencing_token,'succeeded'))
        self.assertEqual(DatasetRevision.all_objects.count(),1)

    def test_queue_cancel_refunds_unused_quota_and_scope_is_inherited(self):
        run=self.submit()
        self.assertEqual(self.client.post(f'/api/v1/recipes/runs/{run.run_id}/cancel/').status_code,200)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.job.job_id).settled_amount,0)
        self.assertEqual(self.client.patch(f'/api/v1/jobs/{run.job.job_id}/',{'name':'changed'},format='json').status_code,400)
        self.assertEqual(self.client.delete(f'/api/v1/jobs/{run.job.job_id}/').status_code,400)
        run.project=self.other;run.save()
        self.assertEqual(self.client.get(f'/api/v1/recipes/runs/{run.run_id}/').status_code,404)
        self.assertEqual(self.client.get(f'/api/v1/jobs/{run.job.job_id}/').status_code,404)

    def test_expired_complete_checkpoint_replays_without_duplicate_usage(self):
        run=self.submit();descriptor=claim_job(self.worker)
        attempt=JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
        recipe_jobs.recipe_executor(descriptor,ExecutionContext(attempt,descriptor['fencing_token']))
        JobAttempt.all_objects.filter(pk=attempt.pk).update(lease_expires_at=timezone.now()-timezone.timedelta(seconds=1))
        self.assertEqual(reconcile_expired_leases(),1);self.assertFalse(commit_result(attempt,descriptor['fencing_token'],'succeeded'))
        self.complete();run.refresh_from_db()
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.job.job_id).settled_amount,1)
        self.assertEqual(UsageEvent.all_objects.count(),1)

    def test_partial_row_checkpoint_reuses_completed_generation(self):
        graph=definition();graph['steps'].insert(3,{'id':'generate','type':'generate','input':'clean','output':'text','max_tokens':32,'seed':42})
        graph['steps'][-1]['input']='generate'
        self.recipe=self.client.post('/api/v1/recipes/',graph,format='json').data
        self.body.update(recipe=self.recipe['artifact_id'],model=str(self.laya.model_version_id))
        with patch.object(recipe_jobs.inference,'snapshot',return_value={'format':'fixture','files':{}}), \
             patch.object(recipe_jobs.inference,'local_session') as session, \
             patch.object(recipe_jobs,'local_generate') as generation:
            session.return_value.__enter__.return_value={}
            good={'text':'Generated engineering maintenance note.', 'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18},'finish_reason':'stop'}
            generation.side_effect=[good,RuntimeError('worker interruption')]
            run=self.submit();self.assertEqual(execute_one(self.worker,recipe_jobs.recipe_executor)['status'],'failed')
            run.refresh_from_db();self.assertEqual(sum(k.startswith('generate/') for k in run.checkpoints),1)
            self.assertEqual(self.client.post(f'/api/v1/recipes/runs/{run.run_id}/retry/').status_code,200)
            generation.side_effect=None;generation.return_value=good
            self.complete();self.assertEqual(generation.call_count,4) # completed first row was reused
            self.assertEqual(BudgetReservation.all_objects.get(job_id=run.job.job_id).settled_amount,2)

    def generation_recipe(self,output='text'):
        graph=definition();graph['steps'].insert(3,{'id':'generate','type':'generate','input':'clean','output':output,'max_tokens':32,'seed':42})
        graph['steps'][-1]['input']='generate'
        version=self.client.post('/api/v1/recipes/',graph,format='json').data
        self.body.update(recipe=version['artifact_id'],model=str(self.laya.model_version_id))

    def test_protected_source_groups_are_excluded_before_model_loading(self):
        self.generation_recipe()
        rows=recipe_jobs.source_rows(self.source,{'format':'json'},self.tenant.pk,self.project.pk)
        protected=_store(io.BytesIO((json.dumps(rows[0])+'\n').encode()),tenant=self.tenant.pk,project=self.project.pk,
            name='protected.jsonl',media_type='application/x-ndjson')
        self.body['protected_sources']=[protected['artifact_id']]
        with patch.object(recipe_jobs.inference,'snapshot',return_value={'format':'fixture','files':{}}),patch.object(recipe_jobs.inference,'local_session') as load:
            run=self.submit();self.complete();load.assert_not_called()
        run.refresh_from_db();self.assertEqual(run.result['row_count'],0);self.assertEqual(run.result['rejected_count'],3)
        self.assertEqual(DatasetRevision.all_objects.count(),0)

    def test_invalid_generated_json_has_rejection_and_usage_and_cannot_publish(self):
        self.generation_recipe('json')
        with patch.object(recipe_jobs.inference,'snapshot',return_value={'format':'fixture','files':{}}), \
             patch.object(recipe_jobs.inference,'local_session'),patch.object(recipe_jobs,'local_generate',return_value={
                 'text':'{unfinished', 'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18},'finish_reason':'length'}):
            run=self.submit();self.complete();run.refresh_from_db()
            self.assertEqual(run.result['row_count'],0);self.assertEqual(run.result['usage']['total_tokens'],54)
            report=recipe_jobs.read_json(run.result['report'],self.tenant.pk,self.project.pk)
            self.assertTrue(all(r['reason']=='invalid_json_output' for r in report['rejected']))
            dataset=Dataset.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='refused output')
            self.body.update(preview=False,preview_run=str(run.run_id),dataset=str(dataset.dataset_id),reviewed_preview=True,idempotency_key='full')
            self.assertEqual(self.client.post('/api/v1/recipes/runs/',self.body,format='json').status_code,400)
            self.assertEqual(BudgetReservation.all_objects.count(),1)

    def test_idempotency_cannot_switch_quota_or_pool(self):
        self.submit()
        policy=BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,name='other recipe quota',unit='recipe_attempts',period='lifetime',limit_amount=100)
        self.body['budget_policy']=str(policy.policy_id)
        self.assertEqual(self.client.post('/api/v1/recipes/runs/',self.body,format='json').status_code,400)
        self.assertEqual(BudgetReservation.all_objects.count(),1)

    def test_corrupt_recipe_checkpoint_is_refused_before_reexecution(self):
        run=self.submit();descriptor=claim_job(self.worker);attempt=JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
        recipe_jobs.recipe_executor(descriptor,ExecutionContext(attempt,descriptor['fencing_token']));run.refresh_from_db()
        run.checkpoints['$result']['sha256']='f'*64;run.save()
        JobAttempt.all_objects.filter(pk=attempt.pk).update(lease_expires_at=timezone.now()-timezone.timedelta(seconds=1))
        reconcile_expired_leases()
        self.assertEqual(execute_one(self.worker,recipe_jobs.recipe_executor)['status'],'failed')
        self.assertEqual(DatasetRevision.all_objects.count(),0);self.assertEqual(UsageEvent.all_objects.count(),1)

    def test_accepted_json_is_canonical_and_duplicate_calls_keep_measured_usage(self):
        self.generation_recipe('json')
        with patch.object(recipe_jobs.inference,'snapshot',return_value={'format':'fixture','files':{}}), \
             patch.object(recipe_jobs.inference,'local_session'),patch.object(recipe_jobs,'local_generate',return_value={
                 'text':'{"status":"ready","checks":["power"]}', 'usage':{'prompt_tokens':10,'completion_tokens':8,'total_tokens':18},'finish_reason':'stop'}):
            run=self.submit();self.complete();run.refresh_from_db()
            self.assertEqual(run.result['row_count'],1)
            self.assertEqual(run.result['usage']['completed_generation_calls'],3)
            self.assertEqual(run.result['usage']['total_tokens'],54)
            report=recipe_jobs.read_json(run.result['report'],self.tenant.pk,self.project.pk)
            self.assertEqual(report['rows'][0]['blocks'][0]['value'],{'status':'ready','checks':['power']})
            from contracts import validate_envelope
            validate_envelope(report['rows'][0])
            self.assertEqual(len(report['rejected']),2)

    def test_runtime_failure_fails_attempt_instead_of_rejecting_source_rows(self):
        self.generation_recipe()
        with patch.object(recipe_jobs.inference,'snapshot',return_value={'format':'fixture','files':{}}), \
             patch.object(recipe_jobs.inference,'local_session'), \
             patch.object(recipe_jobs,'local_generate',side_effect=ValueError('Context admission refused')):
            run=self.submit()
            self.assertEqual(execute_one(self.worker,recipe_jobs.recipe_executor)['status'],'failed')
        run.refresh_from_db()
        self.assertEqual(run.result,{})
        self.assertFalse(any(k.startswith('generate/') for k in run.checkpoints))
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.job.job_id).settled_amount,1)

    def test_changed_model_withholds_generated_row_before_checkpoint(self):
        self.generation_recipe()
        def changed(*args):
            type(self.laya).all_objects.filter(pk=self.laya.pk).update(metadata={'changed':True})
            return {'text':'must not publish','usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},'finish_reason':'stop'}
        with patch.object(recipe_jobs.inference,'snapshot',return_value={'format':'fixture','files':{}}), \
             patch.object(recipe_jobs.inference,'local_session'),patch.object(recipe_jobs,'local_generate',side_effect=changed):
            run=self.submit()
            self.assertEqual(execute_one(self.worker,recipe_jobs.recipe_executor)['status'],'failed')
        run.refresh_from_db()
        self.assertFalse(any(k.startswith('generate/') for k in run.checkpoints))
        self.assertFalse(DatasetRevision.all_objects.exists())

    def test_actual_cpu_reference_model_generates_measured_preview(self):
        from modelanvil.runners.local_execution import initialize_character_base
        _,_,version=initialize_character_base(tenant=self.tenant.pk,project=self.project.pk,name='Actual recipe CPU',seed=42)
        graph=definition()
        graph['steps'].insert(3,{'id':'generate','type':'generate','input':'clean','output':'text','max_tokens':4,'seed':42})
        graph['steps'][-1]['input']='generate'
        self.body.update(recipe=self.client.post('/api/v1/recipes/',graph,format='json').data['artifact_id'],model=str(version.model_version_id))
        run=self.submit();self.complete();run.refresh_from_db()
        self.assertEqual(run.result['usage']['completed_generation_calls'],3)
        self.assertGreater(run.result['usage']['completion_tokens'],0)
        self.assertEqual(run.frozen['model_snapshot']['format'],'cpu-reference')
        self.assertTrue(run.frozen['model_snapshot']['registered_identity'])
