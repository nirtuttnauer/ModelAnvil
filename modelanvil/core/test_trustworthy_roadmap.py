"""Ledger, decision report, development corrections, and closed commercial gates."""
import importlib.util
import json
import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.annotation.feedback import assert_uninspected_cases
from modelanvil.compute.plugins import DEFERRED_UNTIL_PILOT, PluginError, definition, provider_claim
from modelanvil.core.decision_report import DECISIVE_CASES, build_report
from modelanvil.core.evaluation_gate import gate_status
from modelanvil.core.pilot_gate import paid_packaging_allowed
from modelanvil.core.restore_rehearsal import rehearse_copy
from modelanvil.core.tenancy import reset_context, set_active_tenant
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.releases.models import ServingEndpoint
from modelanvil.runners.development_cycle import handoff_failed_cases
from modelanvil.runners.evidence import LEVELS
from modelanvil.runners.models import EvaluationCaseResult, EvaluationRun, EvaluationSuite, EvaluationSuiteVersion, Model, ModelVersion, TokenizerVersion
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.cpu_hf_runtime import LIMITS as CPU_LIMITS
from modelanvil.runners.training.sequence_envelope import HISTORICAL_GENERATED_TOKENS, HISTORICAL_SEQUENCE_TOKENS, admit_report, apply_cpu_measurement, generated_token_ceiling
from modelanvil.api.views.capability_ledger import ledger_payload


ROOT = Path(__file__).resolve().parents[2]


def rows(count, candidate_passed, baseline_passed, slice_name='label'):
    candidate, baseline = [], []
    for index in range(count):
        case_id = f'case-{index}'
        candidate.append({'case_id': case_id, 'passed': candidate_passed, 'slice_name': slice_name})
        baseline.append({'case_id': case_id, 'passed': baseline_passed, 'slice_name': slice_name})
    return candidate, baseline


def measured_report(**changes):
    report = {
        'profile': 'modelanvil.smollm2-cpu-sft.v1', 'device': 'cpu', 'packages': hf_runtime.PACKAGES,
        'model_sha256': hf_runtime.GUIDED_FILE_HASHES['model.safetensors'], 'completed_steps': 1,
        'sequence_tokens': 256, 'generated_tokens': 48, 'truncated': False, 'recovery': 'parameter_state_roundtrip',
        'peak_rss_bytes': 4 * 1024**3, 'host_memory_bytes': 8 * 1024**3, 'rows_measured': 1,
        'production_qualified': False, 'hardware_qualified': False,
    }
    report.update(changes)
    return report


class EnvelopeTests(TestCase):
    def test_gpu_wall_stays_until_a_gpu_measurement_exists(self):
        self.assertEqual(hf_runtime.LIMITS['sequence_tokens'], HISTORICAL_SEQUENCE_TOKENS)
        self.assertGreater(CPU_LIMITS['sequence_tokens'], HISTORICAL_SEQUENCE_TOKENS)
        self.assertGreater(generated_token_ceiling(), HISTORICAL_GENERATED_TOKENS)
        self.assertFalse(ledger_payload()['production_qualified'])
        self.assertEqual(ledger_payload()['paid_packaging'], 'closed')

    def test_cpu_report_can_raise_only_the_cpu_profile(self):
        admitted = admit_report(measured_report())
        self.assertEqual(admitted['sequence_tokens'], 256)
        updated = apply_cpu_measurement({'sequence_tokens': 128, 'memory_bytes': 16 * 1024**3, 'steps': 20}, measured_report())
        self.assertEqual(updated['sequence_tokens'], 256)
        self.assertEqual(updated['memory_bytes'], admitted['memory_bytes'])
        self.assertEqual(hf_runtime.LIMITS['sequence_tokens'], 128)
        with self.assertRaises(ValueError):
            admit_report(measured_report(sequence_tokens=128))
        with self.assertRaises(ValueError):
            admit_report(measured_report(production_qualified=True))
        self.assertEqual(generated_token_ceiling(measured_report()), 48)

    def test_measure_script_pins_match_the_runtime(self):
        path = ROOT / 'scripts/measure_sequence_envelope.py'
        spec = importlib.util.spec_from_file_location('measure_sequence_envelope', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.PACKAGES, hf_runtime.PACKAGES)
        self.assertEqual(module.GUIDED_WEIGHT, hf_runtime.GUIDED_FILE_HASHES['model.safetensors'])
        self.assertEqual(module.BASE_WEIGHT, hf_runtime.FILE_HASHES['model.safetensors'])

    def test_ledger_text_matches_the_code_limits(self):
        text = (ROOT / 'docs/engineering/capability-ledger.md').read_text()
        self.assertIn(f'Guided sequence tokens: {hf_runtime.LIMITS["sequence_tokens"]}', text)
        self.assertIn(f'CPU sequence tokens: {CPU_LIMITS["sequence_tokens"]}', text)
        self.assertIn(f'Generated tokens: {generated_token_ceiling()}', text)
        self.assertIn('production_qualified: false', text)
        source = (ROOT / 'web/src/api/evidence-label.ts').read_text()
        for level, label in LEVELS.items():
            self.assertIn(f"{level}: '{label}'", source)


class DecisionAndPlaybookTests(TestCase):
    def test_small_samples_stay_inconclusive_and_a_thirty_case_loss_is_a_rejection(self):
        small_candidate, small_baseline = rows(4, True, False)
        small = build_report(candidate_rows=small_candidate, baseline_rows=small_baseline, evidence_level='integrated_execution', status='completed')
        self.assertEqual(small['recommended_outcome'], 'inconclusive')
        self.assertFalse(small['decisive'])
        self.assertFalse(small['gate']['passed'])
        self.assertFalse(small['production_qualified'])
        candidate, baseline = rows(DECISIVE_CASES, False, True)
        rejected = build_report(candidate_rows=candidate, baseline_rows=baseline, evidence_level='integrated_execution', status='completed',
            pins={'prompt_format': 'native_template'}, runtime_seconds=1.5)
        self.assertEqual(rejected['recommended_outcome'], 'reject')
        self.assertTrue(rejected['decisive'])
        self.assertEqual(gate_status(rejected), 1)
        self.assertIn('cannot be called a win', small['gate']['reason'])

    def test_playbooks_fit_the_published_envelope_and_name_one_rejection(self):
        for name in ('classification', 'extraction', 'constrained'):
            directory = ROOT / 'playbooks' / name
            limits = json.loads((directory / 'limits.json').read_text())
            suite = json.loads((directory / 'suite.json').read_text())
            self.assertEqual(limits['sequence_tokens'], hf_runtime.LIMITS['sequence_tokens'])
            self.assertEqual(limits['generated_tokens'], generated_token_ceiling())
            self.assertFalse(limits['production_qualified'])
            self.assertTrue((directory / 'external-load.md').read_text().startswith('# External load'))
            self.assertGreaterEqual(len((directory / 'train.jsonl').read_text().splitlines()), 3)
            self.assertTrue(all(case.get('source_group_id') for case in suite['cases']))
            for line in (directory / 'train.jsonl').read_text().splitlines():
                self.assertLess(len(line), limits['sequence_tokens'] * 8)
        protocol = json.loads((ROOT / 'playbooks/classification/comparison.json').read_text())
        candidate, baseline = rows(protocol['cases'], protocol['candidate_passed'], protocol['baseline_passed'], protocol['slice'])
        report = build_report(candidate_rows=candidate, baseline_rows=baseline, evidence_level='integrated_execution', status='completed')
        self.assertEqual(report['recommended_outcome'], 'reject')
        extraction = json.loads((ROOT / 'playbooks/extraction/comparison.json').read_text())
        candidate, baseline = rows(extraction['cases'], extraction['candidate_passed'], extraction['baseline_passed'], extraction['slice'])
        self.assertEqual(build_report(candidate_rows=candidate, baseline_rows=baseline, evidence_level='integrated_execution', status='completed')['recommended_outcome'], 'inconclusive')

    def test_regression_gate_and_directory_rehearsal_do_not_qualify_production(self):
        passing = {'candidate_accuracy': 0.9, 'baseline_accuracy': 0.8, 'decisive': True, 'production_qualified': False}
        self.assertEqual(gate_status(passing), 0)
        self.assertEqual(gate_status({'candidate_accuracy': 0.5, 'baseline_accuracy': 0.8, 'decisive': True, 'production_qualified': False}), 1)
        self.assertEqual(gate_status({**passing, 'production_qualified': True}), 2)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            source.mkdir()
            (source / 'weights.bin').write_bytes(b'abc')
            report = rehearse_copy(source, Path(temporary) / 'destination')
        self.assertEqual(report['files'], 1)
        self.assertFalse(report['production_qualified'])
        self.assertFalse(paid_packaging_allowed())


class DevelopmentCycleTests(TestCase):
    def setUp(self):
        reset_context()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_root': self.directory.name, 'artifact_backend': 'filesystem'})
        override.enable()
        self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='cycle', name='Cycle')
        set_active_tenant(self.tenant.pk)
        self.addCleanup(set_active_tenant, None)
        team = Team.all_objects.create(tenant_id=self.tenant.pk, slug='team', name='Team')
        self.project = Project.all_objects.create(tenant_id=self.tenant.pk, team=team, slug='one', name='One')
        tokenizer = TokenizerVersion.all_objects.create(tenant_id=self.tenant.pk, name='Cycle tokenizer')
        model = Model.all_objects.create(tenant_id=self.tenant.pk, name='Cycle model')
        self.model = ModelVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project, model=model, tokenizer=tokenizer, architecture_ref='fixture', revision_no=1)
        suite = EvaluationSuite.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='Development checks')
        self.version = EvaluationSuiteVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project, suite=suite, protected_role='development', cases=[{
            'case_id': 'failed-1', 'input_prompt': 'What is two plus two?', 'expected_output': '4', 'source_group_id': 'dev-group', 'slice': 'arithmetic'}])
        self.run = EvaluationRun.all_objects.create(tenant_id=self.tenant.pk, project=self.project, suite_version=self.version,
            candidate_model_version=self.model, status='completed', protocol_ref={'execution_evidence': {'level': 'integrated_execution', 'source': 'test'}})
        EvaluationCaseResult.all_objects.create(tenant_id=self.tenant.pk, run=self.run, case_id='failed-1', input_prompt='What is two plus two?',
            candidate_output='5', expected_output='4', passed=False, slice_name='arithmetic')

    def test_failed_development_cases_train_later_and_cannot_enter_the_protected_test(self):
        self.assertEqual(ServingEndpoint.all_objects.count(), 0)
        from modelanvil.core.decision_report import report_for_run
        self.assertFalse(report_for_run(self.run)['gate']['passed'])
        result = handoff_failed_cases(run=self.run, corrections=[{'case_id': 'failed-1', 'corrected_output': '4'}], dataset_name='Cycle 2 corrections')
        self.run.suite_version.refresh_from_db()
        self.assertEqual(self.run.suite_version.protected_role, 'development_inspected')
        self.assertFalse(result['promoted'])
        self.assertEqual(ServingEndpoint.all_objects.count(), 0)
        self.assertEqual(self.model.pk, self.run.candidate_model_version_id)
        with self.assertRaises(ValueError):
            assert_uninspected_cases(self.tenant.pk, [{'case_id': 'final', 'input_prompt': 'Other', 'source_group_id': 'dev-group'}])
        assert_uninspected_cases(self.tenant.pk, [{'case_id': 'final', 'input_prompt': 'Other', 'source_group_id': 'fresh-group'}])
        with self.assertRaises(ValueError):
            handoff_failed_cases(run=self.run, corrections=[{'case_id': 'failed-1', 'corrected_output': '4'}], dataset_name='Again')


@override_settings(ALLOWED_HOSTS=['testserver'])
class CapabilityLedgerHttpTests(TestCase):
    def test_viewers_can_read_the_ledger_and_paid_packaging_stays_closed(self):
        client = APIClient()
        self.assertEqual(client.get('/api/v1/capability-ledger/').status_code, 401)
        tenant = Tenant.objects.create(slug='ledger', name='Ledger')
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name='Viewer', role=Role.VIEWER, secret_hash=hashed)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        response = client.get('/api/v1/capability-ledger/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertFalse(response.json()['production_qualified'])
        self.assertEqual(response.json()['paid_packaging'], 'closed')
        self.assertEqual(response.json()['guided_sequence_tokens'], hf_runtime.LIMITS['sequence_tokens'])
        status = client.get('/api/v1/accounts/status/')
        self.assertEqual(status.json()['paid_packaging'], 'closed')
        self.assertEqual(status.json()['customer_discovery'], 'open')


class DeferredProviderTests(TestCase):
    def test_backlog_providers_cannot_be_selected(self):
        self.assertEqual(provider_claim('runpod'), 'implemented_unqualified')
        self.assertEqual(provider_claim('vast'), 'deferred')
        self.assertIn('aws', DEFERRED_UNTIL_PILOT)
        with self.assertRaises(PluginError):
            definition('vast', uuid.uuid4(), 'compute')
        self.assertNotIn('runpod', DEFERRED_UNTIL_PILOT)


class AccountMailTests(TestCase):
    def setUp(self):
        reset_context()
        from django.core.cache import cache
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf(self):
        return self.client.cookies['csrftoken'].value

    @override_settings(MODELANVIL_SELF_SERVICE_ACCOUNTS=True, MODELANVIL_SEND_RESET_EMAIL=True, DEBUG=False, EMAIL_HOST='smtp.example.invalid',
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', DEFAULT_FROM_EMAIL='reset@example.invalid')
    def test_configured_mail_hides_the_reset_code(self):
        self.client.get('/api/v1/accounts/status/')
        self.assertEqual(self.client.post('/api/v1/accounts/signup/', {'email': 'mail@example.invalid', 'name': 'Mail',
            'password': 'a-long-testing-password-937!'}, format='json', HTTP_X_CSRFTOKEN=self.csrf()).status_code, 200)
        requested = self.client.post('/api/v1/accounts/password-reset/', {'email': 'mail@example.invalid'}, format='json', HTTP_X_CSRFTOKEN=self.csrf())
        unknown = self.client.post('/api/v1/accounts/password-reset/', {'email': 'missing@example.invalid'}, format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(requested.status_code, 200, requested.content)
        self.assertNotIn('reset_code', requested.json())
        self.assertEqual(requested.json()['delivery'], unknown.json()['delivery'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('reset code', mail.outbox[0].body)
        self.assertNotIn(mail.outbox[0].body, json.dumps(requested.json()))
