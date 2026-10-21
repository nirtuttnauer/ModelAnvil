"""Installed local worker profiles and observed connection readiness."""
import os
from datetime import timedelta

from django.utils import timezone

from modelanvil.identity.models import Tenant, hash_api_key
from modelanvil.jobs.models import Worker, WorkerCredential

PROFILES = {
    "cpu-character": ("CPU character SFT", "modelanvil.runners.training.runtime"),
    "cpu-transformer": ("Small CPU transformer SFT", "modelanvil.runners.training.general_runtime"),
    "model-import": ("Model snapshot acquisition", "modelanvil.runners.model_catalog"),
    "cpu-evaluation": ("CPU candidate evaluation", "modelanvil.runners.eval_worker"),
    "dataset-bank": ("Dataset Bank acquisition", "modelanvil.data.bank.acquisition"),
    "cpu-recipes": ("CPU data recipes", "modelanvil.data.recipe_jobs"),
}
HEARTBEAT_SECONDS = 60
EXECUTOR = "modelanvil.runners.training.executor.training_worker_executor"


def profile_details(profile):
    if profile in ('dataset-bank', 'cpu-recipes'):
        return {'id': profile, 'name': PROFILES[profile][0], 'memory_bytes': 512 * 1024**2,
                'available': True, 'limitations': (
                    ['Downloads qualified pinned sources and verifies their bytes before publication.',
                     'Uses bank_acquisition_records quotas. Upstream downloads require network access.']
                    if profile == 'dataset-bank' else
                    ['Previews and publishes reviewed deterministic recipes on CPU.',
                     'Generation requires the pinned inference packages and a compatible local model.',
                     'Uses recipe_attempts quotas; full runs require a reviewed matching preview.'])}
    if profile == 'cpu-evaluation':
        runtime = profile_runtime(profile)
        return {'id': profile, 'name': PROFILES[profile][0], 'memory_bytes': runtime.MEMORY_BYTES,
                'available': True, 'limitations': ['Up to 64 held-out cases, 32 generated tokens per case, greedy CPU inference.',
                    'Supports verified CPU reference bundles and bounded Safetensors snapshots; production qualification unavailable.']}
    if profile == 'model-import':
        from importlib.util import find_spec
        available = all(find_spec(package) for package in ('requests', 'huggingface_hub', 'filelock'))
        return {'id': profile, 'name': PROFILES[profile][0], 'memory_bytes': 256 * 1024 * 1024,
                'available': available,
                'limitations': ['Downloads approved pinned Hub snapshots into local artifact storage.',
                    'Install requirements.inference.txt in the service environment first.' if not available else
                    'Gated access uses administrator-provisioned project Hub credentials.']}
    runtime = profile_runtime(profile)
    return {'id': profile, 'name': PROFILES[profile][0], 'memory_bytes': runtime.LIMITS['memory_bytes'],
            'available': True, 'limitations': runtime.runner_manifest()['limitations']}


def profile_executor(profile):
    if profile == 'dataset-bank':
        return 'modelanvil.data.bank.acquisition.bank_acquisition_executor'
    if profile == 'cpu-recipes':
        return 'modelanvil.data.recipe_jobs.recipe_executor'
    if profile == 'cpu-evaluation':
        return 'modelanvil.runners.eval_worker.evaluation_worker_executor'
    return 'modelanvil.runners.model_catalog.model_import_executor' if profile == 'model-import' else EXECUTOR


def profile_runtime(profile):
    from importlib import import_module
    return import_module(PROFILES[profile][1])


def credential_active(worker, secret=None):
    credentials = WorkerCredential.all_objects.filter(
        worker=worker, tenant_id=worker.tenant_id, revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    if secret is not None:
        credentials = credentials.filter(secret_hash=hash_api_key(secret))
    return credentials.exists() and Tenant.objects.filter(pk=worker.tenant_id, status="active").exists()


def connection_state(worker):
    if worker.capabilities.get("setup_profile") and not credential_active(worker):
        return "credential_unavailable"
    if worker.last_heartbeat_at is None:
        return "not_connected"
    if worker.status == Worker.Status.OFFLINE:
        return "offline"
    age = (timezone.now() - worker.last_heartbeat_at).total_seconds()
    if not 0 <= age <= HEARTBEAT_SECONDS:
        return "stale"
    return "connected"


def setup_worker_ready(worker):
    # Legacy operator registrations retain their existing admission contract.
    return not worker.capabilities.get("setup_profile") or connection_state(worker) == "connected"


def local_capacity_available(worker):
    if worker.status not in (Worker.Status.AVAILABLE, Worker.Status.BUSY) or worker.drain_requested or worker.slots < 1:
        return False
    if worker.capabilities.get('setup_profile'):
        return setup_worker_ready(worker)
    # Legacy registrations without observations retain their admission contract.
    return worker.last_heartbeat_at is None or connection_state(worker) == 'connected'


def observe_operator_worker(worker):
    """Keep trusted local executors visible while polling without work."""
    values = {"last_heartbeat_at": timezone.now()}
    worker.refresh_from_db()
    if worker.status == Worker.Status.OFFLINE and not worker.claimed_jobs.filter(status="running").exists():
        values["status"] = Worker.Status.AVAILABLE
    Worker.all_objects.filter(pk=worker.pk).update(**values)
    worker.refresh_from_db()


def observe_local_worker(worker, profile, secret):
    """Called by the trusted local process, never by a browser declaration."""
    if worker.capabilities.get("setup_profile") != profile or not credential_active(worker, secret):
        raise ValueError("Worker credential is expired, revoked or bound to a different worker.")
    info = profile_details(profile)
    if not info['available']:
        raise ValueError('Install the required packages for this local worker profile.')
    memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    if memory < info['memory_bytes']:
        raise ValueError("Host memory is below the installed runtime requirement.")
    capabilities = {**worker.capabilities, "memory_bytes": memory, "accelerator": "cpu"}
    if profile == 'dataset-bank':
        capabilities['dataset_acquisition'] = True
    elif profile == 'cpu-recipes':
        from importlib.metadata import PackageNotFoundError, version
        from modelanvil.runners.training.hf_runtime import PACKAGES
        try:
            generation = all(version(name) == pin for name, pin in PACKAGES.items())
        except PackageNotFoundError:
            generation = False
        capabilities.update(recipe_runtime=profile_runtime(profile).runtime_digest(),
                            recipe_device='cpu', recipe_generation=generation)
    elif profile == 'model-import':
        capabilities['model_import'] = True
    elif profile == 'cpu-evaluation':
        runtime = profile_runtime(profile)
        capabilities.update(evaluation_runtime=runtime.CONTRACT_DIGEST, evaluation_build=runtime.BUILD_DIGEST)
    else:
        capabilities['training_runtime'] = profile_runtime(profile).CONTRACT_DIGEST
    values = {"capabilities": capabilities, "last_heartbeat_at": timezone.now()}
    if worker.status == Worker.Status.OFFLINE and not worker.claimed_jobs.filter(status="running").exists():
        values["status"] = Worker.Status.AVAILABLE
    Worker.all_objects.filter(pk=worker.pk).update(**values)
    worker.refresh_from_db()
