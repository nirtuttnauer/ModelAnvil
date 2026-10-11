"""Native Apple Metal four-bit frozen-base adapter training with fenced checkpoints."""
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

from django.db import transaction
from django.utils import timezone

from modelanvil.device_admission import device_available, device_lease
from modelanvil.runners.training import hf_runtime as hf
from modelanvil.runners.training.runtime import digest, _locked_live_run, _finalize_worker_job
from scripts.mlx_candidate_infer import QUANTIZATION, LORA, load_candidate, completion

RUNTIME_ID = 'modelanvil.smollm2-mlx-qlora.v1'
SOURCE, FILE_HASHES, LIMITS, OPTIMIZER = hf.SOURCE, hf.FILE_HASHES, hf.LIMITS, hf.OPTIMIZER
PACKAGES = {**hf.PACKAGES, 'mlx': '0.32.3', 'mlx-metal': '0.32.3', 'mlx-lm': '0.29.1', 'tokenizers': '0.22.2'}
CONTRACT = {'runtime': RUNTIME_ID, 'source': SOURCE, 'file_hashes': FILE_HASHES,
    'packages': PACKAGES, 'recipe': 'qlora_adapter', 'recipes': ['qlora_adapter'],
    'precision': 'fp32', 'quantization': QUANTIZATION, 'quantization_targets': 'linear_layers_only_full_precision_tied_embeddings', 'lora': LORA, 'optimizer': OPTIMIZER,
    'limits': LIMITS, 'placement': 'one_trusted_local_metal_worker', 'device_admission': 'exclusive_posix_user_host_v1'}
CONTRACT_DIGEST = digest(CONTRACT)
file_ref, staged_files, _tokenizer = hf.file_ref, hf.staged_files, hf._tokenizer
is_worker_run = hf.is_worker_run


def require_packages():
    for name, expected in PACKAGES.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        if actual != expected:
            raise ValueError(f'Install {name}=={expected} for this native Metal adapter runtime.')


def validate_options(*, precision='fp32', adapter=None, quantization=None, recipe_type='qlora_adapter'):
    if recipe_type != 'qlora_adapter' or precision != 'fp32' or adapter not in (None, 'qlora') or quantization not in (None, 'int4'):
        raise ValueError('Select QLoRA with FP32 adapters and four-bit affine group-32 base weights.')


def runner_manifest():
    value = hf.runner_manifest()
    value.update(adapter_id=RUNTIME_ID, image=f'local-python-contract@sha256:{CONTRACT_DIGEST}')
    value['capabilities'][0].update(architectures=[RUNTIME_ID], output_schema_refs=['mlx:quantized_lora_safetensors'])
    value['limitations'] = ['One pinned SmolLM2-135M snapshot and one explicit mlx:0 Metal device.',
        'Four-bit affine group-32 frozen base, FP32 rank-8 q/v adapters; no distributed or other-vendor qualification.']
    return value


def build_digest():
    root = Path(__file__).resolve().parents[3]
    return hashlib.sha256((hf.build_digest() + (Path(__file__).read_bytes() +
        (root / 'scripts/mlx_candidate_infer.py').read_bytes()).hex()).encode()).hexdigest()


def observed_device(selector):
    require_packages()
    import mlx.core as mx
    if selector != 'mlx:0' or not mx.metal.is_available() or mx.default_device() != mx.gpu:
        raise ValueError('Select mlx:0 on this native Metal host; CPU training fallback is disabled.')
    recommended = mx.device_info().get('max_recommended_working_set_size')
    active = mx.get_active_memory()
    if type(recommended) is not int or recommended - active < LIMITS['gpu_memory_bytes']:
        raise ValueError('MLX recommended process headroom is unknown or below 4 GiB.')
    return {'device': {'id': 'mlx:0', 'backend': 'mlx', 'name': mx.device_info().get('device_name'),
        'runtime_recommended_memory_bytes': recommended, 'process_headroom_bytes': recommended - active,
        'memory_scope': 'shared_unified'}, 'framework': {'name': 'mlx', 'version': PACKAGES['mlx']},
        'packages': PACKAGES, 'capacity_source': 'MLX recommended process working set, not system-wide free memory'}


def capable_worker(worker):
    caps = worker.capabilities
    return (isinstance(caps, dict) and caps.get('training_runtime') == CONTRACT_DIGEST
        and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes']
        and caps.get('gpu_backend') == 'mlx' and caps.get('gpu_device') == 'mlx:0'
        and caps.get('gpu_packages') == PACKAGES and worker.slots in (0, 1))


def resolve_inputs(**kwargs):
    kwargs.setdefault('recipe_type', 'qlora_adapter')
    return hf.resolve_inputs(**kwargs, profile=sys.modules[__name__])


def checkpoint_bundle(run, checkpoint):
    state = checkpoint.weights_manifest
    if (not checkpoint.is_valid or digest(state) != checkpoint.state_digest or state.get('pins') != run.hardware_config['pins']
        or state.get('step') != checkpoint.step or state.get('run_id') != str(run.run_id)
        or state.get('optimizer') != {**OPTIMIZER, 'updates': checkpoint.step} or state.get('metrics') != checkpoint.metrics):
        raise ValueError('MLX checkpoint checksum, cursor or pinned optimizer changed.')
    with staged_files({**state['files'], 'optimizer.safetensors': state['adam']}, run.tenant_id, run.project_id):
        pass
    return {'config.json': state['pins']['config'], 'files': state['files'], 'source': SOURCE,
        'weights_manifest.json': {'weights_sha256': state['files']['adapters.safetensors']['sha256'],
            'base_weights_sha256': state['files']['model.safetensors']['sha256']},
        'tokenizer_config.json': state['tokenizer'],
        'provenance.json': {'tenant_id': str(run.tenant_id), 'project_id': str(run.project_id),
            'run_id': str(run.run_id), 'pins': state['pins'], 'step': checkpoint.step}}


def restore_optimizer(optimizer, model, directory, step):
    import mlx.core as mx
    from mlx.utils import tree_flatten, tree_unflatten
    optimizer.init(model.trainable_parameters())
    expected = dict(tree_flatten(optimizer.state))
    saved = mx.load(str(directory / 'optimizer.safetensors'))
    if set(saved) != set(expected) or any(saved[n].shape != p.shape or saved[n].dtype != p.dtype
        or not mx.all(mx.isfinite(saved[n])).item() for n, p in expected.items()):
        raise ValueError('MLX optimizer keys, shapes, precision or values changed.')
    if saved['step'].item() != step or saved['learning_rate'].item() != expected['learning_rate'].item():
        raise ValueError('MLX optimizer cursor or learning rate changed.')
    optimizer.state = tree_unflatten(list(saved.items()))


def execute_training(run, context):
    from modelanvil.runners.models import RunnerManifest
    pins = run.hardware_config['pins']
    if not context.heartbeat(progress=run.current_step / run.total_steps):
        return
    runner = RunnerManifest.all_objects.get(manifest_id=pins['runner_id'], tenant_id=run.tenant_id)
    inputs = resolve_inputs(dataset=run.dataset_revision, base=run.base_model_version, tokenizer=run.tokenizer_version,
        runner=runner, pool=run.job.pool, tenant=run.tenant_id, project=run.project_id, steps=run.total_steps,
        require_capacity=False, recipe_type=run.recipe_type, initialization_seed=run.initialization_seed)
    if inputs['pins'] != pins or context.attempt.worker_id != pins['worker_id']:
        raise ValueError('MLX runtime, inputs, device or worker changed after launch.')
    latest = run.checkpoints.filter(is_valid=True).order_by('-step').first()
    if latest:
        checkpoint_bundle(run, latest)
    files = latest.weights_manifest['files'] if latest else inputs['bundle']['files']
    recovery = {**files, **({'optimizer.safetensors': latest.weights_manifest['adam']} if latest else {})}
    import mlx.core as mx
    with device_lease('mlx:0'):
        try:
            _execute_updates(run, context, inputs, files, recovery, latest)
        finally:
            gc.collect()
            mx.clear_cache()


def _execute_updates(run, context, inputs, files, recovery, latest):
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.utils import tree_flatten
    from modelanvil.runners.models import TrainingCheckpoint, TrainingRun
    model = optimizer = loss_fn = gradients = ids = loss = base = None
    try:
        with staged_files(recovery, run.tenant_id, run.project_id) as directory:
            model, tokenizer, config, adapter_config = load_candidate(directory, run.initialization_seed, training=True)
            optimizer = optim.AdamW(learning_rate=OPTIMIZER['learning_rate'], betas=(OPTIMIZER['beta1'], OPTIMIZER['beta2']),
                eps=OPTIMIZER['epsilon'], weight_decay=OPTIMIZER['weight_decay'])
            if latest:
                restore_optimizer(optimizer, model, directory, latest.step)
            def loss_function(model, ids):
                return nn.losses.cross_entropy(model(ids[:, :-1]), ids[:, 1:], reduction='mean')
            loss_fn = nn.value_and_grad(model, loss_function)
            for step in range(run.current_step + 1, run.total_steps + 1):
                if not context.heartbeat(progress=(step - 1) / run.total_steps):
                    return
                sample = inputs['samples'][(step - 1) % len(inputs['samples'])]
                ids = mx.array([sample['token_ids']])
                mx.reset_peak_memory()
                cpu_started, started = time.process_time(), time.perf_counter()
                loss, gradients = loss_fn(model, ids)
                mx.eval(loss, gradients)
                if not mx.isfinite(loss).item() or any(not mx.all(mx.isfinite(g)).item() for _, g in tree_flatten(gradients)):
                    raise ValueError('MLX adapter loss or gradients are non-finite.')
                grad_norm = mx.sqrt(sum(mx.sum(g * g) for _, g in tree_flatten(gradients))).item()
                optimizer.update(model, gradients)
                mx.eval(model.parameters(), optimizer.state)
                post_loss = loss_function(model, ids).item()
                if not mx.isfinite(mx.array(post_loss)).item():
                    raise ValueError('MLX update produced non-finite loss.')
                elapsed = time.perf_counter() - started
                metrics = {'step': step, 'loss': loss.item(), 'post_update_loss': post_loss,
                    'sample_id': sample['sample_id'], 'training_pairs': len(sample['token_ids']) - 1,
                    'cpu_seconds': time.process_time() - cpu_started, 'engine_wall_seconds': elapsed,
                    'gpu_backend': 'mlx', 'gpu_device': 'mlx:0', 'device_residency_checked': True,
                    'gradient_norm': grad_norm, 'trainable_parameters': sum(p.size for _, p in tree_flatten(model.trainable_parameters())),
                    'gpu_allocated_bytes': mx.get_active_memory(), 'peak_allocated_bytes': mx.get_peak_memory(),
                    'peak_reserved_bytes': None, 'gpu_utilization_percent': None,
                    'tokens_per_second': (len(sample['token_ids']) - 1) / elapsed, 'measured_at': timezone.now().isoformat(),
                    'quantization': QUANTIZATION}
                mx.save_safetensors(str(directory / 'adapters.safetensors'), dict(tree_flatten(model.trainable_parameters())))
                mx.save_safetensors(str(directory / 'optimizer.safetensors'), dict(tree_flatten(optimizer.state)))
                (directory / 'adapter_config.json').write_text(json.dumps(adapter_config, sort_keys=True))
                if not latest and step == 1:
                    # Store the actual quantized frozen base once; adapters and moments are per-step.
                    base = {n.replace('.linear.', '.'): p for n, p in tree_flatten(model.parameters()) if not n.endswith(('.lora_a', '.lora_b'))}
                    mx.save_safetensors(str(directory / 'model.safetensors'), base)
                    (directory / 'config.json').write_text(json.dumps(config, sort_keys=True))
                if not context.heartbeat(progress=(step - 1) / run.total_steps):
                    return
                with transaction.atomic():
                    locked = _locked_live_run(context, run.run_id)
                    if locked.current_step != step - 1:
                        raise ValueError('MLX training cursor changed; publication refused.')
                    if not latest and step == 1:
                        files = {**files, **{n: hf._store_file(directory / n, run, context, step) for n in ('model.safetensors', 'config.json')}}
                    saved = {**files, **{n: hf._store_file(directory / n, run, context, step) for n in ('adapters.safetensors', 'adapter_config.json')}}
                    adam = hf._store_file(directory / 'optimizer.safetensors', run, context, step)
                    _locked_live_run(context, run.run_id)
                    state = {'run_id': str(run.run_id), 'step': step, 'pins': run.hardware_config['pins'], 'files': saved,
                        'adam': adam, 'optimizer': {**OPTIMIZER, 'updates': step}, 'tokenizer': inputs['tokenizer'], 'metrics': metrics,
                        'attempt_id': str(context.attempt.attempt_id), 'fencing_token': context.fencing_token}
                    TrainingCheckpoint.all_objects.create(tenant_id=run.tenant_id, training_run=locked, step=step,
                        state_digest=digest(state), weights_manifest=state, metrics=metrics)
                    locked.current_step, locked.latest_loss = step, metrics['loss']
                    locked.metrics_log = [*locked.metrics_log, metrics]
                    locked.status, locked.started_at = TrainingRun.Status.RUNNING, locked.started_at or timezone.now()
                    locked.save(update_fields=['current_step', 'latest_loss', 'metrics_log', 'status', 'started_at', 'updated_at'])
    except Exception as exc:
        import traceback
        traceback.clear_frames(exc.__traceback__)
        raise
    finally:
        model = optimizer = loss_fn = gradients = ids = loss = base = None


def finalize_job(job, status):
    return _finalize_worker_job(job, status, runtime_id=RUNTIME_ID, contract_digest=CONTRACT_DIGEST,
        model_name_prefix='modelanvil-mlx-qlora', checkpoint_bundle=checkpoint_bundle, is_worker_run=is_worker_run)


def generate_candidate_completion(bundle, prompt, max_new_tokens=8):
    if not isinstance(prompt, str) or len(prompt) > 4096 or type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 32:
        raise ValueError('Use up to 4096 prompt characters and 1–32 output tokens.')
    observed_device('mlx:0')
    provenance = bundle['provenance.json']
    with device_lease('mlx:0'):
        model = None
        try:
            with staged_files(bundle['files'], provenance['tenant_id'], provenance['project_id']) as directory:
                model, tokenizer, _, _ = load_candidate(directory)
                ids, text = completion(model, tokenizer, prompt, max_new_tokens)
                model = None
        finally:
            model = None
            import mlx.core as mx
            gc.collect()
            mx.clear_cache()
    return {'is_verified': True, 'completion': text, 'generated_token_ids': ids, 'decoded_text': True,
        'weights_sha256': bundle['weights_manifest.json']['weights_sha256'],
        'verification_scope': 'local_metal_mlx_quantized_adapter_reload', 'production_qualified': False}


def verify_external_loadable(bundle):
    result = generate_candidate_completion(bundle, 'Once upon a time', 1)
    return {'is_loadable': True, 'format': 'mlx_quantized_lora_safetensors', 'model_instantiated': True,
        'weights_sha256': result['weights_sha256'], 'verification_scope': result['verification_scope'],
        'independent_runtime_verified': False, 'production_qualified': False}
