"""Actual published text/base weights through durable CPU SFT and recovery."""
import base64
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient
from modelanvil.artifacts.models import Artifact, Dataset
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job, reconcile_expired_leases
from modelanvil.jobs.models import OutboxEvent
from modelanvil.runners.models import Model, ModelVersion, RunnerManifest, TokenizerVersion, TrainingRun
from modelanvil.runners.training.engine import CausalTextModel, TrainingEngine, pack_safetensors
from modelanvil.runners.training.engine import unpack_safetensors
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.runners.training.runtime import CONTRACT_DIGEST, LIMITS, RUNTIME_ID, digest, runner_manifest, checkpoint_bundle


@override_settings(ALLOWED_HOSTS=['testserver'])
class CpuRuntimeTests(TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(); self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': root.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='cpu-runtime', name='CPU reference')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name='engineer', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef \n')]
        self.spec = {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}
        self.tok = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, name='character', vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
        self.model = CausalTextModel(len(tokens), n_embd=4, lora_r=2, lora_alpha=4, seed=123)
        self.raw, weights = pack_safetensors(self.model.export_tensors())
        self.bundle = {'config.json': {'vocab_size': len(tokens), 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4}, 'weights_manifest.json': weights,
            'model.safetensors.b64': base64.b64encode(self.raw).decode(), 'tokenizer_config.json': self.spec}
        base_artifact = self.artifact('base.json', json.dumps(self.bundle).encode(), 'application/json')
        model = Model.objects.create(tenant_id=self.tenant.pk, name='Tiny numerical base')
        self.base = ModelVersion.objects.create(tenant_id=self.tenant.pk, model=model, revision_no=1, tokenizer=self.tok,
            architecture_ref=RUNTIME_ID, artifact_manifest_id=str(base_artifact.artifact_id))
        dataset = Dataset.objects.create(tenant_id=self.tenant.pk, name='Real text')
        rows = [self.envelope(i, text) for i, text in enumerate(['ab ab ab', 'cd cd cd'])]
        source = self.artifact('samples.jsonl', b''.join(json.dumps(r).encode() + b'\n' for r in rows), 'application/x-ndjson')
        self.dataset = publish_prepared_dataset(dataset, source, validation_percent=0, test_percent=0)
        manifest = runner_manifest()
        self.runner = RunnerManifest.objects.create(tenant_id=self.tenant.pk, name='CPU contract', version='1',
            manifest=manifest, digest=digest(manifest), compatibility={'contract_digest': CONTRACT_DIGEST})
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='local-cpu', queue_name='cpu', status='active')
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, name='local', pool=self.pool, slots=1,
            capabilities={'training_runtime': CONTRACT_DIGEST, 'memory_bytes': LIMITS['memory_bytes']}, status=Worker.Status.AVAILABLE)
        self.policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name='step budget', period='lifetime', unit='training_steps', limit_amount=100)

    def artifact(self, key, raw, media):
        artifact = Artifact.objects.create(tenant_id=self.tenant.pk, storage_location_id='local', object_key=key,
            sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type=media)
        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
        return artifact

    def envelope(self, i, text):
        return {'schema_version': '1.0', 'sample_id': str(uuid.uuid4()), 'source_group_id': str(i),
            'blocks': [{'block_id': 'text', 'type': 'text', 'text': text}],
            'provenance': {'source_snapshot_ref': 'reference', 'source_record_key': str(i), 'content_sha256': hashlib.sha256(text.encode()).hexdigest()}}

    def payload(self):
        return {'recipe_type': 'full_sft', 'tokenizer_version': self.tok.pk, 'base_model_version': self.base.pk,
            'dataset_revision': self.dataset.pk, 'runner_manifest': self.runner.pk, 'pool': self.pool.pk,
            'budget_policy_id': str(self.policy.policy_id), 'total_steps': 4}

    def launch(self, key='reference', **changes):
        payload = {**self.payload(), **changes}
        response = self.client.post('/api/v1/training-runs/', payload, format='json', HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(response.status_code, 201, response.data)
        return TrainingRun.all_objects.get(run_id=response.data['run_id'])

    def execute(self, run):
        descriptor = claim_job(self.worker)
        self.assertIsNotNone(descriptor)
        outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertTrue(outcome['committed'], outcome)
        self.assertEqual(outcome['status'], JobAttempt.Status.SUCCEEDED, JobAttempt.all_objects.last().error)
        run.refresh_from_db(); return run

    def test_actual_weights_samples_metrics_atomic_dispatch_and_independent_inference(self):
        run = self.launch()
        repeat = self.launch(); self.assertEqual(run.pk, repeat.pk)
        self.assertEqual(Job.all_objects.count(), 1)
        self.assertEqual(BudgetReservation.all_objects.count(), 1)
        self.assertEqual(OutboxEvent.all_objects.filter(payload__job_id=str(run.job.job_id)).count(), 1)
        run = self.execute(run)
        self.assertEqual(run.status, 'completed'); self.assertEqual(run.checkpoints.count(), 4)
        checkpoint = run.checkpoints.get(step=4)
        self.assertNotEqual(checkpoint.weights_manifest['weights']['weights_sha256'], self.bundle['weights_manifest.json']['weights_sha256'])
        self.assertEqual([m['training_pairs'] for m in run.metrics_log], [9] * 4)
        self.assertTrue(all(m['cpu_seconds'] > 0 for m in run.metrics_log))
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount, 4)
        self.assertEqual(UsageEvent.all_objects.get().quantity, 4)
        response = self.client.post(f'/api/v1/training-runs/{run.run_id}/export/')
        self.assertEqual(response.status_code, 200, response.data)
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'bundle.json'; file.write_text(json.dumps(response.data['bundle']))
            completed = subprocess.run([sys.executable, '-I', 'scripts/cpu_character_infer.py', str(file), '--prompt', 'ab'], capture_output=True, text=True, check=True)
        external = json.loads(completed.stdout)
        internal = TrainingEngine.generate_candidate_completion(response.data['bundle'], 'ab')
        self.assertEqual(external['generated_token_ids'], internal['generated_token_ids'])
        self.assertEqual(external['weights_sha256'], internal['weights_sha256'])
        self.assertTrue(internal['decoded_text'])
        report_path = os.environ.get('MODELANVIL_CPU_REPORT_PATH')
        if report_path:
            report = {'environment': {'platform': platform.platform(), 'machine': platform.machine(),
                'python': platform.python_version(), 'processor': platform.processor()},
                'contract_digest': CONTRACT_DIGEST, 'pins': run.hardware_config['pins'],
                'metrics': run.metrics_log, 'usage': {'training_steps': run.current_step,
                    'training_pairs': sum(m['training_pairs'] for m in run.metrics_log),
                    'cpu_seconds': sum(m['cpu_seconds'] for m in run.metrics_log)},
                'checkpoint_digest': checkpoint.state_digest,
                'external_inference': external, 'internal_inference': internal}
            Path(report_path).write_text(json.dumps(report, indent=2))
            Path(report_path).with_suffix('.bundle.json').write_text(json.dumps(response.data['bundle'], indent=2))
        self.assertEqual(self.client.post(f'/api/v1/training-runs/{run.run_id}/train-steps/', {'steps': 1}, format='json').status_code, 400)

    def test_budget_failure_rolls_back_run_job_outbox_and_idempotency(self):
        self.policy.limit_amount = 1; self.policy.save()
        response = self.client.post('/api/v1/training-runs/', self.payload(), format='json', HTTP_IDEMPOTENCY_KEY='too-much')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(TrainingRun.all_objects.count(), 0); self.assertEqual(Job.all_objects.count(), 0)
        self.assertEqual(OutboxEvent.all_objects.count(), 0); self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_unsupported_and_changed_inputs_stop_without_candidate(self):
        response = self.client.post('/api/v1/training-runs/', {**self.payload(), 'recipe_type': 'lora_adapter'}, format='json', HTTP_IDEMPOTENCY_KEY='unsupported')
        self.assertEqual(response.status_code, 400); self.assertEqual(Job.all_objects.count(), 0)
        run = self.launch()
        self.tok.compatibility = {'character_v1': {'tokens': self.spec['tokens'][:-1] + ['x']}}; self.tok.save()
        descriptor = claim_job(self.worker)
        outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertEqual(outcome['status'], 'failed'); run.refresh_from_db()
        self.assertEqual(run.status, 'failed'); self.assertEqual(run.checkpoints.count(), 0)
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount, 0)

    def test_expired_worker_cannot_publish_and_recovery_matches_uninterrupted_weights(self):
        run = self.launch()
        descriptor = claim_job(self.worker)
        original = CausalTextModel.compute_loss_and_step
        calls = 0
        def expire(model, sequence, learning_rate):
            nonlocal calls
            result = original(model, sequence, learning_rate); calls += 1
            if calls == 3:
                JobAttempt.all_objects.filter(attempt_id=descriptor['attempt_id']).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
            return result
        with patch.object(CausalTextModel, 'compute_loss_and_step', expire):
            outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertFalse(outcome['committed']); run.refresh_from_db()
        self.assertEqual(run.current_step, 2); self.assertEqual(run.checkpoints.count(), 2)
        reconcile_expired_leases()
        run = self.execute(run)
        recovered = run.checkpoints.get(step=4).weights_manifest['weights']['weights_sha256']
        comparison = self.execute(self.launch(key='uninterrupted'))
        self.assertEqual(recovered, comparison.checkpoints.get(step=4).weights_manifest['weights']['weights_sha256'])
        self.assertEqual(BudgetReservation.all_objects.count(), 2); self.assertEqual(UsageEvent.all_objects.count(), 2)
        self.assertEqual(JobAttempt.all_objects.filter(job=run.job).count(), 2)

    def test_cancellation_acknowledges_fence_and_settles_only_committed_steps(self):
        run = self.launch(); descriptor = claim_job(self.worker)
        original = CausalTextModel.compute_loss_and_step
        calls = 0
        def cancel(model, sequence, learning_rate):
            nonlocal calls
            result = original(model, sequence, learning_rate); calls += 1
            if calls == 2:
                response = self.client.post(f'/api/v1/training-runs/{run.run_id}/cancel/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(BudgetReservation.all_objects.get().state, 'reserved')
            return result
        with patch.object(CausalTextModel, 'compute_loss_and_step', cancel):
            outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertTrue(outcome['committed']); run.refresh_from_db(); self.assertEqual(run.status, 'cancelled')
        self.assertEqual(run.current_step, 1); self.assertIsNone(run.output_model_version_id)
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount, 1)

    def test_checkpoint_corruption_is_rejected(self):
        run = self.execute(self.launch())
        checkpoint = run.checkpoints.last(); checkpoint.weights_manifest['optimizer']['updates'] += 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            checkpoint_bundle(run, checkpoint)

    def test_selected_base_weights_and_exact_encoded_samples_determine_result(self):
        run = self.launch()
        from modelanvil.runners.training.runtime import resolve_inputs
        inputs = resolve_inputs(dataset=self.dataset, base=self.base, tokenizer=self.tok, runner=self.runner,
            pool=self.pool, tenant=self.tenant.pk, project=None, steps=4)
        model, _ = TrainingEngine._load_export_model(self.bundle)
        for step in range(4):
            model.compute_loss_and_step(inputs['sequences'][step % len(inputs['sequences'])], 0.05)
            raw, _ = pack_safetensors(model.export_tensors())
            model.import_tensors(unpack_safetensors(raw))
        _, expected = pack_safetensors(model.export_tensors())
        run = self.execute(run)
        self.assertEqual(run.checkpoints.get(step=4).weights_manifest['weights']['weights_sha256'], expected['weights_sha256'])

    def test_queued_cancel_and_exhausted_retry_settle_reservation(self):
        run = self.launch()
        response = self.client.post(f'/api/v1/training-runs/{run.run_id}/cancel/')
        self.assertEqual(response.status_code, 200); run.refresh_from_db()
        self.assertEqual(run.status, 'cancelled'); self.assertIsNone(claim_job(self.worker))
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount, 0)
        second = self.launch(key='retry-exhaustion')
        for _ in range(3):
            descriptor = claim_job(self.worker)
            JobAttempt.all_objects.filter(attempt_id=descriptor['attempt_id']).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
            reconcile_expired_leases()
        second.refresh_from_db(); self.assertEqual(second.status, 'failed')
        self.assertEqual(BudgetReservation.all_objects.get(job_id=second.job.job_id).settled_amount, 0)

    def test_configuration_and_job_are_immutable_and_repeated_export_reuses_candidate(self):
        run = self.launch()
        for method, url, payload in [('patch', f'/api/v1/training-runs/{run.run_id}/', {'total_steps': 8}),
                                     ('patch', f'/api/v1/jobs/{run.job.job_id}/', {'payload': {}})]:
            response = getattr(self.client, method)(url, payload, format='json')
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.delete(f'/api/v1/jobs/{run.job.job_id}/').status_code, 400)
        self.assertEqual(self.client.delete(f'/api/v1/training-runs/{run.run_id}/').status_code, 400)
        self.assertEqual(self.client.post(f'/api/v1/training-runs/{run.run_id}/export/').status_code, 400)
        self.execute(run)
        first = self.client.post(f'/api/v1/training-runs/{run.run_id}/export/')
        second = self.client.post(f'/api/v1/training-runs/{run.run_id}/export/')
        self.assertEqual(first.data, second.data)
        self.assertEqual(ModelVersion.all_objects.count(), 2)

    def test_launch_rejects_changed_idempotency_and_incompatible_reference_resources(self):
        self.launch()
        response = self.client.post('/api/v1/training-runs/', {**self.payload(), 'total_steps': 8}, format='json', HTTP_IDEMPOTENCY_KEY='reference')
        self.assertEqual(response.status_code, 409)
        cases = [({'tokenizer_version': None}, 'tokenizer'), ({'runner_manifest': None}, 'runner'),
                 ({'dataset_revision': None}, 'dataset'), ({'pool': None}, 'pool'), ({'budget_policy_id': None}, 'budget')]
        for fields, key in cases:
            response = self.client.post('/api/v1/training-runs/', {**self.payload(), **fields}, format='json', HTTP_IDEMPOTENCY_KEY=key)
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Job.all_objects.count(), 1)

    def test_full_sft_gradient_uses_pre_update_parameters_including_embeddings(self):
        # Finite differences against one token pair detect incorrect update ordering.
        model = self.model
        model.lm_head[5][0] = 0.3; model.lora_B[0][0] = 0.2
        parameters = [(model.wte, 4, 0), (model.lm_head, 5, 0), (model.lora_A, 0, 0), (model.lora_B, 0, 0)]
        expected = []
        epsilon = 1e-5
        for matrix, row, column in parameters:
            value = matrix[row][column]
            matrix[row][column] = value + epsilon; high = model.compute_loss([4, 5])
            matrix[row][column] = value - epsilon; low = model.compute_loss([4, 5])
            matrix[row][column] = value
            expected.append((value, (high - low) / (2 * epsilon)))
        model.compute_loss_and_step([4, 5], 0.05)
        for (matrix, row, column), (value, gradient) in zip(parameters, expected):
            self.assertAlmostEqual(matrix[row][column], value - 0.05 * gradient, places=8)

    def test_operator_reference_setup_produces_browser_selectable_inputs(self):
        from modelanvil.identity.models import Project, Team
        team = Team.objects.create(tenant_id=self.tenant.pk, slug='cpu-team', name='CPU team')
        project = Project.objects.create(tenant_id=self.tenant.pk, team=team, slug='cpu-project', name='CPU project')
        output = io.StringIO()
        call_command('setup_cpu_training_reference', tenant_id=self.tenant.pk, project_id=project.pk, name='reference-install', stdout=output)
        installed = json.loads(output.getvalue())
        response = self.client.post('/api/v1/training-runs/', installed['launch'], format='json', HTTP_IDEMPOTENCY_KEY='installed')
        self.assertEqual(response.status_code, 201, response.content)
        run = TrainingRun.all_objects.get(run_id=response.data['run_id'])
        worker = Worker.all_objects.get(pk=installed['worker_id'])
        descriptor = claim_job(worker)
        result = execute_claim(worker, descriptor, training_worker_executor)
        self.assertEqual(result['status'], 'succeeded', JobAttempt.all_objects.last().error)
        run.refresh_from_db(); self.assertEqual(run.status, 'completed')

    def test_earlier_worker_contract_is_unknown_evidence_not_synthetic(self):
        from modelanvil.runners.evidence import training_evidence, model_evidence
        run = self.execute(self.launch())
        run.hardware_config['pins']['contract_digest'] = '0' * 64
        run.save(update_fields=['hardware_config'])
        self.assertEqual(training_evidence(run)['level'], 'unknown')
        self.assertEqual(model_evidence(run.output_model_version)['level'], 'unknown')
