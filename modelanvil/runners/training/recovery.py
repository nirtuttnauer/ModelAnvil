"""A terminal execution resumes through a new job and remaining-step reservation."""
from copy import deepcopy
import math

from django.db import transaction
from django.core.exceptions import ValidationError
from modelanvil.core.tenancy import get_active_project
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Job, JobAttempt
from modelanvil.runners.models import RunnerManifest, TrainingCheckpoint, TrainingRun
from modelanvil.runners.training import general_runtime, runtime, registry


def recovery_review(run, *, policy=None):
    blockers = []
    if get_active_project() and get_active_project() != run.project_id:
        blockers.append('Recovery must be launched from the originating project.')
    job = run.job
    pins = run.hardware_config.get('pins', {})
    module = registry.runtime_module(pins.get('runtime'))
    checkpoint = run.checkpoints.order_by('-step').first()
    remaining = run.total_steps - run.current_step
    if module not in (runtime, general_runtime):
        blockers.append('Self-service recovery supports the CPU character and CPU transformer runtimes only.')
    if not registry.is_worker_run(run) or not job:
        blockers.append('This execution has no durable worker job.')
    elif (job.status not in (Job.Status.FAILED, Job.Status.INTERRUPTED)
          or run.status != TrainingRun.Status.FAILED):
        blockers.append('Only a failed or interrupted terminal execution can be resumed.')
    if job:
        if job.desired_action != Job.DesiredAction.RUN:
            blockers.append('Cancellation must be resolved before recovery; cancelled work cannot resume.')
        if (job.claimed_by_id or job.lease_expires_at or job.fencing_token
                or job.attempts.filter(status=JobAttempt.Status.RUNNING).exists()):
            blockers.append('Worker ownership is active or unresolved; reconcile the lease first.')
    if remaining <= 0:
        blockers.append('All optimizer steps are already committed.')
    if not checkpoint or checkpoint.step != run.current_step or run.current_step <= 0:
        blockers.append('A verified checkpoint at the exact committed cursor is required.')
    if module in (runtime, general_runtime) and checkpoint and not blockers:
        try:
            manifest = RunnerManifest.all_objects.get(tenant_id=run.tenant_id, manifest_id=pins['runner_id'])
            inputs = registry.resolve_inputs(dataset=run.dataset_revision, base=run.base_model_version,
                tokenizer=run.tokenizer_version, runner=manifest, pool=run.pool, tenant=run.tenant_id,
                project=run.project_id, steps=run.total_steps, recipe_type=run.recipe_type,
                initialization_seed=run.initialization_seed, hyperparameters=run.hyperparameters)
            if inputs['pins'] != pins:
                raise ValueError('Pinned inputs, runtime build or optimizer changed; exact recovery is unavailable.')
            bundle = module.checkpoint_bundle(run, checkpoint)
            if module == general_runtime:
                model, _ = module._load_general_export_model(bundle)
                moments = checkpoint.weights_manifest.get('adam', {})
                count = len(model.parameters())
                if (moments.get('t') != checkpoint.step or len(moments.get('m', [])) != count
                        or len(moments.get('v', [])) != count
                        or any(not math.isfinite(x) for x in [*moments['m'], *moments['v']])
                        or any(x < 0 for x in moments['v'])):
                    raise ValueError('The checkpoint lacks compatible finite AdamW optimizer state.')
        except (ValueError, KeyError, TypeError, ValidationError, RunnerManifest.DoesNotExist) as exc:
            blockers.append(str(exc) or 'Checkpoint or pinned inputs are unavailable.')
    original = BudgetReservation.all_objects.filter(tenant_id=run.tenant_id,
        reservation_id=run.resource_reservation_id, job_id=getattr(job, 'job_id', None)).first()
    if not original or original.state != BudgetReservation.State.SETTLED:
        blockers.append('The parent execution must have a settled reservation before recovery.')
    if policy is None and original:
        policy = original.policy
    headroom = None
    if (not policy or policy.tenant_id != run.tenant_id or not check_resource_access(policy, run.project_id, run.tenant_id)
            or not policy.enabled or policy.unit != 'training_steps' or policy.currency):
        blockers.append('Select an enabled, accessible quantity budget in training_steps.')
    else:
        _, committed = BudgetReservation.current_commitment(policy)
        headroom = policy.limit_amount - committed
        if headroom < remaining:
            blockers.append('The selected budget cannot reserve the remaining optimizer steps.')
    child = TrainingRun.all_objects.filter(recovery_parent=run).first()
    if child:
        blockers.append('A recovery execution already exists; open it instead of restarting this parent.')
    return {'available': not blockers, 'blocked_by': blockers, 'checkpoint_id': str(checkpoint.checkpoint_id) if checkpoint else None,
        'step': run.current_step, 'remaining_steps': max(0, remaining), 'pins': pins,
        'policy_id': str(policy.policy_id) if policy else None, 'headroom': str(headroom) if headroom is not None else None,
        'recovery_run_id': str(child.run_id) if child else None,
        'replay_limits': 'Resume the latest committed cursor with identical pinned bytes, build, optimizer and sample order. Uncommitted computation may be repeated; committed steps are never charged twice.'}


@transaction.atomic
def resume_training(run, *, checkpoint_id, policy_id):
    # Terminal parent job first, matching the worker's job -> run lock order.
    if run.job_id:
        Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=run.tenant_id)
    parent = TrainingRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
    policy = BudgetPolicy.all_objects.select_for_update().filter(tenant_id=run.tenant_id, policy_id=policy_id).first()
    if policy is None:
        raise ValueError('The selected budget policy is unavailable.')
    existing = TrainingRun.all_objects.filter(recovery_parent=parent).first()
    if existing:
        reservation = BudgetReservation.all_objects.get(reservation_id=existing.resource_reservation_id)
        if str(existing.recovery_checkpoint.checkpoint_id) != str(checkpoint_id) or str(reservation.policy.policy_id) != str(policy_id):
            raise ValueError('Recovery already exists with different inputs.')
        return existing, False
    review = recovery_review(parent, policy=policy)
    if not review['available'] or str(checkpoint_id) != review['checkpoint_id']:
        raise ValueError(' '.join(review['blocked_by']) or 'Select the latest checkpoint at the committed cursor.')
    checkpoint = parent.checkpoints.select_for_update().get(checkpoint_id=checkpoint_id)
    config = deepcopy(parent.hardware_config)
    config['recovery'] = {'parent_run_id': str(parent.run_id), 'checkpoint_id': str(checkpoint.checkpoint_id),
        'checkpoint_digest': checkpoint.state_digest, 'start_step': checkpoint.step}
    child = TrainingRun.all_objects.create(tenant_id=parent.tenant_id, project_id=parent.project_id,
        recipe_type=parent.recipe_type, base_model_version=parent.base_model_version, tokenizer_version=parent.tokenizer_version,
        dataset_revision=parent.dataset_revision, dataset_manifest_digest=parent.dataset_manifest_digest,
        pool=parent.pool, hyperparameters=deepcopy(parent.hyperparameters), hardware_config=config,
        initialization_seed=parent.initialization_seed, total_steps=parent.total_steps, current_step=checkpoint.step,
        latest_loss=parent.latest_loss, recovery_parent=parent, recovery_checkpoint=checkpoint)
    job = Job.all_objects.create(tenant_id=parent.tenant_id, pool=parent.pool, name=f'Resume {parent.run_id} at step {checkpoint.step}',
        payload={'type': 'qualified_training', 'run_id': str(child.run_id)}, requirements=deepcopy(parent.job.requirements), max_attempts=3)
    reservation = BudgetReservation.reserve(tenant_id=parent.tenant_id, policy=policy, job_id=job.job_id,
        estimated_amount=review['remaining_steps'])
    child.job, child.resource_reservation_id = job, reservation.reservation_id
    child.save(update_fields=['job', 'resource_reservation_id', 'updated_at'])
    state = deepcopy(checkpoint.weights_manifest)
    state.update(run_id=str(child.run_id), recovery_source=config['recovery'])
    TrainingCheckpoint.all_objects.create(tenant_id=parent.tenant_id, training_run=child, step=checkpoint.step,
        state_digest=runtime.digest(state), weights_manifest=state, metrics=deepcopy(checkpoint.metrics))
    return child, True
