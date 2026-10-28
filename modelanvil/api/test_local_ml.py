"""HTTP journeys that execute verified local tensors rather than echoing evaluation answers."""
import hashlib
import io
import json
import tempfile
import uuid
from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from modelanvil.artifacts.models import Artifact, Dataset
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.jobs.models import JobAttempt, Worker, WorkerPool, claim_job
from modelanvil.jobs.executor import execute_claim
from modelanvil.runners.models import AlignmentRun, EvaluationRun, Model, ModelVersion, RunnerManifest, TokenizerVersion, TrainingRun
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.runners.training.runtime import CONTRACT_DIGEST, LIMITS, digest, runner_manifest


class LocalMlApiTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(); self.addCleanup(storage.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': storage.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='local-ml', name='Local ML')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        secret, hashed = generate_api_key()
        self.key = ApiKey.objects.create(tenant=self.tenant, name='engineer', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        response = self.client.post('/api/v1/model-versions/initialize-cpu/', {'name': 'Actual initial CPU model', 'seed': 42}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.base = ModelVersion.all_objects.get(pk=response.data['model_version']['id'])
        self.tokenizer = self.base.tokenizer

    def suite(self, cases=None):
        response = self.client.post('/api/v1/evaluation-suites/', {'name': 'Pinned CPU checks'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        response = self.client.post('/api/v1/evaluation-suite-versions/', {'suite': response.data['id'] if 'id' in response.data else self._suite_pk(response.data['suite_id']), 'revision_no': 1, 'scorer_type': 'exact_match', 'cases': cases or [{'case_id': 'not-echoed', 'input_prompt': 'a', 'expected_output': 'ANSWER_IS_NOT_ECHOED', 'slice': 'all'}]}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['id']

    def _suite_pk(self, suite_id):
        from modelanvil.runners.models import EvaluationSuite
        return EvaluationSuite.all_objects.get(suite_id=suite_id).pk

    def pending_eval(self, candidate=None, baseline=None, cases=None):
        response = self.client.post('/api/v1/evaluation-runs/', {'suite_version': self.suite(cases), 'candidate_model_version': (candidate or self.base).pk, 'baseline_model_version': baseline.pk if baseline else None}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'pending')
        self.assertEqual(response.data['execution_evidence']['level'], 'configuration_only')
        return response.data['run_id']

    def test_initializer_commits_real_untrained_weights_without_qualification(self):
        artifact = Artifact.all_objects.get(artifact_id=self.base.artifact_manifest_id)
        self.assertEqual(artifact.state, Artifact.State.COMMITTED)
        self.assertEqual(self.base.state, ModelVersion.State.DRAFT)
        self.assertFalse(self.base.metadata['trained'])
        from modelanvil.runners.local_execution import load_character_bundle
        bundle, _, verification = load_character_bundle(self.base, tenant=self.tenant.pk, project=None)
        self.assertTrue(verification['is_loadable'])
        self.assertFalse(verification['production_qualified'])
        self.assertEqual(bundle['provenance.json']['initialization_seed'], 42)
        duplicate = self.client.post('/api/v1/model-versions/initialize-cpu/', {'name': self.base.model.name}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(Model.all_objects.count(), 1)
        self.assertEqual(TokenizerVersion.all_objects.count(), 1)

    def test_model_eligibility_requires_verified_bytes_and_supports_installed_transformer_base(self):
        data = self.client.get(f'/api/v1/model-versions/{self.base.model_version_id}/').data
        self.assertTrue(data['capabilities']['train']['eligible'])
        self.assertTrue(data['capabilities']['evaluate']['eligible'])
        self.assertFalse(data['capabilities']['production_qualified'])
        self.assertTrue(data['capabilities']['chat']['eligible'])
        artifact = Artifact.all_objects.get(artifact_id=self.base.artifact_manifest_id)
        Artifact.all_objects.filter(pk=artifact.pk).update(state='staging')
        self.assertFalse(self.client.get(f'/api/v1/model-versions/{self.base.model_version_id}/').data['capabilities']['train']['eligible'])
        response = self.client.post('/api/v1/model-versions/initialize-cpu/',
            {'name': 'Verified byte transformer', 'profile': 'cpu-transformer', 'seed': 0}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['model_version']['capabilities']['train']['eligible'])
        version = ModelVersion.all_objects.get(pk=response.data['model_version']['id'])
        self.assertEqual(version.tokenizer.vocabulary_size, 260)
        self.assertEqual(version.metadata['initialization_seed'], 0)

    def test_actual_evaluation_scores_inference_not_expected_answers_and_is_repeat_safe(self):
        run_id = self.pending_eval(baseline=self.base)
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {'max_tokens': 4}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'completed')
        self.assertEqual(response.data['execution_evidence']['level'], 'integrated_execution')
        self.assertFalse(response.data['execution_evidence']['production_qualified'])
        metric = response.data['metrics'][0]
        self.assertEqual(metric['sample_count'], 1)  # The "all" slice is not counted twice.
        self.assertEqual(metric['value'], 0)
        self.assertGreater(metric['uncertainty_interval']['upper'], 0)
        self.assertEqual(response.data['baseline_metrics'][0]['sample_count'], 1)
        cases = self.client.get(f'/api/v1/evaluation-runs/{run_id}/cases/').data['results']
        self.assertEqual(cases[0]['candidate_output'], '')  # Initial zero head chooses EOS.
        self.assertNotEqual(cases[0]['candidate_output'], cases[0]['expected_output'])
        self.assertEqual(cases[0]['baseline_output'], '')
        again = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(EvaluationRun.all_objects.get(run_id=run_id).case_results.count(), 1)
        self.assertEqual(self.client.patch(f'/api/v1/evaluation-runs/{run_id}/', {'baseline_model_version': None}, format='json').status_code, 400)

    def test_corrupt_uncommitted_foreign_and_unsupported_weights_never_create_scores(self):
        run_id = self.pending_eval()
        artifact = Artifact.all_objects.get(artifact_id=self.base.artifact_manifest_id)
        from pathlib import Path
        artifact_path = Path(settings.MODELANVIL['artifact_root']) / str(self.tenant.pk) / artifact.object_key
        artifact_path.write_bytes(b'corrupted bytes')
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        run = EvaluationRun.all_objects.get(run_id=run_id)
        self.assertEqual(run.status, 'pending'); self.assertEqual(run.case_results.count(), 0); self.assertEqual(run.metrics.count(), 0)
        Artifact.all_objects.filter(pk=artifact.pk).update(state=Artifact.State.STAGING)
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json').status_code, 400)
        Artifact.all_objects.filter(pk=artifact.pk).update(state=Artifact.State.COMMITTED)
        other = Tenant.objects.create(slug='foreign-local-ml', name='Other')
        Artifact.all_objects.filter(pk=artifact.pk).update(tenant_id=other.pk)
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json').status_code, 400)
        self.base.architecture_ref = 'unsupported-transformer'; self.base.save()
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json').status_code, 400)
        self.assertEqual(run.case_results.count(), 0)

    def test_viewer_cannot_initialize_or_execute(self):
        run_id = self.pending_eval()
        self.key.role = Role.VIEWER; self.key.save(update_fields=['role'])
        response = self.client.post('/api/v1/model-versions/initialize-cpu/', {'name': 'Viewer base'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json').status_code, 403)

    def test_project_scoped_execute_rejects_foreign_run_and_cross_project_pin(self):
        run_id = self.pending_eval()
        team = Team.objects.create(tenant_id=self.tenant.pk, name='Team', slug='team')
        home = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='Home', slug='home')
        away = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='Away', slug='away')
        run = EvaluationRun.all_objects.get(run_id=run_id)
        run.project = away; run.save()
        self.key.project = home; self.key.save(update_fields=['project'])
        self.assertEqual(self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json').status_code, 404)
        run.project = home; run.save()
        run.suite_version.project = away; run.suite_version.save()
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {}, format='json')
        self.assertEqual(response.status_code, 400, response.json())
        run.refresh_from_db(); self.assertEqual(run.status, 'pending'); self.assertEqual(run.metrics.count(), 0)

    def test_atomic_suite_registration_leaves_no_orphan_on_invalid_cases(self):
        from modelanvil.runners.models import EvaluationSuite, EvaluationSuiteVersion
        invalid = self.client.post('/api/v1/evaluation-suites/register-cpu/', {'name': 'Invalid', 'cases': []}, format='json')
        self.assertEqual(invalid.status_code, 400); self.assertEqual(EvaluationSuite.all_objects.count(), 0)
        payload = {'name': 'Registered', 'protected_role': 'protected_eval', 'cases': [{'case_id': 'one', 'input_prompt': '', 'expected_output': '', 'source_group_id': 'held-out'}]}
        response = self.client.post('/api/v1/evaluation-suites/register-cpu/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data); self.assertEqual(response.data['cases_count'], 1)
        duplicate = self.client.post('/api/v1/evaluation-suites/register-cpu/', payload, format='json')
        self.assertEqual(duplicate.status_code, 400); self.assertEqual(EvaluationSuite.all_objects.count(), 1); self.assertEqual(EvaluationSuiteVersion.all_objects.count(), 1)

    def test_browser_suite_import_versions_role_and_source_groups(self):
        from modelanvil.runners.models import EvaluationSuite, EvaluationSuiteVersion
        missing = self.client.post('/api/v1/evaluation-suites/register-cpu/', {
            'name': 'Held out', 'protected_role': 'protected_eval',
            'cases': [{'case_id': 'one', 'input_prompt': 'a', 'expected_output': 'b'}]}, format='json')
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(EvaluationSuite.all_objects.count(), 0)
        wrong_role = self.client.post('/api/v1/evaluation-suites/register-cpu/', {
            'name': 'Held out', 'protected_role': 'training',
            'cases': [{'case_id': 'one', 'input_prompt': 'a', 'expected_output': 'b', 'source_group_id': 'g1'}]}, format='json')
        self.assertEqual(wrong_role.status_code, 400)
        numeric = self.client.post('/api/v1/evaluation-suites/register-cpu/', {
            'name': 'Numbers', 'protected_role': 'protected_eval', 'scorer_type': 'numeric_tolerance',
            'cases': [{'case_id': 'one', 'input_prompt': 'a', 'expected_output': 'nope', 'source_group_id': 'g1'}]}, format='json')
        self.assertEqual(numeric.status_code, 400)
        self.assertIn('numeric', str(numeric.json()).lower())
        payload = {'name': 'Held out', 'protected_role': 'protected_eval', 'cases': [
            {'case_id': 'one', 'input_prompt': 'a', 'expected_output': 'b', 'source_group_id': 'group-a', 'slice': 'held-out'}]}
        first = self.client.post('/api/v1/evaluation-suites/register-cpu/', payload, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data['protected_role'], 'protected_eval')
        self.assertEqual(first.data['revision_no'], 1)
        self.assertEqual(first.data['source_group_count'], 1)
        same = self.client.post('/api/v1/evaluation-suites/register-cpu/', {**payload, 'suite': first.data['suite']}, format='json')
        self.assertEqual(same.status_code, 200, same.data)
        self.assertEqual(same.data['id'], first.data['id'])
        self.assertEqual(EvaluationSuiteVersion.all_objects.count(), 1)
        nxt = self.client.post('/api/v1/evaluation-suites/register-cpu/', {**payload, 'suite': first.data['suite'], 'cases': [
            {'case_id': 'two', 'input_prompt': 'c', 'expected_output': 'd', 'source_group_id': 'group-b'}]}, format='json')
        self.assertEqual(nxt.status_code, 201, nxt.data)
        self.assertEqual(nxt.data['revision_no'], 2)
        self.assertEqual(nxt.data['suite'], first.data['suite'])
        self.assertEqual(nxt.data['protected_role'], 'protected_eval')
        self.assertEqual(EvaluationSuite.all_objects.count(), 1)

    def test_suite_validation_and_pins_remain_immutable(self):
        suite_id = self.suite()
        from modelanvil.runners.models import EvaluationSuiteVersion
        suite = EvaluationSuiteVersion.all_objects.get(pk=suite_id)
        response = self.client.post('/api/v1/evaluation-suite-versions/', {'suite': suite.suite_id, 'revision_no': 2, 'cases': [{'case_id': 'same', 'input_prompt': 'a', 'expected_output': 'b'}, {'case_id': 'same', 'input_prompt': 'c', 'expected_output': 'd'}]}, format='json')
        self.assertEqual(response.status_code, 400)
        for method in (self.client.patch, self.client.delete):
            self.assertEqual(method(f'/api/v1/evaluation-suite-versions/{suite.suite_version_id}/', {}, format='json').status_code, 405)

    def test_alignment_plan_truthfully_rejects_execution_and_stays_pending(self):
        response = self.client.post('/api/v1/alignment-runs/', {'algorithm': 'dpo', 'policy_model_version': self.base.pk, 'reference_model_version': self.base.pk, 'dataset_manifest_digest': 'a' * 64, 'held_out_validation_digest': 'b' * 64, 'total_steps': 5}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['execution_capabilities']['can_execute'])
        self.assertEqual(response.data['execution_evidence']['level'], 'configuration_only')
        run_id = response.data['run_id']
        self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{run_id}/execute/', {}, format='json').status_code, 400)
        run = AlignmentRun.all_objects.get(run_id=run_id)
        self.assertEqual(run.current_step, 0); self.assertEqual(run.latest_metrics, {}); self.assertIsNone(run.output_model_version_id)

    def test_initialized_base_to_published_text_worker_candidate_and_real_eval(self):
        rows = [{'schema_version': '1.0', 'sample_id': str(uuid.uuid4()), 'source_group_id': str(i), 'blocks': [{'block_id': 'text', 'type': 'text', 'text': 'ab ab ab'}], 'provenance': {'source_snapshot_ref': 'test', 'source_record_key': str(i), 'content_sha256': hashlib.sha256(b'ab ab ab').hexdigest()}} for i in range(2)]
        raw = b''.join(json.dumps(row).encode() + b'\n' for row in rows)
        artifact = Artifact.objects.create(tenant_id=self.tenant.pk, storage_location_id='local', object_key='samples.jsonl', sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type='application/x-ndjson')
        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
        dataset = Dataset.objects.create(tenant_id=self.tenant.pk, name='Published actual text')
        revision = publish_prepared_dataset(dataset, artifact, validation_percent=0, test_percent=0)
        manifest = runner_manifest()
        runner = RunnerManifest.objects.create(tenant_id=self.tenant.pk, name='Actual CPU contract', version='1', manifest=manifest, digest=digest(manifest), compatibility={'contract_digest': CONTRACT_DIGEST})
        pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='CPU', queue_name='cpu')
        worker = Worker.objects.create(tenant_id=self.tenant.pk, name='Local CPU', pool=pool, slots=1, capabilities={'training_runtime': CONTRACT_DIGEST, 'memory_bytes': LIMITS['memory_bytes']})
        policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name='Steps', period='lifetime', unit='training_steps', limit_amount=100)
        payload = {'recipe_type': 'full_sft', 'tokenizer_version': self.tokenizer.pk, 'base_model_version': self.base.pk, 'dataset_revision': revision.pk, 'runner_manifest': runner.pk, 'pool': pool.pk, 'budget_policy_id': str(policy.policy_id), 'total_steps': 2}
        preflight = self.client.post('/api/v1/training-runs/preflight/', payload, format='json')
        self.assertEqual(preflight.status_code, 200, preflight.data); self.assertEqual(preflight.data['status'], 'approved')
        response = self.client.post('/api/v1/training-runs/', {**payload, 'preflight_token': preflight.data['preflight_token']}, format='json', HTTP_IDEMPOTENCY_KEY='local-ml-journey')
        self.assertEqual(response.status_code, 201, response.data)
        training = TrainingRun.all_objects.get(run_id=response.data['run_id'])
        outcome = execute_claim(worker, claim_job(worker), training_worker_executor)
        self.assertEqual(outcome['status'], JobAttempt.Status.SUCCEEDED)
        training.refresh_from_db(); self.assertEqual(training.status, 'completed')
        self.assertNotEqual(training.output_model_version.metadata['weights_sha256'], self.base.metadata['weights_sha256'])
        run_id = self.pending_eval(candidate=training.output_model_version, baseline=self.base)
        response = self.client.post(f'/api/v1/evaluation-runs/{run_id}/execute/', {'max_tokens': 4}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['protocol_ref']['pins']['candidate_weights_sha256'], training.output_model_version.metadata['weights_sha256'])
        self.assertEqual(response.data['metrics'][0]['sample_count'], 1)
