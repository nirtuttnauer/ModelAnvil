"""Actual worker results, scoped local measurement, and non-inflatable cycle counts."""
import uuid
from datetime import timedelta

from django.utils import timezone
from django.test import TestCase

from modelanvil.api import test_durable_evaluation as fixture
from modelanvil.core.models import ActivationEvent, ImprovementDecision
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import claim_job
from modelanvil.runners.eval_worker import evaluation_worker_executor
from modelanvil.runners.models import TrainingRun


class ActivationTests(TestCase):
    artifact = fixture.DurableEvaluationTests.artifact
    envelope = fixture.DurableEvaluationTests.envelope
    payload = fixture.DurableEvaluationTests.payload
    launch = fixture.DurableEvaluationTests.launch
    execute = fixture.DurableEvaluationTests.execute
    suite = fixture.DurableEvaluationTests.suite
    _suite_pk = fixture.DurableEvaluationTests._suite_pk
    pending_eval = fixture.DurableEvaluationTests.pending_eval
    queued = fixture.DurableEvaluationTests.queued

    def setUp(self):
        fixture.DurableEvaluationTests.setUp(self)
        team = Team.all_objects.create(tenant_id=self.tenant.pk, name='Pilot', slug='pilot')
        self.project = Project.all_objects.create(tenant_id=self.tenant.pk, team=team, name='First task', slug='first')
        self.headers = {'HTTP_X_PROJECT_ID': str(self.project.pk)}
        self.evaluation = self.queued()
        outcome = execute_claim(self.evaluator, claim_job(self.evaluator, self.evaluation.job), evaluation_worker_executor)
        self.assertEqual(outcome['status'], 'succeeded', outcome)
        self.evaluation.refresh_from_db()
        self.url = f'/api/v1/evaluation-runs/{self.evaluation.run_id}/record-decision/'

    def report(self, **headers):
        response = self.client.get('/api/v1/activation/report/', **(headers or self.headers))
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def event(self, **values):
        data = {'event_id': str(uuid.uuid4()), 'session_id': str(uuid.uuid4()), 'kind': 'workspace_opened', **values}
        return self.client.post('/api/v1/activation/events/', data, format='json', **self.headers)

    def test_reviewer_can_record_a_measured_decision_but_viewer_cannot(self):
        from rest_framework.test import APIClient
        secret, hashed = generate_api_key()
        key = ApiKey.objects.create(tenant=self.tenant, name='Reviewer', role=Role.VIEWER, secret_hash=hashed)
        client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers).status_code, 403)
        key.role = Role.REVIEWER; key.save()
        response = client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['production_qualified'])

    def test_actual_decision_is_immutable_idempotent_and_does_not_deploy(self):
        self.assertEqual(self.report()['weekly_improvement_cycles'], 0)
        opened = self.event()
        self.assertEqual(opened.status_code, 201, opened.data)
        response = self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['production_qualified'])
        again = self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(response.data['decision_id'], again.data['decision_id'])
        self.assertEqual(self.client.post(self.url, {'outcome': 'accept'}, format='json', **self.headers).status_code, 400)
        report = self.report()
        self.assertEqual(report['weekly_improvement_cycles'], 1)
        self.assertEqual(report['weekly_teams_with_decisions'], 1)
        self.assertEqual(report['weekly_rejected_candidates'], 1)
        self.assertEqual(report['weekly_accepted_improvements'], 0)
        self.assertGreaterEqual(report['time_to_first_decision_seconds'], 0)
        self.assertGreaterEqual(report['decisions'][0]['training']['execution_seconds'], 0)
        self.assertGreaterEqual(report['decisions'][0]['evaluation']['queue_seconds'], 0)
        self.assertEqual(ImprovementDecision.all_objects.count(), 1)
        self.assertFalse('ANSWER_IS_NOT_ECHOED' in str(report))

    def test_an_accept_choice_without_measured_gain_is_not_an_accepted_improvement(self):
        response = self.client.post(self.url, {'outcome': 'accept'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['accepted_improvement'])
        self.assertEqual(self.report()['weekly_improvement_cycles'], 1)
        self.assertEqual(self.report()['weekly_accepted_improvements'], 0)

    def test_partial_simulation_and_missing_baseline_cannot_count_as_completed_cycles(self):
        original = self.evaluation.protocol_ref.copy()
        for change in ({'status': 'running'}, {'baseline_model_version': None}, {'job': None},
                       {'protocol_ref': {**original, 'execution_evidence': {'level': 'simulation'}}},
                       {'protocol_ref': {**original, 'baseline_results': []}}):
            old = {key: getattr(self.evaluation, key) for key in change}
            for key, value in change.items(): setattr(self.evaluation, key, value)
            self.evaluation.save()
            response = self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
            self.assertEqual(response.status_code, 400, response.json())
            for key, value in old.items(): setattr(self.evaluation, key, value)
            self.evaluation.save()
        self.evaluation.case_results.all().delete()
        self.assertEqual(self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers).status_code, 400)
        self.assertEqual(self.report()['weekly_improvement_cycles'], 0)

    def test_event_allowlist_duplicate_retry_and_content_free_storage(self):
        event = {'event_id': str(uuid.uuid4()), 'session_id': str(uuid.uuid4()), 'kind': 'activity', 'active_milliseconds': 1200}
        for status in (201, 200):
            result = self.client.post('/api/v1/activation/events/', event, format='json', **self.headers)
            self.assertEqual(result.status_code, status, result.data)
        altered = {**event, 'active_milliseconds': 1300}
        self.assertEqual(self.client.post('/api/v1/activation/events/', altered, format='json', **self.headers).status_code, 409)
        for extra in ({'prompt': 'PRIVATE'}, {'token': 'SECRET'}, {'url': 'https://external.invalid'}, {'active_milliseconds': 60001}):
            result = self.client.post('/api/v1/activation/events/', {**event, **extra}, format='json', **self.headers)
            self.assertEqual(result.status_code, 400, result.json())
        self.assertEqual(ActivationEvent.all_objects.count(), 1)
        self.assertEqual(self.report()['reported_active_seconds'], 1.2)
        self.assertEqual(self.report()['weekly_improvement_cycles'], 0)
        self.assertEqual(self.report()['external_analytics'], 'disabled')

    def test_project_tenant_and_role_boundaries(self):
        self.assertEqual(self.client.post('/api/v1/activation/events/', {
            'event_id': str(uuid.uuid4()), 'session_id': str(uuid.uuid4()), 'kind': 'workspace_opened'}, format='json').status_code, 404)
        self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
        other = Project.all_objects.create(tenant_id=self.tenant.pk, team=self.project.team, name='Other', slug='other')
        self.assertEqual(self.report(HTTP_X_PROJECT_ID=str(other.pk))['weekly_improvement_cycles'], 0)
        self.assertEqual(self.client.get('/api/v1/activation/report/').data['weekly_improvement_cycles'], 1)
        ApiKey.objects.filter(tenant=self.tenant).update(role=Role.VIEWER)
        self.assertEqual(self.client.get('/api/v1/activation/report/').status_code, 403)
        self.assertEqual(self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers).status_code, 403)
        tenant = Tenant.objects.create(slug='separate', name='Separate')
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name='Other', role=Role.ADMIN, secret_hash=hashed)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(self.client.get('/api/v1/activation/report/').data['weekly_improvement_cycles'], 0)
        self.assertEqual(self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers).status_code, 401)

    def test_week_boundaries_and_current_evidence_revalidation(self):
        response = self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.report()['weekly_improvement_cycles'], 1)
        self.evaluation.protocol_ref['baseline_results'] = []
        self.evaluation.save()
        self.assertEqual(self.report()['weekly_improvement_cycles'], 0)
        self.evaluation.refresh_from_db()
        monday = timezone.now().date() - timedelta(days=timezone.now().weekday())
        previous = self.client.get(f'/api/v1/activation/report/?week={monday - timedelta(days=7)}', **self.headers)
        self.assertEqual(previous.data['weekly_improvement_cycles'], 0)
        self.assertEqual(self.client.get('/api/v1/activation/report/?week=not-a-date', **self.headers).status_code, 400)

    def test_tenant_totals_deduplicate_the_same_team_candidate_and_evaluation_across_projects(self):
        other = Project.all_objects.create(tenant_id=self.tenant.pk, team=self.project.team, name='Second', slug='second')
        for project in (self.project, other):
            response = self.client.post(self.url, {'outcome': 'reject'}, format='json', HTTP_X_PROJECT_ID=str(project.pk))
            self.assertEqual(response.status_code, 201, response.json())
        totals = self.client.get('/api/v1/activation/report/').json()
        self.assertEqual(ImprovementDecision.all_objects.count(), 2)
        self.assertEqual(totals['weekly_improvement_cycles'], 1)
        self.assertEqual(totals['weekly_teams_with_decisions'], 1)

    def test_setup_check_and_synthetic_training_cannot_be_accepted(self):
        training = TrainingRun.all_objects.get(output_model_version=self.evaluation.candidate_model_version)
        original = dict(training.hardware_config or {})
        training.hardware_config = {**original, 'setup_check': True}
        training.save(update_fields=['hardware_config'])
        setup = self.client.post(self.url, {'outcome': 'accept'}, format='json', **self.headers)
        self.assertEqual(setup.status_code, 400, setup.json())
        self.assertIn('setup check', str(setup.json()).lower())
        training.hardware_config = {**original, 'execution_mode': 'simulation', 'setup_check': False}
        training.save(update_fields=['hardware_config'])
        synthetic = self.client.post(self.url, {'outcome': 'reject'}, format='json', **self.headers)
        self.assertEqual(synthetic.status_code, 400, synthetic.json())
        self.assertIn('synthetic', str(synthetic.json()).lower())
        self.assertEqual(self.report()['weekly_improvement_cycles'], 0)
