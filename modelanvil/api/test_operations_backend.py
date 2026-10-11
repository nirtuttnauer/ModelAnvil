"""Operations API persistence, accounting precision and linked project boundaries."""
import uuid
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, RateRevision, UsageEvent
from modelanvil.data.models import DataSource, SourceSnapshot
from modelanvil.identity.models import ApiKey, Project, ProjectGrant, Role, Team, Tenant, generate_api_key
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool
from modelanvil.runners.models import TrainingRun, TokenizerVersion
from modelanvil.core.models import AuditEvent


@override_settings(ALLOWED_HOSTS=['testserver'])
class OperationsBackendTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug='ops', name='Operations')
        self.team = Team.objects.create(tenant_id=self.tenant.pk, slug='ops', name='Operations')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=self.team, slug='public', name='Public')
        self.hidden = Project.objects.create(tenant_id=self.tenant.pk, team=self.team, slug='private', name='Private')
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=self.project, name='ops', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='CPU')
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name='CPU1')
        self.tokenizer = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, name='Tokenizer', vocabulary_size=10)

    def job(self, **kwargs):
        return Job.objects.create(tenant_id=self.tenant.pk, name='Job', pool=self.pool, **kwargs)

    def owner(self, job, project):
        return TrainingRun.objects.create(tenant_id=self.tenant.pk, project=project, job=job, pool=self.pool,
            tokenizer_version=self.tokenizer, recipe_type=TrainingRun.RecipeType.FULL_SFT, hardware_config={'execution_mode': 'worker'})

    def test_unlike_currencies_and_unpriced_usage_are_kept_separate(self):
        for currency, quantity in [('USD', 2), ('EUR', 3)]:
            rate = RateRevision.objects.create(tenant_id=self.tenant.pk, revision=currency, provider='owned',
                resource_kind='cpu', unit='cpu_seconds', unit_price=Decimal('2'), currency=currency,
                effective_from=timezone.now()-timezone.timedelta(days=1), source='schedule')
            UsageEvent.record(tenant_id=self.tenant.pk, provider_event_key=currency, quantity=quantity,
                unit='cpu_seconds', rate_revision=rate.revision)
        UsageEvent.record(tenant_id=self.tenant.pk, provider_event_key='unpriced', quantity=4, unit='cpu_seconds')
        response = self.client.get('/api/v1/usage-events/summary/')
        self.assertEqual(response.status_code, 200, response.content)
        rows = {r['currency']: r for r in response.json()['usage_by_unit']}
        self.assertEqual(Decimal(rows['USD']['total_amount']), 4)
        self.assertEqual(Decimal(rows['EUR']['total_amount']), 6)
        self.assertIsNone(rows['']['total_amount'])
        self.assertEqual(rows['']['unpriced_event_count'], 1)
        self.assertEqual(rows['']['total_quantity'], '4.000000')

    def test_reservations_disclose_units_without_summing_unlike_quantities(self):
        for unit, currency in [('training_steps', ''), ('usd', 'USD')]:
            policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name=unit, period='lifetime',
                unit=unit, currency=currency, limit_amount=100)
            BudgetReservation.reserve(tenant_id=self.tenant.pk, policy=policy, job_id=uuid.uuid4(), estimated_amount=10)
        data = self.client.get('/api/v1/usage-events/summary/').json()
        self.assertIsNone(data['total_reserved_amount'])
        self.assertEqual({r['unit'] for r in data['reserved_by_unit']}, {'training_steps', 'usd'})
        ledger = self.client.get('/api/v1/budget-reservations/').json()['results']
        self.assertEqual({r['unit'] for r in ledger}, {'training_steps', 'usd'})

    def test_job_attempt_filter_and_owner_cancel_route(self):
        one, other = self.job(status='running'), self.job(status='running')
        run = self.owner(one, self.project)
        for job in (one, other):
            JobAttempt.objects.create(tenant_id=self.tenant.pk, job=job, worker=self.worker, fencing_token=str(uuid.uuid4()))
        response = self.client.get(f'/api/v1/job-attempts/?job_id={one.job_id}')
        self.assertEqual({r['job_id'] for r in response.json()['results']}, {str(one.job_id)})
        self.assertEqual(self.client.get('/api/v1/job-attempts/?job_id=invalid').status_code, 400)
        expected = f'/api/v1/training-runs/{run.run_id}/cancel/'
        self.assertEqual(self.client.get(f'/api/v1/jobs/{one.job_id}/').json()['cancel_endpoint'], expected)
        detail = self.client.get(f'/api/v1/run-details/job/{one.job_id}/').json()
        self.assertEqual(detail['actions']['cancel']['endpoint'], expected)

    def test_training_owned_job_does_not_bypass_project_boundary(self):
        job = self.job(status='running'); run = self.owner(job, self.hidden)
        attempt = JobAttempt.objects.create(tenant_id=self.tenant.pk, job=job, worker=self.worker, fencing_token='hidden')
        for path in (f'/api/v1/jobs/{job.job_id}/', f'/api/v1/job-attempts/{attempt.attempt_id}/',
                     f'/api/v1/run-details/job/{job.job_id}/', f'/api/v1/run-details/job/{job.job_id}/attempts/',
                     f'/api/v1/run-details/training/{run.run_id}/'):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.post(f'/api/v1/jobs/{job.job_id}/cancel/').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/jobs/').json()['results'], [])
        ProjectGrant.objects.create(tenant_id=self.tenant.pk, project=self.hidden, granted_to_project=self.project,
            resource_type='trainingrun', resource_id=run.run_id)
        self.assertEqual(self.client.get(f'/api/v1/jobs/{job.job_id}/').status_code, 200)

    def test_hidden_training_run_without_job_does_not_hide_unrelated_jobs(self):
        self.owner(None, self.hidden)
        visible = self.job()
        response = self.client.get('/api/v1/jobs/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([row['job_id'] for row in response.json()['results']], [str(visible.job_id)])
        self.assertEqual(self.client.get(f'/api/v1/jobs/{visible.job_id}/').status_code, 200)

    def test_bank_jobs_inherit_fine_grained_snapshot_access(self):
        source = DataSource.objects.create(tenant_id=self.tenant.pk, project=self.hidden, name='private', kind='upload')
        snapshot = SourceSnapshot.objects.create(tenant_id=self.tenant.pk, source=source, source_revision='1')
        job = self.job(payload={'type': 'dataset_acquisition', 'snapshot_id': str(snapshot.snapshot_id)})
        missing = self.job(payload={'type': 'dataset_acquisition'})
        self.assertEqual(self.client.get(f'/api/v1/jobs/{job.job_id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/jobs/{missing.job_id}/').status_code, 404)
        ProjectGrant.objects.create(tenant_id=self.tenant.pk, project=self.hidden, granted_to_project=self.project,
            resource_type='sourcesnapshot', resource_id=snapshot.snapshot_id)
        data = self.client.get(f'/api/v1/jobs/{job.job_id}/').json()
        self.assertEqual(data['cancel_endpoint'], f'/api/v1/dataset-bank/acquisitions/{snapshot.snapshot_id}/cancel/')

    def test_create_replay_cancel_and_reservation_are_durable(self):
        policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name='steps', period='lifetime',
            unit='training_steps', limit_amount=100)
        body = {'name': 'Durable', 'pool': self.pool.pk, 'payload': {}, 'budget_policy_id': str(policy.policy_id), 'estimated_amount': '2.123456'}
        first = self.client.post('/api/v1/jobs/', body, format='json', HTTP_IDEMPOTENCY_KEY='durable')
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post('/api/v1/jobs/', body, format='json', HTTP_IDEMPOTENCY_KEY='durable')
        self.assertEqual(first.json()['job_id'], second.json()['job_id'])
        self.assertEqual(AuditEvent.objects.filter(resource_type='job', action='create').count(), 1)
        job = Job.objects.get(job_id=first.json()['job_id'])
        self.assertEqual(self.client.post(f'/api/v1/jobs/{job.job_id}/cancel/').status_code, 200)
        job.refresh_from_db(); self.assertEqual(job.status, 'cancelled')
        reservation = BudgetReservation.objects.get(job_id=job.job_id)
        self.assertEqual(reservation.state, 'released'); self.assertIsNotNone(reservation.settled_at)
        self.assertEqual(self.client.post(f'/api/v1/jobs/{job.job_id}/cancel/').status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(resource_type='job', action='cancel').count(), 1)
        bad = self.client.post('/api/v1/jobs/', {**body, 'payload': []}, format='json', HTTP_IDEMPOTENCY_KEY='bad')
        self.assertEqual(bad.status_code, 400)
