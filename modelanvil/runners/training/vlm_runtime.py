"""Pinned local SmolVLM LoRA training with paired asset admission and durable checkpoints."""
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
from contextlib import contextmanager, ExitStack
import tempfile

from django.db import transaction

from modelanvil.artifacts.storage import LocalArtifactStorage, artifact_storage_backend
from modelanvil.device_admission import device_available
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Worker
from modelanvil.runners.inference import copy_verified, verified_artifact, runtime_input_identity
from modelanvil.runners.training import hf_runtime as hf, cpu_hf_runtime as cpu
from modelanvil.runners.training.runtime import digest, read_artifact
from . import vlm_math as math, vlm_data

RUNTIME_ID = 'modelanvil.smolvlm-mps-lora.v1'
DEVICE = 'mps:0'
SOURCE, FILE_HASHES, LORA = math.SOURCE, math.FILE_HASHES, math.ADAPTER
file_ref = hf.file_ref
PACKAGES = {**hf.PACKAGES, 'peft': '0.21.2', 'accelerate': '1.15.0', 'pillow': '13.0.0', 'torchvision': '0.28.0'}
LIMITS = {'rows': 32, 'steps': 20, 'sequence_tokens': 128, 'memory_bytes': 16 * 1024**3,
    'gpu_memory_bytes': 4 * 1024**3, 'weight_bytes': 2 * 1024**3, 'aux_bytes': 8 * 1024**2}
OPTIMIZER = {**hf.OPTIMIZER, 'learning_rate': .00002}
CONTRACT = {'runtime': RUNTIME_ID, 'source': SOURCE, 'files': FILE_HASHES, 'packages': PACKAGES,
    'device': DEVICE, 'precision': 'fp32', 'torch_threads': 1, 'recipe': 'lora_adapter', 'recipes': ['lora_adapter'],
    'adapter': LORA, 'optimizer': OPTIMIZER, 'initialization_seed': 42, 'limits': LIMITS,
    'processor_overrides': math.PROCESSOR, 'image_formats': ['image/png', 'image/jpeg'],
    'images_per_sample': 1, 'image_bytes': 2 * 1024**2, 'image_pixels': 1024**2,
    'assistant_labels': 'native_template_prefix_including_end_of_utterance', 'production_qualified': False}
CONTRACT_DIGEST = digest(CONTRACT)


def require_packages():
    for name, expected in PACKAGES.items():
        try: installed = importlib.metadata.version(name).split('+')[0]
        except importlib.metadata.PackageNotFoundError: installed = None
        if installed != expected: raise ValueError(f'Install {name}=={expected} for the pinned vision-language profile.')


def runner_manifest(profile=None):
    profile = profile or sys.modules[__name__]
    return {'schema_version': '1.0', 'adapter_id': profile.RUNTIME_ID, 'version': '1', 'platform_api': 'v1',
        'image': f'local-python-contract@sha256:{profile.CONTRACT_DIGEST}', 'license': 'Apache-2.0 model; libraries retain their licenses',
        'capabilities': [{'kind': 'train', 'input_schema_refs': ['urn:modelanvil:schema:sample-envelope:1.0'],
            'output_schema_refs': ['huggingface:safetensors'], 'formats': ['image', 'text'],
            'architectures': [profile.RUNTIME_ID], 'recovery': 'verified_checkpoint'}],
        'resources': {'cpu_cores': 1, 'memory_bytes': LIMITS['memory_bytes'], 'gpu_count': 0 if profile.DEVICE == 'cpu' else 1,
            'disk_bytes': 2 * 1024**3, 'distributed': False},
        'permissions': {'network_hosts': [], 'artifact_access': ['read_job_inputs', 'write_attempt_staging'], 'secret_kinds': []},
        'dependencies': [], 'limitations': ['Exact SmolVLM-256M snapshot and processor, FP32 text-decoder rank-eight q/v LoRA only.',
            'One PNG/JPEG image per paired sample, 512px tile,128 tokens,1–20 updates; current profile device only.',
            'No remote media URLs, video, full-model/quantized training, customer or production qualification.']}


def _source_digest():
    root = Path(__file__).resolve().parents[3]
    names = ('modelanvil/runners/training/vlm_runtime.py', 'modelanvil/runners/training/cpu_vlm_runtime.py',
        'modelanvil/runners/training/vlm_math.py', 'modelanvil/runners/training/vlm_data.py',
        'modelanvil/runners/training/registry.py', 'modelanvil/runners/training/runtime.py',
        'modelanvil/runners/training/hf_runtime.py', 'modelanvil/runners/alignment/torch_rlhf.py', 'modelanvil/runners/training/admission.py',
        'modelanvil/runners/inference.py', 'modelanvil/runners/vlm_inference.py', 'modelanvil/jobs/models.py', 'modelanvil/device_admission.py',
        'scripts/vlm_candidate_infer.py', 'scripts/score_vlm_candidate.py', 'modelanvil/api/views/model_workspace.py',
        'modelanvil/api/views/training_views.py', 'modelanvil/runners/training/preflight_report.py', 'modelanvil/runners/capabilities.py', 'modelanvil/runners/guided_comparison.py', 'requirements.vision.txt')
    return hashlib.sha256(b''.join((root / name).read_bytes() for name in names)).hexdigest()


_BUILD_DIGEST = _source_digest()


def build_digest():
    if _source_digest() != _BUILD_DIGEST:
        raise ValueError('Vision runtime changed on disk; restart API and worker before launch or recovery.')
    return _BUILD_DIGEST


def validate_options(*, precision='fp32', adapter=None, quantization=None, recipe_type='lora_adapter'):
    if precision != 'fp32' or adapter not in (None, 'lora') or quantization not in (None, 'none') or recipe_type != 'lora_adapter':
        raise ValueError('This vision profile supports FP32 text-decoder LoRA only; other recipes require qualification.')


def observed_device(selector):
    from modelanvil.runners.training.hardware import total_memory_bytes
    memory = total_memory_bytes()
    if memory is None or memory < LIMITS['memory_bytes']: raise ValueError('Vision execution requires at least 16 GiB of known host memory.')
    if selector == 'cpu': return cpu.observed_device(selector)
    if selector != 'mps:0': raise ValueError('The named vision profile supports explicit cpu or mps:0 only.')
    return hf.observed_device(selector)


def memory_observation(selector):
    return cpu.memory_observation(selector) if selector == 'cpu' else hf.memory_observation(selector)


def capable_worker(worker, profile=None):
    profile = profile or sys.modules[__name__]
    caps = worker.capabilities
    return (caps.get('training_runtime') == profile.CONTRACT_DIGEST and caps.get('gpu_device') == profile.DEVICE
        and caps.get('gpu_backend') == ('cpu' if profile.DEVICE == 'cpu' else 'mps') and caps.get('gpu_packages') == PACKAGES
        and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes']
        and worker.slots in (0, 1) and worker.status in ('available', 'busy', 'draining'))


@contextmanager
def staged_files(files, tenant, project):
    allowed = set(FILE_HASHES) | {'adapter_model.safetensors', 'adapter_config.json', 'optimizer.safetensors'}
    if not isinstance(files, dict) or not files or set(files) - allowed:
        raise ValueError('Vision snapshot contains unsupported filenames.')
    with tempfile.TemporaryDirectory(prefix='modelanvil-vlm-') as temp:
        directory = Path(temp)
        for name, ref in files.items():
            artifact = verified_artifact(ref, tenant, project)
            maximum = LIMITS['weight_bytes'] if name == 'model.safetensors' else LIMITS['aux_bytes']
            if artifact.byte_size > maximum: raise ValueError('Vision snapshot file exceeds its declared size bound.')
            with (directory / name).open('wb') as output: copy_verified(ref, tenant, project, output)
        yield directory


def resolve_inputs(*, dataset, base, tokenizer, runner, pool, tenant, project, steps, require_capacity=True,
                   recipe_type='lora_adapter', initialization_seed=42, profile=None):
    profile = profile or sys.modules[__name__]
    require_packages()
    if recipe_type != 'lora_adapter' or initialization_seed != 42 or type(steps) is not int or not 1 <= steps <= LIMITS['steps']:
        raise ValueError('Use 1–20 FP32 vision LoRA updates with pinned initialization seed42.')
    if (not all((dataset, base, tokenizer, runner, pool)) or not project or not isinstance(artifact_storage_backend(), LocalArtifactStorage)
            or any(not check_resource_access(obj, project, tenant) for obj in (dataset, base, tokenizer, runner, pool))):
        raise ValueError('Select accessible published vision data, local base/processor, tokenizer, runner and pool in a project.')
    if (not isinstance(base.metadata, dict) or not isinstance(tokenizer.compatibility, dict)
            or base.processor_id and not isinstance(base.processor.metadata, dict)):
        raise ValueError('Vision source metadata must be an object.')
    if (base.state in ('archived', 'rejected') or base.architecture_ref != profile.RUNTIME_ID or base.tokenizer_id != tokenizer.pk or base.processor_id is None
            or not check_resource_access(base.processor, project, tenant) or base.metadata.get('source') != SOURCE
            or tokenizer.compatibility.get('hf_snapshot') != SOURCE
            or base.processor.metadata.get('vision_profile') != math.PROCESSOR
            or base.processor.configuration_digest != digest({'source_files': FILE_HASHES, 'overrides': math.PROCESSOR})):
        raise ValueError('Use the exact pinned vision base, tokenizer and processor profile.')
    if (not runner.enabled or runner.manifest != profile.runner_manifest() or runner.digest != digest(profile.runner_manifest())
            or runner.compatibility.get('contract_digest') != profile.CONTRACT_DIGEST
            or pool.status not in (('active',) if require_capacity else ('active', 'draining'))):
        raise ValueError('Enable the exact vision runtime manifest and active worker pool.')
    ref = base.metadata.get('snapshot_manifest')
    artifact = verified_artifact(ref, tenant, project)
    if str(artifact.artifact_id) != base.artifact_manifest_id or base.processor.metadata.get('artifact_manifest_id') != base.artifact_manifest_id:
        raise ValueError('Vision base and processor must reference the same immutable snapshot manifest.')
    raw = read_artifact(artifact, tenant, project)
    try: bundle = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError): raise ValueError('Vision base manifest is malformed.') from None
    if (not isinstance(bundle, dict) or bundle.get('source') != SOURCE or set(bundle.get('files', {})) != set(FILE_HASHES)
            or any(not isinstance(bundle['files'][name], dict) or bundle['files'][name].get('sha256') != sha for name, sha in FILE_HASHES.items())):
        raise ValueError('Vision base/processor files differ from the pinned complete snapshot.')
    workers = list(Worker.all_objects.filter(tenant_id=tenant, pool=pool, status__in=('available', 'busy') if require_capacity else ('available', 'busy', 'draining')))
    if len(workers) != 1 or not profile.capable_worker(workers[0]) or require_capacity and (workers[0].slots < 1 or workers[0].drain_requested):
        raise ValueError('Use a dedicated pool with one matching available single-slot vision worker.')
    worker = workers[0]; observed = profile.observed_device(profile.DEVICE)
    if require_capacity and not device_available(profile.DEVICE): raise ValueError('The selected local vision device is busy.')
    with staged_files(bundle['files'], tenant, project) as directory:
        processor = math.processor(directory)
        if len(processor.tokenizer) != tokenizer.vocabulary_size or processor.chat_template != tokenizer.chat_template:
            raise ValueError('Vision tokenizer/template differ from the pinned processor.')
        data = vlm_data.samples(dataset, processor, tenant, project)
    config = {'runtime': profile.RUNTIME_ID, 'source': SOURCE, 'processor_overrides': math.PROCESSOR,
        'sequence_tokens': 128, 'model_role': 'vision_language'}
    pins = {'runtime': profile.RUNTIME_ID, 'contract_digest': profile.CONTRACT_DIGEST, 'build_digest': profile.build_digest(),
        'dataset_id': str(dataset.revision_id), 'dataset_digest': dataset.manifest_digest,
        'base_id': str(base.model_version_id), 'base_artifact_id': str(artifact.artifact_id), 'base_digest': hashlib.sha256(raw).hexdigest(),
        'base_input_identity': runtime_input_identity(base), 'tokenizer_id': str(tokenizer.tokenizer_id),
        'tokenizer_digest': digest({n: r for n, r in bundle['files'].items() if n != 'model.safetensors'}),
        'processor_identity': json.loads(json.dumps({f.attname: getattr(base.processor, f.attname) for f in base.processor._meta.concrete_fields}, default=str)),
        'processor_id': str(base.processor.processor_id), 'processor_digest': digest({'source_files': FILE_HASHES, 'overrides': math.PROCESSOR}),
        'runner_id': str(runner.manifest_id), 'runner_digest': runner.digest, 'pool_id': pool.pk, 'worker_id': worker.pk,
        'steps': steps, 'config': config, 'source': SOURCE, 'optimizer': OPTIMIZER, 'adapter': LORA, 'recipe': 'lora_adapter',
        'initialization_seed': 42, 'sample_order': 'seeded_epoch_shuffle_v1', 'chat_sft': True, 'accelerator': observed,
        'sample_digest': digest(data['train']), 'validation_digest': digest(data['validation']), 'protected_test_digest': digest(data['test']),
        'asset_pins': {name: [row['image'] for row in rows] for name, rows in data.items()},
        'splits': {'consumed': 'train', 'train_rows': len(data['train']), 'excluded_rows': {name: len(rows) for name, rows in data.items() if name != 'train'}},
        'trainable_parameters': 460800, 'production_qualified': False}
    return {'pins': pins, 'bundle': bundle, 'tokenizer': {'kind': 'huggingface-vision', 'source': SOURCE},
        'samples': data['train'], 'validation_samples': data['validation'], 'protected_test_samples': data['test'],
        'sequences': [row['token_ids'] for row in data['train']], 'checkpoint_bytes': 12 * 460800 + 1024**2,
        'checkpoint_count': steps, 'staging_bytes': 2 * bundle['files']['model.safetensors']['byte_size']}


def is_worker_run(run):
    return (run.hardware_config or {}).get('execution_mode') == 'worker'


def checkpoint_bundle(run, checkpoint):
    state = checkpoint.weights_manifest
    if (not checkpoint.is_valid or digest(state) != checkpoint.state_digest or state.get('pins') != run.hardware_config['pins']
            or state.get('step') != checkpoint.step or state.get('run_id') != str(run.run_id)
            or state.get('metrics') != checkpoint.metrics
            or set(state.get('files', {})) != set(FILE_HASHES) | {'adapter_model.safetensors', 'adapter_config.json'}):
        raise ValueError('Vision checkpoint inputs, cursor or model/processor files changed.')
    with staged_files({**state['files'], 'optimizer.safetensors': state['adam']}, run.tenant_id, run.project_id): pass
    return {'config.json': state['pins']['config'], 'files': state['files'], 'source': SOURCE,
        'weights_manifest.json': {'weights_sha256': state['files']['adapter_model.safetensors']['sha256'],
            'base_weights_sha256': state['files']['model.safetensors']['sha256']},
        'processor_config.json': {'source': SOURCE, 'overrides': math.PROCESSOR, 'processor_id': state['pins']['processor_id']},
        'provenance.json': {'run_id': str(run.run_id), 'tenant_id': str(run.tenant_id), 'project_id': str(run.project_id), 'step': checkpoint.step, 'pins': state['pins']},
        'production_qualified': False}


def _authorized_budget(run):
    from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
    reservation = BudgetReservation.all_objects.filter(tenant_id=run.tenant_id, job_id=run.job.job_id,
        reservation_id=run.resource_reservation_id, state='reserved').first()
    policy = BudgetPolicy.all_objects.select_for_update().filter(pk=reservation.policy_id, tenant_id=run.tenant_id).first() if reservation else None
    period, committed = BudgetReservation.current_commitment(policy) if policy else (None, None)
    start = (run.hardware_config.get('recovery') or {}).get('start_step', 0)
    if (policy is None or not policy.enabled or policy.unit != 'training_steps' or policy.currency
            or reservation.period_start != period or reservation.estimated_amount != run.total_steps - start
            or committed > policy.limit_amount):
        raise ValueError('Vision training budget is no longer authorized.')


def _current_inputs(run, profile):
    from modelanvil.identity.models import Tenant
    if (run.job.project_id != run.project_id or run.job.pool_id != run.pool_id
            or run.job.payload != {'type': 'qualified_training', 'run_id': str(run.run_id)}):
        raise ValueError('Vision job, project or pool differs from its pinned training run.')
    if not Tenant.objects.filter(pk=run.tenant_id, status='active').exists():
        raise ValueError('Vision training tenant is no longer active.')
    from modelanvil.runners.models import RunnerManifest
    runner = RunnerManifest.all_objects.filter(tenant_id=run.tenant_id, manifest_id=run.hardware_config['pins']['runner_id']).first()
    prepared = profile.resolve_inputs(dataset=run.dataset_revision, base=run.base_model_version, tokenizer=run.tokenizer_version,
        runner=runner, pool=run.pool, tenant=run.tenant_id, project=run.project_id, steps=run.total_steps,
        require_capacity=False, recipe_type=run.recipe_type, initialization_seed=run.initialization_seed)
    if prepared['pins'] != run.hardware_config['pins']:
        raise ValueError('Vision source, assets, processor, code or worker changed after launch.')
    _authorized_budget(run)
    return prepared


def _validation(model, rows, processor, run, device):
    import torch
    total, tokens = 0., 0
    with torch.no_grad():
        for sample in rows:
            encoded, prefix = vlm_data.materialize(sample, processor, run.tenant_id, run.project_id)
            count = len(sample['token_ids']) - prefix
            total += float(math.answer_loss(model, encoded, prefix, device)) * count; tokens += count
    return {'loss': total / tokens, 'prediction_tokens': tokens, 'samples': len(rows)}


def execute_training(run, context, profile=None):
    import gc
    import time
    import torch
    from django.utils import timezone
    from safetensors.torch import save_file
    from modelanvil.device_admission import device_lease
    from modelanvil.runners.models import TrainingRun, TrainingCheckpoint
    from modelanvil.runners.training.runtime import _locked_live_run
    from modelanvil.runners.alignment.torch_rlhf import apply_update
    profile = profile or sys.modules[__name__]
    previous_threads = torch.get_num_threads(); torch.set_num_threads(1)
    model = optimizer = loss = None
    trainable = []
    admission = ExitStack()
    try:
        with transaction.atomic():
            locked = _locked_live_run(context, run.run_id)
            inputs = _current_inputs(locked, profile)
            if locked.started_at is None:
                locked.started_at, locked.status = timezone.now(), TrainingRun.Status.RUNNING
                locked.save(update_fields=['started_at', 'status', 'updated_at'])
        latest = run.checkpoints.filter(is_valid=True).order_by('-step').first()
        if latest: checkpoint_bundle(run, latest)
        if (latest.step if latest else 0) != run.current_step:
            raise ValueError('Vision checkpoint and committed cursor disagree.')
        files = latest.weights_manifest['files'] if latest else inputs['bundle']['files']
        recovery = {**files, **({'optimizer.safetensors': latest.weights_manifest['adam']} if latest else {})}
        admission.enter_context(device_lease(profile.DEVICE))
        with hf.deterministic_updates():
            with staged_files(recovery, run.tenant_id, run.project_id) as directory:
                processor = math.processor(directory)
                model = math.load_model(directory, training=True).to(profile.DEVICE)
                trainable = [p for p in model.parameters() if p.requires_grad]
                if sum(p.numel() for p in trainable) != 460800 or any(str(p.device) != profile.DEVICE for p in model.parameters()):
                    raise ValueError('Vision parameter scope or explicit device residency changed.')
                optimizer = torch.optim.AdamW(trainable, lr=OPTIMIZER['learning_rate'], betas=(.9,.999), eps=1e-8, weight_decay=0., foreach=False)
                if latest: hf._restore_optimizer(model, optimizer, directory, latest.step)
                before = _validation(model, inputs['validation_samples'], processor, run, profile.DEVICE)
                baseline = latest.metrics['validation_loss_before_training'] if latest else before['loss']
                for step in range(run.current_step + 1, run.total_steps + 1):
                    if not context.heartbeat(progress=(step - 1) / run.total_steps): return
                    with transaction.atomic():
                        locked = _locked_live_run(context, run.run_id); _current_inputs(locked, profile)
                    sample = inputs['samples'][hf.training_sample_index(step, len(inputs['samples']), inputs['pins'])]
                    encoded, prefix = vlm_data.materialize(sample, processor, run.tenant_id, run.project_id)
                    cpu_started, wall_started = time.process_time(), time.perf_counter()
                    loss = math.answer_loss(model, encoded, prefix, profile.DEVICE)
                    metrics = apply_update(loss, model, optimizer, 1.)
                    if str(loss.device) != profile.DEVICE or any(p.grad is not None for p in model.parameters() if not p.requires_grad):
                        raise ValueError('Vision training gradients left the declared adapter/device scope.')
                    after = _validation(model, inputs['validation_samples'], processor, run, profile.DEVICE)
                    if profile.DEVICE == 'mps:0': torch.mps.synchronize()
                    metrics.update(measured_at=timezone.now().isoformat(), validation_samples=after['samples'],
                        gpu_allocated_bytes=torch.mps.current_allocated_memory() if profile.DEVICE == 'mps:0' else None,
                        step=step, sample_id=sample['sample_id'], image_sha256=sample['image']['sha256'],
                        training_pairs=len(sample['token_ids']) - prefix, cpu_seconds=time.process_time() - cpu_started,
                        engine_wall_seconds=time.perf_counter() - wall_started, total_parameters=sum(p.numel() for p in model.parameters()),
                        validation_loss_before_training=baseline, validation_loss=after['loss'], validation_prediction_tokens=after['prediction_tokens'],
                        gpu_backend='cpu' if profile.DEVICE=='cpu' else 'mps', gpu_device=profile.DEVICE, device_residency_checked=True,
                        peak_allocated_bytes=None, peak_reserved_bytes=None, production_qualified=False)
                    metrics['tokens_per_second'] = metrics['training_pairs'] / metrics['engine_wall_seconds']
                    if profile.DEVICE == 'mps:0': metrics['unified_memory'] = hf.mps_memory()
                    model.save_pretrained(str(directory), safe_serialization=True, save_embedding_layers=False)
                    save_file(hf._optimizer_state(model, optimizer), str(directory / 'optimizer.safetensors'))
                    with transaction.atomic():
                        locked = _locked_live_run(context, run.run_id); _current_inputs(locked, profile)
                        state = {'run_id': str(run.run_id), 'step': step, 'pins': inputs['pins'], 'metrics': metrics,
                            'files': {**inputs['bundle']['files'], **{name: hf._store_file(directory / name, run, context, step)
                                for name in ('adapter_model.safetensors', 'adapter_config.json')}},
                            'adam': hf._store_file(directory / 'optimizer.safetensors', run, context, step)}
                        TrainingCheckpoint.all_objects.create(tenant_id=run.tenant_id, training_run=locked, step=step,
                            state_digest=digest(state), weights_manifest=state, metrics=metrics)
                        locked.current_step, locked.latest_loss = step, metrics['loss']
                        locked.metrics_log = [*locked.metrics_log, metrics]
                        locked.save(update_fields=['current_step', 'latest_loss', 'metrics_log', 'updated_at'])
                        run.current_step = step
            model = optimizer = loss = None; trainable = []; gc.collect()
            if profile.DEVICE == 'mps:0': torch.mps.empty_cache()
        admission.close()
        # Independent scoring runs after releasing the training device and model allocations.
        evaluation = _independent_evaluation(run, context, inputs)
        with transaction.atomic():
            locked = _locked_live_run(context, run.run_id); _current_inputs(locked, profile)
            locked.hardware_config = {**locked.hardware_config, 'independent_evaluation': evaluation}
            locked.save(update_fields=['hardware_config', 'updated_at'])
    except Exception:
        # Trusted finalization derives failure from missing cursor/evaluation; no input text leaves through error egress.
        return
    finally:
        try:
            model = optimizer = loss = None; trainable = []
            gc.collect()
            if profile.DEVICE == 'mps:0': torch.mps.empty_cache()
            torch.set_num_threads(previous_threads)
        finally:
            admission.close()


def finalize_job(job, status, profile=None):
    from modelanvil.jobs.models import Job
    from modelanvil.runners.models import TrainingRun
    from modelanvil.runners.training.runtime import _finalize_worker_job
    profile = profile or sys.modules[__name__]
    run = TrainingRun.all_objects.select_for_update().get(job=job, tenant_id=job.tenant_id)
    if status in (Job.Status.QUEUED, Job.Status.INTERRUPTED): return status
    if job.desired_action == 'cancel': status = Job.Status.CANCELLED
    if status == Job.Status.SUCCEEDED:
        try:
            _current_inputs(run, profile)
            checkpoint = run.checkpoints.get(step=run.total_steps, is_valid=True)
            checkpoint_bundle(run, checkpoint)
            evaluation = run.hardware_config.get('independent_evaluation', {})
            if (run.current_step != run.total_steps or evaluation.get('status') not in ('completed', 'unavailable')
                    or type(evaluation.get('passed')) is not bool or evaluation.get('checkpoint_digest') != checkpoint.state_digest):
                raise ValueError('Vision training has no complete independently evaluated candidate.')
        except (ValueError, TypeError, KeyError, run.checkpoints.model.DoesNotExist):
            status = Job.Status.FAILED
    _finalize_worker_job(job, status, runtime_id=profile.RUNTIME_ID, contract_digest=profile.CONTRACT_DIGEST,
        model_name_prefix='smolvlm-lora', checkpoint_bundle=checkpoint_bundle, is_worker_run=is_worker_run,
        candidate_metadata={'model_role': 'vision_language', 'trained': True,
            'independent_evaluation_passed': run.hardware_config.get('independent_evaluation', {}).get('passed', False),
            'production_qualified': False})
    return status


def _independent_evaluation(run, context, inputs):
    import os
    import subprocess
    import time
    from modelanvil.device_admission import device_lease
    from modelanvil.runners.training.runtime import _locked_live_run
    checkpoint = run.checkpoints.get(step=run.total_steps, is_valid=True)
    bundle = checkpoint_bundle(run, checkpoint)
    cases = inputs['protected_test_samples']
    manifest = {'source': SOURCE, 'base_files': {n:r['sha256'] for n,r in inputs['bundle']['files'].items()},
        'candidate_files': {n:r['sha256'] for n,r in bundle['files'].items()},
        'training_groups': sorted({s['source_group_id'] for s in inputs['samples']}),
        'training_image_hashes': sorted({s['image']['sha256'] for s in inputs['samples']}), 'cases': []}
    try:
        with device_lease('cpu', pass_descriptor=True) as descriptor, tempfile.TemporaryDirectory(prefix='modelanvil-vlm-score-') as temp:
            root = Path(temp)
            for index, sample in enumerate(cases):
                filename = f'case-{index}.' + ('png' if sample['image']['media_type']=='image/png' else 'jpg')
                with (root/filename).open('wb') as output: copy_verified(sample['image']['artifact'],run.tenant_id,run.project_id,output)
                manifest['cases'].append({'sample_id':sample['sample_id'],'source_group_id':sample['source_group_id'],
                    'image_filename':filename,'image_sha256':sample['image']['sha256'],'media_type':sample['image']['media_type'],
                    'question':sample['question'],'answer':sample['answer']})
            raw = json.dumps(manifest,sort_keys=True,allow_nan=False).encode();(root/'manifest.json').write_bytes(raw)
            with staged_files(inputs['bundle']['files'],run.tenant_id,run.project_id) as base, staged_files(bundle['files'],run.tenant_id,run.project_id) as candidate:
                script=Path(__file__).resolve().parents[3]/'scripts/score_vlm_candidate.py'
                command=[sys.executable,'-I',str(script),'--base',str(base),'--candidate',str(candidate),'--manifest',str(root/'manifest.json')]
                env={'PATH':os.environ.get('PATH',''),'HOME':str(root),'HF_HOME':str(root/'hub'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                    'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'}
                with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
                    child=subprocess.Popen(command,stdout=stdout,stderr=stderr,env=env,pass_fds=(descriptor,))
                    deadline=time.monotonic()+130
                    try:
                        while child.poll() is None:
                            if not context.heartbeat(progress=1.):raise ValueError('Vision evaluation lost its claim.')
                            with transaction.atomic():
                                locked=_locked_live_run(context,run.run_id);_authorized_budget(locked)
                                for ref in [*bundle['files'].values(),*[s['image']['artifact'] for s in cases]]:
                                    verified_artifact(ref,run.tenant_id,run.project_id)
                            if time.monotonic()>deadline:raise ValueError('Independent vision scoring timed out.')
                            time.sleep(.25)
                        if child.returncode:raise ValueError('Independent vision scoring did not complete.')
                        stdout.seek(0);output=stdout.read(256*1024+1)
                        if len(output)>256*1024:raise ValueError('Independent vision report exceeds its limit.')
                        report=json.loads(output)
                    finally:
                        if child.poll() is None:child.kill()
                        child.wait()
            if (report.get('schema_version')!='modelanvil.independent-vlm-evaluation.v1'
                    or report.get('manifest_sha256')!=hashlib.sha256(raw).hexdigest()
                    or report.get('file_sha256')!={'base':manifest['base_files'],'candidate':manifest['candidate_files']}
                    or report.get('image_sha256')!={s['sample_id']:s['image']['sha256'] for s in cases}
                    or report.get('consumer_imported_modelanvil_or_django') is not False
                    or set(report.get('checks',{}))!={'visual_exact_match_not_regressed','visual_holdout_loss_within_five_percent'}
                    or any(type(v) is not bool for v in report['checks'].values()) or type(report.get('passed')) is not bool
                    or report['passed']!=all(report['checks'].values())):
                raise ValueError('Independent visual report does not bind the exact candidate/processor/images.')
            return {'status':'completed','passed':report['passed'],'report':report,
                'checkpoint_digest':checkpoint.state_digest,'production_qualified':False}
    except (ValueError,OSError):
        return {'status':'unavailable','passed':False,'checkpoint_digest':checkpoint.state_digest,
            'reason':'Independent CPU visual scoring unavailable; qualification blocked.','production_qualified':False}


def verify_external_loadable(bundle):
    from modelanvil.device_admission import device_lease
    provenance = bundle['provenance.json']
    with device_lease('cpu'), staged_files(bundle['files'], provenance['tenant_id'], provenance['project_id']) as directory:
        processor = math.processor(directory)
        model = math.load_model(directory)
        count = sum(p.numel() for p in model.parameters())
        del model, processor
    return {'is_loadable': True, 'format': 'idefics3_peft_lora_safetensors', 'model_instantiated': True,
        'parameters': count, 'weights_sha256': bundle['weights_manifest.json']['weights_sha256'],
        'verification_scope': 'local_cpu_exact_vision_processor_and_adapter_reload',
        'independent_runtime_verified': False, 'production_qualified': False}
