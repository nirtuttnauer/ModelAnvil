"""Public Hub discovery and immutable, tenant-scoped model acquisition."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.models import Model, ModelImport, ModelVersion, TokenizerVersion
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.runtime import digest

MAX_BYTES = 8 * 1024**3
MAX_FILES = 64
AUX_NAMES = {'config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json',
             'special_tokens_map.json', 'tokenizer.model', 'vocab.json', 'merges.txt',
             'model.safetensors.index.json', 'adapter_config.json', 'preprocessor_config.json',
             'processor_config.json', 'chat_template.jinja', 'rl_agent_config.json'}
SPECIALIST_NAMES = {'encoder/config.json', 'tokenizer/tokenizer.json', 'tokenizer/tokenizer_config.json'}


def repo_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value) or '..' in value:
        raise ValueError('Use a Hub model ID in owner/model form.')
    return value


def revision_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{40}', value):
        raise ValueError('Select an immutable 40-character commit revision.')
    return value


def hub_token(tenant, project):
    # Never inherit a workstation's ambient Hub token across tenants/projects.
    return getattr(settings, 'MODELANVIL_HUB_TOKENS', {}).get(f'{tenant}:{project}', False)


def hub_client(tenant, project):
    from huggingface_hub import HfApi
    return HfApi(endpoint='https://huggingface.co', token=hub_token(tenant, project), library_name='modelanvil')


def search_models(query, tenant, project):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120:
        raise ValueError('Search with 1–120 characters.')
    try:
        rows = hub_client(tenant, project).list_models(search=query.strip(), limit=20, cardData=True, fetch_config=True)
        return [{'repo_id': m.id, 'revision': m.sha, 'task': m.pipeline_tag,
                 'license': (m.card_data or {}).get('license'), 'gated': bool(m.gated),
                 'downloads': m.downloads, 'architecture': (m.config or {}).get('model_type')} for m in rows]
    except Exception as exc:
        raise ValueError('Model discovery is unavailable; check Hub access and connectivity.') from exc


def filename_allowed(name):
    if isinstance(name, str) and name in SPECIALIST_NAMES:
        return True
    return isinstance(name, str) and '/' not in name and '\\' not in name and '..' not in name and (
        name in AUX_NAMES or re.fullmatch(r'(?:model(?:-\d{5}-of-\d{5})?|adapter_model|adapters)\.safetensors', name)
        or re.fullmatch(r'[A-Za-z0-9_.-]{1,160}\.gguf', name))


def inspect_model(identifier, revision, tenant, project, *, format='safetensors', filename=None):
    identifier, revision = repo_id(identifier), revision_id(revision)
    if format not in {'safetensors', 'gguf', 'mlx'}:
        raise ValueError('Select Safetensors, GGUF or MLX.')
    try:
        info = hub_client(tenant, project).model_info(identifier, revision=revision, files_metadata=True, timeout=15)
    except Exception as exc:
        raise ValueError('Pinned model metadata is unavailable; check revision and scoped Hub access.') from exc
    if info.sha != revision:
        raise ValueError('Hub returned a different model revision.')
    files = {}
    for item in info.siblings:
        name = item.rfilename
        if not filename_allowed(name):
            continue
        if format == 'gguf' and name != filename or format in {'safetensors', 'mlx'} and name.endswith('.gguf'):
            continue
        size = item.size
        if type(size) is not int or size <= 0:
            raise ValueError('Selected model files need declared positive byte sizes.')
        lfs = item.lfs
        files[name] = {'byte_size': size, 'sha256': getattr(lfs, 'sha256', None) if lfs else None}
    if format in {'safetensors', 'mlx'} and ('config.json' not in files or not any(n.endswith('.safetensors') for n in files)):
        raise ValueError('The snapshot needs a configuration and safe model weights; pickle/remote code are not imported.')
    if not files or len(files) > MAX_FILES or sum(f['byte_size'] for f in files.values()) > MAX_BYTES:
        raise ValueError('Select a model with at most 64 files and 8 GiB of imported bytes.')
    if any(f['byte_size'] > 8 * 1024**2 for n, f in files.items() if not n.endswith(('.safetensors', '.gguf'))):
        raise ValueError('Auxiliary model files must fit within 8 MiB.')
    license_expression = (info.card_data or {}).get('license')
    if not isinstance(license_expression, str) or not license_expression:
        raise ValueError('Record model license evidence before importing this snapshot.')
    return {'repo_id': identifier, 'revision': revision, 'format': format, 'files': files,
            'byte_size': sum(v['byte_size'] for v in files.values()), 'license': license_expression,
            'gated': bool(info.gated), 'task': info.pipeline_tag,
            'architecture': (info.config or {}).get('model_type'),
            'parameters_count': getattr(info.safetensors, 'total', None),
            'training_supported': identifier == hf_runtime.SOURCE['repo_id'] and revision == hf_runtime.SOURCE['revision'] and format == 'safetensors'}


@transaction.atomic
def launch_import(plan, *, name, tenant, project, pool, idempotency_key, accepted_license):
    from modelanvil.jobs.models import Job, Worker
    if not project or not check_resource_access(project, getattr(project, 'pk', project), tenant):
        raise ValueError('Select an accessible project for model acquisition.')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 180 or not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
        raise ValueError('Provide a model name and an idempotency key.')
    if accepted_license != plan['license']:
        raise ValueError('Confirm the exact model license shown in the preview.')
    project_id = getattr(project, 'pk', project)
    fingerprint = digest({'plan': plan, 'name': name.strip(), 'pool': pool.pk})
    prior = ModelImport.all_objects.select_for_update().filter(tenant_id=tenant, project_id=project_id, idempotency_key=idempotency_key).first()
    if prior:
        if prior.input_digest != fingerprint:
            raise ValueError('This idempotency key belongs to different import inputs.')
        return prior
    if str(pool.tenant_id) != str(tenant) or pool.status != 'active' or not Worker.all_objects.filter(
            tenant_id=tenant, pool=pool, status__in=['available', 'busy'], capabilities__model_import=True).exists():
        raise ValueError('Select an active pool with a model-import worker.')
    item = ModelImport.all_objects.create(tenant_id=tenant, project_id=project_id, name=name.strip(),
        repo_id=plan['repo_id'], revision=plan['revision'], format=plan['format'], license_expression=plan['license'],
        files=plan['files'], input_digest=fingerprint, idempotency_key=idempotency_key)
    item.job = Job.all_objects.create(tenant_id=tenant, pool=pool, name=f'Import {name.strip()}',
        payload={'type': 'model_import', 'import_id': str(item.import_id)},
        requirements={'slots': 1, 'model_import': True})
    item.save(update_fields=['job', 'updated_at'])
    return item


def _locked_live_import(context, identifier):
    from modelanvil.jobs.models import Job, JobAttempt
    attempt = JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job = Job.all_objects.select_for_update().get(pk=attempt.job_id)
    if (attempt.status != 'running' or job.status != 'running' or attempt.fencing_token != context.fencing_token
        or job.fencing_token != context.fencing_token or job.claimed_by_id != attempt.worker_id
        or not attempt.lease_expires_at or attempt.lease_expires_at <= timezone.now()
        or job.desired_action == 'cancel'):
        raise ValueError('Model import lost its lease or was cancelled; publication refused.')
    return ModelImport.all_objects.select_for_update().get(import_id=identifier, job=job, tenant_id=job.tenant_id)


def _store(stream, *, tenant, project, name, expected=None, size=None, metadata=None, media_type='application/octet-stream'):
    sha, length = hashlib.sha256(), 0
    while block := stream.read(1024 * 1024):
        length += len(block)
        if length > MAX_BYTES or size is not None and length > size:
            raise ValueError('Model bytes exceed the declared import limit.')
        sha.update(block)
    if size is not None and length != size or expected and sha.hexdigest() != expected:
        raise ValueError('Model file checksum or byte size does not match the pinned snapshot.')
    stream.seek(0)
    artifact = Artifact.all_objects.create(tenant_id=tenant, project_id=project, storage_location_id='local',
        object_key=f'model-imports/{uuid.uuid4()}/{name}', sha256=sha.hexdigest(), byte_size=length,
        media_type=media_type, metadata=metadata or {})
    upload_staged_artifact(artifact, stream, backend=artifact_storage_backend())
    return hf_runtime.file_ref(artifact)


def publish_files(files, *, tenant, project, name, source, format, license_expression):
    """Called under a transaction/fence; bytes were verified before entering the manifest."""
    if format in {'ocr', 'laya'}:
        from modelanvil.runners.specialists import publish_specialist
        return publish_specialist(files, tenant=tenant, project=project, name=name,
            kind=format, license_expression=license_expression)
    from modelanvil.runners.inference import staged_snapshot
    vocab, template, config = 1, '', {}
    if format in {'safetensors', 'mlx'}:
        with staged_snapshot(files, tenant, project) as directory:
            from transformers import AutoConfig, AutoTokenizer
            from safetensors import safe_open
            for filename in files:
                if filename.endswith('.safetensors'):
                    try:
                        with safe_open(directory / filename, framework='pt', device='cpu') as weights:
                            if not list(weights.keys()):
                                raise ValueError('Model weights are empty.')
                    except Exception:
                        raise ValueError('Safetensors weights are incomplete, corrupt or empty.') from None
            parsed = AutoConfig.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
            spec = AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
            vocab, template, config = len(spec), spec.chat_template or '', parsed.to_dict()
            if getattr(parsed, 'auto_map', None):
                raise ValueError('Remote-code model architectures are not supported.')
    elif format == 'gguf':
        with staged_snapshot(files, tenant, project) as directory:
            if len(files) != 1:
                raise ValueError('Import one GGUF file.')
            with (directory / next(iter(files))).open('rb') as stream:
                if stream.read(4) != b'GGUF' or int.from_bytes(stream.read(4), 'little') not in (2, 3):
                    raise ValueError('GGUF header is invalid or unsupported.')
    else:
        raise ValueError('Unsupported model format.')
    if (source.get('repo_id') == hf_runtime.SOURCE['repo_id'] and source.get('revision') == hf_runtime.SOURCE['revision']
            and all(files.get(n, {}).get('sha256') == sha for n, sha in hf_runtime.FILE_HASHES.items())):
        source = dict(hf_runtime.SOURCE)
    tok = TokenizerVersion.all_objects.create(tenant_id=tenant, project_id=project,
        name=f'{name} tokenizer {uuid.uuid4().hex[:8]}', vocabulary_size=vocab, chat_template=template,
        configuration_digest=digest({n: v for n, v in files.items() if not n.endswith(('.safetensors', '.gguf'))}),
        compatibility={**({'hf_snapshot': source} if source == hf_runtime.SOURCE else {'model_snapshot': source}), 'immutable_import': True})
    logical = Model.all_objects.create(tenant_id=tenant, project_id=project, name=name, intended_tasks=['text_generation'])
    manifest = {'source': source, 'files': files, 'format': format}
    ref = _store(io.BytesIO(json.dumps(manifest, sort_keys=True).encode()), tenant=tenant, project=project, name='snapshot.json')
    architecture = hf_runtime.RUNTIME_ID if source == hf_runtime.SOURCE and format == 'safetensors' else f'modelanvil.{format}.v1'
    return ModelVersion.all_objects.create(tenant_id=tenant, project_id=project, model=logical, tokenizer=tok,
        architecture_ref=architecture, artifact_manifest_id=ref['artifact_id'], license_evidence=license_expression[:64],
        metadata={'source': source, 'snapshot_manifest': ref, 'format': format, 'vocab_size': vocab, 'configuration': config,
                  'license_expression': license_expression, 'imported': True, 'load_tested': False})


def download_file(item, name, pin, context):
    """Resume pinned HTTP bytes; short read timeouts keep cancellation bounded."""
    import requests
    from filelock import FileLock
    from huggingface_hub import hf_hub_url
    backend = artifact_storage_backend()
    if not hasattr(backend, 'root'):
        raise ValueError('Model acquisition requires local filesystem storage.')
    cache = backend.root / '.model-cache' / str(item.tenant_id) / str(item.project_id) / item.revision
    cache.mkdir(parents=True, exist_ok=True)
    if not cache.resolve().is_relative_to(backend.root):
        raise ValueError('Model cache escapes its storage boundary.')
    partial = cache / (name + '.partial')
    if partial.is_symlink():
        raise ValueError('Model cache files cannot be symbolic links.')
    url = hf_hub_url(item.repo_id, name, revision=item.revision, endpoint='https://huggingface.co')
    token = hub_token(item.tenant_id, item.project_id)
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    with FileLock(str(partial) + '.lock', timeout=1):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > pin['byte_size']:
            partial.unlink(); offset = 0
        if offset < pin['byte_size']:
            if offset:
                headers['Range'] = f'bytes={offset}-'
            with requests.get(url, headers=headers, stream=True, timeout=(10, 10)) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    if not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                        raise ValueError('Hub resume range does not match the partial file.')
                elif response.status_code == 200:
                    offset = 0
                else:
                    raise ValueError('Hub download returned an unsupported response.')
                last_check = 0
                with partial.open('ab' if offset else 'wb') as stream:
                    for block in response.iter_content(chunk_size=256 * 1024):
                        if time.monotonic() - last_check > 2:
                            last_check = time.monotonic()
                            if not context.heartbeat():
                                raise ValueError('Model download cancelled or lease lost.')
                        offset += len(block)
                        if offset > pin['byte_size']:
                            raise ValueError('Downloaded bytes exceed the pinned file size.')
                        stream.write(block)
        try:
            with partial.open('rb') as stream:
                return _store(stream, tenant=item.tenant_id, project=item.project_id, name=name,
                              expected=pin['sha256'], size=pin['byte_size'])
        except ValueError:
            partial.unlink(missing_ok=True)
            raise


def model_import_executor(descriptor, context):
    identifier = descriptor.get('payload', {}).get('import_id')
    item = ModelImport.all_objects.select_related('project').get(import_id=identifier, job=context.attempt.job, tenant_id=context.attempt.tenant_id)
    if not context.heartbeat():
        return None
    for index, (name, pin) in enumerate(item.files.items()):
        if not context.heartbeat(progress=index / len(item.files)):
            return None
        if name in item.acquired_files:
            continue
        # Per-file cache supports resume; no shared cross-tenant authenticated cache.
        try:
            ref = download_file(item, name, pin, context)
        except Exception:
            raise ValueError('Pinned model download failed; retry with scoped Hub access. Partial cache remains resumable.') from None
        with transaction.atomic():
            item = _locked_live_import(context, identifier)
            item.acquired_files = {**item.acquired_files, name: ref}
            item.status = 'running'
            item.save(update_fields=['acquired_files', 'status', 'updated_at'])
    if not context.heartbeat(progress=1):
        return None
    with transaction.atomic():
        item = _locked_live_import(context, identifier)
        if not item.candidate_id:
            source = {'repo_id': item.repo_id, 'revision': item.revision, 'license': item.license_expression}
            item.candidate = publish_files(item.acquired_files, tenant=item.tenant_id, project=item.project_id,
                name=item.name, source=source, format=item.format, license_expression=item.license_expression)
            _locked_live_import(context, identifier)
            item.status = 'completed'
            item.save(update_fields=['candidate', 'status', 'updated_at'])
    return None


@transaction.atomic
def import_local(files, *, tenant, project, name, license_expression, idempotency_key, format=None):
    from modelanvil.runners.inference import verified_artifact
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES or any(not filename_allowed(n) for n in files):
        raise ValueError('Select supported model and tokenizer files.')
    for ref in files.values():
        verified_artifact(ref, tenant, project.pk)
    format = format or ('gguf' if len(files) == 1 and next(iter(files)).endswith('.gguf') else 'safetensors')
    fingerprint = digest({'name': name, 'files': files, 'license': license_expression, 'format': format})
    prior = ModelImport.all_objects.select_for_update().filter(tenant_id=tenant, project=project, idempotency_key=idempotency_key).first()
    if prior:
        if prior.input_digest != fingerprint:
            raise ValueError('This idempotency key belongs to different import inputs.')
        return prior
    source = {'local_snapshot_sha256': digest(files), 'license': license_expression}
    candidate = publish_files(files, tenant=tenant, project=project.pk, name=name, source=source,
                              format=format, license_expression=license_expression)
    return ModelImport.all_objects.create(tenant_id=tenant, project=project, name=name, format=format,
        license_expression=license_expression, files=files, acquired_files=files,
        candidate=candidate, status='completed', input_digest=fingerprint, idempotency_key=idempotency_key)
