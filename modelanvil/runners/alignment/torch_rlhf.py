"""CPU reward head and on-policy RLOO (Ahmadian et al., arXiv:2402.14740, §2.3)."""
import math

from .torch_dpo import response_log_probability


def require_cpu(model):
    import torch
    if any(p.device.type != 'cpu' or p.dtype != torch.float32 for p in model.parameters()):
        raise ValueError('This alignment profile requires materialized CPU FP32 parameters.')


def reward_head(hidden_size):
    import torch
    head = torch.nn.Linear(hidden_size, 1, bias=False, dtype=torch.float32, device='cpu')
    torch.nn.init.zeros_(head.weight)
    return head


def response_features(encoder, ids, prompt_tokens):
    import torch
    if not 1 <= prompt_tokens < len(ids) <= 128:
        raise ValueError('Reward pooling requires a bounded nonempty response.')
    require_cpu(encoder)
    with torch.no_grad():
        hidden = encoder.model(input_ids=torch.tensor([ids], dtype=torch.long), use_cache=False).last_hidden_state
        features = hidden[0, prompt_tokens:].float().mean(dim=0).detach()
    if not torch.isfinite(features).all().item():
        raise ValueError('Reward encoder produced non-finite features.')
    return features


def optimizer(model, learning_rate):
    import torch
    return torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=learning_rate,
        betas=(.9, .999), eps=1e-8, weight_decay=0., foreach=False)


def apply_update(loss, model, adam, max_gradient_norm):
    import torch
    if not torch.isfinite(loss).item():
        raise ValueError('Non-finite alignment objective; update refused.')
    trainable = [p for p in model.parameters() if p.requires_grad]
    before = [p.detach().clone() for p in trainable]
    adam.zero_grad(set_to_none=True)
    loss.backward()
    if any(p.grad is None or not torch.isfinite(p.grad).all().item() for p in trainable):
        raise ValueError('Missing or non-finite alignment gradient; update refused.')
    norm = torch.nn.utils.clip_grad_norm_(trainable, max_gradient_norm, error_if_nonfinite=True)
    adam.step()
    if any(not torch.isfinite(p).all().item() for p in trainable):
        raise ValueError('Non-finite updated alignment weights; checkpoint refused.')
    return {'loss': float(loss.detach()), 'gradient_norm': float(norm),
        'changed_parameters': sum(int(torch.count_nonzero(a != p.detach())) for a, p in zip(before, trainable)),
        'trainable_parameters': sum(p.numel() for p in trainable)}


def reward_update(encoder, head, adam, pair, max_gradient_norm):
    import torch.nn.functional as F
    chosen = head(response_features(encoder, pair['chosen'], pair['prompt_tokens'])).squeeze()
    rejected = head(response_features(encoder, pair['rejected'], pair['prompt_tokens'])).squeeze()
    metrics = apply_update(-F.logsigmoid(chosen - rejected), head, adam, max_gradient_norm)
    return {**metrics, 'chosen_reward': float(chosen.detach()), 'rejected_reward': float(rejected.detach())}


def generate_rollouts(policy, prompt_ids, *, count, max_new_tokens, eos_token_id, generator, heartbeat=lambda: True):
    import torch
    require_cpu(policy)
    if (not 1 <= len(prompt_ids) <= 120 or type(count) is not int or not 2 <= count <= 4
            or type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 8
            or len(prompt_ids) + max_new_tokens > 128 or type(eos_token_id) is not int):
        raise ValueError('RLOO requires 2–4 bounded fresh completions and a pinned EOS token.')
    result = []
    was_training = policy.training
    policy.eval()
    try:
        with torch.no_grad():
            for _ in range(count):
                ids = list(prompt_ids); logp = 0.
                for _ in range(max_new_tokens):
                    if not heartbeat():
                        raise InterruptedError('RLOO rollout lost its claim.')
                    logits = policy(input_ids=torch.tensor([ids], dtype=torch.long), use_cache=False).logits[0, -1].float()
                    if not torch.isfinite(logits).all().item():
                        raise ValueError('Non-finite rollout logits.')
                    probabilities = torch.softmax(logits, dim=-1)
                    token = int(torch.multinomial(probabilities, 1, generator=generator))
                    logp += float(torch.log_softmax(logits, dim=-1)[token])
                    ids.append(token)
                    if token == eos_token_id: break
                result.append({'ids': ids, 'prompt_tokens': len(prompt_ids), 'old_log_probability': logp,
                    'generated_tokens': len(ids) - len(prompt_ids)})
    finally:
        policy.train(was_training)
    return result


def score_rollouts(reference, head, rollouts, beta):
    import torch
    if not math.isfinite(beta) or not 0 <= beta <= 1:
        raise ValueError('RLOO KL coefficient must lie between zero and one.')
    require_cpu(reference); require_cpu(head)
    if any(p.requires_grad for p in reference.parameters()):
        raise ValueError('RLOO reference must be frozen.')
    scored, reference_logits = [], {}
    with torch.no_grad():
        for index, row in enumerate(rollouts):
            ids, start = row['ids'], row['prompt_tokens']
            hidden = reference.model(input_ids=torch.tensor([ids], dtype=torch.long), use_cache=False).last_hidden_state
            reward = float(head(hidden[0, start:].mean(dim=0)).squeeze())
            logits = reference.lm_head(hidden[0, start - 1:-1]).float()
            target = torch.tensor(ids[start:], dtype=torch.long)
            ref_logp = -float(torch.nn.functional.cross_entropy(logits, target, reduction='sum'))
            shaped = reward - beta * (row['old_log_probability'] - ref_logp)
            if not all(math.isfinite(x) for x in (reward, ref_logp, shaped)):
                raise ValueError('Non-finite rollout score.')
            scored.append({**row, 'reward': reward, 'reference_log_probability': ref_logp, 'shaped_reward': shaped})
            reference_logits[str(index)] = logits.contiguous()
    return scored, reference_logits


def leave_one_out_advantages(rewards):
    import torch
    if rewards.ndim != 1 or not 2 <= len(rewards) <= 4 or not torch.isfinite(rewards).all().item():
        raise ValueError('RLOO needs 2–4 finite rewards for the same prompt.')
    return (rewards - (rewards.sum() - rewards) / (len(rewards) - 1)).detach()


def policy_update(policy, adam, scored, reference_logits, max_gradient_norm):
    import torch
    require_cpu(policy)
    prompts = {tuple(row['ids'][:row['prompt_tokens']]) for row in scored}
    if len(prompts) != 1:
        raise ValueError('Leave-one-out baselines require independent samples of the same prompt.')
    advantages = leave_one_out_advantages(torch.tensor([row['shaped_reward'] for row in scored]))
    logps = torch.stack([response_log_probability(policy, row['ids'], row['prompt_tokens'], 'cpu') for row in scored])
    old = torch.tensor([row['old_log_probability'] for row in scored])
    if not torch.allclose(logps.detach(), old, rtol=1e-5, atol=1e-4):
        raise ValueError('RLOO samples are no longer on-policy; refuse off-policy updates.')
    metrics = apply_update(-(advantages * logps).mean(), policy, adam, max_gradient_norm)
    divergences = []
    with torch.no_grad():
        for index, row in enumerate(scored):
            ids, start = row['ids'], row['prompt_tokens']
            logits = policy(input_ids=torch.tensor([ids[:-1]], dtype=torch.long), use_cache=False).logits[0, start - 1:].float()
            ref = reference_logits[str(index)]
            if ref.shape != logits.shape or not torch.isfinite(ref).all().item():
                raise ValueError('Frozen-reference response logits differ from the checkpoint.')
            logp, logq = logits.log_softmax(-1), ref.log_softmax(-1)
            divergences.append(float((logp.exp() * (logp - logq)).sum(-1).mean()))
    return {**metrics, 'reward_mean': sum(row['reward'] for row in scored) / len(scored),
        'shaped_reward_mean': sum(row['shaped_reward'] for row in scored) / len(scored),
        'sampled_context_categorical_kl': max(0., sum(divergences) / len(divergences)),
        'advantage_min': float(advantages.min()), 'advantage_max': float(advantages.max())}
