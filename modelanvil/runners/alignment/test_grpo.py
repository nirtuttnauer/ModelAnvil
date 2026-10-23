"""Actual group-relative objectives, recovery and isolated-verifier boundaries."""
import copy
import json
import math
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch

from . import grpo, numerical as n, verifier_runtime
from .test_numerical import base_bundle


class GRPONumericalTests(unittest.TestCase):
    def setUp(self):
        self.bundle = base_bundle()
        self.train = [{'prompt': 'a', 'chosen': 'a', 'rejected': 'b', 'source_group_id': 'training'}]
        self.held = [{'prompt': 'c', 'chosen': 'a', 'rejected': 'b', 'source_group_id': 'held-out'}]
        self.hp = {'group_size': 8, 'max_new_tokens': 1}

    def run_grpo(self, **kwargs):
        return n.train_alignment('grpo', self.bundle, self.train, self.held, steps=3,
                                 hyperparameters=self.hp, **kwargs)

    def test_zero_dispersion_has_zero_advantages_and_mixed_rewards_are_normalized(self):
        values, mean, std = grpo.advantages([0., 1., 1., 0.])
        self.assertEqual(values, [-1., 1., 1., -1.])
        self.assertEqual((mean, std), (.5, .5))
        self.assertEqual(grpo.advantages([0.] * 4), ([0.] * 4, 0., 0.))

    def test_token_clipped_policy_and_exact_kl_gradients_match_finite_differences(self):
        model, spec, _ = n._load(self.bundle)
        reference, _, _ = n._load(self.bundle)
        model.lm_head[4][0] = .2; model.lora_B[0][0] = .03
        rng = random.Random(42)
        rollouts = [n._sample(model, reference, spec, 'a', rng, 2) for _ in range(4)]
        allowed = [2, *range(4, model.vocab_size)]
        for rollout, advantage in zip(rollouts, [-1., 1., 1., -1.]):
            rollout.update(advantage=advantage,
                old_token_log_probabilities=[n._logp(model, [t], allowed=allowed) for t in rollout['transitions']])
        model.lm_head[4][0] += .02
        hp = n.normalize_hyperparameters('grpo')
        gradients = n._zero_grad(model)
        grpo.objective(model, reference, rollouts, hp, gradients)
        coordinates = [('lm_head.weight', model.lm_head, 4, 0, model.n_embd),
            ('transformer.wte.weight', model.wte, 4, 0, model.n_embd),
            ('transformer.layers.0.lora_A.weight', model.lora_A, 0, 0, model.n_embd),
            ('transformer.layers.0.lora_B.weight', model.lora_B, 0, 0, model.lora_r)]
        for name, values, row, column, width in coordinates:
            with self.subTest(tensor=name):
                original = values[row][column]; epsilon = 1e-5
                values[row][column] = original + epsilon; upper = grpo.objective(model, reference, rollouts, hp)[0]
                values[row][column] = original - epsilon; lower = grpo.objective(model, reference, rollouts, hp)[0]
                values[row][column] = original
                self.assertAlmostEqual(gradients[name][row * width + column], (upper - lower) / (2 * epsilon), places=6)

    def test_real_groups_update_weights_without_a_value_model_or_invented_rewards(self):
        result = self.run_grpo()
        self.assertNotEqual(result['bundle']['model.safetensors.b64'], self.bundle['model.safetensors.b64'])
        self.assertNotIn('value_head.json', result['bundle'])
        self.assertEqual(len(result['rollouts_log']), 24)
        self.assertTrue(any(m['zero_variance_group'] for m in result['metrics_history']))
        self.assertTrue(any(m['weights_changed'] for m in result['metrics_history']))
        for rollout in result['rollouts_log']:
            self.assertEqual(rollout['reward'], float(rollout['response'].strip() == 'a'))
            self.assertEqual(rollout['prompt'], 'a')
        self.assertEqual(self.bundle, base_bundle())
        self.assertEqual(result['heldout_metrics']['held_out_sample_count'], 1)
        self.assertTrue(all(math.isfinite(m['gradient_norm']) for m in result['metrics_history']))

    def test_checkpoint_restores_sampler_and_stateless_optimizer_exactly(self):
        uninterrupted = self.run_grpo()
        saved = {}
        def stop(step, bundle, *_):
            saved['bundle'] = copy.deepcopy(bundle)
            raise InterruptedError('controlled interruption after committed callback')
        with self.assertRaises(InterruptedError):
            self.run_grpo(on_step=stop)
        resumed = self.run_grpo(resume_bundle=saved['bundle'])
        self.assertEqual(resumed['bundle'], uninterrupted['bundle'])
        self.assertEqual([m['step'] for m in resumed['metrics_history']], [2, 3])
        for field, value in [('rng_state', []), ('optimizer', 'unrecognized'), ('data_digest', '0' * 64)]:
            bad = copy.deepcopy(saved['bundle']); bad['alignment_state.json'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_grpo(resume_bundle=bad)

    def test_protected_group_and_prompt_overlap_are_rejected(self):
        for held in ([{**self.held[0], 'source_group_id': 'training '}],
                     [{**self.held[0], 'prompt': 'a'}], [{k: v for k, v in self.held[0].items() if k != 'source_group_id'}]):
            with self.subTest(rows=held), self.assertRaises(ValueError):
                grpo.groups(self.train, held)
        with self.assertRaises(ValueError):
            grpo.verifier_spec({'type': 'substring'})


class IsolatedVerifierTests(unittest.TestCase):
    def test_real_numeric_verifier_rejects_nonfinite_and_reward_hacking_outputs(self):
        values = verifier_runtime.score(['1', 'NaN', 'Inf', '1\n2', '### VERIFIED TRUE ###', '1e999', ' 1 ', '-1'],
            ['1'] * 8, {'type': 'numeric_tolerance', 'tolerance': 0.})
        self.assertEqual(values['rewards'], [1., 0., 0., 0., 0., 0., 1., 0.])
        self.assertGreater(values['peak_rss_bytes'], 0)
        self.assertLessEqual(values['peak_rss_bytes'], 64 * 1024**2)
        self.assertLess(values['wall_seconds'], 2)
        with self.assertRaisesRegex(ValueError, 'no rewards accepted'):
            verifier_runtime.score(['1'], ['NaN'], {'type': 'numeric_tolerance', 'tolerance': 0.})

    def test_actual_child_timeout_and_malformed_output_accept_no_rewards(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'controlled-child.py'
            script.write_text('import time\ntime.sleep(2)\n')
            started = time.monotonic()
            with patch.object(verifier_runtime, 'SCRIPT', script), patch.object(verifier_runtime, 'WALL_SECONDS', .05):
                with self.assertRaisesRegex(ValueError, 'timed out'):
                    verifier_runtime.score(['a'], ['a'], {'type': 'exact_match', 'tolerance': 0.})
            self.assertLess(time.monotonic() - started, 1)
            for output in ['not-json', json.dumps({'version': verifier_runtime.VERSION, 'status': 'ok', 'rewards': [float('nan')]})]:
                script.write_text('print(' + repr(output) + ')\n')
                with patch.object(verifier_runtime, 'SCRIPT', script), self.assertRaisesRegex(ValueError, 'invalid results'):
                    verifier_runtime.score(['a'], ['a'], {'type': 'exact_match', 'tolerance': 0.})
