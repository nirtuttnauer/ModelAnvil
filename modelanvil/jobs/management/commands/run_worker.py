"""Poll for and execute durable jobs with an operator-installed executor."""
from __future__ import annotations

import time
import os
import getpass

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from modelanvil.jobs.executor import execute_one
from modelanvil.jobs.models import Worker
from modelanvil.jobs.setup import PROFILES


class Command(BaseCommand):
    help = "Run a trusted local executor against durable worker claims."

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", type=int, required=True)
        executors = parser.add_mutually_exclusive_group(required=True)
        executors.add_argument(
            "--executor",
            help="Dotted Python path to an operator-installed (descriptor, context) callable.",
        )
        executors.add_argument("--profile", choices=list(PROFILES),
                               help="Run a shipped local profile registered through Infrastructure.")
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
        from modelanvil.jobs.setup import observe_local_worker, observe_operator_worker, profile_executor
        profile = options.get("profile")
        secret = None
        if profile:
            secret = os.environ.get("MODELANVIL_WORKER_TOKEN") or getpass.getpass("Worker credential: ")
        executor_path = profile_executor(profile) if profile else options["executor"]
        try:
            executor = import_string(executor_path)
        except (ImportError, AttributeError, ValueError) as exc:
            raise CommandError("Cannot load the configured trusted executor") from exc
        if not callable(executor):
            raise CommandError("Configured executor is not callable")

        try:
            while True:
                if profile:
                    try:
                        observe_local_worker(worker, profile, secret)
                    except ValueError as exc:
                        raise CommandError(str(exc)) from exc
                else:
                    observe_operator_worker(worker)
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
        finally:
            Worker.all_objects.filter(pk=worker.pk).update(status=Worker.Status.OFFLINE)
