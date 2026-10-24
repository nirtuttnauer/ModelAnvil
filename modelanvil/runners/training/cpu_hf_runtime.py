"""Bounded pretrained SmolLM2 CPU training; GPU/QLoRA gates remain separate."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys

from modelanvil.runners.training import hf_runtime as hf
from modelanvil.runners.training.runtime import digest, _finalize_worker_job

RUNTIME_ID = 'modelanvil.smollm2-cpu-sft.v1'
SOURCE, FILE_HASHES, PACKAGES = hf.SOURCE, hf.FILE_HASHES, hf.PACKAGES
OPTIMIZER, LORA = hf.OPTIMIZER, hf.LORA
LIMITS = {**hf.LIMITS, 'steps': 20, 'memory_bytes': 16 * 1024**3, 'gpu_memory_bytes': 0}
CONTRACT = {**copy.deepcopy(hf.CONTRACT), 'runtime': RUNTIME_ID, 'limits': LIMITS,
            'recipes': ['full_sft', 'lora_adapter', 'continued_pretraining'], 'placement': 'one_trusted_local_cpu_worker',
            'cpu_threads': 1, 'guided_source': None, 'large_guided_source': None}
CONTRACT_DIGEST = digest(CONTRACT)
file_ref, staged_files, _tokenizer = hf.file_ref, hf.staged_files, hf._tokenizer
checkpoint_bundle = hf.checkpoint_bundle
is_worker_run = hf.is_worker_run
generate_candidate_completion = hf.generate_candidate_completion
verify_external_loadable = hf.verify_external_loadable
require_packages = hf.require_packages


def validate_options(**kwargs):
    try:
        hf.validate_options(**kwargs)
    except ValueError as exc:
        raise ValueError(str(exc).replace('GPU', 'CPU')) from None


def runner_manifest():
    value = copy.deepcopy(hf.runner_manifest())
    value.update(adapter_id=RUNTIME_ID, image=f'local-python-contract@sha256:{CONTRACT_DIGEST}')
    value['capabilities'][0]['architectures'] = [RUNTIME_ID]
    value['resources'].update(gpu_count=0, memory_bytes=LIMITS['memory_bytes'])
    value['limitations'] = ['Exact pinned pretrained SmolLM2-135M, FP32 full SFT, rank-8 q/v LoRA or continued pretraining on CPU.',
        'One thread and one dedicated local worker; 1–20 updates, at most 1000 examples and 128 tokens per example.',
        'No QLoRA, guided large model, GPU, distributed, remote, customer quality or production qualification.']
    return value


def build_digest():
    return hashlib.sha256((hf.build_digest() + Path(__file__).read_text()).encode()).hexdigest()


def capable_worker(worker):
    caps = worker.capabilities
    if caps.get('managed_local') or caps.get('setup_profile'):
        from modelanvil.jobs.setup import connection_state
        if connection_state(worker) != 'connected':
            return False
    # Keep the shared placement wire fields; backend/device explicitly identify CPU.
    return (caps.get('training_runtime') == CONTRACT_DIGEST and caps.get('gpu_backend') == 'cpu'
        and caps.get('gpu_device') == 'cpu' and caps.get('gpu_packages') == PACKAGES
        and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes']
        and worker.slots in (0, 1))


def observed_device(selector):
    from modelanvil.device_admission import host_key
    from modelanvil.runners.training.hardware import total_memory_bytes, cpu_brand
    if selector != 'cpu':
        raise ValueError('The bounded pretrained CPU profile requires the explicit cpu device.')
    memory = total_memory_bytes()
    if type(memory) is not int or memory < LIMITS['memory_bytes']:
        raise ValueError('Pretrained CPU training requires at least 16 GiB observed host memory.')
    return {'host_key': host_key(), 'device': {'id': 'cpu', 'backend': 'cpu', 'torch_device': 'cpu',
            'name': cpu_brand(), 'total_memory_bytes': memory}, 'packages': PACKAGES,
            'capacity_source': 'Observed physical host memory; bounded tensors, not a free-memory reservation.'}


def memory_observation(selector):
    value = observed_device(selector)
    return {'total_bytes': value['device']['total_memory_bytes'], 'required_bytes': LIMITS['memory_bytes'],
            'scope': value['capacity_source']}


def resolve_inputs(**kwargs):
    base = kwargs.get('base')
    if base and base.metadata.get('source', SOURCE) != SOURCE:
        raise ValueError('Use the exact pinned 135M base for pretrained CPU training.')
    return hf.resolve_inputs(**kwargs, profile=sys.modules[__name__])


def execute_training(run, context):
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        return hf.execute_training(run, context, profile=sys.modules[__name__])
    finally:
        torch.set_num_threads(previous)


def finalize_job(job, status):
    return _finalize_worker_job(job, status, runtime_id=RUNTIME_ID, contract_digest=CONTRACT_DIGEST,
        model_name_prefix='smollm2-cpu-sft', checkpoint_bundle=checkpoint_bundle,
        is_worker_run=is_worker_run, select_checkpoint=hf.best_checkpoint)
