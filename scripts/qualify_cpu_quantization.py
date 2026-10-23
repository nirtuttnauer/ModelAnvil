"""Sequential native CPU measurements. Reports evidence; never grants release approval.

Use an independently frozen held-out text file; never substitute authored fixture metrics.
The native processes each have their own measured high-water RSS and no GPU offload.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import tempfile
import time



QUALIFIED_CORPUS = {
    'source_repo': 'Salesforce/wikitext',
    'source_revision': 'b08601e04326c79dfdd32d625aee71d232d685c3',
    'source_path': 'wikitext-2-raw-v1/test-00000-of-00001.parquet',
    'source_sha256': '5f1bea067869d04849c0f975a2b29c4ff47d867f484f5010ea5e861eab246d91',
    'sha256': '60869b19adb8bd51d357269ce3afd8952a8cc4ee90ff9822f9f9394ecaf9604e',
    'byte_size': 32112,
}


def validate_corpus(manifest, actual):
    if (any(manifest.get(key) != value for key, value in QUALIFIED_CORPUS.items())
            or manifest.get('fixture') is not False or manifest.get('split') != 'test'
            or not manifest.get('license') or actual != {k: QUALIFIED_CORPUS[k] for k in ('sha256', 'byte_size')}):
        raise ValueError('Only the exact pinned public WikiText test selection qualifies this bounded comparison; fixture or unqualified corpus metrics are refused.')


def pin(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024): sha.update(block)
    return {'sha256': sha.hexdigest(), 'byte_size': path.stat().st_size}


def measure(command):
    # Each wrapper starts exactly one native process; RUSAGE_CHILDREN is not cumulative across samples.
    with tempfile.TemporaryDirectory() as directory:
        out, err = Path(directory) / 'out', Path(directory) / 'err'
        started = time.monotonic()
        env = {key: value for key, value in os.environ.items() if key in {'PATH', 'SYSTEMROOT', 'TMPDIR', 'LANG', 'LC_ALL'}}
        env.update(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', HF_HUB_OFFLINE='1')
        with out.open('w') as stdout, err.open('w') as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, env=env, timeout=180, check=False)
        elapsed = time.monotonic() - started
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        stdout, stderr = out.read_text(), err.read_text()
        if result.returncode or len(stdout) + len(stderr) > 4 * 1024**2:
            raise ValueError('Native measurement failed or exceeded its output bound.')
        return {'elapsed_seconds': elapsed, 'native_peak_rss_bytes': int(usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)),
                'cpu_seconds': usage.ru_utime + usage.ru_stime, 'stdout': stdout, 'stderr': stderr}


def compare(baseline, quantized, *, fixture):
    if fixture:
        raise ValueError('Fixture metrics cannot qualify held-out quantization quality.')
    if any(not math.isfinite(v) or v <= 0 for v in (baseline, quantized)):
        raise ValueError('Quantization requires finite positive measured perplexities.')
    return {'metric': 'perplexity', 'baseline': baseline, 'quantized': quantized,
            'relative_change': quantized / baseline - 1, 'maximum_relative_increase': .05,
            'state': 'passed' if quantized <= baseline * 1.05 else 'failed',
            'production_qualified': False,
            'scope': 'Bounded corpus regression check only. Pretraining contamination and domain quality remain unqualified.'}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--measure-child':
        print(json.dumps(measure(sys.argv[2:]))); return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'quantized', 'perplexity', 'completion', 'heldout', 'heldout-manifest', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.heldout_manifest.read_text())
    actual = pin(args.heldout)
    validate_corpus(manifest, actual)
    def sample(command):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--measure-child', *map(str, command)],
                                capture_output=True, text=True, timeout=200, check=True)
        return json.loads(result.stdout)
    results = {}
    for label, path in (('baseline', args.baseline), ('quantized', args.quantized)):
        if not 1 <= path.stat().st_size <= 1024**3: raise ValueError('Model exceeds the 1 GiB CPU bound.')
        quality = sample([args.perplexity, '-m', path, '-ngl', '0', '-t', '1', '-tb', '1', '-c', '128',
                          '-b', '128', '-ub', '128', '--chunks', '8', '-f', args.heldout, '--no-warmup'])
        match = re.search(r'Final estimate: PPL = ([0-9.eE+-]+)', quality['stdout'] + quality['stderr'])
        chunks = re.search(r'calculating perplexity over (\d+) chunks', quality['stdout'] + quality['stderr'])
        if not match or not chunks or int(chunks[1]) != 8:
            raise ValueError('Native perplexity did not process the required eight 128-token chunks.')
        generations = []
        for _ in range(3):
            value = sample([args.completion, '-m', path, '-ngl', '0', '-t', '1', '-tb', '1', '-c', '128',
                            '-n', '16', '--seed', '42', '--temp', '0', '--no-warmup', '--no-conversation',
                            '--no-display-prompt', '-p', 'A telescope collects'])
            if not value['stdout'].strip(): raise ValueError('Native export generated no decoded output.')
            generations.append(value)
        results[label] = {'model': pin(path), 'perplexity': float(match[1]), 'chunks': 8, 'context_tokens': 128,
                          'quality_measurement': quality, 'generation_measurements': generations}
    report = {'profile': 'modelanvil.cpu-quantization-comparison.v1', 'device': 'cpu', 'threads': 1,
              'host': platform.platform(), 'machine': platform.machine(), 'corpus': manifest, 'results': results,
              'tools': {'perplexity': pin(args.perplexity), 'completion': pin(args.completion)},
              'quality_gate': compare(results['baseline']['perplexity'], results['quantized']['perplexity'], fixture=False),
              'production_qualified': False}
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'report': str(args.output), 'quality_gate': report['quality_gate']}))


if __name__ == '__main__': main()
