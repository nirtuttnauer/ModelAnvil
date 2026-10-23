"""Job/accounting regressions; mocks here do not qualify GPU execution."""
from datetime import timedelta
import io
import hashlib
import json
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.identity.models import Tenant, Team, Project, ApiKey, Role, generate_api_key
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job, commit_result, reconcile_expired_leases
from modelanvil.runners.models import AlignmentRun, Model, ModelVersion, TokenizerVersion
from . import mps_dpo


@override_settings(ALLOWED_HOSTS=['testserver'])
class DPOJobControlsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug='dpo-control', name='DPO controls')
        team = Team.objects.create(tenant_id=self.tenant.pk, slug='team', name='Team')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=team, slug='p', name='Project')
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='operator DPO')
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name='worker', slots=1)
        tokenizer = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Control fixture')
        model = Model.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Control fixture')
        base = ModelVersion.objects.create(tenant_id=self.tenant.pk, project=self.project, model=model,
            tokenizer=tokenizer, revision_no=1, architecture_ref='control-fixture')
        self.job = Job.objects.create(tenant_id=self.tenant.pk, project=self.project, pool=self.pool,
            name='DPO', max_attempts=3, payload={'type': 'qualified_dpo'})
        self.run = AlignmentRun.objects.create(tenant_id=self.tenant.pk, project=self.project, worker_pool=self.pool,
            job=self.job, policy_model_version=base, reference_model_version=base, algorithm='dpo',
            total_steps=3, execution_pins={'runtime': mps_dpo.RUNTIME_ID})
        self.job.payload['run_id'] = str(self.run.run_id); self.job.save()
        policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name='Steps', period='lifetime',
            unit='training_steps', limit_amount=20)
        self.reservation = BudgetReservation.reserve(tenant_id=self.tenant.pk, policy=policy,
            job_id=self.job.job_id, estimated_amount=3)
        self.run.resource_reservation_id = self.reservation.reservation_id; self.run.save()
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant_id=self.tenant.pk, project=self.project, name='tests', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')

    def claim(self):
        with patch('modelanvil.runners.training.admission.gpu_claim_plan', return_value=None):
            descriptor = claim_job(self.worker, self.job)
        self.assertIsNotNone(descriptor)
        return JobAttempt.objects.get(attempt_id=descriptor['attempt_id']), descriptor['fencing_token']

    def test_scoped_expiry_requeues_run_without_settlement_and_fences_old_result(self):
        attempt, token = self.claim()
        self.run.status = 'running'; self.run.save()
        JobAttempt.objects.filter(pk=attempt.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(reconcile_expired_leases(job_ids=[uuid.uuid4()]), 0)
        self.assertEqual(reconcile_expired_leases(job_ids=[self.job.job_id]), 1)
        self.run.refresh_from_db(); self.job.refresh_from_db(); self.reservation.refresh_from_db()
        self.assertEqual((self.run.status, self.job.status, self.reservation.state), ('interrupted', 'queued', 'reserved'))
        self.assertFalse(commit_result(attempt, token, JobAttempt.Status.SUCCEEDED))
        self.assertEqual(UsageEvent.all_objects.count(), 0)

    def test_queued_cancellation_settles_zero_once_and_cannot_be_resumed(self):
        for _ in range(2):
            response = self.client.post(f'/api/v1/alignment-runs/{self.run.run_id}/cancel/', {}, format='json')
            self.assertEqual(response.status_code, 200, response.content)
        self.reservation.refresh_from_db(); self.job.refresh_from_db()
        self.assertEqual(self.reservation.state, 'settled')
        self.assertEqual(self.job.status, 'cancelled')
        self.assertEqual(list(UsageEvent.all_objects.values_list('quantity', flat=True)), [0])
        self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{self.run.run_id}/resume/', {}, format='json').status_code, 400)

    def test_worker_success_without_committed_weights_fails_closed(self):
        attempt, token = self.claim()
        self.run.status = 'running'; self.run.save()
        self.assertTrue(commit_result(attempt, token, JobAttempt.Status.SUCCEEDED))
        self.run.refresh_from_db(); self.job.refresh_from_db(); attempt.refresh_from_db()
        self.assertEqual((self.run.status, self.job.status, attempt.status), ('failed', 'failed', 'failed'))
        self.assertIsNone(self.run.output_model_version_id)
        self.assertEqual(UsageEvent.all_objects.get().quantity, 0)

    def test_queued_plan_and_owning_job_are_immutable_and_use_alignment_cancel(self):
        path = f'/api/v1/alignment-runs/{self.run.run_id}/'
        self.assertEqual(self.client.patch(path, {'total_steps': 4}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(path).status_code, 400)
        path = f'/api/v1/jobs/{self.job.job_id}/'
        self.assertEqual(self.client.patch(path, {'payload': {}}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(path).status_code, 400)
        self.assertEqual(self.client.post(path + 'cancel/', {}, format='json').status_code, 400)
        self.assertEqual(self.client.get(path).json()['cancel_endpoint'], f'/api/v1/alignment-runs/{self.run.run_id}/cancel/')

    def test_review_attestation_is_explicit_and_frozen_in_registered_bytes(self):
        import tempfile
        from modelanvil.runners.training.runtime import read_artifact
        with tempfile.TemporaryDirectory() as directory, override_settings(MODELANVIL={**settings.MODELANVIL,
                'artifact_backend': 'filesystem', 'artifact_root': directory}):
            payload = {'name': 'Reviewed fixture', 'samples': [{'prompt': 'A:', 'chosen': ' yes',
                'rejected': ' no', 'source_group_id': 'one'}]}
            response = self.client.post('/api/v1/alignment-runs/register-preferences/', payload, format='json')
            artifact = Artifact.all_objects.get(artifact_id=response.json()['artifact_id'])
            with self.assertRaisesRegex(ValueError, 'review'): mps_dpo._preferences(artifact, self.tenant.pk, self.project.pk)
            response = self.client.post('/api/v1/alignment-runs/register-preferences/',
                {**payload, 'labels_reviewed': True}, format='json')
            self.assertEqual(response.status_code, 201, response.content)
            reviewed = Artifact.all_objects.get(artifact_id=response.json()['artifact_id'])
            raw = read_artifact(reviewed, self.tenant.pk, self.project.pk)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), reviewed.sha256)
            self.assertTrue(json.loads(raw)['review']['labels_reviewed'])
            self.assertNotEqual(artifact.sha256, reviewed.sha256)
            self.assertEqual(mps_dpo._preferences(reviewed, self.tenant.pk, self.project.pk)[2], {'one'})
            forged = Artifact.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
                storage_location_id='local', object_key=f'forged/{uuid.uuid4()}.json', sha256=reviewed.sha256,
                byte_size=len(raw), media_type='application/json')
            upload_staged_artifact(forged, io.BytesIO(raw), backend=artifact_storage_backend())
            with self.assertRaisesRegex(ValueError, 'review'): mps_dpo._preferences(forged, self.tenant.pk, self.project.pk)

    def test_gpu_settings_reject_unknown_algorithms_options_and_unsafe_numbers(self):
        for options in ({}, {'budget_policy_id': 'x', 'learning_rate': .05},
                {'budget_policy_id': 'x', 'beta': float('nan')}, {'budget_policy_id': 'x', 'orpo': True}):
            with self.assertRaises(ValueError): mps_dpo.hyperparameters(options)

    def test_formal_review_is_bound_to_exported_bytes_even_if_artifact_reference_is_replaced(self):
        import tempfile
        from modelanvil.annotation.models import LabelSchema, LabelingCampaign, CumulativeSnapshot
        with tempfile.TemporaryDirectory() as directory, override_settings(MODELANVIL={**settings.MODELANVIL,
                'artifact_backend': 'filesystem', 'artifact_root': directory}):
            schema = LabelSchema.objects.create(tenant_id=self.tenant.pk, name='Formal fixture', kind='preference_ranking')
            campaign = LabelingCampaign.objects.create(tenant_id=self.tenant.pk, project=self.project,
                name='Formal fixture', label_schema=schema, seed_mode='manual')
            snap = CumulativeSnapshot.objects.create(tenant_id=self.tenant.pk, campaign=campaign,
                cycle_no=1, item_count=1, manifest_digest='a' * 64)

            def store(chosen):
                raw = json.dumps({'schema_version': 'modelanvil.preference-pairs.v1', 'pairs': [
                    {'prompt': 'A:', 'chosen': chosen, 'rejected': ' no', 'metadata': {'source_group_id': 'formal-one'}}]}).encode()
                artifact = Artifact.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
                    storage_location_id='local', object_key=f'formal/{uuid.uuid4()}.json',
                    sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type='application/json',
                    metadata={'snapshot_id': str(snap.snapshot_id)})
                upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
                return artifact

            original, replacement = store(' yes'), store(' yep')
            snap.qualification = {'formal_preference': {'artifact': {
                'artifact_id': str(original.artifact_id), 'sha256': original.sha256, 'byte_size': original.byte_size}}}
            snap.save()
            self.assertEqual(mps_dpo._preferences(original, self.tenant.pk, self.project.pk)[2], {'formal-one'})
            original.object_key, original.sha256, original.byte_size = replacement.object_key, replacement.sha256, replacement.byte_size
            with self.assertRaisesRegex(ValueError, 'immutable'): original.save()
            # Inject persisted-row corruption beyond the normal immutable model guard.
            Artifact.all_objects.filter(pk=original.pk).update(object_key=replacement.object_key,
                sha256=replacement.sha256, byte_size=replacement.byte_size)
            original.refresh_from_db()
            with self.assertRaisesRegex(ValueError, 'review'): mps_dpo._preferences(original, self.tenant.pk, self.project.pk)
