"""Real transformer evaluation, fenced recovery and case-based settlement."""
import io
import os
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from modelanvil.api import test_local_ml as local_fixture
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.identity.models import ApiKey, Role
from modelanvil.jobs.executor import execute_claim, ExecutionContext
from modelanvil.jobs.models import Job, JobAttempt, Worker, claim_job, commit_result, reconcile_expired_leases
from modelanvil.jobs.setup import observe_local_worker
from modelanvil.runners.eval_worker import evaluation_worker_executor
from modelanvil.runners.models import EvaluationRun
from modelanvil.runners.training import test_general_runtime as general_fixture


class DurableEvaluationTests(TestCase):
    artifact = general_fixture.GeneralRuntimeTests.artifact
    envelope = general_fixture.GeneralRuntimeTests.envelope
    payload = general_fixture.GeneralRuntimeTests.payload
    launch = general_fixture.GeneralRuntimeTests.launch
    execute = general_fixture.GeneralRuntimeTests.execute
    suite = local_fixture.LocalMlApiTests.suite
    _suite_pk = local_fixture.LocalMlApiTests._suite_pk
    pending_eval = local_fixture.LocalMlApiTests.pending_eval

    def setUp(self):
        general_fixture.GeneralRuntimeTests.setUp(self)
        self.candidate = self.execute(self.launch()).output_model_version
        ApiKey.objects.filter(tenant=self.tenant).update(role=Role.ADMIN)
        response = self.client.post('/api/v1/workers/setup/', {
            'worker_name': 'evaluator', 'pool': 'evaluation', 'profile': 'cpu-evaluation'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.credential = response.data['worker_token']
        self.evaluator = Worker.all_objects.get(pk=response.data['worker_id'])
        observe_local_worker(self.evaluator, 'cpu-evaluation', self.credential)
        self.case_budget = BudgetPolicy.all_objects.create(tenant_id=self.tenant.pk,
            name='Evaluation cases', period='lifetime', unit='evaluation_cases', limit_amount=50)
        self.request = {'pool': self.evaluator.pool_id, 'budget_policy_id': str(self.case_budget.policy_id), 'max_tokens': 2}

    def queued(self, cases=None):
        run_id = self.pending_eval(candidate=self.candidate, baseline=self.base, cases=cases)
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', self.request, format='json')
        self.assertEqual(response.status_code, 202, response.data)
        return EvaluationRun.all_objects.get(run_id=run_id)

    def test_actual_transformer_candidate_and_baseline_with_idempotent_queue_and_completion(self):
        run = self.queued()
        self.assertNotEqual(self.candidate.metadata['weights_sha256'], self.base.metadata.get('weights_sha256'))
        again = self.client.post(f'/api/v1/evaluation-runs/{run.run_id}/execute/', self.request, format='json')
        self.assertEqual(again.status_code, 200)
        conflict = self.client.post(f'/api/v1/evaluation-runs/{run.run_id}/execute/', {**self.request, 'max_tokens': 3}, format='json')
        self.assertEqual(conflict.status_code, 400)
        self.assertEqual(BudgetReservation.all_objects.filter(policy=self.case_budget).count(), 1)
        with patch.dict(os.environ, {'MODELANVIL_WORKER_TOKEN': self.credential}):
            call_command('run_worker', worker_id=self.evaluator.pk, profile='cpu-evaluation', once=True, stdout=io.StringIO())
        run.refresh_from_db()
        self.assertEqual(run.status, 'completed', JobAttempt.all_objects.last().error)
        self.assertEqual(run.job.status, 'succeeded')
        self.assertEqual(run.case_results.count(), 1)
        self.assertEqual(run.protocol_ref['pins']['scorer_version'], 'modelanvil.local-scorers.v1')
        self.assertEqual(run.protocol_ref['pins']['protected_role'], 'protected_eval')
        self.assertEqual(run.protocol_ref['environment']['device'], 'cpu')
        self.assertTrue(run.protocol_ref['environment']['python'])
        self.assertEqual(run.protocol_ref['environment']['build_digest'], run.protocol_ref['pins']['build_digest'])
        recorded = self.client.get(f'/api/v1/evaluation-runs/{run.run_id}/').data
        self.assertTrue(recorded['comparison']['compatible'])
        self.assertEqual(recorded['case_coverage'], {'completed': 1, 'missing': 0, 'failed': 1, 'total': 1})
        self.assertNotEqual(run.case_results.get().candidate_output, 'ANSWER_IS_NOT_ECHOED')
        self.assertFalse(run.case_results.get().passed)
        self.assertEqual(len(run.protocol_ref['baseline_results']), 1)
        self.assertEqual(run.metrics.get(key='accuracy', slice_name='all').value, 0)
        event = UsageEvent.all_objects.get(unit='evaluation_cases')
        self.assertEqual(event.quantity, 1)
        attempt = JobAttempt.all_objects.get(job=run.job)
        self.assertFalse(commit_result(attempt, attempt.fencing_token, 'succeeded'))
        self.assertEqual(UsageEvent.all_objects.filter(unit='evaluation_cases').count(), 1)
        detail = self.client.get(f'/api/v1/run-details/evaluation/{run.run_id}/').data
        self.assertEqual(detail['observed']['current_step'], 1)
        self.assertEqual(detail['inputs']['case_coverage']['missing'], 0)
        self.assertEqual(detail['evidence']['level'], 'integrated_execution')
        self.assertEqual(self.client.get(f'/api/v1/run-details/evaluation/{run.run_id}/attempts/').status_code, 200)

    def test_incompatible_tokenizer_rejected_before_allocation(self):
        from modelanvil.runners.models import TokenizerVersion
        other = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, name='Incompatible evaluation tokenizer', vocabulary_size=17)
        type(self.base).all_objects.filter(pk=self.base.pk).update(tokenizer=other)
        run_id = self.pending_eval(candidate=self.candidate, baseline=self.base)
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', self.request, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn('tokenizer', str(response.json()).lower())
        self.assertFalse(BudgetReservation.all_objects.filter(policy=self.case_budget).exists())

    def test_known_source_group_overlap_rejected_before_allocation(self):
        from modelanvil.runners.training.runtime import read_artifact
        import json
        prepared = json.loads(read_artifact(self.dataset.manifest_artifact, self.tenant.pk, None))
        row = next(r for r in prepared['rows'] if r['sample_id'] in prepared['split_manifest']['train'])
        run_id = self.pending_eval(candidate=self.candidate, baseline=self.base, cases=[{
            'case_id': 'overlap', 'input_prompt': 'x', 'expected_output': 'z', 'source_group_id': row['source_group_id']}])
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', self.request, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn('overlap', str(response.json()))
        self.assertFalse(BudgetReservation.all_objects.filter(policy=self.case_budget).exists())

    def test_queued_cancel_settles_zero_and_retains_provenance(self):
        run = self.queued()
        self.assertEqual(self.client.post(f'/api/v1/jobs/{run.job.job_id}/cancel/', {}, format='json').status_code, 400)
        response = self.client.post(f'/api/v1/evaluation-runs/{run.run_id}/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        run.refresh_from_db(); self.assertEqual(run.status, 'cancelled')
        self.assertEqual(BudgetReservation.all_objects.get(policy=self.case_budget).settled_amount, 0)
        self.assertEqual(self.client.delete(f'/api/v1/evaluation-runs/{run.run_id}/').status_code, 400)
        self.assertIsNone(claim_job(self.evaluator, run.job))
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run.run_id}/cancel/', {}, format='json').status_code, 200)
        self.assertEqual(UsageEvent.all_objects.filter(unit='evaluation_cases').count(), 1)
        from modelanvil.runners.eval_worker import finalize_evaluation
        completed_at = run.completed_at
        finalize_evaluation(run.job, 'succeeded')  # Late duplicate cannot rewrite cancellation.
        run.refresh_from_db()
        self.assertEqual(run.status, 'cancelled')
        self.assertEqual(run.completed_at, completed_at)
        self.assertFalse(run.metrics.exists())

    def test_running_cancel_is_requested_until_worker_observes_it(self):
        run = self.queued()
        descriptor = claim_job(self.evaluator, run.job)
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run.run_id}/cancel/', {}, format='json').status_code, 202)
        detail = self.client.get(f'/api/v1/run-details/evaluation/{run.run_id}/').data
        self.assertEqual(detail['observed']['job_state'], 'running')
        self.assertEqual(detail['desired']['action'], 'cancel')
        self.assertFalse(detail['desired']['acknowledged'])
        outcome = execute_claim(self.evaluator, descriptor, evaluation_worker_executor)
        self.assertTrue(outcome['committed'], outcome)
        run.refresh_from_db(); self.assertEqual(run.status, 'cancelled')
        self.assertFalse(run.metrics.exists())
        self.assertEqual(BudgetReservation.all_objects.get(policy=self.case_budget).settled_amount, 0)

    def test_interrupted_partial_execution_recovers_without_duplicate_cases_or_charges(self):
        cases = [{'case_id': str(i), 'input_prompt': 'x', 'expected_output': 'unmatched', 'slice': 'held-out'} for i in range(3)]
        run = self.queued(cases)
        descriptor = claim_job(self.evaluator, run.job)
        original = ExecutionContext.heartbeat
        expired = False
        def interrupted(context, progress=None):
            nonlocal expired
            if run.case_results.count() == 1 and not expired:
                expired = True
                JobAttempt.all_objects.filter(pk=context.attempt.pk).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
            return original(context, progress)
        with patch.object(ExecutionContext, 'heartbeat', interrupted):
            outcome = execute_claim(self.evaluator, descriptor, evaluation_worker_executor)
        self.assertFalse(outcome['committed'])
        run.refresh_from_db(); self.assertEqual(run.case_results.count(), 1)
        self.assertFalse(run.metrics.exists())
        detail = self.client.get(f'/api/v1/run-details/evaluation/{run.run_id}/').data
        self.assertEqual(detail['inputs']['case_coverage']['missing'], 2)
        recorded = self.client.get(f'/api/v1/evaluation-runs/{run.run_id}/').data
        self.assertEqual(recorded['case_coverage']['missing'], 2)
        self.assertFalse(recorded['comparison']['compatible'])
        self.assertEqual(reconcile_expired_leases(), 1)
        self.evaluator.refresh_from_db()
        second = claim_job(self.evaluator, run.job)
        outcome = execute_claim(self.evaluator, second, evaluation_worker_executor)
        self.assertTrue(outcome['committed'], outcome)
        run.refresh_from_db(); self.assertEqual(run.status, 'completed', JobAttempt.all_objects.last().error)
        self.assertEqual(run.case_results.count(), 3)
        self.assertEqual(len(run.protocol_ref['baseline_results']), 3)
        self.assertEqual(UsageEvent.all_objects.get(unit='evaluation_cases').quantity, 3)
        self.assertEqual(BudgetReservation.all_objects.get(policy=self.case_budget).settled_amount, 3)

    def test_changed_input_and_stale_worker_cannot_report_success(self):
        Worker.all_objects.filter(pk=self.evaluator.pk).update(last_heartbeat_at=timezone.now()-timedelta(seconds=61))
        run_id = self.pending_eval(candidate=self.candidate, baseline=self.base)
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', self.request, format='json').status_code, 400)
        observe_local_worker(self.evaluator, 'cpu-evaluation', self.credential)
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', self.request, format='json')
        self.assertEqual(response.status_code, 202, response.data)
        run = EvaluationRun.all_objects.get(run_id=run_id)
        run.protocol_ref['pins']['build_digest'] = 'changed'
        run.save()
        outcome = execute_claim(self.evaluator, claim_job(self.evaluator, run.job), evaluation_worker_executor)
        self.assertEqual(outcome['status'], 'failed')
        run.refresh_from_db(); self.assertEqual(run.status, 'failed')
        self.assertFalse(run.metrics.exists())
        self.assertEqual(BudgetReservation.all_objects.get(policy=self.case_budget).settled_amount, 0)
