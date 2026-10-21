"""Administrator setup, observed readiness and real bounded local execution."""
import io
import json
import os
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.jobs.models import Job, Worker, WorkerCredential, WorkerPool, claim_job
from modelanvil.jobs.setup import connection_state, observe_local_worker, local_capacity_available
from modelanvil.runners.models import RunnerManifest, TrainingRun
from modelanvil.runners.training.runtime import CONTRACT_DIGEST, capable_worker


@override_settings(ALLOWED_HOSTS=['testserver'])
class ComputeSetupTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug='compute-setup', name='Compute setup')
        self.client = APIClient()
        self.auth(Role.ADMIN)

    def auth(self, role, tenant=None):
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=tenant or self.tenant, name=role, role=role, secret_hash=hashed)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')

    def register(self, **changes):
        return self.client.post('/api/v1/workers/setup/',
            {'worker_name': 'local-worker', 'pool': 'local-pool', 'profile': 'cpu-character', **changes}, format='json')

    def test_only_admin_can_provision_shipped_profiles(self):
        for role in (Role.VIEWER, Role.ENGINEER, Role.MANAGER):
            self.auth(role)
            self.assertFalse(self.client.get('/api/v1/workers/setup/').data['can_administer'])
            self.assertEqual(self.register().status_code, 403)
        self.assertEqual(Worker.all_objects.count(), 0)
        self.assertEqual(RunnerManifest.all_objects.count(), 0)
        self.auth(Role.ADMIN)
        self.assertEqual(self.register(profile='arbitrary.module').status_code, 400)
        response = self.register(); self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response['Cache-Control'], 'no-store')
        worker = Worker.all_objects.get(pk=response.data['worker_id'])
        self.assertEqual(worker.status, 'offline')
        self.assertEqual(connection_state(worker), 'not_connected')
        self.assertFalse(capable_worker(worker))
        self.assertEqual(len(WorkerCredential.all_objects.get(worker=worker).secret_hash), 64)
        self.assertNotIn(response.data['worker_token'], response.data['startup_command'])
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(Worker.all_objects.count(), 1)

    def test_heartbeat_reconnect_staleness_and_revocation(self):
        data = self.register().data
        worker = Worker.all_objects.get(pk=data['worker_id'])
        observe_local_worker(worker, 'cpu-character', data['worker_token'])
        self.assertEqual(worker.capabilities['training_runtime'], CONTRACT_DIGEST)
        self.assertEqual(connection_state(worker), 'connected')
        self.assertTrue(capable_worker(worker))
        Worker.all_objects.filter(pk=worker.pk).update(last_heartbeat_at=timezone.now()-timedelta(seconds=61))
        worker.refresh_from_db(); self.assertEqual(connection_state(worker), 'stale')
        self.assertFalse(capable_worker(worker))
        job = Job.all_objects.create(tenant_id=self.tenant.pk, name='queued', pool=worker.pool)
        self.assertIsNone(claim_job(worker, job))
        observe_local_worker(worker, 'cpu-character', data['worker_token'])
        response = self.client.post(f'/api/v1/workers/{worker.pk}/credential/revoke/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(connection_state(worker), 'credential_unavailable')
        self.assertIsNone(claim_job(worker, job))
        with self.assertRaises(ValueError):
            observe_local_worker(worker, 'cpu-character', data['worker_token'])

    def test_inventory_and_other_tenants_cannot_recover_secrets(self):
        data = self.register().data
        inventory = self.client.get('/api/v1/worker-inventory/').json()
        self.assertNotIn(data['worker_token'], json.dumps(inventory))
        self.assertEqual(inventory['results'][0]['connection_state'], 'not_connected')
        self.auth(Role.ADMIN, Tenant.objects.create(slug='other-compute', name='Other'))
        self.assertEqual(self.client.get('/api/v1/worker-inventory/').data['results'], [])
        self.assertEqual(self.client.post(f"/api/v1/workers/{data['worker_id']}/credential/revoke/", {}, format='json').status_code, 404)
        worker = Worker.all_objects.get(pk=data['worker_id'])
        with self.assertRaises(ValueError):
            observe_local_worker(worker, 'cpu-character', 'mkw_wrong')

    def test_bank_and_recipe_profiles_require_a_live_credential_before_capacity(self):
        from modelanvil.data.recipe_jobs import runtime_digest
        for profile in ('dataset-bank', 'cpu-recipes'):
            response = self.register(worker_name=profile, profile=profile)
            self.assertEqual(response.status_code, 201, response.json())
            data = response.data
            self.assertIsNone(data['runner_id'])
            self.assertIn(f'--profile {profile}', data['startup_command'])
            worker = Worker.all_objects.get(pk=data['worker_id'])
            self.assertFalse(local_capacity_available(worker))
            observe_local_worker(worker, profile, data['worker_token'])
            self.assertTrue(local_capacity_available(worker))
            if profile == 'dataset-bank':
                self.assertTrue(worker.capabilities['dataset_acquisition'])
            else:
                self.assertEqual(worker.capabilities['recipe_runtime'], runtime_digest())
                self.assertEqual(worker.capabilities['recipe_device'], 'cpu')
            Worker.all_objects.filter(pk=worker.pk).update(drain_requested=True)
            worker.refresh_from_db(); self.assertFalse(local_capacity_available(worker))
            Worker.all_objects.filter(pk=worker.pk).update(drain_requested=False,
                last_heartbeat_at=timezone.now()-timedelta(seconds=61))
            worker.refresh_from_db(); self.assertFalse(local_capacity_available(worker))
            observe_local_worker(worker, profile, data['worker_token'])
            self.client.post(f'/api/v1/workers/{worker.pk}/credential/revoke/', {}, format='json')
            self.assertFalse(local_capacity_available(worker))

    def test_data_profiles_refuse_pools_that_prohibit_dataset_output(self):
        WorkerPool.all_objects.create(tenant_id=self.tenant.pk, name='closed', result_egress='metadata_only')
        for profile in ('dataset-bank', 'cpu-recipes'):
            response = self.register(worker_name=profile, profile=profile, pool='closed')
            self.assertEqual(response.status_code, 409, response.json())
        self.assertEqual(Worker.all_objects.count(), 0)

    def test_profile_command_claims_real_training_and_commits_weights(self):
        with tempfile.TemporaryDirectory() as root, override_settings(MODELANVIL={**settings.MODELANVIL,
                'artifact_backend': 'filesystem', 'artifact_root': root}):
            team = Team.objects.create(tenant_id=self.tenant.pk, name='Team', slug='team')
            project = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='Pilot', slug='pilot')
            output = io.StringIO()
            call_command('setup_cpu_training_reference', tenant_id=self.tenant.pk, project_id=project.pk,
                         name='pilot', stdout=output)
            payload = json.loads(output.getvalue())['launch']
            Worker.all_objects.filter(name='pilot-worker').delete()
            data = self.register(pool='pilot-pool').data
            worker = Worker.all_objects.get(pk=data['worker_id'])
            observe_local_worker(worker, 'cpu-character', data['worker_token'])
            payload.update(pool=data['pool_id'], runner_manifest=data['runner_id'], total_steps=2)
            preflight = self.client.post('/api/v1/training-runs/preflight/', payload, format='json')
            self.assertEqual(preflight.status_code, 200, preflight.data)
            self.assertEqual(preflight.data['status'], 'approved', preflight.data)
            payload['preflight_token'] = preflight.data['preflight_token']
            launched = self.client.post('/api/v1/training-runs/', payload, format='json', HTTP_IDEMPOTENCY_KEY='setup-pilot')
            self.assertEqual(launched.status_code, 201, launched.data)
            replay = self.client.post('/api/v1/training-runs/', {**payload, 'preflight_token': 'refreshed-or-expired'}, format='json', HTTP_IDEMPOTENCY_KEY='setup-pilot')
            self.assertEqual(replay.status_code, 201, replay.data)
            self.assertEqual(replay.data['run_id'], launched.data['run_id'])
            self.assertEqual(TrainingRun.all_objects.count(), 1)
            with patch.dict(os.environ, {'MODELANVIL_WORKER_TOKEN': data['worker_token']}):
                call_command('run_worker', worker_id=worker.pk, profile='cpu-character', once=True, stdout=io.StringIO())
            run = TrainingRun.all_objects.get(run_id=launched.data['run_id'])
            self.assertEqual(run.status, 'completed')
            self.assertEqual(run.current_step, 2)
            self.assertIsNotNone(run.output_model_version)
            self.assertEqual(run.job.status, 'succeeded')
            self.client.post(f'/api/v1/workers/{worker.pk}/credential/revoke/', {}, format='json')
            with patch.dict(os.environ, {'MODELANVIL_WORKER_TOKEN': data['worker_token']}), self.assertRaises(CommandError):
                call_command('run_worker', worker_id=worker.pk, profile='cpu-character', once=True, stdout=io.StringIO())
