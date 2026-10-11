"""Numerical objective checks independent of ORM persistence or fixture metrics."""
import base64
import copy
import json
import math
import unittest

from modelanvil.runners.alignment.numerical import (
    _dpo, _kl, _load, _ppo_objective, _zero_grad, normalize_hyperparameters,
    normalize_verifier_spec, score_reward, train_alignment,
)
from modelanvil.runners.training.engine import CausalTextModel, TrainingEngine, pack_safetensors
from modelanvil.runners.training.runtime import RUNTIME_ID


def base_bundle():
    model = CausalTextModel(12, n_embd=4, lora_r=2, lora_alpha=4, seed=42)
    raw, manifest = pack_safetensors(model.export_tensors())
    return {'config.json': {'runtime': RUNTIME_ID, 'vocab_size': 12, 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
            'model.safetensors.b64': base64.b64encode(raw).decode(), 'weights_manifest.json': manifest,
            'tokenizer_config.json': {'kind': 'character-v1', 'tokens': ['<pad>', '<bos>', '<eos>', '<unk>', 'a', 'b', 'c', 'd', 'e', 'f', ' ', '\n'], 'bos_id': 1, 'eos_id': 2, 'unk_id': 3},
            'provenance.json': {'trained': False, 'production_qualified': False}}


class NumericalAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.bundle = base_bundle()
        self.training = [{'prompt': 'a', 'chosen': 'a', 'rejected': 'b'}]
        self.heldout = [{'prompt': 'c', 'chosen': 'a', 'rejected': 'b'}]

    def test_dpo_gradient_matches_central_finite_difference_for_all_tensor_groups(self):
        model, spec, _ = _load(self.bundle)
        reference, _, _ = _load(self.bundle)
        # Exercise every backprop branch, including the normally zero LoRA-B/head.
        model.lm_head[4][0] = .2; model.lm_head[5][1] = -.1
        model.lora_B[0][0] = .03
        gradients = _zero_grad(model)
        _dpo(model, reference, spec, self.training[0], .1, gradients)
        parameters = [('lm_head.weight', model.lm_head, 4, 0),
                      ('transformer.wte.weight', model.wte, 4, 0),
                      ('transformer.layers.0.lora_A.weight', model.lora_A, 0, 0),
                      ('transformer.layers.0.lora_B.weight', model.lora_B, 0, 0)]
        for name, matrix, row, column in parameters:
            original = matrix[row][column]; epsilon = 1e-5
            matrix[row][column] = original + epsilon
            plus = _dpo(model, reference, spec, self.training[0], .1)[0]
            matrix[row][column] = original - epsilon
            minus = _dpo(model, reference, spec, self.training[0], .1)[0]
            matrix[row][column] = original
            numerical = (plus - minus) / (2 * epsilon)
            analytical = gradients[name][row * len(matrix[0]) + column]
            self.assertAlmostEqual(numerical, analytical, delta=1e-8, msg=name)

    def test_exact_categorical_kl_gradient_matches_finite_difference(self):
        model, _, _ = _load(self.bundle); reference, _, _ = _load(self.bundle)
        model.lm_head[4][0] = .4
        gradients = _zero_grad(model); transitions = [(4, 5), (5, 2)]
        value = _kl(model, reference, transitions, gradients, 1.)
        self.assertGreater(value, 0)
        original = model.lm_head[4][0]; epsilon = 1e-5
        model.lm_head[4][0] = original + epsilon; plus = _kl(model, reference, transitions)
        model.lm_head[4][0] = original - epsilon; minus = _kl(model, reference, transitions)
        self.assertAlmostEqual((plus - minus) / (2 * epsilon), gradients['lm_head.weight'][16], delta=1e-8)

    def test_ppo_clipping_gradient_matches_actual_surrogate_on_both_advantage_signs(self):
        for ratio in (.6, 1., 1.5):
            for advantage in (-2., 2.):
                log_ratio = math.log(ratio); epsilon = 1e-6
                objective, gradient, clipped = _ppo_objective(log_ratio, advantage, .2)
                plus = _ppo_objective(log_ratio + epsilon, advantage, .2)[0]
                minus = _ppo_objective(log_ratio - epsilon, advantage, .2)[0]
                self.assertAlmostEqual((plus - minus) / (2 * epsilon), gradient, delta=1e-8)
                self.assertAlmostEqual(objective, -min(ratio * advantage, min(1.2, max(.8, ratio)) * advantage))
                if clipped:
                    self.assertEqual(gradient, 0.)
        with self.assertRaises(ValueError): _ppo_objective(1000, 1., .2)

    def test_dpo_changes_canonical_weights_reduces_measured_loss_and_freezes_reference(self):
        original = copy.deepcopy(self.bundle); checkpoints = []
        result = train_alignment('dpo', self.bundle, self.training, self.heldout, reference_bundle=self.bundle,
                                 steps=30, hyperparameters={'learning_rate': .2}, on_step=lambda *args: checkpoints.append(args))
        self.assertEqual(self.bundle, original)
        self.assertNotEqual(result['bundle']['weights_manifest.json']['weights_sha256'], original['weights_manifest.json']['weights_sha256'])
        self.assertLess(result['metrics_history'][-1]['loss'], result['metrics_history'][0]['loss'])
        self.assertEqual(result['heldout_metrics']['held_out_sample_count'], 1)
        self.assertTrue(all(c[2]['weights_changed'] for c in checkpoints))
        self.assertEqual(result['bundle'], checkpoints[-1][1])
        for _, bundle, _, _ in checkpoints:
            self.assertEqual(bundle, json.loads(json.dumps(bundle)))
            self.assertTrue(TrainingEngine.verify_external_loadable(bundle)['is_loadable'])
        self.assertEqual(result['bundle']['alignment_state.json']['seed'], 42)

    def test_bradley_terry_head_is_real_serialized_frozen_encoder_and_usable_by_ppo(self):
        result = train_alignment('reward_model', self.bundle, self.training, self.heldout, steps=20)
        reward = result['bundle']
        self.assertEqual(reward['model.safetensors.b64'], self.bundle['model.safetensors.b64'])
        self.assertTrue(any(w != 0 for w in reward['reward_head.json']['weights']))
        chosen = score_reward(reward, 'a', 'a'); rejected = score_reward(reward, 'a', 'b')
        self.assertGreater(chosen, rejected)
        self.assertLess(result['metrics_history'][-1]['loss'], result['metrics_history'][0]['loss'])
        frozen_reward = copy.deepcopy(reward)
        policy = train_alignment('ppo_rlhf', self.bundle, self.training, self.heldout, reference_bundle=self.bundle,
                                 reward_bundle=reward, steps=5, hyperparameters={'max_new_tokens': 3, 'rollout_batch_size': 4})
        self.assertNotEqual(policy['bundle']['model.safetensors.b64'], self.bundle['model.safetensors.b64'])
        self.assertEqual(reward, frozen_reward)
        self.assertNotIn('reward_head.json', policy['bundle'])
        self.assertTrue(any(w != 0 for w in policy['bundle']['value_head.json']['weights']))
        for row in policy['rollouts_log']:
            self.assertAlmostEqual(row['reward'], score_reward(reward, row['prompt'], row['response']))
            self.assertTrue(math.isfinite(row['old_log_probability']))
        self.assertEqual(policy['heldout_metrics']['held_out_sample_count'], 1)
        bad = copy.deepcopy(reward); bad['reward_head.json']['weights'][0] += .1
        with self.assertRaises(ValueError):
            score_reward(bad, 'a', 'a')
        huge = copy.deepcopy(reward); huge['reward_head.json']['weights'][0] = 1e300
        with self.assertRaises(ValueError): score_reward(huge, 'a', 'a')
        with self.assertRaises(ValueError):
            train_alignment('ppo_rlhf', self.bundle, self.training, self.heldout, reference_bundle=self.bundle, reward_bundle=self.bundle)

    def test_verifier_samples_fresh_outputs_scores_them_and_never_injects_answers(self):
        result = train_alignment('verifier_rl', self.bundle, self.training, self.heldout, steps=4,
                                 verifier_spec={'type': 'exact_match'}, hyperparameters={'max_new_tokens': 3, 'rollout_batch_size': 4})
        self.assertEqual(len(result['rollouts_log']), 16)
        outputs = [r['response'] for r in result['rollouts_log']]
        self.assertGreater(len(set(outputs)), 1)
        for row in result['rollouts_log']:
            self.assertEqual(row['reward'], 1. if row['response'].strip() == 'a' else -1.)
        self.assertNotEqual(result['bundle']['model.safetensors.b64'], self.bundle['model.safetensors.b64'])
        self.assertGreater(result['metrics_history'][0]['gradient_norm'], 0)
        self.assertTrue(0 <= result['heldout_metrics']['held_out_pass_rate'] <= 1)
        again = train_alignment('verifier_rl', self.bundle, self.training, self.heldout, steps=4,
                                verifier_spec={'type': 'exact_match'}, hyperparameters={'max_new_tokens': 3, 'rollout_batch_size': 4})
        self.assertEqual(again, result)

    def test_long_prompt_caps_fresh_response_to_declared_character_envelope(self):
        training = [{'prompt': 'a' * 61, 'chosen': 'a', 'rejected': 'b'}]
        heldout = [{'prompt': 'c' * 61, 'chosen': 'a', 'rejected': 'b'}]
        result = train_alignment('verifier_rl', self.bundle, training, heldout, steps=2,
                                 hyperparameters={'max_new_tokens': 16, 'rollout_batch_size': 4})
        for row in result['rollouts_log']:
            self.assertEqual(row['max_new_tokens'], 1)
            self.assertLessEqual(len(row['response']), 1)
            self.assertLessEqual(len(row['prompt']) + len(row['response']), 62)
            self.assertEqual(len(row['transitions']), 1)

    def test_unsupported_inputs_and_cancellation_stop_before_later_updates(self):
        for algorithm, params in [('dpo', []), ('dpo', {'beta': float('nan')}), ('ppo_rlhf', {'ppo_epochs': 1.5}), ('reward_model', {'fake_improvement': 1})]:
            with self.assertRaises(ValueError): normalize_hyperparameters(algorithm, params)
        with self.assertRaises(ValueError): normalize_verifier_spec({'type': 'unknown'})
        with self.assertRaises(ValueError): train_alignment('dpo', self.bundle, self.training, self.heldout)
        with self.assertRaises(ValueError): train_alignment('dpo', self.bundle, self.training, self.training, reference_bundle=self.bundle)
        invalid = copy.deepcopy(self.bundle); invalid['config.json']['n_embd'] = 17
        with self.assertRaises(ValueError): train_alignment('reward_model', invalid, self.training, self.heldout)
        too_long = [{'prompt': 'a' * 40, 'chosen': 'b' * 32, 'rejected': 'a'}]
        with self.assertRaises(ValueError): train_alignment('reward_model', self.bundle, too_long, self.heldout)
        calls = []
        def cancel(step, *args):
            calls.append(step); raise RuntimeError('Cancelled by service fence')
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            train_alignment('dpo', self.bundle, self.training, self.heldout, reference_bundle=self.bundle, steps=3, on_step=cancel)
        self.assertEqual(calls, [1])
