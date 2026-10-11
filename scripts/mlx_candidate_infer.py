"""Offline MLX four-bit adapter consumer, independent of ModelAnvil and Django."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

QUANTIZATION = {'group_size': 32, 'bits': 4, 'mode': 'affine'}
LORA = {'rank': 8, 'scale': 2.0, 'dropout': 0.0, 'keys': ['self_attn.q_proj', 'self_attn.v_proj']}


def load_candidate(directory, seed=42, training=False):
    import mlx.core as mx
    import mlx.nn as nn
    from mlx.utils import tree_flatten
    from mlx_lm.utils import load_model, load_tokenizer
    from mlx_lm.tuner.utils import linear_to_lora_layers
    directory = Path(directory)
    for name in ('model.safetensors', 'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'):
        if not (directory / name).is_file():
            raise ValueError('The complete local model and tokenizer snapshot is required.')
    config = json.loads((directory / 'config.json').read_text())
    dimensions = {'hidden_size': 576, 'num_hidden_layers': 30, 'intermediate_size': 1536, 'num_attention_heads': 9, 'num_key_value_heads': 3, 'vocab_size': 49152, 'tie_word_embeddings': True}
    if config.get('model_type') != 'llama' or any(config.get(key) != value for key, value in dimensions.items()):
        raise ValueError('This adapter consumer supports the pinned SmolLM2-135M dimensions only.')
    if config.get('quantization') not in (None, QUANTIZATION) or config.get('quantization_config'):
        raise ValueError('Use the four-bit affine group-32 profile.')
    model, config = load_model(directory, strict=True)
    model.apply(lambda p: p.astype(mx.float32) if mx.issubdtype(p.dtype, mx.floating) else p)
    if not config.get('quantization'):
        nn.quantize(model, **QUANTIZATION, class_predicate=lambda _, layer: isinstance(layer, nn.Linear))
        config['quantization'] = QUANTIZATION
    model.freeze()
    mx.random.seed(seed)
    linear_to_lora_layers(model, len(model.layers), LORA)
    expected = dict(tree_flatten(model.trainable_parameters()))
    if len(expected) != 120 or any(not n.endswith(('.lora_a', '.lora_b')) for n in expected):
        raise ValueError('Only rank-eight q/v adapter tensors may be trainable.')
    adapter_config = {'num_layers': 30, 'fine_tune_type': 'lora', 'lora_parameters': LORA}
    if (directory / 'adapters.safetensors').exists():
        if json.loads((directory / 'adapter_config.json').read_text()) != adapter_config:
            raise ValueError('Adapter configuration changed.')
        saved = mx.load(str(directory / 'adapters.safetensors'))
        if set(saved) != set(expected) or any(saved[n].shape != p.shape or saved[n].dtype != p.dtype for n, p in expected.items()):
            raise ValueError('Adapter keys, shapes or precision changed.')
        model.load_weights(list(saved.items()), strict=False)
    for name, parameter in tree_flatten(model.parameters()):
        if mx.issubdtype(parameter.dtype, mx.floating) and not mx.all(mx.isfinite(parameter)).item():
            raise ValueError('Model contains non-finite tensors.')
    mx.eval(model.parameters())
    model.train(training)
    tokenizer = load_tokenizer(directory, {'local_files_only': True, 'trust_remote_code': False}, eos_token_ids=config.get('eos_token_id'))
    return model, tokenizer, config, adapter_config


def completion(model, tokenizer, prompt, count):
    import mlx.core as mx
    ids = tokenizer.encode(prompt, add_special_tokens=True)
    if not 1 <= len(ids) <= 128 or not 1 <= count <= 32:
        raise ValueError('Use 1–128 input tokens and 1–32 output tokens.')
    generated = []
    for _ in range(count):
        token = mx.argmax(model(mx.array([ids + generated]))[0, -1]).item()
        generated.append(token)
        if token in tokenizer.eos_token_ids:
            break
    return generated, tokenizer.decode(generated, skip_special_tokens=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--device', choices=['mlx:0', 'cpu'], default='mlx:0')
    args = parser.parse_args()
    import mlx.core as mx
    if args.device == 'mlx:0' and not mx.metal.is_available():
        raise ValueError('Metal is unavailable; CPU fallback is refused.')
    mx.set_default_device(mx.gpu if args.device == 'mlx:0' else mx.cpu)
    model, tokenizer, _, _ = load_candidate(args.directory)
    ids, text = completion(model, tokenizer, 'Once upon a time', 8)
    path = args.directory / 'adapters.safetensors'
    print(json.dumps({'prompt': 'Once upon a time', 'completion': text, 'generated_token_ids': ids,
        'weights_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'execution': {'backend': args.device.split(':')[0], 'device_residency_checked': True},
        'consumer_imported_modelanvil_or_django': any(n == 'django' or n.startswith('modelanvil') for n in sys.modules)}))


if __name__ == '__main__':
    main()
