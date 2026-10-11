"""End-to-end tests for the registered general transformer runtime contract."""
import base64
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
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job
from modelanvil.runners.models import Model, ModelVersion, RunnerManifest, TokenizerVersion, TrainingRun
from modelanvil.runners.training.engine import pack_safetensors
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.runners.training.general_runtime import (
    CONTRACT_DIGEST, LIMITS, RUNTIME_ID, digest, runner_manifest, tokenizer_spec, checkpoint_bundle,
)
from modelanvil.runners.training.general_transformer import GeneralTransformer
from modelanvil.runners.training import registry


@override_settings(ALLOWED_HOSTS=['testserver'])
class GeneralRuntimeTests(TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(); self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': root.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='general-runtime', name='General reference')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name='engineer', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.tok = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, name='bytes',
            vocabulary_size=LIMITS['vocab_size'], compatibility={'byte_v1': {'vocab_size': LIMITS['vocab_size']}},
            special_tokens={'pad_token': '<pad>', 'bos_token': '<bos>', 'eos_token': '<eos>', 'unk_token': '<unk>'})
        self.spec = tokenizer_spec(self.tok)
        self.model = GeneralTransformer(vocab_size=LIMITS['vocab_size'], n_layer=1, n_head=2, n_embd=8, context_window=16, seed=11)
        raw, weights = pack_safetensors(self.model.export_tensors())
        config = {'vocab_size': LIMITS['vocab_size'], 'n_layer': 1, 'n_head': 2, 'n_embd': 8, 'context_window': 16, 'runtime': RUNTIME_ID}
        self.bundle = {'config.json': config, 'tokenizer_config.json': self.spec,
                       'model.safetensors.b64': base64.b64encode(raw).decode(), 'weights_manifest.json': weights}
        base_artifact = self.artifact('base.json', json.dumps(self.bundle).encode(), 'application/json')
        model = Model.objects.create(tenant_id=self.tenant.pk, name='Tiny transformer base')
        self.base = ModelVersion.objects.create(tenant_id=self.tenant.pk, model=model, revision_no=1, tokenizer=self.tok,
            architecture_ref=RUNTIME_ID, artifact_manifest_id=str(base_artifact.artifact_id),
            metadata={'vocab_size': LIMITS['vocab_size'], 'runtime': RUNTIME_ID})
        dataset = Dataset.objects.create(tenant_id=self.tenant.pk, name='Byte text')
        rows = [self.envelope(i, text) for i, text in enumerate(['ab', 'cd'])]
        source = self.artifact('samples.jsonl', b''.join(json.dumps(r).encode() + b'\n' for r in rows), 'application/x-ndjson')
        self.dataset = publish_prepared_dataset(dataset, source, validation_percent=0, test_percent=0)
        manifest = runner_manifest()
        self.runner = RunnerManifest.objects.create(tenant_id=self.tenant.pk, name='general contract', version='1',
            manifest=manifest, digest=digest(manifest), compatibility={'contract_digest': CONTRACT_DIGEST})
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='local-cpu', queue_name='general-cpu', status='active')
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

    def payload(self, **changes):
        return {'recipe_type': 'full_sft', 'tokenizer_version': self.tok.pk, 'base_model_version': self.base.pk,
            'dataset_revision': self.dataset.pk, 'runner_manifest': self.runner.pk, 'pool': self.pool.pk,
            'budget_policy_id': str(self.policy.policy_id), 'total_steps': 2, **changes}

    def launch(self, key='reference', **changes):
        response = self.client.post('/api/v1/training-runs/', self.payload(**changes), format='json', HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(response.status_code, 201, response.data)
        return TrainingRun.all_objects.get(run_id=response.data['run_id'])

    def execute(self, run):
        descriptor = claim_job(self.worker)
        self.assertIsNotNone(descriptor)
        outcome = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertTrue(outcome['committed'], outcome)
        self.assertEqual(outcome['status'], JobAttempt.Status.SUCCEEDED, JobAttempt.all_objects.last().error)
        run.refresh_from_db(); return run

    def test_worker_path_trains_checkpoints_exports_and_infers(self):
        run = self.launch()
        self.assertEqual(run.hardware_config['pins']['runtime'], RUNTIME_ID)
        self.assertNotEqual(run.hardware_config['pins']['contract_digest'], None)
        run = self.execute(run)
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.checkpoints.count(), 2)
        self.assertEqual([m['training_pairs'] for m in run.metrics_log], [3, 3])
        self.assertEqual(BudgetReservation.all_objects.get().settled_amount, 2)
        self.assertEqual(UsageEvent.all_objects.get().quantity, 2)
        self.assertEqual(UsageEvent.all_objects.get().detail['runtime'], RUNTIME_ID)
        self.assertEqual(run.output_model_version.architecture_ref, RUNTIME_ID)

        export = self.client.post(f'/api/v1/training-runs/{run.run_id}/export/')
        self.assertEqual(export.status_code, 200, export.data)
        self.assertEqual(export.data['verification']['verification_scope'], 'local_modelanvil_general_transformer_runtime')

        infer = self.client.post(f'/api/v1/training-runs/{run.run_id}/infer/', {'prompt': 'ab', 'max_tokens': 4}, format='json')
        self.assertEqual(infer.status_code, 200, infer.data)
        self.assertTrue(infer.data['inference']['decoded_text'])
        self.assertIsInstance(infer.data['inference']['completion'], str)

    def test_evidence_is_integrated_for_general_runtime(self):
        run = self.execute(self.launch())
        from modelanvil.runners.evidence import training_evidence
        report = training_evidence(run)
        self.assertEqual(report['level'], 'integrated_execution')
        self.assertEqual(report['runtime_scope'], RUNTIME_ID)

    def test_checkpoint_corruption_is_rejected(self):
        run = self.execute(self.launch())
        checkpoint = run.checkpoints.get(step=1)
        checkpoint.weights_manifest['adam']['t'] += 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            checkpoint_bundle(run, checkpoint)

    def test_unknown_base_architecture_is_rejected(self):
        self.base.architecture_ref = 'modelanvil.not-a-runtime'
        self.base.save(update_fields=['architecture_ref'])
        response = self.client.post('/api/v1/training-runs/', self.payload(), format='json', HTTP_IDEMPOTENCY_KEY='unknown-arch')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Job.all_objects.count(), 0)

    def test_registry_dispatch_and_contract_endpoint(self):
        self.assertEqual(registry.runtime_for_architecture(RUNTIME_ID).RUNTIME_ID, RUNTIME_ID)
        self.assertEqual(registry.runtime_for_architecture('modelanvil.cpu-character-sft.v1').RUNTIME_ID, 'modelanvil.cpu-character-sft.v1')
        self.assertIsNone(registry.runtime_for_architecture('nope'))
        response = self.client.get(f'/api/v1/training-runs/runtime-contract/?runtime={RUNTIME_ID}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['contract_digest'], CONTRACT_DIGEST)

    def test_preflight_resolves_general_samples(self):
        response = self.client.post('/api/v1/training-runs/preflight/', self.payload(), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        report = response.data
        self.assertEqual(report['status'], 'approved', report['checks'])
        self.assertEqual(len(report['samples']), 2)
        self.assertGreater(report['samples'][0]['token_count'], 0)

    def test_operator_reference_setup_produces_browser_selectable_inputs(self):
        from django.core.management import call_command
        from modelanvil.identity.models import Project, Team
        team = Team.objects.create(tenant_id=self.tenant.pk, slug='general-team', name='General team')
        project = Project.objects.create(tenant_id=self.tenant.pk, team=team, slug='general-project', name='General project')
        output = io.StringIO()
        call_command('setup_general_training_reference', tenant_id=self.tenant.pk, project_id=project.pk, name='general-install', stdout=output)
        installed = json.loads(output.getvalue())
        response = self.client.post('/api/v1/training-runs/', installed['launch'], format='json', HTTP_IDEMPOTENCY_KEY='installed')
        self.assertEqual(response.status_code, 201, response.content)
        run = TrainingRun.all_objects.get(run_id=response.data['run_id'])
        self.assertEqual(run.hardware_config['pins']['runtime'], RUNTIME_ID)
        worker = Worker.all_objects.get(pk=installed['worker_id'])
        descriptor = claim_job(worker)
        result = execute_claim(worker, descriptor, training_worker_executor)
        self.assertEqual(result['status'], 'succeeded', JobAttempt.all_objects.last().error)
        run.refresh_from_db(); self.assertEqual(run.status, 'completed')
