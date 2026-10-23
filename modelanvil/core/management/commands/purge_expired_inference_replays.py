"""Preview or remove completed inference replay bodies outside their replay window."""
from datetime import timedelta
import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from modelanvil.core.models import IdempotencyKey
from modelanvil.runners.inference_replay import RETENTION_SECONDS


class Command(BaseCommand):
    help = 'Preview expired completed inference replay records. --apply deletes replay bodies, preserving measured inference history and pending keys.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        expired = IdempotencyKey.all_objects.filter(principal__startswith='inference:',
            completed_at__lt=timezone.now() - timedelta(seconds=RETENTION_SECONDS))
        count = expired.count()
        if options['apply']:
            expired.delete()
        self.stdout.write(json.dumps({'expired_inference_replays': count, 'deleted': options['apply']}))
