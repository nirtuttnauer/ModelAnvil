"""Exclusive local device use across cooperating processes under one OS account."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import stat

from django.conf import settings


class DeviceBusy(ValueError):
    pass


def device_key(selector):
    if not isinstance(selector, str):
        raise ValueError('Select an explicit supported local device.')
    if selector in {'mps:0', 'mlx:0'}:
        return 'apple-0'
    if selector == 'cpu':
        return 'cpu'
    if not re.fullmatch(r'(?:cuda|rocm|xpu):(?:0|[1-9][0-9]*)', selector):
        raise ValueError('Select an explicit supported local device.')
    return selector.replace(':', '-')


@contextmanager
def device_lease(selector):
    key = device_key(selector)
    try:
        import fcntl
    except ImportError:
        raise ValueError('This local device admission runtime requires a qualified POSIX host.') from None
    root = Path(settings.MODELANVIL_DEVICE_LOCK_ROOT)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.stat()
    if root.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Device admission directory must be private and owned by this OS account.')
    descriptor = os.open(root / (key + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError('Device admission file must be a private regular file.')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeviceBusy('This local device is busy in another inference or training process; retry when it finishes.') from None
        yield key
    finally:
        os.close(descriptor)  # The OS also releases the lock if a process dies.


def device_available(selector):
    try:
        with device_lease(selector):
            return True
    except DeviceBusy:
        return False
