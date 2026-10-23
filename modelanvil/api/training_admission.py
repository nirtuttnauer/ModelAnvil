"""Shared validated training admission for individual runs and reviewed campaigns."""
from rest_framework import serializers
from modelanvil.core.models import record_audit
from modelanvil.core.tenancy import get_active_tenant, get_active_project


def training_preflight(attrs, *, lock_budget=False):
    from modelanvil.runners.training.preflight_report import build_preflight_report
    from modelanvil.budgets.models import BudgetPolicy
    tenant = get_active_tenant()
    project = get_active_project() or getattr(attrs.get('project'), 'pk', None) or getattr(attrs.get('base_model_version'), 'project_id', None)
    policies = BudgetPolicy.all_objects.filter(tenant_id=tenant, policy_id=attrs.get('budget_policy_id'))
    policy = (policies.select_for_update() if lock_budget else policies).first()
    report = build_preflight_report(recipe_type=attrs.get('recipe_type', 'full_sft'),
        tokenizer_version=attrs.get('tokenizer_version'), base_model_version=attrs.get('base_model_version'),
        dataset_revision=attrs.get('dataset_revision'), pool=attrs.get('pool'), runner=attrs.get('runner_manifest'),
        total_steps=attrs.get('total_steps', 100), budget_policy=policy,
        execution_mode=attrs.get('execution_mode', 'worker'), tenant=tenant, project=project,
        initialization_seed=attrs.get('initialization_seed', 42), hyperparameters=attrs.get('hyperparameters', {}))
    return report, policy


def admit_training(serializer, request):
    from modelanvil.budgets.models import BudgetReservation
    from modelanvil.jobs.models import Job
    attrs = serializer.validated_data
    proof = attrs.pop('preflight_token', None)
    setup_check = bool(attrs.pop('setup_check', False))
    purpose = attrs.pop('purpose', 'experiment')
    if purpose == 'pilot' and (attrs.get('execution_mode', 'worker') != 'worker' or attrs.get('total_steps', 100) > 10):
        raise serializers.ValidationError('Measured pilots require a real worker execution of at most 10 optimizer steps.')
    mode = attrs.get('execution_mode', 'worker')
    tenant = get_active_tenant()
    project = get_active_project() or getattr(attrs.get('project'), 'pk', None) or getattr(attrs.get('base_model_version'), 'project_id', None)
    pins = None
    if mode == 'worker':
        from modelanvil.runners.training.preflight_report import verify_token
        report, policy = training_preflight(attrs, lock_budget=True)
        if report['status'] != 'approved':
            raise serializers.ValidationError({'preflight': [f"{c['check']}: {c['reason']} {c['corrective_action']}" for c in report['checks'] if c['blocking']]})
        if proof:
            try:
                verify_token(proof, report, request.user.pk)
            except ValueError as exc:
                raise serializers.ValidationError({'preflight_token': str(exc)}) from exc
        pins = report['pins']
        if attrs.get('estimated_amount') is not None and attrs['estimated_amount'] != pins['steps']:
            raise serializers.ValidationError({'estimated_amount': 'Reservation must equal the requested sample passes.'})
    budget_id = attrs.pop('budget_policy_id', None)
    attrs.pop('estimated_amount', None)
    attrs.pop('execution_mode', None)
    runner = attrs.pop('runner_manifest', None)
    if mode == 'simulation' and (attrs.get('pool') or budget_id or runner):
        raise serializers.ValidationError('Simulation cannot allocate workers or reserve compute budget.')
    run = serializer.save(tenant_id=tenant, project_id=project,
        hardware_config={'execution_mode': mode, 'purpose': purpose, 'setup_check': setup_check, **({'pins': pins} if pins else {})})
    if pins:
        gpu = pins.get('accelerator', {}).get('device')
        requirements = {'training_runtime': pins['contract_digest'], 'slots': 1}
        if gpu:
            requirements.update(gpu_backend=gpu['backend'], gpu_device=gpu['id'])
        job = Job.objects.create(tenant_id=tenant, project_id=project, pool=run.pool, name=f'{run.recipe_type}: {run.run_id}',
            payload={'type': 'qualified_training', 'run_id': str(run.run_id)},
            requirements=requirements, max_attempts=3)
        try:
            reservation = BudgetReservation.reserve(tenant_id=tenant, policy=policy,
                job_id=job.job_id, estimated_amount=pins['steps'])
        except ValueError as exc:
            raise serializers.ValidationError({'budget_policy_id': str(exc)}) from exc
        run.job = job
        run.resource_reservation_id = reservation.reservation_id
        run.save(update_fields=['job', 'resource_reservation_id', 'updated_at'])
    record_audit('training.launch', 'training_run', run.run_id,
        actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
        input_snapshot={'job_id': str(run.job.job_id) if run.job else None, 'recipe': run.recipe_type,
            'total_steps': run.total_steps, 'execution_mode': mode})
    return run
