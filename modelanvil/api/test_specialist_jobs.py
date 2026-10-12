"""Durable specialist admission, recovery, quota and publication fences."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from contracts import validate_envelope
from modelanvil.api import test_specialists as fixtures
from modelanvil.artifacts.models import Artifact, Dataset, LineageEdge
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.jobs.executor import ExecutionContext, execute_one
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job, commit_result, reconcile_expired_leases
from modelanvil.runners.models import InferenceRequest
from modelanvil.runners.specialist_jobs import cancel, runtime_digest, specialist_executor, save_page, read_pages


class DurableSpecialistTests(TestCase):
    setUp = fixtures.SpecialistApiTests.setUp
    version = fixtures.SpecialistApiTests.version
    upload_image = fixtures.SpecialistApiTests.upload_image

    def setup_job(self, **changes):
        self.pool = WorkerPool.all_objects.create(tenant_id=self.tenant.pk, name='specialist')
        self.worker = Worker.all_objects.create(tenant_id=self.tenant.pk, name='specialist', pool=self.pool,
            capabilities={'specialist_runtime':runtime_digest(), 'specialist_device':'mlx:0'})
        self.policy = BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk, name='attempt quota',
            period='lifetime', unit='specialist_attempts', limit_amount=10)
        self.body = {'kind':'ocr', 'request':{'model':str(self.model.model_version_id), 'image_artifact':self.upload_image()},
            'pool':self.pool.pk, 'budget_policy':str(self.policy.policy_id), 'idempotency_key':'first'}
        self.body.update(changes)
        self.pin_patch = patch('modelanvil.runners.specialists.snapshot', return_value={'files':{}})
        self.pin_patch.start(); self.addCleanup(self.pin_patch.stop)
        return self.submit()

    def submit(self):
        return self.client.post('/api/v1/specialists/jobs/', self.body, format='json')

    def record(self, response):
        self.assertEqual(response.status_code, 202, response.data)
        return InferenceRequest.all_objects.get(request_id=response.data['request_id'])

    def result(self):
        return {'text':'Invoice 1042', 'pages':[{'page':1, 'text':'Invoice 1042', 'image_dimensions':[900,350],
            'regions':[{'region_id':'page-1-region-1', 'order':1, 'label':'text', 'confidence':.92,
                'box':[40,90,260,135], 'coordinate_system':'normalized_page_rgb_pixels_xyxy',
                'crop_sha256':'c'*64, 'text':'Invoice 1042'}]}], 'image_dimensions':[900,350],
            'device':'mlx:0', 'usage':{'input_tokens':400,'output_tokens':8}, 'elapsed_seconds':2,
            'provenance':{'source':{}, 'snapshot_sha256':'b'*64, 'files':{}}}

    def page_result(self):
        return {'page':{'page':1,'text':'Invoice 1042','image_dimensions':[900,350], 'raster_sha256':'a'*64},
            'usage':{'input_tokens':400,'output_tokens':8,'total_tokens':408,'peak_memory_gb':2.4},
            'rasterization':{'source_format':'pdf','page_count':2}, 'runtime_versions':{}, 'finish_reason':'stop'}

    @patch('modelanvil.runners.specialists.execute')
    def test_page_checkpoint_survives_interruption_and_is_supplied_to_retry(self, execute):
        record=self.record(self.setup_job())
        def first(*args, **kwargs):
            kwargs['checkpoint_page'](self.page_result())
            raise ValueError('interruption after page one')
        execute.side_effect=first
        self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'failed')
        record.refresh_from_db();refs=read_pages(record);self.assertEqual(set(refs),{'1'})
        poll=self.client.get(f'/api/v1/specialists/jobs/{record.request_id}/')
        self.assertEqual(poll.data['completed_pages'],[1]);self.assertEqual(poll.data['page_count'],2)
        self.assertFalse(Artifact.all_objects.filter(metadata__kind='ocr_dataset_input').exists())
        self.assertEqual(self.client.post(f'/api/v1/specialists/jobs/{record.request_id}/retry/').status_code,200)
        def second(*args, **kwargs):
            self.assertEqual(kwargs['resume_pages'],refs)
            return self.result()
        execute.side_effect=second
        self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'succeeded')
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,2)

    def test_stale_worker_cannot_replace_a_saved_page(self):
        record=self.record(self.setup_job());descriptor=claim_job(self.worker)
        attempt=JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id']);context=ExecutionContext(attempt,descriptor['fencing_token'])
        save_page(context,self.page_result());save_page(context,self.page_result())
        self.assertEqual(Artifact.all_objects.filter(metadata__kind='ocr_page_checkpoint').count(),1)
        self.expire(descriptor)
        with self.assertRaisesMessage(ValueError,'fenced out'):
            save_page(context,self.page_result())
        record.refresh_from_db();self.assertEqual(set(read_pages(record)),{'1'})

    def test_page_checkpoint_identity_and_checksum_are_verified(self):
        record=self.record(self.setup_job());descriptor=claim_job(self.worker)
        context=ExecutionContext(JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id']),descriptor['fencing_token'])
        save_page(context,self.page_result());record.refresh_from_db()
        record.configuration['pages']['1']['sha256']='f'*64
        with self.assertRaises(ValueError):read_pages(record)

    def expire(self, descriptor):
        JobAttempt.all_objects.filter(attempt_id=descriptor['attempt_id']).update(lease_expires_at=timezone.now()-timezone.timedelta(seconds=1))
        Job.all_objects.filter(job_id=descriptor['job_id']).update(lease_expires_at=timezone.now()-timezone.timedelta(seconds=1))
        self.assertEqual(reconcile_expired_leases(), 1)

    def test_idempotency_freezes_inputs_and_one_reservation(self):
        r = self.setup_job(); self.record(r)
        self.assertEqual(self.submit().data, r.data)
        self.assertEqual(Job.all_objects.count(),1); self.assertEqual(BudgetReservation.all_objects.get().estimated_amount,3)
        self.body['request']['max_tokens']=256
        self.assertEqual(self.submit().status_code,400)
        self.assertEqual(InferenceRequest.all_objects.count(),1)

    def test_exact_worker_and_quota_required_before_queue(self):
        r = self.setup_job(); self.record(r)
        self.body['idempotency_key']='new'
        self.worker.capabilities={'specialist_runtime':'wrong','specialist_device':'mlx:0'}; self.worker.save()
        self.assertEqual(self.submit().status_code,400)
        self.worker.capabilities={'specialist_runtime':runtime_digest(),'specialist_device':'mlx:0'}; self.worker.save()
        self.policy.limit_amount=3; self.policy.save()
        self.assertEqual(self.submit().status_code,400)
        self.assertEqual(Job.all_objects.count(),1)

    @patch('modelanvil.runners.specialists.execute')
    def test_runtime_change_refuses_execution_before_usage_or_publication(self, execute):
        record=self.record(self.setup_job())
        with patch('modelanvil.runners.specialist_jobs.runtime_digest',return_value='f'*64):
            self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'failed')
        execute.assert_not_called()
        self.assertFalse(UsageEvent.all_objects.exists())
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,0)
        record.refresh_from_db();self.assertEqual(record.status,'failed')

    @patch('modelanvil.runners.specialists.execute')
    def test_success_commits_region_geometry_once_and_measured_usage(self, execute):
        record=self.record(self.setup_job()); execute.return_value=self.result()
        page=execute.return_value['pages'][0]
        page['regions'].append({**page['regions'][0], 'region_id':'page-1-region-2', 'order':2,
            'text':'Total: 38.50 USD', 'box':[40,140,330,185]})
        page['text'] += '\n\nTotal: 38.50 USD'
        outcome=execute_one(self.worker,specialist_executor)
        self.assertEqual(outcome['status'],'succeeded'); self.assertTrue(outcome['committed'])
        record.refresh_from_db(); self.assertEqual(record.status,'completed')
        self.assertEqual(UsageEvent.all_objects.count(),1)
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,1)
        poll=self.client.get(f'/api/v1/specialists/jobs/{record.request_id}/')
        self.assertEqual(poll.status_code,200,poll.data); result=poll.data['result']
        validate_envelope(result['envelope'])
        self.assertEqual(result['envelope']['blocks'][0]['location']['coordinates'],[40,90,260,135])
        self.assertEqual(len(result['envelope']['blocks']),2)
        self.assertEqual(LineageEdge.all_objects.count(),2)
        dataset=Dataset.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='ordered regions')
        published=self.client.post(f'/api/v1/datasets/{dataset.dataset_id}/prepare/',
            {'input_artifact_id':result['output_artifact']['artifact_id'], 'chunk_characters':None,'detect':True,'dedup':True},format='json')
        self.assertEqual(published.status_code,201,published.data)
        self.assertEqual(published.data['row_count'],1)
        attempt=JobAttempt.all_objects.get()
        lineage_count=LineageEdge.all_objects.count()
        self.assertFalse(commit_result(attempt,attempt.fencing_token,'succeeded'))
        self.assertEqual(LineageEdge.all_objects.count(),lineage_count)

    def test_queued_cancel_settles_zero_without_executing(self):
        record=self.record(self.setup_job())
        r=self.client.post(f'/api/v1/specialists/jobs/{record.request_id}/cancel/')
        self.assertEqual(r.status_code,200); self.assertEqual(r.data['status'],'cancelled')
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,0)
        self.assertEqual(execute_one(self.worker,specialist_executor),{'claimed':False})

    @patch('modelanvil.runners.specialists.execute')
    def test_running_cancel_reaps_before_publication(self, execute):
        record=self.record(self.setup_job())
        def stop(*args, **kwargs):
            cancel(record)
            self.assertFalse(kwargs['context'].heartbeat())
            raise ValueError('cancelled')
        execute.side_effect=stop
        self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'interrupted')
        record.refresh_from_db(); self.assertEqual(record.status,'cancelled')
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,1)
        self.assertFalse(Artifact.all_objects.filter(metadata__kind='ocr_dataset_input').exists())

    @patch('modelanvil.runners.specialists.execute')
    def test_expired_worker_checkpoint_recovers_without_duplicate_compute_or_charges(self, execute):
        record=self.record(self.setup_job()); execute.return_value=self.result()
        descriptor=claim_job(self.worker)
        attempt=JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
        specialist_executor(descriptor,ExecutionContext(attempt,descriptor['fencing_token']))
        self.expire(descriptor)
        self.assertFalse(commit_result(attempt,descriptor['fencing_token'],'succeeded'))
        self.assertFalse(Artifact.all_objects.filter(metadata__kind='ocr_dataset_input').exists())
        self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'succeeded')
        self.assertEqual(execute.call_count,1); self.assertEqual(UsageEvent.all_objects.count(),1)
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,1)
        record.refresh_from_db(); self.assertEqual(record.status,'completed')

    @patch('modelanvil.runners.specialists.execute')
    def test_failed_attempt_retry_reclaims_unused_quota(self, execute):
        record=self.record(self.setup_job()); execute.side_effect=ValueError('unsupported input')
        self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'failed')
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,1)
        self.assertEqual(self.client.post(f'/api/v1/specialists/jobs/{record.request_id}/retry/').status_code,200)
        execute.side_effect=None; execute.return_value=self.result()
        self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'succeeded')
        self.assertEqual(UsageEvent.all_objects.count(),2)
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,2)

    @patch('modelanvil.runners.specialists.execute')
    def test_cancel_after_checkpoint_prevents_publication(self, execute):
        record=self.record(self.setup_job()); execute.return_value=self.result()
        descriptor=claim_job(self.worker); attempt=JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
        specialist_executor(descriptor,ExecutionContext(attempt,descriptor['fencing_token']))
        cancel(record)
        self.assertTrue(commit_result(attempt,descriptor['fencing_token'],'succeeded'))
        record.refresh_from_db(); self.assertEqual(record.status,'cancelled')
        self.assertFalse(Artifact.all_objects.filter(metadata__kind='ocr_dataset_input').exists())
        self.assertIsNone(self.client.get(f'/api/v1/specialists/jobs/{record.request_id}/').data['result'])

    def test_job_apis_do_not_expose_another_project_or_allow_mutation(self):
        record=self.record(self.setup_job())
        self.assertEqual(self.client.patch(f'/api/v1/jobs/{record.configuration["job_id"]}/',{'name':'mutated'},format='json').status_code,400)
        self.assertEqual(self.client.post(f'/api/v1/jobs/{record.configuration["job_id"]}/cancel/').status_code,400)
        self.assertEqual(self.client.delete(f'/api/v1/jobs/{record.configuration["job_id"]}/').status_code,400)
        record.project=self.other; record.save()
        self.assertEqual(self.client.get(f'/api/v1/specialists/jobs/{record.request_id}/').status_code,404)
        self.assertEqual(self.client.get('/api/v1/specialists/jobs/').data,[])
        self.assertEqual(self.client.get(f'/api/v1/jobs/{record.configuration["job_id"]}/').status_code,404)

    @patch('modelanvil.runners.specialists.execute')
    def test_policy_change_prevents_fenced_result_publication(self, execute):
        self.record(self.setup_job()); execute.return_value=self.result()
        descriptor=claim_job(self.worker); attempt=JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
        specialist_executor(descriptor,ExecutionContext(attempt,descriptor['fencing_token']))
        self.pool.result_egress='metadata_only'; self.pool.save()
        with self.assertRaisesMessage(ValueError,'egress policy'):
            commit_result(attempt,descriptor['fencing_token'],'succeeded')
        self.assertFalse(Artifact.all_objects.filter(metadata__kind='ocr_dataset_input').exists())

    @patch('modelanvil.runners.specialists.execute')
    def test_corrupt_checkpoint_is_refused(self, execute):
        record=self.record(self.setup_job()); execute.return_value=self.result()
        descriptor=claim_job(self.worker); attempt=JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
        specialist_executor(descriptor,ExecutionContext(attempt,descriptor['fencing_token']))
        record.refresh_from_db()
        record.configuration['checkpoint']['sha256']='f'*64; record.save()
        self.expire(descriptor)
        self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'failed')
        self.assertEqual(execute.call_count,1)
        self.assertFalse(Artifact.all_objects.filter(metadata__kind='ocr_dataset_input').exists())

    @patch('modelanvil.runners.specialists.execute', side_effect=ValueError('invalid source'))
    def test_retry_is_bounded_to_three_claims_and_charges_each_execution_once(self, execute):
        record=self.record(self.setup_job())
        for number in range(3):
            self.assertEqual(execute_one(self.worker,specialist_executor)['status'],'failed')
            response=self.client.post(f'/api/v1/specialists/jobs/{record.request_id}/retry/')
            self.assertEqual(response.status_code,200 if number < 2 else 400)
        self.assertEqual(execute.call_count,3); self.assertEqual(UsageEvent.all_objects.count(),3)
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount,3)

    def test_supervised_child_is_killed_and_reaped_on_lease_loss(self):
        from modelanvil.runners import specialists
        from modelanvil.device_admission import device_lease
        actual_popen=subprocess.Popen; children=[]
        def spawn(*args, **kwargs):
            child=actual_popen(*args, **kwargs); children.append(child); return child
        class Context:
            checks=0
            def heartbeat(self):
                self.checks += 1
                return self.checks < 2
        from modelanvil.runners.model_catalog import _store
        ref=_store(io.BytesIO(b'{}'),tenant=self.tenant.pk,project=self.project.pk,name='config.json')
        inputs={'state':'Request a refund ' + 'x'*30000, 'questions':{'q':{'type':'noul','instructions':'Refund?'}}}
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory)/'runtime.py'; runtime.write_text('import time\ntime.sleep(120)\n')
            with override_settings(MODELANVIL_SPECIALIST_PYTHON=sys.executable), \
                 patch.object(specialists,'RUNTIME',runtime), \
                 patch.object(specialists,'snapshot',return_value={'source':{},'files':{'config.json':ref}}), \
                 patch.object(specialists.subprocess,'Popen',side_effect=spawn):
                with self.assertRaisesMessage(ValueError,'cancelled or lease lost'):
                    specialists.execute(self.laya,tenant=self.tenant.pk,project=self.project.pk,
                        kind='laya',device='cpu',inputs=inputs,context=Context())
        self.assertEqual(len(children),1); self.assertIsNotNone(children[0].returncode)
        with self.assertRaises(ProcessLookupError):
            os.kill(children[0].pid,0)
        with device_lease('cpu'):
            pass
