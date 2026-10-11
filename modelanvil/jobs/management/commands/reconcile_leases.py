"""Periodically return capacity from workers whose execution leases expired."""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from modelanvil.jobs.models import reconcile_expired_leases


class Command(BaseCommand):
    help = "Reconcile expired worker leases and requeue or fail their jobs."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Poll continuously instead of running once.")
        parser.add_argument("--interval", type=float, default=5.0, help="Seconds between reconciliation passes.")

    def handle(self, *args, **options):
        interval = options["interval"]
        if interval <= 0:
            raise CommandError("--interval must be positive")

        try:
            while True:
                count = reconcile_expired_leases()
                self.stdout.write(f"reconciled={count}")
                if not options["loop"]:
                    return
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("lease reconciler stopped")
