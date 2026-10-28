"""Operator-installed local specialist worker; no caller-provided executable."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from modelanvil.jobs.executor import execute_one
from modelanvil.jobs.models import Worker, WorkerPool
from modelanvil.jobs.setup import observe_operator_worker
from modelanvil.runners.specialist_jobs import runtime_digest, specialist_executor
from modelanvil.runners.specialists import RUNTIME


class Command(BaseCommand):
    help = 'Register and run a pinned specialist worker for one local device.'

    def add_arguments(self, parser):
        parser.add_argument('--pool-id', type=int, required=True)
        parser.add_argument('--name', required=True)
        parser.add_argument('--device', choices=['cpu','mps:0','mlx:0'], required=True)
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        pool = WorkerPool.all_objects.filter(pk=options['pool_id'], status='active', result_egress='envelope').first()
        if pool is None or not 1 <= len(options['name'].strip()) <= 200:
            raise CommandError('Select an active envelope pool and a bounded worker name.')
        python = getattr(settings, 'MODELANVIL_SPECIALIST_PYTHON', None) or os.environ.get('MODELANVIL_SPECIALIST_PYTHON')
        if not python or not Path(python).is_absolute() or not Path(python).is_file():
            raise CommandError('Configure the isolated MODELANVIL_SPECIALIST_PYTHON first.')
        with tempfile.TemporaryDirectory(prefix='modelanvil-specialist-probe-') as directory:
            result = subprocess.run([python, '-I', str(RUNTIME), '--probe', options['device']],
                cwd=directory, env={'PATH':os.defpath, 'HOME':directory, 'TMPDIR':directory, 'HF_HUB_OFFLINE':'1'},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode or json.loads(result.stdout).get('device') != options['device']:
            raise CommandError('The pinned specialist runtime or device probe failed.')
        worker, created = Worker.all_objects.get_or_create(tenant_id=pool.tenant_id, name=options['name'].strip(),
            defaults={'pool':pool, 'capabilities':{'specialist_runtime':runtime_digest(), 'specialist_device':options['device']}})
        if not created and (worker.pool_id != pool.pk or worker.capabilities !=
                {'specialist_runtime':runtime_digest(), 'specialist_device':options['device']}):
            raise CommandError('Existing worker identity differs; use a new worker name.')
        self.stdout.write(f'worker_id={worker.pk} device={options["device"]}')
        try:
            while True:
                observe_operator_worker(worker)
                outcome = execute_one(worker, specialist_executor)
                if outcome.get('claimed'):
                    self.stdout.write(json.dumps(outcome))
                if options['once']:
                    return
                if not outcome.get('claimed'):
                    time.sleep(2)
        except KeyboardInterrupt:
            self.stdout.write('Specialist worker stopped.')
        finally:
            Worker.all_objects.filter(pk=worker.pk).update(status=Worker.Status.OFFLINE)
