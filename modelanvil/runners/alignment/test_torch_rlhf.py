"""Numerical invariants; these small models do not qualify pretrained model quality."""
import importlib.util
from types import SimpleNamespace
from unittest import skipUnless

from django.test import SimpleTestCase

from . import torch_rlhf as rl


@skipUnless(importlib.util.find_spec('torch'), 'Optional PyTorch is not installed')
class RLOOMathTests(SimpleTestCase):
    def test_leave_one_out_is_unstandardized_and_detached(self):
        import torch
        rewards = torch.tensor([1., 2., 6.], requires_grad=True)
        advantages = rl.leave_one_out_advantages(rewards)
        self.assertTrue(torch.equal(advantages, torch.tensor([-3., -1.5, 4.5])))
        self.assertFalse(advantages.requires_grad)
        for bad in ([1.], [1., float('nan')]):
            with self.assertRaises(ValueError): rl.leave_one_out_advantages(torch.tensor(bad))

    def test_fresh_sampling_and_update_preserve_frozen_reference(self):
        import copy
        import torch
        class Encoder(torch.nn.Module):
            def __init__(self):
                super().__init__(); self.embedding = torch.nn.Embedding(8, 4)
            def forward(self, input_ids, **kwargs):
                return SimpleNamespace(last_hidden_state=self.embedding(input_ids))
        class LM(torch.nn.Module):
            def __init__(self):
                super().__init__(); self.model = Encoder(); self.lm_head = torch.nn.Linear(4, 8, bias=False)
            def forward(self, input_ids, **kwargs):
                return SimpleNamespace(logits=self.lm_head(self.model(input_ids).last_hidden_state))
        with torch.random.fork_rng():
            torch.manual_seed(42); policy = LM()
        reference = copy.deepcopy(policy).requires_grad_(False)
        head = rl.reward_head(4); adam_head = rl.optimizer(head, .01)
        original = {k: v.clone() for k, v in reference.state_dict().items()}
        metrics = rl.reward_update(reference, head, adam_head,
            {'chosen': [1, 3, 4, 2], 'rejected': [1, 3, 5, 2], 'prompt_tokens': 2}, 1.)
        self.assertGreater(metrics['changed_parameters'], 0)
        samples = rl.generate_rollouts(policy, [1, 3], count=4, max_new_tokens=4, eos_token_id=2,
            generator=torch.Generator().manual_seed(42))
        scored, logits = rl.score_rollouts(reference, head, samples, .1)
        result = rl.policy_update(policy, rl.optimizer(policy, .001), scored, logits, 1.)
        self.assertGreater(result['changed_parameters'], 0)
        self.assertGreaterEqual(result['sampled_context_categorical_kl'], 0)
        self.assertTrue(all(torch.equal(v, original[k]) for k, v in reference.state_dict().items()))
        self.assertTrue(all(p.grad is None for p in reference.parameters()))
        with self.assertRaisesRegex(ValueError, 'on-policy'):
            rl.policy_update(policy, rl.optimizer(policy, .001), scored, logits, 1.)
