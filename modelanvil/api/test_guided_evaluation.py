"""Native-profile boundaries, protected classification data and historical evidence."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from modelanvil.api import test_activation as activation_fixture
from modelanvil.runners import guided_evaluation as guided
from modelanvil.runners.eval_worker import LEGACY_CPU_BUILD, verified_evaluation_inputs


class ClassificationTests(SimpleTestCase):
    def test_reviewed_native_manifest_detects_corrupt_weights_and_review(self):
        from modelanvil.releases.review import write_guided_evidence
        from scripts.native_adapter_infer import verify
        raw = b'checked weights'
        files = {'model.safetensors': {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw)}}
        review = {'candidate_model_version': 'candidate', 'evaluation_run': 'evaluation'}
        resources = {'evaluation': {'execution_seconds': 2.5, 'usage': []}, 'peak_memory_bytes': None}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive_path = directory / 'candidate.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('model.safetensors', raw)
                write_guided_evidence(archive, files, review, resource_usage=resources)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(directory)
            self.assertEqual(verify(directory)['candidate'], 'candidate')
            (directory / 'resource-usage.json').write_text('{}')
            with self.assertRaisesMessage(ValueError, 'resource usage checksum'): verify(directory)
            (directory / 'resource-usage.json').write_text(json.dumps(resources, sort_keys=True, indent=2))
            (directory / 'model.safetensors').write_bytes(b'corrupt weights')
            with self.assertRaises(ValueError): verify(directory)
            (directory / 'model.safetensors').write_bytes(raw)
            (directory / 'review.json').write_text('{}')
            with self.assertRaisesMessage(ValueError, 'review checksum'): verify(directory)

    def test_suite_uses_only_original_test_rows_and_full_task_labels(self):
        rows = [{'sample_id': str(index), 'source_group_id': str(index), 'blocks': [
            {'type': 'text', 'role': 'user', 'text': f'route {index}'},
            {'type': 'text', 'role': 'assistant', 'text': label}]} for index, label in enumerate(['billing', 'access', 'billing'])]
        raw = json.dumps({'rows': rows, 'split_manifest': {'train': ['0'], 'validation': ['1'], 'test': ['2']}}).encode()
        training = SimpleNamespace(tenant_id=1, project_id=2,
            dataset_revision=SimpleNamespace(manifest_artifact=object(), manifest_digest=hashlib.sha256(raw).hexdigest()))
        with patch.object(guided, 'read_artifact', return_value=raw), patch.object(guided, 'check_resource_access', return_value=True):
            cases, labels = guided.held_out_cases(training)
        self.assertEqual([case['case_id'] for case in cases], ['2'])
        self.assertEqual(labels, ['access', 'billing'])
        bad = json.dumps({'rows': rows, 'split_manifest': {'train': ['0', '2'], 'validation': ['1'], 'test': []}}).encode()
        training.dataset_revision.manifest_digest = hashlib.sha256(bad).hexdigest()
        with patch.object(guided, 'read_artifact', return_value=bad), patch.object(guided, 'check_resource_access', return_value=True):
            with self.assertRaisesMessage(ValueError, '1–64'):
                guided.held_out_cases(training)

    def test_native_case_preserves_system_and_history_and_exact_label(self):
        row = {'sample_id': 'held-out', 'source_group_id': 'g1', 'blocks': [
            {'type': 'text', 'role': 'system', 'text': 'Reply with billing or support.'},
            {'type': 'text', 'role': 'user', 'text': 'Where is my invoice?'},
            {'type': 'text', 'role': 'assistant', 'text': 'billing'}]}
        case = guided.classification_case(row)
        self.assertEqual(case['messages'], [{'role': b['role'], 'content': b['text']} for b in row['blocks'][:-1]])
        self.assertEqual(case['expected_output'], 'billing')
        for text in ('billing\nsupport', ' billing', 'x' * 65):
            row['blocks'][-1]['text'] = text
            with self.assertRaises(ValueError): guided.classification_case(row)

    def test_classification_bounds_and_invalid_predictions_count_as_errors(self):
        for labels in ([], ['one'], ['one', 'one'], ['one', {}], list('abcdefghi')):
            with self.assertRaises(ValueError): guided.classification_labels(labels)
        result = guided.classification_metrics([
            {'expected_output': 'a', 'candidate_output': 'a'}, {'expected_output': 'b', 'candidate_output': 'a'},
            {'expected_output': 'b', 'candidate_output': 'not a label'}], ['a', 'b'])
        self.assertEqual(result['confusion_matrix'], [[1, 0, 0], [1, 0, 1]])
        self.assertEqual(result['accuracy'], 1 / 3)
        self.assertEqual(result['macro_f1'], 1 / 3)

    def test_loaded_native_session_is_reused_and_base_disables_adapter(self):
        state = {'base': False, 'loads': 0, 'formats': []}
        class Model:
            @contextmanager
            def disable_adapter(self):
                state['base'] = True
                try: yield
                finally: state['base'] = False
        @contextmanager
        def session(*args, **kwargs):
            state['loads'] += 1
            self.assertEqual(kwargs['device'], 'mps:0')
            yield {'device': 'mps:0', 'model': Model()}
        def generate(_session, messages, **kwargs):
            state['formats'].append(kwargs['prompt_format'])
            yield {'text': 'base' if state['base'] else 'adapter'}
        run = SimpleNamespace(candidate_model_version=object(), tenant_id=1, project_id=2)
        context = SimpleNamespace(heartbeat=lambda: True)
        case = {'input_prompt': 'route this'}
        with patch.object(guided, 'native_pair'), patch('modelanvil.runners.inference.local_session', session), patch('modelanvil.runners.inference.generate', generate):
            with guided.native_predictors(run, 32, context) as predict:
                for _ in range(2):
                    self.assertEqual(predict(case), 'adapter')
                    self.assertEqual(predict(case, baseline=True), 'base')
        self.assertEqual(state['loads'], 1)
        self.assertEqual(state['formats'], ['model'] * 4)
        self.assertFalse(state['base'])


class HistoricalEvaluationTests(TestCase):
    artifact = activation_fixture.ActivationTests.artifact
    envelope = activation_fixture.ActivationTests.envelope
    payload = activation_fixture.ActivationTests.payload
    launch = activation_fixture.ActivationTests.launch
    execute = activation_fixture.ActivationTests.execute
    suite = activation_fixture.ActivationTests.suite
    _suite_pk = activation_fixture.ActivationTests._suite_pk
    pending_eval = activation_fixture.ActivationTests.pending_eval
    queued = activation_fixture.ActivationTests.queued

    def setUp(self):
        activation_fixture.ActivationTests.setUp(self)

    def test_known_cpu_evidence_survives_but_unknown_build_and_changed_bytes_fail(self):
        run = self.evaluation
        pins = run.protocol_ref['pins']
        pins['build_digest'] = pins['environment']['build_digest'] = LEGACY_CPU_BUILD
        run.save()
        self.assertEqual(verified_evaluation_inputs(run)['pins'], pins)
        response = self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers).status_code, 200)
        pins['build_digest'] = pins['environment']['build_digest'] = '0' * 64
        with self.assertRaises(ValueError): verified_evaluation_inputs(run)
        pins['build_digest'] = pins['environment']['build_digest'] = LEGACY_CPU_BUILD
        pins['candidate']['sha256'] = '0' * 64
        with self.assertRaises(ValueError): verified_evaluation_inputs(run)

    def test_guided_preparation_refuses_non_guided_training_without_jobs_or_allowances(self):
        from modelanvil.budgets.models import BudgetPolicy
        from modelanvil.jobs.models import Job
        from modelanvil.runners.models import TrainingRun
        training = TrainingRun.all_objects.get(output_model_version=self.candidate)
        counts = (Job.all_objects.count(), BudgetPolicy.all_objects.count())
        response = self.client.post(f'/api/v1/training-runs/{training.run_id}/prepare-evaluation/', {}, format='json', **self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual((Job.all_objects.count(), BudgetPolicy.all_objects.count()), counts)

    def test_resource_report_uses_actual_timing_and_ledger_units_and_leaves_unknown_cost_unavailable(self):
        from modelanvil.core.activation import evaluation_resources
        measured = evaluation_resources(self.evaluation)
        self.assertGreaterEqual(measured['evaluation']['execution_seconds'], 0)
        self.assertGreaterEqual(measured['training']['execution_seconds'], 0)
        self.assertEqual(measured['evaluation']['usage'][0]['unit'], 'evaluation_cases')
        self.assertEqual(measured['training']['usage'][0]['unit'], 'training_steps')
        self.assertIsNone(measured['evaluation']['usage'][0]['amount'])
        self.assertIsNone(measured['evaluation']['usage'][0]['currency'])
        self.assertIsNone(measured['peak_memory_bytes'])
        self.evaluation.job = None
        self.assertEqual(evaluation_resources(self.evaluation)['evaluation'],
            {'queue_seconds': None, 'execution_seconds': None, 'usage_available': False, 'usage': []})


class GuidedExecutionTests(TestCase):
    from modelanvil.api.test_durable_evaluation import DurableEvaluationTests as fixture
    artifact = fixture.artifact
    envelope = fixture.envelope
    payload = fixture.payload
    launch = fixture.launch
    execute = fixture.execute
    suite = fixture.suite
    _suite_pk = fixture._suite_pk
    pending_eval = fixture.pending_eval

    def setUp(self):
        self.fixture.setUp(self)

    def prepared(self):
        from modelanvil.runners.models import EvaluationRun
        from modelanvil.runners.eval_worker import queue_evaluation
        cases = [{'case_id': str(i), 'source_group_id': f'held-out-{i}', 'input_prompt': 'x',
            'expected_output': label, 'slice': label} for i, label in enumerate(['billing', 'access'])]
        run = EvaluationRun.all_objects.get(run_id=self.pending_eval(candidate=self.candidate, baseline=self.base, cases=cases))
        run.suite_version.scorer_config = {'labels': ['billing', 'access']}
        run.suite_version.save()
        run.protocol_ref = {'profile': guided.PROFILE, 'training_run_id': 'test-training'}
        run.save()
        self.evaluator.capabilities.update(evaluation_runtime=guided.CONTRACT_DIGEST, memory_bytes=32 * 1024**3, gpu_device='mps:0')
        self.evaluator.save()
        queue_evaluation(run, pool=self.evaluator.pool, policy=self.case_budget, max_tokens=2)
        return run

    def test_native_dispatch_report_and_exactly_once_accounting(self):
        from modelanvil.jobs.models import claim_job, commit_result
        from modelanvil.jobs.executor import execute_claim
        from modelanvil.budgets.models import UsageEvent, BudgetReservation
        from modelanvil.runners.eval_worker import evaluation_worker_executor
        calls = []
        @contextmanager
        def predictors(run, max_tokens, context):
            def predict(case, baseline=False):
                calls.append((case['case_id'], baseline))
                return 'billing' if baseline else case['expected_output']
            yield predict
        with patch.object(guided, 'native_pair', return_value=(None, None, 'a' * 64)), patch.object(guided, 'native_predictors', predictors):
            run = self.prepared()
            outcome = execute_claim(self.evaluator, claim_job(self.evaluator, run.job), evaluation_worker_executor)
            self.assertEqual(outcome['status'], 'succeeded', outcome)
            run.refresh_from_db()
            report = guided.decision_report(run)
            self.assertTrue(report['available'])
            self.assertEqual(report['candidate']['accuracy'], 1)
            self.assertEqual(report['candidate']['macro_f1'], 1)
            self.assertEqual(report['baseline']['accuracy'], 0.5)
            self.assertEqual(report['case_changes']['improved'], 1)
            self.assertEqual(run.protocol_ref['pins']['prompt_format'], 'model')
            self.assertEqual(run.protocol_ref['pins']['environment']['device'], 'mps:0')
            self.assertEqual(run.protocol_ref['pins']['template_sha256'], 'a' * 64)
            from modelanvil.api.views.models_evals import EvaluationRunSerializer
            pins_before = deepcopy(run.protocol_ref)
            serialized = EvaluationRunSerializer(run).data['decision_report']['resource_evidence']
            self.assertEqual(serialized['evaluation']['usage'][0]['unit'], 'evaluation_cases')
            self.assertGreaterEqual(serialized['evaluation']['execution_seconds'], 0)
            self.assertEqual(run.protocol_ref, pins_before)
            self.assertEqual(len(calls), 4)
            attempt = run.job.attempts.get()
            self.assertFalse(commit_result(attempt, attempt.fencing_token, 'succeeded'))
            self.assertEqual(UsageEvent.all_objects.get(unit='evaluation_cases').quantity, 2)
            self.assertEqual(BudgetReservation.all_objects.get(policy=self.case_budget).settled_amount, 2)

    def test_cpu_worker_cannot_claim_native_profile_and_cancel_settles_zero(self):
        from modelanvil.jobs.models import claim_job
        from modelanvil.runners.eval_worker import CONTRACT_DIGEST
        from modelanvil.budgets.models import BudgetReservation
        with patch.object(guided, 'native_pair', return_value=(None, None, 'a' * 64)):
            run = self.prepared()
        self.evaluator.capabilities['evaluation_runtime'] = CONTRACT_DIGEST
        self.evaluator.save()
        self.assertIsNone(claim_job(self.evaluator, run.job))
        response = self.client.post(f'/api/v1/evaluation-runs/{run.run_id}/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BudgetReservation.all_objects.get(policy=self.case_budget).settled_amount, 0)

    def test_native_recovery_retains_pairs_and_does_not_repeat_committed_cases(self):
        from modelanvil.jobs.models import claim_job, JobAttempt, reconcile_expired_leases
        from modelanvil.jobs.executor import execute_claim, ExecutionContext
        from modelanvil.runners.eval_worker import evaluation_worker_executor
        from modelanvil.budgets.models import UsageEvent
        calls = []
        @contextmanager
        def predictors(run, max_tokens, context):
            def predict(case, baseline=False):
                calls.append((case['case_id'], baseline))
                return case['expected_output']
            yield predict
        with patch.object(guided, 'native_pair', return_value=(None, None, 'a' * 64)), patch.object(guided, 'native_predictors', predictors):
            run = self.prepared()
            descriptor = claim_job(self.evaluator, run.job)
            original = ExecutionContext.heartbeat
            expired = False
            def interrupt(context, progress=None):
                nonlocal expired
                if run.case_results.count() == 1 and not expired:
                    expired = True
                    JobAttempt.all_objects.filter(pk=context.attempt.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
                return original(context, progress)
            with patch.object(ExecutionContext, 'heartbeat', interrupt):
                outcome = execute_claim(self.evaluator, descriptor, evaluation_worker_executor)
            self.assertFalse(outcome['committed'])
            run.refresh_from_db()
            self.assertEqual(run.case_results.count(), 1)
            self.assertEqual(len(run.protocol_ref['baseline_results']), 1)
            self.assertEqual(reconcile_expired_leases(), 1)
            self.evaluator.refresh_from_db()
            result = execute_claim(self.evaluator, claim_job(self.evaluator, run.job), evaluation_worker_executor)
            self.assertEqual(result['status'], 'succeeded', result)
            run.refresh_from_db()
            self.assertEqual(run.case_results.count(), 2)
            self.assertEqual(len(run.protocol_ref['baseline_results']), 2)
            self.assertEqual(calls.count(('0', False)), 1)
            self.assertEqual(calls.count(('0', True)), 1)
            self.assertEqual(UsageEvent.all_objects.get(unit='evaluation_cases').quantity, 2)
