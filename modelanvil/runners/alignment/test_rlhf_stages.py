"""Actual CPU stage boundaries and serialized restart; no production qualification."""
import copy
import json
import unittest

from . import numerical as n, rlhf_stages as stages
from .test_numerical import base_bundle


class RLHFStageTests(unittest.TestCase):
    def test_serialized_reward_and_ppo_stages_reproduce_actual_continuous_weights(self):
        base = base_bundle(); training = [{'prompt': 'a', 'chosen': 'a', 'rejected': 'b'}]
        held = [{'prompt': 'c', 'chosen': 'a', 'rejected': 'b'}]
        reward_plan = stages.prepare('reward_model', base, training, steps=20)
        reward_state = stages.initial_state(reward_plan)
        for _ in range(20):
            reward_state, units = stages.advance(reward_plan, json.loads(json.dumps(reward_state)))
            self.assertEqual(units, {'training_steps': 1, 'generated_tokens': 0, 'reward_scores': 2})
        reward = n.train_alignment('reward_model', base, training, held, steps=20)['bundle']
        self.assertEqual(reward_state['bundle'], reward)
        hp = {'max_new_tokens': 3, 'rollout_batch_size': 4}
        plan = stages.prepare('ppo_rlhf', base, training, reference=base, reward=reward, steps=5, hyperparameters=hp)
        frozen = copy.deepcopy(plan)
        state = stages.initial_state(plan)
        committed_records, total_tokens = [], 0
        for update in range(5):
            state, units = stages.advance(plan, json.loads(json.dumps(state)))
            self.assertEqual(state['phase'], 'score')
            self.assertEqual(units['reward_scores'], 0)
            self.assertGreater(units['generated_tokens'], 0)
            total_tokens += units['generated_tokens']
            self.assertTrue(all('reward' not in row for row in state['records']))
            generated = copy.deepcopy(state['records']); starting_weights = state['bundle']['model.safetensors.b64']
            state, units = stages.advance(plan, json.loads(json.dumps(state)))
            self.assertEqual(state['phase'], 'policy_update')
            self.assertEqual(units, {'training_steps': 0, 'generated_tokens': 0, 'reward_scores': 4})
            self.assertEqual(state['bundle']['model.safetensors.b64'], starting_weights)
            self.assertEqual([r['response'] for r in generated], [r['response'] for r in state['records']])
            for row in state['records']:
                self.assertAlmostEqual(row['reward'], n.score_reward(reward, row['prompt'], row['response']))
            committed_records.extend(state['records'])
            state, units = stages.advance(plan, json.loads(json.dumps(state)))
            self.assertEqual(state['completed_updates'], update + 1)
            self.assertEqual(units, {'training_steps': 1, 'generated_tokens': 0, 'reward_scores': 0})
        uninterrupted = n.train_alignment('ppo_rlhf', base, training, held, reference_bundle=base,
            reward_bundle=reward, steps=5, hyperparameters=hp)
        self.assertEqual(state['phase'], 'finished')
        self.assertEqual(state['bundle'], uninterrupted['bundle'])
        self.assertEqual(committed_records, json.loads(json.dumps(uninterrupted['rollouts_log'])))
        self.assertEqual(total_tokens, sum(len(row['transitions']) for row in committed_records))
        self.assertEqual(plan, frozen, 'Policy updates must not mutate the pinned reward or reference.')
        self.assertNotEqual(state['bundle']['model.safetensors.b64'], base['model.safetensors.b64'])
        with self.assertRaises(ValueError): stages.advance(plan, state)

    def test_saved_plan_and_rng_cannot_silently_change_on_resume(self):
        base = base_bundle(); training = [{'prompt': 'a', 'chosen': 'a', 'rejected': 'b'}]
        reward = n.train_alignment('reward_model', base, training,
            [{'prompt': 'c', 'chosen': 'a', 'rejected': 'b'}], steps=3)['bundle']
        plan = stages.prepare('ppo_rlhf', base, training, reference=base, reward=reward, steps=2)
        state = stages.initial_state(plan)
        altered = copy.deepcopy(plan); altered['hyperparameters']['learning_rate'] *= 2
        with self.assertRaisesRegex(ValueError, 'plan'): stages.advance(altered, state)
        state['rng_state'] = ['invalid']
        with self.assertRaisesRegex(ValueError, 'RNG'): stages.advance(plan, state)
