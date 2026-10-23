"""Bounded local alignment execution with verified inputs and fenced publications."""
from __future__ import annotations

import hashlib
import io
import json
import math
import time
import uuid
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import LocalArtifactStorage, artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.local_execution import load_character_bundle
from modelanvil.runners.models import AlignmentCheckpoint, AlignmentRun, Model, ModelVersion
from modelanvil.runners.training import runtime
from modelanvil.runners.training.engine import TrainingEngine

RUNTIME_ID = 'modelanvil.cpu-character-alignment.v1'
ALGORITHMS = ['dpo', 'reward_model', 'ppo_rlhf', 'verifier_rl', 'grpo']
LIMITS = {'steps': 100, 'rows': 32, 'response_characters': 32, 'sequence_tokens': 64}


def read_preferences(artifact, *, tenant, project):
    raw = runtime.read_artifact(artifact, tenant, project)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('Preferences must contain valid JSON.') from exc
    if not isinstance(data, dict) or data.get('schema_version') != 'modelanvil.preference-pairs.v1':
        raise ValueError('Register a modelanvil.preference-pairs.v1 preference artifact.')
    pairs = data.get('pairs')
    validate_preference_pairs(pairs)
    return pairs, hashlib.sha256(raw).hexdigest()


def validate_preference_pairs(pairs):
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= LIMITS['rows']:
        raise ValueError('Register 1–32 preference pairs.')
    seen = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError('Preference pairs must be objects.')
        for key in ('prompt', 'chosen', 'rejected'):
            if not isinstance(pair.get(key), str) or not pair[key].strip():
                raise ValueError('Each pair requires nonempty prompt, chosen and rejected text.')
        if pair['chosen'] == pair['rejected']:
            raise ValueError('Chosen and rejected responses must differ.')
        if any(len(pair[key]) > 32 or len(pair['prompt'] + pair[key]) > 62 for key in ('chosen', 'rejected')):
            raise ValueError('Responses support up to 32 characters and prompt plus response up to 62.')
        identity = (pair['prompt'], pair['chosen'], pair['rejected'])
        if identity in seen:
            raise ValueError('Preference pairs must be unique.')
        seen.add(identity)


def validate_alignment_inputs(run):
    from .numerical import normalize_hyperparameters, score_reward
    if run.algorithm not in ALGORITHMS:
        raise ValueError('Select a supported alignment recipe.')
    if type(run.total_steps) is not int or not 1 <= run.total_steps <= LIMITS['steps']:
        raise ValueError('Local alignment supports 1–100 optimizer steps.')
    if not isinstance(run.hyperparameters, dict):
        raise ValueError('Hyperparameters must be an object.')
    if not run.train_dataset_artifact_id or not run.held_out_dataset_artifact_id:
        raise ValueError('Pin training and held-out preference artifacts before executing alignment.')
    if not run.policy_model_version_id:
        raise ValueError('Select a verified CPU character policy model.')
    hp = normalize_hyperparameters(run.algorithm, {k: v for k, v in run.hyperparameters.items() if k != 'budget_policy_id'})
    if not isinstance(artifact_storage_backend(), LocalArtifactStorage):
        raise ValueError('Local alignment requires the filesystem artifact backend.')
    train, train_digest = read_preferences(run.train_dataset_artifact, tenant=run.tenant_id, project=run.project_id)
    heldout, heldout_digest = read_preferences(run.held_out_dataset_artifact, tenant=run.tenant_id, project=run.project_id)
    if {p['prompt'].strip() for p in train} & {p['prompt'].strip() for p in heldout}:
        raise ValueError('Training and held-out prompts must be disjoint.')
    policy, policy_artifact, _ = load_character_bundle(run.policy_model_version, tenant=run.tenant_id, project=run.project_id)
    if policy['config.json'].get('runtime') != runtime.RUNTIME_ID:
        raise ValueError('Policy bundle must declare the CPU character runtime.')
    spec = policy['tokenizer_config.json']
    for pair in train + heldout:
        for key in ('prompt', 'chosen', 'rejected'):
            if any(char not in spec['tokens'][4:] for char in pair[key]):
                raise ValueError('Preferences must be fully covered by the policy character vocabulary.')
    pins = {'runtime': RUNTIME_ID, 'algorithm': run.algorithm, 'steps': run.total_steps,
            'dataset_manifest_digest': train_digest, 'held_out_validation_digest': heldout_digest,
            'train_artifact_id': str(run.train_dataset_artifact.artifact_id),
            'held_out_artifact_id': str(run.held_out_dataset_artifact.artifact_id),
            'policy_model_version_id': str(run.policy_model_version.model_version_id),
            'policy_artifact_digest': policy_artifact.sha256, 'tokenizer_digest': runtime.digest(spec),
            'hyperparameters': hp, 'verifier_spec': run.verifier_spec,
            'build_digest': hashlib.sha256(b''.join((Path(__file__).parent / name).read_bytes()
                for name in ('execution.py', 'numerical.py'))).hexdigest()}
    bundles = {'policy_bundle': policy, 'reference_bundle': None, 'reward_bundle': None}
    if run.algorithm in ('dpo', 'ppo_rlhf') and not run.reference_model_version_id:
        raise ValueError('DPO and PPO require a pinned reference model.')
    for role in ('reference', 'reward'):
        version = getattr(run, f'{role}_model_version')
        if version is None:
            continue
        if version.tokenizer_id != run.policy_model_version.tokenizer_id:
            raise ValueError('Policy, reference and reward models must share the same tokenizer.')
        bundle, artifact, _ = load_character_bundle(version, tenant=run.tenant_id, project=run.project_id)
        if bundle['config.json'].get('runtime') != runtime.RUNTIME_ID:
            raise ValueError('Reference and reward bundles must declare the CPU character runtime.')
        bundles[f'{role}_bundle'] = bundle
        pins[f'{role}_model_version_id'] = str(version.model_version_id)
        pins[f'{role}_artifact_digest'] = artifact.sha256
    if run.algorithm == 'ppo_rlhf':
        if bundles['reward_bundle'] is None:
            raise ValueError('PPO requires a trained Bradley–Terry reward model.')
        score_reward(bundles['reward_bundle'], train[0]['prompt'], train[0]['chosen'])
    if run.algorithm == 'verifier_rl':
        if not isinstance(run.verifier_spec, dict) or run.verifier_spec.get('type') not in ('exact_match', 'substring', 'numeric_tolerance'):
            raise ValueError('Verifier requires exact_match, substring or numeric_tolerance; chosen responses supply targets.')
        if set(run.verifier_spec) - {'type', 'tolerance'}:
            raise ValueError('Verifier configuration supports type and numeric tolerance only.')
        tolerance = run.verifier_spec.get('tolerance', 0.0001)
        if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 <= tolerance <= 1000000:
            raise ValueError('Verifier tolerance must be finite and between 0 and 1000000.')
    if run.algorithm == 'grpo':
        from . import grpo, verifier_runtime
        grpo.groups(train, heldout)
        pins['verifier_spec'] = grpo.verifier_spec(run.verifier_spec)
        pins['verifier_runtime'] = verifier_runtime.contract()
        pins['seed'] = 42
        paths = [Path(__file__).parent / name for name in ('execution.py', 'numerical.py', 'grpo.py', 'verifier_runtime.py')]
        paths.append(verifier_runtime.SCRIPT)
        pins['build_digest'] = hashlib.sha256(b''.join(path.read_bytes() for path in paths)).hexdigest()
    return {'pins': pins, **bundles, 'train_preferences': train, 'heldout_preferences': heldout,
            'hyperparameters': hp}


def alignment_capabilities(run):
    reason = 'Bounded local CPU alignment; candidate weights require independent evaluation.'
    can_execute = run.status == AlignmentRun.Status.PENDING
    if can_execute:
        try:
            validate_alignment_inputs(run)
            if run.algorithm == 'grpo' and _budget(run) is None:
                raise ValueError('GRPO requires an enabled training_steps budget.')
        except (ValueError, TypeError, AttributeError) as exc:
            can_execute, reason = False, str(exc)
    elif run.status == AlignmentRun.Status.COMPLETED and run.execution_pins:
        reason = 'Completed with verified candidate weights.'
    else:
        reason = f'This {run.status} run cannot be launched.'
    return {'can_execute': can_execute,
            'can_resume': bool(run.algorithm == 'grpo' and run.current_step and run.execution_pins
                and run.status in (AlignmentRun.Status.RUNNING, AlignmentRun.Status.INTERRUPTED)),
            'supported_algorithms': ALGORITHMS,
            'runtime': RUNTIME_ID, 'reason': reason, 'limits': LIMITS}


def _settle(run):
    if run.started_at is None:
        return
    reservation = None
    if run.resource_reservation_id:
        reservation = BudgetReservation.all_objects.get(tenant_id=run.tenant_id, reservation_id=run.resource_reservation_id)
        if reservation.state == BudgetReservation.State.RESERVED:
            reservation.settle(run.current_step)
    UsageEvent.record(tenant_id=run.tenant_id, provider_event_key=f'alignment:{run.run_id}',
        quantity=run.current_step, unit='training_steps', reservation=reservation,
        detail={'runtime': RUNTIME_ID, 'algorithm': run.algorithm, 'status': run.status,
                'cpu_seconds': sum(m.get('cpu_seconds', 0) + m.get('verifier_cpu_seconds', 0) for m in run.metrics_history),
                'production_qualified': False})


def _budget(run):
    policies = BudgetPolicy.all_objects.filter(tenant_id=run.tenant_id, unit='training_steps', enabled=True)
    policy_id = run.hyperparameters.get('budget_policy_id')
    if policy_id is not None:
        try:
            policy = policies.get(policy_id=uuid.UUID(str(policy_id)))
        except (ValueError, BudgetPolicy.DoesNotExist):
            raise ValueError('Select an enabled training_steps budget in this tenant.') from None
        return policy
    # Require an explicit selection instead of choosing an arbitrary policy.
    if policies.count() > 1:
        raise ValueError('Select budget_policy_id when multiple training_steps budgets exist.')
    return policies.first()


class ExecutionStopped(ValueError):
    pass


def _grpo_budget(run):
    reservation = BudgetReservation.all_objects.filter(tenant_id=run.tenant_id,
        reservation_id=run.resource_reservation_id, job_id=run.run_id, state='reserved').first()
    policy = (BudgetPolicy.all_objects.select_for_update().filter(pk=reservation.policy_id, tenant_id=run.tenant_id).first()
              if reservation else None)
    period, committed = BudgetReservation.current_commitment(policy) if policy else (None, None)
    if (not policy or not policy.enabled or policy.unit != 'training_steps' or policy.currency
            or reservation.estimated_amount != run.total_steps or reservation.period_start != period
            or committed > policy.limit_amount):
        raise ValueError('GRPO step budget changed or is no longer authorized.')


def _live(run, token):
    locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
    if locked.status != AlignmentRun.Status.RUNNING or locked.execution_token != token:
        raise ExecutionStopped('Alignment execution stopped; no further weights will be published.')
    if locked.algorithm == 'grpo':
        _grpo_budget(locked)
    return locked


def execute_alignment(run, *, resume=False):
    """Numerical work outside transactions; each checkpoint and candidate checks the claim."""
    from .numerical import train_alignment
    resume_bundle = None
    with transaction.atomic():
        locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        if locked.status == AlignmentRun.Status.COMPLETED and locked.execution_pins:
            load_character_bundle(locked.output_model_version, tenant=locked.tenant_id, project=locked.project_id)
            return locked
        if resume:
            if (locked.algorithm != 'grpo' or locked.status not in (AlignmentRun.Status.RUNNING, AlignmentRun.Status.INTERRUPTED)
                    or not locked.current_step or not locked.execution_pins):
                raise ValueError('Only an interrupted/running GRPO run with a committed checkpoint can be taken over.')
            inputs = validate_alignment_inputs(locked)
            if inputs['pins'] != locked.execution_pins:
                raise ValueError('GRPO pinned inputs or runtime changed; recovery refused.')
            checkpoint = locked.checkpoints.filter(step=locked.current_step, is_valid=True).first()
            if (checkpoint is None or runtime.digest(checkpoint.policy_state) != checkpoint.state_digest
                    or checkpoint.policy_state.get('pins') != inputs['pins']
                    or checkpoint.policy_state.get('run_id') != str(locked.run_id)
                    or checkpoint.policy_state.get('step') != locked.current_step):
                raise ValueError('GRPO checkpoint integrity verification failed.')
            resume_bundle = checkpoint.policy_state['bundle']
            TrainingEngine.verify_external_loadable(resume_bundle)
            _grpo_budget(locked)
        else:
            if locked.status != AlignmentRun.Status.PENDING or locked.current_step:
                raise ValueError('Only a pending, unexecuted plan can be launched. Use explicit GRPO checkpoint takeover for interrupted work.')
            inputs = validate_alignment_inputs(locked)
            policy = _budget(locked)
            if locked.algorithm == 'grpo' and policy is None:
                raise ValueError('GRPO requires an enabled training_steps budget.')
            if policy:
                reservation = BudgetReservation.reserve(tenant_id=locked.tenant_id, policy=policy,
                    job_id=locked.run_id, estimated_amount=locked.total_steps)
                locked.resource_reservation_id = reservation.reservation_id
            locked.execution_pins = inputs['pins']
            locked.dataset_manifest_digest = inputs['pins']['dataset_manifest_digest']
            locked.held_out_validation_digest = inputs['pins']['held_out_validation_digest']
        locked.execution_token = token = uuid.uuid4()
        locked.started_at, locked.status = locked.started_at or timezone.now(), AlignmentRun.Status.RUNNING
        locked.save()
        run = locked

    last_clock = time.thread_time()

    def checkpoint(step, bundle, metrics, rollouts):
        nonlocal last_clock
        now_clock = time.thread_time()
        metrics = {**metrics, 'cpu_seconds': now_clock - last_clock}
        last_clock = now_clock
        TrainingEngine.verify_external_loadable(bundle)
        state = {'run_id': str(run.run_id), 'step': step, 'pins': inputs['pins'], 'bundle': bundle}
        with transaction.atomic():
            locked = _live(run, token)
            if locked.current_step != step - 1 or locked.execution_pins != inputs['pins']:
                raise ValueError('Alignment cursor or pinned inputs changed; checkpoint refused.')
            AlignmentCheckpoint.all_objects.create(tenant_id=run.tenant_id, alignment_run=locked,
                step=step, state_digest=runtime.digest(state), policy_state=state, metrics=metrics)
            locked.current_step = step
            locked.metrics_history = [*locked.metrics_history, metrics]
            locked.latest_metrics = metrics
            locked.rollouts_log = [*locked.rollouts_log, *rollouts][-20:]
            locked.save(update_fields=['current_step', 'metrics_history', 'latest_metrics', 'rollouts_log', 'updated_at'])

    def check_live():
        with transaction.atomic():
            _live(run, token)

    try:
        result = train_alignment(run.algorithm, inputs['policy_bundle'], inputs['train_preferences'],
            inputs['heldout_preferences'], reference_bundle=inputs['reference_bundle'],
            reward_bundle=inputs['reward_bundle'], steps=run.total_steps,
            hyperparameters=inputs['hyperparameters'], verifier_spec=run.verifier_spec, on_step=checkpoint,
            **({'resume_bundle': resume_bundle, 'before_step': check_live} if run.algorithm == 'grpo' else {}))
        with transaction.atomic():
            locked = _live(run, token)
            # Reverify input pins before committing the candidate, including scope and actual bytes.
            if validate_alignment_inputs(locked)['pins'] != inputs['pins']:
                raise ValueError('Alignment inputs changed during execution; candidate refused.')
            cp = AlignmentCheckpoint.all_objects.get(alignment_run=locked, step=locked.total_steps)
            if (locked.current_step != locked.total_steps or runtime.digest(cp.policy_state) != cp.state_digest
                    or cp.policy_state.get('pins') != inputs['pins'] or cp.policy_state.get('bundle') != result['bundle']):
                raise ValueError('Final checkpoint integrity verification failed.')
            bundle = {**result['bundle'], 'provenance.json': {'alignment_run_id': str(run.run_id),
                'pins': inputs['pins'], 'checkpoint_digest': cp.state_digest, 'trained': True,
                'production_qualified': False}}
            TrainingEngine.verify_external_loadable(bundle)
            payload = json.dumps(bundle, sort_keys=True, allow_nan=False).encode()
            artifact = Artifact.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
                storage_location_id='local', object_key=f'alignment/{run.run_id}/candidate.json',
                sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
            upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
            model = Model.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
                name=f'{run.algorithm}-{run.run_id}', intended_tasks=['reward_scoring' if run.algorithm == 'reward_model' else 'text_generation'])
            locked.output_model_version = ModelVersion.all_objects.create(tenant_id=run.tenant_id,
                project_id=run.project_id, model=model, revision_no=1, tokenizer=run.policy_model_version.tokenizer,
                architecture_ref=runtime.RUNTIME_ID, artifact_manifest_id=str(artifact.artifact_id),
                parameters_count=run.policy_model_version.parameters_count, state=ModelVersion.State.DRAFT,
                license_evidence=run.policy_model_version.license_evidence,
                producing_job_id=run.run_id, metadata={'alignment_recipe': run.algorithm,
                    'source_run_id': str(run.run_id), 'weights_sha256': bundle['weights_manifest.json']['weights_sha256'],
                    'checkpoint_digest': cp.state_digest, 'trained': True, 'production_qualified': False,
                    'model_role': 'reward_model' if run.algorithm == 'reward_model' else 'policy'})
            locked.latest_metrics = {**locked.latest_metrics, **result['latest_metrics'], 'held_out_evaluation': result['heldout_metrics']}
            locked.status, locked.stop_reason, locked.completed_at = AlignmentRun.Status.COMPLETED, 'completed', timezone.now()
            locked.save()
            _settle(locked)
            return locked
    except ExecutionStopped:
        return AlignmentRun.all_objects.get(pk=run.pk, tenant_id=run.tenant_id)
    except Exception:
        with transaction.atomic():
            locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
            if locked.status == AlignmentRun.Status.RUNNING and locked.execution_token == token:
                locked.status, locked.stop_reason, locked.completed_at = AlignmentRun.Status.FAILED, 'execution_failed', timezone.now()
                locked.save(update_fields=['status', 'stop_reason', 'completed_at', 'updated_at'])
                _settle(locked)
        raise


def cancel_alignment(run):
    with transaction.atomic():
        locked = AlignmentRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        if locked.status in (AlignmentRun.Status.COMPLETED, AlignmentRun.Status.FAILED, AlignmentRun.Status.CANCELLED):
            return locked
        locked.status, locked.stop_reason, locked.completed_at = AlignmentRun.Status.CANCELLED, 'cancelled', timezone.now()
        locked.execution_token = None
        locked.save(update_fields=['status', 'stop_reason', 'completed_at', 'execution_token', 'updated_at'])
        _settle(locked)
        return locked
