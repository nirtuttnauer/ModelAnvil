"""One installation-owned service runs local training for isolated user workspaces."""
import fcntl
import os
from pathlib import Path
import signal
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connection, OperationalError
from django.db.models import Q
from django.utils import timezone

from modelanvil.core.tenancy import reset_context, set_active_tenant
from modelanvil.jobs.executor import execute_one
from modelanvil.jobs.models import Worker, reconcile_expired_leases
from modelanvil.runners.models import LocalTrainingHost
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.runners.training.hardware import total_memory_bytes
from modelanvil.runners.training.managed import verified_model_directory, recommended_source
from modelanvil.runners.guided_evaluation import CONTRACT_DIGEST as EVALUATION_CONTRACT
from modelanvil.runners.eval_worker import BUILD_DIGEST as EVALUATION_BUILD, evaluation_worker_executor


def managed_workers():
    return Worker.all_objects.filter(capabilities__managed_local=True).filter(
        Q(capabilities__training_runtime=hf_runtime.CONTRACT_DIGEST)
        | Q(capabilities__evaluation_runtime=EVALUATION_CONTRACT, capabilities__evaluation_build=EVALUATION_BUILD))


class Command(BaseCommand):
    help = 'Run the managed local GPU service. End users launch training through the browser.'

    def add_arguments(self, parser):
        parser.add_argument('--device', default='mps:0')
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        root = Path(settings.MODELANVIL['artifact_root'])
        root.mkdir(parents=True, exist_ok=True)
        with (root / 'managed-training.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CommandError('A managed training service is already running for this installation.') from None
            self.run_service(options)

    def run_service(self, options):
        host, _ = LocalTrainingHost.objects.get_or_create(name='local')
        LocalTrainingHost.objects.filter(pk=host.pk).update(status='starting', error='', last_heartbeat_at=timezone.now())
        stopped = threading.Event()
        state = {'status': 'starting'}
        build = hf_runtime.build_digest()

        def heartbeat():
            try:
                while not stopped.is_set():
                    close_old_connections()
                    try:
                        LocalTrainingHost.objects.filter(pk=host.pk).update(status=state['status'], last_heartbeat_at=timezone.now())
                        workers = managed_workers()
                        if state['status'] in ('ready', 'training'):
                            workers.filter(status='offline', drain_requested=False).update(status='available')
                            workers.update(last_heartbeat_at=timezone.now())
                    except OperationalError as exc:
                        if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                            raise
                        # Initial pinned model registration can hold SQLite's writer lock beyond one heartbeat.
                    stopped.wait(2)
            finally:
                close_old_connections()

        previous_term = signal.getsignal(signal.SIGTERM)
        def stop_service(signum, frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, stop_service)
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            hf_runtime.require_packages()
            observed = hf_runtime.observed_device(options['device'])
            memory = total_memory_bytes()
            if not memory or memory < hf_runtime.LIMITS['memory_bytes']:
                raise ValueError('Local training requires at least 8 GiB host memory.')
            LocalTrainingHost.objects.filter(pk=host.pk).update(device=observed['device']['id'], memory_bytes=memory)
            if recommended_source() == hf_runtime.LARGE_GUIDED_SOURCE:
                hf_runtime.require_adapter_package()
            verified_model_directory(download=True)
            LocalTrainingHost.objects.filter(pk=host.pk).update(device=observed['device']['id'], memory_bytes=memory,
                build_digest=build, status='ready', error='', last_heartbeat_at=timezone.now())
            state['status'] = 'ready'
            self.stdout.write('Managed local training is ready. Users can fine-tune from the browser.')
            while True:
                close_old_connections()
                if hf_runtime.build_digest() != build:
                    raise ValueError('Training code changed. Restart ModelAnvil to use the updated runtime.')
                claimed = False
                try:
                    reconcile_expired_leases()
                    workers = managed_workers().order_by('last_heartbeat_at', 'pk')
                    for worker in workers:
                        reset_context()
                        set_active_tenant(worker.tenant_id)
                        if worker.status == 'offline' and not worker.drain_requested:
                            Worker.all_objects.filter(pk=worker.pk).update(status='available')
                            worker.refresh_from_db()
                        state['status'] = 'training'
                        executor = evaluation_worker_executor if worker.capabilities.get('evaluation_runtime') == EVALUATION_CONTRACT else training_worker_executor
                        outcome = execute_one(worker, executor)
                        state['status'] = 'ready'
                        if outcome.get('claimed'):
                            self.stdout.write(f'Training job finished: {outcome.get("status", "unknown")}')
                            claimed = True
                            break
                except OperationalError as exc:
                    if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower():
                        raise
                    state['status'] = 'ready'
                    if options['once']:
                        raise CommandError('The local database is busy; retry after workspace preparation finishes.') from None
                if options['once']:
                    return
                if not claimed:
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write('Managed local training stopped.')
        except Exception as exc:
            state['status'] = 'error'
            # Fixed errors from runtime checks are safe; third-party download diagnostics stay in logs.
            message = str(exc) if isinstance(exc, ValueError) else 'Local model preparation failed. Check the installation service and retry.'
            LocalTrainingHost.objects.filter(pk=host.pk).update(error=message[:400])
            raise CommandError(message) from None
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            stopped.set()
            thread.join(timeout=5)
            LocalTrainingHost.objects.filter(pk=host.pk).update(status=state['status'] if state['status'] == 'error' else 'offline',
                last_heartbeat_at=timezone.now())
            Worker.all_objects.filter(capabilities__managed_local=True).update(status='offline')
            reset_context()
