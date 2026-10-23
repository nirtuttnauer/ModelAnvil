"""Small numerical objective tests; these do not qualify GPU hardware or model quality."""
import copy
import importlib.util
import math
from types import SimpleNamespace
from unittest import skipUnless

from django.test import SimpleTestCase

from .torch_dpo import encode_pair, preference_loss, response_log_probability
from .preference_groups import source_group


class TokenBoundaryTests(SimpleTestCase):
    def test_group_aliases_normalize_and_conflicts_cannot_hide_overlap(self):
        self.assertEqual(source_group({'metadata': {'source_group_id': ' group '}}), 'group')
        self.assertEqual(source_group({'source_group_id': 'group'}), 'group')
        for row in ({'source_group_id': 'one', 'metadata': {'source_group_id': 'two'}},
                    {'source_group_id': None}, {}):
            with self.assertRaises(ValueError): source_group(row, required=True)

    def test_prefix_alignment_eos_and_truncation_are_explicit(self):
        tokenizer = SimpleNamespace(chat_template='', all_special_tokens=['<eos>'], eos_token_id=2,
            encode=lambda text, **_: [ord(char) for char in text])
        pair = {'prompt': 'A:', 'chosen': ' yes', 'rejected': ' no'}
        result = encode_pair(tokenizer, pair)
        self.assertEqual(result['prompt_tokens'], 2)
        self.assertEqual(result['chosen'][-1], 2)
        for changes in ({'chosen': '<eos>'}, {'chosen': 'x' * 128}):
            with self.assertRaises(ValueError): encode_pair(tokenizer, {**pair, **changes})
        tokenizer.encode = lambda text, **_: [1, 2] if text == 'A:' else [9, 3, 4]
        with self.assertRaisesRegex(ValueError, 'boundaries'): encode_pair(tokenizer, pair)


@skipUnless(importlib.util.find_spec('torch'), 'Optional PyTorch runtime is not installed')
class NumericalDPOTests(SimpleTestCase):
    def test_actual_update_uses_response_mask_and_keeps_reference_frozen(self):
        import torch
        class Bigram(torch.nn.Module):
            def __init__(self):
                super().__init__(); self.weights = torch.nn.Embedding(8, 8)
                torch.nn.init.zeros_(self.weights.weight)
            def forward(self, input_ids, **kwargs):
                return SimpleNamespace(logits=self.weights(input_ids))
        policy = Bigram(); reference = copy.deepcopy(policy).requires_grad_(False)
        before = reference.weights.weight.detach().clone()
        chosen, rejected = [1, 3, 4, 2], [1, 3, 5, 2]
        logp = lambda model, ids: response_log_probability(model, ids, 2, 'cpu')
        ref_chosen, ref_rejected = logp(reference, chosen), logp(reference, rejected)
        optimizer = torch.optim.SGD(policy.parameters(), lr=.1)
        loss = preference_loss(logp(policy, chosen), logp(policy, rejected), ref_chosen, ref_rejected, .1)
        self.assertAlmostEqual(loss.item(), math.log(2), places=6)
        self.assertAlmostEqual(ref_chosen.item(), -2 * math.log(8), places=6)
        loss.backward(); optimizer.step()
        after = preference_loss(logp(policy, chosen), logp(policy, rejected), ref_chosen, ref_rejected, .1)
        self.assertLess(after.item(), loss.item())
        self.assertTrue(torch.equal(reference.weights.weight, before))
        self.assertIsNone(reference.weights.weight.grad)
        self.assertTrue(torch.equal(policy.weights.weight[1], before[1]), 'Prompt-only transition must be masked')
        self.assertFalse(torch.equal(policy.weights.weight, before))
        root = __import__('pathlib').Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location('independent_dpo_test', root / 'scripts/score_dpo_candidate.py')
        consumer = importlib.util.module_from_spec(spec); spec.loader.exec_module(consumer)
        with torch.inference_mode():
            self.assertAlmostEqual(consumer.response_score(reference, {'chosen': chosen, 'prompt_tokens': 2}, 'chosen'),
                ref_chosen.item(), places=6)
