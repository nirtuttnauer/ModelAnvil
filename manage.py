#!/usr/bin/env python
"""Django management entry point for ModelAnvil."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")
    try:
        from django.core.management import execute_from_command_line
        if len(sys.argv) > 1 and sys.argv[1] == "runserver":
            from django.core.servers.basehttp import WSGIServer

            # Workspace page requests can exceed Django's ten-connection accept queue.
            WSGIServer.request_queue_size = 128
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
