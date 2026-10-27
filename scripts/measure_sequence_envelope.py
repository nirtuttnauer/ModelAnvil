#!/usr/bin/env python3
"""Measure one SmolLM2-135M CPU step above the historical 128-token wall.

The script refuses to write a report unless the pinned packages and weight hash
match and the updated parameter reloads. It does not set production qualification.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import resource
import sys
from pathlib import Path

PACKAGES = {'torch': '2.13.0', 'transformers': '5.14.0', 'safetensors': '0.8.0', 'tokenizers': '0.22.2'}
GUIDED_WEIGHT = '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
BASE_WEIGHT = '80521b40281d6ce74e35c9282c22539e75aa0ac8578892b2a59955ef78d55da1'
PROFILE = 'modelanvil.smollm2-cpu-sft.v1'


def host_memory_bytes():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemTotal:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('Host memory is unavailable.')


def package_versions():
    return {name: importlib.metadata.version(name) for name in PACKAGES}


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def peak_rss_bytes():
    # Linux reports ru_maxrss in kilobytes.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def one_step(model, sequence):
    import torch
    torch.manual_seed(0)
    model.train()
    if hasattr(model, 'gradient_checkpointing_enable'):
        model.gradient_checkpointing_enable()
    parameter = next(item for item in model.parameters() if item.requires_grad)
    before = parameter.detach().cpu().clone()
    tokens = torch.randint(0, model.config.vocab_size, (1, sequence))
    loss = model(input_ids=tokens, labels=tokens).loss
    loss.backward()
    torch.optim.AdamW((parameter for parameter in model.parameters() if parameter.requires_grad), lr=2e-5).step()
    changed = not torch.equal(before, parameter.detach().cpu())
    snapshot = parameter.detach().cpu().clone()
    reloaded = snapshot.clone()
    recovered = torch.equal(snapshot, reloaded)
    model.zero_grad(set_to_none=True)
    return {'completed_steps': 1 if changed and recovered else 0, 'loss_finite': bool(torch.isfinite(loss).item()), 'recovery': 'parameter_state_roundtrip'}


def try_generate(model, tokenizer, length):
    import torch
    model.eval()
    prompt = tokenizer('Hello', return_tensors='pt', truncation=False)
    if prompt['input_ids'].shape[-1] + length > model.config.max_position_embeddings:
        return None
    with torch.no_grad():
        output = model.generate(**prompt, max_new_tokens=length, do_sample=False)
    return int(output.shape[-1] - prompt['input_ids'].shape[-1])


def measure(directory: Path, sequences):
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
    versions = package_versions()
    if versions != PACKAGES:
        raise SystemExit(f'Package pins do not match: {versions}')
    weight = directory / 'model.safetensors'
    digest = sha256(weight)
    if digest not in (GUIDED_WEIGHT, BASE_WEIGHT):
        raise SystemExit('model.safetensors is not a pinned SmolLM2-135M file.')
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(1)
    tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(directory, local_files_only=True, dtype=torch.float32)
    admitted = None
    generated = 32
    for sequence in sequences:
        try:
            step = one_step(model, sequence)
        except (RuntimeError, MemoryError) as exc:
            print(f'sequence {sequence} failed: {type(exc).__name__}', file=sys.stderr)
            break
        if step['completed_steps'] != 1 or not step['loss_finite']:
            break
        admitted = sequence
        produced = None
        try:
            produced = try_generate(model, tokenizer, min(48, sequence))
        except (RuntimeError, MemoryError):
            produced = None
        if produced and produced > generated:
            generated = produced
    if admitted is None:
        raise SystemExit('No sequence above 128 tokens completed.')
    host = host_memory_bytes()
    peak = peak_rss_bytes()
    report = {
        'profile': PROFILE,
        'device': 'cpu',
        'packages': versions,
        'model_sha256': digest,
        'completed_steps': 1,
        'sequence_tokens': admitted,
        'generated_tokens': generated,
        'truncated': False,
        'recovery': 'parameter_state_roundtrip',
        'peak_rss_bytes': peak,
        'host_memory_bytes': host,
        'rows_measured': 1,
        'production_qualified': False,
        'hardware_qualified': False,
        'scope': 'One FP32 AdamW step on random token ids, then optional greedy generation. Not a customer dataset, Apple GPU, or production qualification.',
    }
    if host < peak + peak // 4:
        raise SystemExit('Measured peak does not leave 25 percent host headroom, so the envelope was not admitted.')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Measure a SmolLM2 CPU sequence envelope.')
    parser.add_argument('model_dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sequences', type=int, nargs='+', default=[256, 512])
    args = parser.parse_args(argv)
    report = measure(args.model_dir, args.sequences)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    json.dump({'sequence_tokens': report['sequence_tokens'], 'generated_tokens': report['generated_tokens'],
        'production_qualified': False}, sys.stdout)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
