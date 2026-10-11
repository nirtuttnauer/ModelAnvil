"""Native quantized-adapter boundaries; real model checks require an explicit local fixture."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
from unittest import skipUnless

from django.test import SimpleTestCase

from modelanvil.runners.training import mlx_runtime as runtime
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


@skipUnless(os.environ.get('MODELANVIL_MLX_TEST_MODEL_DIR'), 'Requires explicit verified local model and Metal access')
class NativeAdapterModelTests(SimpleTestCase):
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
