"""Consume RabbitMQ dispatch events for one registered worker."""
from __future__ import annotations

from typing import cast

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from modelanvil.jobs.broker import WorkerBrokerConsumer
from modelanvil.jobs.executor import Executor
from modelanvil.jobs.models import Worker, dispatch_topic


class Command(BaseCommand):
    help = "Consume tenant-scoped RabbitMQ dispatches for a registered worker."

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", type=int, required=True)
        parser.add_argument(
            "--executor",
            required=True,
            help="Dotted Python path to an operator-installed (descriptor, context) callable.",
        )
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
        try:
            executor = import_string(options["executor"])
        except (ImportError, AttributeError, ValueError) as exc:
            raise CommandError(f"Cannot load executor {options['executor']!r}") from exc
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
            )
            consumer.run()
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
