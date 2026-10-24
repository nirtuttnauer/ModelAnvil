"""CPU profile of the same pinned vision-language recipe; GPU qualification stays separate."""
import copy
import sys

from . import vlm_runtime as vlm
from .vlm_runtime import SOURCE, FILE_HASHES, LORA, PACKAGES, OPTIMIZER, require_packages, observed_device, memory_observation, staged_files, validate_options, file_ref, verify_external_loadable
from .runtime import digest

RUNTIME_ID = 'modelanvil.smolvlm-cpu-lora.v1'
DEVICE = 'cpu'
LIMITS = {**vlm.LIMITS, 'gpu_memory_bytes': 0}
CONTRACT = {**copy.deepcopy(vlm.CONTRACT), 'runtime': RUNTIME_ID, 'device': DEVICE, 'cpu_threads': 1, 'limits': LIMITS}
CONTRACT_DIGEST = digest(CONTRACT)


def build_digest(): return vlm.build_digest()

def runner_manifest(): return vlm.runner_manifest(sys.modules[__name__])

def capable_worker(worker): return vlm.capable_worker(worker, sys.modules[__name__])

def resolve_inputs(**kwargs): return vlm.resolve_inputs(**kwargs, profile=sys.modules[__name__])

is_worker_run, checkpoint_bundle = vlm.is_worker_run, vlm.checkpoint_bundle

def execute_training(run, context): return vlm.execute_training(run, context, sys.modules[__name__])

def finalize_job(job, status): return vlm.finalize_job(job, status, sys.modules[__name__])
