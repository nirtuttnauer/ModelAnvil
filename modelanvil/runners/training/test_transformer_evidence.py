"""Fenced-protocol, split-integrity, separate-process and hardware evidence for the transformer runtime.

These tests cover the TASK-13 acceptance criteria this environment can actually
exercise on the registered ``modelanvil.general-transformer-sft.v1`` contract:
measured optimizer updates through the durable worker protocol,
cancellation/expiry/corruption refusing to publish a candidate, budget
settlement reflecting committed work, an independent process decoding the
produced weights, and a measured hardware report that names no accelerator.
"""
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.data.publication import _read_verified_input, publish_prepared_dataset
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job, reconcile_expired_leases
from modelanvil.runners.models import Model, ModelVersion, RunnerManifest, TokenizerVersion, TrainingRun
from modelanvil.runners.training.engine import pack_safetensors
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.runners.training.general_runtime import (
    CONTRACT_DIGEST, LIMITS, RUNTIME_ID, checkpoint_bundle, digest, generate_candidate_completion,
    runner_manifest, tokenizer_spec,
)
from modelanvil.runners.training.general_transformer import AdamW, GeneralTransformer

INDEPENDENT_INFER = Path(__file__).resolve().parent / 'independent_infer.py'


@override_settings(ALLOWED_HOSTS=['testserver'])
class TransformerRuntimeEvidenceTests(TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(); self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': root.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='transformer-evidence', name='Transformer evidence')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name='engineer', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.tok = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, name='bytes',
            vocabulary_size=LIMITS['vocab_size'], compatibility={'byte_v1': {'vocab_size': LIMITS['vocab_size']}},
            special_tokens={'pad_token': '<pad>', 'bos_token': '<bos>', 'eos_token': '<eos>', 'unk_token': '<unk>'})
        self.spec = tokenizer_spec(self.tok)
        self.model = GeneralTransformer(vocab_size=LIMITS['vocab_size'], n_layer=1, n_head=1,
                                        n_embd=4, context_window=16, seed=11)
        raw, weights = pack_safetensors(self.model.export_tensors())
        self.bundle = {'config.json': {'vocab_size': LIMITS['vocab_size'], 'n_layer': 1, 'n_head': 1,
                                       'n_embd': 4, 'context_window': 16, 'runtime': RUNTIME_ID},
                       'tokenizer_config.json': self.spec, 'model.safetensors.b64': base64.b64encode(raw).decode(),
                       'weights_manifest.json': weights}
        self.base_artifact = self.artifact('base.json', json.dumps(self.bundle).encode(), 'application/json')
        model = Model.objects.create(tenant_id=self.tenant.pk, name='Transformer base')
        self.base = ModelVersion.objects.create(tenant_id=self.tenant.pk, model=model, revision_no=1,
            tokenizer=self.tok, architecture_ref=RUNTIME_ID,
            artifact_manifest_id=str(self.base_artifact.artifact_id), metadata={'runtime': RUNTIME_ID})
        rows = [self.envelope(index, text) for index, text in enumerate(
            ['ab', 'cd', 'ef', 'gh'])]
        source = self.artifact('samples.jsonl', b''.join(json.dumps(row).encode() + b'\n' for row in rows),
                               'application/x-ndjson')
        self.dataset = publish_prepared_dataset(
            dataset=Dataset.objects.create(tenant_id=self.tenant.pk, name='Published text'),
            artifact=source, validation_percent=25, test_percent=25)
        manifest = runner_manifest()
        self.runner = RunnerManifest.objects.create(tenant_id=self.tenant.pk, name='transformer contract',
            version='1', manifest=manifest, digest=digest(manifest),
            compatibility={'contract_digest': CONTRACT_DIGEST})
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='local-cpu',
                                              queue_name='transformer-cpu', status='active')
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, name='local', pool=self.pool, slots=1,
            capabilities={'training_runtime': CONTRACT_DIGEST, 'memory_bytes': LIMITS['memory_bytes']},
            status=Worker.Status.AVAILABLE)
        self.policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name='step budget',
                                                  period='lifetime', unit='training_steps', limit_amount=100)
        self.prepared = json.loads(self.read(self.dataset.manifest_artifact))
        self.train_ids = set(self.prepared['split_manifest']['train'])
        self.held_out = {name: set(ids) for name, ids in self.prepared['split_manifest'].items()
                         if name != 'train'}

    def artifact(self, key, raw, media):
        artifact = Artifact.objects.create(tenant_id=self.tenant.pk, storage_location_id='local',
            object_key=key, sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type=media)
        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
        return artifact

    def read(self, artifact):
        return _read_verified_input(artifact, artifact_storage_backend())

    def envelope(self, index, text):
        return {'schema_version': '1.0', 'sample_id': str(uuid.uuid4()), 'source_group_id': str(index),
                'blocks': [{'block_id': 'text', 'type': 'text', 'text': text}],
                'provenance': {'source_snapshot_ref': 'evidence', 'source_record_key': str(index),
                               'content_sha256': hashlib.sha256(text.encode()).hexdigest()}}

    def payload(self, **changes):
        return {'recipe_type': 'full_sft', 'tokenizer_version': self.tok.pk, 'base_model_version': self.base.pk,
                'dataset_revision': self.dataset.pk, 'runner_manifest': self.runner.pk, 'pool': self.pool.pk,
                'budget_policy_id': str(self.policy.policy_id), 'total_steps': 3, **changes}

    def launch(self, key='evidence', **changes):
        response = self.client.post('/api/v1/training-runs/', self.payload(**changes), format='json',
                                    HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(response.status_code, 201, response.content)
        return TrainingRun.all_objects.get(run_id=response.data['run_id'])

    def execute(self, run):
        descriptor = claim_job(self.worker)
        self.assertIsNotNone(descriptor)
        outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        run.refresh_from_db()
        return outcome

    # -- pinned splits and recorded hashes ----------------------------------
    def test_only_the_published_train_split_is_consumed_and_hashes_are_recorded(self):
        self.assertTrue(self.train_ids, 'the published revision must declare a nonempty train split')
        self.assertEqual(self.train_ids & set().union(*self.held_out.values()), set())
        run = self.launch(total_steps=2)
        pins = run.hardware_config['pins']
        self.assertEqual(pins['splits']['consumed'], 'train')
        self.assertEqual(pins['splits']['train_rows'], len(self.train_ids))
        self.assertEqual(pins['splits']['excluded_rows'],
                         {name: len(ids) for name, ids in sorted(self.held_out.items())})
        self.assertEqual(pins['dataset_digest'], self.dataset.manifest_digest)
        self.assertEqual(pins['base_digest'], hashlib.sha256(self.read(self.base_artifact)).hexdigest())
        self.assertEqual(pins['tokenizer_digest'], digest(self.spec))
        self.assertEqual(len(pins['build_digest']), 64)
        self.assertEqual(pins['contract_digest'], CONTRACT_DIGEST)

        outcome = self.execute(run)
        self.assertEqual(outcome['status'], JobAttempt.Status.SUCCEEDED)
        trained = {metric['sample_id'] for metric in run.metrics_log}
        self.assertTrue(trained)
        self.assertTrue(trained <= self.train_ids)
        self.assertEqual(trained & set().union(*self.held_out.values()), set())

    def publish_tampered_manifest(self, prepared):
        """Publish a revision whose manifest declares a defective split."""
        payload = json.dumps(prepared).encode()
        artifact = self.artifact(f'tampered-{uuid.uuid4()}.json', payload, 'application/json')
        revision = DatasetRevision.objects.create(
            tenant_id=self.tenant.pk, dataset_id=self.dataset.dataset_id,
            revision_no=self.dataset.revision_no + 1, schema_version=self.dataset.schema_version,
            manifest_digest=hashlib.sha256(payload).hexdigest(), manifest_artifact=artifact,
            recipe_digest=self.dataset.recipe_digest, source_snapshots=self.dataset.source_snapshots,
            row_count=self.dataset.row_count)
        revision.publish()
        return revision

    def test_contaminated_split_is_refused_before_dispatch(self):
        prepared = json.loads(json.dumps(self.prepared))
        held_out_name = next(name for name in prepared['split_manifest'] if name != 'train')
        prepared['split_manifest'][held_out_name] = [*prepared['split_manifest'][held_out_name],
                                                     prepared['split_manifest']['train'][0]]
        revision = self.publish_tampered_manifest(prepared)
        response = self.client.post('/api/v1/training-runs/',
                                    self.payload(dataset_revision=revision.pk), format='json',
                                    HTTP_IDEMPOTENCY_KEY='contaminated')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(TrainingRun.all_objects.count(), 0)
        self.assertEqual(Job.all_objects.count(), 0)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_held_out_split_referencing_absent_samples_is_refused(self):
        prepared = json.loads(json.dumps(self.prepared))
        held_out_name = next(name for name in prepared['split_manifest'] if name != 'train')
        prepared['split_manifest'][held_out_name] = [*prepared['split_manifest'][held_out_name],
                                                     str(uuid.uuid4())]
        revision = self.publish_tampered_manifest(prepared)
        response = self.client.post('/api/v1/training-runs/',
                                    self.payload(dataset_revision=revision.pk), format='json',
                                    HTTP_IDEMPOTENCY_KEY='missing-split')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Job.all_objects.count(), 0)

    # -- fenced protocol ----------------------------------------------------
    def test_expired_worker_cannot_publish_and_recovery_matches_uninterrupted_weights(self):
        run = self.launch()
        descriptor = claim_job(self.worker)
        original = AdamW.step
        calls = 0

        def expire(optimizer):
            nonlocal calls
            calls += 1
            result = original(optimizer)
            if calls == 2:
                JobAttempt.all_objects.filter(attempt_id=descriptor['attempt_id']).update(
                    lease_expires_at=timezone.now() - timedelta(seconds=1))
            return result

        with patch.object(AdamW, 'step', expire):
            outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertFalse(outcome['committed'])
        run.refresh_from_db()
        self.assertEqual(run.current_step, 1)
        self.assertEqual(run.checkpoints.count(), 1)
        self.assertIsNone(run.output_model_version_id)

        reconcile_expired_leases()
        outcome = self.execute(run)
        self.assertEqual(outcome['status'], JobAttempt.Status.SUCCEEDED, JobAttempt.all_objects.last().error)
        self.assertEqual(run.status, TrainingRun.Status.COMPLETED)
        recovered = run.checkpoints.get(step=3).weights_manifest['weights']['weights_sha256']

        comparison_run = self.launch(key='uninterrupted')
        comparison = self.execute(comparison_run)
        self.assertEqual(comparison['status'], JobAttempt.Status.SUCCEEDED)
        self.assertEqual(recovered,
                         comparison_run.checkpoints.get(step=3).weights_manifest['weights']['weights_sha256'])
        self.assertEqual(BudgetReservation.all_objects.count(), 2)
        self.assertEqual(UsageEvent.all_objects.count(), 2)
        self.assertEqual(JobAttempt.all_objects.filter(job=run.job).count(), 2)

    def test_cancellation_refuses_publication_and_settles_only_committed_steps(self):
        run = self.launch()
        descriptor = claim_job(self.worker)
        original = AdamW.step
        calls = 0

        def cancel(optimizer):
            nonlocal calls
            calls += 1
            result = original(optimizer)
            if calls == 2:
                response = self.client.post(f'/api/v1/training-runs/{run.run_id}/cancel/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(BudgetReservation.all_objects.get().state, 'reserved')
            return result

        with patch.object(AdamW, 'step', cancel):
            outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertTrue(outcome['committed'])
        run.refresh_from_db()
        self.assertEqual(run.status, TrainingRun.Status.CANCELLED)
        self.assertEqual(run.current_step, 1)
        self.assertIsNone(run.output_model_version_id)
        self.assertEqual(ModelVersion.all_objects.filter(
            tenant_id=self.tenant.pk, metadata__source_run_id=str(run.run_id)).count(), 0)
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount, 1)
        self.assertEqual(UsageEvent.all_objects.get().quantity, 1)

    def test_queued_cancellation_settles_zero_and_claims_nothing(self):
        run = self.launch()
        response = self.client.post(f'/api/v1/training-runs/{run.run_id}/cancel/')
        self.assertEqual(response.status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.status, TrainingRun.Status.CANCELLED)
        self.assertIsNone(claim_job(self.worker))
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount, 0)

    def test_corrupt_checkpoint_state_is_rejected(self):
        run = self.launch()
        self.assertEqual(self.execute(run)['status'], JobAttempt.Status.SUCCEEDED)
        checkpoint = run.checkpoints.get(step=3)
        checkpoint.weights_manifest['adam']['t'] += 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            checkpoint_bundle(run, checkpoint)

    def test_corrupt_pinned_input_after_launch_stops_without_candidate(self):
        run = self.launch()
        Artifact.all_objects.filter(pk=self.base_artifact.pk).update(sha256='0' * 64)
        outcome = self.execute(run)
        self.assertEqual(outcome['status'], JobAttempt.Status.FAILED)
        run.refresh_from_db()
        self.assertEqual(run.status, TrainingRun.Status.FAILED)
        self.assertEqual(run.checkpoints.count(), 0)
        self.assertIsNone(run.output_model_version_id)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.job.job_id).settled_amount, 0)

    def test_budget_admission_failure_rolls_back_run_job_and_reservation(self):
        self.policy.limit_amount = 1; self.policy.save()
        response = self.client.post('/api/v1/training-runs/', self.payload(), format='json',
                                    HTTP_IDEMPOTENCY_KEY='too-large')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(TrainingRun.all_objects.count(), 0)
        self.assertEqual(Job.all_objects.count(), 0)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_repeated_launch_reuses_one_chargeable_attempt(self):
        first = self.launch()
        second = self.launch()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Job.all_objects.count(), 1)
        self.assertEqual(BudgetReservation.all_objects.count(), 1)
        changed = self.client.post('/api/v1/training-runs/', self.payload(total_steps=9), format='json',
                                   HTTP_IDEMPOTENCY_KEY='evidence')
        self.assertEqual(changed.status_code, 409)

    # -- independent process ------------------------------------------------
    def test_separate_process_loads_produced_weights_and_decodes_identically(self):
        run = self.launch(total_steps=2)
        self.assertEqual(self.execute(run)['status'], JobAttempt.Status.SUCCEEDED)
        export = self.client.post(f'/api/v1/training-runs/{run.run_id}/export/')
        self.assertEqual(export.status_code, 200, export.data)
        bundle = export.data['bundle']
        internal = generate_candidate_completion(bundle, prompt='ab', max_new_tokens=6)

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'candidate.json'
            path.write_text(json.dumps(bundle))
            completed = subprocess.run(
                [sys.executable, '-I', str(INDEPENDENT_INFER), str(path), '--prompt', 'ab',
                 '--max-new-tokens', '6'], capture_output=True, text=True, check=True)
        external = json.loads(completed.stdout)
        self.assertTrue(external['is_loadable'])
        self.assertTrue(external['independent_runtime_verified'])
        self.assertFalse(external['production_qualified'])
        self.assertEqual(external['generated_token_ids'], internal['generated_token_ids'])
        self.assertEqual(external['weights_sha256'], internal['weights_sha256'])
        self.assertEqual(external['weights_sha256'], bundle['weights_manifest.json']['weights_sha256'])
        self.assertEqual(external['completion'], internal['completion'])
        self.assertTrue(external['decoded_text'])

        report_path = os.environ.get('MODELANVIL_TRANSFORMER_REPORT_PATH')
        if report_path:
            checkpoint = run.checkpoints.get(step=run.total_steps)
            report = {'runtime': RUNTIME_ID, 'contract_digest': CONTRACT_DIGEST,
                      'pins': run.hardware_config['pins'], 'metrics': run.metrics_log,
                      'usage': {'training_steps': run.current_step,
                                'training_pairs': sum(m['training_pairs'] for m in run.metrics_log),
                                'cpu_seconds': sum(m['cpu_seconds'] for m in run.metrics_log)},
                      'checkpoint_digest': checkpoint.state_digest,
                      'weights_sha256': bundle['weights_manifest.json']['weights_sha256'],
                      'internal_inference': internal, 'external_inference': external}
            Path(report_path).write_text(json.dumps(report, indent=2))
            Path(report_path).with_suffix('.bundle.json').write_text(json.dumps(bundle, indent=2))

    def test_separate_process_refuses_tampered_weights(self):
        run = self.launch(total_steps=2)
        self.assertEqual(self.execute(run)['status'], JobAttempt.Status.SUCCEEDED)
        export = self.client.post(f'/api/v1/training-runs/{run.run_id}/export/')
        bundle = json.loads(json.dumps(export.data['bundle']))
        bundle['weights_manifest.json']['weights_sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'tampered.json'
            path.write_text(json.dumps(bundle))
            completed = subprocess.run(
                [sys.executable, '-I', str(INDEPENDENT_INFER), str(path), '--prompt', 'ab'],
                capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 1)
        report = json.loads(completed.stdout)
        self.assertFalse(report['is_loadable'])
        self.assertIn('SHA-256', report['error'])

    def test_separate_process_never_imports_django_or_modelanvil(self):
        source = INDEPENDENT_INFER.read_text(encoding='utf-8')
        for forbidden in ('import django', 'from django', 'import modelanvil', 'from modelanvil'):
            self.assertNotIn(forbidden, source)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'bundle.json'
            path.write_text(json.dumps(self.bundle))
            probe = (
                'import importlib.util, json, sys;'
                'spec = importlib.util.spec_from_file_location("independent_infer", %r);'
                'module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module);'
                'module.main([%r, "--prompt", "ab"]);'
                'print(json.dumps(sorted(m for m in sys.modules '
                'if m.split(".")[0] in {"django", "modelanvil"})))'
            ) % (str(INDEPENDENT_INFER), str(path))
            completed = subprocess.run([sys.executable, '-I', '-c', probe],
                                       capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout.strip().splitlines()[-1]), [])


class HardwareReportTests(SimpleTestCase):
    def test_report_measures_the_host_and_qualifies_nothing(self):
        from modelanvil.runners.training.hardware import hardware_report

        report = hardware_report()
        self.assertIn(report['accelerator_status'], ('available', 'unavailable'))
        self.assertFalse(report['graphics_devices_are_training_capacity'])
        self.assertFalse(report['production_qualified'])
        self.assertFalse(report['hardware_qualified'])
        self.assertTrue(report['accelerator_reason'])
        self.assertTrue(report['host']['platform'])
        self.assertTrue(report['host']['python']['version'])
        registered = {entry['runtime_id'] for entry in report['runtimes']}
        self.assertIn(RUNTIME_ID, registered)
        for entry in report['runtimes']:
            self.assertEqual(len(entry['contract_digest']), 64)
            self.assertEqual(len(entry['build_digest']), 64)

    def test_a_graphics_adapter_is_never_reported_as_training_capacity(self):
        from modelanvil.runners.training import hardware

        with patch('modelanvil.accelerators.inventory', return_value={'backends': {}}):
            devices, reason = hardware.accelerators()
        self.assertEqual(devices, [])
        self.assertIn('not training capacity', reason)

    def test_report_is_serializable_and_stable_in_shape(self):
        from modelanvil.runners.training.hardware import hardware_report

        first = json.loads(json.dumps(hardware_report()))
        second = json.loads(json.dumps(hardware_report()))
        self.assertEqual(set(first), set(second))
        self.assertEqual(first['accelerator_status'], second['accelerator_status'])
        self.assertEqual(first['host']['platform'], second['host']['platform'])
