"""Remove retained staging parts for terminal upload sessions."""
from django.core.management.base import BaseCommand, CommandError

from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.artifacts.transfers import prune_transfer_parts


class Command(BaseCommand):
    help = "Purge terminal transfer part objects after an explicit retention period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retention-days",
            type=int,
            required=True,
            help="Keep transfer part objects for at least this many days after terminal state.",
        )

    def handle(self, *args, **options):
        retention_days = options["retention_days"]
        if retention_days < 1:
            raise CommandError("--retention-days must be at least 1")
        result = prune_transfer_parts(
            retention_days=retention_days,
            backend=artifact_storage_backend(),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged parts for {result['sessions_purged']} transfer sessions "
                f"({result['parts_purged']} part objects)."
            )
        )
