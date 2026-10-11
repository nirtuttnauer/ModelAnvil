"""Real tests for the general transformer runtime, autodiff and scope report."""
import math

from django.test import SimpleTestCase

from modelanvil.runners.training.autograd import Value, mean, softmax
from modelanvil.runners.training.engine import pack_safetensors, unpack_safetensors
from modelanvil.runners.training.general_transformer import (
    AdamW,
    ByteTokenizer,
    GENERAL_RUNTIME_ID,
    GeneralTransformer,
    format_chat_messages,
    prune_context,
    runtime_manifest,
)
from modelanvil.runners.training.scope import STATUS_AVAILABLE, STATUS_UNAVAILABLE, runtime_scope_report


class AutodiffTests(SimpleTestCase):
    def test_gradients_match_finite_difference(self):
        value = Value(2.0)
        weight = Value(-1.5)

        def expression(a, b):
            return math.tanh(a * b) + a * a - b

        out = (value * weight).tanh() + value ** 2 - weight
        out.backward()
        eps = 1e-6
        numeric_dv = (expression(value.data + eps, weight.data) - expression(value.data - eps, weight.data)) / (2 * eps)
        numeric_dw = (expression(value.data, weight.data + eps) - expression(value.data, weight.data - eps)) / (2 * eps)
        self.assertAlmostEqual(value.grad, numeric_dv, delta=1e-4)
        self.assertAlmostEqual(weight.grad, numeric_dw, delta=1e-4)

    def test_softmax_is_normalized_and_differentiable(self):
        values = [Value(v) for v in (0.7, 0.2, -0.4)]
        probs = softmax(values)
        total = mean(probs)
        total.backward()
        self.assertAlmostEqual(sum(p.data for p in probs), 1.0, places=6)
        for value in values:
            self.assertGreater(value.grad, 0)


class ChatTemplateTests(SimpleTestCase):
    def test_formats_messages(self):
        rendered = format_chat_messages([
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Count to three."},
            {"role": "assistant", "content": "1, 2, 3"},
        ])
        self.assertIn("<|system|>\nBe terse.\n", rendered)
        self.assertIn("<|user|>\nCount to three.\n", rendered)
        self.assertIn("<|assistant|>\n1, 2, 3\n", rendered)

    def test_rejects_empty_messages(self):
        with self.assertRaises(ValueError):
            format_chat_messages([])


class ByteTokenizerTests(SimpleTestCase):
    def test_roundtrip_and_specials(self):
        tokenizer = ByteTokenizer()
        ids = tokenizer.encode("héllo ✓")
        self.assertEqual(ids[0], tokenizer.special_tokens["bos_token"])
        self.assertEqual(ids[-1], tokenizer.special_tokens["eos_token"])
        self.assertEqual(tokenizer.decode(ids), "héllo ✓")
        self.assertEqual(tokenizer.vocabulary_size, 260)
        for key in ("pad_token", "bos_token", "eos_token", "unk_token"):
            self.assertIn(key, tokenizer.special_tokens)


class GeneralTransformerTests(SimpleTestCase):
    def _model(self, **kwargs):
        options = {"vocab_size": 16, "n_layer": 1, "n_head": 2, "n_embd": 4, "context_window": 16, "seed": 7}
        options.update(kwargs)
        return GeneralTransformer(**options)

    def test_attention_is_causal(self):
        model = self._model(vocab_size=32, seed=1)
        first = [1, 2, 3, 4, 5]
        second = [1, 2, 3, 9, 8]
        logits_first = model.forward_logits(first)
        logits_second = model.forward_logits(second)
        for position in range(2):
            for vocab in range(32):
                self.assertEqual(logits_first[position][vocab].data, logits_second[position][vocab].data)

    def test_training_reduces_loss_with_adamw(self):
        model = self._model()
        tokens = [2, 3, 1, 5, 3, 1, 5, 3]
        optimizer = AdamW(model.parameters(), learning_rate=0.08, weight_decay=1e-4)
        before = model.loss(tokens).data
        for _ in range(20):
            model.zero_grad()
            loss = model.loss(tokens)
            loss.backward()
            optimizer.step()
        after = model.loss(tokens).data
        self.assertLess(after, before)

    def test_forward_rejects_oversized_context(self):
        model = self._model(context_window=6)
        with self.assertRaises(ValueError):
            model.forward_logits(list(range(7)))

    def test_safetensors_checkpoint_roundtrip(self):
        model = self._model()
        raw, manifest = pack_safetensors(model.export_tensors())
        tensors = unpack_safetensors(raw)
        restored = self._model()
        restored.import_tensors(tensors)
        for name, (shape, flat) in model.export_tensors().items():
            self.assertEqual(restored.export_tensors()[name][0], shape)
            for original, recovered in zip(flat, restored.export_tensors()[name][1]):
                self.assertAlmostEqual(original, recovered, places=5)

    def test_import_rejects_missing_tensor(self):
        model = self._model()
        exported = model.export_tensors()
        exported.pop("lm_head.weight")
        restored = self._model()
        with self.assertRaises(ValueError):
            restored.import_tensors(exported)

    def test_adamw_applies_weight_decay(self):
        param = Value(1.0)
        optimizer = AdamW([param], learning_rate=0.1, weight_decay=0.5)
        optimizer.step()
        self.assertAlmostEqual(param.data, 0.95, places=6)

    def test_prune_context_right_aligns(self):
        self.assertEqual(prune_context([1, 2, 3, 4], 3), [2, 3, 4])
        with self.assertRaises(ValueError):
            prune_context([1], 8)

    def test_runtime_manifest_is_honest(self):
        manifest = runtime_manifest()
        self.assertEqual(manifest["adapter_id"], GENERAL_RUNTIME_ID)
        self.assertEqual(manifest["resources"]["gpu_count"], 0)
        self.assertFalse(manifest["resources"]["distributed"])


class RuntimeScopeTests(SimpleTestCase):
    def test_default_report_marks_only_local_cpu_available(self):
        report = runtime_scope_report(gpu_count=0, provider_configured=False)
        by_id = {item["target_id"]: item for item in report["targets"]}
        self.assertEqual(by_id[GENERAL_RUNTIME_ID]["status"], STATUS_AVAILABLE)
        for target_id in ("modelanvil.gpu-sft.v1", "modelanvil.distributed-sft.v1", "modelanvil.remote-production.v1"):
            self.assertEqual(by_id[target_id]["status"], STATUS_UNAVAILABLE)
            self.assertTrue(by_id[target_id]["reason"])
            self.assertTrue(by_id[target_id]["corrective_action"])
        self.assertIn(GENERAL_RUNTIME_ID, report["available"])
        self.assertNotIn("modelanvil.gpu-sft.v1", report["available"])

    def test_provisioned_infrastructure_flips_status(self):
        report = runtime_scope_report(gpu_count=2, provider_configured=True)
        by_id = {item["target_id"]: item for item in report["targets"]}
        self.assertEqual(by_id["modelanvil.gpu-sft.v1"]["status"], STATUS_AVAILABLE)
        self.assertEqual(by_id["modelanvil.remote-production.v1"]["status"], STATUS_AVAILABLE)
        self.assertEqual(by_id["modelanvil.distributed-sft.v1"]["status"], STATUS_UNAVAILABLE)