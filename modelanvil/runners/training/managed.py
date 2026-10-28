"""Trusted local service prepares pinned resources; browser requests cannot select code or paths."""
import hashlib
import io
import json
from pathlib import Path
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.identity.models import Project
from modelanvil.jobs.models import Worker, WorkerPool
from modelanvil.runners.models import LocalTrainingHost, Model, ModelVersion, RunnerManifest, TokenizerVersion
from modelanvil.runners.training import hf_runtime


def host_status():
    host = LocalTrainingHost.objects.filter(name='local').first()
    fresh = bool(host and host.last_heartbeat_at and 0 <= (timezone.now() - host.last_heartbeat_at).total_seconds() <= 15)
    available = bool(fresh and host.status in ('ready', 'training') and host.build_digest == hf_runtime.build_digest())
    return {'available': available, 'busy': bool(available and host.status == 'training'),
            'device': host.device if available else None,
            'memory_bytes': host.memory_bytes if available and host.memory_bytes > 0 else None,
            'memory_observed_at': host.last_heartbeat_at if available else None,
            'memory_basis': 'Observed total system memory; currently free memory is not reported.',
            'message': 'Your computer is training another model. You can prepare your dataset while it finishes.' if available and host.status == 'training'
                       else 'Training runs on this computer. No server commands or cloud account needed.' if available
                       else host.error if fresh and host.error else 'Local training is offline. The installation owner needs to start ModelAnvil with its managed training service.'}


def recommended_source():
    host = LocalTrainingHost.objects.filter(name='local').first()
    return hf_runtime.LARGE_GUIDED_SOURCE if host and host.device.startswith('mps:') and host.memory_bytes >= 32 * 1024**3 else hf_runtime.GUIDED_SOURCE


def verified_model_directory(*, download=False):
    source = recommended_source()
    directory = Path(settings.MODELANVIL_LOCAL_MODEL_DIR or (settings.BASE_DIR / 'data' / source['repo_id'].split('/')[-1].lower()))
    hashes = hf_runtime.LARGE_GUIDED_FILE_HASHES if source == hf_runtime.LARGE_GUIDED_SOURCE else hf_runtime.GUIDED_FILE_HASHES
    for name, expected in hashes.items():
        path = directory / name
        if not path.exists() and download:
            from modelanvil.core.privacy import acquisition_scope, require_destination, install_hub_guard
            from huggingface_hub import hf_hub_download
            with acquisition_scope(None, None, public_provisioning=True):
                require_destination('https://huggingface.co')
                install_hub_guard()
                hf_hub_download(source['repo_id'], name, revision=source['revision'],
                                local_dir=directory, token=False)
        try:
            maximum = hf_runtime.LIMITS['weight_bytes'] if name.endswith('.safetensors') else hf_runtime.LIMITS['aux_bytes']
            if not 1 <= path.stat().st_size <= maximum:
                raise ValueError('The bundled model exceeds its verified file limits.')
            sha = hashlib.sha256()
            with path.open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    sha.update(block)
            if sha.hexdigest() != expected:
                raise ValueError('The bundled model checksum changed. Restore the pinned SmolLM2 snapshot.')
        except OSError:
            raise ValueError('The pretrained model is unavailable. The managed service will prepare it before training.') from None
    return directory


def _store(tenant, project, name, payload=None, path=None):
    sha = hashlib.sha256()
    if path is not None:
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                sha.update(block)
        size = path.stat().st_size
    else:
        sha.update(payload)
        size = len(payload)
    artifact = Artifact.all_objects.create(tenant_id=tenant, project_id=project, storage_location_id='local',
        object_key=f'managed-models/{uuid.uuid4()}/{name}', sha256=sha.hexdigest(), byte_size=size,
        media_type='application/octet-stream' if path else 'application/json')
    if path is not None:
        with path.open('rb') as stream:
            upload_staged_artifact(artifact, stream, backend=artifact_storage_backend())
    else:
        upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
    return artifact


def prepare_resources(tenant, project, *, allow_new_allowance=True):
    if not host_status()['available']:
        raise ValueError(host_status()['message'])
    if not allow_new_allowance and not BudgetPolicy.all_objects.filter(tenant_id=tenant, name='Guided training allowance').exists():
        raise ValueError('The workspace owner needs to enable its guided training allowance before you can train.')
    hf_runtime.require_packages()
    source = recommended_source()
    large = source == hf_runtime.LARGE_GUIDED_SOURCE
    if large:
        hf_runtime.require_adapter_package()
    directory = verified_model_directory()
    host = LocalTrainingHost.objects.get(name='local')
    observed = hf_runtime.observed_device(host.device)
    if not hasattr(artifact_storage_backend(), 'root'):
        raise ValueError('Managed local training requires local artifact storage.')
    # Project locking prevents duplicate model registration on retry or a second tab.
    with transaction.atomic():
        scope = Project.all_objects.select_for_update().get(pk=project, tenant_id=tenant)
        name = f'Managed {source["repo_id"].split("/")[-1]} · {scope.pk}'
        model, _ = Model.all_objects.get_or_create(tenant_id=tenant, project_id=project, name=name,
            defaults={'description': 'Instruction-tuned SmolLM2 for guided local fine-tuning.', 'intended_tasks': ['text_generation']})
        base = ModelVersion.all_objects.filter(tenant_id=tenant, project_id=project, model=model, revision_no=1).first()
        if base is None:
            files = {filename: hf_runtime.file_ref(_store(tenant, project, filename, path=directory / filename))
                     for filename in hf_runtime.FILE_HASHES}
            manifest = _store(tenant, project, 'snapshot.json', payload=json.dumps({'source': source, 'files': files}, sort_keys=True).encode())
            spec = hf_runtime._tokenizer(directory)
            tokenizer = TokenizerVersion.all_objects.create(tenant_id=tenant, project_id=project,
                name=f'{source["repo_id"].split("/")[-1]} matching tokenizer', vocabulary_size=len(spec), compatibility={'hf_snapshot': source},
                chat_template=getattr(spec, 'chat_template', '') or '',
                special_tokens={k: v for k, v in spec.special_tokens_map.items() if isinstance(v, str)})
            base = ModelVersion.all_objects.create(tenant_id=tenant, project_id=project, model=model, revision_no=1,
                tokenizer=tokenizer, architecture_ref=hf_runtime.RUNTIME_ID, artifact_manifest_id=str(manifest.artifact_id),
                license_evidence='Apache-2.0', metadata={'snapshot_manifest': hf_runtime.file_ref(manifest),
                    'vocab_size': len(spec), 'source': source, 'managed_local': True})
        if base.architecture_ref != hf_runtime.RUNTIME_ID or base.metadata.get('source') != source:
            raise ValueError('The managed base model registration changed. Restore its verified source.')
        value = hf_runtime.runner_manifest()
        runner, _ = RunnerManifest.all_objects.get_or_create(tenant_id=tenant, digest=hf_runtime.digest(value),
            defaults={'name': 'Managed local fine-tuning', 'version': hf_runtime.CONTRACT_DIGEST[:12], 'manifest': value,
                      'compatibility': {'contract_digest': hf_runtime.CONTRACT_DIGEST}})
        pool, _ = WorkerPool.all_objects.get_or_create(tenant_id=tenant, name=f'Managed local fine-tuning · {hf_runtime.CONTRACT_DIGEST[:8]}')
        worker, created = Worker.all_objects.get_or_create(tenant_id=tenant, name=pool.name, pool=pool,
            defaults={'slots': 1, 'last_heartbeat_at': timezone.now(), 'capabilities': {
                'managed_local': True, 'training_runtime': hf_runtime.CONTRACT_DIGEST, 'memory_bytes': host.memory_bytes,
                'gpu_backend': observed['device']['backend'], 'gpu_device': observed['device']['id'], 'gpu_packages': hf_runtime.PACKAGES}})
        if not worker.capabilities.get('managed_local') or worker.capabilities.get('training_runtime') != hf_runtime.CONTRACT_DIGEST:
            raise ValueError('The managed worker registration changed. Restart local training to repair its runtime.')
        policy, _ = BudgetPolicy.all_objects.get_or_create(tenant_id=tenant, name='Guided training allowance',
            defaults={'unit': 'training_steps', 'period': 'lifetime', 'limit_amount': 10000})
        if pool.status != 'active' or not runner.enabled or not policy.enabled or policy.unit != 'training_steps':
            raise ValueError('Managed compute or its training allowance has been paused by the workspace owner.')
        return {'project': str(project), 'execution_mode': 'worker', 'recipe_type': 'lora_adapter' if large else 'full_sft',
                'base_model_version': base.pk, 'tokenizer_version': base.tokenizer_id,
                'runner_manifest': runner.pk, 'pool': pool.pk, 'budget_policy_id': str(policy.policy_id),
                'initialization_seed': 42}
