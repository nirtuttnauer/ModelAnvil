#!/usr/bin/env python3
"""Independent standard-library consumer for bounded CPU character SFT exports.

No Django or ModelAnvil imports. This is a reference consumer, not Hugging Face
or a production serving engine. Run: python -I scripts/cpu_character_infer.py bundle.json --prompt ab
"""
import argparse
import base64
import hashlib
import json
import math
import struct
from pathlib import Path


def infer(bundle, prompt, count):
    raw = base64.b64decode(bundle['model.safetensors.b64'], validate=True)
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != bundle['weights_manifest.json']['weights_sha256']:
        raise ValueError('Invalid weights checksum or size')
    size = struct.unpack('<Q', raw[:8])[0]
    if size > len(raw) - 8:
        raise ValueError('Invalid tensor header')
    header = json.loads(raw[8:8 + size]); data = raw[8 + size:]
    cfg = bundle['config.json']
    vocab, width, rank, alpha = (cfg[k] for k in ('vocab_size', 'n_embd', 'lora_r', 'lora_alpha'))
    if (any(type(n) is not int for n in (vocab, width, rank, alpha))
            or not 10 <= vocab <= 256 or not 1 <= width <= 16 or not 1 <= rank <= 4 or not 1 <= alpha <= 1024):
        raise ValueError('Unsupported model dimensions')
    shapes = {'transformer.wte.weight': [vocab, width], 'transformer.layers.0.lora_A.weight': [rank, width],
              'transformer.layers.0.lora_B.weight': [width, rank], 'lm_head.weight': [vocab, width]}
    if set(header) - {'__metadata__'} != set(shapes):
        raise ValueError('Unsupported tensor names')
    tensors, ranges = {}, []
    for name, shape in shapes.items():
        desc = header[name]; start, end = desc['data_offsets']
        if (desc['shape'] != shape or desc['dtype'] != 'F32' or not 0 <= start < end <= len(data)
                or end - start != math.prod(shape) * 4):
            raise ValueError('Invalid tensor layout')
        flat = struct.unpack(f'<{math.prod(shape)}f', data[start:end])
        if not all(math.isfinite(value) for value in flat):
            raise ValueError('Non-finite weights')
        tensors[name] = [flat[i * shape[1]:(i + 1) * shape[1]] for i in range(shape[0])]
        ranges.append((start, end))
    cursor = 0
    for start, end in sorted(ranges):
        if start != cursor:
            raise ValueError('Tensor gaps or overlaps')
        cursor = end
    if cursor != len(data):
        raise ValueError('Trailing tensor data')
    tokens = bundle['tokenizer_config.json']['tokens']
    if len(tokens) != vocab or tokens[:4] != ['<pad>', '<bos>', '<eos>', '<unk>'] or len(set(tokens)) != vocab or any(len(t) != 1 for t in tokens[4:]):
        raise ValueError('Invalid tokenizer')
    table = {char: i for i, char in enumerate(tokens)}
    current = table.get(prompt[-1], 3) if prompt else 1
    wte, a, b, head = (tensors[k] for k in shapes)
    generated = []
    for _ in range(count):
        x = wte[current]
        ax = [sum(a[k][j] * x[j] for j in range(width)) for k in range(rank)]
        h = [x[i] + alpha / rank * sum(b[i][k] * ax[k] for k in range(rank)) for i in range(width)]
        logits = [sum(head[v][i] * h[i] for i in range(width)) for v in range(vocab)]
        if not all(math.isfinite(value) for value in logits):
            raise ValueError('Non-finite output')
        current = max([2, *range(4, vocab)], key=logits.__getitem__)
        generated.append(current)
        if current == 2:
            break
    return {'completion': ''.join(tokens[t] for t in generated if t >= 4), 'generated_token_ids': generated,
            'weights_sha256': hashlib.sha256(raw).hexdigest(), 'runtime': 'independent_stdlib_character_consumer'}


def read_export(path):
    if not path.is_dir():
        if path.stat().st_size > 1024*1024:
            raise ValueError('Bundle exceeds supported limits')
        return json.loads(path.read_text())
    manifest = json.loads((path / 'manifest.json').read_text())
    if manifest['schema_version'] not in ('modelanvil.local-export.v1', 'modelanvil.local-export.v2') or len(manifest['files']) > 24:
        raise ValueError('Invalid export manifest')
    files = {}
    for name, pin in manifest['files'].items():
        if Path(name).name != name or not 0 <= pin['byte_size'] <= 2*1024**2:
            raise ValueError('Invalid export path or size')
        file = path / name
        if file.stat().st_size != pin['byte_size']:
            raise ValueError('File size mismatch')
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ValueError('File checksum mismatch')
        files[name] = raw
    bundle = {name: json.loads(raw) for name, raw in files.items() if name.endswith('.json')}
    bundle['model.safetensors.b64'] = base64.b64encode(files['model.safetensors']).decode()
    return bundle


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path); parser.add_argument('--prompt', default='')
    parser.add_argument('--max-tokens', type=int, choices=range(1, 33), default=8)
    args = parser.parse_args()
    if len(args.prompt) > 4096:
        parser.error('Bundle or prompt exceeds supported limits')
    print(json.dumps(infer(read_export(args.bundle), args.prompt, args.max_tokens)))
