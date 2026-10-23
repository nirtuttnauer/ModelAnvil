"""Real reviewed-label CPU cycles; format fixtures test orchestration, not task quality."""
import io
import json
from django.test import TestCase, override_settings
from modelanvil.annotation.models import CampaignBatch, CumulativeSnapshot, LabelingCampaign
from modelanvil.artifacts.models import Dataset
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import ApiKey, Role
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Job, Worker, claim_job
from modelanvil.jobs.setup import observe_local_worker
from modelanvil.runners.eval_worker import evaluation_worker_executor
from modelanvil.runners.models import EvaluationSuite, EvaluationSuiteVersion, TrainingRun, EvaluationMetric
from modelanvil.runners.training import test_cpu_runtime as cpu
from modelanvil.runners.training.executor import training_worker_executor


@override_settings(ALLOWED_HOSTS=['testserver'])
class RealCampaignCycleTests(TestCase):
    artifact = cpu.CpuRuntimeTests.artifact
    envelope = cpu.CpuRuntimeTests.envelope

    def setUp(self):
        cpu.CpuRuntimeTests.setUp(self)
        ApiKey.objects.filter(tenant=self.tenant).update(role=Role.ADMIN)
        response = self.client.post('/api/v1/workers/setup/', {'worker_name': 'cycle evaluator',
            'pool': 'cycle-evaluation', 'profile': 'cpu-evaluation'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.evaluator = Worker.all_objects.get(pk=response.data['worker_id'])
        observe_local_worker(self.evaluator, 'cpu-evaluation', response.data['worker_token'])
        self.case_policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name='cycle cases',
            period='lifetime', unit='evaluation_cases', limit_amount=10)
        dataset = Dataset.objects.create(tenant_id=self.tenant.pk, name='Labeling source')
        rows = [self.envelope(i, text) for i, text in enumerate(['ab ab', 'cd cd', 'ef ef'])]
        rows[-1]['source_group_id'] = 'protected'
        raw = b''.join(json.dumps(row).encode()+b'\n' for row in rows)
        self.source = publish_prepared_dataset(dataset, self.artifact('labels-source.jsonl', raw,
            'application/x-ndjson'), validation_percent=0, test_percent=0)
        suite = EvaluationSuite.objects.create(tenant_id=self.tenant.pk, name='Independent format fixture')
        self.suite = EvaluationSuiteVersion.objects.create(tenant_id=self.tenant.pk, suite=suite,
            scorer_type='exact_match', cases=[{'case_id': 'held', 'source_group_id': 'protected',
                'input_prompt': 'ef', 'expected_output': 'impossible-negative-control'}])
        self.config = {'base_model_version': str(self.base.model_version_id), 'runner_manifest': self.runner.pk,
            'training_pool': self.pool.pk, 'training_budget': str(self.policy.policy_id),
            'evaluation_suite': str(self.suite.suite_version_id), 'evaluation_pool': self.evaluator.pool_id,
            'evaluation_budget': str(self.case_policy.policy_id), 'steps_per_cycle': 2,
            'max_training_steps': 4, 'max_evaluation_cases': 2, 'min_accuracy': 0, 'max_tokens': 2}
        # Negative-control outputs score zero. Threshold0 tests orchestration only, not task quality.

    def create(self, **changes):
        response = self.client.post('/api/v1/labeling-campaigns/', {'name': 'Real labels', 'kind': 'classification',
            'classes': ['a', 'b'], 'max_cycles': 2, 'budget_limit_dollars': 0,
            'source_revision': str(self.source.revision_id), 'cycle': self.config, **changes}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def open_and_review(self, campaign):
        response = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {'limit': 1}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        batch = response.data
        tasks = self.client.get(f'/api/v1/labeling-batches/{batch["batch_id"]}/tasks/').data['results']
        self.assertEqual(len(tasks), 1); self.assertNotEqual(tasks[0]['content']['source_group_id'], 'protected')
        response = self.client.post(f'/api/v1/annotation-tasks/{tasks[0]["task_id"]}/review/',
            {'decision': 'corrected', 'human_label': {'label': 'a'}, 'expected_revision': 1}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return batch

    def close(self, batch):
        return self.client.post(f'/api/v1/labeling-batches/{batch["batch_id"]}/close/', {}, format='json')

    def advance(self, campaign):
        return self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/advance/', {}, format='json')

    def execute(self, worker, executor):
        descriptor = claim_job(worker); self.assertIsNotNone(descriptor)
        outcome = execute_claim(worker, descriptor, executor)
        self.assertEqual(outcome['status'], 'succeeded', outcome)

    def train_and_evaluate(self, campaign, snapshot):
        self.execute(self.worker, training_worker_executor)
        response = self.advance(campaign); self.assertEqual(response.status_code, 200, response.data)
        snapshot.refresh_from_db(); self.assertIsNotNone(snapshot.evaluation_run_id)
        self.execute(self.evaluator, evaluation_worker_executor)
        response = self.advance(campaign); self.assertEqual(response.status_code, 200, response.data)
        snapshot.refresh_from_db()
        return response.data

    def test_two_real_cycles_are_budgeted_independent_repeat_safe_and_keep_history(self):
        campaign = self.create()
        self.assertIn('protected', campaign['configuration']['protected_source_groups'])
        first = self.open_and_review(campaign)
        closed = self.close(first); self.assertEqual(closed.status_code, 200, closed.data)
        snapshot = CumulativeSnapshot.objects.get(snapshot_id=closed.data['snapshot_id'])
        self.assertIsNotNone(snapshot.training_run_id)
        self.assertEqual(self.close(first).data['training_run_id'], closed.data['training_run_id'])
        self.assertEqual(TrainingRun.objects.count(), 1)
        self.assertEqual(self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {'limit': 1}, format='json').status_code, 409)
        campaign = self.train_and_evaluate(campaign, snapshot)
        self.assertEqual(snapshot.qualification['decision'], 'promoted')
        first_model = campaign['active_model_id']
        second = self.open_and_review(campaign)
        self.assertEqual(second['drafting_model_id'], first_model)
        self.assertEqual(second['draft_configuration']['prompt'], '{text}\n')
        closed = self.close(second); self.assertEqual(closed.status_code, 200, closed.data)
        snapshot2 = CumulativeSnapshot.objects.get(snapshot_id=closed.data['snapshot_id'])
        self.assertEqual(snapshot2.item_count, 2)
        campaign = self.train_and_evaluate(campaign, snapshot2)
        self.assertEqual(campaign['status'], 'completed')
        self.assertEqual(TrainingRun.objects.count(), 2)
        self.assertEqual(BudgetReservation.objects.filter(policy=self.policy).count(), 2)
        self.assertEqual(sum(BudgetReservation.objects.filter(policy=self.policy).values_list('settled_amount', flat=True)), 4)
        self.assertEqual(snapshot.training_run.status, 'completed')
        self.assertEqual(snapshot.evaluation_run.case_results.count(), 1)

    def test_budget_failure_rolls_back_closure_and_keeps_approved_reviews(self):
        campaign = self.create(); batch = self.open_and_review(campaign)
        self.policy.limit_amount = 1; self.policy.save()
        result = self.close(batch); self.assertEqual(result.status_code, 400, result.content)
        self.assertEqual(CumulativeSnapshot.objects.count(), 0); self.assertEqual(TrainingRun.objects.count(), 0)
        self.assertEqual(CampaignBatch.objects.get(batch_id=batch['batch_id']).tasks.filter(status='completed').count(), 1)

    def test_pause_cancels_queued_work_without_losing_labels_and_blocks_advancement(self):
        campaign = self.create(); batch = self.open_and_review(campaign)
        response = self.close(batch); self.assertEqual(response.status_code, 200, response.data)
        result = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/lifecycle/', {'transition': 'pause'}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        snapshot = CumulativeSnapshot.objects.get(); snapshot.training_run.refresh_from_db()
        self.assertEqual(snapshot.training_run.status, 'cancelled'); self.assertEqual(snapshot.item_count, 1)
        self.assertEqual(self.advance(campaign).status_code, 400)
        self.assertEqual(BudgetReservation.objects.get(policy=self.policy).state, 'settled')

    def test_changed_suite_and_unpriced_dollar_ceiling_refuse_before_dispatch(self):
        result = self.client.post('/api/v1/labeling-campaigns/', {'name': 'Unsafe', 'kind': 'classification',
            'classes': ['a'], 'source_revision': str(self.source.revision_id), 'cycle': self.config}, format='json')
        self.assertEqual(result.status_code, 400)
        campaign = self.create(); batch = self.open_and_review(campaign)
        self.suite.cases[0]['expected_output'] = 'changed'; self.suite.save()
        self.assertEqual(self.close(batch).status_code, 400)
        self.assertEqual(TrainingRun.objects.count(), 0)

    def test_real_failed_gate_retains_prior_model_and_roll_back_keeps_history(self):
        self.config['min_accuracy'] = 1
        campaign = self.create(seed_mode='existing_model', drafting_model_id=str(self.base.model_version_id))
        batch = self.open_and_review(campaign); response = self.close(batch)
        self.assertEqual(response.status_code, 200, response.content)
        snapshot = CumulativeSnapshot.objects.get()
        campaign = self.train_and_evaluate(campaign, snapshot)
        self.assertEqual(snapshot.qualification['decision'], 'rejected')
        self.assertEqual(campaign['active_model_id'], str(self.base.model_version_id))
        self.assertEqual(snapshot.item_count, 1)

    def test_regression_is_rejected_even_when_absolute_threshold_passes(self):
        campaign = self.create(seed_mode='existing_model', drafting_model_id=str(self.base.model_version_id))
        batch = self.open_and_review(campaign); self.assertEqual(self.close(batch).status_code, 200)
        self.execute(self.worker, training_worker_executor)
        self.assertEqual(self.advance(campaign).status_code, 200)
        self.execute(self.evaluator, evaluation_worker_executor)
        snapshot = CumulativeSnapshot.objects.get(); evaluation = snapshot.evaluation_run
        # Controlled recorded outcomes isolate non-regression from the absolute threshold.
        EvaluationMetric.objects.filter(run=evaluation, key='accuracy', slice_name='all').update(value=0.5)
        evaluation.protocol_ref['baseline_metrics'][0]['value'] = 1.0
        evaluation.save(update_fields=['protocol_ref'])
        response = self.advance(campaign); self.assertEqual(response.status_code, 200, response.content)
        snapshot.refresh_from_db(); self.assertEqual(snapshot.qualification['decision'], 'rejected')
        self.assertEqual(response.data['active_model_id'], str(self.base.model_version_id))

    def test_explicit_rollback_changes_future_assignment_without_losing_labels(self):
        campaign = self.create(); batch = self.open_and_review(campaign)
        self.assertEqual(self.close(batch).status_code, 200)
        snapshot = CumulativeSnapshot.objects.get(); campaign = self.train_and_evaluate(campaign, snapshot)
        response = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/rollback/',
            {'model_version_id': str(self.base.model_version_id)}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['active_model_id'], str(self.base.model_version_id))
        snapshot.refresh_from_db(); self.assertEqual(snapshot.item_count, 1)
        self.assertEqual(snapshot.qualification['decision'], 'promoted')
        second = self.open_and_review(response.data)
        self.assertEqual(second['drafting_model_id'], str(self.base.model_version_id))

    def test_step_cap_blocks_new_dispatch_and_viewer_cannot_advance(self):
        self.config['max_training_steps'] = 2
        campaign = self.create(); batch = self.open_and_review(campaign)
        self.assertEqual(self.close(batch).status_code, 200)
        snapshot = CumulativeSnapshot.objects.get(); campaign = self.train_and_evaluate(campaign, snapshot)
        second = self.open_and_review(campaign)
        self.assertEqual(self.close(second).status_code, 400)
        self.assertEqual(TrainingRun.objects.count(), 1)
        self.assertEqual(CumulativeSnapshot.objects.count(), 1)
        ApiKey.objects.filter(tenant=self.tenant).update(role=Role.VIEWER)
        self.assertEqual(self.advance(campaign).status_code, 403)
