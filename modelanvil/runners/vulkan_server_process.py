"""Exec the pinned llama.cpp Vulkan server with a hard lifetime that survives parent death."""
import os
import signal
import sys


if __name__ == '__main__':
    seconds = int(sys.argv[1])
    if not 1 <= seconds <= 3600 or len(sys.argv) < 3:
        raise ValueError('The Vulkan inference server requires a bounded installed command.')
    signal.alarm(seconds)  # Survives exec; the default SIGALRM action ends an orphaned server.
    os.execv(sys.argv[2], sys.argv[2:])
