"""CPU reward/PPO kernels shared by synchronous and checkpointed stage execution."""
import copy
import hashlib
import json
import math
import random

from . import numerical as n


def train_reward_head(model, spec, row, weights, hp):
    delta = [a - b for a, b in zip(n._features(model, spec, row['prompt'], row['chosen']),
                                  n._features(model, spec, row['prompt'], row['rejected']))]
    margin = n._dot(weights, delta)
    gradient = [(n._sigmoid(margin) - 1.) * feature for feature in delta]
    norm = math.sqrt(sum(g * g for g in gradient))
    scale = min(1., hp['max_gradient_norm'] / max(norm, 1e-12))
    weights = [w - hp['learning_rate'] * scale * g for w, g in zip(weights, gradient)]
    return weights, {'loss': n._pair_loss(margin), 'reward_margin': margin,
                     'preference_accuracy': float(margin > 0), 'gradient_norm': norm}


def generate_rollouts(model, reference, spec, training, step, hp, rng):
    records = []
    for index in range(hp['rollout_batch_size']):
        task = training[((step - 1) * hp['rollout_batch_size'] + index) % len(training)]
        records.append({**n._sample(model, reference, spec, task['prompt'], rng, hp['max_new_tokens']), 'step': step})
    return records


def score_rollouts(model, reference, reward_model, reward_weights, spec, training, records,
                   value_weights, step, hp, *, verifier_spec=None):
    scored = copy.deepcopy(records)
    for index, rollout in enumerate(scored):
        task = training[((step - 1) * hp['rollout_batch_size'] + index) % len(training)]
        feature = n._features(model, spec, task['prompt'], '')
        reward = ((1. if n._verify(rollout['response'], task.get('ground_truth', task.get('chosen')), verifier_spec) else -1.)
                  if verifier_spec is not None else
                  n._dot(reward_weights, n._features(reward_model, spec, task['prompt'], rollout['response'])))
        value = n._dot(value_weights, feature)
        rollout.update(reward=reward, value=value, advantage=reward - value,
                       kl_divergence=n._kl(model, reference, rollout['transitions']))
    return scored


def update_policy(model, reference, spec, records, value_weights, hp):
    clipped_count, objective, norm = 0, 0., 0.
    for _ in range(hp['ppo_epochs']):
        gradients = n._zero_grad(model); objective = 0.
        for rollout in records:
            logp = n._logp(model, rollout['transitions'], allowed=[2, *range(4, model.vocab_size)])
            surrogate, derivative, clipped = n._ppo_objective(
                logp - rollout['old_log_probability'], rollout['advantage'], hp['clip_range'])
            objective += surrogate / len(records)
            clipped_count += int(clipped)
            if not clipped:
                n._logp(model, rollout['transitions'], allowed=[2, *range(4, model.vocab_size)],
                        gradients=gradients, coefficient=derivative / len(records))
            objective += hp['kl_coefficient'] * n._kl(model, reference, rollout['transitions'],
                gradients, hp['kl_coefficient'] / len(records)) / len(records)
        norm = n._apply(model, gradients, hp)
    value_loss = 0.
    for rollout in records:
        feature = n._features(model, spec, rollout['prompt'], '')
        error = n._dot(value_weights, feature) - rollout['reward']
        value_loss += error * error / len(records)
        value_weights = [w - hp['value_learning_rate'] * error * f / len(records) for w, f in zip(value_weights, feature)]
    mean_reward = sum(r['reward'] for r in records) / len(records)
    mean_kl = sum(r['kl_divergence'] for r in records) / len(records)
    return value_weights, {'policy_loss': objective, 'value_loss': value_loss, 'raw_reward_mean': mean_reward,
        'net_reward_mean': mean_reward - hp['kl_coefficient'] * mean_kl, 'kl_divergence': mean_kl,
        'gradient_norm': norm, 'clip_fraction': clipped_count / (len(records) * hp['ppo_epochs']),
        'sample_count': len(records)}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def prepare(algorithm, policy, training, *, reference=None, reward=None, steps=20, hyperparameters=None, seed=42):
    """Internal numerical plan; API admission must additionally enforce reviewed/project-scoped inputs."""
    if algorithm not in ('reward_model', 'ppo_rlhf'):
        raise ValueError('The staged CPU profile supports learned reward heads and PPO only.')
    if type(steps) is not int or not 1 <= steps <= 100 or type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('Use 1–100 updates and a nonnegative 32-bit seed.')
    model, spec, encoder = n._load(policy)
    training = n.validate_preferences(training, spec)
    reference = reference or policy
    if n._load(reference)[1] != spec:
        raise ValueError('Policy/reference tokenizers differ.')
    if algorithm == 'ppo_rlhf':
        if reward is None: raise ValueError('PPO requires an actual learned reward head.')
        reward_model, reward_spec, reward_encoder = n._load(reward)
        if reward_spec != spec: raise ValueError('Reward/policy tokenizers differ.')
        n._validate_head(reward.get('reward_head.json'), reward_model, reward_encoder)
    plan = {'algorithm': algorithm, 'initial_policy': policy, 'reference': reference, 'reward': reward,
            'training': training, 'steps': steps, 'hyperparameters': n.normalize_hyperparameters(algorithm, hyperparameters),
            'seed': seed, 'initial_weights_sha256': encoder}
    return copy.deepcopy(plan)


def initial_state(plan):
    model, _, encoder = n._load(plan['initial_policy'])
    values = (n._validate_head(plan['initial_policy']['value_head.json'], model, encoder,
              format_name='modelanvil.cpu-character-value.v1') if 'value_head.json' in plan['initial_policy'] else [0.] * model.n_embd)
    return {'schema_version': 'modelanvil.cpu-rlhf-stages.v1', 'plan_digest': _digest(plan),
            'completed_updates': 0, 'phase': 'reward_update' if plan['algorithm'] == 'reward_model' else 'rollout',
            'bundle': copy.deepcopy(plan['initial_policy']), 'value_weights': values,
            'rng_state': random.Random(plan['seed']).getstate(), 'records': [], 'latest_metrics': {}}


def advance(plan, state):
    """Compute one serializable stage, returning its state and measured logical resource units."""
    if (state.get('schema_version') != 'modelanvil.cpu-rlhf-stages.v1' or state.get('plan_digest') != _digest(plan)
            or type(state.get('completed_updates')) is not int or not 0 <= state['completed_updates'] < plan['steps']):
        raise ValueError('Staged alignment plan or committed update cursor changed.')
    state = copy.deepcopy(state)
    phase, step, hp = state['phase'], state['completed_updates'] + 1, plan['hyperparameters']
    model, spec, encoder = n._load(state['bundle'])
    reference, _, _ = n._load(plan['reference'])
    rng = random.Random()
    def tuples(value): return tuple(tuples(item) for item in value) if isinstance(value, (tuple, list)) else value
    try: rng.setstate(tuples(state['rng_state']))
    except (ValueError, TypeError, KeyError): raise ValueError('Staged alignment RNG state is invalid.') from None
    units = {'training_steps': 0, 'generated_tokens': 0, 'reward_scores': 0}
    reward_weights = None
    if plan['algorithm'] == 'reward_model':
        if phase != 'reward_update': raise ValueError('Invalid reward-training stage.')
        weights = n._validate_head(state['bundle']['reward_head.json'], model, encoder) if 'reward_head.json' in state['bundle'] else [0.] * model.n_embd
        reward_weights, metrics = train_reward_head(model, spec, plan['training'][(step - 1) % len(plan['training'])], weights, hp)
        units.update(training_steps=1, reward_scores=2)
    elif phase == 'rollout':
        state['records'] = generate_rollouts(model, reference, spec, plan['training'], step, hp, rng)
        state['rng_state'], state['phase'] = rng.getstate(), 'score'
        units['generated_tokens'] = sum(len(row['transitions']) for row in state['records'])
        return state, units
    elif phase == 'score':
        reward_model, _, reward_encoder = n._load(plan['reward'])
        weights = n._validate_head(plan['reward']['reward_head.json'], reward_model, reward_encoder)
        state['records'] = score_rollouts(model, reference, reward_model, weights, spec, plan['training'],
            state['records'], state['value_weights'], step, hp)
        state['phase'] = 'policy_update'
        units['reward_scores'] = len(state['records'])
        return state, units
    elif phase == 'policy_update':
        state['value_weights'], metrics = update_policy(model, reference, spec, state['records'], state['value_weights'], hp)
        units['training_steps'] = 1
    else:
        raise ValueError('Invalid PPO stage.')
    metadata = {'algorithm': plan['algorithm'], 'seed': plan['seed'], 'step': step, 'hyperparameters': hp,
                'rng_state': rng.getstate(), 'initial_weights_sha256': plan['initial_weights_sha256']}
    state['bundle'] = n._bundle(model, plan['initial_policy'], metadata, reward_weights=reward_weights,
        value_weights=state['value_weights'] if plan['algorithm'] == 'ppo_rlhf' else None)
    model, _, encoder = n._load(state['bundle'])
    if plan['algorithm'] == 'ppo_rlhf':
        state['value_weights'] = n._validate_head(state['bundle']['value_head.json'], model, encoder,
            format_name='modelanvil.cpu-character-value.v1')
    state['completed_updates'], state['latest_metrics'] = step, {'step': step, **metrics}
    state['phase'] = 'finished' if step == plan['steps'] else 'reward_update' if plan['algorithm'] == 'reward_model' else 'rollout'
    return state, units
