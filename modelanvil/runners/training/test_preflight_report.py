"""Qualified fixtures, no-allocation failures and changed-preview admission."""
import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings
from modelanvil.budgets.models import BudgetReservation
from modelanvil.jobs.models import Job
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training import test_cpu_runtime as cpu
from modelanvil.runners.training.runtime import resolve_inputs


@override_settings(ALLOWED_HOSTS=['testserver'])
class PreflightReportTests(TestCase):
    setUp = cpu.CpuRuntimeTests.setUp
    artifact = cpu.CpuRuntimeTests.artifact
    envelope = cpu.CpuRuntimeTests.envelope
    payload = cpu.CpuRuntimeTests.payload
    execute = cpu.CpuRuntimeTests.execute

    def preview(self, **changes):
        response = self.client.post('/api/v1/training-runs/preflight/', {**self.payload(), **changes}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def launch(self, payload, key='preview'):
        return self.client.post('/api/v1/training-runs/', payload, format='json', HTTP_IDEMPOTENCY_KEY=key)

    def assert_no_allocation(self):
        self.assertEqual(TrainingRun.all_objects.count(), 0)
        self.assertEqual(Job.all_objects.count(), 0)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_actual_sample_preview_requirements_budget_and_unknown_estimates(self):
        report = self.preview()
        actual = resolve_inputs(dataset=self.dataset, base=self.base, tokenizer=self.tok, runner=self.runner,
                                pool=self.pool, steps=4, tenant=self.tenant.pk, project=None)
        self.assertEqual(report['samples'][0]['token_ids'], actual['samples'][0]['token_ids'])
        self.assertEqual(report['samples'][0]['text_preview'], actual['samples'][0]['text'])
        self.assertEqual(report['status'], 'approved')
        self.assertEqual(report['requirements']['memory_bytes'], cpu.LIMITS['memory_bytes'])
        self.assertGreater(report['requirements']['storage_bytes'], 0)
        self.assertEqual(report['budget']['remaining'], '100.000000')
        self.assertEqual(report['estimate']['total_tokens'], 36)
        self.assertFalse(report['estimate']['known'])
        self.assertFalse(report['estimate']['estimated_cost']['known'])
        self.assertIsNone(report['estimate']['currency'])
        self.assertTrue(report['preflight_token'])
        self.assert_no_allocation()

    def test_incompatible_reference_fixtures_never_allocate(self):
        cases = [('recipe_type', 'lora_adapter'), ('dataset_revision', None), ('runner_manifest', None),
                 ('base_model_version', None), ('pool', None), ('budget_policy_id', None)]
        for field, value in cases:
            with self.subTest(field=field):
                # Nullable model fields may validate, while required/scoped IDs fail at the boundary.
                response = self.client.post('/api/v1/training-runs/preflight/', {**self.payload(), field: value}, format='json')
                if response.status_code == 200:
                    self.assertEqual(response.data['status'], 'blocked')
                    self.assertTrue(all(c['corrective_action'] for c in response.data['checks'] if c['blocking']))
                else:
                    self.assertEqual(response.status_code, 400)
                self.assertEqual(self.launch({**self.payload(), field: value}).status_code, 400)
                self.assert_no_allocation()

    def test_simultaneous_capacity_budget_and_storage_failures_are_actionable(self):
        self.worker.slots = 0; self.worker.save()
        self.policy.limit_amount = 1; self.policy.save()
        with patch('modelanvil.runners.training.preflight_report.storage_capacity', return_value={'artifacts': {'available_bytes': 0}}):
            report = self.preview()
            self.assertTrue({'worker-slots', 'budget', 'storage'}.issubset(report['blocking_checks']))
            self.assertTrue(all(c['corrective_action'] for c in report['checks'] if c['blocking']))
            self.assertEqual(self.launch(self.payload()).status_code, 400)
        self.assert_no_allocation()

    def test_memory_failure_and_unknown_storage_block(self):
        self.worker.capabilities['memory_bytes'] = 1; self.worker.save()
        with patch('modelanvil.runners.training.preflight_report.storage_capacity', side_effect=OSError('offline volume')):
            report = self.preview()
        self.assertTrue({'worker-memory', 'worker-slots', 'storage'}.issubset(report['blocking_checks']))
        self.assertIsNone(report['preflight_token'])
        self.assert_no_allocation()

    def test_changed_configuration_and_revision_reject_preview_token(self):
        report = self.preview()
        payload = {**self.payload(), 'preflight_token': report['preflight_token']}
        self.assertEqual(self.launch({**payload, 'total_steps': 5}).status_code, 400)
        # The base may still resolve, but a changed selected revision requires a new preview.
        self.base.metadata = {'changed': True}; self.base.save()
        self.assertEqual(self.launch(payload).status_code, 400)
        self.assert_no_allocation()

    def test_launch_rechecks_capacity_budget_storage_and_disabled_runner(self):
        proof = self.preview()['preflight_token']
        payload = {**self.payload(), 'preflight_token': proof}
        self.worker.slots = 0; self.worker.save()
        self.assertEqual(self.launch(payload).status_code, 400)
        self.worker.slots = 1; self.worker.save()
        self.policy.limit_amount = 1; self.policy.save()
        self.assertEqual(self.launch(payload).status_code, 400)
        self.policy.limit_amount = 100; self.policy.save()
        with patch('modelanvil.runners.training.preflight_report.storage_capacity', return_value={'artifacts': {'available_bytes': 0}}):
            self.assertEqual(self.launch(payload).status_code, 400)
        self.runner.enabled = False; self.runner.save()
        self.assertEqual(self.launch(payload).status_code, 400)
        self.assert_no_allocation()

    def test_invalid_expired_token_and_safe_idempotent_replay(self):
        report = self.preview()
        payload = {**self.payload(), 'preflight_token': report['preflight_token']}
        self.assertEqual(self.launch({**payload, 'preflight_token': 'tampered'}).status_code, 400)
        with patch('django.core.signing.time.time', return_value=9999999999):
            self.assertEqual(self.launch(payload).status_code, 400)
        self.assert_no_allocation()
        first = self.launch(payload)
        self.assertEqual(first.status_code, 201, first.data)
        self.worker.slots = 0; self.worker.save()
        with patch('django.core.signing.time.time', return_value=9999999999):
            replay = self.launch(payload)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.data['run_id'], first.data['run_id'])
        self.assertEqual(Job.all_objects.count(), 1)
        self.assertEqual(BudgetReservation.all_objects.count(), 1)

    def test_measured_pilot_cpu_estimate_matches_committed_engine_metrics(self):
        response = self.launch(self.payload())
        self.assertEqual(response.status_code, 201, response.data)
        run = self.execute(TrainingRun.all_objects.get(run_id=response.data['run_id']))
        estimate = self.preview(total_steps=8)['estimate']
        self.assertTrue(estimate['known'])
        self.assertIn(str(run.run_id), estimate['source'])
        self.assertAlmostEqual(estimate['estimated_duration_seconds'], 2 * sum(m['cpu_seconds'] for m in run.metrics_log))
        self.assertFalse(estimate['estimated_cost']['known'])
        self.assertIn('unmeasured', estimate['assumptions'][-1])
        with patch('modelanvil.runners.training.preflight_report.checkpoint_bundle', side_effect=ValueError('corrupt')):
            self.assertFalse(self.preview()['estimate']['known'])

    def test_preflight_conceals_other_projects_and_rejects_other_principal(self):
        from modelanvil.identity.models import Project, Team, ApiKey, Role, generate_api_key
        from modelanvil.core.tenancy import set_active_project
        team = Team.objects.create(tenant_id=self.tenant.pk, name='Team', slug='team')
        source = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='Private source', slug='source')
        target = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='Target', slug='target')
        self.base.project = source; self.base.save()
        set_active_project(target.pk); self.addCleanup(set_active_project, None)
        response = self.client.post('/api/v1/training-runs/preflight/', self.payload(), format='json', HTTP_X_PROJECT_ID=str(target.pk))
        self.assertEqual(response.status_code, 400, response.content)
        set_active_project(None)
        report = self.preview()
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name='other engineer', role=Role.ENGINEER, secret_hash=hashed)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        response = self.launch({**self.payload(), 'preflight_token': report['preflight_token']})
        self.assertEqual(response.status_code, 400, response.content)
        self.assert_no_allocation()

    def test_malformed_and_cross_tenant_inputs_do_not_escape_validation(self):
        for body in [{'total_steps': 'bad'}, {'total_steps': 0}, {'total_steps': 3001},
                     {'pool': 'invalid'}, {'budget_policy_id': 'bad'}, {'base_model_version': 99999},
                     {'project': str(uuid.uuid4())}]:
            with self.subTest(body=body):
                response = self.client.post('/api/v1/training-runs/preflight/', body, format='json')
                self.assertEqual(response.status_code, 400, response.content)
        self.assert_no_allocation()
