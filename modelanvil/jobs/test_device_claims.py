"""Real database/device-lock fencing with controlled GPU inventory; no GPU execution."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import copy
import tempfile
import threading
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from django.conf import settings
from django.db import connection,close_old_connections
from django.test import TestCase,TransactionTestCase,override_settings,tag
from django.utils import timezone
from modelanvil.budgets.models import BudgetPolicy,BudgetReservation
from modelanvil.core.tenancy import reset_context
from modelanvil.device_admission import device_lease,host_key
from modelanvil.identity.models import Tenant,Team,Project
from modelanvil.jobs.models import Job,JobAttempt,Worker,WorkerPool,DeviceClaim,claim_job,commit_result,reconcile_expired_leases
from modelanvil.runners.models import TrainingRun,TokenizerVersion
from modelanvil.runners.training.admission import gpu_claim_plan
from modelanvil.runners.training import hf_runtime


def worker_job(name):
    tenant=Tenant.objects.create(name=name,slug=name)
    pool=WorkerPool.all_objects.create(tenant_id=tenant.pk,name=name)
    worker=Worker.all_objects.create(tenant_id=tenant.pk,pool=pool,name=name,slots=1,capabilities={})
    job=Job.all_objects.create(tenant_id=tenant.pk,pool=pool,name=name,payload={'type':'fixture'},requirements={'slots':1})
    return worker,job


class DeviceClaimTests(TestCase):
    def setUp(self):
        reset_context();self.addCleanup(reset_context)
        self.a,self.first=worker_job('claim-a');self.b,self.second=worker_job('claim-b')
        self.placement={'host_key':'controlled-host','device_key':'apple-0'}
        patcher=patch('modelanvil.runners.training.admission.gpu_claim_plan',return_value=self.placement)
        patcher.start();self.addCleanup(patcher.stop)

    def test_distinct_tenants_cannot_claim_same_physical_device_and_completion_releases(self):
        first=claim_job(self.a,self.first);self.assertIsNotNone(first)
        self.assertIsNone(claim_job(self.b,self.second))
        self.b.refresh_from_db();self.second.refresh_from_db()
        self.assertEqual(self.b.slots,1);self.assertEqual(self.second.status,'queued')
        attempt=JobAttempt.all_objects.get(attempt_id=first['attempt_id'])
        self.assertTrue(commit_result(attempt,first['fencing_token'],'succeeded'))
        second=claim_job(self.b,self.second);self.assertIsNotNone(second)
        self.assertEqual(str(DeviceClaim.objects.get().attempt.attempt_id),second['attempt_id'])

    def test_expiry_then_stale_commit_cannot_release_new_device_owner_and_cancel_releases(self):
        first=claim_job(self.a,self.first);old=JobAttempt.all_objects.get(attempt_id=first['attempt_id'])
        expired=timezone.now()-timedelta(seconds=1)
        JobAttempt.all_objects.filter(pk=old.pk).update(lease_expires_at=expired)
        Job.all_objects.filter(pk=self.first.pk).update(lease_expires_at=expired)
        self.assertEqual(reconcile_expired_leases(),1)
        second=claim_job(self.b,self.second);self.assertIsNotNone(second)
        self.assertFalse(commit_result(old,first['fencing_token'],'succeeded'))
        newer=JobAttempt.all_objects.get(attempt_id=second['attempt_id'])
        self.assertEqual(DeviceClaim.objects.get().attempt_id,newer.pk)
        self.second.desired_action='cancel';self.second.save(update_fields=['desired_action'])
        self.assertTrue(commit_result(newer,second['fencing_token'],'interrupted'))
        self.assertIsNone(DeviceClaim.objects.get().attempt_id)
        self.second.refresh_from_db();self.assertEqual(self.second.status,'cancelled')
        self.b.refresh_from_db();self.assertEqual(self.b.slots,1)


class GPUClaimValidationTests(TestCase):
    def setUp(self):
        reset_context();self.addCleanup(reset_context)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        override=override_settings(MODELANVIL_DEVICE_LOCK_ROOT=self.temp.name);override.enable();self.addCleanup(override.disable)
        self.worker,self.job=worker_job('gpu-claim')
        team=Team.all_objects.create(tenant_id=self.worker.tenant_id,name='Team',slug='team')
        project=Project.all_objects.create(tenant_id=self.worker.tenant_id,team=team,name='P',slug='p')
        tok=TokenizerVersion.all_objects.create(tenant_id=self.worker.tenant_id,project=project,name='Tokenizer')
        self.observed={'host_key':host_key(),'device':{'id':'cuda:0','backend':'cuda','uuid':'controlled-device','total_memory_bytes':8*1024**3},'framework':{'version':'controlled'},'packages':{}}
        self.module=SimpleNamespace(CONTRACT_DIGEST='contract',build_digest=lambda:'build',capable_worker=lambda w:True,
            require_packages=lambda:None,observed_device=lambda selector:copy.deepcopy(self.observed))
        self.worker.capabilities={'gpu_device':'cuda:0'};self.worker.save(update_fields=['capabilities'])
        self.job.project=project;self.job.save(update_fields=['project'])
        self.policy=BudgetPolicy.all_objects.create(tenant_id=self.worker.tenant_id,name='Steps',unit='training_steps',period='lifetime',limit_amount=2)
        reservation=BudgetReservation.reserve(tenant_id=self.worker.tenant_id,policy=self.policy,job_id=self.job.job_id,estimated_amount=2)
        pins={'runtime':'controlled-runtime','contract_digest':'contract','build_digest':'build','worker_id':self.worker.pk,'accelerator':copy.deepcopy(self.observed)}
        self.run=TrainingRun.all_objects.create(tenant_id=self.worker.tenant_id,project=project,tokenizer_version=tok,pool=self.worker.pool,
            job=self.job,total_steps=2,resource_reservation_id=reservation.reservation_id,hardware_config={'execution_mode':'worker','pins':pins})
        self.job.payload={'type':'qualified_training','run_id':str(self.run.run_id)};self.job.save(update_fields=['payload'])
        patcher=patch('modelanvil.runners.training.registry.runtime_module',return_value=self.module);patcher.start();self.addCleanup(patcher.stop)

    def test_fresh_claim_and_current_budget_then_disabled_or_changed_build_refuse(self):
        self.assertEqual(gpu_claim_plan(self.job,self.worker),{'host_key':host_key(),'device_key':'cuda-0'})
        self.policy.enabled=False;self.policy.save(update_fields=['enabled'])
        with self.assertRaisesRegex(ValueError,'budget'):gpu_claim_plan(self.job,self.worker)
        self.policy.enabled=True;self.policy.limit_amount=1;self.policy.save(update_fields=['enabled','limit_amount'])
        with self.assertRaisesRegex(ValueError,'budget'):gpu_claim_plan(self.job,self.worker)
        self.policy.limit_amount=2;self.policy.currency='USD';self.policy.save(update_fields=['limit_amount','currency'])
        with self.assertRaisesRegex(ValueError,'budget'):gpu_claim_plan(self.job,self.worker)
        self.module.build_digest=lambda:'different'
        with self.assertRaisesRegex(ValueError,'build'):gpu_claim_plan(self.job,self.worker)

    def test_changed_backend_host_identity_vanished_device_and_false_worker_refuse(self):
        baseline=copy.deepcopy(self.observed)
        for change in ({'host_key':'different-host'},{'device':{**baseline['device'],'uuid':'replaced'}},{'device':{'id':'cpu','backend':'cpu'}}):
            self.observed={**baseline,**change}
            with self.assertRaisesRegex(ValueError,'placement'):gpu_claim_plan(self.job,self.worker)
        self.observed=baseline
        self.module.observed_device=lambda selector:(_ for _ in ()).throw(ValueError('device vanished'))
        self.assertIsNone(claim_job(self.worker,self.job));self.assertEqual(JobAttempt.all_objects.count(),0)
        self.module.observed_device=lambda selector:copy.deepcopy(baseline)
        self.module.capable_worker=lambda w:False
        with self.assertRaisesRegex(ValueError,'worker'):gpu_claim_plan(self.job,self.worker)

    def test_other_tenant_and_actual_busy_posix_device_cannot_claim(self):
        other,_=worker_job('foreign-gpu')
        with self.assertRaisesRegex(ValueError,'tenant'):gpu_claim_plan(self.job,other)
        with device_lease('cuda:0'):
            self.assertIsNone(claim_job(self.worker,self.job))
        self.assertEqual(JobAttempt.all_objects.count(),0)
        self.assertIsNotNone(claim_job(self.worker,self.job))

    def test_current_free_memory_is_required_and_not_frozen_into_identity(self):
        for getter in (None,lambda index:(1*1024**3,8*1024**3),lambda index:(None,None)):
            api=SimpleNamespace(**({'mem_get_info':getter} if getter else {}))
            with patch.dict('sys.modules',{'torch':SimpleNamespace(cuda=api)}),self.assertRaises(ValueError):hf_runtime.memory_observation('cuda:0')
        with patch.dict('sys.modules',{'torch':SimpleNamespace(cuda=SimpleNamespace(mem_get_info=lambda index:(6*1024**3,8*1024**3)))}):
            current=hf_runtime.memory_observation('cuda:0')
            self.assertEqual(current['headroom_bytes'],6*1024**3)
            self.assertIn('observed_at',current)


@tag('pg')
@skipUnless(connection.vendor=='postgresql','PostgreSQL row-level device claim concurrency')
class DeviceClaimConcurrencyTests(TransactionTestCase):
    def test_two_workers_tenants_claim_one_device_once(self):
        reset_context();a,first=worker_job('concurrent-a');b,second=worker_job('concurrent-b')
        barrier=threading.Barrier(2)
        def race(worker,job):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return claim_job(worker,job)
            finally:close_old_connections()
        with patch('modelanvil.runners.training.admission.gpu_claim_plan',return_value={'host_key':'controlled-host','device_key':'apple-0'}),ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(race,a,first),pool.submit(race,b,second)]
            results=[f.result(timeout=20) for f in futures]
        self.assertEqual(sum(result is not None for result in results),1)
        self.assertEqual(JobAttempt.all_objects.filter(status='running').count(),1)
        self.assertEqual(DeviceClaim.objects.exclude(attempt=None).count(),1)
