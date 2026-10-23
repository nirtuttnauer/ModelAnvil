"""Non-allocating model eligibility; launch/load paths still verify actual inputs."""
from importlib.util import find_spec

from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.runners.training.registry import runtime_for_architecture


def training_memory_requirements(architecture_ref, source=None):
    module = runtime_for_architecture(architecture_ref)
    if module is None:
        return None
    from modelanvil.runners.training import hf_runtime, mlx_runtime, cpu_hf_runtime
    large = module is hf_runtime and source == hf_runtime.LARGE_GUIDED_SOURCE
    return {'host_memory_bytes': 32 * 1024**3 if large else module.LIMITS['memory_bytes'],
            'accelerator_memory_bytes': 12 * 1024**3 if large else module.LIMITS.get('gpu_memory_bytes', 0),
            'accelerator_backends': ['mps'] if large else ['mlx'] if module is mlx_runtime
                                    else ['cuda', 'rocm', 'xpu', 'mps'] if module is hf_runtime else ['cpu'],
            'runtime_contract': module.CONTRACT_DIGEST,
            'basis': 'Pinned training profile minimum. Preflight checks live accelerator headroom, inputs and allocation.'}


def model_capabilities(version):
    from modelanvil.runners.training import general_runtime, hf_runtime, mlx_runtime, cpu_hf_runtime
    from modelanvil.runners.training import runtime as character
    result = {'train': {'eligible': False, 'recipes': [], 'reason': 'No supported verified training inputs.'},
              'evaluate': {'eligible': False, 'reason': 'This model needs a supported evaluation runtime.'},
              'chat': {'eligible': False, 'devices': [], 'reason': 'Import a supported snapshot for local chat.'},
              'production_qualified': False, 'memory_requirements': {'weights_bytes': None, 'training': None}}
    if version.state in ('archived', 'rejected'):
        for operation in ('train', 'evaluate', 'chat'):
            result[operation]['reason'] = 'This model version is archived or rejected.'
        return result
    tenant = get_active_tenant() or version.tenant_id
    project = get_active_project() or version.project_id
    module = runtime_for_architecture(version.architecture_ref)
    if module in (character, general_runtime):
        try:
            if module is character:
                from modelanvil.runners.local_execution import load_character_bundle
                load_character_bundle(version, tenant=tenant, project=project)
            else:
                from modelanvil.runners.local_execution import load_reference_bundle
                load_reference_bundle(version, tenant=tenant, project=project)
            result['train'] = {'eligible': True, 'recipes': ['full_sft'], 'reason': 'Verified bounded CPU inputs; preflight checks data, capacity and budget.'}
            result['evaluate'] = {'eligible': True, 'reason': 'Verified CPU reference bundle; budgeted durable evaluation supports up to 64 cases.'}
            from modelanvil.runners.local_execution import load_reference_bundle
            bundle, _, _ = load_reference_bundle(version, tenant=tenant, project=project)
            result['chat'] = {'eligible': True, 'devices': ['cpu'], 'format': 'cpu-reference', 'max_tokens': 32,
                'tokenizer_kind': 'byte-v1' if module == general_runtime else 'character-v1',
                'context_limit': bundle['config.json'].get('context_window', 64),
                'reason': 'Verified CPU reference weights; greedy plain text inference only.'}
            result['memory_requirements']['training'] = training_memory_requirements(version.architecture_ref)
        except (ValueError, TypeError, KeyError):
            result['train']['reason'] = 'Model weights or tokenizer are missing, corrupt or incompatible.'
        return result
    try:
        from modelanvil.runners.inference import copy_verified, snapshot, verified_artifact, safetensors_limits
        plan = snapshot(version, tenant, project)
        weight_bytes = sum(verified_artifact(ref, tenant, project).byte_size
                           for name, ref in plan['files'].items() if name.endswith(('.safetensors', '.gguf')))
        result['memory_requirements'] = {'weights_bytes': weight_bytes,
            'training': training_memory_requirements(version.architecture_ref, plan.get('source'))}
        import io
        import json
        config = {}
        if 'config.json' in plan['files']:
            config_ref = plan['files']['config.json']
            if verified_artifact(config_ref, tenant, project).byte_size > 8 * 1024**2:
                raise ValueError('Model configuration exceeds its inspected size limit.')
            raw = io.BytesIO(); copy_verified(config_ref, tenant, project, raw)
            config = json.loads(raw.getvalue())
            if not isinstance(config, dict):
                raise ValueError('Model configuration must be an object.')
        format = plan['format']
        if format == 'gguf':
            from modelanvil.runners.gguf_runtime import MAX_WEIGHT_BYTES
            if not 0 < weight_bytes <= MAX_WEIGHT_BYTES:
                raise ValueError('CPU GGUF weights must fit within the verified 1 GiB limit.')
            if not find_spec('xllamacpp'):
                raise ValueError('Install the optional llama.cpp runtime for CPU GGUF inference.')
            devices = ['cpu']
        elif format == 'mlx':
            if not find_spec('mlx'):
                raise ValueError('Install the Apple MLX runtime before inference.')
            devices = ['mlx:0']
        else:
            limits = safetensors_limits(plan)
            if weight_bytes > limits['weight_bytes'] or (version.parameters_count or 0) > limits['parameters']:
                raise ValueError('This snapshot exceeds the verified FP32 inference limits.')
            if config.get('quantization_config'):
                raise ValueError('Quantized Safetensors require a separately supported runtime.')
            if config.get('model_type') and config['model_type'] not in {'llama','qwen2','mistral','gemma','gemma2','gpt2'}:
                raise ValueError('This architecture is outside the supported text inference runtime.')
            if not find_spec('torch') or not find_spec('transformers'):
                raise ValueError('Install requirements.inference.txt in the API environment before inference.')
            devices = ['cpu']
            import torch
            if torch.backends.mps.is_available():
                devices.append('mps:0')
        result['chat'] = {'eligible': True, 'devices': devices, 'format': format, 'max_tokens': 256,
                          'context_limit': min(2048, config.get('max_position_embeddings', 2048)),
                          'reason': 'Snapshot inputs verified; actual loading and memory admission are checked at generation.'}
        if format == 'safetensors' and 'cpu' in devices:
            result['evaluate'] = {'eligible': True, 'reason': 'Verified bounded CPU snapshot; evaluation rechecks exact inputs and context.'}
        if module in (hf_runtime, mlx_runtime, cpu_hf_runtime):
            recipes = module.CONTRACT['recipes']
            result['train'] = {'eligible': True, 'recipes': recipes, 'reason': 'Pinned profile; training preflight checks exact runtime, tokenizer, device and input bytes.'}
    except (ValueError, TypeError, KeyError, OSError) as exc:
        result['chat']['reason'] = str(exc) if isinstance(exc, ValueError) else 'Snapshot inputs are unavailable or incompatible.'
    return result
