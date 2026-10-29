#!/usr/bin/env python3
"""Record or verify content identities for a public or private beta release.

This is a local build receipt, not a hardware, cloud, or customer qualification.
It never includes environment values, credentials, datasets, or model weights.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


PUBLIC_PREFIXES = ('modelanvil/', 'contracts/', 'scripts/', 'deploy/', 'catalog/',
                   'web/src/', 'web/.storybook/', 'web/scripts/', 'web/public/')
PUBLIC_FILES = {'web/package.json', 'web/package-lock.json', 'web/vite.config.ts',
                'web/vitest.config.ts', 'web/tsconfig.json', 'web/index.html', 'Makefile', 'compose.yaml',
                'manage.py', '.dockerignore', '.github/workflows/ci.yml', 'design/figcraft/variables.json'}
PRIVATE_PREFIXES = ('modelanvil_saas/', 'deploy/', 'tests/', 'web/src/', 'web/scripts/')
PRIVATE_FILES = {'web/package.json', 'web/tsconfig.json', 'web/vite.config.ts', 'web/index.html', 'web/vite-env.d.ts', '.dockerignore'}


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def source_files(root, private=False):
    output = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'])
    prefixes, exact = (PRIVATE_PREFIXES, PRIVATE_FILES) if private else (PUBLIC_PREFIXES, PUBLIC_FILES)
    files = {}
    for name in sorted(set(output.decode().split('\0')) - {''}):
        path = root / name
        if (name.startswith(prefixes) or name in exact or (not private and name.startswith('requirements') and name.endswith('.txt'))):
            if '.env' in path.name or '__screenshots__' in path.parts or path.is_symlink() or not path.is_file():
                continue
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def record(root, private=False):
    files = source_files(root, private)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'head': git(root, 'rev-parse', '--verify', 'HEAD'),
            'baseline': git(root, 'rev-parse', '--verify', 'refs/heads/codex/beta-baseline-20261028'),
            'implementation_checkpoint': git(root, 'rev-parse', '--verify', 'refs/heads/codex/beta-implementation-20261028'),
            'source_digest': digest, 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--private', action='store_true', help='Include private identities; write only to private storage.')
    parser.add_argument('--image', action='append', default=[], metavar='NAME=IMAGE', help='Inspect an existing local Docker image; never pulls it.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    current = {'public': record(root)}
    if args.private:
        current['private'] = record(root / 'private-saas', private=True)
    if args.verify:
        saved = json.loads(args.verify.read_text())
        if set(saved['sources']) != set(current):
            raise SystemExit('Select the same public/private scope as the saved receipt.')
        for name, source in current.items():
            if saved['sources'][name]['source_digest'] != source['source_digest']:
                raise SystemExit(f'{name} sources changed; rebuild and requalify this release.')
        print('Source identities match. Hardware, deployment, and pilot gates remain separate.')
        return
    if not args.output:
        parser.error('--output is required when not verifying')
    if args.private and not args.output.resolve().is_relative_to((root / 'private-saas').resolve()):
        parser.error('Private receipts must remain inside private-saas/ (normally output/).')
    images = {}
    for entry in args.image:
        name, separator, image = entry.partition('=')
        if not separator or not name or not image or image.startswith('-'):
            parser.error('Each --image must be NAME=IMAGE')
        result = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image]))[0]
        images[name] = {'id': result['Id'], 'repo_digests': result.get('RepoDigests', [])}
    receipt = {'schema_version': 1, 'recorded_at': datetime.now(timezone.utc).isoformat(),
               'sources': current, 'images': images,
               'qualification': {'apple_hardware': 'requires_matching_evidence',
                                 'live_cloud': 'requires_matching_evidence',
                                 'customer_pilots': 'requires_observed_teams'}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(f'Recorded {sum(len(source["files"]) for source in current.values())} source identities and {len(images)} local image identities.')


if __name__ == '__main__':
    main()
