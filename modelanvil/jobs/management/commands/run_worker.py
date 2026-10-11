"""Poll for and execute durable jobs with an operator-installed executor."""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from modelanvil.jobs.executor import execute_one
from modelanvil.jobs.models import Worker


class Command(BaseCommand):
    help = "Run a trusted local executor against durable worker claims."

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", type=int, required=True)
        parser.add_argument(
            "--executor",
            required=True,
            help="Dotted Python path to an operator-installed (descriptor, context) callable.",
        )
        parser.add_argument("--once", action="store_true", help="Poll once and exit.")
        parser.add_argument("--interval", type=float, default=2.0, help="Seconds between empty polls.")

    def handle(self, *args, **options):
        if options["worker_id"] < 1:
            raise CommandError("--worker-id must be positive")
        if options["interval"] <= 0:
            raise CommandError("--interval must be positive")

        worker = Worker.all_objects.filter(pk=options["worker_id"]).first()
        if worker is None:
            raise CommandError("Worker not found")
        try:
            executor = import_string(options["executor"])
        except (ImportError, AttributeError, ValueError) as exc:
            raise CommandError(f"Cannot load executor {options['executor']!r}") from exc
        if not callable(executor):
            raise CommandError("Configured executor is not callable")

        try:
            while True:
                outcome = execute_one(worker, executor)
                if outcome.get("claimed"):
                    self.stdout.write(
                        f"claimed=1 committed={int(outcome['committed'])} status={outcome['status']}"
                    )
                elif options["once"]:
                    self.stdout.write("claimed=0")
                else:
                    time.sleep(options["interval"])
                    continue
                if options["once"]:
                    return
        except KeyboardInterrupt:
            self.stdout.write("worker stopped")
