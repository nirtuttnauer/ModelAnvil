"""Fixed offline verifier child. Receives data only; never imports application code."""
import json
import math
import resource
import sys

VERSION = 'modelanvil.builtin-verifier.v1'
LIMITS = {'cpu_seconds': 1, 'address_space_bytes': 256 * 1024**2, 'open_files': 32,
          'file_bytes': 0, 'max_peak_rss_bytes': 64 * 1024**2, 'input_bytes': 16384, 'records': 8, 'characters': 32}


def verify(response, expected, spec):
    if not isinstance(response, str) or len(response) > LIMITS['characters']:
        raise ValueError('Invalid response.')
    if not isinstance(expected, str) or not expected.strip() or len(expected) > LIMITS['characters']:
        raise ValueError('Invalid expected answer.')
    if spec['type'] == 'exact_match':
        return response.strip() == expected.strip()
    target = float(expected)
    if not math.isfinite(target):
        raise ValueError('Expected numeric answer must be finite.')
    try:
        actual = float(response)
    except ValueError:
        return False
    return math.isfinite(actual) and abs(actual - target) <= spec['tolerance']


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (LIMITS['cpu_seconds'], LIMITS['cpu_seconds']))
    # Darwin refuses lowering RLIMIT_AS; only fixed data bounds and measured RSS qualify there.
    address_space_enforced = sys.platform != 'darwin'
    if address_space_enforced:
        resource.setrlimit(resource.RLIMIT_AS, (LIMITS['address_space_bytes'], LIMITS['address_space_bytes']))
    resource.setrlimit(resource.RLIMIT_NOFILE, (LIMITS['open_files'], LIMITS['open_files']))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    raw = sys.stdin.buffer.read(LIMITS['input_bytes'] + 1)
    if len(raw) > LIMITS['input_bytes']:
        raise ValueError('Verifier input exceeds limit.')
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'spec', 'responses', 'expected'}:
        raise ValueError('Invalid verifier input.')
    spec = data['spec']
    if (not isinstance(spec, dict) or set(spec) != {'type', 'tolerance'}
            or spec['type'] not in {'exact_match', 'numeric_tolerance'}
            or type(spec['tolerance']) not in (int, float) or not math.isfinite(spec['tolerance'])
            or not 0 <= spec['tolerance'] <= 1000000):
        raise ValueError('Invalid verifier rule.')
    responses = data['responses']
    if not isinstance(responses, list) or not 1 <= len(responses) <= LIMITS['records']:
        raise ValueError('Invalid verifier group.')
    expected = data['expected']
    if not isinstance(expected, list) or len(expected) != len(responses):
        raise ValueError('Invalid expected-answer group.')
    rewards = [float(verify(response, answer, spec)) for response, answer in zip(responses, expected)]
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_rss = usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
    if peak_rss > LIMITS['max_peak_rss_bytes']:
        raise ValueError('Verifier memory envelope exceeded; no rewards accepted.')
    print(json.dumps({'version': VERSION, 'status': 'ok', 'rewards': rewards,
        'limits': {**LIMITS, 'address_space_bytes': LIMITS['address_space_bytes'] if address_space_enforced else None}, 'network': 'no_network_operations_or_user_code',
        'cpu_seconds': usage.ru_utime + usage.ru_stime, 'peak_rss_bytes': peak_rss,
        'address_space_enforced': address_space_enforced}, allow_nan=False))


if __name__ == '__main__':
    main()
