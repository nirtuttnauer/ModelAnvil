"""Native quantized-adapter boundaries; real model checks require an explicit local fixture."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import uuid
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase, tag

from modelanvil.runners.training import hf_runtime, mlx_profile as profiles, mlx_runtime as runtime, registry
from scripts.mlx_candidate_infer import load_candidate, QUANTIZATION


class NativeAdapterBoundaryTests(SimpleTestCase):
    def test_only_native_backend_and_exact_contract_authorize_worker(self):
        caps = {'training_runtime': runtime.CONTRACT_DIGEST, 'memory_bytes': 8 * 1024**3,
            'gpu_backend': 'mlx', 'gpu_device': 'mlx:0', 'gpu_packages': runtime.PACKAGES}
        worker = SimpleNamespace(capabilities=caps, slots=1)
        self.assertTrue(runtime.capable_worker(worker))
        for key, value in [('gpu_backend', 'mps'), ('gpu_device', 'cpu'), ('training_runtime', 'other'),
            ('memory_bytes', None), ('gpu_packages', {})]:
            worker.capabilities = {**caps, key: value}
            self.assertFalse(runtime.capable_worker(worker))
        for options in ({'precision': 'bf16'}, {'adapter': 'lora'}, {'quantization': 'int8'}, {'recipe_type': 'full_sft'}):
            with self.assertRaises(ValueError):
                runtime.validate_options(**options)
        runtime.validate_options(adapter='qlora', quantization='int4')
        with self.assertRaisesRegex(ValueError, 'FP8'):
            runtime.validate_options(precision='fp8')


class OptimizationProfileTests(SimpleTestCase):
    def test_default_profile_is_the_original_recipe_and_supported_combinations_validate(self):
        self.assertEqual(profiles.validate_profile(), profiles.DEFAULT_PROFILE)
        self.assertEqual(profiles.ADAMW, hf_runtime.OPTIMIZER)
        self.assertEqual(runtime.validate_hyperparameters(None), profiles.DEFAULT_PROFILE)
        self.assertEqual(runtime.validate_hyperparameters({}), profiles.DEFAULT_PROFILE)
        chosen = {'compute_precision': 'bf16', 'gradient_checkpointing': True, 'batch_samples': 8,
            'sequence_layout': 'packed', 'attention_kernel': 'mlx_fast_sdpa_force_fused', 'optimizer': 'adafactor'}
        self.assertEqual(runtime.validate_hyperparameters({'optimization': chosen}), chosen)
        self.assertEqual(profiles.validate_profile({'batch_samples': 4})['sequence_layout'], 'padded')
        self.assertEqual(runtime.CONTRACT['optimization_profile'], profiles.CONTRACT)

    def test_published_contract_describes_the_validated_profile_and_missing_metrics(self):
        from jsonschema import Draft202012Validator
        from contracts.schemas import load_schema
        schemas = load_schema('openapi')['components']['schemas']
        published = schemas['MlxOptimizationProfile']
        self.assertEqual({k: v['default'] for k, v in published['properties'].items()}, profiles.DEFAULT_PROFILE)
        validator = Draft202012Validator(published)
        for value in (profiles.validate_profile(), profiles.validate_profile({'compute_precision': 'bf16', 'batch_samples': 8,
                'sequence_layout': 'packed', 'gradient_checkpointing': True, 'optimizer': 'adafactor', 'attention_kernel': 'mlx_fast_sdpa_force_fused'})):
            self.assertEqual(list(validator.iter_errors(value)), [])
        for value in ({'compute_precision': 'fp16'}, {'compute_precision': 'fp8'}, {'batch_samples': 9}, {'optimizer': 'adamw_8bit'}, {'learning_rate': 1}):
            self.assertTrue(list(validator.iter_errors(value)), value)
            with self.assertRaises(ValueError):
                profiles.validate_profile(value)
        metric = {'step': 1, 'loss': 2.0, 'measured_at': '2026-11-15T16:40:12.000000+00:00', 'peak_reserved_bytes': None,
            'gpu_utilization_percent': None, 'peak_allocated_bytes': 1024, 'unavailable_metrics': profiles.UNAVAILABLE_METRICS}
        self.assertEqual(list(Draft202012Validator(schemas['TrainingStepMetric']).iter_errors(metric)), [])
        self.assertEqual(set(profiles.UNAVAILABLE_METRICS.values()), set(profiles.UNAVAILABLE_REASONS))

    def test_unsupported_and_incompatible_profiles_name_the_refused_setting(self):
        cases = [({'compute_precision': value}, 'FP8') for value in ('fp8', 'FP8_E4M3', 'fp8-e5m2', 'float8_e4m3fn', 'e4m3')]
        cases += [({'compute_precision': 'fp16'}, 'loss scaling'), ({'compute_precision': 'float16'}, 'loss scaling'),
            ({'compute_precision': 'int8'}, 'fp32 or bf16'), ({'compute_precision': None}, 'fp32 or bf16'),
            ({'sequence_layout': 'packed'}, 'Packing needs batch_samples of at least 2'),
            ({'sequence_layout': 'packed', 'batch_samples': 1}, 'Packing needs'),
            ({'sequence_layout': 'truncated', 'batch_samples': 2}, 'never truncated'),
            ({'batch_samples': 0}, 'batch_samples'), ({'batch_samples': 9}, 'batch_samples'),
            ({'batch_samples': True}, 'batch_samples'), ({'batch_samples': '8'}, 'batch_samples'),
            ({'gradient_checkpointing': 1}, 'true or false'),
            ({'attention_kernel': 'flash_attention_2'}, 'FlashAttention'), ({'attention_kernel': 'eager'}, 'FlashAttention'),
            ({'optimizer': 'adamw_8bit'}, 'bitsandbytes'), ({'optimizer': 'paged_adamw'}, 'bitsandbytes'),
            ({'learning_rate': 0.1}, 'Unsupported optimization settings: learning_rate'), ([], 'object')]
        for value, message in cases:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, message):
                profiles.validate_profile(value)
        for hyperparameters in ({'learning_rate': 0.1}, {'optimization': {}, 'validation_interval': 1}, [{'optimization': {}}]):
            with self.subTest(hyperparameters=hyperparameters), self.assertRaisesRegex(ValueError, 'accepts only hyperparameters.optimization'):
                runtime.validate_hyperparameters(hyperparameters)

    def test_refused_profile_fails_before_any_input_or_device_work_and_valid_profile_is_pinned(self):
        with patch.object(runtime.hf, 'resolve_inputs') as resolved:
            for profile in ({'compute_precision': 'fp8'}, {'sequence_layout': 'packed'}, {'optimizer': 'adamw_8bit'}):
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    runtime.resolve_inputs(hyperparameters={'optimization': profile}, dataset=None, base=None, tokenizer=None,
                        runner=None, pool=None, tenant=None, project=None, steps=1)
            resolved.assert_not_called()
            resolved.return_value = {'pins': {'optimizer': runtime.OPTIMIZER}, 'samples': [{'token_ids': [1, 2]}]}
            inputs = runtime.resolve_inputs(hyperparameters={'optimization': {'optimizer': 'adafactor', 'batch_samples': 2}},
                dataset=None, base=None, tokenizer=None, runner=None, pool=None, tenant=None, project=None, steps=1)
        self.assertEqual(inputs['pins']['optimizer'], profiles.ADAFACTOR)
        self.assertEqual(inputs['pins']['optimization'], {**profiles.DEFAULT_PROFILE, 'optimizer': 'adafactor', 'batch_samples': 2})
        self.assertNotIn('hyperparameters', resolved.call_args.kwargs)

    def test_registry_forwards_hyperparameters_only_to_the_native_profile(self):
        with patch.object(runtime, 'resolve_inputs', return_value='resolved') as native:
            self.assertEqual(registry.resolve_inputs(base=SimpleNamespace(architecture_ref=runtime.RUNTIME_ID),
                hyperparameters={'optimization': {'batch_samples': 2}}), 'resolved')
        self.assertEqual(native.call_args.kwargs['hyperparameters'], {'optimization': {'batch_samples': 2}})
        with self.assertRaisesRegex(ValueError, 'does not expose custom'):
            registry.resolve_inputs(base=SimpleNamespace(architecture_ref=hf_runtime.RUNTIME_ID), hyperparameters={'optimization': {}})

    def test_checkpoint_resume_refuses_a_changed_profile_or_optimizer(self):
        default = {'optimization': profiles.DEFAULT_PROFILE, 'optimizer': profiles.ADAMW, 'config': {}}
        changed = {**default, 'optimization': {**profiles.DEFAULT_PROFILE, 'gradient_checkpointing': True}}
        run = SimpleNamespace(run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), project_id=uuid.uuid4(), hardware_config={'pins': changed})
        def checkpoint(pins, optimizer):
            state = {'pins': pins, 'step': 1, 'run_id': str(run.run_id), 'optimizer': {**optimizer, 'updates': 1}, 'metrics': {}}
            return SimpleNamespace(is_valid=True, weights_manifest=state, state_digest=runtime.digest(state), step=1, metrics={})
        with patch.object(runtime, 'staged_files') as staged:
            with self.assertRaisesRegex(ValueError, 'different optimization profile'):
                runtime.checkpoint_bundle(run, checkpoint(default, profiles.ADAMW))
            adafactor = {**default, 'optimization': {**profiles.DEFAULT_PROFILE, 'optimizer': 'adafactor'}, 'optimizer': profiles.ADAFACTOR}
            run.hardware_config = {'pins': adafactor}
            with self.assertRaisesRegex(ValueError, 'pinned optimizer'):
                runtime.checkpoint_bundle(run, checkpoint(adafactor, profiles.ADAMW))
            staged.assert_not_called()


class OptimizationPreflightTests(TestCase):
    def test_incompatible_profile_blocks_preflight_before_inputs_resolve(self):
        from modelanvil.identity.models import Tenant
        from modelanvil.jobs.models import WorkerPool
        from modelanvil.core.tenancy import set_active_tenant
        from modelanvil.runners.training import preflight_report
        tenant = Tenant.objects.create(slug='mlx-profile', name='MLX profile')
        set_active_tenant(tenant.pk); self.addCleanup(set_active_tenant, None)
        pool = WorkerPool.objects.create(tenant_id=tenant.pk, name='metal', queue_name='metal', status='active')
        manifest = runtime.runner_manifest()
        runner = SimpleNamespace(enabled=True, manifest=manifest, digest=runtime.digest(manifest), compatibility={'contract_digest': runtime.CONTRACT_DIGEST})
        resources = dict(recipe_type='qlora_adapter', tokenizer_version=SimpleNamespace(pk=7), dataset_revision=SimpleNamespace(state='published'),
            base_model_version=SimpleNamespace(architecture_ref=runtime.RUNTIME_ID, tokenizer_id=7), pool=pool, runner=runner,
            total_steps=3, tenant=tenant.pk, project=None)
        with patch.object(preflight_report, 'resolve_inputs', side_effect=ValueError('inputs reached')) as resolved:
            for profile, message in (({'compute_precision': 'fp8'}, 'FP8'), ({'sequence_layout': 'packed'}, 'Packing'),
                    ({'compute_precision': 'fp16', 'gradient_checkpointing': True}, 'loss scaling')):
                report = preflight_report.build_preflight_report(**resources, hyperparameters={'optimization': profile})
                failed = next(c for c in report['checks'] if c['check'] == 'optimization-profile')
                self.assertEqual(report['status'], 'blocked')
                self.assertEqual(failed['status'], 'fail'); self.assertIn(message, failed['reason']); self.assertTrue(failed['corrective_action'])
                self.assertIsNone(report['pins'])
            resolved.assert_not_called()
            report = preflight_report.build_preflight_report(**resources, hyperparameters={'optimization': {'compute_precision': 'bf16'}})
        passed = next(c for c in report['checks'] if c['check'] == 'optimization-profile')
        self.assertEqual(passed['status'], 'pass'); self.assertEqual(passed['detail']['compute_precision'], 'bf16')
        self.assertEqual(resolved.call_args.kwargs['hyperparameters'], {'optimization': {'compute_precision': 'bf16'}})


# Collected only with the verified local model, then tagged pg so that host
# runs it in the PostgreSQL suite. A missing fixture is not a runtime skip.
_MLX_FIXTURE = os.environ.get('MODELANVIL_MLX_TEST_MODEL_DIR')


@tag('pg')
class NativeAdapterModelTests(SimpleTestCase if _MLX_FIXTURE else object):
    def test_frozen_four_bit_base_actual_update_exact_resume_and_corruption(self):
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten
        self.assertTrue(mx.metal.is_available())
        mx.set_default_device(mx.gpu)
        model, tokenizer, config, adapter_config = load_candidate(os.environ['MODELANVIL_MLX_TEST_MODEL_DIR'], training=True)
        self.assertIsInstance(model.layers[0].self_attn.q_proj.linear, nn.QuantizedLinear)
        self.assertEqual(model.layers[0].self_attn.q_proj.linear.bits, 4)
        self.assertNotIsInstance(model.model.embed_tokens, nn.QuantizedEmbedding)
        before = {n: mx.array(p) for n, p in tree_flatten(model.parameters()) if not n.endswith(('.lora_a', '.lora_b'))}
        trainable = dict(tree_flatten(model.trainable_parameters()))
        self.assertEqual(sum(p.size for p in trainable.values()), 460800)
        optimizer = optim.AdamW(learning_rate=1e-5, weight_decay=0.)
        ids = mx.array([tokenizer.encode('A small verified text sample for adapter training.')])
        def update(model, optimizer):
            value_grad = nn.value_and_grad(model, lambda m, x: nn.losses.cross_entropy(m(x[:, :-1]), x[:, 1:], reduction='mean'))
            loss, gradients = value_grad(model, ids)
            self.assertTrue(mx.isfinite(loss).item())
            optimizer.update(model, gradients)
            mx.eval(model.parameters(), optimizer.state)
        update(model, optimizer)
        after = dict(tree_flatten(model.parameters()))
        self.assertTrue(all(mx.array_equal(p, after[n]).item() for n, p in before.items()))
        self.assertTrue(any(mx.any(p != 0).item() for n, p in tree_flatten(model.trainable_parameters()) if n.endswith('.lora_b')))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in runtime.FILE_HASHES:
                if not name.endswith('.safetensors') and name != 'config.json':
                    shutil.copyfile(Path(os.environ['MODELANVIL_MLX_TEST_MODEL_DIR']) / name, directory / name)
            base = {n.replace('.linear.', '.'): p for n, p in before.items()}
            mx.save_safetensors(str(directory / 'model.safetensors'), base)
            (directory / 'config.json').write_text(json.dumps(config))
            (directory / 'adapter_config.json').write_text(json.dumps(adapter_config))
            mx.save_safetensors(str(directory / 'adapters.safetensors'), dict(tree_flatten(model.trainable_parameters())))
            mx.save_safetensors(str(directory / 'optimizer.safetensors'), dict(tree_flatten(optimizer.state)))
            recovered, _, saved_config, _ = load_candidate(directory, training=True)
            self.assertEqual(saved_config['quantization'], QUANTIZATION)
            other = optim.AdamW(learning_rate=1e-5, weight_decay=0.)
            runtime.restore_optimizer(other, recovered, directory, 1)
            update(model, optimizer); update(recovered, other)
            expected = dict(tree_flatten(model.trainable_parameters()))
            self.assertTrue(all(mx.array_equal(p, expected[n]).item() for n, p in tree_flatten(recovered.trainable_parameters())))
            saved = mx.load(str(directory / 'adapters.safetensors'))
            name = next(iter(saved)); saved[name] = mx.full(saved[name].shape, float('nan'))
            mx.save_safetensors(str(directory / 'adapters.safetensors'), saved)
            with self.assertRaisesRegex(ValueError, 'non-finite'):
                load_candidate(directory)
            saved[name] = mx.zeros(saved[name].shape); saved['unexpected'] = mx.array([1.])
            mx.save_safetensors(str(directory / 'adapters.safetensors'), saved)
            with self.assertRaisesRegex(ValueError, 'keys'):
                load_candidate(directory)
            moments = mx.load(str(directory / 'optimizer.safetensors')); moments['step'] = mx.array(2, dtype=moments['step'].dtype)
            mx.save_safetensors(str(directory / 'optimizer.safetensors'), moments)
            with self.assertRaisesRegex(ValueError, 'cursor'):
                runtime.restore_optimizer(other, recovered, directory, 1)
        mx.clear_cache()

    def _model(self):
        import mlx.core as mx
        self.assertTrue(mx.metal.is_available())
        mx.set_default_device(mx.gpu)
        model, tokenizer, _, _ = load_candidate(os.environ['MODELANVIL_MLX_TEST_MODEL_DIR'], training=True)
        texts = ['A telescope collects light from distant stars.',
            'Ocean tides follow gravitational forces from the moon and the sun, twice every single day.', 'Bread rises.']
        samples = [{'sample_id': f's{i}', 'token_ids': tokenizer.encode(text)} for i, text in enumerate(texts)]
        self.assertEqual(len({len(s['token_ids']) for s in samples}), 3)
        return model, samples

    @staticmethod
    def _gradients(model, batch, profile):
        import mlx.core as mx
        from mlx.utils import tree_flatten
        loss, gradients = profiles.value_and_grad(model, batch, profile)
        mx.eval(loss, gradients)
        return loss.item(), dict(tree_flatten(gradients))

    @staticmethod
    def _relative(actual, expected):
        import mlx.core as mx
        difference = sum(mx.sum((actual[n] - expected[n]) ** 2).item() for n in expected)
        return (difference / sum(mx.sum(g ** 2).item() for g in expected.values())) ** 0.5

    def test_padding_and_packing_preserve_sample_boundaries_and_supervision(self):
        import mlx.core as mx
        model, samples = self._model()
        single, batched = profiles.DEFAULT_PROFILE, {**profiles.DEFAULT_PROFILE, 'batch_samples': 3}
        packed_profile = {**batched, 'sequence_layout': 'packed'}
        ids = mx.array([samples[1]['token_ids'][:-1]])
        self.assertTrue(mx.array_equal(model(ids), profiles.forward(model, ids, 'causal', single)).item())
        alone = [profiles.batch_loss(model, profiles.build_batch([s], 'padded'), single, reduction='none')[0] for s in samples]
        padded_batch, packed_batch = profiles.build_batch(samples, 'padded'), profiles.build_batch(samples, 'packed')
        padded = profiles.batch_loss(model, padded_batch, batched, reduction='none')
        packed = profiles.batch_loss(model, packed_batch, packed_profile, reduction='none')[0]
        pairs = sum(len(s['token_ids']) - 1 for s in samples)
        self.assertEqual((padded_batch['pairs'], packed_batch['pairs']), (pairs, pairs))
        self.assertEqual((mx.sum(padded_batch['weights']).item(), mx.sum(packed_batch['weights']).item()), (pairs, pairs))
        self.assertEqual(packed_batch['padding_positions'], 0); self.assertGreater(padded_batch['padding_positions'], 0)
        # FP32 MLX kernels change with batch shape: the same sample repeated three times in one batch already
        # differs from its single-row loss by about 3e-3 per token here. Different shapes are compared within
        # that noise floor; sample isolation is asserted exactly below, where shapes are held fixed.
        noise, mean_noise = 2e-2, 1e-3
        replicated = profiles.batch_loss(model, profiles.build_batch([samples[1]] * 3, 'padded'), batched, reduction='none')
        self.assertLess(mx.max(mx.abs(replicated[0] - alone[1])).item(), noise)
        offset = 0
        for index, sample in enumerate(samples):
            count = len(sample['token_ids']) - 1
            expected = mx.sum(alone[index]).item()
            self.assertLess(mx.max(mx.abs(padded[index, :count] - alone[index])).item(), noise)
            self.assertLess(abs(mx.sum(padded[index, :count]).item() - expected) / expected, mean_noise)
            self.assertEqual(mx.sum(mx.abs(padded[index, count:])).item(), 0)
            self.assertLess(mx.max(mx.abs(packed[offset:offset + count] - alone[index])).item(), noise)
            self.assertLess(abs(mx.sum(packed[offset:offset + count]).item() - expected) / expected, mean_noise)
            if index < len(samples) - 1:
                self.assertEqual(packed_batch['weights'][0, offset + count].item(), 0)
                self.assertEqual(packed[offset + count].item(), 0)
            offset += count + 1
        # Exact isolation: different padding tokens change no supervised prediction.
        repadded = {**padded_batch, 'inputs': mx.where(padded_batch['weights'] == 0, 1234, padded_batch['inputs'])}
        self.assertFalse(mx.array_equal(repadded['inputs'], padded_batch['inputs']).item())
        changed = profiles.batch_loss(model, repadded, batched, reduction='none')
        self.assertEqual(mx.max(mx.abs(changed - padded)).item(), 0)
        # Exact isolation: changing the first packed sample changes only its own predictions.
        other = [{**samples[0], 'token_ids': [t + 1 for t in samples[0]['token_ids']]}, *samples[1:]]
        changed = profiles.batch_loss(model, profiles.build_batch(other, 'packed'), packed_profile, reduction='none')[0]
        first = len(samples[0]['token_ids'])
        self.assertGreater(mx.max(mx.abs(changed[:first - 1] - packed[:first - 1])).item(), 0)
        self.assertEqual(mx.max(mx.abs(changed[first:] - packed[first:])).item(), 0)
        padded_loss, padded_grads = self._gradients(model, padded_batch, batched)
        packed_loss, packed_grads = self._gradients(model, packed_batch, packed_profile)
        self.assertLess(abs(packed_loss - padded_loss) / padded_loss, 1e-3)
        self.assertLess(self._relative(packed_grads, padded_grads), 1e-2)
        mx.clear_cache()

    def test_checkpointing_and_fused_attention_reproduce_gradients(self):
        import mlx.core as mx
        model, samples = self._model()
        for layout in ('padded', 'packed'):
            profile = {**profiles.DEFAULT_PROFILE, 'batch_samples': 3, 'sequence_layout': layout}
            batch = profiles.build_batch(samples, layout)
            loss, gradients = self._gradients(model, batch, profile)
            # Recomputing blocks repeats the same kernels, so checkpointing is exact.
            other_loss, other = self._gradients(model, batch, {**profile, 'gradient_checkpointing': True})
            self.assertEqual(other_loss, loss); self.assertLess(self._relative(other, gradients), 1e-6)
            # Forcing the fused kernel changes the accumulation order only (about 3e-5 loss, 2e-3 gradient here).
            for change in ({'attention_kernel': 'mlx_fast_sdpa_force_fused'},
                    {'gradient_checkpointing': True, 'attention_kernel': 'mlx_fast_sdpa_force_fused'}):
                with self.subTest(layout=layout, change=change):
                    other_loss, other = self._gradients(model, batch, {**profile, **change})
                    self.assertLess(abs(other_loss - loss) / loss, 1e-3)
                    self.assertLess(self._relative(other, gradients), 1e-2)
        mx.clear_cache()

    def test_bf16_compute_keeps_fp32_adapters_and_close_gradients(self):
        import mlx.core as mx
        from mlx.utils import tree_flatten
        model, samples = self._model()
        profile = {**profiles.DEFAULT_PROFILE, 'batch_samples': 3}
        batch = profiles.build_batch(samples, 'padded')
        loss, gradients = self._gradients(model, batch, profile)
        bf16 = {**profile, 'compute_precision': 'bf16'}
        profiles.prepare_model(model, bf16)
        self.assertTrue(all(p.dtype == mx.float32 for _, p in tree_flatten(model.trainable_parameters())))
        linear = model.model.layers[0].self_attn.q_proj.linear
        self.assertEqual((linear.scales.dtype, linear.biases.dtype, linear.weight.dtype), (mx.bfloat16, mx.bfloat16, mx.uint32))
        self.assertEqual((model.model.embed_tokens.weight.dtype, model.model.norm.weight.dtype,
            model.model.layers[0].input_layernorm.weight.dtype), (mx.float32, mx.float32, mx.float32))
        self.assertEqual(profiles.forward(model, batch['inputs'], batch['mask'], bf16).dtype, mx.float32)
        other_loss, other = self._gradients(model, batch, bf16)
        self.assertTrue(all(g.dtype == mx.float32 for g in other.values()))
        # Measured on this fixture: 3e-4 relative loss and 0.980 gradient cosine (an all-BF16 residual stream
        # gave 1.7% and 0.937). The benchmark's held-out tolerance is the quality gate; these guard regressions.
        self.assertLess(abs(other_loss - loss) / loss, 1e-3)
        dot = sum(mx.sum(other[n] * gradients[n]).item() for n in gradients)
        norms = (sum(mx.sum(g ** 2).item() for g in other.values()) * sum(mx.sum(g ** 2).item() for g in gradients.values())) ** 0.5
        self.assertGreater(dot / norms, 0.97)
        mx.clear_cache()

    def test_adafactor_factored_state_updates_and_restores_exactly(self):
        import mlx.core as mx
        from mlx.utils import tree_flatten
        model, samples = self._model()
        profile = {**profiles.DEFAULT_PROFILE, 'batch_samples': 3, 'optimizer': 'adafactor'}
        batch = profiles.build_batch(samples, 'padded')
        optimizer = profiles.make_optimizer('adafactor')
        loss, norm = profiles.train_step(model, optimizer, batch, profile)
        self.assertGreater(norm, 0)
        state = dict(tree_flatten(optimizer.state))
        self.assertTrue(any(n.endswith('exp_avg_sq_row') for n in state)); self.assertFalse(any(n.endswith('.exp_avg') for n in state))
        adam = profiles.make_optimizer('adamw'); adam.init(model.trainable_parameters())
        self.assertLess(profiles.state_bytes(optimizer.state) * 10, profiles.state_bytes(adam.state))
        self.assertTrue(any(mx.any(p != 0).item() for n, p in tree_flatten(model.trainable_parameters()) if n.endswith('.lora_b')))
        with tempfile.TemporaryDirectory() as tmp:
            mx.save_safetensors(str(Path(tmp) / 'optimizer.safetensors'), state)
            restored = profiles.make_optimizer('adafactor')
            runtime.restore_optimizer(restored, model, Path(tmp), 1)
            self.assertTrue(all(mx.array_equal(v, state[n]).item() for n, v in tree_flatten(restored.state)))
            with self.assertRaisesRegex(ValueError, 'keys'):
                runtime.restore_optimizer(profiles.make_optimizer('adamw'), model, Path(tmp), 1)
        mx.clear_cache()
