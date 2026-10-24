"""Fenced CPU SmolLM2 reward training and RLOO, with separately charged durable stages."""
import copy
import gc
import hashlib
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
from contextlib import ExitStack, contextmanager

from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import LocalArtifactStorage, artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.device_admission import device_available, device_key, device_lease, host_key
from modelanvil.identity.models import Tenant, check_resource_access
from modelanvil.jobs.models import Job, JobAttempt, Worker
from modelanvil.runners.inference import runtime_input_identity, snapshot, copy_verified, verified_artifact
from modelanvil.runners.models import AlignmentRun, AlignmentCheckpoint, AlignmentStageAttempt, Model, ModelVersion
from modelanvil.runners.training import hf_runtime as hf, cpu_hf_runtime as cpu
from modelanvil.runners.training.runtime import digest

from .reviewed_inputs import read_reviewed_preferences
from .torch_dpo import encode_pair
from . import torch_rlhf as rl

RUNTIME_ID = 'modelanvil.smollm2-cpu-rlhf.v1'
UNITS = ('training_steps', 'generated_tokens', 'alignment_scores')
MAX_ATTEMPTS = 3
LIMITS = {'steps': 20, 'rows': 32, 'sequence_tokens': 128, 'memory_bytes': 16 * 1024**3,
    'max_new_tokens': 8, 'rollout_group_size': 4}
CONTRACT = {'runtime': RUNTIME_ID, 'algorithms': ['reward_model', 'rloo'], 'source': hf.SOURCE,
    'files': hf.FILE_HASHES, 'packages': {**hf.PACKAGES, 'peft': '0.21.2', 'accelerate': '1.15.0'},
    'device': 'cpu', 'precision': 'fp32', 'threads': 1, 'seed': 42, 'adapter': hf.LORA,
    'reward_head': 'response_hidden_mean_linear_no_bias_bt', 'optimizer': 'adamw',
    'limits': LIMITS, 'max_attempts': MAX_ATTEMPTS, 'units': list(UNITS),
    'uncertain_accounting': 'declared_upper_bound', 'production_qualified': False}
CONTRACT_DIGEST = digest(CONTRACT)


def _source_digest():
    root = Path(__file__).resolve().parents[3]
    names = ('modelanvil/runners/alignment/hf_rlhf.py', 'modelanvil/runners/alignment/torch_rlhf.py',
        'modelanvil/runners/alignment/torch_dpo.py', 'modelanvil/runners/alignment/reviewed_inputs.py',
        'modelanvil/runners/alignment/preference_groups.py', 'modelanvil/runners/alignment/execution.py',
        'modelanvil/runners/models.py', 'modelanvil/runners/inference.py', 'modelanvil/jobs/models.py',
        'modelanvil/budgets/models.py', 'modelanvil/runners/training/hf_runtime.py',
        'modelanvil/runners/training/cpu_hf_runtime.py', 'modelanvil/runners/training/admission.py',
        'modelanvil/device_admission.py', 'scripts/score_hf_rlhf.py', 'scripts/score_dpo_candidate.py', 'scripts/hf_candidate_infer.py')
    return hashlib.sha256(b''.join((root / name).read_bytes() for name in names)).hexdigest()


_BUILD_DIGEST = _source_digest()


def build_digest():
    global _BUILD_DIGEST
    current = _source_digest()
    if _BUILD_DIGEST is None: _BUILD_DIGEST = current
    if current != _BUILD_DIGEST:
        raise ValueError('CPU RLHF implementation changed; restart the API and worker before execution or recovery.')
    return current


def environment():
    hf.require_packages(); hf.require_adapter_package()
    import importlib.metadata
    if any(importlib.metadata.version(n).split('+')[0] != v for n, v in CONTRACT['packages'].items()):
        raise ValueError('Install the exact pinned CPU alignment packages.')
    return {**cpu.observed_device('cpu'), 'python': platform.python_version(), 'platform': platform.platform(),
        'alignment_packages': CONTRACT['packages']}


def capable_worker(worker):
    caps = worker.capabilities
    return (isinstance(caps, dict) and caps.get('alignment_runtime') == CONTRACT_DIGEST
        and caps.get('alignment_worker_id') == str(worker.pk) and caps.get('host_key') == host_key()
        and caps.get('gpu_device') == 'cpu' and caps.get('gpu_packages') == CONTRACT['packages']
        and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes']
        and worker.slots in (0, 1) and worker.status in ('available', 'busy') and not worker.drain_requested)


def hyperparameters(value, algorithm):
    defaults = {'learning_rate': .001 if algorithm == 'reward_model' else .00002, 'max_gradient_norm': 1.}
    allowed = {'budget_policy_id', 'scoring_budget_policy_id', *defaults}
    if algorithm == 'rloo':
        defaults.update(beta=.1, rollout_group_size=2, max_new_tokens=4, max_kl_divergence=.5)
        allowed |= {'rollout_budget_policy_id', 'beta', 'rollout_group_size', 'max_new_tokens', 'max_kl_divergence'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Unsupported CPU reward/RLOO hyperparameters.')
    hp = {**defaults, **value}
    ranges = [('learning_rate', .000001, .01 if algorithm == 'reward_model' else .0002), ('max_gradient_norm', .1, 1.)]
    if algorithm == 'rloo':
        ranges += [('beta', 0., 1.), ('max_kl_divergence', 0., 2.5)]
        for key, low, high in [('rollout_group_size', 2, 4), ('max_new_tokens', 1, 8)]:
            if type(hp[key]) is not int or not low <= hp[key] <= high:
                raise ValueError(f'CPU RLOO {key} must be between {low} and {high}.')
    for key, low, high in ranges:
        if type(hp[key]) not in (float, int) or not math.isfinite(hp[key]) or not low <= hp[key] <= high:
            raise ValueError(f'CPU alignment {key} must be finite and between {low} and {high}.')
    return hp


def _base(version, tenant, project):
    if version is None or version.architecture_ref not in (cpu.RUNTIME_ID, hf.RUNTIME_ID) or version.tokenizer.chat_template:
        raise ValueError('Select the operator-registered plain pinned SmolLM2-135M base and tokenizer.')
    plan = snapshot(version, tenant, project)
    files = plan.get('files', {})
    if (plan.get('trained') or plan.get('source') != hf.SOURCE or plan.get('format') != 'safetensors'
            or set(files) != set(hf.FILE_HASHES) or any(files[n]['sha256'] != sha for n, sha in hf.FILE_HASHES.items())):
        raise ValueError('CPU reward/RLOO requires the exact unmodified pinned base files.')
    return files


def _policy(run, key, unit):
    try:
        policy = BudgetPolicy.all_objects.get(tenant_id=run.tenant_id,
            policy_id=uuid.UUID(str(run.hyperparameters.get(key))), enabled=True, unit=unit, currency='')
    except (ValueError, TypeError, BudgetPolicy.DoesNotExist):
        raise ValueError(f'Select an explicit enabled {unit} budget without currency.') from None
    return policy


def validate_inputs(run, *, require_capacity=True):
    if run.algorithm not in CONTRACT['algorithms'] or not run.project_id or not run.worker_pool_id:
        raise ValueError('CPU reward/RLOO execution requires a project and dedicated CPU alignment pool.')
    if type(run.total_steps) is not int or not 1 <= run.total_steps <= LIMITS['steps']:
        raise ValueError('CPU reward/RLOO supports 1–20 optimizer updates.')
    if (not Tenant.objects.filter(pk=run.tenant_id, status='active').exists()
            or run.worker_pool.tenant_id != run.tenant_id or run.worker_pool.status != 'active'
            or not isinstance(artifact_storage_backend(), LocalArtifactStorage)):
        raise ValueError('Use an active same-tenant pool, project and local filesystem artifacts.')
    hp = hyperparameters(run.hyperparameters, run.algorithm); observed = environment()
    workers = Worker.all_objects.filter(tenant_id=run.tenant_id, pool=run.worker_pool)
    if run.execution_pins.get('worker_id') is not None: workers = workers.filter(pk=run.execution_pins['worker_id'])
    worker = next((w for w in workers.order_by('pk') if capable_worker(w) and (w.slots > 0 or not require_capacity)), None)
    if worker is None: raise ValueError('No matching trusted CPU reward/RLOO worker is available in this pool.')
    files = _base(run.policy_model_version, run.tenant_id, run.project_id)
    if run.reference_model_version is None or run.reference_model_version.tokenizer_id != run.policy_model_version.tokenizer_id:
        raise ValueError('Pin the starting base as frozen reference with the same exact tokenizer.')
    _base(run.reference_model_version, run.tenant_id, run.project_id)
    datasets, data_pins = {}, {}
    for name, artifact in [('train', run.train_dataset_artifact), ('heldout', run.held_out_dataset_artifact),
                           ('regression', run.regression_dataset_artifact)]:
        pairs, sha, groups = read_reviewed_preferences(artifact, run.tenant_id, run.project_id)
        prompts = {p['prompt'].strip() for p in pairs}
        if any(groups & set(p['source_groups']) or prompts & set(p['prompts']) for p in data_pins.values()):
            raise ValueError('Training, held-out and regression source groups and prompts must be disjoint.')
        datasets[name] = pairs
        data_pins[name] = {'artifact': hf.file_ref(artifact), 'raw_sha256': sha,
            'source_groups': sorted(groups), 'prompts': sorted(prompts)}
    reward = None
    if run.algorithm == 'rloo':
        reward = candidate_bundle(run.reward_model_version, run.tenant_id, run.project_id, role='reward')
        source_run = AlignmentRun.all_objects.get(run_id=reward['provenance']['run_id'], tenant_id=run.tenant_id)
        if not source_run.latest_metrics.get('independent_evaluation', {}).get('passed'):
            raise ValueError('RLOO requires a successful independently qualified learned reward head.')
        protected = [data_pins[n] for n in ('heldout', 'regression')]
        if any(set(p['source_groups']) & set(s['source_groups']) or set(p['prompts']) & set(s['prompts'])
               for p in protected for s in source_run.execution_pins['datasets'].values()):
            raise ValueError('RLOO held-out/regression evidence must be independent of reward training and selection data.')
    elif run.reward_model_version_id:
        raise ValueError('Reward-head training does not consume another reward model.')
    with stage_files({n: ref for n, ref in files.items() if not n.endswith('.safetensors')}, run.tenant_id, run.project_id) as directory:
        tokenizer = hf._tokenizer(directory)
        if len(tokenizer) != run.policy_model_version.tokenizer.vocabulary_size:
            raise ValueError('Registry vocabulary differs from pinned tokenizer bytes.')
        encoded = {name: [encode_pair(tokenizer, pair) for pair in pairs] for name, pairs in datasets.items()}
        if any(p['prompt_tokens'] > 120 for p in encoded['train']):
            raise ValueError('Rollout prompts must fit within 120 tokens without truncation.')
    calls = 4 * len(datasets['heldout']) + 2 * len(datasets['regression'])
    estimates = {'training_steps': MAX_ATTEMPTS * run.total_steps,
        'alignment_scores': MAX_ATTEMPTS * (2 * run.total_steps if run.algorithm == 'reward_model'
            else hp['rollout_group_size'] * run.total_steps) + MAX_ATTEMPTS * calls}
    policies = {'training_steps': _policy(run, 'budget_policy_id', 'training_steps'),
        'alignment_scores': _policy(run, 'scoring_budget_policy_id', 'alignment_scores')}
    if run.algorithm == 'rloo':
        estimates['generated_tokens'] = MAX_ATTEMPTS * run.total_steps * hp['rollout_group_size'] * hp['max_new_tokens']
        policies['generated_tokens'] = _policy(run, 'rollout_budget_policy_id', 'generated_tokens')
    pins = {'runtime': RUNTIME_ID, 'contract_digest': CONTRACT_DIGEST, 'build_digest': build_digest(),
        'algorithm': run.algorithm, 'steps': run.total_steps, 'seed': 42, 'sample_order': 'seeded_epoch_shuffle_v1', 'hyperparameters': hp,
        'environment': observed, 'worker_id': worker.pk, 'pool_id': run.worker_pool_id, 'base_files': files,
        'model_ids': {role: getattr(run, role + '_model_version_id') for role in ('policy', 'reference', 'reward')},
        'model_identities': {role: runtime_input_identity(getattr(run, role + '_model_version'))
            for role in ('policy', 'reference', 'reward') if getattr(run, role + '_model_version') is not None},
        'reward': reward, 'datasets': data_pins, 'encoded_digest': digest(encoded), 'evaluation_score_calls': calls,
        'dataset_manifest_digest': data_pins['train']['raw_sha256'], 'held_out_validation_digest': data_pins['heldout']['raw_sha256'],
        'budget_specs': {unit: {'policy_id': str(policies[unit].policy_id), 'estimated_amount': amount}
            for unit, amount in estimates.items()}, 'production_qualified': False}
    return {'pins': pins, 'encoded': encoded, 'datasets': datasets, 'worker': worker,
        'policies': policies, 'estimates': estimates, 'eos_token_id': tokenizer.eos_token_id}


def authorized_budgets(run):
    refs, specs = run.execution_pins.get('reservations', {}), run.execution_pins['budget_specs']
    if (run.job.max_attempts != MAX_ATTEMPTS or run.job.attempt_count > MAX_ATTEMPTS
            or set(refs) != set(specs) or str(run.resource_reservation_id) != refs.get('training_steps')):
        raise ValueError('CPU alignment retry or reservation scope changed.')
    result = {}
    for unit, spec in sorted(specs.items()):
        reservation = BudgetReservation.all_objects.filter(tenant_id=run.tenant_id, job_id=run.job.job_id,
            reservation_id=refs[unit], state='reserved').first()
        policy = BudgetPolicy.all_objects.select_for_update().filter(tenant_id=run.tenant_id,
            pk=reservation.policy_id).first() if reservation else None
        period, committed = BudgetReservation.current_commitment(policy) if policy else (None, None)
        if (policy is None or not policy.enabled or policy.unit != unit or policy.currency
                or str(policy.policy_id) != spec['policy_id'] or reservation.estimated_amount != spec['estimated_amount']
                or reservation.period_start != period or committed > policy.limit_amount):
            raise ValueError('CPU alignment stage budget is no longer authorized.')
        result[unit] = reservation
    return result


def _current_inputs(run):
    prepared = validate_inputs(run, require_capacity=False)
    if prepared['pins'] != {k: v for k, v in run.execution_pins.items() if k != 'reservations'}:
        raise ValueError('CPU alignment inputs, access, runtime, worker or budget scope changed.')
    authorized_budgets(run)
    return prepared


class ExecutionStopped(ValueError):
    pass


class MeasuredStageStopped(ValueError):
    def __init__(self, actual, metrics):
        self.actual, self.metrics = actual, metrics
        super().__init__('CPU RLOO categorical divergence stop limit exceeded.')


def _live(run, context):
    job = Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id)
    locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
    attempt = JobAttempt.all_objects.filter(pk=context.attempt.pk, job=job, worker_id=context.attempt.worker_id,
        fencing_token=context.fencing_token, status='running', lease_expires_at__gt=timezone.now()).first()
    if (attempt is None or job.status != 'running' or job.desired_action != 'run' or locked.status != 'running'
            or job.fencing_token != context.fencing_token or job.payload != {'type': 'qualified_rlhf', 'run_id': str(run.run_id)}
            or job.project_id != locked.project_id or job.pool_id != locked.worker_pool_id
            or locked.execution_pins != run.execution_pins or context.attempt.worker_id != locked.execution_pins['worker_id']):
        raise ExecutionStopped('CPU alignment attempt lost its claim; publication refused.')
    _current_inputs(locked)
    return locked


def gpu_claim_plan(job, worker):
    run = AlignmentRun.all_objects.filter(job=job, tenant_id=worker.tenant_id,
        run_id=job.payload.get('run_id')).first()
    if run is None or run.project_id != job.project_id or run.worker_pool_id != worker.pool_id:
        raise ValueError('CPU alignment job or placement changed.')
    _current_inputs(run)
    if run.execution_pins['worker_id'] != worker.pk or environment() != run.execution_pins['environment'] or not device_available('cpu'):
        raise ValueError('Pinned CPU worker or physical device is unavailable.')
    return {'host_key': host_key(), 'device_key': device_key('cpu')}


def launch(run, *, resume=False):
    if resume and run.job_id:
        from modelanvil.jobs.models import reconcile_expired_leases
        reconcile_expired_leases(job_ids=[run.job.job_id])
    with transaction.atomic():
        job = Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id) if run.job_id else None
        locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        if job is None and locked.job_id: raise ValueError('Alignment job changed; refresh before launch.')
        if job is not None:
            if not resume: return locked
            if job.status not in ('queued', 'interrupted') or job.desired_action != 'run' or locked.status not in ('pending', 'interrupted'):
                raise ValueError('Only an interrupted reserved CPU alignment job can resume.')
            _current_inputs(locked)
            if job.status == 'interrupted': job.status = 'queued'; job.save(update_fields=['status', 'updated_at'])
            return locked
        if resume or locked.status != 'pending' or locked.current_step:
            raise ValueError('Select a pending unexecuted CPU reward/RLOO plan.')
        inputs = validate_inputs(locked)
        if not device_available('cpu'): raise ValueError('The local CPU lease is busy; no job or budget allocated.')
        job = Job.all_objects.create(tenant_id=locked.tenant_id, project_id=locked.project_id, pool=locked.worker_pool,
            name=f'CPU {locked.algorithm} {locked.run_id}', max_attempts=MAX_ATTEMPTS,
            payload={'type': 'qualified_rlhf', 'run_id': str(locked.run_id)}, requirements={'alignment_runtime': CONTRACT_DIGEST,
                'alignment_worker_id': str(inputs['worker'].pk), 'gpu_device': 'cpu', 'host_key': host_key(), 'slots': 1})
        reservations = {unit: BudgetReservation.reserve(tenant_id=locked.tenant_id, policy=inputs['policies'][unit],
            job_id=job.job_id, estimated_amount=amount) for unit, amount in sorted(inputs['estimates'].items())}
        locked.job = job; locked.execution_pins = {**inputs['pins'],
            'reservations': {unit: str(res.reservation_id) for unit, res in reservations.items()}}
        locked.resource_reservation_id = reservations['training_steps'].reservation_id
        locked.dataset_manifest_digest = inputs['pins']['dataset_manifest_digest']
        locked.held_out_validation_digest = inputs['pins']['held_out_validation_digest']
        locked.save()
        return locked


@contextmanager
def stage_files(files, tenant, project):
    allowed = set(hf.FILE_HASHES) | {'reward_head.safetensors', 'optimizer.safetensors',
        'rollout_reference.safetensors', 'adapter_model.safetensors', 'adapter_config.json'}
    if not isinstance(files, dict) or not files or set(files) - allowed:
        raise ValueError('Unsupported CPU alignment stage files.')
    with tempfile.TemporaryDirectory(prefix='modelanvil-rlhf-stage-') as temp:
        directory = Path(temp)
        for name, ref in files.items():
            artifact = verified_artifact(ref, tenant, project)
            maximum = 512 * 1024**2 if name == 'model.safetensors' else 8 * 1024**2
            if name == 'reward_head.safetensors': maximum = 8192
            if artifact.byte_size > maximum: raise ValueError('CPU alignment file exceeds its declared bound.')
            with (directory / name).open('wb') as output: copy_verified(ref, tenant, project, output)
        yield directory


def checkpoint_state(run, checkpoint):
    state = checkpoint.policy_state
    if (not checkpoint.is_valid or digest(state) != checkpoint.state_digest or state.get('pins') != run.execution_pins
            or state.get('run_id') != str(run.run_id) or state.get('sequence') != checkpoint.step
            or state.get('metrics') != checkpoint.metrics or not 0 <= state.get('updates', -1) <= run.total_steps
            or state.get('phase') not in ('reward_update', 'rollout', 'score', 'policy_update', 'evaluation', 'done')):
        raise ValueError('CPU alignment checkpoint digest, cursor or inputs changed.')
    expected = set(hf.FILE_HASHES) | ({'reward_head.safetensors'} if run.algorithm == 'reward_model'
        else {'adapter_model.safetensors', 'adapter_config.json'})
    if set(state.get('files', {})) != expected:
        raise ValueError('CPU alignment checkpoint files are incomplete.')
    refs = [*state['files'].values(), *([state['adam']] if state.get('adam') else []),
        *([state['reference_logits']] if state.get('reference_logits') else [])]
    for ref in refs: verified_artifact(ref, run.tenant_id, run.project_id)
    return copy.deepcopy(state)


def _initial_state(run):
    return {'run_id': str(run.run_id), 'pins': run.execution_pins, 'sequence': 0, 'updates': 0,
        'phase': 'reward_update' if run.algorithm == 'reward_model' else 'rollout',
        'files': run.execution_pins['base_files'], 'adam': None, 'rng': None, 'metrics': {}}


def stage_bound(run, phase):
    hp = run.execution_pins['hyperparameters']
    units = dict.fromkeys(UNITS, 0)
    if phase in ('reward_update', 'policy_update'): units['training_steps'] = 1
    if phase == 'reward_update': units['alignment_scores'] = 2
    if phase == 'rollout': units['generated_tokens'] = hp['rollout_group_size'] * hp['max_new_tokens']
    if phase == 'score': units['alignment_scores'] = hp['rollout_group_size']
    if phase == 'evaluation': units['alignment_scores'] = run.execution_pins['evaluation_score_calls']
    return units


def usage(run):
    measured, uncertain = dict.fromkeys(UNITS, 0), dict.fromkeys(UNITS, 0)
    for receipt in run.stage_attempts.all():
        values = receipt.actual_units if receipt.actual_units is not None else receipt.upper_units
        target = measured if receipt.actual_units is not None else uncertain
        for unit in UNITS: target[unit] += values[unit]
    return {'measured_units': measured, 'uncertain_upper_units': uncertain,
        'charged_units': {u: measured[u] + uncertain[u] for u in UNITS},
        'uncertain_is_measurement': False}


def _begin_stage(run, context, state):
    with transaction.atomic():
        locked = _live(run, context)
        latest = locked.checkpoints.filter(is_valid=True).order_by('-step').first()
        if ((latest.step if latest else 0) != state['sequence'] or
                latest is not None and latest.state_digest != digest(state)):
            raise ExecutionStopped('Another stage checkpoint superseded this worker state.')
        bound = stage_bound(run, state['phase']); charged = usage(locked)['charged_units']
        if any(charged[u] + bound[u] > run.execution_pins['budget_specs'].get(u, {}).get('estimated_amount', 0) for u in UNITS):
            raise ValueError('CPU alignment stage would exceed its reserved resource bound.')
        return AlignmentStageAttempt.all_objects.create(tenant_id=run.tenant_id, alignment_run=locked,
            job_attempt=context.attempt, sequence=state['sequence'] + 1, phase=state['phase'],
            input_digest=digest(state), upper_units=bound)


def _commit_stage(run, context, receipt, state, actual, observations):
    with transaction.atomic():
        locked = _live(run, context)
        receipt = AlignmentStageAttempt.all_objects.select_for_update().get(pk=receipt.pk)
        if receipt.status != 'started': raise ExecutionStopped('Stage attempt is no longer publishable.')
        checkpoint = AlignmentCheckpoint.all_objects.create(tenant_id=run.tenant_id, alignment_run=locked,
            step=state['sequence'], state_digest=digest(state), policy_state=state, metrics=state['metrics'])
        receipt.status = 'committed' if actual is not None else 'unavailable'
        receipt.actual_units, receipt.observations, receipt.checkpoint = actual, observations, checkpoint
        receipt.save()
        locked.current_step = state['updates']
        locked.latest_metrics = {**state['metrics'], 'phase': state['phase'], 'stage_sequence': state['sequence'],
            'stage_usage': usage(locked), 'production_qualified': False}
        if state.get('evaluation'): locked.latest_metrics['independent_evaluation'] = state['evaluation']
        locked.metrics_history = [*locked.metrics_history, {'sequence': state['sequence'], 'phase': receipt.phase,
            **state['metrics'], **observations, 'actual_units': actual, 'upper_units': receipt.upper_units}]
        if state.get('rollouts'): locked.rollouts_log = state['rollouts']
        locked.save(update_fields=['current_step', 'latest_metrics', 'metrics_history', 'rollouts_log', 'updated_at'])
        run.current_step = locked.current_step


def _save(path, run, context, state):
    return hf._store_file(path, run, context, state['sequence'])


def _numerical_stage(run, context, state, inputs):
    import torch
    from safetensors.torch import load_file, save_file
    phase, hp = state['phase'], run.execution_pins['hyperparameters']
    new = copy.deepcopy(state); new['sequence'] += 1
    actual = stage_bound(run, phase); metrics = {}
    files = dict(state['files'])
    if state.get('adam'): files['optimizer.safetensors'] = state['adam']
    if state.get('reference_logits'): files['rollout_reference.safetensors'] = state['reference_logits']
    with stage_files(files, run.tenant_id, run.project_id) as directory:
        if not context.heartbeat(): raise ExecutionStopped('CPU alignment lost its claim before model loading.')
        if phase == 'reward_update':
            encoder = hf._load_model(directory).requires_grad_(False).eval()
            head = rl.reward_head(encoder.config.hidden_size)
            if state['updates']:
                head.load_state_dict(load_file(str(directory / 'reward_head.safetensors'), device='cpu'), strict=True)
            adam = rl.optimizer(head, hp['learning_rate'])
            if state['updates']: hf._restore_optimizer(head, adam, directory, state['updates'])
            index = hf.training_sample_index(state['updates'] + 1, len(inputs['encoded']['train']), {'sample_order': 'seeded_epoch_shuffle_v1', 'initialization_seed': 42})
            metrics = rl.reward_update(encoder, head, adam, inputs['encoded']['train'][index], hp['max_gradient_norm'])
            save_file(head.state_dict(), str(directory / 'reward_head.safetensors'))
            save_file(hf._optimizer_state(head, adam), str(directory / 'optimizer.safetensors'))
            new['files'] = {**state['files'], 'reward_head.safetensors': _save(directory / 'reward_head.safetensors', run, context, new)}
            new['adam'] = _save(directory / 'optimizer.safetensors', run, context, new)
            new['updates'] += 1; new['phase'] = 'evaluation' if new['updates'] == run.total_steps else 'reward_update'
        elif phase == 'rollout':
            policy = hf._recipe_model(directory, 'lora_adapter', seed=42, training=False, source=hf.SOURCE, adapter=hf.LORA)
            generator = torch.Generator().manual_seed(42)
            if state['rng'] is not None: generator.set_state(torch.tensor(state['rng'], dtype=torch.uint8))
            index = hf.training_sample_index(state['updates'] + 1, len(inputs['encoded']['train']), {'sample_order': 'seeded_epoch_shuffle_v1', 'initialization_seed': 42})
            pair = inputs['encoded']['train'][index]
            samples = rl.generate_rollouts(policy, pair['chosen'][:pair['prompt_tokens']], count=hp['rollout_group_size'],
                max_new_tokens=hp['max_new_tokens'], eos_token_id=inputs['eos_token_id'], generator=generator,
                heartbeat=context.heartbeat)
            new['rollouts'], new['rng'], new['phase'] = samples, generator.get_state().tolist(), 'score'
            actual['generated_tokens'] = sum(r['generated_tokens'] for r in samples)
            if not state['updates']:
                policy.save_pretrained(str(directory), safe_serialization=True, save_embedding_layers=False)
                new['files'] = {**state['files'], **{n: _save(directory / n, run, context, new)
                    for n in ('adapter_model.safetensors', 'adapter_config.json')}}
            metrics = {'generated_tokens': actual['generated_tokens'], 'rollout_count': len(samples)}
        elif phase == 'score':
            # A separate base directory prevents adapter auto-discovery on the frozen reward/reference encoder.
            base = directory / 'base'; base.mkdir()
            for name in hf.FILE_HASHES: os.link(directory / name, base / name)
            reference = hf._load_model(base).requires_grad_(False).eval()
            reward_ref = run.execution_pins['reward']['files']['reward_head.safetensors']
            with stage_files({'reward_head.safetensors': reward_ref}, run.tenant_id, run.project_id) as reward_dir:
                head = rl.reward_head(576)
                head.load_state_dict(load_file(str(reward_dir / 'reward_head.safetensors'), device='cpu'), strict=True)
                head.requires_grad_(False)
            scored, logits = rl.score_rollouts(reference, head, state['rollouts'], hp['beta'])
            save_file(logits, str(directory / 'rollout_reference.safetensors'))
            new['rollouts'], new['phase'] = scored, 'policy_update'
            new['reference_logits'] = _save(directory / 'rollout_reference.safetensors', run, context, new)
            metrics = {'reward_mean': sum(r['reward'] for r in scored) / len(scored)}
        elif phase == 'policy_update':
            policy = hf._recipe_model(directory, 'lora_adapter', seed=42, training=True, source=hf.SOURCE, adapter=hf.LORA)
            adam = rl.optimizer(policy, hp['learning_rate'])
            if state['updates']: hf._restore_optimizer(policy, adam, directory, state['updates'])
            metrics = rl.policy_update(policy, adam, state['rollouts'],
                load_file(str(directory / 'rollout_reference.safetensors'), device='cpu'), hp['max_gradient_norm'])
            if metrics['sampled_context_categorical_kl'] > hp['max_kl_divergence']:
                raise MeasuredStageStopped(actual, metrics)
            policy.save_pretrained(str(directory), safe_serialization=True, save_embedding_layers=False)
            save_file(hf._optimizer_state(policy, adam), str(directory / 'optimizer.safetensors'))
            new['files'] = {**state['files'], **{n: _save(directory / n, run, context, new)
                for n in ('adapter_model.safetensors', 'adapter_config.json')}}
            new['adam'] = _save(directory / 'optimizer.safetensors', run, context, new)
            new['updates'] += 1; new['phase'] = 'evaluation' if new['updates'] == run.total_steps else 'rollout'
            new.pop('reference_logits', None)
        else: raise ValueError('Unknown CPU numerical alignment stage.')
    new['metrics'] = metrics
    return new, actual


def _evaluation(run, context, state, descriptor):
    from modelanvil.runners.training.runtime import read_artifact
    pins = run.execution_pins; data = pins['datasets']
    role = 'reward' if run.algorithm == 'reward_model' else 'policy'
    model_files = {n: r for n, r in state['files'].items() if n != 'reward_head.safetensors'}
    manifest = {'role': role, 'base_files': {n: r['sha256'] for n, r in pins['base_files'].items()},
        'candidate_files': {n: r['sha256'] for n, r in model_files.items()},
        'preferences_sha256': data['heldout']['raw_sha256'], 'regression_sha256': data['regression']['raw_sha256'],
        'training_groups': data['train']['source_groups'], 'training_prompts': data['train']['prompts']}
    if role == 'reward': manifest['reward_head_sha256'] = state['files']['reward_head.safetensors']['sha256']
    raw = json.dumps(manifest, sort_keys=True, allow_nan=False).encode()
    try:
        with tempfile.TemporaryDirectory(prefix='modelanvil-rlhf-score-') as temp, ExitStack() as stack:
            root = Path(temp)
            base = stack.enter_context(stage_files(pins['base_files'], run.tenant_id, run.project_id))
            candidate = stack.enter_context(stage_files(state['files'], run.tenant_id, run.project_id))
            for name, artifact in [('preferences', run.held_out_dataset_artifact), ('regression', run.regression_dataset_artifact)]:
                (root / (name + '.json')).write_bytes(read_artifact(artifact, run.tenant_id, run.project_id))
            (root / 'manifest.json').write_bytes(raw)
            script = Path(__file__).resolve().parents[3] / 'scripts/score_hf_rlhf.py'
            command = [sys.executable, '-I', str(script), '--base', str(base), '--candidate', str(candidate),
                '--preferences', str(root / 'preferences.json'), '--regression', str(root / 'regression.json'),
                '--manifest', str(root / 'manifest.json')]
            env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(root), 'HF_HOME': str(root / 'hub'),
                'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                'VECLIB_MAXIMUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'TOKENIZERS_PARALLELISM': 'false'}
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, pass_fds=(descriptor,))
                deadline = time.monotonic() + 130
                try:
                    while child.poll() is None:
                        if not context.heartbeat(progress=1.): raise ExecutionStopped('CPU evaluation lost its claim.')
                        with transaction.atomic(): _live(run, context)
                        if time.monotonic() > deadline: raise ValueError('Independent CPU RLHF scoring timed out.')
                        time.sleep(.25)
                    if child.returncode: raise ValueError('Independent CPU RLHF scoring did not complete.')
                    stdout.seek(0); output = stdout.read(256 * 1024 + 1)
                    if len(output) > 256 * 1024: raise ValueError('Independent CPU RLHF report exceeds its limit.')
                    report = json.loads(output)
                finally:
                    if child.poll() is None: child.kill()
                    child.wait()
            expected_hashes = {'base': manifest['base_files'], 'candidate': manifest['candidate_files']}
            if role == 'reward': expected_hashes['reward_head'] = manifest['reward_head_sha256']
            expected_calls = (2 if role == 'reward' else 4) * len(run.execution_pins['datasets']['heldout']['prompts']) + 2 * len(data['regression']['prompts'])
            expected_units = {'training_steps': 0, 'generated_tokens': 0, 'alignment_scores': expected_calls}
            if (report.get('schema_version') != 'modelanvil.independent-cpu-rlhf-evaluation.v1'
                    or report.get('role') != role or report.get('manifest_sha256') != hashlib.sha256(raw).hexdigest()
                    or report.get('file_sha256') != expected_hashes
                    or report.get('input_sha256') != {'preferences': manifest['preferences_sha256'], 'regression': manifest['regression_sha256']}
                    or report.get('consumer_imported_modelanvil_or_django') is not False
                    or type(report.get('passed')) is not bool or report.get('actual_units') != expected_units
                    or not isinstance(report.get('checks'), dict) or set(report['checks']) != ({'ranking_above_chance', 'heldout_log_loss_not_regressed', 'separate_regression_ranking_above_chance'} if role == 'reward' else {'preference_accuracy_not_regressed', 'preference_log_loss_not_regressed', 'separate_regression_loss_within_five_percent'})
                    or any(type(v) is not bool for v in report['checks'].values())
                    or report['passed'] != all(report['checks'].values())):
                raise ValueError('Independent CPU RLHF report does not bind exact inputs and candidate weights.')
            return {'status': 'completed', 'passed': report['passed'], 'report': report,
                'production_qualified': False}, expected_units
    except ExecutionStopped: raise
    except (ValueError, OSError):
        return {'status': 'unavailable', 'passed': False,
            'reason': 'Independent CPU scoring unavailable; qualification blocked.', 'production_qualified': False}, None


def worker_executor(descriptor, context):
    import torch
    run = AlignmentRun.all_objects.filter(tenant_id=context.attempt.tenant_id, job_id=context.attempt.job_id,
        run_id=descriptor.get('payload', {}).get('run_id')).first()
    if (run is None or descriptor.get('payload') != {'type': 'qualified_rlhf', 'run_id': str(run.run_id)}
            or descriptor.get('job_id') != str(run.job.job_id)):
        raise ValueError('CPU alignment descriptor does not match its claimed run.')
    previous_threads = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        with transaction.atomic():
            Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id)
            run = AlignmentRun.all_objects.select_for_update().get(pk=run.pk)
            if run.status not in ('pending', 'interrupted'): raise ExecutionStopped('CPU alignment is not resumable by this attempt.')
            run.status, run.started_at = 'running', run.started_at or timezone.now()
            run.save(update_fields=['status', 'started_at', 'updated_at']); inputs = _current_inputs(run); _live(run, context)
        with device_lease('cpu', pass_descriptor=True) as cpu_descriptor, hf.deterministic_updates():
            latest = run.checkpoints.filter(is_valid=True).order_by('-step').first()
            state = checkpoint_state(run, latest) if latest else _initial_state(run)
            if state['updates'] != run.current_step: raise ValueError('CPU alignment durable cursor differs from checkpoint.')
            while state['phase'] != 'done':
                if not context.heartbeat(progress=state['updates'] / run.total_steps): return None
                receipt = _begin_stage(run, context, state)
                wall, cpu_started = time.monotonic(), time.process_time()
                if state['phase'] == 'evaluation':
                    evaluation, actual = _evaluation(run, context, state, cpu_descriptor)
                    new = {**state, 'sequence': state['sequence'] + 1, 'phase': 'done', 'evaluation': evaluation}
                else:
                    new, actual = _numerical_stage(run, context, state, inputs)
                observations = {'worker_cpu_seconds': time.process_time() - cpu_started, 'wall_seconds': time.monotonic() - wall,
                    'cpu_scope': 'Worker process; independent scorer CPU is reported separately.'}
                _commit_stage(run, context, receipt, new, actual, observations)
                state = new; gc.collect()
    except MeasuredStageStopped as stopped:
        with transaction.atomic():
            locked = _live(run, context)
            receipt = AlignmentStageAttempt.all_objects.select_for_update().get(pk=receipt.pk)
            receipt.status, receipt.actual_units = 'measured_aborted', stopped.actual
            receipt.observations = {'stop_reason': 'categorical_kl_stop', 'metrics': stopped.metrics}
            receipt.save()
            locked.latest_metrics = {**locked.latest_metrics, **stopped.metrics, 'stage_usage': usage(locked)}
            locked.save(update_fields=['latest_metrics', 'updated_at'])
        return None
    except Exception:
        # The winning job transaction derives status from durable receipts, never an untrusted response body.
        # A started receipt remains explicitly uncertain when compute cannot be measured or fenced publication loses.
        return None
    finally:
        gc.collect(); torch.set_num_threads(previous_threads)
    return None


def _uncertain_stages(run):
    for receipt in run.stage_attempts.select_for_update().filter(status='started'):
        receipt.status = 'uncertain'
        receipt.observations = {'measurement': 'Unknown after interruption or refused fenced publication; charged declared upper bound.'}
        receipt.save()


def _settle(run):
    totals = usage(run)
    for unit, ref in run.execution_pins.get('reservations', {}).items():
        reservation = BudgetReservation.all_objects.get(tenant_id=run.tenant_id, reservation_id=ref, job_id=run.job.job_id)
        reservation.settle(totals['charged_units'][unit])
        UsageEvent.record(tenant_id=run.tenant_id, provider_event_key=f'cpu-rlhf:{run.run_id}:{unit}',
            quantity=totals['charged_units'][unit], unit=unit, reservation=reservation,
            detail={'runtime': RUNTIME_ID, 'algorithm': run.algorithm, 'status': run.status,
                'measured': totals['measured_units'][unit], 'uncertain_upper_bound': totals['uncertain_upper_units'][unit],
                'uncertain_is_measurement': False, 'production_qualified': False})
    run.latest_metrics = {**run.latest_metrics, 'stage_usage': totals}
    run.save(update_fields=['latest_metrics', 'updated_at'])


def _bundle(run, checkpoint):
    state = checkpoint_state(run, checkpoint)
    if state['phase'] != 'done' or state['updates'] != run.total_steps:
        raise ValueError('CPU alignment requires all stages and final independent evaluation.')
    evaluation = state.get('evaluation', {})
    if (evaluation.get('status') not in ('completed', 'unavailable') or type(evaluation.get('passed')) is not bool
            or evaluation.get('status') == 'unavailable' and evaluation['passed']):
        raise ValueError('CPU alignment independent qualification evidence is missing.')
    return {'source': hf.SOURCE, 'files': state['files'], 'adapter': hf.LORA if run.algorithm == 'rloo' else None,
        'model_role': 'reward' if run.algorithm == 'reward_model' else 'policy',
        'reward_config': {'hidden_size': 576, 'pooling': 'response_hidden_mean_including_eos', 'bias': False} if run.algorithm == 'reward_model' else None,
        'provenance': {'run_id': str(run.run_id), 'sequence': checkpoint.step, 'updates': state['updates'],
            'checkpoint_digest': checkpoint.state_digest, 'pins': run.execution_pins},
        'production_qualified': False}


def finalize_job(job, status):
    """Trusted winning commit/expiry only; worker response cannot publish a candidate."""
    run = AlignmentRun.all_objects.select_for_update().filter(job=job, tenant_id=job.tenant_id).first()
    if run is None: return Job.Status.FAILED
    if run.status in ('completed', 'cancelled', 'failed'):
        return {'completed': Job.Status.SUCCEEDED, 'cancelled': Job.Status.CANCELLED, 'failed': Job.Status.FAILED}[run.status]
    _uncertain_stages(run)
    if job.desired_action == 'cancel': status = Job.Status.CANCELLED
    if status in (Job.Status.QUEUED, Job.Status.INTERRUPTED):
        run.status, run.stop_reason = 'interrupted', 'worker_attempt_interrupted'
        run.latest_metrics = {**run.latest_metrics, 'stage_usage': usage(run)}
        run.save(update_fields=['status', 'stop_reason', 'latest_metrics', 'updated_at'])
        return status
    if status == Job.Status.SUCCEEDED and run.stage_attempts.filter(status='measured_aborted').exists():
        status = Job.Status.FAILED
    if status == Job.Status.SUCCEEDED:
        try:
            if (job.payload != {'type': 'qualified_rlhf', 'run_id': str(run.run_id)} or job.project_id != run.project_id
                    or job.pool_id != run.worker_pool_id or run.current_step != run.total_steps or run.output_model_version_id):
                raise ValueError('CPU alignment final cursor, job or project changed.')
            _current_inputs(run)
            checkpoint = run.checkpoints.filter(is_valid=True).order_by('-step').first()
            if checkpoint is None: raise ValueError('No final CPU alignment checkpoint.')
            bundle = _bundle(run, checkpoint)
            with stage_files({**bundle['files'], 'optimizer.safetensors': checkpoint.policy_state['adam']}, run.tenant_id, run.project_id): pass
            payload = json.dumps(bundle, sort_keys=True, allow_nan=False).encode()
            artifact = Artifact.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id, storage_location_id='local',
                object_key=f'alignment/{run.run_id}/candidate-{uuid.uuid4()}.json', sha256=hashlib.sha256(payload).hexdigest(),
                byte_size=len(payload), media_type='application/json')
            upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
            model = Model.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
                name=f'{run.algorithm}-{run.run_id}', intended_tasks=['reward_scoring' if run.algorithm == 'reward_model' else 'text_generation'])
            evaluation = checkpoint.policy_state['evaluation']
            weights_name = 'reward_head.safetensors' if run.algorithm == 'reward_model' else 'adapter_model.safetensors'
            run.output_model_version = ModelVersion.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
                model=model, revision_no=1, tokenizer=run.policy_model_version.tokenizer, architecture_ref=RUNTIME_ID,
                artifact_manifest_id=str(artifact.artifact_id), producing_job_id=job.job_id, state=ModelVersion.State.DRAFT,
                license_evidence=run.policy_model_version.license_evidence, metadata={'alignment_recipe': run.algorithm,
                    'source_run_id': str(run.run_id), 'checkpoint_digest': checkpoint.state_digest, 'trained': True,
                    'model_role': bundle['model_role'], 'weights_sha256': bundle['files'][weights_name]['sha256'],
                    'independent_evaluation_passed': evaluation['passed'], 'production_qualified': False})
            run.status = 'completed'
            run.stop_reason = 'completed' if evaluation['passed'] else 'completed_evaluation_' + ('unavailable' if evaluation['status'] == 'unavailable' else 'failed')
        except (ValueError, TypeError, KeyError, OSError, Artifact.DoesNotExist):
            status = Job.Status.FAILED
            run.status, run.stop_reason = 'failed', 'candidate_publication_refused'
    else:
        run.status = 'cancelled' if status == Job.Status.CANCELLED else 'failed'
        run.stop_reason = 'cancelled' if status == Job.Status.CANCELLED else ('categorical_kl_stop' if run.stage_attempts.filter(status='measured_aborted', observations__stop_reason='categorical_kl_stop').exists() else 'worker_execution_failed')
    run.completed_at = timezone.now()
    run.save(update_fields=['status', 'stop_reason', 'completed_at', 'output_model_version', 'updated_at'])
    _settle(run)
    return status


def cancel(run):
    with transaction.atomic():
        job = Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id) if run.job_id else None
        locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        if job is None and locked.job_id: raise ValueError('Alignment job changed; refresh before cancelling.')
        if locked.status in ('completed', 'cancelled', 'failed'): return locked
        if job is None:
            locked.status, locked.stop_reason, locked.completed_at = 'cancelled', 'cancelled', timezone.now()
            locked.save(update_fields=['status', 'stop_reason', 'completed_at', 'updated_at'])
        else:
            job.desired_action = 'cancel'; job.save(update_fields=['desired_action', 'updated_at'])
            if job.status != 'running':
                job.status = finalize_job(job, Job.Status.CANCELLED); job.save(update_fields=['status', 'updated_at'])
        return AlignmentRun.all_objects.get(pk=locked.pk)


def candidate_bundle(version, tenant, project, *, role=None):
    if (version is None or version.architecture_ref != RUNTIME_ID or not check_resource_access(version, project, tenant)
            or not check_resource_access(version.tokenizer, project, tenant) or version.state in ('archived', 'rejected')):
        raise ValueError('Select an accessible actual CPU reward/RLOO candidate.')
    run = AlignmentRun.all_objects.filter(tenant_id=tenant, output_model_version=version, status='completed',
        job__status='succeeded', execution_pins__runtime=RUNTIME_ID).first()
    if (run is None or not check_resource_access(run, project, tenant)
            or version.tokenizer_id != run.policy_model_version.tokenizer_id or str(version.producing_job_id) != str(run.job.job_id)):
        raise ValueError('CPU alignment candidate requires its successful producing job, tokenizer and checkpoint lineage.')
    checkpoint = run.checkpoints.filter(is_valid=True).order_by('-step').first()
    if checkpoint is None or version.metadata.get('checkpoint_digest') != checkpoint.state_digest:
        raise ValueError('CPU alignment candidate checkpoint lineage changed.')
    bundle = _bundle(run, checkpoint)
    if role is not None and bundle['model_role'] != role: raise ValueError('CPU alignment model role differs.')
    artifact = Artifact.all_objects.filter(tenant_id=tenant, artifact_id=version.artifact_manifest_id).first()
    if artifact is None or artifact.byte_size > 1024**2: raise ValueError('CPU alignment candidate manifest unavailable.')
    target = io.BytesIO(); copy_verified(hf.file_ref(artifact), tenant, project, target)
    if digest(json.loads(target.getvalue())) != digest(bundle): raise ValueError('CPU alignment candidate manifest differs from checkpoint.')
    if run.latest_metrics.get('independent_evaluation') != checkpoint.policy_state['evaluation']:
        raise ValueError('CPU alignment qualification evidence differs from its durable evaluation stage.')
    return bundle
