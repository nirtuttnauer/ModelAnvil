"""Reshape the archived TASK-16 file digests so stock secret scanners do not flag them.

The measured archives stored SHA-256 digests under file-name keys such as
"tokenizer.json" and "tokenizer_sha256". Stock gitleaks 8.28.0 reads those lines as
generic API keys. This converts, with the same values and no other change:

  environment.model_file_sha256 {name: digest} -> environment.model_files [{"file", "sha256"}]
  corpus tokenizer_sha256 digest               -> corpus tokenizer {"file": "tokenizer.json", "sha256"}

Formatting stays json.dumps(indent=1, sort_keys=True). --check reverses the
conversion and verifies the original bytes against the measured digests.

  python docs/engineering/verification/task16-mlx-2026-11-15/convert_digest_shape.py [--check]
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS = ('run1-predeclared', 'benchmark')
# SHA-256 of each file as the benchmark wrote it, before conversion.
MEASURED = {
    'run1-predeclared/benchmark.json': 'b4e030f7ef1b30717451c32fc0ac41e78f1938ea0efd93808d910d46e6fdf76d',
    'benchmark/benchmark.json': '8d926d6c7b57134e67b00e0ffc57c26c24ffa14ccfa4aa4333f696d8cc57af14',
    'run1-predeclared/corpus.json': '72e92fb78c11f477226262dbece2e687e81fecefc94f06e2b14da148a47da4f2',
    'benchmark/corpus.json': '72e92fb78c11f477226262dbece2e687e81fecefc94f06e2b14da148a47da4f2',
}


def dump(value):
    return json.dumps(value, indent=1, sort_keys=True) + '\n'


def forward(name, value):
    if name == 'benchmark.json' and 'model_file_sha256' in value['environment']:
        files = value['environment'].pop('model_file_sha256')
        value['environment']['model_files'] = [{'file': f, 'sha256': d} for f, d in sorted(files.items())]
    if name == 'corpus.json' and 'tokenizer_sha256' in value:
        value['tokenizer'] = {'file': 'tokenizer.json', 'sha256': value.pop('tokenizer_sha256')}
    return value


def reverse(name, value):
    if name == 'benchmark.json':
        files = value['environment'].pop('model_files')
        value['environment']['model_file_sha256'] = {item['file']: item['sha256'] for item in files}
    if name == 'corpus.json':
        tokenizer = value.pop('tokenizer')
        assert tokenizer['file'] == 'tokenizer.json'
        value['tokenizer_sha256'] = tokenizer['sha256']
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='Verify that reversing the conversion restores the measured bytes')
    args = parser.parse_args()
    for run in RUNS:
        for name in ('benchmark.json', 'corpus.json'):
            path = ROOT / run / name
            raw = path.read_text()
            if args.check:
                restored = dump(reverse(name, json.loads(raw)))
                digest = hashlib.sha256(restored.encode()).hexdigest()
                if digest != MEASURED[f'{run}/{name}']:
                    raise SystemExit(f'{run}/{name}: reversed bytes differ from the measured file')
                print(f'{run}/{name}: reversed bytes match measured SHA-256 {digest}')
                continue
            if hashlib.sha256(raw.encode()).hexdigest() != MEASURED[f'{run}/{name}']:
                raise SystemExit(f'{run}/{name}: not the measured file; refusing to convert')
            if dump(json.loads(raw)) != raw:
                raise SystemExit(f'{run}/{name}: does not round-trip; refusing to convert')
            path.write_text(dump(forward(name, json.loads(raw))))
            print(f'{run}/{name}: converted')


if __name__ == '__main__':
    main()
