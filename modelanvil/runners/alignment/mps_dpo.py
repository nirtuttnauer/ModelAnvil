"""Bounded, durable MPS DPO using the pinned SmolLM2 base and FP32 q/v adapters."""
import hashlib
import importlib.metadata
import gc
import io
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import ExitStack

from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import LocalArtifactStorage, artifact_storage_backend, upload_staged_artifact
from modelanvil.device_admission import device_available, device_key, device_lease, host_key
from modelanvil.jobs.models import Job, JobAttempt, Worker
from modelanvil.runners.inference import runtime_input_identity, snapshot, staged_snapshot, verified_artifact
from modelanvil.runners.models import AlignmentCheckpoint, AlignmentRun, Model, ModelVersion
from modelanvil.runners.training import hf_runtime as hf
from modelanvil.runners.training.runtime import digest

from .torch_dpo import encode_pair

RUNTIME_ID = 'modelanvil.smollm2-mps-dpo.v1'
LIMITS = {'steps': 20, 'rows': 32, 'sequence_tokens': 128, 'memory_bytes': 8 * 1024**3,
          'gpu_memory_bytes': 4 * 1024**3}
CONTRACT = {'runtime': RUNTIME_ID, 'algorithm': 'dpo', 'source': hf.SOURCE, 'files': hf.FILE_HASHES,
    'packages': {**hf.PACKAGES, 'peft': '0.21.2', 'accelerate': '1.15.0'}, 'device': 'mps:0', 'precision': 'fp32',
    'adapter': hf.LORA, 'optimizer': 'adamw', 'seed': 42, 'limits': LIMITS,
    'prompt_format': 'plain_prefix_stable_response_sum_including_eos', 'production_qualified': False}
CONTRACT_DIGEST = digest(CONTRACT)


def _source_digest():
    root = Path(__file__).resolve().parents[3]
    files = ['modelanvil/runners/alignment/mps_dpo.py', 'modelanvil/runners/alignment/torch_dpo.py',
             'modelanvil/runners/alignment/preference_groups.py',
             'modelanvil/runners/alignment/execution.py', 'modelanvil/runners/inference.py',
             'modelanvil/runners/training/hf_runtime.py', 'modelanvil/runners/training/admission.py',
             'modelanvil/jobs/models.py', 'modelanvil/device_admission.py',
             'scripts/score_dpo_candidate.py', 'scripts/hf_candidate_infer.py']
    return hashlib.sha256(b''.join((root / name).read_bytes() for name in files)).hexdigest()


_BUILD_DIGEST = _source_digest()


def build_digest():
    if _source_digest() != _BUILD_DIGEST:
        raise ValueError('DPO implementation changed on disk; restart the API and worker before launching or recovering.')
    return _BUILD_DIGEST


def environment():
    hf.require_packages(); hf.require_adapter_package()
    for name, expected in CONTRACT['packages'].items():
        try: actual = importlib.metadata.version(name).split('+')[0]
        except importlib.metadata.PackageNotFoundError: actual = None
        if actual != expected:
            raise ValueError(f'Install {name}=={expected} for the pinned MPS DPO profile.')
    observed = hf.observed_device('mps:0')
    if hf.mps_memory()['process_headroom_bytes'] < LIMITS['gpu_memory_bytes']:
        raise ValueError('MPS DPO needs at least 4 GiB of observed process headroom; CPU fallback is disabled.')
    return {**observed, 'python': platform.python_version(), 'platform': platform.platform(),
            'alignment_packages': CONTRACT['packages']}


def capable_worker(worker):
    caps = worker.capabilities
    return (isinstance(caps, dict) and caps.get('alignment_runtime') == CONTRACT_DIGEST
            and caps.get('alignment_worker_id') == str(worker.pk) and caps.get('host_key') == host_key()
            and caps.get('gpu_device') == 'mps:0' and caps.get('gpu_packages') == CONTRACT['packages']
            and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes']
            and worker.slots in (0, 1) and worker.status in ('available', 'busy') and not worker.drain_requested)


def hyperparameters(value):
    if not isinstance(value, dict) or set(value) - {'beta', 'learning_rate', 'max_gradient_norm', 'budget_policy_id'}:
        raise ValueError('MPS DPO accepts beta, learning_rate, max_gradient_norm and a step budget only.')
    result = {'beta': .1, 'learning_rate': .00002, 'max_gradient_norm': 1., **value}
    for name, low, high in (('beta', .001, 1.), ('learning_rate', .000001, .0002), ('max_gradient_norm', .1, 1.)):
        number = result[name]
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'MPS DPO {name} must be finite and between {low} and {high}.')
    if not result.get('budget_policy_id'):
        raise ValueError('Select an explicit enabled training_steps budget for MPS DPO.')
    return result


def _base(version, tenant, project):
    if version is None or version.architecture_ref != hf.RUNTIME_ID or version.tokenizer.chat_template:
        raise ValueError('Select the operator-registered plain SmolLM2-135M GPU base and its exact tokenizer.')
    plan = snapshot(version, tenant, project)
    files = plan.get('files', {})
    if (plan.get('trained') or plan.get('format') != 'safetensors' or plan.get('source') != hf.SOURCE
            or set(files) != set(hf.FILE_HASHES)
            or any(files[name].get('sha256') != sha for name, sha in hf.FILE_HASHES.items())):
        raise ValueError('MPS DPO accepts only the exact pinned unmodified SmolLM2-135M base files.')
    return files


def _preferences(artifact, tenant, project):
    from .execution import read_preferences
    from modelanvil.runners.training.runtime import read_artifact
    if artifact is None or not 0 < artifact.byte_size <= 1024**2:
        raise ValueError('Pin bounded committed preference and regression artifacts.')
    pairs, sha = read_preferences(artifact, tenant=tenant, project=project)
    value = json.loads(read_artifact(artifact, tenant, project))
    review = value.get('review', {})
    owner_reviewed = (isinstance(review, dict) and review.get('method') == 'owner_attestation'
        and review.get('labels_reviewed') is True and bool(review.get('actor_id')))
    if owner_reviewed:
        from modelanvil.core.models import AuditEvent
        try:
            actor = uuid.UUID(str(review['actor_id']))
        except (ValueError, TypeError):
            owner_reviewed = False
        else:
            owner_reviewed = AuditEvent.all_objects.filter(tenant_id=tenant,
                action='preferences.register', resource_type='artifact', resource_id=artifact.artifact_id,
                actor_id=actor, actor_kind=review.get('actor_kind'), result='ok', input_snapshot__sha256=sha).exists()
    formal_reviewed = False
    if artifact.metadata.get('snapshot_id'):
        from modelanvil.annotation.models import CumulativeSnapshot
        formal_reviewed = CumulativeSnapshot.all_objects.filter(tenant_id=tenant,
            snapshot_id=artifact.metadata['snapshot_id'],
            qualification__formal_preference__artifact__artifact_id=str(artifact.artifact_id),
            qualification__formal_preference__artifact__sha256=sha,
            qualification__formal_preference__artifact__byte_size=artifact.byte_size).exists()
    if not owner_reviewed and not formal_reviewed:
        raise ValueError('MPS DPO requires a reviewed preference export or an explicit owner review attestation frozen in the registered bytes.')
    if len({pair['prompt'].strip() for pair in pairs}) != len(pairs):
        raise ValueError('DPO preference sets require unique prompts after whitespace trimming.')
    groups = set()
    for pair in pairs:
        group = pair.get('source_group_id')
        if not isinstance(group, str) or not 1 <= len(group.strip()) <= 128:
            raise ValueError('Every MPS DPO preference/regression row requires a source group ID.')
        groups.add(group.strip())
    return pairs, sha, groups


def validate_inputs(run, *, require_capacity=True):
    from .execution import _budget
    if run.algorithm != 'dpo' or not run.project_id or not run.worker_pool_id:
        raise ValueError('MPS execution requires a project, DPO and a registered Apple GPU alignment pool.')
    if type(run.total_steps) is not int or not 1 <= run.total_steps <= LIMITS['steps']:
        raise ValueError('MPS DPO supports 1–20 adapter updates.')
    if (run.worker_pool.tenant_id != run.tenant_id or run.worker_pool.status != 'active'
            or not isinstance(artifact_storage_backend(), LocalArtifactStorage)):
        raise ValueError('Use an active same-tenant pool and local filesystem artifacts.')
    hp = hyperparameters(run.hyperparameters)
    observed = environment()
    workers = Worker.all_objects.filter(tenant_id=run.tenant_id, pool=run.worker_pool)
    pinned_worker = (run.execution_pins or {}).get('worker_id')
    if pinned_worker is not None:
        workers = workers.filter(pk=pinned_worker)
    worker = next((w for w in workers.order_by('pk') if capable_worker(w) and (w.slots > 0 or not require_capacity)), None)
    if worker is None:
        raise ValueError('No matching available trusted MPS DPO worker is registered in this pool.')
    policy_files = _base(run.policy_model_version, run.tenant_id, run.project_id)
    reference_files = _base(run.reference_model_version, run.tenant_id, run.project_id)
    if run.reference_model_version.tokenizer_id != run.policy_model_version.tokenizer_id:
        raise ValueError('DPO policy and frozen reference must use the same pinned tokenizer revision.')
    datasets = [_preferences(artifact, run.tenant_id, run.project_id) for artifact in
                (run.train_dataset_artifact, run.held_out_dataset_artifact, run.regression_dataset_artifact)]
    for index, (pairs, sha, groups) in enumerate(datasets):
        prompts = {pair['prompt'].strip() for pair in pairs}
        for other, _, other_groups in datasets[:index]:
            if groups & other_groups or prompts & {pair['prompt'].strip() for pair in other}:
                raise ValueError('Training, held-out preferences and regression prompts/source groups must be disjoint.')
    with staged_snapshot({name: ref for name, ref in policy_files.items() if not name.endswith('.safetensors')},
                         run.tenant_id, run.project_id) as directory:
        tokenizer = hf._tokenizer(directory)
        if run.policy_model_version.tokenizer.vocabulary_size != len(tokenizer):
            raise ValueError('DPO tokenizer registry vocabulary differs from the pinned tokenizer bytes.')
        encoded = [[{**encode_pair(tokenizer, pair), 'source_group_id': pair['source_group_id']}
                    for pair in pairs] for pairs, _, _ in datasets]
    budget = _budget(run)
    if budget is None or budget.currency or budget.unit != 'training_steps':
        raise ValueError('MPS DPO requires an enabled training_steps budget without a monetary currency.')
    pins = {'runtime': RUNTIME_ID, 'contract_digest': CONTRACT_DIGEST, 'build_digest': build_digest(),
        'algorithm': 'dpo', 'steps': run.total_steps, 'seed': 42, 'initialization_seed': 42,
        'sample_order': 'seeded_epoch_shuffle_v1',
        'hyperparameters': hp, 'accelerator': observed, 'worker_id': worker.pk, 'pool_id': run.worker_pool_id,
        'policy_model_version_id': str(run.policy_model_version.model_version_id),
        'reference_model_version_id': str(run.reference_model_version.model_version_id),
        'policy_input_identity': runtime_input_identity(run.policy_model_version),
        'reference_input_identity': runtime_input_identity(run.reference_model_version),
        'base_files': policy_files, 'reference_files': reference_files,
        'train_artifact': hf.file_ref(run.train_dataset_artifact),
        'held_out_artifact': hf.file_ref(run.held_out_dataset_artifact),
        'regression_artifact': hf.file_ref(run.regression_dataset_artifact),
        'dataset_manifest_digest': datasets[0][1], 'held_out_validation_digest': datasets[1][1],
        'regression_digest': datasets[2][1], 'encoded_digest': digest(encoded),
        'template': 'plain_prefix_stable_response_sum_including_eos', 'production_qualified': False}
    return {'pins': pins, 'encoded': encoded, 'datasets': [pairs for pairs, _, _ in datasets],
            'hyperparameters': hp, 'worker': worker, 'budget': budget}


def _authorized_budget(run):
    from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
    reservation = BudgetReservation.all_objects.filter(tenant_id=run.tenant_id, job_id=run.job.job_id,
        reservation_id=run.resource_reservation_id, state='reserved').first()
    policy = BudgetPolicy.all_objects.select_for_update().filter(pk=reservation.policy_id,
        tenant_id=run.tenant_id).first() if reservation else None
    period, committed = BudgetReservation.current_commitment(policy) if policy else (None, None)
    if (not policy or not policy.enabled or policy.unit != 'training_steps' or policy.currency
            or reservation.period_start != period or reservation.estimated_amount != run.total_steps
            or committed > policy.limit_amount):
        raise ValueError('MPS DPO step budget is no longer authorized.')


def _current_inputs(run):
    from modelanvil.identity.models import Tenant, check_resource_access
    pins = run.execution_pins
    if (not Tenant.objects.filter(pk=run.tenant_id, status='active').exists()
            or pins.get('runtime') != RUNTIME_ID or pins.get('contract_digest') != CONTRACT_DIGEST
            or pins.get('build_digest') != build_digest() or run.algorithm != 'dpo'
            or run.total_steps != pins.get('steps') or run.worker_pool_id != pins.get('pool_id')
            or hyperparameters(run.hyperparameters) != pins.get('hyperparameters')):
        raise ValueError('MPS DPO tenant, runtime or implementation changed.')
    for role in ('policy', 'reference'):
        version = ModelVersion.all_objects.select_related('tokenizer').filter(
            pk=getattr(run, role + '_model_version_id'), tenant_id=run.tenant_id).first()
        if (version is None or version.state in ('archived', 'rejected')
                or not check_resource_access(version, run.project_id, run.tenant_id)
                or not check_resource_access(version.tokenizer, run.project_id, run.tenant_id)
                or runtime_input_identity(version) != pins[role + '_input_identity']):
            raise ValueError('DPO policy/reference inputs or project access changed.')
    for field, key in (('train_dataset_artifact', 'train_artifact'), ('held_out_dataset_artifact', 'held_out_artifact'),
                       ('regression_dataset_artifact', 'regression_artifact')):
        artifact = getattr(run, field)
        if artifact is None or str(artifact.artifact_id) != pins[key]['artifact_id']:
            raise ValueError('Pinned DPO preference or regression artifact changed.')
    for ref in [*pins['base_files'].values(), *pins['reference_files'].values(), pins['train_artifact'],
                pins['held_out_artifact'], pins['regression_artifact']]:
        verified_artifact(ref, run.tenant_id, run.project_id)


class ExecutionStopped(ValueError):
    pass


def _live(run, context):
    job = Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id)
    attempt = JobAttempt.all_objects.filter(pk=context.attempt.pk, job=job, worker_id=context.attempt.worker_id,
        fencing_token=context.fencing_token, status='running', lease_expires_at__gt=timezone.now()).first()
    locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
    worker = Worker.all_objects.filter(pk=context.attempt.worker_id, tenant_id=run.tenant_id).first()
    if (attempt is None or job.status != 'running' or job.desired_action != 'run'
            or job.payload != {'type': 'qualified_dpo', 'run_id': str(locked.run_id)}
            or job.fencing_token != context.fencing_token or locked.status != 'running'
            or job.project_id != locked.project_id or job.pool_id != locked.worker_pool_id
            or locked.job_id != job.pk or locked.execution_pins != run.execution_pins
            or context.attempt.worker_id != locked.execution_pins['worker_id']
            or worker is None or worker.pool_id != job.pool_id or not capable_worker(worker)):
        raise ExecutionStopped('MPS DPO attempt lost its claim; further publication refused.')
    _authorized_budget(locked); _current_inputs(locked)
    return locked


def gpu_claim_plan(job, worker):
    try: run_id = uuid.UUID(str(job.payload.get('run_id')))
    except (TypeError, ValueError): raise ValueError('DPO job requires its pinned run UUID.') from None
    run = AlignmentRun.all_objects.filter(job=job, tenant_id=worker.tenant_id,
        run_id=run_id).first()
    if (run is None or run.project_id != job.project_id or run.worker_pool_id != worker.pool_id
            or run.execution_pins.get('worker_id') != worker.pk or not capable_worker(worker)):
        raise ValueError('MPS DPO job, project, pool or worker changed.')
    _current_inputs(run); _authorized_budget(run)
    if environment() != run.execution_pins['accelerator'] or not device_available('mps:0'):
        raise ValueError('The pinned MPS GPU is unavailable or busy.')
    return {'host_key': run.execution_pins['accelerator']['host_key'], 'device_key': device_key('mps:0')}


def launch(run, *, resume=False):
    from modelanvil.budgets.models import BudgetReservation
    if resume and run.job_id:
        from modelanvil.jobs.models import reconcile_expired_leases
        reconcile_expired_leases(job_ids=[run.job.job_id])
    with transaction.atomic():
        job = Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id) if run.job_id else None
        locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        if job is None and locked.job_id:
            if resume:
                raise ValueError('The job changed during launch; refresh before requesting recovery.')
            return locked
        if job is not None:
            if not resume:
                return locked
            if (job.status not in ('queued', 'interrupted') or job.desired_action != 'run'
                    or locked.status not in ('pending', 'interrupted')):
                raise ValueError('Only an interrupted reserved MPS DPO job can be resumed; an active attempt cannot be taken over.')
            inputs = validate_inputs(locked, require_capacity=False)
            if inputs['pins'] != locked.execution_pins:
                raise ValueError('DPO pinned inputs or optimizer changed; recovery refused.')
            _authorized_budget(locked)
            if job.status == 'interrupted':
                job.status = 'queued'; job.save(update_fields=['status', 'updated_at'])
            return locked
        if resume or locked.status != 'pending' or locked.current_step:
            raise ValueError('Select a pending unexecuted MPS DPO plan.')
        inputs = validate_inputs(locked)
        if not device_available('mps:0'):
            raise ValueError('The Apple GPU is busy; no job or budget was allocated.')
        worker = inputs['worker']
        job = Job.all_objects.create(tenant_id=locked.tenant_id, project_id=locked.project_id,
            pool=locked.worker_pool, name=f'MPS DPO {locked.run_id}', max_attempts=3,
            payload={'type': 'qualified_dpo', 'run_id': str(locked.run_id)},
            requirements={'alignment_runtime': CONTRACT_DIGEST, 'alignment_worker_id': str(worker.pk),
                          'gpu_device': 'mps:0', 'host_key': host_key(), 'slots': 1})
        reservation = BudgetReservation.reserve(tenant_id=locked.tenant_id, policy=inputs['budget'],
            job_id=job.job_id, estimated_amount=locked.total_steps)
        locked.job, locked.execution_pins = job, inputs['pins']
        locked.resource_reservation_id = reservation.reservation_id
        locked.dataset_manifest_digest = inputs['pins']['dataset_manifest_digest']
        locked.held_out_validation_digest = inputs['pins']['held_out_validation_digest']
        locked.save()
        return locked


def checkpoint_bundle(run, checkpoint):
    state = checkpoint.policy_state
    if (not checkpoint.is_valid or digest(state) != checkpoint.state_digest
            or state.get('run_id') != str(run.run_id) or state.get('step') != checkpoint.step
            or state.get('pins') != run.execution_pins or state.get('metrics') != checkpoint.metrics
            or set(state.get('files', {})) != set(hf.FILE_HASHES) | {'adapter_model.safetensors', 'adapter_config.json'}):
        raise ValueError('DPO checkpoint cursor, inputs, files or digest changed.')
    for ref in [*state['files'].values(), state['adam']]:
        verified_artifact(ref, run.tenant_id, run.project_id)
    return {'source': hf.SOURCE, 'files': state['files'], 'adapter': hf.LORA,
        'provenance': {'run_id': str(run.run_id), 'step': checkpoint.step,
                       'checkpoint_digest': checkpoint.state_digest, 'pins': run.execution_pins},
        'production_qualified': False}


def _updates(run, inputs, context, directory, policy, reference, optimizer):
    import torch
    from safetensors.torch import save_file
    from modelanvil.runners.models import AlignmentCheckpoint
    from .torch_dpo import preference_loss, response_log_probability
    hp = inputs['hyperparameters']; rows = inputs['encoded'][0]
    trainable = [p for p in policy.parameters() if p.requires_grad]
    if (sum(p.numel() for p in trainable) != 460800 or
            any(p.requires_grad and '.lora_' not in name for name, p in policy.named_parameters()) or
            any(p.requires_grad for p in reference.parameters())):
        raise ValueError('DPO must train only the declared rank-eight q/v policy adapters; reference stays frozen.')
    device = torch.device('mps:0')
    for step in range(run.current_step + 1, run.total_steps + 1):
        if not context.heartbeat(progress=(step - 1) / run.total_steps): return
        with transaction.atomic(): _live(run, context)
        row = rows[hf.training_sample_index(step, len(rows), inputs['pins'])]
        if any(p.device != device for model in (policy, reference) for p in model.parameters()):
            raise ValueError('DPO policy/reference parameters left the selected MPS device.')
        logp = lambda model, field: response_log_probability(model, row[field], row['prompt_tokens'], device)
        started, cpu = time.perf_counter(), time.process_time()
        before = [parameter.detach().clone() for parameter in trainable]
        optimizer.zero_grad(set_to_none=True)
        with torch.no_grad(): ref_chosen, ref_rejected = logp(reference, 'chosen'), logp(reference, 'rejected')
        chosen, rejected = logp(policy, 'chosen'), logp(policy, 'rejected')
        loss = preference_loss(chosen, rejected, ref_chosen, ref_rejected, hp['beta'])
        if not torch.isfinite(loss).item(): raise ValueError('DPO objective is non-finite.')
        loss.backward()
        if any(p.grad is not None and (p.grad.device != device or not torch.isfinite(p.grad).all().item()) for p in trainable):
            raise ValueError('DPO gradients became non-finite or left MPS.')
        norm = torch.nn.utils.clip_grad_norm_(trainable, hp['max_gradient_norm'], error_if_nonfinite=True)
        if norm.item() <= 0: raise ValueError('DPO produced no nonzero adapter gradient.')
        optimizer.step()
        changed = sum(torch.count_nonzero(parameter.detach() != previous).item()
                      for parameter, previous in zip(trainable, before))
        if not changed: raise ValueError('DPO optimizer changed no actual adapter weights.')
        if any(not torch.isfinite(p).all().item() for p in trainable) or any(p.grad is not None for p in reference.parameters()):
            raise ValueError('DPO adapter weights are non-finite or the frozen reference received gradients.')
        with torch.no_grad():
            post_chosen, post_rejected = logp(policy, 'chosen'), logp(policy, 'rejected')
            post = preference_loss(post_chosen, post_rejected, ref_chosen, ref_rejected, hp['beta'])
        torch.mps.synchronize(); elapsed = time.perf_counter() - started
        tokens = len(row['chosen']) + len(row['rejected']) - 2 * row['prompt_tokens']
        metrics = {'step': step, 'loss': loss.item(), 'post_update_loss': post.item(), 'beta': hp['beta'],
            'source_group_id': row['source_group_id'], 'prompt_tokens': row['prompt_tokens'], 'response_tokens': tokens,
            'policy_chosen_logp': post_chosen.item(), 'policy_rejected_logp': post_rejected.item(),
            'reference_chosen_logp': ref_chosen.item(), 'reference_rejected_logp': ref_rejected.item(),
            'gradient_norm': norm.item(), 'trainable_parameters': 460800, 'changed_parameter_values': changed,
            'total_parameters': sum(parameter.numel() for parameter in policy.parameters()),
            'gpu_backend': 'mps', 'gpu_device': 'mps:0',
            'device_residency_checked': True, 'reference_frozen': True, 'engine_wall_seconds': elapsed,
            'cpu_seconds': time.process_time() - cpu, 'response_tokens_per_second': tokens / elapsed,
            'gpu_allocated_bytes': torch.mps.current_allocated_memory(), 'mps_memory': hf.mps_memory(),
            'peak_allocated_bytes': None, 'peak_reserved_bytes': None, 'production_qualified': False}
        if not all(math.isfinite(value) for value in metrics.values() if type(value) is float):
            raise ValueError('DPO metrics are non-finite.')
        policy.save_pretrained(str(directory), safe_serialization=True, save_embedding_layers=False)
        save_file(hf._optimizer_state(policy, optimizer), str(directory / 'optimizer.safetensors'))
        if not context.heartbeat(progress=(step - 1) / run.total_steps): return
        with transaction.atomic():
            locked = _live(run, context)
            if locked.current_step != step - 1:
                raise ValueError('DPO checkpoint cursor changed.')
            files = {**inputs['pins']['base_files'], **{name: hf._store_file(directory / name, run, context, step)
                for name in ('adapter_model.safetensors', 'adapter_config.json')}}
            adam = hf._store_file(directory / 'optimizer.safetensors', run, context, step)
            _live(run, context)
            state = {'run_id': str(run.run_id), 'step': step, 'pins': inputs['pins'], 'files': files,
                     'adam': adam, 'metrics': metrics, 'attempt_id': str(context.attempt.attempt_id)}
            AlignmentCheckpoint.all_objects.create(tenant_id=run.tenant_id, alignment_run=locked, step=step,
                policy_state=state, state_digest=digest(state), metrics=metrics)
            locked.current_step, locked.latest_metrics = step, metrics
            locked.metrics_history = [*locked.metrics_history, metrics]
            locked.save(update_fields=['current_step', 'latest_metrics', 'metrics_history', 'updated_at'])
            run.current_step = step


def _train(run, inputs, context):
    import torch
    latest = run.checkpoints.filter(is_valid=True).order_by('-step').first()
    if latest:
        checkpoint_bundle(run, latest)
        if latest.step != run.current_step: raise ValueError('DPO checkpoint and committed cursor disagree.')
    files = latest.policy_state['files'] if latest else inputs['pins']['base_files']
    recovery = {**files, **({'optimizer.safetensors': latest.policy_state['adam']} if latest else {})}
    policy = reference = optimizer = None
    previous_threads = torch.get_num_threads(); torch.set_num_threads(1)
    admission = ExitStack()
    try:
        admission.enter_context(device_lease('mps:0'))
        with hf.deterministic_updates(), hf.staged_files(recovery, run.tenant_id, run.project_id) as directory:
            if not context.heartbeat(): return
            policy = hf._recipe_model(directory, 'lora_adapter', seed=42, training=True, source=hf.SOURCE, adapter=hf.LORA)
            reference = hf._load_model(directory / 'base').requires_grad_(False).eval()
            policy.to('mps:0'); reference.to('mps:0')
            optimizer = torch.optim.AdamW([p for p in policy.parameters() if p.requires_grad],
                lr=inputs['hyperparameters']['learning_rate'], betas=(.9, .999), eps=1e-8, weight_decay=0., foreach=False)
            if latest: hf._restore_optimizer(policy, optimizer, directory, latest.step)
            _updates(run, inputs, context, directory, policy, reference, optimizer)
    except Exception as error:
        import traceback
        traceback.clear_frames(error.__traceback__)
        raise
    finally:
        try:
            policy = reference = optimizer = None
            gc.collect(); torch.mps.empty_cache(); torch.set_num_threads(previous_threads)
        finally:
            admission.close()


def _independent_evaluation(run, context):
    from modelanvil.runners.training.runtime import read_artifact
    checkpoint = run.checkpoints.get(step=run.total_steps, is_valid=True)
    bundle = checkpoint_bundle(run, checkpoint)
    _current_inputs(run)
    try:
        with device_lease('cpu', pass_descriptor=True) as descriptor, tempfile.TemporaryDirectory(prefix='modelanvil-dpo-score-') as temp:
            root = Path(temp)
            for name, artifact in (('preferences', run.held_out_dataset_artifact), ('regression', run.regression_dataset_artifact)):
                (root / (name + '.json')).write_bytes(read_artifact(artifact, run.tenant_id, run.project_id))
            with hf.staged_files(run.execution_pins['reference_files'], run.tenant_id, run.project_id) as base, hf.staged_files(bundle['files'], run.tenant_id, run.project_id) as candidate:
                manifest = {'beta': run.execution_pins['hyperparameters']['beta'],
                    'base_files': {name: ref['sha256'] for name, ref in run.execution_pins['reference_files'].items()},
                    'candidate_files': {name: ref['sha256'] for name, ref in bundle['files'].items()},
                    'preferences_sha256': run.execution_pins['held_out_validation_digest'],
                    'regression_sha256': run.execution_pins['regression_digest'],
                    'training_groups': sorted({row['source_group_id'] for row in validate_inputs(run, require_capacity=False)['encoded'][0]})}
                raw = json.dumps(manifest, sort_keys=True, allow_nan=False).encode(); (root / 'manifest.json').write_bytes(raw)
                script = Path(__file__).resolve().parents[3] / 'scripts/score_dpo_candidate.py'
                command = [sys.executable, '-I', str(script), '--base', str(base), '--candidate', str(candidate),
                    '--preferences', str(root / 'preferences.json'), '--regression', str(root / 'regression.json'),
                    '--manifest', str(root / 'manifest.json')]
                env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(root), 'HF_HOME': str(root / 'hub'),
                    'XDG_CACHE_HOME': str(root / 'cache'), 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                    'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1',
                    'OPENBLAS_NUM_THREADS': '1', 'TOKENIZERS_PARALLELISM': 'false'}
                with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                    child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, pass_fds=(descriptor,))
                    deadline = time.monotonic() + 125
                    try:
                        while child.poll() is None:
                            if not context.heartbeat(progress=1.): raise ExecutionStopped('DPO evaluation lost its worker claim.')
                            with transaction.atomic(): _live(run, context)
                            if time.monotonic() >= deadline: raise ValueError('Independent DPO scoring timed out.')
                            time.sleep(.25)
                        if child.returncode: raise ValueError('Independent DPO scoring did not complete.')
                        stdout.seek(0); output = stdout.read(256 * 1024 + 1)
                        if len(output) > 256 * 1024: raise ValueError('Independent DPO report exceeds its size bound.')
                        report = json.loads(output)
                    finally:
                        if child.poll() is None: child.kill()
                        child.wait()
                if (report.get('schema_version') != 'modelanvil.independent-dpo-evaluation.v1'
                        or report.get('manifest_sha256') != hashlib.sha256(raw).hexdigest()
                        or report.get('file_sha256') != {'base': manifest['base_files'], 'candidate': manifest['candidate_files']}
                        or report.get('input_sha256') != {'preferences': manifest['preferences_sha256'], 'regression': manifest['regression_sha256']}
                        or report.get('beta') != manifest['beta'] or report.get('consumer_imported_modelanvil_or_django') is not False
                        or type(report.get('passed')) is not bool or not isinstance(report.get('checks'), dict)
                        or set(report['checks']) != {'preference_accuracy_not_regressed',
                            'reference_relative_preference_loss_not_regressed', 'separate_regression_loss_within_five_percent'}
                        or any(type(value) is not bool for value in report['checks'].values())
                        or report['passed'] != all(report['checks'].values())):
                    raise ValueError('Independent DPO report does not bind the pinned inputs and weights.')
                return {'status': 'completed', 'passed': report['passed'], 'report': report, 'production_qualified': False}
    except ExecutionStopped:
        raise
    except (ValueError, OSError):
        return {'status': 'unavailable', 'passed': False,
                'reason': 'Independent CPU scoring was unavailable or failed; model qualification is blocked.', 'production_qualified': False}


def worker_executor(descriptor, context):
    try: run_id = uuid.UUID(str(descriptor.get('payload', {}).get('run_id')))
    except (TypeError, ValueError): raise ValueError('DPO executor requires its run UUID.') from None
    run = AlignmentRun.all_objects.filter(run_id=run_id, tenant_id=context.attempt.tenant_id,
        job_id=context.attempt.job_id).first()
    if (run is None or str(run.job.job_id) != descriptor.get('job_id')
            or descriptor.get('payload') != {'type': 'qualified_dpo', 'run_id': str(run.run_id)}):
        raise ValueError('DPO job does not match its claimed alignment run.')
    inputs = validate_inputs(run, require_capacity=False)
    if inputs['pins'] != run.execution_pins or context.attempt.worker_id != inputs['pins']['worker_id']:
        raise ValueError('DPO inputs, runtime or worker changed after launch.')
    if not context.heartbeat(): return None
    with transaction.atomic():
        Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id)
        run = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        if run.status not in ('pending', 'interrupted') or run.job.desired_action != 'run':
            raise ValueError('DPO run is not eligible for this worker attempt.')
        run.status, run.started_at = 'running', run.started_at or timezone.now()
        run.save(update_fields=['status', 'started_at', 'updated_at'])
        _live(run, context)
    if run.current_step < run.total_steps: _train(run, inputs, context)
    if not context.heartbeat(progress=run.current_step / run.total_steps): return None
    if run.current_step != run.total_steps: raise ValueError('DPO worker did not complete its committed updates.')
    evaluation = _independent_evaluation(run, context)
    with transaction.atomic():
        locked = _live(run, context)
        locked.latest_metrics = {**locked.latest_metrics, 'independent_evaluation': evaluation, 'production_qualified': False}
        locked.save(update_fields=['latest_metrics', 'updated_at'])
    return None


def finalize_job(job, status):
    """Called inside the job's winning commit/expiry transaction; never by a worker response body."""
    from .execution import _settle
    run = AlignmentRun.all_objects.select_for_update().filter(job=job, tenant_id=job.tenant_id).first()
    if run is None: return Job.Status.FAILED
    if run.status in ('completed', 'cancelled', 'failed'): return status
    if job.desired_action == 'cancel': status = Job.Status.CANCELLED
    if status in (Job.Status.QUEUED, Job.Status.INTERRUPTED) and job.desired_action == 'run':
        run.status, run.stop_reason = 'interrupted', 'worker_attempt_interrupted'
        run.save(update_fields=['status', 'stop_reason', 'updated_at'])
        return status
    if status == Job.Status.SUCCEEDED:
        try:
            if (job.payload != {'type': 'qualified_dpo', 'run_id': str(run.run_id)}
                    or job.project_id != run.project_id or job.pool_id != run.worker_pool_id
                    or run.current_step != run.total_steps or run.output_model_version_id):
                raise ValueError('DPO final job, cursor or candidate state is invalid.')
            _current_inputs(run); _authorized_budget(run)
            checkpoint = run.checkpoints.get(step=run.total_steps, is_valid=True)
            bundle = checkpoint_bundle(run, checkpoint)
            evaluation = run.latest_metrics.get('independent_evaluation')
            if (not isinstance(evaluation, dict) or evaluation.get('status') not in ('completed', 'unavailable')
                    or type(evaluation.get('passed')) is not bool
                    or evaluation.get('status') == 'unavailable' and evaluation['passed']):
                raise ValueError('DPO requires explicit independent evaluation evidence or a blocked unavailable gate.')
            with hf.staged_files({**bundle['files'], 'optimizer.safetensors': checkpoint.policy_state['adam']},
                                 run.tenant_id, run.project_id):
                pass
            payload = json.dumps(bundle, sort_keys=True, allow_nan=False).encode()
            artifact = Artifact.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
                storage_location_id='local', object_key=f'alignment/{run.run_id}/candidate-{uuid.uuid4()}.json',
                sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
            upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
            model = Model.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
                name=f'dpo-{run.run_id}', intended_tasks=['text_generation'])
            run.output_model_version = ModelVersion.all_objects.create(tenant_id=run.tenant_id,
                project_id=run.project_id, model=model, revision_no=1,
                tokenizer=run.policy_model_version.tokenizer, architecture_ref=RUNTIME_ID,
                artifact_manifest_id=str(artifact.artifact_id), producing_job_id=job.job_id,
                parameters_count=run.latest_metrics.get('total_parameters'), state=ModelVersion.State.DRAFT,
                license_evidence=run.policy_model_version.license_evidence,
                metadata={'alignment_recipe': 'dpo', 'source_run_id': str(run.run_id),
                    'checkpoint_digest': checkpoint.state_digest, 'trained': True, 'model_role': 'policy',
                    'weights_sha256': bundle['files']['adapter_model.safetensors']['sha256'],
                    'independent_evaluation_passed': evaluation['passed'], 'production_qualified': False})
            run.status = 'completed'
            run.stop_reason = ('completed' if evaluation['passed'] else 'completed_evaluation_' +
                ('unavailable' if evaluation['status'] == 'unavailable' else 'failed'))
        except (ValueError, TypeError, KeyError, OSError, Artifact.DoesNotExist, AlignmentCheckpoint.DoesNotExist):
            status = Job.Status.FAILED
            run.status, run.stop_reason = 'failed', 'candidate_publication_refused'
    else:
        run.status = 'cancelled' if status == Job.Status.CANCELLED else 'failed'
        run.stop_reason = 'cancelled' if status == Job.Status.CANCELLED else 'worker_execution_failed'
    run.completed_at = timezone.now()
    run.save(update_fields=['status', 'stop_reason', 'completed_at', 'output_model_version', 'updated_at'])
    _settle(run)
    return status


def cancel(run):
    with transaction.atomic():
        job = Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id) if run.job_id else None
        locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        if job is None and locked.job_id:
            raise ValueError('The job changed during cancellation; refresh and cancel the queued job.')
        if locked.status in ('completed', 'cancelled', 'failed'): return locked
        if job is None:
            locked.status, locked.stop_reason, locked.completed_at = 'cancelled', 'cancelled', timezone.now()
            locked.save(update_fields=['status', 'stop_reason', 'completed_at', 'updated_at'])
        else:
            job.desired_action = Job.DesiredAction.CANCEL
            job.save(update_fields=['desired_action', 'updated_at'])
            if job.status != Job.Status.RUNNING:
                job.status = finalize_job(job, Job.Status.CANCELLED)
                job.save(update_fields=['status', 'updated_at'])
        return AlignmentRun.all_objects.get(pk=locked.pk, tenant_id=run.tenant_id)


def candidate_bundle(version, tenant, project):
    from modelanvil.identity.models import check_resource_access
    run = AlignmentRun.all_objects.filter(tenant_id=tenant, output_model_version=version,
        status='completed', job__status='succeeded', execution_pins__runtime=RUNTIME_ID).first()
    if (run is None or not check_resource_access(run, project, tenant)
            or version.tokenizer_id != run.policy_model_version.tokenizer_id):
        raise ValueError('DPO candidate requires its successful producing job, tokenizer and checkpoint lineage.')
    checkpoint = run.checkpoints.filter(step=run.total_steps, is_valid=True).first()
    if checkpoint is None or version.metadata.get('checkpoint_digest') != checkpoint.state_digest:
        raise ValueError('DPO candidate checkpoint lineage changed.')
    return checkpoint_bundle(run, checkpoint)
