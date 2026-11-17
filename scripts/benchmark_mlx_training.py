"""Controlled baseline-vs-optimized benchmark for native MLX adapter training on one Apple GPU.

Every configuration trains the pinned SmolLM2-135M four-bit adapter recipe from the same seed
on the same pinned corpus, with the same samples in the same order, the same supervised token
count and the same measurement window. Each measurement runs in a fresh subprocess so allocator
state never carries over. The training code is modelanvil.runners.training.mlx_profile, the
module the worker runtime executes; no Django state or database is used.

Measured: wall time and supervised tokens/second over the window, MLX peak active ("allocated")
bytes, resident bytes before the window, optimizer-state bytes and held-out loss scored by an
FP32 mlx_lm forward pass. Peak reserved bytes and GPU utilization are recorded as null with the
reason: MLX exposes neither. Nothing is estimated. Results qualify this Mac only.

Run behind the host compute lock, into a new directory:
  python scripts/benchmark_mlx_training.py --model-dir /path/to/smollm2-135m --output NEW_DIR
"""
from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modelanvil.runners.training import mlx_profile as profiles  # noqa: E402  (pure MLX, no Django)

CORPUS_COMMIT = '0cbd8307299acdf6f5690d2f6c5936246e7ec04e'
SEED = 42
TRAIN_SAMPLES, HELD_OUT_SAMPLES = 96, 32
HELD_OUT_TOLERANCE = 0.01  # Relative held-out loss difference allowed against the baseline.
EQUIVALENCE_LOSS_TOLERANCE = 1e-3  # Max per-step relative training-loss deviation for exact reformulations.
EQUIVALENCE_UPDATE_COSINE = 0.999  # Minimum cosine between learned weight updates for exact reformulations.
BASELINE = {**profiles.DEFAULT_PROFILE, 'batch_samples': 8}
CONFIGS = {
    'baseline': BASELINE,
    'gradient_checkpointing': {**BASELINE, 'gradient_checkpointing': True},
    'bf16_compute': {**BASELINE, 'compute_precision': 'bf16'},
    'packed': {**BASELINE, 'sequence_layout': 'packed'},
    'adafactor': {**BASELINE, 'optimizer': 'adafactor'},
    'force_fused_attention': {**BASELINE, 'attention_kernel': 'mlx_fast_sdpa_force_fused'},
    'low_memory': {**BASELINE, 'compute_precision': 'bf16', 'gradient_checkpointing': True, 'optimizer': 'adafactor'},
    'low_memory_packed': {**BASELINE, 'compute_precision': 'bf16', 'gradient_checkpointing': True, 'optimizer': 'adafactor',
        'sequence_layout': 'packed'},
    # Added after the first run showed Adafactor failing its gate: the combinations of options that passed.
    'bf16_checkpointing': {**BASELINE, 'compute_precision': 'bf16', 'gradient_checkpointing': True},
    'bf16_checkpointing_packed': {**BASELINE, 'compute_precision': 'bf16', 'gradient_checkpointing': True, 'sequence_layout': 'packed'},
    # Same samples and tokens, eight times as many smaller updates: a throughput reference, not a quality comparison.
    'reference_one_sample_per_step': profiles.DEFAULT_PROFILE,
}
EXACT_REFORMULATIONS = ('gradient_checkpointing', 'packed', 'force_fused_attention')
NOT_QUALITY_COMPARABLE = ('reference_one_sample_per_step',)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned_model_hashes():
    # Read the runtime's pinned hashes without importing Django.
    tree = ast.parse((ROOT / 'modelanvil/runners/training/hf_runtime.py').read_text())
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('SOURCE', 'FILE_HASHES')}
    return values['SOURCE'], values['FILE_HASHES']


def build_corpus(model_dir, output):
    """Deterministic prose windows from pinned repository docs; held-out files never enter training."""
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(model_dir / 'tokenizer.json'))
    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=ROOT)
    names = sorted(n for n in git('ls-tree', '-r', '--name-only', CORPUS_COMMIT, 'docs/engineering').decode().splitlines()
        if n.endswith('.md') and '/verification/' not in n and '/qualification-reports/' not in n)
    train, held_out, sources = [], [], []
    for index, name in enumerate(names):
        raw = git('show', f'{CORPUS_COMMIT}:{name}')
        split = 'held_out' if index % 5 == 4 else 'train'
        sources.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'split': split})
        for number, paragraph in enumerate(re.split(r'\n\s*\n', raw.decode())):
            words = paragraph.split()
            if not paragraph[:1].isalpha() or len(words) < 12 or '|' in paragraph or '`' in paragraph:
                continue
            words = words[:96]
            while len(tokenizer.encode(' '.join(words)).ids) > 128:
                words.pop()
            text = ' '.join(words)
            ids = tokenizer.encode(text).ids
            row = {'sample_id': f'{name}#{number}', 'split': split, 'text': text, 'token_ids': ids}
            (held_out if split == 'held_out' else train).append(row)
    if len(train) < TRAIN_SAMPLES or len(held_out) < HELD_OUT_SAMPLES:
        raise ValueError('The pinned corpus commit has too few prose paragraphs.')
    # Interleave files so every step mixes sources; the order is fixed by the sorted names.
    train = sorted(train, key=lambda r: (int(r['sample_id'].rsplit('#', 1)[1]), r['sample_id']))[:TRAIN_SAMPLES]
    held_out = sorted(held_out, key=lambda r: (int(r['sample_id'].rsplit('#', 1)[1]), r['sample_id']))[:HELD_OUT_SAMPLES]
    # Digests sit under a 'sha256' key, never on a line keyed by a file name: scanners read "token...": <hex> as a secret.
    corpus = {'commit': CORPUS_COMMIT, 'tokenizer': {'file': 'tokenizer.json', 'sha256': sha256(model_dir / 'tokenizer.json')},
        'train': train, 'held_out': held_out}
    path = output / 'corpus.json'
    path.write_text(json.dumps(corpus, indent=1, sort_keys=True) + '\n')
    lengths = [len(r['token_ids']) for r in train]
    return path, {'path': path.name, 'sha256': sha256(path), 'commit': CORPUS_COMMIT, 'sources': sources,
        'train_samples': len(train), 'held_out_samples': len(held_out),
        'train_tokens_min_median_max': [min(lengths), statistics.median(lengths), max(lengths)],
        'held_out_source_files': [s['path'] for s in sources if s['split'] == 'held_out'],
        'selection': 'Prose paragraphs (>=12 words, no tables or code) from docs/engineering/*.md at the commit, at most 96 words '
            'and 128 tokenizer tokens; every fifth sorted file is held out; first-paragraph-index order, then path.'}


def environment(model_dir):
    import mlx.core as mx
    def run(*command):
        try:
            return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    source, hashes = pinned_model_hashes()
    observed = {name: sha256(model_dir / name) for name in hashes}
    if observed != hashes:
        raise ValueError('The model directory does not match the pinned SmolLM2-135M file hashes.')
    status = run('git', '-C', str(ROOT), 'status', '--porcelain', '--', 'modelanvil', 'scripts')
    info = mx.device_info()
    return {'macos': platform.mac_ver()[0], 'macos_build': run('sw_vers', '-buildVersion'),
        'chip': run('sysctl', '-n', 'machdep.cpu.brand_string'), 'host_memory_bytes': int(run('sysctl', '-n', 'hw.memsize') or 0),
        'python': platform.python_version(), 'machine': platform.machine(),
        'packages': {name: importlib.metadata.version(name) for name in ('mlx', 'mlx-metal', 'mlx-lm', 'tokenizers')},
        'mlx_device': {key: info.get(key) for key in ('device_name', 'architecture', 'memory_size', 'max_recommended_working_set_size', 'max_buffer_length')},
        'metal_available': mx.metal.is_available(), 'default_device': str(mx.default_device()),
        'git_sha': run('git', '-C', str(ROOT), 'rev-parse', 'HEAD'), 'code_dirty': bool(status),
        'model_source': source, 'model_files': [{'file': name, 'sha256': digest} for name, digest in sorted(observed.items())],
        'code_sha256': {path: sha256(ROOT / path) for path in ('modelanvil/runners/training/mlx_profile.py',
            'scripts/mlx_candidate_infer.py', 'scripts/benchmark_mlx_training.py')}}


def held_out_loss(model, samples):
    """Token-weighted mean next-token loss through the library forward pass (independent of mlx_profile)."""
    import mlx.core as mx
    import mlx.nn as nn
    total, count = 0.0, 0
    for sample in samples:
        ids = mx.array([sample['token_ids']])
        losses = nn.losses.cross_entropy(model(ids[:, :-1]).astype(mx.float32), ids[:, 1:], reduction='sum')
        total += losses.item(); count += ids.shape[1] - 1
    return total / count


def measure(config, args):
    """One isolated measurement (subprocess)."""
    import mlx.core as mx
    from mlx.utils import tree_flatten
    from scripts.mlx_candidate_infer import load_candidate
    if not mx.metal.is_available():
        raise ValueError('Metal is unavailable; this benchmark refuses CPU execution.')
    mx.set_default_device(mx.gpu)
    profile = profiles.validate_profile(CONFIGS[config], allow_unqualified=True)
    corpus = json.loads(Path(args.corpus).read_text())
    train, held_out = corpus['train'], corpus['held_out']
    scale = BASELINE['batch_samples'] // profile['batch_samples']
    steps, warmup = args.steps * scale, args.warmup * scale
    model, _, _, _ = load_candidate(args.model_dir, SEED, training=True)
    before = held_out_loss(model, held_out)
    profiles.prepare_model(model, profile)
    optimizer = profiles.make_optimizer(profile['optimizer'])
    records, window_started, resident = [], None, None
    for step in range(1, steps + 1):
        if step == warmup + 1:
            resident = mx.get_active_memory()
            window_started = time.perf_counter()
        batch = profiles.build_batch(profiles.step_samples(train, step, profile['batch_samples']), profile['sequence_layout'])
        mx.reset_peak_memory()
        started = time.perf_counter()
        loss, norm = profiles.train_step(model, optimizer, batch, profile)
        records.append({'step': step, 'loss': loss, 'gradient_norm': norm, 'supervised_tokens': batch['pairs'],
            'computed_positions': batch['positions'], 'padding_positions': batch['padding_positions'],
            'step_seconds': time.perf_counter() - started, 'peak_allocated_bytes': mx.get_peak_memory(),
            'active_bytes_after': mx.get_active_memory()})
    window_seconds = time.perf_counter() - window_started
    window = records[warmup:]
    adapters = dict(tree_flatten(model.trainable_parameters()))
    optimizer_bytes = profiles.state_bytes(optimizer.state)
    cache_bytes = mx.get_cache_memory()
    mx.save_safetensors(str(Path(args.adapters) / f'{config}.safetensors'), adapters)
    model = optimizer = None
    gc.collect(); mx.clear_cache()
    evaluator, _, _, _ = load_candidate(args.model_dir, SEED, training=False)
    evaluator.load_weights(list(adapters.items()), strict=False)
    after = held_out_loss(evaluator, held_out)
    tokens = sum(r['supervised_tokens'] for r in window)
    return {'config': config, 'profile': profile, 'repeat': args.repeat, 'steps': steps, 'warmup_steps': warmup,
        'window': {'steps': len(window), 'first_sample': warmup * profile['batch_samples'],
            'samples': len(window) * profile['batch_samples'], 'supervised_tokens': tokens,
            'computed_positions': sum(r['computed_positions'] for r in window),
            'padding_positions': sum(r['padding_positions'] for r in window),
            'wall_seconds': window_seconds, 'step_seconds_sum': sum(r['step_seconds'] for r in window),
            'tokens_per_second': tokens / window_seconds,
            'peak_allocated_bytes': max(r['peak_allocated_bytes'] for r in window),
            'resident_bytes_before_window': resident,
            'peak_reserved_bytes': None, 'gpu_utilization_percent': None,
            'unavailable_metrics': profiles.UNAVAILABLE_METRICS},
        'optimizer_state_bytes': optimizer_bytes, 'cache_bytes_at_end': cache_bytes,
        'held_out_loss_before_training': before, 'held_out_loss': after, 'steps_detail': records}


def update_cosine(adapters, config, reference, scale):
    """Cosine between learned weight updates scale*A@B (B starts at zero), concatenated over all adapters."""
    import mlx.core as mx
    first, second = mx.load(str(adapters / f'{config}.safetensors')), mx.load(str(adapters / f'{reference}.safetensors'))
    dot = left = right = 0.0
    for name in first:
        if not name.endswith('.lora_a'):
            continue
        b = name[:-len('lora_a')] + 'lora_b'
        u, v = scale * first[name] @ first[b], scale * second[name] @ second[b]
        dot += mx.sum(u * v).item(); left += mx.sum(u * u).item(); right += mx.sum(v * v).item()
    return dot / math.sqrt(left * right)


def summarize(results, adapters):
    from scripts.mlx_candidate_infer import LORA
    by_config = {}
    for result in results:
        by_config.setdefault(result['config'], []).append(result)
    baseline = by_config['baseline'][0]
    baseline_loss = baseline['held_out_loss']
    rows = {}
    for config, runs in by_config.items():
        walls = [r['window']['wall_seconds'] for r in runs]
        rates = [r['window']['tokens_per_second'] for r in runs]
        losses = [r['held_out_loss'] for r in runs]
        row = {'profile': runs[0]['profile'], 'repeats': len(runs),
            'window_supervised_tokens': runs[0]['window']['supervised_tokens'],
            'window_samples': runs[0]['window']['samples'], 'window_first_sample': runs[0]['window']['first_sample'],
            'computed_positions': runs[0]['window']['computed_positions'], 'padding_positions': runs[0]['window']['padding_positions'],
            'wall_seconds_median': statistics.median(walls), 'wall_seconds_range': [min(walls), max(walls)],
            'tokens_per_second_median': statistics.median(rates), 'tokens_per_second_range': [min(rates), max(rates)],
            'peak_allocated_bytes_max': max(r['window']['peak_allocated_bytes'] for r in runs),
            'peak_allocated_bytes_range': [min(r['window']['peak_allocated_bytes'] for r in runs), max(r['window']['peak_allocated_bytes'] for r in runs)],
            'resident_bytes_before_window': runs[0]['window']['resident_bytes_before_window'],
            'optimizer_state_bytes': runs[0]['optimizer_state_bytes'],
            'peak_reserved_bytes': None, 'gpu_utilization_percent': None,
            'held_out_loss': losses[0], 'held_out_loss_repeat_spread': max(losses) - min(losses),
            'held_out_loss_before_training': runs[0]['held_out_loss_before_training']}
        relative = abs(losses[0] - baseline_loss) / baseline_loss
        row['held_out_relative_difference'] = relative
        if config in NOT_QUALITY_COMPARABLE:
            row['held_out_gate'] = 'not_applicable_different_update_count'
        else:
            row['held_out_gate'] = 'pass' if relative <= HELD_OUT_TOLERANCE else 'fail'
        steps = min(len(runs[0]['steps_detail']), len(baseline['steps_detail']))
        if config not in NOT_QUALITY_COMPARABLE:
            row['max_step_loss_relative_deviation'] = max(abs(a['loss'] - b['loss']) / b['loss']
                for a, b in zip(runs[0]['steps_detail'][:steps], baseline['steps_detail'][:steps]))
            row['update_cosine_to_baseline'] = update_cosine(adapters, config, 'baseline', LORA['scale'])
            if config in EXACT_REFORMULATIONS:
                row['equivalence_gate'] = 'pass' if (row['max_step_loss_relative_deviation'] <= EQUIVALENCE_LOSS_TOLERANCE
                    and row['update_cosine_to_baseline'] >= EQUIVALENCE_UPDATE_COSINE) else 'fail'
        rows[config] = row
    base = rows['baseline']
    for config, row in rows.items():
        row['wall_seconds_vs_baseline'] = row['wall_seconds_median'] / base['wall_seconds_median']
        row['tokens_per_second_vs_baseline'] = row['tokens_per_second_median'] / base['tokens_per_second_median']
        row['peak_allocated_vs_baseline'] = row['peak_allocated_bytes_max'] / base['peak_allocated_bytes_max']
    improvement = (base['held_out_loss_before_training'] - base['held_out_loss']) / base['held_out_loss_before_training']
    return rows, {'baseline_relative_held_out_change_from_untrained': improvement,
        'tolerance_discriminates': abs(improvement) > HELD_OUT_TOLERANCE}


def table(rows):
    mib = 1024 ** 2
    lines = ['| Configuration | Wall s (median, range) | Tokens/s (median) | vs baseline | Peak allocated MiB | vs baseline | '
        'Resident MiB | Optimizer state KiB | Held-out loss | Δ vs baseline | Gate |', '|' + '---|' * 11]
    for config, row in rows.items():
        gate = row['held_out_gate'] + (f", equivalence {row['equivalence_gate']}" if 'equivalence_gate' in row else '')
        lines.append(f"| {config} | {row['wall_seconds_median']:.3f} ({row['wall_seconds_range'][0]:.3f}–{row['wall_seconds_range'][1]:.3f}) | "
            f"{row['tokens_per_second_median']:.0f} | {row['tokens_per_second_vs_baseline']:.2f}× | {row['peak_allocated_bytes_max'] / mib:.1f} | "
            f"{row['peak_allocated_vs_baseline']:.2f}× | {row['resident_bytes_before_window'] / mib:.1f} | {row['optimizer_state_bytes'] / 1024:.1f} | "
            f"{row['held_out_loss']:.5f} | {100 * row['held_out_relative_difference']:.3f}% | {gate} |")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--steps', type=int, default=40, help='Optimizer steps at eight samples per step')
    parser.add_argument('--warmup', type=int, default=5, help='Steps at eight samples per step excluded from the window')
    parser.add_argument('--configs', default=','.join(CONFIGS))
    parser.add_argument('--measure', choices=list(CONFIGS), help=argparse.SUPPRESS)
    parser.add_argument('--corpus', help=argparse.SUPPRESS)
    parser.add_argument('--adapters', help=argparse.SUPPRESS)
    parser.add_argument('--repeat', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.model_dir = args.model_dir.resolve()
    if args.measure:
        print(json.dumps(measure(args.measure, args)))
        return
    if args.output is None:
        parser.error('--output is required')
    selected = args.configs.split(',')
    if 'baseline' not in selected or set(selected) - set(CONFIGS):
        parser.error('Select known configurations including baseline.')
    args.output.mkdir(parents=True, exist_ok=False)
    env = environment(args.model_dir)
    corpus_path, corpus = build_corpus(args.model_dir, args.output)
    results = []
    with tempfile.TemporaryDirectory(prefix='mlx-benchmark-adapters-') as adapters:
        for repeat in range(args.repeats):
            # Rotate the order each repeat so slow drift does not favour one configuration.
            order = selected[repeat % len(selected):] + selected[:repeat % len(selected)]
            for config in order:
                command = [sys.executable, str(Path(__file__).resolve()), '--model-dir', str(args.model_dir), '--measure', config,
                    '--corpus', str(corpus_path), '--adapters', adapters, '--repeat', str(repeat),
                    '--steps', str(args.steps), '--warmup', str(args.warmup)]
                print(f'[benchmark] repeat {repeat} {config}', file=sys.stderr, flush=True)
                completed = subprocess.run(command, capture_output=True, text=True, timeout=1800, cwd=ROOT)
                if completed.returncode:
                    raise RuntimeError(f'{config} failed:\n{completed.stderr[-4000:]}')
                result = json.loads(completed.stdout.strip().splitlines()[-1])
                if repeat:
                    Path(adapters, f'{config}.safetensors').unlink()  # Keep the first repeat for update comparison.
                    # Later repeats re-measure timing and memory; per-step detail is archived for the first repeat.
                    result['steps_detail_peak_allocated_bytes'] = [r['peak_allocated_bytes'] for r in result['steps_detail']]
                    result['steps_detail_losses'] = [r['loss'] for r in result.pop('steps_detail')]
                results.append(result)
            if repeat == 0:
                import shutil
                kept = Path(adapters) / 'first'
                kept.mkdir()
                for path in Path(adapters).glob('*.safetensors'):
                    shutil.move(str(path), kept / path.name)
        rows, discrimination = summarize(results, Path(adapters) / 'first')
    report = {'schema': 'modelanvil.mlx-training-benchmark.v1', 'environment': env, 'corpus': corpus,
        'design': {'seed': SEED, 'samples_per_step_baseline': BASELINE['batch_samples'], 'steps_at_eight_samples': args.steps,
            'warmup_steps_at_eight_samples': args.warmup, 'repeats': args.repeats,
            'window': 'Identical samples and supervised tokens in every configuration; the one-sample-per-step reference uses eight times the steps.',
            'tokens': 'Supervised next-token pairs; padding and packing boundary positions are excluded.',
            'wall_time': 'perf_counter around the whole window (batch construction, forward, backward, optimizer update, synchronizing evaluation).',
            'peak_allocated': 'Max over window steps of mx.get_peak_memory() after mx.reset_peak_memory() before each step: process-wide MLX active bytes, including resident weights.',
            'held_out': 'Token-weighted mean loss on held-out files, FP32 mlx_lm forward pass of a freshly loaded model with the trained adapters.',
            'held_out_tolerance_relative': HELD_OUT_TOLERANCE, 'equivalence_loss_tolerance_relative': EQUIVALENCE_LOSS_TOLERANCE,
            'equivalence_update_cosine_minimum': EQUIVALENCE_UPDATE_COSINE, 'exact_reformulations': list(EXACT_REFORMULATIONS),
            'unavailable_metrics': profiles.UNAVAILABLE_METRICS, 'unavailable_reasons': profiles.UNAVAILABLE_REASONS,
            'scope': 'One Apple GPU on this host. No other GPU, vendor or framework is measured, and no comparison with any other product is made.'},
        'discrimination': discrimination, 'summary': rows, 'results': results}
    (args.output / 'benchmark.json').write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    (args.output / 'summary.md').write_text(table(rows) + '\n')
    print(table(rows))


if __name__ == '__main__':
    main()
