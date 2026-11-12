"""Copy a directory and verify bytes. This is not a recovery-time claim."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _read_regular(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError('Restore rehearsal copies only regular files.') from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Restore rehearsal copies only regular files.')
        chunks = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        return b''.join(chunks)
    finally:
        os.close(descriptor)


def _write_regular(path: Path, data: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
    except OSError as error:
        raise ValueError('Restore rehearsal writes only under the destination.') from error
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise ValueError('Restore rehearsal writes only under the destination.')
            view = view[written:]
    finally:
        os.close(descriptor)


def _plan(source: Path, source_root: Path) -> tuple[list[Path], list[tuple[Path, Path]]]:
    directories: list[Path] = []
    files: list[tuple[Path, Path]] = []
    for directory, dirnames, filenames in os.walk(source, followlinks=False):
        current = Path(directory)
        # The walk root may itself be a symlink; that link is the source, not an escape.
        if not _inside(current, source_root) or (current.is_symlink() and current.resolve() != source_root):
            raise ValueError('Restore rehearsal refuses a symlink that leaves the source tree.')
        retained = []
        for name in dirnames:
            child = current / name
            if child.is_symlink():
                if not _inside(child, source_root):
                    raise ValueError('Restore rehearsal refuses a symlink that leaves the source tree.')
                continue
            retained.append(name)
        dirnames[:] = retained
        relative = current.relative_to(source)
        if relative.parts:
            directories.append(relative)
        for name in filenames:
            child = current / name
            if child.is_symlink():
                if not _inside(child, source_root):
                    raise ValueError('Restore rehearsal refuses a symlink that leaves the source tree.')
                continue
            if not child.is_file() or not _inside(child, source_root):
                raise ValueError('Restore rehearsal copies only regular files.')
            files.append((child.relative_to(source), child))
    directories.sort(key=lambda item: (len(item.parts), item.as_posix()))
    files.sort(key=lambda item: item[0].as_posix())
    return directories, files


def rehearse_copy(source: Path, destination: Path) -> dict:
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        raise ValueError('Restore rehearsal needs an existing source directory.')
    if os.path.lexists(destination):
        raise ValueError('Restore rehearsal destination must not exist.')
    source_root = source.resolve()
    directories, planned = _plan(source, source_root)
    destination.mkdir()
    try:
        dest_root = destination.resolve()
        if destination.is_symlink() or not _inside(destination, dest_root):
            raise ValueError('Restore rehearsal writes only under the destination.')
        for relative in directories:
            target = destination / relative
            if target.exists() or target.is_symlink() or not _inside(target, dest_root):
                raise ValueError('Restore rehearsal writes only under the destination.')
            target.mkdir()
        files = []
        for relative, origin in planned:
            target = destination / relative
            if target.exists() or target.is_symlink() or not _inside(target, dest_root):
                raise ValueError('Restore rehearsal writes only under the destination.')
            data = _read_regular(origin)
            _write_regular(target, data)
            copied = _read_regular(target)
            if target.is_symlink() or not _inside(target, dest_root):
                raise ValueError('Restore rehearsal writes only under the destination.')
            digest = hashlib.sha256(copied).hexdigest()
            if digest != hashlib.sha256(data).hexdigest():
                raise ValueError('Copied bytes do not match the source.')
            files.append({'path': relative.as_posix(), 'sha256': digest, 'bytes': len(copied)})
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {
        'files': len(files),
        'inventory': files,
        'production_qualified': False,
        'hardware_qualified': False,
        'scope': 'Byte copy between directories. Not an off-host database restore or a recovery-time claim.',
    }
