"""GPU input trust boundaries; these small fixtures do not qualify GPU hardware."""
import hashlib
import io
import json
import tempfile
from types import SimpleNamespace
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from modelanvil.artifacts.models import Artifact, Dataset
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import Tenant, Team, Project
from modelanvil.runners.training import hf_runtime as gpu


class GPUInputTests(TestCase):
    def test_guided_shuffle_visits_each_training_sample_once_and_replays_after_resume(self):
        pins = {'sample_order': 'seeded_epoch_shuffle_v1', 'initialization_seed': 42}
        first = [gpu.training_sample_index(step, 12, pins) for step in range(1, 13)]
        second = [gpu.training_sample_index(step, 12, pins) for step in range(13, 25)]
        self.assertEqual(sorted(first), list(range(12)))
        self.assertEqual(sorted(second), list(range(12)))
        self.assertNotEqual(first, second)
        self.assertEqual(first[7:], [gpu.training_sample_index(step, 12, pins) for step in range(8, 13)])
        self.assertEqual([gpu.training_sample_index(step, 12, {}) for step in range(1, 13)], list(range(12)))

    def test_checkpoint_selection_prefers_validation_to_final_training_loss(self):
        from unittest.mock import Mock
        early = SimpleNamespace(step=20, metrics={'validation_loss': 1.5, 'loss': 2.0})
        final = SimpleNamespace(step=30, metrics={'validation_loss': 2.0, 'loss': 0.1})
        checkpoints = Mock()
        checkpoints.filter.return_value.order_by.return_value = [early, final]
        run = SimpleNamespace(checkpoints=checkpoints, current_step=30)
        self.assertIs(gpu.best_checkpoint(run), early)
        checkpoints.filter.return_value.order_by.return_value = [SimpleNamespace(step=30, metrics={})]
        checkpoints.get.return_value = final
        self.assertIs(gpu.best_checkpoint(run), final)

    def setUp(self):
        root = tempfile.TemporaryDirectory(); self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_root': root.name, 'artifact_backend': 'filesystem'})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='gpu-guards', name='GPU guards')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        team = Team.objects.create(tenant_id=self.tenant.pk, name='Team', slug='gpu-guards')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='A', slug='a')
        self.other = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='B', slug='b')
        self.artifact = self.store(b'verified model bytes')

    def store(self, raw, media='application/octet-stream'):
        artifact = Artifact.all_objects.create(tenant_id=self.tenant.pk, project_id=self.project.pk,
            storage_location_id='local', object_key=f'guards/{uuid.uuid4()}',
            sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type=media)
        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
        return artifact

    def test_only_verified_artifacts_enter_allowlisted_staging_paths(self):
        files = {'config.json': gpu.file_ref(self.artifact)}
        with gpu.staged_files(files, self.tenant.pk, self.project.pk) as directory:
            self.assertEqual((directory / 'config.json').read_bytes(), b'verified model bytes')
            staged = directory
        self.assertFalse(staged.exists())
        for filename in ('../config.json', '/config.json', 'model.bin', 'custom_model.py'):
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                with gpu.staged_files({filename: gpu.file_ref(self.artifact)}, self.tenant.pk, self.project.pk):
                    self.fail('unsafe path entered staging')

    def test_foreign_project_and_tenant_references_are_refused(self):
        for tenant, project in ((self.tenant.pk, self.other.pk), (uuid.uuid4(), self.project.pk)):
            with self.assertRaises(ValueError):
                gpu._artifact(gpu.file_ref(self.artifact), tenant, project)

    def test_changed_artifact_metadata_or_bytes_are_refused(self):
        ref = gpu.file_ref(self.artifact)
        with self.assertRaises(ValueError):
            gpu._artifact({**ref, 'sha256': '0'*64}, self.tenant.pk, self.project.pk)
        backend = artifact_storage_backend()
        backend._path(self.tenant.pk, self.artifact.object_key, create_parent=False).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum|size'):
            with gpu.staged_files({'model.safetensors': ref}, self.tenant.pk, self.project.pk):
                self.fail('corrupt model reached loader')

    def test_unknown_or_insufficient_memory_and_fallback_are_refused(self):
        for memory in (None, gpu.LIMITS['gpu_memory_bytes'] - 1):
            with patch.object(gpu, 'inventory', return_value={}), patch.object(gpu, 'select_device', return_value={
                'backend':'mps', 'runtime_recommended_memory_bytes':memory}), patch.dict('os.environ', {'PYTORCH_ENABLE_MPS_FALLBACK':'0'}):
                with self.assertRaisesRegex(ValueError, 'memory capacity'):
                    gpu.observed_device('mps:0')
        with patch.object(gpu, 'inventory', return_value={}), patch.object(gpu, 'select_device', return_value={
                'backend':'mps'}), patch.dict('os.environ', {'PYTORCH_ENABLE_MPS_FALLBACK':'1'}):
            with self.assertRaisesRegex(ValueError, 'fallback'):
                gpu.observed_device('mps:0')

    def test_missing_committed_bytes_are_actionable(self):
        backend = artifact_storage_backend()
        backend._path(self.tenant.pk, self.artifact.object_key, create_parent=False).unlink()
        with self.assertRaisesRegex(ValueError, 'restore the committed'):
            with gpu.staged_files({'config.json': gpu.file_ref(self.artifact)}, self.tenant.pk, self.project.pk):
                self.fail('missing file reached loader')

    def test_mismatched_optional_package_versions_are_actionable(self):
        with patch.object(gpu.importlib.metadata, 'version', return_value='wrong'):
            with self.assertRaisesRegex(ValueError, 'Install the GPU runtime torch'):
                gpu.require_packages()

    def test_mps_process_headroom_counts_driver_and_cached_allocations(self):
        runtime = SimpleNamespace(mps=SimpleNamespace(recommended_max_memory=lambda: 10 * 1024**3,
            driver_allocated_memory=lambda: 7 * 1024**3))
        with patch.dict('sys.modules', {'torch': runtime}):
            memory = gpu.mps_memory()
        self.assertEqual(memory['process_limit_bytes'], 9 * 1024**3)
        self.assertEqual(memory['process_headroom_bytes'], 2 * 1024**3)
        with patch.object(gpu, 'inventory', return_value={'framework': {}}), patch.object(gpu, 'select_device',
            return_value={'backend': 'mps', 'runtime_recommended_memory_bytes': 10 * 1024**3}), \
            patch.object(gpu, 'mps_memory', return_value=memory), patch.dict('os.environ', {'PYTORCH_ENABLE_MPS_FALLBACK':'0'}):
            with self.assertRaisesRegex(ValueError, 'headroom is below'):
                gpu.observed_device('mps:0')

    def test_unsupported_gpu_options_are_rejected_by_launch_and_preview(self):
        from modelanvil.api.views.training_views import TrainingRunSerializer, TrainingPreflightSerializer
        from rest_framework.exceptions import ValidationError
        base = SimpleNamespace(architecture_ref=gpu.RUNTIME_ID)
        for serializer in (TrainingRunSerializer, TrainingPreflightSerializer):
            for options in ({'precision':'bf16'}, {'precision':'fp16'}, {'adapter':'lora'}, {'quantization':'int4'}):
                with self.assertRaisesRegex(ValidationError, 'FP32 full SFT only'):
                    serializer(data=options).validate_gpu_options({'base_model_version':base})
        gpu.validate_options(precision='fp32', adapter='none', quantization='none')

    def test_worker_capabilities_fail_closed_and_allow_only_one_slot(self):
        caps = {'training_runtime':gpu.CONTRACT_DIGEST,'memory_bytes':gpu.LIMITS['memory_bytes'],
                'gpu_backend':'mps','gpu_device':'mps:0','gpu_packages':gpu.PACKAGES}
        self.assertTrue(gpu.capable_worker(SimpleNamespace(capabilities=caps, slots=1)))
        self.assertTrue(gpu.capable_worker(SimpleNamespace(capabilities=caps, slots=0)))
        self.assertFalse(gpu.capable_worker(SimpleNamespace(capabilities=caps, slots=2)))
        for changes in ({'gpu_backend':'cpu'}, {'memory_bytes':True}, {'training_runtime':'unverified'}, {'gpu_packages':{}}):
            self.assertFalse(gpu.capable_worker(SimpleNamespace(capabilities={**caps,**changes}, slots=1)))

    def published(self):
        dataset = Dataset.all_objects.create(tenant_id=self.tenant.pk, project_id=self.project.pk, name='Protected samples')
        texts = ['Bright stars illuminate the night sky.', 'Fresh bread is baked in a hot oven.', 'Ocean currents move warm water.']
        rows = [{'schema_version':'1.0','sample_id':str(uuid.uuid4()),'source_group_id':str(i),
                 'blocks':[{'block_id':'t','type':'text','text':text}],
                 'provenance':{'source_snapshot_ref':'guard-fixture','source_record_key':str(i),'content_sha256':hashlib.sha256(text.encode()).hexdigest()}} for i,text in enumerate(texts)]
        source = self.store(b''.join(json.dumps(r).encode()+b'\n' for r in rows), 'application/x-ndjson')
        return publish_prepared_dataset(dataset, source, validation_percent=20, test_percent=20)

    def test_published_training_samples_exclude_held_out_identifiers(self):
        revision = self.published()
        tokenizer = SimpleNamespace(encode=lambda text, **kw: [1,2,3])
        samples, splits = gpu._training_samples(revision, tokenizer, self.tenant.pk, self.project.pk)
        prepared = json.loads(gpu.read_artifact(revision.manifest_artifact, self.tenant.pk, self.project.pk))
        self.assertEqual({s['sample_id'] for s in samples}, set(prepared['split_manifest']['train']))
        self.assertEqual(splits['consumed'], 'train')
        self.assertTrue(all(s['token_ids']==[1,2,3] for s in samples))

    def test_contamination_and_unresolved_split_ids_are_refused(self):
        revision = self.published()
        original = json.loads(gpu.read_artifact(revision.manifest_artifact, self.tenant.pk, self.project.pk))
        for ids in ([original['split_manifest']['train'][0]], [str(uuid.uuid4())]):
            prepared = {**original,'split_manifest':{**original['split_manifest'],'test':ids}}
            raw = json.dumps(prepared).encode()
            revision.manifest_digest = hashlib.sha256(raw).hexdigest()
            with patch.object(gpu, 'read_artifact', return_value=raw):
                with self.assertRaisesRegex(ValueError, 'contamination|do not resolve'):
                    gpu._training_samples(revision, SimpleNamespace(encode=lambda *a,**k:[1,2,3]), self.tenant.pk, self.project.pk)

    def test_continued_pretraining_validation_never_consumes_train_or_test(self):
        revision = self.published()
        prepared = json.loads(gpu.read_artifact(revision.manifest_artifact, self.tenant.pk, self.project.pk))
        identifiers = [r['sample_id'] for r in prepared['rows']]
        prepared['split_manifest'] = {'train': identifiers[:1], 'validation': identifiers[1:2], 'test': identifiers[2:]}
        raw = json.dumps(prepared).encode(); revision.manifest_digest = hashlib.sha256(raw).hexdigest()
        tokenizer = SimpleNamespace(encode=lambda *a, **k: [1, 2, 3])
        with patch.object(gpu, 'read_artifact', return_value=raw):
            samples, summary = gpu._training_samples(revision, tokenizer, self.tenant.pk, self.project.pk, split='validation')
            self.assertEqual([s['sample_id'] for s in samples], identifiers[1:2])
            self.assertEqual(summary['consumed'], 'validation')
            with self.assertRaisesRegex(ValueError, 'never consumes'):
                gpu._training_samples(revision, tokenizer, self.tenant.pk, self.project.pk, split='test')
        prepared['rows'][1]['source_group_id'] = prepared['rows'][0]['source_group_id']
        raw = json.dumps(prepared).encode(); revision.manifest_digest = hashlib.sha256(raw).hexdigest()
        with patch.object(gpu, 'read_artifact', return_value=raw):
            with self.assertRaisesRegex(ValueError, 'source group'):
                gpu._training_samples(revision, tokenizer, self.tenant.pk, self.project.pk)

    def test_encoded_samples_are_never_silently_truncated(self):
        revision = self.published()
        for tokens in ([1], list(range(129))):
            with self.assertRaisesRegex(ValueError, 'never truncated'):
                gpu._training_samples(revision, SimpleNamespace(encode=lambda *a,**k:tokens), self.tenant.pk, self.project.pk)

    def test_absent_validation_is_reported_without_using_training_examples(self):
        revision = self.published()
        prepared = json.loads(gpu.read_artifact(revision.manifest_artifact, self.tenant.pk, self.project.pk))
        prepared['split_manifest'] = {'train': [r['sample_id'] for r in prepared['rows']], 'validation': [], 'test': []}
        raw = json.dumps(prepared).encode(); revision.manifest_digest = hashlib.sha256(raw).hexdigest()
        with patch.object(gpu, 'read_artifact', return_value=raw):
            samples, summary = gpu._training_samples(revision, SimpleNamespace(encode=lambda *a, **k: [1, 2, 3]),
                self.tenant.pk, self.project.pk, split='validation')
        self.assertEqual(samples, [])
        self.assertEqual(summary['consumed'], 'validation')

    def test_malformed_prepared_manifest_is_refused(self):
        revision = self.published();raw=b'[]';revision.manifest_digest=hashlib.sha256(raw).hexdigest()
        with patch.object(gpu, 'read_artifact', return_value=raw):
            with self.assertRaisesRegex(ValueError, 'must be an object'):
                gpu._training_samples(revision, SimpleNamespace(), self.tenant.pk, self.project.pk)


class IndependentGPUSelectionTests(TestCase):
    """Selection failure must happen before the independent consumer loads a model."""
    def setUp(self):
        import importlib.util
        from pathlib import Path
        api = SimpleNamespace(is_available=lambda: True, device_count=lambda: 2,
            get_device_properties=lambda index: SimpleNamespace(total_memory=8 * 1024**3))
        self.torch = SimpleNamespace(device=lambda value: value,
            version=SimpleNamespace(cuda='12.8', hip=None), cuda=api, xpu=api,
            backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
            mps=SimpleNamespace(recommended_max_memory=lambda: 10 * 1024**3,
                driver_allocated_memory=lambda: 0, set_per_process_memory_fraction=lambda fraction: None))
        path = Path(__file__).resolve().parents[3] / 'scripts/hf_candidate_infer.py'
        spec = importlib.util.spec_from_file_location('independent_gpu_consumer_test', path)
        self.consumer = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'torch':self.torch,
            'transformers':SimpleNamespace(AutoTokenizer=None, LlamaForCausalLM=None)}):
            spec.loader.exec_module(self.consumer)

    def test_rocm_keeps_amd_identity_and_uses_cuda_device_namespace(self):
        self.torch.version.hip = '6.4'; self.torch.version.cuda = None
        self.assertEqual(self.consumer.selected_device('rocm:1'), ('cuda:1','rocm'))
        with self.assertRaisesRegex(ValueError, 'CUDA/HIP'):
            self.consumer.selected_device('cuda:0')

    def test_cuda_xpu_and_cpu_are_explicit(self):
        self.assertEqual(self.consumer.selected_device('cuda:1'), ('cuda:1','cuda'))
        self.assertEqual(self.consumer.selected_device('xpu:0'), ('xpu:0','xpu'))
        self.assertEqual(self.consumer.selected_device('cpu'), ('cpu','cpu'))
        for selector in ('auto','cuda:-1','cuda:2','cuda','mps:1','rocm:0'):
            with self.assertRaises(ValueError):
                self.consumer.selected_device(selector)

    def test_unavailable_or_unknown_capacity_never_falls_back(self):
        self.torch.cuda.is_available = lambda: False
        with self.assertRaisesRegex(ValueError, 'refuses CPU fallback'):
            self.consumer.selected_device('cuda:0')
        self.torch.cuda.is_available = lambda: True
        self.torch.cuda.get_device_properties = lambda index: SimpleNamespace(total_memory=None)
        with self.assertRaisesRegex(ValueError, 'memory'):
            self.consumer.selected_device('cuda:0')

    def test_mps_fallback_and_exhausted_process_allowance_are_refused(self):
        with patch.dict('os.environ', {'PYTORCH_ENABLE_MPS_FALLBACK':'1'}):
            with self.assertRaisesRegex(ValueError, 'fallback enabled'):
                self.consumer.selected_device('mps:0')
        self.torch.mps.driver_allocated_memory = lambda: 9 * 1024**3
        with patch.dict('os.environ', {'PYTORCH_ENABLE_MPS_FALLBACK':'0'}):
            with self.assertRaisesRegex(ValueError, 'headroom'):
                self.consumer.selected_device('mps:0')


class RealLoRACheckpointTests(TestCase):
    def test_deterministic_update_policy_restores_on_failure(self):
        import importlib.util
        if importlib.util.find_spec('torch') is None:
            self.skipTest('Optional PyTorch runtime is not installed')
        import torch
        previous = torch.are_deterministic_algorithms_enabled()
        warning = torch.is_deterministic_algorithms_warn_only_enabled()
        with self.assertRaisesRegex(ValueError, 'test failure'):
            with gpu.deterministic_updates():
                self.assertTrue(torch.are_deterministic_algorithms_enabled())
                self.assertFalse(torch.is_deterministic_algorithms_warn_only_enabled())
                raise ValueError('test failure')
        self.assertEqual(torch.are_deterministic_algorithms_enabled(), previous)
        self.assertEqual(torch.is_deterministic_algorithms_warn_only_enabled(), warning)

    def test_adapter_updates_frozen_base_and_optimizer_recovery(self):
        import importlib.util
        if not all(importlib.util.find_spec(n) for n in ['torch', 'peft', 'transformers']):
            self.skipTest('Optional adapter runtime is not installed')
        import torch
        from pathlib import Path
        from safetensors.torch import save_file
        from transformers import LlamaConfig, LlamaForCausalLM
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with torch.random.fork_rng():
                torch.manual_seed(42)
                base = LlamaForCausalLM(LlamaConfig(vocab_size=8, hidden_size=16, intermediate_size=32,
                    num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2))
            base.save_pretrained(temp, safe_serialization=True)
            for name in gpu.FILE_HASHES:
                if not (directory / name).exists():
                    (directory / name).write_text('{}')
            with patch('requests.sessions.Session.request', side_effect=AssertionError('Adapter loader must stay offline')) as network:
                model = gpu._recipe_model(directory, 'lora_adapter', 42, training=True)
                frozen = {n: p.detach().clone() for n, p in model.named_parameters() if not p.requires_grad}
                adapter = {n: p.detach().clone() for n, p in model.named_parameters() if p.requires_grad}
                optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=0.001, foreach=False)
                def update(model, optimizer):
                    optimizer.zero_grad()
                    ids = torch.tensor([[1, 3, 4, 5]])
                    loss = model(input_ids=ids, labels=ids).loss
                    loss.backward(); optimizer.step()
                    self.assertTrue(torch.isfinite(loss).item())
                update(model, optimizer)
                self.assertTrue(any(not torch.equal(adapter[n], p) for n, p in model.named_parameters() if p.requires_grad))
                self.assertTrue(all(torch.equal(frozen[n], p) for n, p in model.named_parameters() if not p.requires_grad))
                model.save_pretrained(temp, safe_serialization=True, save_embedding_layers=False)
                save_file(gpu._optimizer_state(model, optimizer), str(directory / 'optimizer.safetensors'))
                recovered = gpu._recipe_model(directory, 'lora_adapter', 42, training=True)
                restored = torch.optim.AdamW([p for p in recovered.parameters() if p.requires_grad], lr=0.001, foreach=False)
                gpu._restore_optimizer(recovered, restored, directory, 1)
                update(model, optimizer); update(recovered, restored)
                expected = dict(model.named_parameters())
                self.assertTrue(all(torch.equal(p, expected[n]) for n, p in recovered.named_parameters()))
                from safetensors.torch import load_file
                saved = load_file(str(directory / 'adapter_model.safetensors'))
                name = next(iter(saved)); saved[name].fill_(float('nan'))
                save_file(saved, str(directory / 'adapter_model.safetensors'))
                with self.assertRaisesRegex(ValueError, 'non-finite'):
                    gpu._recipe_model(directory, 'lora_adapter', 42, training=True)
                network.assert_not_called()
