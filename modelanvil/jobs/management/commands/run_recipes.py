"""Run a trusted recipe worker against the existing durable claim protocol."""
import importlib.metadata
import time

from django.core.management.base import BaseCommand, CommandError
from modelanvil.data.recipe_jobs import recipe_executor, runtime_digest
from modelanvil.jobs.executor import execute_one
from modelanvil.jobs.models import Worker, WorkerPool


class Command(BaseCommand):
    help='Register and run a local deterministic/generation recipe worker.'

    def add_arguments(self,parser):
        parser.add_argument('--pool-id',type=int,required=True)
        parser.add_argument('--name',required=True)
        parser.add_argument('--device',choices=['cpu','mps:0','mlx:0'],default='cpu')
        parser.add_argument('--once',action='store_true')

    def handle(self,*args,**options):
        pool=WorkerPool.all_objects.filter(pk=options['pool_id'],status='active',result_egress='envelope').first()
        if pool is None or not 1<=len(options['name'].strip())<=200:raise CommandError('Select an active envelope pool and bounded worker name.')
        device=options['device'];generation=False
        try:
            from modelanvil.runners.training.hf_runtime import PACKAGES
            if device=='mlx:0':
                import mlx.core as mx
                import mlx_lm
                generation=mx.metal.is_available()
            else:
                generation=all(importlib.metadata.version(k)==v for k,v in PACKAGES.items())
                if device=='mps:0':
                    import torch
                    generation=generation and torch.backends.mps.is_available()
        except (ImportError,importlib.metadata.PackageNotFoundError):
            generation=False
        if device!='cpu' and not generation:raise CommandError('The selected generation device or pinned packages are unavailable.')
        capabilities={'recipe_runtime':runtime_digest(),'recipe_device':device,'recipe_generation':generation}
        worker,created=Worker.all_objects.get_or_create(tenant_id=pool.tenant_id,name=options['name'].strip(),
            defaults={'pool':pool,'capabilities':capabilities})
        if not created and (worker.pool_id!=pool.pk or worker.capabilities!=capabilities):
            raise CommandError('Existing worker identity differs; use a new worker name.')
        self.stdout.write(f'worker_id={worker.pk} device={device} generation={int(generation)}')
        try:
            while True:
                result=execute_one(worker,recipe_executor)
                if result.get('claimed'):self.stdout.write(str(result))
                if options['once']:return
                if not result.get('claimed'):time.sleep(2)
        except KeyboardInterrupt:self.stdout.write('Recipe worker stopped.')
