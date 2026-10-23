"""Register one operator-owned local MPS DPO worker without launching a workload."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from modelanvil.device_admission import host_key
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Worker, WorkerPool
from modelanvil.runners.alignment import mps_dpo
from modelanvil.runners.training.hardware import total_memory_bytes


class Command(BaseCommand):
    help = 'Register a fresh same-host single-slot Apple MPS DPO worker/pool. Does not import data or train.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=uuid.UUID, required=True)
        parser.add_argument('--name', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        tenant, name = options['tenant_id'], options['name'].strip()
        if not name or len(name) > 80 or not Tenant.objects.filter(pk=tenant, status='active').exists():
            raise CommandError('Select an active tenant and a new 1–80 character pool name.')
        if WorkerPool.all_objects.filter(tenant_id=tenant, name=name).exists():
            raise CommandError('This pool name is already registered; select a new name.')
        try: observed = mps_dpo.environment()
        except ValueError as error: raise CommandError(str(error)) from error
        memory = total_memory_bytes()
        if memory is None or memory < mps_dpo.LIMITS['memory_bytes']:
            raise CommandError('MPS DPO requires at least 8 GiB of host memory.')
        pool = WorkerPool.all_objects.create(tenant_id=tenant, name=name, status='active')
        worker = Worker.all_objects.create(tenant_id=tenant, pool=pool, name=name, slots=1,
            last_heartbeat_at=timezone.now(), capabilities={'alignment_runtime': mps_dpo.CONTRACT_DIGEST,
                'gpu_device': 'mps:0', 'gpu_packages': mps_dpo.CONTRACT['packages'],
                'host_key': host_key(), 'memory_bytes': memory})
        worker.capabilities['alignment_worker_id'] = str(worker.pk)
        worker.save(update_fields=['capabilities'])
        self.stdout.write(json.dumps({'worker_id': worker.pk, 'pool_id': pool.pk,
            'runtime': mps_dpo.RUNTIME_ID, 'contract_digest': mps_dpo.CONTRACT_DIGEST,
            'accelerator': observed, 'limits': mps_dpo.LIMITS}, default=str, indent=2))
