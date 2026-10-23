"""Invoke one pinned data-only verifier under bounded POSIX child limits."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'alignment_verifier.py'
VERSION = 'modelanvil.builtin-verifier.v1'
WALL_SECONDS = 2


def contract():
    return {'version': VERSION, 'script_sha256': hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        'rules': ['exact_match', 'numeric_tolerance'], 'wall_seconds': WALL_SECONDS,
        'cpu_seconds': 1, 'address_space_bytes': None if sys.platform == 'darwin' else 256 * 1024**2,
        'memory_mode': 'fixed_input_bounds_and_verified_peak_rss' if sys.platform == 'darwin' else 'address_space_and_verified_peak_rss',
        'max_peak_rss_bytes': 64 * 1024**2, 'input_output_bytes': 16384,
        'group_size': 8, 'network': 'no_network_operations_or_user_code',
        'interpreter': f'{sys.version_info.major}.{sys.version_info.minor}'}


def score(responses, expected, spec):
    payload = json.dumps({'responses': responses, 'expected': expected, 'spec': spec}, allow_nan=False).encode()
    if len(payload) > 16384:
        raise ValueError('Verifier input exceeds its bounded data envelope.')
    started = time.monotonic()
    try:
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(SCRIPT)], input=payload,
            capture_output=True, timeout=WALL_SECONDS, env={'PYTHONHASHSEED': '0'})
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Verifier timed out; no rewards accepted.') from exc
    if result.returncode or len(result.stdout) > 16384:
        raise ValueError('Verifier failed; no rewards accepted.')
    try:
        value = json.loads(result.stdout)
        rewards = value['rewards']
        if (value['status'] != 'ok' or value['version'] != VERSION or not isinstance(rewards, list)
                or type(value.get('peak_rss_bytes')) is not int or not 0 < value['peak_rss_bytes'] <= 64 * 1024**2
                or type(value.get('cpu_seconds')) not in (int, float) or not math.isfinite(value['cpu_seconds']) or not 0 <= value['cpu_seconds'] <= 1
                or value.get('address_space_enforced') != (sys.platform != 'darwin')
                or len(rewards) != len(responses) or any(type(r) not in (int, float) or r not in (0, 1) for r in rewards)):
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('Verifier returned invalid results; no rewards accepted.') from exc
    return {**value, 'wall_seconds': time.monotonic() - started}
