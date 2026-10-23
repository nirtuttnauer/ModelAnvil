"""Response-only DPO log probabilities; objective from arXiv:2305.18290, Eq. 7."""
import math


def encode_pair(tokenizer, pair, *, limit=128):
    if tokenizer.chat_template:
        raise ValueError('This DPO profile uses the pinned plain-text base without a chat template.')
    if any(token in pair[field] for token in tokenizer.all_special_tokens for field in ('prompt', 'chosen', 'rejected')):
        raise ValueError('Preference text cannot contain tokenizer control tokens.')
    prompt = tokenizer.encode(pair['prompt'], add_special_tokens=True)
    encoded = {'prompt_tokens': len(prompt)}
    for field in ('chosen', 'rejected'):
        ids = tokenizer.encode(pair['prompt'] + pair[field], add_special_tokens=True)
        if not prompt or ids[:len(prompt)] != prompt or len(ids) <= len(prompt):
            raise ValueError('Prompt/response token boundaries must match the pinned plain-text template.')
        if type(tokenizer.eos_token_id) is not int:
            raise ValueError('DPO requires a pinned EOS token.')
        ids.append(tokenizer.eos_token_id)
        if len(ids) > limit:
            raise ValueError('DPO prompt and response must fit within 128 tokens including EOS; no truncation.')
        encoded[field] = ids
    if encoded['chosen'] == encoded['rejected']:
        raise ValueError('Chosen and rejected responses must encode to different tokens.')
    return encoded


def response_log_probability(model, ids, prompt_tokens, device):
    import torch
    import torch.nn.functional as functional
    if not 1 <= prompt_tokens < len(ids) <= 128:
        raise ValueError('Invalid response token mask.')
    tokens = torch.tensor([ids], dtype=torch.long, device=device)
    inputs = tokens[:, :-1]
    # One unpadded sequence needs only the model's native causal mask.
    logits = model(input_ids=inputs, use_cache=False).logits
    # Gather backward uses an unsupported deterministic MPS scatter; CE has the same SUM log-probability.
    return -functional.cross_entropy(logits[0, prompt_tokens - 1:, :].float(),
        tokens[0, prompt_tokens:], reduction='sum')


def preference_loss(chosen, rejected, reference_chosen, reference_rejected, beta):
    import torch.nn.functional as functional
    if type(beta) not in (float, int) or not math.isfinite(beta) or beta <= 0:
        raise ValueError('DPO beta must be finite and positive.')
    margin = (chosen - rejected) - (reference_chosen.detach() - reference_rejected.detach())
    return -functional.logsigmoid(beta * margin).mean()
