"""Bounded local generation from verified, project-scoped snapshots."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import gc
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import uuid

from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.identity.models import check_resource_access
from modelanvil.device_admission import device_lease

_allocation = threading.Lock()
MAX_BYTES = 8 * 1024**3
_RUNTIME_CODE = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                 for name in ('inference.py', 'gguf_runtime.py', 'training/hf_runtime.py', 'capabilities.py',
                              '../api/views/model_workspace.py', '../../scripts/mlx_candidate_infer.py', 'vlm_inference.py', 'training/vlm_math.py', 'training/vlm_data.py')}


def generation_configuration(configuration):
    """Compare generation controls, keeping server observations out of A/B settings."""
    return {key: configuration[key] for key in ('max_tokens', 'temperature', 'seed', 'prompt_format') if key in configuration}


def runtime_provenance(format, device):
    import importlib.metadata
    import platform
    from modelanvil.device_admission import host_key
    from modelanvil.runners.training.hardware import cpu_brand
    packages = {'safetensors': ['torch', 'transformers', 'tokenizers', 'safetensors'],
                'vision': ['torch', 'transformers', 'tokenizers', 'safetensors', 'peft', 'pillow', 'torchvision'],
                'mlx': ['mlx', 'mlx-metal', 'mlx-lm', 'transformers', 'tokenizers'],
                'gguf': ['xllamacpp', 'gguf', 'requests']}.get(format, [])
    versions = {}
    for name in packages:
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = None
    return {'implementation': _RUNTIME_CODE, 'format': format, 'device': device,
        'host': host_key(), 'cpu': cpu_brand(), 'platform': platform.platform(), 'python': platform.python_version(),
        'packages': versions}


def runtime_signature(format, device):
    return hashlib.sha256(json.dumps(runtime_provenance(format, device), sort_keys=True).encode()).hexdigest()


def runtime_input_identity(version):
    fields = lambda obj: {field.attname: getattr(obj, field.attname) for field in obj._meta.concrete_fields}
    return hashlib.sha256(json.dumps({'model': fields(version), 'tokenizer': fields(version.tokenizer),
        **({'processor': fields(version.processor)} if version.processor_id else {})},
        sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def probed_devices(version, format, devices, tenant, project):
    from modelanvil.runners.models import InferenceRequest
    rows = InferenceRequest.all_objects.filter(tenant_id=tenant, project_id=project, model_version=version,
        status='completed', configuration___runtime__input_identity=runtime_input_identity(version))
    return [device for device in devices if rows.filter(configuration__device=device,
        configuration___runtime__signature=runtime_signature(format, device)).exists()]


def validate_mlx_profile(config, weight_bytes, *, native_adapter=False):
    from scripts.mlx_candidate_infer import QUANTIZATION
    expected = {'model_type': 'llama', 'hidden_size': 576, 'num_hidden_layers': 30, 'vocab_size': 49152,
                'intermediate_size': 1536, 'num_attention_heads': 9, 'num_key_value_heads': 3, 'tie_word_embeddings': True}
    if (any(config.get(key) != value for key, value in expected.items()) or not 0 < weight_bytes <= 1024**3
            or config.get('quantization') not in ((None, QUANTIZATION) if native_adapter else (None,))
            or config.get('quantization_config')):
        raise ValueError('The current MLX inference profile accepts the bounded dense SmolLM2-135M base or its verified native adapter checkpoint; other models/quantizations require qualification.')


def runtime_observation(session):
    value = {'format': session['format'], 'actual_device': session.get('device', 'cpu')}
    if session['format'] == 'mlx':
        import mlx.core as mx
        value.update(backend='apple-mlx', active_bytes=mx.get_active_memory(), peak_allocated_bytes=mx.get_peak_memory(),
                     reserved_bytes=None, memory_scope='MLX process allocations; no reserved/global-free-memory measurement.')
    elif session['format'] in ('safetensors', 'vision'):
        value['tensor_devices'] = sorted({str(p.device) for p in session['model'].parameters()})
        if str(session['device']).startswith('mps'):
            import torch
            from modelanvil.runners.training.hf_runtime import mps_memory
            value.update(backend='torch-mps', memory=mps_memory(), peak_allocated_bytes=None, reserved_bytes=None,
                         current_allocated_bytes=torch.mps.current_allocated_memory(),
                         memory_scope='Observed PyTorch process allocations/headroom; no true peak/reserved counters.')
        else: value['backend'] = 'torch-cpu' if session['device'] == 'cpu' else 'torch-device'
    elif session['format'] == 'gguf':
        value.update(backend='llama.cpp-cpu', gpu_layers=0, kv_offload=False, op_offload=False)
    if session['format'] == 'vision':
        value['image'] = session['image_pin']
        value['processor'] = {'source': session['processor'].__class__.__name__, 'image_tokens': 64, 'size': 512, 'image_splitting': False}
    return value


def safetensors_limits(plan):
    return {'weight_bytes': 4 * 1024**3, 'parameters': 2000000000} if plan.get('guided_large') else {'weight_bytes': 1024**3, 'parameters': 300000000}


def model_chat_template(version):
    """Completed chat SFT candidates export the runtime's role template."""
    if version.tokenizer.chat_template:
        return version.tokenizer.chat_template
    from modelanvil.runners.models import TrainingRun
    from modelanvil.data.training_import import ROLE_PREFIX_TEMPLATE
    completed = TrainingRun.all_objects.filter(tenant_id=version.tenant_id, output_model_version=version,
        status='completed', job__status='succeeded', hardware_config__pins__chat_sft=True).exists()
    return ROLE_PREFIX_TEMPLATE if completed else ''


def verified_artifact(ref, tenant, project):
    from modelanvil.runners.training.hf_runtime import file_ref
    try:
        if (not isinstance(ref, dict) or set(ref) != {'artifact_id', 'sha256', 'byte_size'}
                or type(ref['byte_size']) is not int):
            raise ValueError()
        uuid.UUID(str(ref['artifact_id']))
        artifact = Artifact.all_objects.get(artifact_id=ref['artifact_id'], tenant_id=tenant)
    except (Artifact.DoesNotExist, KeyError, TypeError, ValueError):
        raise ValueError('Model artifact is unavailable.') from None
    if (file_ref(artifact) != ref or not check_resource_access(artifact, project, tenant)
            or artifact.state != 'committed' or artifact.storage_location_id != 'local'
            or artifact.object_version is not None or not 0 < artifact.byte_size <= MAX_BYTES
            or DeletionTombstone.all_objects.filter(tenant_id=tenant, resource_id=str(artifact.artifact_id)).exists()):
        raise ValueError('Use verified, accessible local model artifacts.')
    return artifact


def copy_verified(ref, tenant, project, target):
    artifact = verified_artifact(ref, tenant, project)
    sha, size = hashlib.sha256(), 0
    with artifact_storage_backend().open(tenant, artifact.object_key) as source:
        while block := source.read(1024 * 1024):
            size += len(block)
            if size > artifact.byte_size:
                raise ValueError('Model artifact exceeds its committed size.')
            sha.update(block)
            target.write(block)
    if size != artifact.byte_size or sha.hexdigest() != artifact.sha256:
        raise ValueError('Model artifact checksum or size changed; loading refused.')


@contextmanager
def staged_snapshot(files, tenant, project):
    from modelanvil.runners.model_catalog import filename_allowed
    if (not isinstance(files, dict) or not 1 <= len(files) <= 64
            or any(not filename_allowed(n) for n in files)):
        raise ValueError('Snapshot contains unsupported filenames.')
    artifacts = [verified_artifact(ref, tenant, project) for ref in files.values()]
    if sum(a.byte_size for a in artifacts) > MAX_BYTES:
        raise ValueError('Snapshot exceeds the 8 GiB import limit.')
    if any(a.byte_size > 8 * 1024**2 for n, a in zip(files, artifacts) if not n.endswith(('.safetensors', '.gguf'))):
        raise ValueError('Auxiliary model files must fit within 8 MiB.')
    with tempfile.TemporaryDirectory(prefix='modelanvil-inference-') as temp:
        directory = Path(temp)
        for name, ref in files.items():
            (directory / name).parent.mkdir(exist_ok=True)
            with (directory / name).open('wb') as target:
                copy_verified(ref, tenant, project, target)
        yield directory


def snapshot(version, tenant, project):
    from modelanvil.runners.training import cpu_hf_runtime
    if not check_resource_access(version, project, tenant) or not check_resource_access(version.tokenizer, project, tenant):
        raise ValueError('Model or tokenizer is outside this project.')
    from modelanvil.runners.training import vlm_runtime, cpu_vlm_runtime
    if version.architecture_ref in (vlm_runtime.RUNTIME_ID, cpu_vlm_runtime.RUNTIME_ID):
        from modelanvil.runners.vlm_inference import snapshot as vision_snapshot
        return vision_snapshot(version, tenant, project)
    import io
    ref = version.metadata.get('snapshot_manifest')
    from modelanvil.runners.alignment import mps_dpo, hf_rlhf
    if version.architecture_ref == hf_rlhf.RUNTIME_ID:
        bundle = hf_rlhf.candidate_bundle(version, tenant, project, role="policy")
        return {"format": "safetensors", "files": bundle["files"], "recipe": "lora_adapter", "trained": True,
            "source": bundle["source"], "adapter": bundle["adapter"]}
    if version.architecture_ref == mps_dpo.RUNTIME_ID:
        from modelanvil.runners.training.runtime import digest
        from modelanvil.runners.training.hf_runtime import file_ref
        bundle = mps_dpo.candidate_bundle(version, tenant, project)
        artifact = Artifact.all_objects.filter(artifact_id=version.artifact_manifest_id, tenant_id=tenant).first()
        if artifact is None or artifact.byte_size > 1024**2:
            raise ValueError('DPO candidate manifest is unavailable or exceeds its size bound.')
        target = io.BytesIO(); copy_verified(file_ref(artifact), tenant, project, target)
        if digest(json.loads(target.getvalue())) != digest(bundle):
            raise ValueError('DPO candidate manifest differs from its committed checkpoint.')
        return {'format': 'safetensors', 'files': bundle['files'], 'recipe': 'lora_adapter', 'trained': True,
                'source': bundle['source'], 'adapter': bundle['adapter']}
    if not ref:
        from modelanvil.runners.models import TrainingRun
        from modelanvil.runners.training import hf_runtime, mlx_runtime, cpu_hf_runtime
        from modelanvil.runners.training.registry import runtime_for_run
        from modelanvil.runners.training.runtime import digest
        run = TrainingRun.all_objects.filter(output_model_version=version, tenant_id=tenant,
            status='completed', job__status='succeeded', base_model_version__architecture_ref__in=[cpu_hf_runtime.RUNTIME_ID, hf_runtime.RUNTIME_ID, mlx_runtime.RUNTIME_ID]).first()
        if run is None or not check_resource_access(run, project, tenant) or run.tokenizer_version_id != version.tokenizer_id:
            raise ValueError('Import a snapshot or complete a supported transformer training run before inference.')
        checkpoint = run.checkpoints.filter(step=version.metadata.get('selected_checkpoint_step', run.total_steps)).first()
        if checkpoint is None or version.metadata.get('checkpoint_digest') != checkpoint.state_digest:
            raise ValueError('Candidate checkpoint lineage changed; inference refused.')
        bundle = runtime_for_run(run).checkpoint_bundle(run, checkpoint)
        artifact = Artifact.all_objects.filter(artifact_id=version.artifact_manifest_id, tenant_id=tenant).first()
        if artifact is None or artifact.byte_size > 1024**2:
            raise ValueError('Candidate manifest is unavailable or exceeds its size limit.')
        from modelanvil.runners.training.hf_runtime import file_ref
        target = io.BytesIO(); copy_verified(file_ref(artifact), tenant, project, target)
        if digest(json.loads(target.getvalue())) != digest(bundle):
            raise ValueError('Candidate manifest differs from its committed checkpoint.')
        return {'format': 'mlx' if run.recipe_type == 'qlora_adapter' else 'safetensors', 'files': bundle['files'], 'recipe': run.recipe_type, 'trained': True,
                'source': bundle.get('source'), 'adapter': bundle['provenance.json']['pins'].get('adapter'), 'guided_large': bundle.get('source') == hf_runtime.LARGE_GUIDED_SOURCE and run.recipe_type == 'lora_adapter'}
    if not ref or str(ref.get('artifact_id')) != version.artifact_manifest_id:
        raise ValueError('Import a pinned model snapshot before local inference.')
    artifact = verified_artifact(ref, tenant, project)
    if artifact.byte_size > 1024 * 1024:
        raise ValueError('Snapshot manifest exceeds its size limit.')
    target = io.BytesIO()
    copy_verified(ref, tenant, project, target)
    try:
        value = json.loads(target.getvalue())
        from modelanvil.runners.training import hf_runtime, mlx_runtime
        profiles = {module.RUNTIME_ID: module for module in (cpu_hf_runtime, hf_runtime, mlx_runtime)}
        if isinstance(value, dict) and set(value) == {'source', 'files'} and version.architecture_ref in profiles:
            source = value['source']
            profile = profiles[version.architecture_ref]
            if profile is hf_runtime and source != profile.SOURCE and not version.metadata.get('managed_local'):
                raise ValueError()
            expected = (profile.FILE_HASHES if source == profile.SOURCE else
                hf_runtime.LARGE_GUIDED_FILE_HASHES if profile is hf_runtime and source == hf_runtime.LARGE_GUIDED_SOURCE else
                hf_runtime.GUIDED_FILE_HASHES if profile is hf_runtime and source == hf_runtime.GUIDED_SOURCE else None)
            files = value['files']
            if (source != version.metadata.get('source') or expected is None
                    or not isinstance(files, dict) or set(files) != set(expected)
                    or any(not isinstance(files[name], dict) or files[name].get('sha256') != sha for name, sha in expected.items())):
                raise ValueError()
            return {**value, 'format': 'mlx' if profile is mlx_runtime else 'safetensors', 'guided_large': source == hf_runtime.LARGE_GUIDED_SOURCE}
        if not isinstance(value, dict) or value['format'] not in {'safetensors', 'gguf', 'mlx'}:
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise ValueError('Snapshot manifest is invalid.') from None


def snapshot_guard(version, tenant, project):
    """Recheck current access and immutable input identity before publishing output."""
    from copy import deepcopy
    from modelanvil.runners.training import runtime, general_runtime
    from modelanvil.runners.training.hf_runtime import file_ref
    def fields(obj):
        return {f.attname: deepcopy(getattr(obj, f.attname)) for f in obj._meta.concrete_fields}
    model_pin, tokenizer_pin = fields(version), fields(version.tokenizer)
    processor_pin = fields(version.processor) if version.processor_id else None
    refs, plan = [], None
    if version.architecture_ref not in (runtime.RUNTIME_ID, general_runtime.RUNTIME_ID):
        plan = snapshot(version, tenant, project)
        refs.extend(plan['files'].values())
    if version.artifact_manifest_id:
        manifest = Artifact.all_objects.filter(artifact_id=version.artifact_manifest_id, tenant_id=tenant).first()
        if manifest is None:
            raise ValueError('Model manifest is unavailable.')
        refs.append(file_ref(manifest))

    def check():
        current = type(version).all_objects.select_related('tokenizer').filter(pk=version.pk, tenant_id=tenant).first()
        if (current is None or current.state in ('archived', 'rejected') or fields(current) != model_pin
                or fields(current.tokenizer) != tokenizer_pin
                or (fields(current.processor) if current.processor_id else None) != processor_pin
                or current.processor_id and not check_resource_access(current.processor, project, tenant)
                or not check_resource_access(current, project, tenant)
                or not check_resource_access(current.tokenizer, project, tenant)):
            raise ValueError('Model inputs or current project access changed; generation stopped.')
        for ref in refs:
            verified_artifact(ref, tenant, project)
    check()
    check.format = plan['format'] if plan else 'cpu-reference'
    check.identity = hashlib.sha256(json.dumps({'model': model_pin, 'tokenizer': tokenizer_pin, 'processor': processor_pin, 'artifacts': refs},
        sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()
    return check


def validate_messages(messages):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
        raise ValueError('Supply 1–64 text messages.')
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                or message['role'] not in {'system', 'user', 'assistant'}
                or not isinstance(message['content'], str) or not message['content']):
            raise ValueError('Messages need a system/user/assistant role and nonempty text content.')
    if sum(len(m['content']) for m in messages) > 32000:
        raise ValueError('Conversation exceeds the 32,000-character limit.')
    return messages


def rendered_prompt(tokenizer, messages, prompt_format='model'):
    if prompt_format == 'chatml':
        return ''.join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages) + '<|im_start|>assistant\n'
    if prompt_format == 'plain':
        if len(messages) != 1 or messages[0]['role'] != 'user':
            raise ValueError('Plain text formatting accepts one user prompt.')
        return messages[0]['content']
    if tokenizer.chat_template:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    if len(messages) == 1 and messages[0]['role'] == 'user':
        return messages[0]['content']
    raise ValueError('This base model has no chat template; use one user prompt or import an instruction model.')


@contextmanager
def local_session(version, *, tenant, project, device='cpu', image_id=None):
    """One model per process and exclusive local device use; close always unloads."""
    from modelanvil.runners.training import runtime, general_runtime
    if version.state in ('archived', 'rejected'):
        raise ValueError('This model version is archived or rejected.')
    if version.architecture_ref in (runtime.RUNTIME_ID, general_runtime.RUNTIME_ID):
        if device != 'cpu':
            raise ValueError('CPU reference candidates require the CPU device.')
        from modelanvil.runners.local_execution import load_reference_bundle
        bundle, _, _ = load_reference_bundle(version, tenant=tenant, project=project)
        if not _allocation.acquire(blocking=False):
            raise ValueError('Local inference is busy; retry after the current request finishes.')
        try:
            with device_lease(device):
                yield {'format': 'cpu-reference', 'bundle': bundle}
        finally:
            _allocation.release()
        return
    plan = snapshot(version, tenant, project)
    if plan['format'] == 'vision':
        from modelanvil.runners.vlm_inference import session as vision_session
        if not _allocation.acquire(blocking=False): raise ValueError('Local inference is busy.')
        try:
            with vision_session(plan, image_id=image_id, tenant=tenant, project=project, device=device) as session:
                yield session
        finally: _allocation.release()
        return
    if image_id is not None: raise ValueError('Image input requires a supported vision model.')
    if not _allocation.acquire(blocking=False):
        raise ValueError('Local inference is busy; retry after the current request finishes.')
    model, session, admission = None, {}, ExitStack()
    try:
        admission.enter_context(device_lease(device))
        with staged_snapshot(plan['files'], tenant, project) as directory:
            if plan['format'] == 'gguf':
                if device != 'cpu':
                    raise ValueError('GGUF GPU inference needs a separately qualified llama.cpp build.')
                from modelanvil.runners.gguf_runtime import GGUFSession
                weights = [n for n in plan['files'] if n.endswith('.gguf')]
                if len(weights) != 1:
                    raise ValueError('Import exactly one GGUF file.')
                model = GGUFSession(directory / weights[0])
                session.update(format='gguf', model=model, device=device)
                yield session
            elif plan['format'] == 'mlx':
                if device != 'mlx:0':
                    raise ValueError('Select mlx:0 explicitly for MLX snapshots.')
                try:
                    import mlx.core as mx
                    from mlx_lm import load
                except ImportError:
                    raise ValueError('Install the optional MLX runtime in a process with Metal access.') from None
                if not mx.metal.is_available() or mx.default_device() != mx.gpu:
                    raise ValueError('MLX Metal must be available and selected; CPU fallback is disabled.')
                config = json.loads((directory / 'config.json').read_text())
                weight_bytes = sum(verified_artifact(ref, tenant, project).byte_size for n, ref in plan['files'].items() if n.endswith('.safetensors'))
                validate_mlx_profile(config, weight_bytes, native_adapter=bool(plan.get('trained') and plan.get('recipe') == 'qlora_adapter'))
                allowance = mx.device_info().get('max_recommended_working_set_size')
                if type(allowance) is not int or allowance - mx.get_active_memory() < 2 * weight_bytes + 256 * 1024**2:
                    raise ValueError('MLX recommended process memory headroom is unknown or insufficient.')
                mx.reset_peak_memory()
                if 'adapters.safetensors' in plan['files']:
                    if not plan.get('trained') or plan.get('recipe') != 'qlora_adapter':
                        raise ValueError('Native adapter inference requires a completed verified QLoRA candidate.')
                    from scripts.mlx_candidate_infer import load_candidate
                    model, tokenizer, config, _ = load_candidate(directory)
                else:
                    model, tokenizer = load(str(directory), tokenizer_config={'local_files_only': True, 'trust_remote_code': False})
                session.update(format='mlx', model=model, tokenizer=tokenizer, device=device, config=config)
                yield session
            else:
                import torch
                from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
                from modelanvil.accelerators import inventory, select_device
                observed = {'backend': 'cpu', 'torch_device': 'cpu'} if device == 'cpu' else select_device(inventory(), device)
                if observed['backend'] == 'mps':
                    import os
                    if os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK') == '1':
                        raise ValueError('Disable MPS CPU fallback before GPU inference.')
                weight_bytes = sum(verified_artifact(ref, tenant, project).byte_size for n, ref in plan['files'].items() if n.endswith('.safetensors'))
                limits = safetensors_limits(plan)
                if weight_bytes > limits['weight_bytes']:
                    raise ValueError('Snapshot weights exceed the verified local runtime limit.')
                required = 4 * weight_bytes + 256 * 1024**2
                if observed['backend'] == 'mps':
                    from modelanvil.runners.training.hf_runtime import mps_memory
                    if mps_memory()['process_headroom_bytes'] < required:
                        raise ValueError('MPS process memory headroom is insufficient for this snapshot.')
                elif observed['backend'] != 'cpu' and (observed.get('total_memory_bytes') or 0) < required:
                    raise ValueError('Device memory is unknown or insufficient for this snapshot.')
                config = AutoConfig.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
                if getattr(config, 'quantization_config', None):
                    raise ValueError('Quantized snapshots need their own qualified runtime.')
                if config.model_type not in {'llama', 'qwen2', 'mistral', 'gemma', 'gemma2', 'gpt2'}:
                    raise ValueError('This text runtime supports Llama, Qwen2, Mistral, Gemma and GPT-2 architectures.')
                dimensions = [(getattr(config, 'num_hidden_layers', 0), 64), (getattr(config, 'hidden_size', 0), 8192),
                              (getattr(config, 'vocab_size', 0), 256000)]
                if any(type(n) is not int or not 1 <= n <= maximum for n, maximum in dimensions):
                    raise ValueError('Model configuration dimensions exceed this bounded runtime.')
                with torch.device('meta'):
                    shape_model = AutoModelForCausalLM.from_config(config, trust_remote_code=False)
                maximum_parameters = limits['parameters']
                if sum(p.numel() for p in shape_model.parameters()) > maximum_parameters:
                    raise ValueError('This snapshot exceeds the verified local runtime parameter limit.')
                del shape_model
                tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
                if 'adapter_config.json' in plan['files']:
                    if not plan.get('trained') or plan.get('recipe') != 'lora_adapter':
                        raise ValueError('Adapter inference requires a completed verified ModelAnvil LoRA candidate and pinned local base.')
                    from modelanvil.runners.training.hf_runtime import _recipe_model
                    model = _recipe_model(directory, 'lora_adapter', source=plan.get('source'), adapter=plan.get('adapter'))
                    info = {key: [] for key in ['missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs']}
                else:
                    model, info = AutoModelForCausalLM.from_pretrained(str(directory), local_files_only=True,
                        trust_remote_code=False, use_safetensors=True, dtype=torch.float32,
                        attn_implementation='eager', output_loading_info=True)
                if any(info[k] for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs']):
                    raise ValueError('Snapshot weights do not completely match its architecture.')
                if any(p.is_meta or not torch.isfinite(p).all().item() for p in model.parameters()):
                    raise ValueError('Snapshot contains missing or non-finite weights.')
                model.eval().to(observed['torch_device'])
                session.update(format='safetensors', model=model, tokenizer=tokenizer,
                               device=observed['torch_device'], config=config)
                yield session
    finally:
        session.clear()
        try:
            if model is not None:
                if hasattr(model, 'close'):
                    model.close()
                del model
            gc.collect()
            if plan['format'] == 'mlx' and 'mx' in locals():
                mx.clear_cache()
            elif plan['format'] == 'safetensors' and 'torch' in locals() and device != 'cpu':
                api = getattr(torch, 'cuda' if device.startswith('rocm:') else device.split(':')[0], None)
                if api is not None and hasattr(api, 'empty_cache'):
                    api.empty_cache()
        finally:
            try:
                admission.close()
            finally:
                _allocation.release()


def generate(session, messages, *, max_tokens=128, temperature=0.0, seed=42, prompt_format='model', cancelled=lambda: False):
    """Yield actual decoded tokens and finish with measured usage. No answer fixtures."""
    validate_messages(messages)
    if type(max_tokens) is not int or not 1 <= max_tokens <= 256:
        raise ValueError('Generate 1–256 tokens.')
    if type(temperature) not in (float, int) or not 0 <= temperature <= 2:
        raise ValueError('Temperature must be between 0 and 2.')
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('Seed must be a nonnegative 32-bit integer.')
    if prompt_format not in {'model', 'plain', 'chatml'}:
        raise ValueError('Choose the imported model template, plain text or ChatML.')
    started, count, finish = time.monotonic(), 0, 'length'
    measured = session.setdefault('measurement', {})
    def observe(prompt_count, generated_count):
        measured.update(usage={'prompt_tokens': prompt_count, 'completion_tokens': generated_count,
            'total_tokens': prompt_count + generated_count}, elapsed_seconds=time.monotonic() - started)
    if session['format'] == 'vision':
        from modelanvil.runners.vlm_inference import generate as vision_generate
        yield from vision_generate(session, messages, max_tokens=max_tokens, temperature=temperature, prompt_format=prompt_format, cancelled=cancelled)
        return
    if session['format'] == 'cpu-reference':
        from modelanvil.runners.training import runtime, general_runtime, registry
        if temperature != 0 or max_tokens > 32:
            raise ValueError('CPU reference inference supports greedy decoding and 1–32 tokens.')
        if prompt_format == 'chatml':
            raise ValueError('CPU reference inference uses plain text; ChatML is unsupported.')
        prompt = rendered_prompt(None, messages, 'plain')
        bundle = session['bundle']
        module = general_runtime if bundle['config.json']['runtime'] == general_runtime.RUNTIME_ID else runtime
        prompt_count = len(module.encode(prompt, bundle['tokenizer_config.json']))
        if prompt_count + max_tokens > bundle['config.json'].get('context_window', 64):
            raise ValueError('Prompt and output exceed the CPU reference context limit.')
        observe(prompt_count, 0)
        if cancelled():
            finish = 'cancelled'
        else:
            output = registry.generate_completion(bundle, prompt, max_new_tokens=max_tokens)
            count = len(output['generated_token_ids'])
            observe(prompt_count, count)
            finish = 'stop' if output['generated_token_ids'][-1:] == [2] else 'length'
            yield {'text': output['completion']}
        yield {'finish_reason': finish, 'elapsed_seconds': time.monotonic()-started,
               'usage': {'prompt_tokens': prompt_count, 'completion_tokens': count, 'total_tokens': prompt_count+count}}
        return
    if session['format'] == 'gguf':
        yield from session['model'].generate(messages, max_tokens=max_tokens, temperature=temperature,
            seed=seed, prompt_format=prompt_format, cancelled=cancelled, started=started, measurement=measured)
        return
    if session['format'] == 'mlx':
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache
        from mlx_lm.sample_utils import make_sampler
        tokenizer = session['tokenizer']
        ids = tokenizer.encode(rendered_prompt(tokenizer, messages, prompt_format),
            add_special_tokens=prompt_format == 'plain' or (prompt_format == 'model' and not bool(tokenizer.chat_template)))
        if not ids or len(ids) + max_tokens > min(2048, session['config'].get('max_position_embeddings', 2048)):
            raise ValueError('MLX prompt and output must fit within 2,048 tokens and the model context.')
        observe(len(ids), 0)
        mx.random.seed(seed)
        sampler, cache = make_sampler(temp=temperature), make_prompt_cache(session['model'])
        current, detokenizer = mx.array(ids, dtype=mx.int32), tokenizer.detokenizer
        # Synchronous steps avoid mlx-lm's speculative one-token lookahead on cancellation.
        for _ in range(max_tokens):
            if cancelled():
                finish = 'cancelled'; break
            if mx.default_device() != mx.gpu:
                raise ValueError('MLX GPU selection changed; CPU fallback is disabled.')
            logits = session['model'](current[None], cache=cache)[:, -1, :].astype(mx.float32)
            if not mx.all(mx.isfinite(logits)).item():
                raise ValueError('MLX inference produced non-finite logits.')
            token = int(sampler(logits - mx.logsumexp(logits, keepdims=True)).item())
            count += 1
            observe(len(ids), count)
            if token in tokenizer.eos_token_ids:
                finish = 'stop'; break
            detokenizer.add_token(token)
            segment = detokenizer.last_segment
            current = mx.array([token], dtype=mx.int32)
            if segment:
                yield {'text': segment}
        if finish != 'cancelled':
            detokenizer.finalize()
            segment = detokenizer.last_segment
            if segment:
                yield {'text': segment}
        yield {'finish_reason': finish, 'elapsed_seconds': time.monotonic() - started,
               'usage': {'prompt_tokens': len(ids), 'completion_tokens': count, 'total_tokens': len(ids) + count}}
        return
    import torch
    tokenizer, model = session['tokenizer'], session['model']
    prompt = rendered_prompt(tokenizer, messages, prompt_format)
    ids = tokenizer.encode(prompt, add_special_tokens=prompt_format == 'plain' or (prompt_format == 'model' and not bool(tokenizer.chat_template)))
    context_limit = min(2048, getattr(session['config'], 'max_position_embeddings', 2048))
    if not ids or len(ids) + max_tokens > context_limit:
        raise ValueError(f'Prompt and output must fit within {context_limit} tokens; shorten the conversation.')
    observe(len(ids), 0)
    current = torch.tensor([ids], dtype=torch.long, device=session['device'])
    # Sampling on CPU keeps the seeded generator independent of global RNG/device support.
    rng = torch.Generator(device='cpu').manual_seed(seed)
    generated, decoded, past = [], '', None
    eos = tokenizer.eos_token_id
    with torch.inference_mode():
        for _ in range(max_tokens):
            if cancelled():
                finish = 'cancelled'; break
            result = model(input_ids=current, past_key_values=past, use_cache=True)
            logits = result.logits[0, -1].float().cpu()
            if not torch.isfinite(logits).all().item():
                raise ValueError('Inference produced non-finite logits.')
            next_id = int(torch.argmax(logits).item()) if temperature == 0 else int(torch.multinomial(
                torch.softmax(logits / temperature, dim=-1), 1, generator=rng).item())
            count += 1
            observe(len(ids), count)
            if next_id == eos:
                finish = 'stop'; break
            generated.append(next_id)
            text = tokenizer.decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)
            # Delay incomplete UTF-8 replacements until a following token completes them.
            if not text.endswith('\ufffd') and text.startswith(decoded):
                yield {'text': text[len(decoded):]}
                decoded = text
            past = result.past_key_values
            current = torch.tensor([[next_id]], dtype=torch.long, device=session['device'])
    yield {'finish_reason': finish, 'elapsed_seconds': time.monotonic() - started,
           'usage': {'prompt_tokens': len(ids), 'completion_tokens': count, 'total_tokens': len(ids) + count}}
