#!/usr/bin/env python3
"""Record ModelAnvil's own vulkan:0 session receipts for each GGUF file (run behind the compute lock).

usage: MODELANVIL_VULKAN_INFERENCE='{...}' python session_evidence.py --output new.json MODEL.gguf ...
Loads each file through modelanvil.runners.vulkan_runtime.VulkanGGUFSession, generates with the
model's chat template (greedy, seed 42), cancels one stream, keeps llama-server's load-report lines
and checks that unload closes the private listener. No database, tenant data or network is used.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

LOAD_LINES = re.compile(r'using device|offload|model buffer|KV buffer|compute buffer|Flash Attention|flash_attn|'
                        r'n_ctx  |listening on|model loaded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('models', nargs='+', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('output must be new')
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'modelanvil.settings')
    import django
    django.setup()
    import requests
    from modelanvil.runners import vulkan_runtime
    from modelanvil.runners.inference import generate
    messages = [{'role': 'user', 'content': 'What is 2 + 2?'}]
    report = {'schema': 'modelanvil.vulkan-session-evidence.v1', 'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
              'installation': vulkan_runtime.inspect(), 'qualification': vulkan_runtime.QUALIFICATION, 'sessions': []}
    for path in args.models:
        started = time.monotonic()
        model = vulkan_runtime.VulkanGGUFSession(path)
        load_seconds = time.monotonic() - started
        session = {'format': 'gguf', 'model': model, 'device': 'vulkan:0'}
        address, process = model.base_url, model.process
        try:
            log = (Path(model.directory) / 'server.log').read_text(errors='replace')
            parts = list(generate(session, messages, max_tokens=16, temperature=0, seed=42))
            repeat = list(generate(session, messages, max_tokens=16, temperature=0, seed=42))
            stopped, cancelled = [False], []
            for part in generate(session, messages, max_tokens=64, cancelled=lambda: stopped[0]):
                cancelled.append(part)
                stopped[0] = stopped[0] or 'text' in part
            unauthorized = requests.post(address + '/v1/completions', json={'prompt': 'hi', 'max_tokens': 2}, timeout=5).status_code
        finally:
            model.close()
        try:
            requests.get(address + '/health', timeout=2)
            listener_closed = False
        except requests.ConnectionError:
            listener_closed = True
        text = ''.join(p.get('text', '') for p in parts)
        evidence = {k: v for k, v in model.evidence.items() if k != 'runtime'}
        report['sessions'].append({
            'file': path.name, 'load_seconds_including_device_probe': round(load_seconds, 3), 'evidence': evidence,
            'server_load_report': [line.strip() for line in log.splitlines() if LOAD_LINES.search(line) and 'api_key' not in line],
            'decoded_text': text, 'repeat_identical': text == ''.join(p.get('text', '') for p in repeat),
            'final': parts[-1], 'cancelled_final': cancelled[-1], 'unauthorized_status': unauthorized,
            'server_exit_code': process.poll(), 'listener_closed_after_unload': listener_closed})
    report['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps([{k: s[k] for k in ('file', 'decoded_text', 'repeat_identical', 'listener_closed_after_unload')}
                      for s in report['sessions']], indent=1))


if __name__ == '__main__':
    main()
