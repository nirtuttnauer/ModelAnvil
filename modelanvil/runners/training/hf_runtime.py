"""Bounded local GPU full SFT and LoRA for one immutable SmolLM2 snapshot.

Optional framework imports are delayed. CPU references remain separate runtimes.
No remote code, pickle, implicit model download, mixed precision or GPU fallback.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import math
import os
import random
from pathlib import Path
import tempfile
import time
import uuid

from django.db import transaction
from django.utils import timezone

from modelanvil.accelerators import inventory, select_device
from modelanvil.device_admission import device_available, device_lease
from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.training.runtime import digest, read_artifact, _locked_live_run, _finalize_worker_job

RUNTIME_ID = 'modelanvil.smollm2-gpu-sft.v1'
SOURCE = {'repo_id': 'HuggingFaceTB/SmolLM2-135M', 'revision': '93efa2f097d58c2a74874c7e644dbc9b0cee75a2', 'license': 'Apache-2.0'}
FILE_HASHES = {
    'model.safetensors': '80521b40281d6ce74e35c9282c22539e75aa0ac8578892b2a59955ef78d55da1',
    'config.json': '1d556eab73b69c7f11f64c557a2f9c6f440bd4c6b89bb2584a6b498c92603843',
    'tokenizer.json': '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c',
    'tokenizer_config.json': '4bb9af56a342753d39374f4016a16574cab299fe088e896f425ce3c433f61424',
    'special_tokens_map.json': 'e786b595b9a23148bf1630df78d9037a048ea671e48bfd3549a1e3c233742bb3',
}
PACKAGES = {'torch': '2.13.0', 'transformers': '5.14.0', 'safetensors': '0.8.0', 'tokenizers': '0.22.2'}
GUIDED_SOURCE = {'repo_id': 'HuggingFaceTB/SmolLM2-135M-Instruct', 'revision': '12fd25f77366fa6b3b4b768ec3050bf629380bac', 'license': 'Apache-2.0'}
GUIDED_FILE_HASHES = {**FILE_HASHES,
    'model.safetensors': '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c',
    'config.json': '8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a',
    'tokenizer_config.json': '4ec77d44f62efeb38d7e044a1db318f6a939438425312dfa333b8382dbad98df',
    'special_tokens_map.json': '2b7379f3ae813529281a5c602bc5a11c1d4e0a99107aaa597fe936c1e813ca52'}
LARGE_GUIDED_SOURCE = {'repo_id': 'HuggingFaceTB/SmolLM2-1.7B-Instruct', 'revision': '31b70e2e869a7173562077fd711b654946d38674', 'license': 'Apache-2.0'}
LARGE_GUIDED_FILE_HASHES = {**GUIDED_FILE_HASHES,
    'model.safetensors': 'f55217be716b6a997b97b9d8d7eb6fad02e00858f5010ec24f64603c3a98a0e8',
    'config.json': '994f50b16abb4ae00880baefe03c10260b5bd608d2bf586f7056ca05a534feea'}
LIMITS = {'rows': 1000, 'steps': 3000, 'sequence_tokens': 128, 'memory_bytes': 8 * 1024**3,
          'gpu_memory_bytes': 4 * 1024**3, 'weight_bytes': 4 * 1024**3, 'aux_bytes': 8 * 1024**2}
OPTIMIZER = {'algorithm': 'adamw', 'learning_rate': 0.00002, 'beta1': 0.9, 'beta2': 0.999,
             'epsilon': 1e-8, 'weight_decay': 0.0}
LORA = {'r': 8, 'lora_alpha': 16, 'target_modules': ['q_proj', 'v_proj'], 'lora_dropout': 0.0,
        'bias': 'none', 'task_type': 'CAUSAL_LM'}
GUIDED_LORA = {**LORA, 'r': 16, 'lora_alpha': 32,
    'target_modules': ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']}
CONTRACT = {'runtime': RUNTIME_ID, 'source': SOURCE, 'file_hashes': FILE_HASHES, 'packages': PACKAGES,
            'recipe': 'full_sft', 'precision': 'fp32', 'optimizer': OPTIMIZER, 'limits': LIMITS,
            'dropout': 'disabled', 'placement': 'one_trusted_local_worker',
            'recipes': ['full_sft', 'lora_adapter', 'continued_pretraining'], 'lora': LORA, 'adapter_package': {'peft': '0.21.2'},
            'lora_gradient_checkpointing': 'non_reentrant', 'deterministic_algorithms': True,
            'device_admission': 'exclusive_posix_user_host_v1',
            'chat_sft': 'native_template_assistant_labels_eos_v2',
            'guided_source': GUIDED_SOURCE, 'guided_file_hashes': GUIDED_FILE_HASHES,
            'large_guided_source': LARGE_GUIDED_SOURCE, 'large_guided_file_hashes': LARGE_GUIDED_FILE_HASHES,
            'large_guided_recipe': 'lora_adapter', 'large_guided_learning_rate': 0.0002, 'large_guided_adapter': GUIDED_LORA,
            'gradient_clip_norm': 1.0, 'guided_checkpoints': 'three_spaced_checkpoints_best_validation_v1'}
CONTRACT['guided_sample_order'] = 'seeded_epoch_shuffle_v1'
CONTRACT_DIGEST = digest(CONTRACT)
MPS_MEMORY_FRACTION = 0.9


def validate_options(*, precision='fp32', adapter=None, quantization=None, recipe_type='full_sft'):
    allowed = (None, 'lora') if recipe_type == 'lora_adapter' else (None, 'none')
    if precision != 'fp32' or adapter not in allowed or quantization not in (None, 'none'):
        if recipe_type == 'lora_adapter':
            raise ValueError('This GPU LoRA profile supports FP32 rank-8 q/v adapters only; QLoRA and mixed precision remain unqualified.')
        raise ValueError('This GPU recipe supports FP32 full SFT only; disable adapters, quantization and mixed precision.')


def require_adapter_package():
    try:
        installed = importlib.metadata.version('peft')
    except importlib.metadata.PackageNotFoundError:
        installed = None
    if installed != '0.21.2':
        raise ValueError('Install peft==0.21.2 for the pinned FP32 LoRA recipe; QLoRA is not qualified here.')


def mps_memory():
    import torch
    recommended = torch.mps.recommended_max_memory()
    allocated = torch.mps.driver_allocated_memory()
    if type(recommended) is not int or type(allocated) is not int or recommended <= 0 or allocated < 0:
        raise ValueError('MPS process memory headroom is unknown; repair the local runtime.')
    limit = int(recommended * MPS_MEMORY_FRACTION)
    return {'recommended_bytes': recommended, 'process_limit_bytes': limit,
            'driver_allocated_bytes': allocated, 'process_headroom_bytes': max(0, limit - allocated),
            'scope': 'Process allowance including driver/cache allocations; not system-wide free memory or a reservation.'}


def runner_manifest():
    return {'schema_version': '1.0', 'adapter_id': RUNTIME_ID, 'version': '1', 'platform_api': 'v1',
            'image': f'local-python-contract@sha256:{CONTRACT_DIGEST}', 'license': 'Apache-2.0 model; optional libraries retain their licenses',
            'capabilities': [{'kind': 'train', 'input_schema_refs': ['urn:modelanvil:schema:sample-envelope:1.0'],
                              'output_schema_refs': ['huggingface:safetensors'], 'formats': ['text'],
                              'architectures': [RUNTIME_ID], 'recovery': 'verified_checkpoint'}],
            'resources': {'cpu_cores': 1, 'memory_bytes': LIMITS['memory_bytes'], 'gpu_count': 1,
                          'disk_bytes': 2 * 1024**3, 'distributed': False},
            'permissions': {'network_hosts': [], 'artifact_access': ['read_job_inputs', 'write_attempt_staging'], 'secret_kinds': []},
            'dependencies': [],
            'limitations': ['One pinned SmolLM2-135M model, text or assistant-only conversation SFT, rank-8 q/v LoRA or continued pretraining, FP32, deterministic manifest-order samples.',
                           'One trusted local GPU worker per pool; cross-worker device reservations require TASK-42.',
                           'No QLoRA, quantization, distributed or remote worker support; each device needs qualification.']}


def build_digest():
    root = Path(__file__).parent
    paths = [root / name for name in ['hf_runtime.py', 'runtime.py', 'executor.py', 'registry.py']]
    paths.extend(root.parents[1] / name for name in ('accelerators.py', 'device_admission.py', 'data/training_import.py'))
    return hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()


def require_packages():
    for name, version in PACKAGES.items():
        try:
            installed = importlib.metadata.version(name).split('+')[0]
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != version:
            raise ValueError(f'Install the GPU runtime {name}=={version} in the trusted local API/worker environment.')


def capable_worker(worker):
    caps = worker.capabilities
    if caps.get('managed_local'):
        from modelanvil.jobs.setup import connection_state
        if connection_state(worker) != 'connected':
            return False
    return (isinstance(caps, dict) and caps.get('training_runtime') == CONTRACT_DIGEST
            and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes']
            and caps.get('gpu_backend') in {'cuda', 'rocm', 'xpu', 'mps'}
            and isinstance(caps.get('gpu_device'), str) and caps.get('gpu_packages') == PACKAGES
            and worker.slots in (0, 1))


def observed_device(selector):
    report = inventory()
    device = select_device(report, selector)
    if device['backend'] == 'mps' and os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK') == '1':
        raise ValueError('Unset PYTORCH_ENABLE_MPS_FALLBACK; GPU training refuses CPU kernel fallback.')
    capacity = (device.get('runtime_recommended_memory_bytes') if device['backend'] == 'mps'
                else device.get('total_memory_bytes'))
    if type(capacity) is not int or capacity < LIMITS['gpu_memory_bytes']:
        raise ValueError('GPU memory capacity is unknown or insufficient for the bounded FP32 recipe.')
    if device['backend'] == 'mps' and mps_memory()['process_headroom_bytes'] < LIMITS['gpu_memory_bytes']:
        raise ValueError('MPS process headroom is below 4 GiB; release this process\'s GPU allocations before launch.')
    return {'device': device, 'framework': report['framework'], 'packages': PACKAGES,
            'capacity_source': 'MPS recommended shared-memory budget' if device['backend'] == 'mps' else 'framework device capacity'}


def file_ref(artifact):
    return {'artifact_id': str(artifact.artifact_id), 'sha256': artifact.sha256, 'byte_size': artifact.byte_size}


def _artifact(ref, tenant, project, *, weight=False):
    if not isinstance(ref, dict):
        raise ValueError('Model files require immutable artifact references.')
    try:
        artifact = Artifact.all_objects.get(artifact_id=uuid.UUID(ref['artifact_id']), tenant_id=tenant)
    except (Artifact.DoesNotExist, KeyError, ValueError, TypeError):
        raise ValueError('Referenced model file is unavailable.') from None
    maximum = LIMITS['weight_bytes'] * (2 if weight else 1) if weight else LIMITS['aux_bytes']
    if (not check_resource_access(artifact, project, tenant) or artifact.state != 'committed'
            or artifact.storage_location_id != 'local' or artifact.object_version is not None
            or not 1 <= artifact.byte_size <= maximum or file_ref(artifact) != ref
            or DeletionTombstone.all_objects.filter(tenant_id=tenant, resource_id=str(artifact.artifact_id)).exists()):
        raise ValueError('Use an accessible committed local model artifact within the runtime size limit.')
    return artifact


@contextlib.contextmanager
def staged_files(files, tenant, project):
    """Only verified bytes enter a library loader; filenames are server allowlisted."""
    allowed = set(FILE_HASHES) | {'optimizer.safetensors', 'adapter_model.safetensors', 'adapters.safetensors', 'adapter_config.json'}
    if not isinstance(files, dict) or not files or set(files) - allowed:
        raise ValueError('Model file manifest contains missing or unsupported filenames.')
    backend = artifact_storage_backend()
    if not hasattr(backend, 'root'):
        raise ValueError('GPU runtime requires shared local filesystem storage.')
    with tempfile.TemporaryDirectory(prefix='modelanvil-model-') as temp:
        directory = Path(temp)
        for name, ref in files.items():
            artifact = _artifact(ref, tenant, project, weight=name.endswith('.safetensors'))
            sha, size = hashlib.sha256(), 0
            try:
                with backend.open(tenant, artifact.object_key) as source, (directory / name).open('wb') as target:
                    while block := source.read(1024 * 1024):
                        size += len(block)
                        if size > artifact.byte_size:
                            raise ValueError('Model artifact exceeds its committed size.')
                        sha.update(block); target.write(block)
            except OSError:
                raise ValueError('Model artifact bytes are unavailable; restore the committed local file.') from None
            if size != artifact.byte_size or sha.hexdigest() != artifact.sha256:
                raise ValueError('Model artifact checksum or size changed; allocation refused.')
        yield directory


def _tokenizer(directory):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)


def _load_model(directory):
    import torch
    from transformers import LlamaForCausalLM
    model, info = LlamaForCausalLM.from_pretrained(str(directory), local_files_only=True, use_safetensors=True,
        dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
    if info['missing_keys'] or info['unexpected_keys'] or info['mismatched_keys'] or info['error_msgs']:
        raise ValueError('Model weights do not completely match the pinned transformer.')
    model.eval()  # Gradients remain enabled; disables stochastic dropout for exact step recovery.
    model.config.use_cache = False
    for parameter in model.parameters():
        if parameter.is_meta:
            raise ValueError('Model checkpoint did not materialize all transformer weights.')
        if not torch.isfinite(parameter).all().item():
            raise ValueError('Model contains non-finite weights.')
    return model


def _recipe_model(directory, recipe_type='full_sft', seed=42, *, training=False, source=None, adapter=None):
    if recipe_type in {'full_sft', 'continued_pretraining'}:
        return _load_model(directory)
    require_adapter_package()
    adapter = adapter or LORA
    if adapter not in (LORA, GUIDED_LORA) or (adapter == GUIDED_LORA and source != LARGE_GUIDED_SOURCE):
        raise ValueError('Use a verified adapter configuration for the pinned source model.')
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model, get_peft_model_state_dict
    # Transformers auto-detects adapter_config.json; isolate the verified base to prevent implicit Hub loading.
    base = directory / 'base'; base.mkdir(exist_ok=True)
    for filename in FILE_HASHES:
        if not (base / filename).exists():
            os.link(directory / filename, base / filename)
    model = _load_model(base)
    if (directory / 'adapter_model.safetensors').exists():
        config = json.loads((directory / 'adapter_config.json').read_text())
        if any(config.get(k) != value for k, value in adapter.items() if k != 'target_modules') or set(config.get('target_modules', [])) != set(adapter['target_modules']):
            raise ValueError('Adapter configuration differs from the pinned LoRA profile.')
        model = PeftModel.from_pretrained(model, str(directory), is_trainable=training, local_files_only=True)
        from safetensors.torch import load_file
        saved = load_file(str(directory / 'adapter_model.safetensors'))
        expected = get_peft_model_state_dict(model, save_embedding_layers=False)
        if set(saved) != set(expected) or any(saved[n].shape != p.shape or not torch.isfinite(saved[n]).all().item() for n, p in expected.items()):
            raise ValueError('Adapter checkpoint has missing, unexpected or non-finite tensors.')
    else:
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            model = get_peft_model(model, LoraConfig(**adapter))
    source = source or SOURCE
    model.peft_config['default'].base_model_name_or_path = source['repo_id']
    model.peft_config['default'].revision = source['revision']
    if training:
        model.train()
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    else:
        model.eval()
    if any(p.requires_grad and '.lora_' not in name for name, p in model.named_parameters()):
        raise ValueError('LoRA may update only its adapter parameters.')
    return model


def _training_samples(dataset, tokenizer, tenant, project, *, split='train'):
    if split not in {'train', 'validation'}:
        raise ValueError('The training runtime never consumes the protected test split.')
    from contracts import validate_envelope
    if dataset.state != 'published' or not dataset.manifest_artifact_id:
        raise ValueError('Publish a prepared text dataset before GPU training.')
    raw = read_artifact(dataset.manifest_artifact, tenant, project)
    if hashlib.sha256(raw).hexdigest() != dataset.manifest_digest:
        raise ValueError('Dataset manifest digest changed; republish the dataset.')
    prepared = json.loads(raw)
    if not isinstance(prepared, dict):
        raise ValueError('Prepared dataset manifest must be an object.')
    rows, splits = prepared.get('rows'), prepared.get('split_manifest')
    if not isinstance(rows, list) or not 1 <= len(rows) <= LIMITS['rows'] or not isinstance(splits, dict):
        raise ValueError('Prepare bounded text rows with protected split identifiers.')
    if not splits.get('train') or any(not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) for ids in splits.values()):
        raise ValueError('Prepared splits require a nonempty train list and valid sample identifiers.')
    train = splits['train']; held = [i for name, ids in splits.items() if name != 'train' for i in ids]
    if len(set(train + held)) != len(train + held):
        raise ValueError('Protected split contamination or duplicate train identifiers; republish the dataset.')
    selected = splits.get(split, [])
    seen, samples, groups = set(), [], {}
    for row in rows:
        validate_envelope(row)
        identifier = row['sample_id']
        if identifier in seen:
            raise ValueError('Prepared samples must have unique identifiers.')
        seen.add(identifier)
        group = row.get('source_group_id', identifier)
        named_split = next((name for name, identifiers in splits.items() if identifier in identifiers), None)
        if group in groups and groups[group] != named_split:
            raise ValueError('A source group crosses protected dataset splits.')
        groups[group] = named_split
        if identifier not in selected:
            continue
        from modelanvil.data.training_import import tokenize_blocks
        text, ids, labels = tokenize_blocks(row['blocks'], tokenizer)
        if not text or not 2 <= len(ids) <= LIMITS['sequence_tokens']:
            raise ValueError('Prepare nonempty samples of 2–128 actual tokenizer tokens; samples are never truncated.')
        samples.append({'sample_id': identifier, 'text': text, 'token_ids': ids, **({'labels': labels} if labels != ids else {})})
    if (not samples and split == 'train') or (set(train) | set(held)) - seen:
        raise ValueError('Published split identifiers do not resolve to actual samples.')
    return samples, {'consumed': split, 'train_rows': len(train), 'excluded_rows': {n: len(ids) for n, ids in splits.items() if n != 'train'}, 'excluded_digest': digest(sorted(held))}


def resolve_inputs(*, dataset, base, tokenizer, runner, pool, tenant, project, steps, require_capacity=True,
                   recipe_type='full_sft', initialization_seed=42, profile=None):
    import sys
    profile = profile or sys.modules[__name__]
    from modelanvil.jobs.models import Worker
    profile.require_packages()
    if recipe_type not in profile.CONTRACT['recipes'] or type(initialization_seed) is not int or not 0 <= initialization_seed <= 2147483647:
        raise ValueError('Select a supported runtime recipe with a seed from 0 to 2147483647.')
    if recipe_type == 'lora_adapter':
        require_adapter_package()
    if type(steps) is not int or not 1 <= steps <= profile.LIMITS['steps']:
        raise ValueError(f'GPU full SFT supports 1–{profile.LIMITS["steps"]} optimizer steps.')
    if not all([dataset, base, tokenizer, runner, pool]) or any(not check_resource_access(r, project, tenant) for r in [dataset, base, tokenizer, runner, pool]):
        raise ValueError('Select accessible published data, base weights, tokenizer, runner and pool.')
    source = base.metadata.get('source', SOURCE)
    guided = source in (GUIDED_SOURCE, LARGE_GUIDED_SOURCE) and profile.RUNTIME_ID == RUNTIME_ID
    large_guided = source == LARGE_GUIDED_SOURCE
    expected_hashes = LARGE_GUIDED_FILE_HASHES if large_guided else GUIDED_FILE_HASHES if guided else FILE_HASHES
    if large_guided and recipe_type != 'lora_adapter':
        raise ValueError('The recommended 1.7B model uses lightweight LoRA training on this computer.')
    if (source not in (SOURCE, GUIDED_SOURCE, LARGE_GUIDED_SOURCE) or base.architecture_ref != profile.RUNTIME_ID or base.tokenizer_id != tokenizer.pk
            or (tokenizer.chat_template and not guided) or tokenizer.compatibility.get('hf_snapshot') != source):
        raise ValueError('Select a pinned SmolLM2 snapshot and its matching tokenizer.')
    if (not runner.enabled or runner.manifest != profile.runner_manifest() or runner.digest != digest(profile.runner_manifest())
            or runner.compatibility.get('contract_digest') != profile.CONTRACT_DIGEST or (pool.status != 'active' and (require_capacity or pool.status != 'draining'))):
        raise ValueError('Enable the exact GPU runtime manifest and activate its worker pool.')
    manifest = base.metadata.get('snapshot_manifest', {})
    artifact = _artifact({'artifact_id': str(base.artifact_manifest_id),
                          'sha256': manifest.get('sha256'), 'byte_size': manifest.get('byte_size')}, tenant, project)
    raw = read_artifact(artifact, tenant, project)
    bundle = json.loads(raw)
    if not isinstance(bundle, dict):
        raise ValueError('Base snapshot manifest must be an object.')
    files = bundle.get('files', {})
    if (bundle.get('source') != source or not isinstance(files, dict) or set(files) != set(expected_hashes)
            or any(not isinstance(files[n], dict) or files[n].get('sha256') != h for n, h in expected_hashes.items())):
        raise ValueError('Base must contain the exact immutable SmolLM2 snapshot files.')
    workers = list(Worker.all_objects.filter(tenant_id=tenant, pool=pool, status__in=['available', 'busy']))
    matching = [w for w in workers if profile.capable_worker(w)]
    # This first local runtime does not share GPUs between independently registered workers.
    if len(workers) != 1 or len(matching) != 1:
        raise ValueError('Use a dedicated pool with exactly one single-slot GPU worker for this contract.')
    worker = matching[0]
    if large_guided and worker.capabilities['memory_bytes'] < 32 * 1024**3:
        raise ValueError('The 1.7B adapter profile requires at least 32 GiB host memory; use the small guided model.')
    observed = profile.observed_device(worker.capabilities['gpu_device'])
    if large_guided and observed['device']['backend'] != 'mps':
        raise ValueError('The 1.7B adapter profile is verified on Apple GPUs only; use the small guided model on this device.')
    if large_guided and mps_memory()['process_headroom_bytes'] < 12 * 1024**3:
        raise ValueError('The 1.7B adapter profile needs 12 GiB of free process memory headroom. Release GPU allocations before launch.')
    if observed['device']['backend'] != worker.capabilities['gpu_backend']:
        raise ValueError('GPU worker backend changed; re-register the worker before launch.')
    if require_capacity and worker.slots < 1:
        raise ValueError('Free the GPU worker slot before launching.')
    if require_capacity and not device_available(worker.capabilities['gpu_device']):
        raise ValueError('The selected local device is busy; retry preflight when it finishes.')
    with staged_files(files, tenant, project) as directory:
        spec = _tokenizer(directory)
        config = json.loads((directory / 'config.json').read_text())
        if len(spec) != tokenizer.vocabulary_size or config['vocab_size'] != tokenizer.vocabulary_size:
            raise ValueError('Tokenizer vocabulary does not match the pinned transformer.')
        samples, splits = _training_samples(dataset, spec, tenant, project)
        if guided and tokenizer.chat_template != spec.chat_template:
            raise ValueError('The instruction model requires its verified native chat template.')
        validation = _training_samples(dataset, spec, tenant, project, split='validation')[0] if guided or recipe_type == 'continued_pretraining' else []
    pins = {'runtime': profile.RUNTIME_ID, 'contract_digest': profile.CONTRACT_DIGEST, 'build_digest': profile.build_digest(),
            'dataset_id': str(dataset.revision_id), 'dataset_digest': dataset.manifest_digest,
            'base_id': str(base.model_version_id), 'base_artifact_id': str(artifact.artifact_id),
            'base_digest': hashlib.sha256(raw).hexdigest(), 'tokenizer_id': str(tokenizer.tokenizer_id),
            'tokenizer_digest': digest({n: files[n] for n in files if n != 'model.safetensors'}),
            'runner_id': str(runner.manifest_id), 'runner_digest': runner.digest, 'pool_id': pool.pk,
            'steps': steps, 'config': {**config, 'runtime': profile.RUNTIME_ID}, 'optimizer': profile.OPTIMIZER,
            'sample_digest': digest(samples), 'splits': splits, 'accelerator': observed, 'worker_id': worker.pk}
    pins['chat_sft'] = any('labels' in sample for sample in samples)
    if pins['chat_sft'] and recipe_type == 'continued_pretraining':
        raise ValueError('Conversations require supervised fine-tuning; continued pretraining accepts plain text.')
    pins['recipe'] = recipe_type
    if guided:
        pins.update(source=source, checkpoint_interval=max(1, (steps + 2) // 3), validation_digest=digest(validation),
                    sample_order='seeded_epoch_shuffle_v1', initialization_seed=initialization_seed)
    if large_guided:
        pins['optimizer'] = {**profile.OPTIMIZER, 'learning_rate': 0.0002}
    if recipe_type == 'lora_adapter':
        pins.update(adapter=GUIDED_LORA if large_guided else LORA, initialization_seed=initialization_seed, adapter_package={'peft': '0.21.2'})
    if recipe_type == 'continued_pretraining':
        pins.update(objective='causal_next_token_continued_pretraining', initialization='pinned_pretrained_weights',
            corpus={'components': [{'revision_id': str(dataset.revision_id), 'manifest_digest': dataset.manifest_digest, 'weight': 1.0}],
                'ordering': 'published_manifest_order_cyclic', 'sample_order_digest': digest([r['sample_id'] for r in samples]),
                'validation_digest': digest(validation), 'sampler_rng': 'none_dropout_disabled'})
    # BF16 base becomes FP32 weights + two FP32 Adam moments, with staging/candidate headroom.
    checkpoint_bytes = 6 * files['model.safetensors']['byte_size'] + 1024**2
    if recipe_type in {'lora_adapter', 'qlora_adapter'}:
        adapter_parameters = config['num_hidden_layers'] * LORA['r'] * (
            3 * config['hidden_size'] + config['num_key_value_heads'] * config['hidden_size'] // config['num_attention_heads'])
        if large_guided:
            adapter_parameters = config['num_hidden_layers'] * GUIDED_LORA['r'] * (
                9 * config['hidden_size'] + 2 * config['num_key_value_heads'] * config['hidden_size'] // config['num_attention_heads'] + 3 * config['intermediate_size'])
        pins['trainable_parameters'] = adapter_parameters
        checkpoint_bytes = 12 * adapter_parameters + 1024**2
    if recipe_type == 'qlora_adapter':
        pins.update(adapter=profile.LORA, quantization=profile.QUANTIZATION, initialization_seed=initialization_seed, adapter_package=profile.PACKAGES)
        checkpoint_bytes += files['model.safetensors']['byte_size']
    return {'pins': pins, 'bundle': bundle, 'tokenizer': {'kind': 'huggingface', 'source': source},
            'samples': samples, 'sequences': [s['token_ids'] for s in samples], 'validation_samples': validation, 'checkpoint_bytes': checkpoint_bytes,
            'checkpoint_count': (steps + pins.get('checkpoint_interval', 1) - 1) // pins.get('checkpoint_interval', 1),
            'staging_bytes': 2 * files['model.safetensors']['byte_size'] if recipe_type == 'lora_adapter' else 0}


def is_worker_run(run):
    return run.hardware_config.get('execution_mode') == 'worker'


def checkpoint_bundle(run, checkpoint):
    state = checkpoint.weights_manifest
    if (not checkpoint.is_valid or digest(state) != checkpoint.state_digest or state.get('pins') != run.hardware_config['pins']
            or state.get('step') != checkpoint.step or state.get('run_id') != str(run.run_id)
            or state.get('optimizer') != {**state['pins'].get('optimizer', OPTIMIZER), 'updates': checkpoint.step} or state.get('metrics') != checkpoint.metrics):
        raise ValueError('GPU checkpoint checksum, cursor or pinned optimizer changed.')
    bundle = {'config.json': state['pins']['config'], 'files': state['files'], 'source': state['pins'].get('source', SOURCE),
              'weights_manifest.json': {'weights_sha256': state['files'].get('adapter_model.safetensors', state['files']['model.safetensors'])['sha256'],
                                        'base_weights_sha256': state['files']['model.safetensors']['sha256']},
              'tokenizer_config.json': state['tokenizer'],
              'provenance.json': {'tenant_id': str(run.tenant_id), 'project_id': str(run.project_id) if run.project_id else None,
                                  'run_id': str(run.run_id), 'pins': state['pins'], 'step': checkpoint.step}}
    with staged_files({**state['files'], 'optimizer.safetensors': state['adam']}, run.tenant_id, run.project_id):
        pass
    return bundle


def _store_file(path, run, context, step):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            sha.update(block)
    artifact = Artifact.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
        storage_location_id='local', object_key=f'gpu-training/{run.run_id}/{context.attempt.attempt_id}/{step}/{path.name}',
        sha256=sha.hexdigest(), byte_size=path.stat().st_size, media_type='application/octet-stream')
    with path.open('rb') as stream:
        upload_staged_artifact(artifact, stream, backend=artifact_storage_backend())
    return file_ref(artifact)


def _optimizer_state(model, optimizer):
    import torch
    tensors = {}
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        state = optimizer.state[parameter]
        for key in ['exp_avg', 'exp_avg_sq']:
            tensors[f'{key}:{name}'] = state[key].detach().to('cpu').contiguous()
        tensors[f'step:{name}'] = torch.tensor([int(state['step'].item())], dtype=torch.int64)
    return tensors


def _restore_optimizer(model, optimizer, directory, step):
    import torch
    from safetensors.torch import load_file
    saved = load_file(str(directory / 'optimizer.safetensors'))
    expected = {f'{key}:{name}' for name, p in model.named_parameters() if p.requires_grad for key in ['exp_avg', 'exp_avg_sq', 'step']}
    if set(saved) != expected:
        raise ValueError('Optimizer checkpoint has missing or unexpected tensors.')
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        value = saved[f'step:{name}']
        if value.numel() != 1 or value.item() != step:
            raise ValueError('Optimizer checkpoint update count changed.')
        state = optimizer.state[parameter]
        state['step'] = torch.tensor(float(step))
        for key in ['exp_avg', 'exp_avg_sq']:
            value = saved[f'{key}:{name}']
            if value.shape != parameter.shape or not torch.isfinite(value).all().item():
                raise ValueError('Optimizer checkpoint moment shape or values changed.')
            state[key] = value.to(parameter.device)


@contextlib.contextmanager
def deterministic_updates():
    import torch
    previous = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(previous, warn_only=warn_only)


def execute_training(run, context):
    import torch
    from modelanvil.runners.models import RunnerManifest
    pins = run.hardware_config['pins']
    if not context.heartbeat(progress=run.current_step / run.total_steps):
        return
    runner = RunnerManifest.all_objects.get(manifest_id=pins['runner_id'], tenant_id=run.tenant_id)
    inputs = resolve_inputs(dataset=run.dataset_revision, base=run.base_model_version, tokenizer=run.tokenizer_version,
        runner=runner, pool=run.pool, tenant=run.tenant_id, project=run.project_id, steps=run.total_steps, require_capacity=False,
        recipe_type=run.recipe_type, initialization_seed=run.initialization_seed)
    if inputs['pins'] != pins or context.attempt.worker_id != pins['worker_id']:
        raise ValueError('Pinned GPU inputs, placement or runtime changed; create a new run.')
    latest = run.checkpoints.order_by('-step').first()
    if (latest and latest.step != run.current_step) or (run.current_step and not latest):
        raise ValueError('Committed GPU cursor lacks a matching checkpoint.')
    files = checkpoint_bundle(run, latest)['files'] if latest else inputs['bundle']['files']
    recovery = {**files, **({'optimizer.safetensors': latest.weights_manifest['adam']} if latest else {})}
    device = torch.device(pins['accelerator']['device']['torch_device'])
    if device.type == 'mps':
        torch.mps.set_per_process_memory_fraction(MPS_MEMORY_FRACTION)
    with device_lease(pins['accelerator']['device']['id']), deterministic_updates():
        try:
            _execute_updates(run, context, inputs, device, recovery, files, latest)
        finally:
            import gc
            gc.collect()
            api = getattr(torch, 'cuda' if device.type == 'cuda' else device.type)
            api.empty_cache()


def _validation_loss(model, samples, device):
    import torch
    pairs, total = 0, 0.0
    with torch.no_grad():
        for sample in samples:
            ids = torch.tensor([sample['token_ids']], device=device, dtype=torch.long)
            value = model(input_ids=ids, labels=torch.tensor([sample.get('labels', sample['token_ids'])], device=device, dtype=torch.long)).loss
            if not torch.isfinite(value).item():
                raise ValueError('Protected validation produced non-finite loss.')
            count = sum(label != -100 for label in sample.get('labels', sample['token_ids'])[1:])
            pairs += count
            total += value.item() * count
    return {'loss': total / pairs, 'prediction_tokens': pairs, 'samples': len(samples)}


def training_sample_index(step, count, pins):
    epoch, offset = divmod(step - 1, count)
    if pins.get('sample_order') != 'seeded_epoch_shuffle_v1':
        return offset
    order = list(range(count))
    random.Random(pins['initialization_seed'] + epoch).shuffle(order)
    return order[offset]


def _execute_updates(run, context, inputs, device, recovery, files, latest):
    import torch
    from safetensors.torch import save_file
    from modelanvil.runners.models import TrainingCheckpoint, TrainingRun
    pins = run.hardware_config['pins']
    model = optimizer = loss = ids = None
    trainable = []
    try:
        with transaction.atomic():
            locked = _locked_live_run(context, run.run_id)
            if locked.started_at is None:
                locked.started_at = timezone.now(); locked.status = TrainingRun.Status.RUNNING
                locked.save(update_fields=['started_at', 'status', 'updated_at'])
        with staged_files(recovery, run.tenant_id, run.project_id) as directory:
            model = _recipe_model(directory, run.recipe_type, run.initialization_seed, training=True, source=pins.get('source'), adapter=pins.get('adapter')).to(device)
            trainable = [p for p in model.parameters() if p.requires_grad]
            optimizer_spec = pins['optimizer']
            optimizer = torch.optim.AdamW(trainable, lr=optimizer_spec['learning_rate'],
                betas=(optimizer_spec['beta1'], optimizer_spec['beta2']), eps=optimizer_spec['epsilon'], weight_decay=optimizer_spec['weight_decay'], foreach=False)
            if latest:
                _restore_optimizer(model, optimizer, directory, latest.step)
            validation_before = _validation_loss(model, inputs['validation_samples'], device) if inputs['validation_samples'] else None
            validation_baseline = ({'loss': latest.metrics['validation_loss_before_training']}
                if latest and latest.metrics.get('validation_loss_before_training') is not None else validation_before)
            window = {'training_pairs': 0, 'cpu_seconds': 0.0, 'engine_wall_seconds': 0.0, 'updates': 0}
            for step in range(run.current_step + 1, run.total_steps + 1):
                if not context.heartbeat(progress=(step - 1) / run.total_steps):
                    return
                sample = inputs['samples'][training_sample_index(step, len(inputs['samples']), pins)]
                ids = torch.tensor([sample['token_ids']], device=device, dtype=torch.long)
                backend = pins['accelerator']['device']['backend']
                api = getattr(torch, 'cuda' if backend == 'rocm' else backend)
                if backend != 'mps':
                    api.reset_peak_memory_stats(device)
                cpu_started, wall_started = time.process_time(), time.perf_counter()
                optimizer.zero_grad()
                loss = model(input_ids=ids, labels=torch.tensor([sample.get('labels', sample['token_ids'])], device=device, dtype=torch.long)).loss
                loss.backward()
                if loss.device != device or not torch.isfinite(loss).item() or any(
                        p.device != device or p.grad is None or not torch.isfinite(p.grad).all().item() for p in trainable):
                    raise ValueError('Training gradients are non-finite or left the selected GPU.')
                if any(p.grad is not None for p in model.parameters() if not p.requires_grad):
                    raise ValueError('Frozen base parameters unexpectedly acquired gradients.')
                grad_norm = torch.linalg.vector_norm(torch.stack([torch.linalg.vector_norm(p.grad.detach()) for p in trainable])).item()
                torch.nn.utils.clip_grad_norm_(trainable, 1.0)
                optimizer.step()
                with torch.no_grad():
                    post_loss = model(input_ids=ids, labels=torch.tensor([sample.get('labels', sample['token_ids'])], device=device, dtype=torch.long)).loss.item()
                if not torch.isfinite(torch.tensor(post_loss)).item():
                    raise ValueError('GPU update produced non-finite loss.')
                api.synchronize() if backend == 'mps' else api.synchronize(device)
                metrics = {'step': step, 'loss': loss.item(), 'post_update_loss': post_loss, 'sample_id': sample['sample_id'],
                           'training_pairs': sum(label != -100 for label in sample.get('labels', sample['token_ids'])[1:]), 'cpu_seconds': time.process_time() - cpu_started,
                           'engine_wall_seconds': time.perf_counter() - wall_started, 'gpu_backend': backend,
                           'gpu_device': str(device), 'device_residency_checked': True,
                           'gradient_norm': grad_norm, 'trainable_parameters': sum(p.numel() for p in trainable),
                           'total_parameters': sum(p.numel() for p in model.parameters()), 'measured_at': timezone.now().isoformat(),
                           'peak_allocated_bytes': None if backend == 'mps' else api.max_memory_allocated(device),
                           'peak_reserved_bytes': None if backend == 'mps' else api.max_memory_reserved(device),
                           'gpu_allocated_bytes': api.current_allocated_memory() if backend == 'mps' else api.memory_allocated(device)}
                metrics['tokens_per_second'] = metrics['training_pairs'] / metrics['engine_wall_seconds']
                metrics['gpu_utilization_percent'] = None  # No portable utilization measurement is available in this runtime.
                if backend == 'mps':
                    metrics['unified_memory'] = mps_memory()
                for key in ('training_pairs', 'cpu_seconds', 'engine_wall_seconds'):
                    window[key] += metrics[key]
                window['updates'] += 1
                if step % pins.get('checkpoint_interval', 1) and step != run.total_steps:
                    continue
                metrics.update({key: window[key] for key in ('training_pairs', 'cpu_seconds', 'engine_wall_seconds')}, updates_since_checkpoint=window['updates'])
                metrics['tokens_per_second'] = window['training_pairs'] / window['engine_wall_seconds']
                window = {'training_pairs': 0, 'cpu_seconds': 0.0, 'engine_wall_seconds': 0.0, 'updates': 0}
                if validation_before is not None:
                    validation_started = time.perf_counter()
                    after = _validation_loss(model, inputs['validation_samples'], device)
                    metrics.update(validation_loss_before_update=validation_before['loss'], validation_loss_before_training=validation_baseline['loss'], validation_loss=after['loss'],
                        validation_prediction_tokens=after['prediction_tokens'], validation_samples=after['samples'],
                        validation_wall_seconds=time.perf_counter() - validation_started,
                        cumulative_training_prediction_tokens=sum(sum(label != -100 for label in inputs['samples'][training_sample_index(i + 1, len(inputs['samples']), pins)].get('labels', inputs['samples'][training_sample_index(i + 1, len(inputs['samples']), pins)]['token_ids'])[1:]) for i in range(step)))
                    validation_before = after
                # Hugging Face preserves its expected tied embedding key; generic save_model does not.
                model.save_pretrained(str(directory), safe_serialization=True,
                    **({'save_embedding_layers': False} if run.recipe_type == 'lora_adapter' else {}))
                if pins.get('chat_sft') and pins.get('source') not in (GUIDED_SOURCE, LARGE_GUIDED_SOURCE):
                    from modelanvil.data.training_import import ROLE_PREFIX_TEMPLATE
                    candidate_tokenizer = _tokenizer(directory)
                    candidate_tokenizer.chat_template = ROLE_PREFIX_TEMPLATE
                    candidate_tokenizer.save_pretrained(str(directory), save_jinja_files=False)
                save_file(_optimizer_state(model, optimizer), str(directory / 'optimizer.safetensors'))
                if not context.heartbeat(progress=(step - 1) / run.total_steps):
                    return
                with transaction.atomic():
                    locked = _locked_live_run(context, run.run_id)
                    if locked.current_step != (latest.step if latest else run.current_step):
                        raise ValueError('GPU training cursor changed; publication refused.')
                    if run.recipe_type == 'lora_adapter':
                        saved_files = {**files, **{n: _store_file(directory / n, run, context, step)
                            for n in ['adapter_model.safetensors', 'adapter_config.json']}}
                    else:
                        saved_files = {**files, 'model.safetensors': _store_file(directory / 'model.safetensors', run, context, step)}
                    if pins.get('chat_sft'):
                        saved_files.update({n: _store_file(directory / n, run, context, step) for n in FILE_HASHES if n != 'model.safetensors'})
                    adam_ref = _store_file(directory / 'optimizer.safetensors', run, context, step)
                    _locked_live_run(context, run.run_id)  # Recheck expiry/cancellation after bounded storage writes.
                    state = {'run_id': str(run.run_id), 'step': step, 'pins': pins,
                        'files': saved_files, 'adam': adam_ref,
                        'optimizer': {**optimizer_spec, 'updates': step}, 'tokenizer': inputs['tokenizer'], 'metrics': metrics,
                        'attempt_id': str(context.attempt.attempt_id), 'fencing_token': context.fencing_token}
                    latest = TrainingCheckpoint.all_objects.create(tenant_id=run.tenant_id, training_run=locked,
                        step=step, state_digest=digest(state), weights_manifest=state, metrics=metrics)
                    locked.current_step, locked.latest_loss = step, metrics['loss']
                    locked.metrics_log = [*locked.metrics_log, metrics]; locked.status = TrainingRun.Status.RUNNING
                    locked.started_at = locked.started_at or timezone.now()
                    locked.save(update_fields=['current_step', 'latest_loss', 'metrics_log', 'status', 'started_at', 'updated_at'])

    except Exception as exc:
        import traceback
        traceback.clear_frames(exc.__traceback__)
        raise
    finally:
        if optimizer is not None:
            optimizer.state.clear()
            optimizer.param_groups.clear()
        trainable.clear()
        model = optimizer = loss = ids = None


def finalize_job(job, status):
    return _finalize_worker_job(job, status, runtime_id=RUNTIME_ID, contract_digest=CONTRACT_DIGEST,
        model_name_prefix='smollm2-gpu-sft', checkpoint_bundle=checkpoint_bundle, is_worker_run=is_worker_run,
        select_checkpoint=best_checkpoint)


def best_checkpoint(run):
    checkpoints = list(run.checkpoints.filter(is_valid=True).order_by('step'))
    measured = [c for c in checkpoints if type(c.metrics.get('validation_loss')) in (int, float) and math.isfinite(c.metrics['validation_loss'])]
    return min(measured, key=lambda c: c.metrics['validation_loss']) if measured else run.checkpoints.get(step=run.current_step)


def generate_candidate_completion(bundle, prompt, max_new_tokens=8):
    import torch
    if not isinstance(prompt, str) or len(prompt) > 4096 or type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 32:
        raise ValueError('Use a text prompt up to 4096 characters and 1–32 new tokens.')
    provenance = bundle['provenance.json']
    with staged_files(bundle['files'], provenance['tenant_id'], provenance['project_id']) as directory:
        model, tokenizer = _recipe_model(directory, bundle['provenance.json']['pins'].get('recipe', 'full_sft'), source=bundle.get('source'), adapter=bundle['provenance.json']['pins'].get('adapter')), _tokenizer(directory)
        ids = tokenizer.encode(prompt, add_special_tokens=True)
        if not 1 <= len(ids) <= LIMITS['sequence_tokens']:
            raise ValueError('Prompt must encode to 1–128 tokens; inputs are never silently truncated.')
        with torch.no_grad():
            output = model.generate(torch.tensor([ids]), attention_mask=torch.ones((1, len(ids)), dtype=torch.long), max_new_tokens=max_new_tokens,
                do_sample=False, pad_token_id=tokenizer.eos_token_id)
        generated = output[0, len(ids):].tolist()
    return {'is_verified': True, 'prompt': prompt, 'generated_token_ids': generated,
            'completion': tokenizer.decode(generated, skip_special_tokens=True), 'decoded_text': True,
            'weights_sha256': bundle['weights_manifest.json']['weights_sha256'],
            'verification_scope': 'local_cpu_huggingface_safetensors_reload', 'production_qualified': False}


def verify_external_loadable(bundle):
    result = generate_candidate_completion(bundle, 'Once upon a time', max_new_tokens=1)
    return {'is_loadable': True, 'format': 'peft_lora_safetensors' if bundle['provenance.json']['pins'].get('recipe') == 'lora_adapter' else 'huggingface_safetensors', 'model_instantiated': True,
            'weights_sha256': result['weights_sha256'], 'verification_scope': result['verification_scope'],
            'independent_runtime_verified': False, 'production_qualified': False}
