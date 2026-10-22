import math
import time

from django.core.management.base import BaseCommand, CommandError
from modelanvil.compute.plugins import PluginError, definition
from modelanvil.compute.task_worker import execute_task
from modelanvil.jobs.executor import execute_one
from modelanvil.jobs.models import Worker


class Command(BaseCommand):
    help = "Run an operator-installed task plugin with the existing fenced worker protocol."

    def add_arguments(self, parser):
        parser.add_argument("--worker-id", type=int, required=True)
        parser.add_argument("--plugin-id", required=True)
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2)

    def handle(self, *args, **options):
        if not math.isfinite(options["interval"]) or options["interval"] <= 0:
            raise CommandError("Interval must be finite and positive.")
        worker = Worker.all_objects.filter(pk=options["worker_id"]).first()
        if worker is None:
            raise CommandError("Worker not found.")
        plugin_id = options["plugin_id"]
        try:
            _, digest = definition(plugin_id, worker.tenant_id, "task")
        except PluginError as exc:
            raise CommandError(str(exc)) from None
        if worker.capabilities.get("task_plugin") != plugin_id or worker.capabilities.get("task_plugin_digest") != digest:
            raise CommandError("Worker must be registered for this task plugin and digest.")
        def executor(descriptor, context):
            return execute_task(plugin_id, worker.tenant_id, descriptor, context)
        try:
            while True:
                outcome = execute_one(worker, executor)
                self.stdout.write(str(outcome))
                if options["once"]:
                    return
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("plugin worker stopped")
