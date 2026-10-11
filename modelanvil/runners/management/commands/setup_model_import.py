"""Register an operator-owned local acquisition worker and optionally run it."""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from modelanvil.core.tenancy import set_active_tenant
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Worker, WorkerPool


class Command(BaseCommand):
    help = 'Create a local model import pool; --run polls approved Hub import jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', required=True)
        parser.add_argument('--name', default='Local model imports')
        parser.add_argument('--run', action='store_true')
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(tenant_id=options['tenant_id'])
        except (Tenant.DoesNotExist, ValueError):
            raise CommandError('Select an existing tenant UUID.') from None
        if not tenant.is_active():
            raise CommandError('Tenant must be active.')
        set_active_tenant(tenant.pk)
        pool, _ = WorkerPool.all_objects.get_or_create(tenant_id=tenant.pk, name=options['name'],
            defaults={'queue_name': f'model-imports-{tenant.pk}'})
        worker, _ = Worker.all_objects.get_or_create(tenant_id=tenant.pk, pool=pool, name='local-model-import',
            defaults={'slots': 1, 'capabilities': {'model_import': True}})
        if pool.status != 'active' or worker.capabilities != {'model_import': True}:
            raise CommandError('Existing pool/worker differs; choose a new name or repair its configuration.')
        self.stdout.write(f'pool={pool.pk} worker={worker.pk}')
        if options['run']:
            call_command('run_worker', worker_id=worker.pk, executor='modelanvil.runners.model_catalog.model_import_executor',
                         once=options['once'], interval=2, stdout=self.stdout)
