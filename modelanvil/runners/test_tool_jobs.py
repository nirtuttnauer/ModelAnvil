"""Failure/recovery accounting tests. Mock tensors never qualify a model or hardware."""
from contextlib import nullcontext
import hashlib
import json
import uuid
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase
from modelanvil.api import test_specialists as fixtures
from modelanvil.api.test_tools import ADD
from modelanvil.budgets.models import BudgetPolicy,BudgetReservation
from modelanvil.jobs.models import Job,WorkerPool,Worker,claim_job
from modelanvil.jobs.executor import execute_claim
from modelanvil.runners.models import InferenceRequest
from modelanvil.runners import tool_jobs as tools,tool_runtime as runtime


class ToolRecoveryTests(TestCase):
    setUp=fixtures.SpecialistApiTests.setUp
    version=fixtures.SpecialistApiTests.version

    def request(self,pending=None):
        pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='tools-'+str(uuid.uuid4()))
        worker=Worker.all_objects.create(tenant_id=self.tenant.pk,pool=pool,name='tools-'+str(uuid.uuid4()),slots=1)
        job=Job.all_objects.create(tenant_id=self.tenant.pk,project=self.project,pool=pool,name='tools',max_attempts=3)
        frozen={'plan':{'files':{}},'catalog':{'tools':[ADD],'servers':{},'bindings':{'add':{'kind':'mcp','server_id':'fixture'}},'sandbox':None},'max_tokens':128}
        record=InferenceRequest.all_objects.create(tenant_id=self.tenant.pk,project=self.project,model_version=self.model,principal_id='fixture',input_digest=tools.digest(frozen),
            configuration={'kind':tools.TYPE,'job_id':str(job.job_id),'frozen':frozen,'messages':[{'role':'user','content':'Add17and25.'}],
                'trace':[],'model_turns':0,'tool_calls':0,'charges':{},'pending_call':pending})
        job.payload={'type':tools.TYPE,'request_id':str(record.request_id),'input_digest':record.input_digest};job.save()
        policy=BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,name='tools-'+str(uuid.uuid4()),unit='generated_tokens',period='lifetime',limit_amount=1152)
        reservation=BudgetReservation.reserve(tenant_id=self.tenant.pk,policy=policy,job_id=job.job_id,estimated_amount=1152)
        return job,record,worker,reservation,frozen

    def run_job(self,job,worker,frozen):
        with patch('modelanvil.runners.training.admission.gpu_claim_plan',return_value=None),patch.object(tools,'current_inputs',return_value=frozen), \
                patch.object(runtime,'staged_files',return_value=nullcontext(Path('/not-loaded'))):
            descriptor=claim_job(worker,job);self.assertIsNotNone(descriptor)
            execute_claim(worker,descriptor,tools.tool_executor)
        job.refresh_from_db()

    def test_unknown_prior_tool_result_is_not_dispatched_again(self):
        job,record,worker,reservation,frozen=self.request('call_0_0')
        record.configuration['charges']={'lost:0':{'tokens':128,'basis':'unknown_inflight_upper_bound'}};record.configuration['model_turns']=1;record.save()
        with patch.object(runtime,'generate') as generate,patch.object(tools.mcp,'call') as dispatch:
            self.run_job(job,worker,frozen);generate.assert_not_called();dispatch.assert_not_called()
        self.assertEqual(job.status,'failed');self.assertEqual(job.attempts.get().status,'failed')
        reservation.refresh_from_db();self.assertEqual(reservation.settled_amount,128)
        record.refresh_from_db();self.assertEqual(record.usage['unknown_inflight_tokens'],128);self.assertIn('trace_artifact',record.configuration)

    def test_truncated_native_calls_never_execute_and_retry_usage_is_bounded(self):
        job,record,worker,reservation,frozen=self.request()
        report={'finish_reason':'length','content':'<tool_call>{"name":"add"','usage':{'completion_tokens':8},'wall_seconds':1}
        with patch.object(runtime,'generate',return_value=report) as generate,patch.object(tools.mcp,'call') as dispatch:
            self.run_job(job,worker,frozen);self.assertEqual(generate.call_count,3);dispatch.assert_not_called()
        self.assertEqual(job.status,'failed');reservation.refresh_from_db();self.assertEqual(reservation.settled_amount,24)
        record.refresh_from_db();self.assertEqual(sum(e['kind']=='validation_failure' for e in record.configuration['trace']),3)

    def test_worker_success_without_real_complete_trace_fails_and_cancel_settles_once(self):
        job,record,worker,reservation,frozen=self.request()
        with patch.object(tools,'current_inputs',return_value=frozen):self.assertEqual(tools.finalize_job(job,'succeeded'),'failed')
        reservation.refresh_from_db();self.assertEqual(reservation.settled_amount,0)
        other_job,other_record,worker,reservation,frozen=self.request()
        tools.cancel(other_record);reservation.refresh_from_db();self.assertEqual(reservation.state,'settled');self.assertEqual(reservation.settled_amount,0)
        with self.assertRaises(ValueError):tools.cancel(other_record)

    def test_source_build_changes_invalidate_loaded_worker(self):
        original=Path.read_bytes
        def changed(path):
            raw=original(path)
            return raw+b'changed' if str(path).endswith('/scripts/tool_sandbox_guard.py') else raw
        with patch.object(Path,'read_bytes',changed):
            with self.assertRaisesRegex(ValueError,'changed on disk'):runtime.build_digest()

    def test_abandoned_native_completion_conservatively_settles_once(self):
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        import io
        job,record,worker,reservation,frozen=self.request()
        record.status='running';record.configuration={'kind':'native_tool_completion','frozen':{'max_tokens':128},'reservation_job_id':str(job.job_id)};record.save()
        InferenceRequest.all_objects.filter(pk=record.pk).update(created_at=timezone.now()-timedelta(seconds=121))
        call_command('reconcile_tool_completions',stdout=io.StringIO());call_command('reconcile_tool_completions',stdout=io.StringIO())
        record.refresh_from_db();reservation.refresh_from_db();self.assertEqual(record.status,'failed');self.assertEqual(reservation.settled_amount,128)
        self.assertEqual(reservation.usage_events.count(),1)
