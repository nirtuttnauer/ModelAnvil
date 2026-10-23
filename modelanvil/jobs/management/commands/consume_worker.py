"""Consume RabbitMQ dispatch events for one registered worker."""
from __future__ import annotations

import os
import getpass
from typing import cast

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from modelanvil.jobs.broker import WorkerBrokerConsumer
from modelanvil.jobs.setup import PROFILES, observe_local_worker, profile_executor
from modelanvil.jobs.executor import Executor
from modelanvil.jobs.models import Worker, dispatch_topic


class Command(BaseCommand):
    help = "Consume tenant-scoped RabbitMQ dispatches for a registered worker."

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", type=int, required=True)
        executors = parser.add_mutually_exclusive_group(required=True)
        executors.add_argument(
            "--executor",
            help="Dotted Python path to an operator-installed (descriptor, context) callable.",
        )
        executors.add_argument("--profile", choices=list(PROFILES))
        parser.add_argument("--concurrency", type=int, default=1)
        parser.add_argument("--retry-delay-ms", type=int, default=5000)

    def handle(self, *args, **options):
        if options["worker_id"] < 1:
            raise CommandError("--worker-id must be positive")
        if options["concurrency"] < 1 or options["retry_delay_ms"] < 1:
            raise CommandError("--concurrency and --retry-delay-ms must be positive")
        worker = Worker.all_objects.select_related("pool").filter(pk=options["worker_id"]).first()
        if worker is None:
            raise CommandError("Worker not found")
        profile = options.get("profile")
        secret = (os.environ.get("MODELANVIL_WORKER_TOKEN") or getpass.getpass("Worker credential: ")) if profile else None
        observer = (lambda: observe_local_worker(worker, profile, secret)) if profile else None
        executor_path = profile_executor(profile) if profile else options["executor"]
        try:
            executor = import_string(executor_path)
        except (ImportError, AttributeError, ValueError) as exc:
            raise CommandError(f"Cannot load executor {executor_path!r}") from exc
        if not callable(executor):
            raise CommandError("Configured executor is not callable")
        executor = cast(Executor, executor)
        queue_name = dispatch_topic(worker.tenant_id, worker.pool.queue_name, worker.pool.name)
        try:
            consumer = WorkerBrokerConsumer(
                worker,
                queue_name,
                executor,
                concurrency=options["concurrency"],
                retry_delay_ms=options["retry_delay_ms"],
                observer=observer,
            )
            consumer.run()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        finally:
            if profile:
                Worker.all_objects.filter(pk=worker.pk).update(status=Worker.Status.OFFLINE)
