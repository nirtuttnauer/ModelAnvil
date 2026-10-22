import math
import time

from django.core.management.base import BaseCommand, CommandError
from modelanvil.compute.models import ComputeAllocation
from modelanvil.compute.service import reconcile


class Command(BaseCommand):
    help = "Reconcile owned compute and release expired allocations. Run continuously for automatic cleanup."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval", type=float, default=30)

    def handle(self, *args, **options):
        if not math.isfinite(options["interval"]) or options["interval"] <= 0:
            raise CommandError("Interval must be finite and positive.")
        try:
            while True:
                count = 0
                rows = ComputeAllocation.all_objects.exclude(state__in=("released", "failed"))
                for allocation in rows.iterator():
                    reconcile(allocation)
                    count += 1
                self.stdout.write(f"reconciled={count}")
                if not options["loop"]:
                    return
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("compute reconciler stopped")
