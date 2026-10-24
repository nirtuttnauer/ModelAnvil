"""Fresh GPU claim validation before attempt/device/worker capacity is reserved."""
from modelanvil.device_admission import device_available,device_key


def gpu_claim_plan(job,worker):
    if isinstance(job.payload,dict) and job.payload.get('type')=='qualified_tool_chat':
        from modelanvil.runners.tool_jobs import gpu_claim_plan as tools_claim_plan
        return tools_claim_plan(job,worker)
    if isinstance(job.payload,dict) and job.payload.get("type")=="qualified_audio_generation":
        from modelanvil.runners.audio_generation import gpu_claim_plan as audio_claim_plan
        return audio_claim_plan(job,worker)
    if isinstance(job.payload, dict) and job.payload.get('type') == 'qualified_rlhf':
        from modelanvil.runners.alignment.hf_rlhf import gpu_claim_plan as rlhf_claim_plan
        return rlhf_claim_plan(job, worker)
    if isinstance(job.payload, dict) and job.payload.get('type') == 'qualified_dpo':
        from modelanvil.runners.alignment.mps_dpo import gpu_claim_plan as dpo_claim_plan
        return dpo_claim_plan(job, worker)
    if not isinstance(job.payload,dict) or job.payload.get('type')!='qualified_training':
        return None
    from modelanvil.runners.models import TrainingRun
    from modelanvil.runners.training.registry import runtime_module
    import uuid
    try:run_id=uuid.UUID(str(job.payload.get('run_id')))
    except (ValueError,TypeError):raise ValueError('Training payload needs its pinned run ID.') from None
    run=TrainingRun.all_objects.filter(job=job,tenant_id=worker.tenant_id,run_id=run_id).first()
    if run is None:
        raise ValueError('Qualified training requires its matching tenant-scoped run.')
    pins=run.hardware_config.get('pins',{})
    if not pins.get('accelerator'):
        return None
    module=runtime_module(pins.get('runtime'))
    if (module is None or pins.get('worker_id')!=worker.pk or pins.get('contract_digest')!=module.CONTRACT_DIGEST
            or pins.get('build_digest')!=module.build_digest() or not module.capable_worker(worker)
            or job.project_id!=run.project_id):
        raise ValueError('GPU worker, runtime build, project or contract changed; preview and launch again.')
    module.require_packages()
    observed=module.observed_device(worker.capabilities['gpu_device'])
    if observed!=pins['accelerator']:
        raise ValueError('GPU placement, host, framework or capacity changed after launch.')
    from modelanvil.budgets.models import BudgetReservation
    reservation=BudgetReservation.all_objects.select_related('policy').filter(reservation_id=run.resource_reservation_id,
        tenant_id=run.tenant_id,job_id=job.job_id,state='reserved').first()
    if reservation:
        from modelanvil.budgets.models import BudgetPolicy
        reservation.policy=BudgetPolicy.all_objects.select_for_update().get(pk=reservation.policy_id,tenant_id=run.tenant_id)
    period,committed=BudgetReservation.current_commitment(reservation.policy) if reservation else (None,None)
    if (reservation is None or period!=reservation.period_start or not reservation.policy.enabled or reservation.policy.unit!='training_steps' or reservation.policy.currency
            or reservation.estimated_amount!=run.total_steps
            or committed>reservation.policy.limit_amount):
        raise ValueError('GPU training budget is no longer authorized.')
    selector=observed['device']['id']
    if not device_available(selector):
        raise ValueError('The selected physical GPU is busy in a cooperating process.')
    return {'host_key':observed['host_key'],'device_key':device_key(selector)}
