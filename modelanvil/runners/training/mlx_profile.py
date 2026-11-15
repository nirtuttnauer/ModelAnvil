"""Validated memory and throughput profile for native MLX adapter training.

Pure MLX and Python, with no Django imports, so the controlled benchmark
(scripts/benchmark_mlx_training.py) measures the same batching, forward pass,
loss and optimizer code that the worker runtime executes.

Every optimization is explicit and pinned with the run. Nothing is selected
automatically, and unsupported or incompatible combinations raise ValueError
before a model, tokenizer or device is touched.
"""
from __future__ import annotations

import math

PROFILE_VERSION = 'modelanvil.mlx-optimization-profile.v1'
DEFAULT_PROFILE = {'compute_precision': 'fp32', 'gradient_checkpointing': False, 'batch_samples': 1,
    'sequence_layout': 'padded', 'attention_kernel': 'mlx_fast_sdpa', 'optimizer': 'adamw'}
MAX_BATCH_SAMPLES = 8
PAD_TOKEN_ID = 0  # Never supervised: padded targets carry zero loss weight.
# Kept literally equal to hf_runtime.OPTIMIZER (asserted by tests) so the default profile is unchanged.
ADAMW = {'algorithm': 'adamw', 'learning_rate': 0.00002, 'beta1': 0.9, 'beta2': 0.999,
    'epsilon': 1e-8, 'weight_decay': 0.0}
# Factored second moment, no first moment, fixed learning rate: no relative-step schedule or parameter scaling.
ADAFACTOR = {'algorithm': 'adafactor', 'learning_rate': 0.00002, 'beta1': None, 'decay_rate': -0.8,
    'clip_threshold': 1.0, 'epsilon': [1e-30, 0.001], 'weight_decay': 0.0,
    'relative_step': False, 'scale_parameter': False, 'warmup_init': False}
OPTIMIZERS = {'adamw': ADAMW, 'adafactor': ADAFACTOR}
PRECISIONS = ('fp32', 'bf16')
LAYOUTS = ('padded', 'packed')
ATTENTION_KERNELS = ('mlx_fast_sdpa', 'mlx_fast_sdpa_force_fused')
FP8_REFUSAL = ('FP8 training is not supported on this hardware: MLX 0.32.3 offers FP8 only as uint8 storage '
    'conversion (mx.to_fp8/mx.from_fp8), with no FP8 matmul or training dtype on Apple GPUs. Select fp32 or bf16.')
FP16_REFUSAL = ('FP16 compute is not qualified: it needs dynamic loss scaling, which this runtime does not implement. '
    'Select bf16 or fp32.')
ATTENTION_REFUSAL = ('MLX attention always runs mx.fast.scaled_dot_product_attention; eager, FlashAttention, xformers and '
    'SDPA-backend switches belong to other frameworks. Select mlx_fast_sdpa or mlx_fast_sdpa_force_fused.')
OPTIMIZER_REFUSAL = ('Select optimizer adamw or adafactor. 8-bit and paged optimizers depend on CUDA bitsandbytes and '
    'are not available for MLX.')
# Per-step metrics carry these short codes; the reasons are pinned once in the contract.
UNAVAILABLE_METRICS = {'peak_reserved_bytes': 'not_exposed_by_mlx', 'gpu_utilization_percent': 'not_exposed_by_mlx'}
UNAVAILABLE_REASONS = {'not_exposed_by_mlx': 'MLX 0.32.3 exposes active, peak-active and current cache bytes, but no '
    'peak reserved-pool or GPU utilization counter, and macOS GPU busy time is not sampled. No value is estimated.'}
CONTRACT = {'version': PROFILE_VERSION, 'default': DEFAULT_PROFILE, 'compute_precisions': list(PRECISIONS),
    'refused_precisions': {'fp16': FP16_REFUSAL, 'fp8': FP8_REFUSAL}, 'sequence_layouts': list(LAYOUTS),
    'max_batch_samples': MAX_BATCH_SAMPLES, 'attention_kernels': list(ATTENTION_KERNELS), 'optimizers': OPTIMIZERS,
    'adapter_and_optimizer_precision': 'fp32',
    'bf16': 'quantization scales/biases and block matmul inputs BF16; residual stream, norms, embeddings, logits FP32',
    'loss': 'mean cross-entropy over supervised next-token pairs in the step, FP32 logits',
    'packing': 'block-diagonal causal mask; boundary pairs unsupervised; relative RoPE positions',
    'padding': 'right padding with causal mask; padded targets unsupervised',
    'gradient_checkpointing': 'mx.checkpoint per transformer block', 'unavailable_metrics': UNAVAILABLE_METRICS,
    'unavailable_reasons': UNAVAILABLE_REASONS}


def validate_profile(value=None):
    """Return the complete pinned profile, or raise ValueError naming the refused setting."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('Provide hyperparameters.optimization as an object.')
    unknown = set(value) - set(DEFAULT_PROFILE)
    if unknown:
        raise ValueError('Unsupported optimization settings: ' + ', '.join(sorted(map(str, unknown)))
            + '. Choose from ' + ', '.join(DEFAULT_PROFILE) + '.')
    profile = {**DEFAULT_PROFILE, **value}
    precision = profile['compute_precision']
    if not isinstance(precision, str):
        raise ValueError('Select compute_precision fp32 or bf16.')
    folded = precision.lower().replace('-', '').replace('_', '')
    if 'fp8' in folded or 'float8' in folded or folded.startswith(('e4m3', 'e5m2')):
        raise ValueError(FP8_REFUSAL)
    if folded in ('fp16', 'float16', 'half', 'f16'):
        raise ValueError(FP16_REFUSAL)
    if precision not in PRECISIONS:
        raise ValueError('Select compute_precision fp32 or bf16.')
    if type(profile['gradient_checkpointing']) is not bool:
        raise ValueError('Set gradient_checkpointing to true or false.')
    samples = profile['batch_samples']
    if type(samples) is not int or not 1 <= samples <= MAX_BATCH_SAMPLES:
        raise ValueError(f'Select batch_samples from 1 to {MAX_BATCH_SAMPLES} whole samples per optimizer step.')
    if profile['sequence_layout'] not in LAYOUTS:
        raise ValueError('Select sequence_layout padded or packed; samples are never truncated or split.')
    if profile['sequence_layout'] == 'packed' and samples < 2:
        raise ValueError('Packing needs batch_samples of at least 2; a single sample per step is neither padded nor packed.')
    if profile['attention_kernel'] not in ATTENTION_KERNELS:
        raise ValueError(ATTENTION_REFUSAL)
    if profile['optimizer'] not in OPTIMIZERS:
        raise ValueError(OPTIMIZER_REFUSAL)
    return profile


def step_samples(samples, step, batch_samples):
    """Manifest-order samples for one optimizer step; one sample per step reproduces the original cursor."""
    start = (step - 1) * batch_samples
    return [samples[(start + offset) % len(samples)] for offset in range(batch_samples)]


def build_batch(samples, layout):
    """Encode whole samples so no loss or attention crosses a sample boundary."""
    import mlx.core as mx
    sequences = [list(sample['token_ids']) for sample in samples]
    if not sequences or any(len(tokens) < 2 for tokens in sequences):
        raise ValueError('Each training sample needs at least two tokens.')
    pairs = sum(len(tokens) - 1 for tokens in sequences)
    ids = [sample['sample_id'] for sample in samples]
    if layout == 'padded':
        width = max(len(tokens) for tokens in sequences) - 1
        pad = [width - len(tokens) + 1 for tokens in sequences]
        inputs = [tokens[:-1] + [PAD_TOKEN_ID] * extra for tokens, extra in zip(sequences, pad)]
        targets = [tokens[1:] + [PAD_TOKEN_ID] * extra for tokens, extra in zip(sequences, pad)]
        weights = [[1.0] * (len(tokens) - 1) + [0.0] * extra for tokens, extra in zip(sequences, pad)]
        # Right padding under a causal mask: real positions never attend to later padding.
        mask = 'causal' if width > 1 else None
        positions = len(sequences) * width
    elif layout == 'packed':
        row = [token for tokens in sequences for token in tokens]
        segment = [index for index, tokens in enumerate(sequences) for _ in tokens]
        inputs, targets = [row[:-1]], [row[1:]]
        # The pair joining two samples is never supervised.
        weights = [[1.0 if segment[j] == segment[j + 1] else 0.0 for j in range(len(row) - 1)]]
        segments = mx.array(segment[:-1])
        order = mx.arange(len(row) - 1)
        mask = (segments[:, None] == segments[None, :]) & (order[:, None] >= order[None, :])
        positions = len(row) - 1
    else:
        raise ValueError('Select sequence_layout padded or packed.')
    return {'inputs': mx.array(inputs), 'targets': mx.array(targets), 'weights': mx.array(weights, dtype=mx.float32),
        'mask': mask, 'pairs': pairs, 'positions': positions, 'padding_positions': positions - pairs - (
            len(sequences) - 1 if layout == 'packed' else 0), 'sample_ids': ids}


def _attention(attention, x, mask, force_fused):
    # Same operations as mlx_lm 0.29.1 llama.Attention without a cache; only the kernel option differs.
    import mlx.core as mx
    batch, length, _ = x.shape
    queries = attention.q_proj(x).reshape(batch, length, attention.n_heads, -1).transpose(0, 2, 1, 3)
    keys = attention.k_proj(x).reshape(batch, length, attention.n_kv_heads, -1).transpose(0, 2, 1, 3)
    values = attention.v_proj(x).reshape(batch, length, attention.n_kv_heads, -1).transpose(0, 2, 1, 3)
    queries, keys = attention.rope(queries), attention.rope(keys)
    output = mx.fast.scaled_dot_product_attention(queries, keys, values, scale=attention.scale, mask=mask,
        **({'force_fused': True} if force_fused else {}))
    return attention.o_proj(output.transpose(0, 2, 1, 3).reshape(batch, length, -1))


def _block(layer, h, mask, force_fused, low_precision):
    # Same residual structure as mlx_lm 0.29.1 llama.TransformerBlock. With BF16 compute the attention and MLP
    # matmuls take BF16 inputs while the residual stream and norms stay FP32.
    if low_precision is None:
        h = h + _attention(layer.self_attn, layer.input_layernorm(h), mask, force_fused)
        return h + layer.mlp(layer.post_attention_layernorm(h))
    h = h + _attention(layer.self_attn, layer.input_layernorm(h).astype(low_precision), mask, force_fused).astype(h.dtype)
    return h + layer.mlp(layer.post_attention_layernorm(h).astype(low_precision)).astype(h.dtype)


def _checkpointed_block(layer, h, mask, force_fused, low_precision):
    import mlx.core as mx
    def block(parameters, h):
        layer.update(parameters)
        return _block(layer, h, mask, force_fused, low_precision)
    return mx.checkpoint(block)(layer.trainable_parameters(), h)


def forward(model, inputs, mask, profile):
    """Logits for the pinned tied-embedding llama; per-block checkpointing recomputes activations in backward."""
    import mlx.core as mx
    inner = model.model
    h = inner.embed_tokens(inputs)
    force_fused = profile['attention_kernel'] == 'mlx_fast_sdpa_force_fused'
    low_precision = mx.bfloat16 if profile['compute_precision'] == 'bf16' else None
    block = _checkpointed_block if profile['gradient_checkpointing'] else _block
    for layer in inner.layers:
        h = block(layer, h, mask, force_fused, low_precision)
    return inner.embed_tokens.as_linear(inner.norm(h))


def batch_loss(model, batch, profile, *, reduction='mean'):
    import mlx.core as mx
    import mlx.nn as nn
    logits = forward(model, batch['inputs'], batch['mask'], profile).astype(mx.float32)
    losses = nn.losses.cross_entropy(logits, batch['targets'], reduction='none') * batch['weights']
    return losses if reduction == 'none' else losses.sum() / batch['pairs']


def prepare_model(model, profile):
    """For BF16 compute, cast the frozen quantization scales/biases; adapters stay FP32 master weights."""
    import mlx.core as mx
    import mlx.nn as nn
    from mlx.utils import tree_flatten
    if not hasattr(model, 'model') or not hasattr(model.model, 'embed_tokens') or 'lm_head' in model:
        raise ValueError('The optimization profile supports the pinned tied-embedding llama only.')
    if any(getattr(layer, 'use_sliding', False) for layer in model.model.layers):
        raise ValueError('The optimization profile supports full-attention layers only.')
    trainable = dict(tree_flatten(model.trainable_parameters()))
    if any(parameter.dtype != mx.float32 for parameter in trainable.values()):
        raise ValueError('Adapter master weights must be FP32.')
    if profile['compute_precision'] == 'bf16':
        # Embeddings, norms and logits stay FP32: an all-BF16 residual stream moved the fixture loss by 1.7%.
        for _, module in model.named_modules():
            if isinstance(module, nn.QuantizedLinear):
                module.scales, module.biases = module.scales.astype(mx.bfloat16), module.biases.astype(mx.bfloat16)
    mx.eval(model.parameters())
    return model


def make_optimizer(name):
    import mlx.optimizers as optim
    spec = OPTIMIZERS[name]
    if name == 'adamw':
        return optim.AdamW(learning_rate=spec['learning_rate'], betas=(spec['beta1'], spec['beta2']),
            eps=spec['epsilon'], weight_decay=spec['weight_decay'])
    return optim.Adafactor(learning_rate=spec['learning_rate'], eps=tuple(spec['epsilon']),
        clip_threshold=spec['clip_threshold'], decay_rate=spec['decay_rate'], beta_1=spec['beta1'],
        weight_decay=spec['weight_decay'], scale_parameter=spec['scale_parameter'],
        relative_step=spec['relative_step'], warmup_init=spec['warmup_init'])


def value_and_grad(model, batch, profile):
    import mlx.nn as nn
    return nn.value_and_grad(model, lambda: batch_loss(model, batch, profile))()


def train_step(model, optimizer, batch, profile):
    """One optimizer update; returns the pre-update loss and the FP32 gradient norm."""
    import mlx.core as mx
    from mlx.utils import tree_flatten
    loss, gradients = value_and_grad(model, batch, profile)
    squared = sum(mx.sum(g.astype(mx.float32) * g.astype(mx.float32)) for _, g in tree_flatten(gradients))
    mx.eval(loss, squared)
    loss_value, norm_squared = loss.item(), squared.item()
    # A NaN or infinite gradient element makes the squared norm non-finite.
    if not math.isfinite(loss_value) or not math.isfinite(norm_squared):
        raise ValueError('MLX adapter loss or gradients are non-finite.')
    optimizer.update(model, gradients)
    mx.eval(model.parameters(), optimizer.state)
    return loss_value, math.sqrt(norm_squared)


def state_bytes(tree):
    from mlx.utils import tree_flatten
    return sum(value.nbytes for _, value in tree_flatten(tree) if hasattr(value, 'nbytes'))
