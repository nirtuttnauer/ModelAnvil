"""Identify the shipped API sources without exposing workspace paths or secrets."""
import hashlib
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

PROTOCOL = 'modelanvil.local-beta.v1'


@lru_cache(maxsize=1)
def build_info():
    root = Path(__file__).resolve().parents[1]
    revision = os.environ.get('MODELANVIL_BUILD_REVISION', '')
    if not revision:
        try:
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        except (OSError, subprocess.SubprocessError):
            revision = 'unversioned'
    sha = hashlib.sha256()
    files = sorted([p for p in (root/'modelanvil').rglob('*.py') if not p.name.startswith('test')]
        + list((root/'contracts').rglob('*.json')) + list((root/'scripts').glob('*.py')))
    for path in files:
        sha.update(path.relative_to(root).as_posix().encode()); sha.update(b'\0'); sha.update(path.read_bytes())
    # Import names are stable even when optional parsers are not installed.
    from modelanvil.data.source_import import MEDIA_TYPES
    return {'revision': revision, 'source_digest': sha.hexdigest(), 'protocol': PROTOCOL,
            'dataset_formats': ['jsonl', *sorted(MEDIA_TYPES)], 'production_qualified': False}


if __name__ == '__main__':
    print(json.dumps(build_info()))
