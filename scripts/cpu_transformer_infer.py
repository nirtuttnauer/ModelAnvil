#!/usr/bin/env python3
"""Independent standard-library consumer for ModelAnvil CPU transformer archives.

Run outside the application: python -I infer.py . --prompt x --max-tokens 2
"""
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path


def load(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['schema_version'] != 'modelanvil.local-export.v1' or manifest['runtime'] != 'modelanvil.general-transformer-sft.v1':
        raise ValueError('Unsupported export runtime')
    files = {}
    if len(manifest['files']) > 24:
        raise ValueError('Too many archive files')
    for name, pin in manifest['files'].items():
        if Path(name).name != name or not 0 <= pin['byte_size'] <= 2 * 1024**2:
            raise ValueError('Invalid bounded archive path or size')
        path = directory / name
        if path.stat().st_size != pin['byte_size']:
            raise ValueError('File size mismatch')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ValueError('File checksum mismatch')
        files[name] = raw
    cfg = json.loads(files['config.json'])
    vocab, width, layers, heads, context = (cfg[k] for k in ('vocab_size', 'n_embd', 'n_layer', 'n_head', 'context_window'))
    if (any(type(n) is not int for n in (vocab, width, layers, heads, context)) or vocab != 260
            or not 1 <= width <= 32 or not 1 <= layers <= 4 or not 1 <= heads <= 4
            or width % heads or not 2 <= context <= 64):
        raise ValueError('Unsupported transformer dimensions')
    raw = files['model.safetensors']
    if hashlib.sha256(raw).hexdigest() != json.loads(files['weights_manifest.json'])['weights_sha256']:
        raise ValueError('Weights checksum mismatch')
    if len(raw) < 8:
        raise ValueError('Missing tensor header')
    size = struct.unpack('<Q', raw[:8])[0]
    if size > len(raw)-8 or size > 65536:
        raise ValueError('Invalid tensor header')
    header = json.loads(raw[8:8+size]); data = raw[8+size:]
    shapes = {'transformer.wte.weight': [vocab, width], 'transformer.wpe.weight': [context, width],
        'transformer.ln_f.weight': [width, 1], 'transformer.ln_f.bias': [width, 1], 'lm_head.weight': [width, vocab]}
    for i in range(layers):
        prefix = f'transformer.layers.{i}'
        for norm in ('attn_ln', 'mlp_ln'):
            shapes[f'{prefix}.{norm}.weight'] = [width, 1]; shapes[f'{prefix}.{norm}.bias'] = [width, 1]
        for projection in ('q', 'k', 'v', 'o'):
            shapes[f'{prefix}.attn.{projection}.weight'] = [width, width]
        shapes[f'{prefix}.mlp.fc1.weight'] = [width, 4*width]
        shapes[f'{prefix}.mlp.fc2.weight'] = [4*width, width]
    if set(header)-{'__metadata__'} != set(shapes):
        raise ValueError('Unsupported tensor names')
    tensors, ranges = {}, []
    for name, shape in shapes.items():
        desc = header[name]; start, end = desc['data_offsets']
        if desc['shape'] != shape or desc['dtype'] != 'F32' or not 0 <= start < end <= len(data) or end-start != math.prod(shape)*4:
            raise ValueError('Invalid tensor layout')
        flat = struct.unpack(f'<{math.prod(shape)}f', data[start:end])
        if not all(math.isfinite(v) for v in flat):
            raise ValueError('Non-finite weights')
        tensors[name] = [flat[i*shape[1]:(i+1)*shape[1]] for i in range(shape[0])]
        ranges.append((start, end))
    cursor = 0
    for start, end in sorted(ranges):
        if start != cursor:
            raise ValueError('Tensor gaps or overlaps')
        cursor = end
    if cursor != len(data):
        raise ValueError('Trailing tensor data')
    spec = json.loads(files['tokenizer_config.json'])
    if spec.get('kind') != 'byte-v1' or spec.get('vocab_size') != 260:
        raise ValueError('Unsupported tokenizer')
    return cfg, tensors, hashlib.sha256(raw).hexdigest()


def infer(cfg, tensors, prompt, count):
    width, heads = cfg['n_embd'], cfg['n_head']
    def linear(row, weight):
        return [sum(row[i]*weight[i][j] for i in range(len(row))) for j in range(len(weight[0]))]
    def norm(row, prefix):
        mean = sum(row)/len(row); variance = sum((v-mean)**2 for v in row)/len(row)
        scale = (variance+1e-5)**-0.5
        return [(v-mean)*scale*tensors[prefix+'.weight'][i][0]+tensors[prefix+'.bias'][i][0] for i,v in enumerate(row)]
    def logits(tokens):
        x = [[tensors['transformer.wte.weight'][token][c]+tensors['transformer.wpe.weight'][p][c]
              for c in range(width)] for p,token in enumerate(tokens)]
        for layer in range(cfg['n_layer']):
            prefix = f'transformer.layers.{layer}'
            normalized = [norm(row, prefix+'.attn_ln') for row in x]
            q,k,v = [[linear(row, tensors[prefix+f'.attn.{proj}.weight']) for row in normalized] for proj in ('q','k','v')]
            attended = [[0.0]*width for _ in x]; size = width//heads
            for head in range(heads):
                lo,hi = head*size,(head+1)*size
                for p in range(len(x)):
                    scores = [sum(q[p][c]*k[j][c] for c in range(lo,hi))/math.sqrt(size) for j in range(p+1)]
                    exps = [math.exp(score-max(scores)) for score in scores]; total = sum(exps)
                    for c in range(lo,hi):
                        attended[p][c] = sum(exps[j]/total*v[j][c] for j in range(p+1))
            projected = [linear(row, tensors[prefix+'.attn.o.weight']) for row in attended]
            x = [[a+b for a,b in zip(row,proj)] for row,proj in zip(x,projected)]
            normalized = [norm(row, prefix+'.mlp_ln') for row in x]
            hidden = [[0.5*v*(1+math.tanh(math.sqrt(2/math.pi)*(v+0.044715*v**3)))
                       for v in linear(row,tensors[prefix+'.mlp.fc1.weight'])] for row in normalized]
            projected = [linear(row,tensors[prefix+'.mlp.fc2.weight']) for row in hidden]
            x = [[a+b for a,b in zip(row,proj)] for row,proj in zip(x,projected)]
        return linear(norm(x[-1],'transformer.ln_f'),tensors['lm_head.weight'])
    context = [1, *[b+4 for b in prompt.encode()], 2]
    if len(context)+count > cfg['context_window']:
        raise ValueError('Prompt and output exceed the context limit')
    generated = []
    for _ in range(count):
        values = logits(context)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Non-finite output')
        next_id = max([2,*range(4,260)],key=values.__getitem__)
        generated.append(next_id); context.append(next_id)
        if next_id == 2:
            break
    return {'completion': bytes(i-4 for i in generated if i>=4).decode('utf-8',errors='replace'),
            'generated_token_ids': generated, 'runtime': 'independent_stdlib_transformer_consumer'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path); parser.add_argument('--prompt', default='x')
    parser.add_argument('--max-tokens', type=int, choices=range(1,33), default=2)
    args = parser.parse_args()
    config, weights, checksum = load(args.directory)
    print(json.dumps({**infer(config,weights,args.prompt,args.max_tokens), 'weights_sha256': checksum}))
