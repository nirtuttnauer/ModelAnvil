"""Self-service recovery replays real optimizer state without charging old steps."""
from unittest.mock import patch
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from modelanvil.budgets.models import BudgetReservation, UsageEvent
from modelanvil.identity.models import ApiKey, Role, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import JobAttempt, claim_job
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training import test_cpu_runtime as cpu, test_general_runtime as general
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.runners.training.runtime import digest


class RecoveryTests(TestCase):
    setUp = cpu.CpuRuntimeTests.setUp
    artifact = cpu.CpuRuntimeTests.artifact
    envelope = cpu.CpuRuntimeTests.envelope
    payload = cpu.CpuRuntimeTests.payload
    launch = cpu.CpuRuntimeTests.launch
    execute = cpu.CpuRuntimeTests.execute

    def interrupt(self, run):
        descriptor = claim_job(self.worker)
        original = cpu.CausalTextModel.compute_loss_and_step
        calls = 0
        def fail(model, *args):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise ValueError('Test interrupted after two committed optimizer steps.')
            return original(model, *args)
        with patch.object(cpu.CausalTextModel, 'compute_loss_and_step', fail):
            result = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertTrue(result['committed']); self.assertEqual(result['status'], JobAttempt.Status.FAILED)
        run.refresh_from_db(); self.assertEqual(run.current_step, 2); return run

    def request_resume(self, run, **changes):
        return self.client.post(f'/api/v1/training-runs/{run.run_id}/resume/', {
            'checkpoint_id': str(run.checkpoints.order_by('-step').first().checkpoint_id),
            'budget_policy_id': str(self.policy.policy_id), **changes}, format='json')

    def test_real_recovery_is_repeat_safe_exact_and_charges_only_remaining_steps(self):
        parent = self.interrupt(self.launch())
        parent_checkpoint = parent.checkpoints.get(step=2)
        before = list(parent.metrics_log)
        report = self.client.get(f'/api/v1/training-runs/{parent.run_id}/resume/')
        self.assertTrue(report.data['available'], report.data); self.assertEqual(report.data['remaining_steps'], 2)
        first = self.request_resume(parent); self.assertEqual(first.status_code, 201, first.data)
        repeat = self.request_resume(parent); self.assertEqual(repeat.status_code, 200, repeat.data)
        self.assertEqual(first.data['run_id'], repeat.data['run_id'])
        child = TrainingRun.all_objects.get(run_id=first.data['run_id'])
        self.assertEqual(child.recovery_parent, parent); self.assertEqual(child.recovery_checkpoint, parent_checkpoint)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=child.job.job_id).estimated_amount, 2)
        child = self.execute(child)
        self.assertEqual([m['step'] for m in child.metrics_log], [3, 4])
        self.assertEqual(BudgetReservation.all_objects.get(job_id=child.job.job_id).settled_amount, 2)
        self.assertEqual(UsageEvent.all_objects.get(provider_event_key=f'training:{child.run_id}').quantity, 2)
        comparison = self.execute(self.launch(key='uninterrupted'))
        self.assertEqual(child.checkpoints.get(step=4).weights_manifest['weights']['weights_sha256'],
            comparison.checkpoints.get(step=4).weights_manifest['weights']['weights_sha256'])
        parent.refresh_from_db(); self.assertEqual(parent.status, 'failed'); self.assertEqual(parent.metrics_log, before)
        parent_checkpoint.refresh_from_db(); self.assertEqual(parent_checkpoint.state_digest, digest(parent_checkpoint.weights_manifest))

    def test_corrupt_checkpoint_active_ownership_cancel_and_exhausted_budget_block(self):
        parent = self.interrupt(self.launch()); checkpoint = parent.checkpoints.get(step=2)
        for changes, reason in [({'claimed_by': self.worker}, 'ownership'), ({'desired_action': 'cancel'}, 'Cancellation')]:
            old = {k: getattr(parent.job, k) for k in changes}
            for k, v in changes.items(): setattr(parent.job, k, v)
            parent.job.save(update_fields=list(changes))
            result = self.request_resume(parent); self.assertEqual(result.status_code, 400, result.json()); self.assertIn(reason, str(result.json()))
            for k, v in old.items(): setattr(parent.job, k, v)
            parent.job.save(update_fields=list(changes))
        self.policy.limit_amount = 2; self.policy.save()
        self.assertEqual(self.request_resume(parent).status_code, 400)
        self.policy.limit_amount = 100; self.policy.save()
        checkpoint.weights_manifest['data_b64'] = 'corrupt'; checkpoint.save()
        self.assertEqual(self.request_resume(parent).status_code, 400)
        self.assertEqual(TrainingRun.all_objects.count(), 1); self.assertEqual(BudgetReservation.all_objects.count(), 1)

    def test_viewer_foreign_scope_and_changed_checkpoint_are_rejected(self):
        parent = self.interrupt(self.launch())
        response = self.request_resume(parent, checkpoint_id=str(parent.checkpoints.get(step=1).checkpoint_id))
        self.assertEqual(response.status_code, 400)
        secret, hashed = generate_api_key(); ApiKey.objects.create(tenant=self.tenant, name='viewer', role=Role.VIEWER, secret_hash=hashed)
        restricted = APIClient(); restricted.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(restricted.post(f'/api/v1/training-runs/{parent.run_id}/resume/', {}, format='json').status_code, 403)
        self.base.artifact_manifest_id = ''; self.base.save()
        self.assertEqual(self.request_resume(parent).status_code, 400)
        self.assertEqual(TrainingRun.all_objects.count(), 1)


class TransformerRecoveryTests(TestCase):
    setUp = general.GeneralRuntimeTests.setUp
    artifact = general.GeneralRuntimeTests.artifact
    envelope = general.GeneralRuntimeTests.envelope
    payload = general.GeneralRuntimeTests.payload
    launch = general.GeneralRuntimeTests.launch
    execute = general.GeneralRuntimeTests.execute

    def test_real_adamw_state_continuation_matches_uninterrupted_weights(self):
        from modelanvil.runners.training.general_transformer import GeneralTransformer
        parent = self.launch(total_steps=4)
        descriptor = claim_job(self.worker); original = GeneralTransformer.loss; calls = 0
        def fail(model, *args):
            nonlocal calls
            calls += 1
            if calls == 5: raise ValueError('Interrupted after two updates.')
            return original(model, *args)
        with patch.object(GeneralTransformer, 'loss', fail):
            execute_claim(self.worker, descriptor, training_worker_executor)
        parent.refresh_from_db(); self.assertEqual(parent.current_step, 2)
        checkpoint = parent.checkpoints.get(step=2)
        response = self.client.post(f'/api/v1/training-runs/{parent.run_id}/resume/', {
            'checkpoint_id': str(checkpoint.checkpoint_id), 'budget_policy_id': str(self.policy.policy_id)}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        child = self.execute(TrainingRun.all_objects.get(run_id=response.data['run_id']))
        expected = self.execute(self.launch(key='full', total_steps=4))
        self.assertEqual(child.checkpoints.get(step=4).weights_manifest['weights']['weights_sha256'],
            expected.checkpoints.get(step=4).weights_manifest['weights']['weights_sha256'])
        self.assertEqual(BudgetReservation.all_objects.get(job_id=child.job.job_id).settled_amount, 2)


class ConcurrentRecoveryTests(TransactionTestCase):
    setUp = RecoveryTests.setUp
    artifact = RecoveryTests.artifact
    envelope = RecoveryTests.envelope
    payload = RecoveryTests.payload
    launch = RecoveryTests.launch
    interrupt = RecoveryTests.interrupt

    def test_concurrent_requests_create_one_child_job_and_one_remaining_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connection
        if connection.vendor == 'sqlite' and str(connection.settings_dict['NAME']).startswith('file:memorydb'):
            self.skipTest('SQLite shared-memory databases cannot wait on table locks; run with DATABASE_TEST_NAME pointing to a temporary file.')
        parent = self.interrupt(self.launch())
        checkpoint = parent.checkpoints.get(step=2)
        gate = Barrier(2)
        def send():
            close_old_connections()
            client = APIClient(); client.credentials(**self.client._credentials)
            try:
                gate.wait(timeout=10)
                response = client.post(f'/api/v1/training-runs/{parent.run_id}/resume/', {
                    'checkpoint_id': str(checkpoint.checkpoint_id), 'budget_policy_id': str(self.policy.policy_id)}, format='json')
                return response.status_code, response.json()
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: send(), range(2)))
        self.assertEqual(sorted(code for code, _ in responses), [200, 201], responses)
        self.assertEqual(responses[0][1]['run_id'], responses[1][1]['run_id'])
        self.assertEqual(TrainingRun.all_objects.filter(recovery_parent=parent).count(), 1)
        self.assertEqual(BudgetReservation.all_objects.count(), 2)
