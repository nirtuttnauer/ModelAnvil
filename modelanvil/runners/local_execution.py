"""Bounded local CPU inference using scoped, checksum-verified weight artifacts."""
from __future__ import annotations

import json
import uuid
from modelanvil.artifacts.models import Artifact
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.training import runtime
from modelanvil.runners.training.engine import TrainingEngine


def load_character_bundle(model_version, *, tenant, project):
    if not check_resource_access(model_version, project, tenant):
        raise ValueError('Model version is unavailable in this project.')
    if model_version.architecture_ref != runtime.RUNTIME_ID:
        raise ValueError('Local evaluation currently supports pinned CPU character bundles only.')
    try:
        artifact = Artifact.all_objects.get(tenant_id=tenant, artifact_id=uuid.UUID(str(model_version.artifact_manifest_id)))
    except (Artifact.DoesNotExist, ValueError):
        raise ValueError('Model version requires a committed CPU character bundle artifact.') from None
    raw = runtime.read_artifact(artifact, tenant, project)
    try:
        bundle = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('Model artifact must contain a valid JSON export bundle.') from exc
    if not isinstance(bundle, dict):
        raise ValueError('Model artifact must contain a JSON object.')
    config = bundle.get('config.json', {})
    if (not isinstance(config, dict)
            or type(config.get('n_embd')) is not int or not 1 <= config['n_embd'] <= runtime.LIMITS['n_embd']
            or type(config.get('lora_r')) is not int or not 1 <= config['lora_r'] <= runtime.LIMITS['lora_r']):
        raise ValueError('Model dimensions exceed the bounded CPU character runtime.')
    if not check_resource_access(model_version.tokenizer, project, tenant):
        raise ValueError('Pinned tokenizer is unavailable in this project.')
    spec = runtime.tokenizer_spec(model_version.tokenizer)
    if bundle.get('tokenizer_config.json') != spec or config.get('vocab_size') != len(spec['tokens']):
        raise ValueError('Bundle tokenizer/configuration does not match the registered tokenizer.')
    verification = TrainingEngine.verify_external_loadable(bundle)
    return bundle, artifact, verification


def initialize_character_base(*, tenant, project, name, seed):
    """Create real initial tensors; this establishes an untrained base, never qualification."""
    import base64
    import hashlib
    import io
    from django.db import transaction
    from modelanvil.artifacts.storage import LocalArtifactStorage, artifact_storage_backend, upload_staged_artifact
    from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion
    from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
    backend = artifact_storage_backend()
    if not isinstance(backend, LocalArtifactStorage):
        raise ValueError('CPU base initialization requires the filesystem artifact backend.')
    with transaction.atomic():
        tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('\t\n\r'), *(chr(i) for i in range(32, 127))]
        tokenizer = TokenizerVersion.objects.create(tenant_id=tenant, project_id=project, name=f'{name} characters', vocabulary_size=len(tokens), special_tokens={'pad_token': '<pad>', 'bos_token': '<bos>', 'eos_token': '<eos>', 'unk_token': '<unk>'}, compatibility={'character_v1': {'tokens': tokens}})
        spec = runtime.tokenizer_spec(tokenizer)
        tokenizer.configuration_digest = runtime.digest(spec)
        tokenizer.save(update_fields=['configuration_digest', 'updated_at'])
        model = CausalTextModel(len(tokens), n_embd=8, lora_r=2, lora_alpha=4, seed=seed)
        raw, manifest = pack_safetensors(model.export_tensors())
        bundle = {'config.json': {'runtime': runtime.RUNTIME_ID, 'vocab_size': len(tokens), 'n_embd': 8, 'lora_r': 2, 'lora_alpha': 4}, 'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(), 'tokenizer_config.json': spec, 'provenance.json': {'initialization_seed': seed, 'trained': False, 'production_qualified': False}}
        TrainingEngine.verify_external_loadable(bundle)
        payload = json.dumps(bundle, sort_keys=True, allow_nan=False).encode()
        logical_model = Model.objects.create(tenant_id=tenant, project_id=project, name=name, intended_tasks=['text_generation'])
        artifact = Artifact.objects.create(tenant_id=tenant, project_id=project, storage_location_id='local', object_key=f'models/{logical_model.model_id}/initial.json', sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
        upload_staged_artifact(artifact, io.BytesIO(payload), backend=backend)
        version = ModelVersion.objects.create(tenant_id=tenant, project_id=project, model=logical_model, tokenizer=tokenizer, architecture_ref=runtime.RUNTIME_ID, artifact_manifest_id=str(artifact.artifact_id), parameters_count=2 * len(tokens) * 8 + 2 * 8 * 2, state=ModelVersion.State.DRAFT, metadata={'initialization_seed': seed, 'trained': False, 'weights_sha256': manifest['weights_sha256'], 'runtime_contract': runtime.CONTRACT_DIGEST})
        return logical_model, tokenizer, version
