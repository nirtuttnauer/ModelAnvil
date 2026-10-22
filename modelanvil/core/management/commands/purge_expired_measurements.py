"""Apply each project's declared retention to content-free interaction measurements."""
from datetime import timedelta
import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from modelanvil.core.models import ActivationEvent
from modelanvil.core.privacy import project_policy
from modelanvil.identity.models import Project


class Command(BaseCommand):
    help = 'Preview expired local interaction events. Use --apply to delete them; product data and decisions are retained.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        count = 0
        for project in Project.all_objects.all().iterator():
            days = project_policy(project.tenant_id, project.pk)['measurement_retention_days']
            expired = ActivationEvent.all_objects.filter(tenant_id=project.tenant_id, project=project,
                created_at__lt=timezone.now()-timedelta(days=days))
            count += expired.count()
            if options['apply']:
                expired.delete()
        self.stdout.write(json.dumps({'expired_measurements': count, 'deleted': options['apply']}))
