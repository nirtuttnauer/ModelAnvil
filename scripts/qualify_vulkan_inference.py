#!/usr/bin/env python3
"""Measure pinned llama.cpp Vulkan GGUF inference on this Mac's Apple GPU through MoltenVK.

Runs the CPU+Vulkan build (Metal never compiled) with every layer offloaded and the CPU-only
reference build of the same commit on identical GGUF files, prompts, seed and greedy settings.
Records llama.cpp's own offload/device/buffer report, decoded text, timing, peak RSS, per-op
graph placement and test-backend-ops results. Raw logs stay in the new private output directory;
``summary.json`` holds the publishable facts. Run behind the host compute lock; nothing is
downloaded, no account or tenant data is used, and measurements are not a throughput guarantee.

usage: qualify_vulkan_inference.py --vulkan-build DIR --cpu-build DIR --model NAME=PATH ... --output NEW_DIR
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

PROMPTS = ['What is 2 + 2?', 'Name three primary colors.', 'Write one sentence about the ocean.']
CHATML = '<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n'
# -lv 4 (trace) prints llama.cpp's own load report; greedy decoding makes the seed irrelevant.
GENERATE = ['-n', '64', '--temp', '0', '--seed', '42', '-c', '2048', '-t', '1', '-tb', '1',
            '-no-cnv', '--no-display-prompt', '--fit', 'off', '-lv', '4']
# The model uses 64-wide f16 attention heads; test that slice of FLASH_ATTN_EXT, not every head size.
FLASH_PARAMS = 'hsk=64,hsv=64,.*type_K=f16,type_V=f16'
ICD = '/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json'


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def env(vulkan, home):
    value = {'PATH': '/usr/bin:/bin', 'HOME': home, 'TMPDIR': home, 'LANG': 'C', 'LC_ALL': 'C'}
    if vulkan:
        value.update(VK_DRIVER_FILES=ICD, VK_ICD_FILENAMES=ICD, VK_LOADER_LAYERS_DISABLE='~all~', GGML_VK_VISIBLE_DEVICES='0')
    return value


def run(name, command, out, *, environment, timeout=900):
    started = time.monotonic()
    try:
        result = subprocess.run(['/usr/bin/time', '-l', *map(str, command)], env=environment, cwd=environment['HOME'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, errors='replace', timeout=timeout)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = 'timeout', exc.stdout or '', exc.stderr or ''
        stdout, stderr = (s.decode(errors='replace') if isinstance(s, bytes) else s for s in (stdout, stderr))
    (out / 'logs' / f'{name}.stdout').write_text(stdout)
    (out / 'logs' / f'{name}.stderr').write_text(stderr)
    rss = re.search(r'^\s*(\d+)\s+maximum resident set size', stderr, re.M)
    return {'command': [Path(command[0]).name, *map(str, command[1:])], 'returncode': code,
            'wall_seconds': round(time.monotonic() - started, 3), 'peak_rss_bytes': int(rss.group(1)) if rss else None,
            'stdout': stdout, 'stderr': stderr}


def mib(pattern, text):
    return {d: float(v) for d, v in re.findall(pattern, text, re.M)}


def load_report(text):
    offload = re.findall(r'load_tensors: offloaded (\d+)/(\d+) layers to GPU', text)
    perf = re.findall(r'eval time =\s+([\d.]+) ms /\s+(\d+) (tokens|runs)\s+\(\s*([\d.]+) ms per token,\s+([\d.]+) tokens per second\)', text)
    return {'offloaded_layers': f'{offload[-1][0]}/{offload[-1][1]}' if offload else None,
            'devices_used': re.findall(r'using device (\S+) \((.+?)\)', text),
            'vulkan_device_info': re.findall(r'ggml_vulkan: \d+ = .+', text),
            'model_buffer_mib': mib(r'load_tensors:\s+(\S+) model buffer size =\s+([\d.]+) MiB', text),
            'kv_buffer_mib': mib(r'llama_kv_cache:\s+(\S+) KV buffer size =\s+([\d.]+) MiB', text),
            'compute_buffer_mib': mib(r'(?:llama_context|sched_reserve):\s+(\S+) compute buffer size =\s+([\d.]+) MiB', text),
            'memory_breakdown': [line.split('common_memory_breakdown_print: ', 1)[1].strip()
                                 for line in text.splitlines() if 'common_memory_breakdown_print: |' in line],
            'flash_attention_enabled': 'Flash Attention enabled' in text,
            'graph_nodes': re.findall(r'graph nodes\s*=\s*(\d+)', text)[-1:] or None,
            'graph_splits': re.findall(r'graph splits = (\d+)', text)[-1:] or None,
            'flash_attention': (re.findall(r'flash_attn\s*=\s*(\S+)', text) or [None])[-1],
            'prompt_eval': next(({'ms': float(m[0]), 'tokens': int(m[1]), 'tokens_per_second': float(m[4])}
                                 for m in perf if m[2] == 'tokens'), None),
            'eval': next(({'ms': float(m[0]), 'tokens': int(m[1]), 'tokens_per_second': float(m[4])}
                          for m in perf if m[2] == 'runs'), None),
            'errors': sorted(set(re.findall(r'^.*(?:error|unsupported|not supported|failed).*$', text, re.M | re.I)))[:20]}


def placement(text):
    """GGML_SCHED_DEBUG=2 node lines: which backend each non-view graph node ran on."""
    nodes = re.findall(r'node #\s*\d+ \(\s*([A-Z0-9_]+)\):\s+\S+ \(\s*[^)]*\) \[\s*(\S+)', text)
    counts = Counter((op, backend) for op, backend in nodes)
    by_op = {}
    for (op, backend), count in sorted(counts.items()):
        by_op.setdefault(op, {})[backend] = count
    return {'nodes': len(nodes), 'ops': by_op,
            'cpu_ops': sorted({op for op, backend in nodes if backend.startswith('CPU')}),
            'splits': re.findall(r'## SPLIT #(\d+): (\S+) # (\d+) inputs', text)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vulkan-build', type=Path, required=True)
    parser.add_argument('--cpu-build', type=Path, required=True)
    parser.add_argument('--model', action='append', required=True, help='LABEL=path/to/model.gguf')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'logs').mkdir()
    home = tempfile.mkdtemp(prefix='vulkan-qualify-')
    builds = {'vulkan': args.vulkan_build.resolve(), 'cpu': args.cpu_build.resolve()}
    records = {name: json.loads((path / 'build-record.json').read_text()) for name, path in builds.items()}
    for name, path in builds.items():
        for tool, value in records[name]['binaries'].items():
            if sha256(path / 'bin' / tool) != value['sha256']:
                raise SystemExit(f'{name} {tool} differs from its build record')
    assert records['vulkan']['vulkan'] and not records['cpu']['vulkan']
    assert not records['vulkan']['metal_compiled'] and not records['cpu']['metal_compiled']
    for key in ('GGML_VK_ALLOW_SYSMEM_FALLBACK', 'GGML_VK_PREFER_HOST_MEMORY', 'VK_ICD_FILENAMES', 'VK_DRIVER_FILES'):
        if key in os.environ:
            print(f'note: ignoring inherited {key}; children get a fixed environment', file=sys.stderr)
    summary = {'schema': 'modelanvil.vulkan-inference-qualification.v1', 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
               'host': {'platform': platform.platform(), 'macos': platform.mac_ver()[0], 'machine': platform.machine(),
                        'sw_vers': subprocess.run(['sw_vers'], capture_output=True, text=True).stdout.split('\n'),
                        'cpu': subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True).stdout.strip(),
                        'memory_bytes': int(subprocess.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True).stdout)},
               'builds': {name: {k: v for k, v in record.items() if k != 'binaries'} | {
                   'binaries': {t: v['sha256'] for t, v in record['binaries'].items()}} for name, record in records.items()},
               'child_environment': {'vulkan': {k: v for k, v in env(True, '<private>').items()}, 'cpu': env(False, '<private>')},
               'prompts': [CHATML.format(p) for p in PROMPTS], 'generation_flags': GENERATE, 'models': {}, 'runs': {}}
    vulkaninfo = shutil.which('vulkaninfo', path='/opt/homebrew/bin')
    if vulkaninfo:
        result = run('vulkaninfo', [vulkaninfo, '--summary'], out, environment=env(True, home), timeout=60)
        summary['vulkaninfo_summary'] = [line for line in result['stdout'].splitlines() if '=' in line and line.startswith('\t')]
    summary['llama_list_devices'] = run('list-devices', [builds['vulkan'] / 'bin/llama-server', '--list-devices'], out,
                                        environment=env(True, home), timeout=60)['stdout'].strip().splitlines()
    for item in args.model:
        label, path = item.split('=', 1)
        path = Path(path).resolve()
        import gguf
        reader = gguf.GGUFReader(str(path))
        file_type = reader.fields['general.file_type'].contents()
        summary['models'][label] = {'file': path.name, 'sha256': sha256(path), 'byte_size': path.stat().st_size,
                                    'architecture': reader.fields['general.architecture'].contents(),
                                    'general_file_type': file_type, 'file_type_name': gguf.LlamaFileType(file_type).name,
                                    'tensor_types': dict(sorted(Counter(t.tensor_type.name for t in reader.tensors).items())),
                                    'tensor_count': len(reader.tensors)}
        del reader
    for label in summary['models']:
        path = Path(next(i.split('=', 1)[1] for i in args.model if i.startswith(label + '='))).resolve()
        rows = summary['runs'].setdefault(label, {})
        for build in ('vulkan', 'cpu'):
            offload = ['-ngl', 'all', '-dev', 'Vulkan0'] if build == 'vulkan' else ['-ngl', '0']
            outputs = []
            for index, prompt in enumerate(PROMPTS):
                for repeat in (1, 2):
                    result = run(f'{label}-{build}-p{index}-r{repeat}', [builds[build] / 'bin/llama-completion', '-m', path,
                                 '-p', CHATML.format(prompt), *GENERATE, *offload], out, environment=env(build == 'vulkan', home))
                    report = load_report(result['stderr'])
                    outputs.append({'prompt': index, 'repeat': repeat, 'returncode': result['returncode'], 'text': result['stdout'],
                                    'peak_rss_bytes': result['peak_rss_bytes'], 'wall_seconds': result['wall_seconds'], **report})
            bench = run(f'{label}-{build}-bench', [builds[build] / 'bin/llama-bench', '-m', path, '-p', '128', '-n', '64', '-r', '5',
                        '-t', '1', '-o', 'json', *(['-ngl', '99', '-dev', 'Vulkan0'] if build == 'vulkan' else ['-ngl', '0'])],
                        out, environment=env(build == 'vulkan', home))
            try:
                bench_rows = [{k: r.get(k) for k in ('n_prompt', 'n_gen', 'avg_ts', 'stddev_ts', 'backends', 'gpu_info',
                                                    'n_gpu_layers', 'n_threads', 'type_k', 'type_v', 'flash_attn', 'devices')}
                              for r in json.loads(bench['stdout'])]
            except (json.JSONDecodeError, TypeError):
                bench_rows = {'returncode': bench['returncode'], 'error': bench['stderr'][-2000:]}
            rows[build] = {'completions': outputs, 'bench': bench_rows}
        # Verbose scheduler trace: the device line and every graph node's backend (CPU = not on Vulkan).
        diagnostic = run(f'{label}-vulkan-sched-debug', [builds['vulkan'] / 'bin/llama-completion', '-m', path, '-p',
                         CHATML.format(PROMPTS[0]), '-n', '8', *GENERATE[2:], '-ngl', 'all', '-dev', 'Vulkan0', '-v'],
                         out, environment={**env(True, home), 'GGML_SCHED_DEBUG': '2'})
        rows['vulkan_graph_placement'] = {**placement(diagnostic['stderr']), 'returncode': diagnostic['returncode'],
                                          'vulkan_device_info': re.findall(r'ggml_vulkan: \d+ = .+', diagnostic['stderr'])}
        comparison = []
        for index in range(len(PROMPTS)):
            texts = {build: [o['text'] for o in rows[build]['completions'] if o['prompt'] == index] for build in ('vulkan', 'cpu')}
            first, second = texts['vulkan'][0], texts['cpu'][0]
            prefix = next((i for i, (a, b) in enumerate(zip(first, second)) if a != b), min(len(first), len(second)))
            comparison.append({'prompt': index, 'vulkan_repeat_identical': len(set(texts['vulkan'])) == 1,
                               'cpu_repeat_identical': len(set(texts['cpu'])) == 1, 'vulkan_equals_cpu': first == second,
                               'common_prefix_characters': prefix, 'vulkan_text': first, 'cpu_text': second})
        rows['comparison'] = comparison
    observed = sorted({op for label in summary['runs'] for op in summary['runs'][label]['vulkan_graph_placement']['ops']})
    support = run('test-backend-ops-support', [builds['vulkan'] / 'bin/test-backend-ops', 'support', '-b', 'Vulkan0',
                  '--output', 'csv'], out, environment=env(True, home), timeout=1800)
    import csv
    lines = support['stdout'].splitlines()
    header = next((i for i, line in enumerate(lines) if line.startswith('"') and 'op_name' in line), None)
    cases = {}
    for row in csv.DictReader(lines[header:]) if header is not None else []:
        if row.get('test_mode') == 'support' and row.get('backend_name') == 'Vulkan0':
            supported = str(row.get('supported')).lower() in ('yes', 'true', '1')
            cases.setdefault(row['op_name'], Counter())['supported' if supported else 'unsupported'] += 1
    unsupported = {op: dict(c) for op, c in sorted(cases.items()) if c['unsupported']}
    # Scheduler traces print op names truncated to 10 characters (FLASH_ATTN -> FLASH_ATTN_EXT).
    ops = sorted({op if op in cases else next((full for full in cases if full.startswith(op)), op) for op in observed})
    graph_ops = [op for op in ops if op != 'FLASH_ATTN_EXT']
    tested = run('test-backend-ops-graph-ops', [builds['vulkan'] / 'bin/test-backend-ops', 'test', '-b', 'Vulkan0',
                 '-o', ','.join(graph_ops)], out, environment=env(True, home), timeout=3600)
    flash = run('test-backend-ops-flash-attn', [builds['vulkan'] / 'bin/test-backend-ops', 'test', '-b', 'Vulkan0',
                '-o', 'FLASH_ATTN_EXT', '-p', FLASH_PARAMS], out, environment=env(True, home), timeout=3600)

    def outcome(result):
        lines = re.sub(r'\x1b\[[0-9;]*m', '', result['stdout']).splitlines()
        return {'returncode': result['returncode'], 'wall_seconds': result['wall_seconds'],
                'passed_line': next((l.strip() for l in lines if re.search(r'\d+/\d+ tests passed', l)), None),
                'backends_line': next((l.strip() for l in lines if 'backends passed' in l), None),
                'ok_cases': sum(1 for l in lines if l.endswith(': OK')),
                'not_supported_cases': sum(1 for l in lines if 'not supported' in l),
                'cases_by_op': dict(sorted(Counter(m.group(1) for l in lines if (m := re.match(r'\s+([A-Z_0-9]+)\(', l))).items())),
                'failures': [l.strip() for l in lines if 'FAIL' in l][:100]}
    summary['test_backend_ops'] = {
        'support': {'returncode': support['returncode'], 'ops_probed': len(cases),
                    'ops_with_unsupported_cases': unsupported,
                    'graph_op_support': {op: dict(cases.get(op, {})) for op in ops}},
        'graph_ops_observed': observed, 'graph_ops_tested': graph_ops + ['FLASH_ATTN_EXT'],
        'test': outcome(tested), 'flash_attention_test': {'params_filter': FLASH_PARAMS, **outcome(flash)}}
    for label in summary['runs']:
        for build in ('vulkan', 'cpu'):
            for row in summary['runs'][label][build]['completions']:
                row.pop('stdout', None)
    summary['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    summary['scope'] = ('One Apple M5 Pro through MoltenVK on this macOS build; pinned SmolLM2-135M-Instruct GGUF files only. '
                        'Not a discrete-GPU, cross-vendor, Linux, Windows/DirectML, training, model-quality or throughput guarantee.')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    shutil.rmtree(home, ignore_errors=True)
    print(json.dumps({label: [c['vulkan_equals_cpu'] for c in summary['runs'][label]['comparison']] for label in summary['runs']}))


if __name__ == '__main__':
    main()
