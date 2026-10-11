"""Runtime registry: dispatch training-run execution by pinned runtime contract.

The character runtime (:mod:`modelanvil.runners.training.runtime`) and the general
transformer runtime (:mod:`modelanvil.runners.training.general_runtime`) both implement
the same small protocol. Every durable code path resolves the run's pinned runtime and
delegates, so a second runtime can be added without rewriting the worker, launch, export
or accounting paths.
"""
from __future__ import annotations

from typing import Any

from modelanvil.runners.training import general_runtime, hf_runtime
from modelanvil.runners.training import runtime as character_runtime

CHARACTER_RUNTIME_ID = character_runtime.RUNTIME_ID

_MODULES = (character_runtime, general_runtime, hf_runtime)
_BY_ID = {module.RUNTIME_ID: module for module in _MODULES}


def runtime_modules():
    return list(_MODULES)


def runtime_module(runtime_id):
    return _BY_ID.get(runtime_id)


def runtime_for_architecture(architecture_ref):
    return _BY_ID.get(architecture_ref)


def runtime_for_run(run):
    pins = (getattr(run, 'hardware_config', None) or {}).get('pins', {})
    return _BY_ID.get(pins.get('runtime'), character_runtime)


def is_worker_run(run):
    return (getattr(run, 'hardware_config', None) or {}).get('execution_mode') == 'worker'


def resolve_inputs(**kwargs):
    base = kwargs.get('base')
    module = runtime_for_architecture(getattr(base, 'architecture_ref', None) or base)
    if module is None:
        raise ValueError('The selected base model architecture is not a supported training runtime.')
    return module.resolve_inputs(**kwargs)


def capable_worker(worker, base=None):
    module = runtime_for_architecture(getattr(base, 'architecture_ref', None)) if base is not None else character_runtime
    return (module or character_runtime).capable_worker(worker)


def checkpoint_bundle(run, checkpoint):
    return runtime_for_run(run).checkpoint_bundle(run, checkpoint)


def execute_training(run, context):
    return runtime_for_run(run).execute_training(run, context)


def finalize_job(job, status):
    from modelanvil.runners.models import TrainingRun
    run = TrainingRun.all_objects.filter(job=job, tenant_id=job.tenant_id).first()
    module = runtime_for_run(run) if run is not None else character_runtime
    return module.finalize_job(job, status)


def runtime_contract(runtime_id=None):
    module = _BY_ID.get(runtime_id, character_runtime)
    return {'contract': module.CONTRACT, 'contract_digest': module.CONTRACT_DIGEST}


def _bundle_is_general(bundle: dict[str, Any]) -> bool:
    return (bundle or {}).get('config.json', {}).get('runtime') == general_runtime.RUNTIME_ID


def verify_bundle(bundle):
    if (bundle or {}).get('config.json', {}).get('runtime') == hf_runtime.RUNTIME_ID:
        return hf_runtime.verify_external_loadable(bundle)
    if _bundle_is_general(bundle):
        return general_runtime.verify_external_loadable(bundle)
    from modelanvil.runners.training.engine import TrainingEngine
    return TrainingEngine.verify_external_loadable(bundle)


def generate_completion(bundle, prompt, max_new_tokens=8):
    if (bundle or {}).get('config.json', {}).get('runtime') == hf_runtime.RUNTIME_ID:
        return hf_runtime.generate_candidate_completion(bundle, prompt=prompt, max_new_tokens=max_new_tokens)
    if _bundle_is_general(bundle):
        return general_runtime.generate_candidate_completion(bundle, prompt=prompt, max_new_tokens=max_new_tokens)
    from modelanvil.runners.training.engine import TrainingEngine
    return TrainingEngine.generate_candidate_completion(bundle, prompt=prompt, max_new_tokens=max_new_tokens)
