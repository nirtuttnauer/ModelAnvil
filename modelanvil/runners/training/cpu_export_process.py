"""Keep the operator's deadline and inherited device lease across POSIX exec."""
import os
import signal
import sys


if __name__ == '__main__':
    seconds = int(sys.argv[1])
    if not 1 <= seconds <= 300 or len(sys.argv) < 3:
        raise ValueError('CPU export requires a bounded installed command.')
    signal.alarm(seconds)  # Survives exec and parent death; the default handler terminates the child.
    os.execvp(sys.argv[2], sys.argv[2:])
