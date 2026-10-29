"""Copy a directory and verify bytes. This is not a recovery-time claim."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def rehearse_copy(source: Path, destination: Path) -> dict:
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        raise ValueError('Restore rehearsal needs an existing source directory.')
    if destination.exists():
        raise ValueError('Restore rehearsal destination must not exist.')
    shutil.copytree(source, destination)
    files = []
    for path in sorted(item for item in destination.rglob('*') if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        original = source / path.relative_to(destination)
        if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            raise ValueError('Copied bytes do not match the source.')
        files.append({'path': path.relative_to(destination).as_posix(), 'sha256': digest, 'bytes': path.stat().st_size})
    return {
        'files': len(files),
        'inventory': files,
        'production_qualified': False,
        'hardware_qualified': False,
        'scope': 'Byte copy between directories. Not an off-host database restore or a recovery-time claim.',
    }
