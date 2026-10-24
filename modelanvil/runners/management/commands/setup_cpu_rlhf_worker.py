"""Register one operator-owned local CPU reward/RLOO worker without launching a workload."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from modelanvil.device_admission import host_key
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Worker, WorkerPool
from modelanvil.runners.alignment import hf_rlhf
from modelanvil.runners.training.hardware import total_memory_bytes


class Command(BaseCommand):
    help = 'Register a fresh same-host single-slot Apple CPU reward/RLOO worker/pool. Does not import data or train.'

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
        try: observed = hf_rlhf.environment()
        except ValueError as error: raise CommandError(str(error)) from error
        memory = total_memory_bytes()
        if memory is None or memory < hf_rlhf.LIMITS['memory_bytes']:
            raise CommandError('CPU reward/RLOO requires at least 16 GiB of host memory.')
        pool = WorkerPool.all_objects.create(tenant_id=tenant, name=name, status='active')
        worker = Worker.all_objects.create(tenant_id=tenant, pool=pool, name=name, slots=1,
            last_heartbeat_at=timezone.now(), capabilities={'alignment_runtime': hf_rlhf.CONTRACT_DIGEST,
                'gpu_device': 'cpu', 'gpu_packages': hf_rlhf.CONTRACT['packages'],
                'host_key': host_key(), 'memory_bytes': memory})
        worker.capabilities['alignment_worker_id'] = str(worker.pk)
        worker.save(update_fields=['capabilities'])
        self.stdout.write(json.dumps({'worker_id': worker.pk, 'pool_id': pool.pk,
            'runtime': hf_rlhf.RUNTIME_ID, 'contract_digest': hf_rlhf.CONTRACT_DIGEST,
            'accelerator': observed, 'limits': hf_rlhf.LIMITS}, default=str, indent=2))
