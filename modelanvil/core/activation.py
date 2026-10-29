"""Local activation reporting. Client timing never establishes model improvement."""
from datetime import datetime, timedelta, timezone as utc

from django.db import transaction
from django.utils import timezone

from modelanvil.core.models import ActivationEvent, ImprovementDecision, record_audit
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.models import EvaluationRun, ModelImport, TrainingRun
from modelanvil.runners.training.runtime import digest


def comparison_evidence(run, project):
    """Verify server-owned durable execution and current access to its inputs."""
    from modelanvil.runners.eval_worker import verified_evaluation_inputs
    from modelanvil.runners.evidence import training_evidence

    if (run.status != 'completed' or not run.job_id or run.job.status != 'succeeded'
            or run.protocol_ref.get('execution_evidence', {}).get('level') != 'integrated_execution'
            or not run.baseline_model_version_id or run.baseline_model_version_id == run.candidate_model_version_id):
        raise ValueError('Complete a durable comparison of a trained candidate and a distinct baseline first.')
    resources = (run, run.candidate_model_version, run.baseline_model_version, run.suite_version, run.job)
    if any(not check_resource_access(resource, project.pk, project.tenant_id) for resource in resources):
        raise ValueError('Comparison inputs are unavailable in this project.')
    training = TrainingRun.all_objects.filter(tenant_id=project.tenant_id,
        output_model_version=run.candidate_model_version, status='completed', job__status='succeeded').first()
    if not training or not check_resource_access(training, project.pk, project.tenant_id):
        raise ValueError('The candidate needs actual completed worker training evidence.')
    config = training.hardware_config or {}
    if config.get('execution_mode') == 'simulation':
        raise ValueError('A synthetic training fixture cannot be accepted as an improvement.')
    if config.get('setup_check'):
        raise ValueError('A three-step setup check cannot be accepted as an improvement.')
    if training_evidence(training)['level'] != 'integrated_execution':
        raise ValueError('The candidate needs actual completed worker training evidence.')
    pins = run.protocol_ref.get('pins', {})
    if not pins or verified_evaluation_inputs(run)['pins'] != pins:
        raise ValueError('Comparison inputs or runtime no longer match their frozen evidence.')
    expected = {case['case_id'] for case in run.suite_version.cases}
    rows = list(run.case_results.order_by('case_id').values('case_id', 'passed', 'score', 'candidate_output'))
    baseline = run.protocol_ref.get('baseline_results', [])
    if (not expected or len(rows) != len(expected) or {r['case_id'] for r in rows} != expected
            or len(baseline) != len(expected) or {r.get('case_id') for r in baseline} != expected
            or any(type(r.get('passed')) is not bool for r in baseline)):
        raise ValueError('Every candidate and baseline case must have a committed result.')
    accuracy = sum(r['passed'] for r in rows) / len(rows)
    base_accuracy = sum(r['passed'] for r in baseline) / len(baseline)
    return training, digest({'pins': pins, 'candidate': rows,
        'baseline': sorted(baseline, key=lambda r: r['case_id'])}), accuracy, base_accuracy


@transaction.atomic
def record_decision(run, project, outcome, actor_id):
    # Serialize submissions from different tabs before deciding whether this is a replay.
    run = EvaluationRun.all_objects.select_for_update().get(pk=run.pk, tenant_id=project.tenant_id)
    training, evidence_digest, accuracy, baseline = comparison_evidence(run, project)
    current = ImprovementDecision.all_objects.filter(tenant_id=project.tenant_id, project=project, evaluation=run).first()
    if current:
        if current.outcome != outcome or current.evidence_digest != evidence_digest:
            raise ValueError('This comparison already has an immutable decision. Run a new comparison to record another.')
        return current, False
    decision = ImprovementDecision.all_objects.create(tenant_id=project.tenant_id, project=project,
        evaluation=run, training=training, outcome=outcome, evidence_digest=evidence_digest,
        candidate_accuracy=accuracy, baseline_accuracy=baseline,
        accepted_improvement=outcome == 'accept' and accuracy > baseline)
    record_audit('create', 'improvement_decision', decision.decision_id, tenant_id=project.tenant_id,
        actor_id=actor_id, actor_kind='user', input_snapshot={'outcome': outcome, 'evaluation': str(run.run_id)})
    return decision, True


def job_timing(job):
    """Attempt wall time includes loading and checkpointing; it is not GPU kernel time."""
    attempts = list(job.attempts.order_by('started_at'))
    if not attempts:
        return {'queue_seconds': None, 'execution_seconds': None}
    queue = max(0, (attempts[0].started_at - job.created_at).total_seconds())
    execution = (sum(max(0, (a.completed_at - a.started_at).total_seconds()) for a in attempts)
                 if all(a.completed_at for a in attempts) else None)
    return {'queue_seconds': queue, 'execution_seconds': execution}


def evaluation_resources(run):
    """Observed wall times and committed ledger units, without estimated GPU usage or prices."""
    from modelanvil.budgets.models import UsageEvent

    def measured(job):
        if job is None:
            return {'queue_seconds': None, 'execution_seconds': None, 'usage_available': False, 'usage': []}
        events = UsageEvent.all_objects.filter(tenant_id=run.tenant_id, reservation__job_id=job.job_id).order_by('pk')
        usage = [{'quantity': str(event.quantity), 'unit': event.unit,
                  'amount': str(event.net_amount()) if event.amount is not None else None,
                  'currency': event.currency or None} for event in events]
        return {**job_timing(job), 'usage_available': bool(usage), 'usage': usage}

    training = TrainingRun.all_objects.filter(tenant_id=run.tenant_id, output_model_version=run.candidate_model_version,
        status='completed').select_related('job').first()
    if training and not check_resource_access(training, run.project_id, run.tenant_id):
        training = None
    return {'evaluation': measured(run.job if run.job_id else None),
            'training': measured(training.job if training and training.job_id else None),
            'peak_memory_bytes': None,
            'basis': 'Attempt wall time includes model loading and checkpointing. Usage is committed ledger units, with recorded cost adjustments when priced. Peak memory and unpriced cost are unavailable, not zero.'}


def activation_report(tenant, project=None, week=None):
    date = week or timezone.now().date()
    start = datetime.combine(date - timedelta(days=date.weekday()), datetime.min.time(), tzinfo=utc.utc)
    end = start + timedelta(days=7)
    decisions = ImprovementDecision.all_objects.filter(tenant_id=tenant).select_related(
        'project', 'evaluation__candidate_model_version', 'evaluation__baseline_model_version', 'evaluation__suite_version',
        'evaluation__job', 'training__job')
    events = ActivationEvent.all_objects.filter(tenant_id=tenant)
    imports = ModelImport.all_objects.filter(tenant_id=tenant).select_related('job')
    if project:
        decisions = decisions.filter(project=project)
        events = events.filter(project=project)
        imports = imports.filter(project=project)
    # A changed/revoked input cannot continue to contribute to the primary metric.
    valid = []
    for decision in decisions.filter(created_at__gte=start, created_at__lt=end).order_by('created_at', 'pk'):
        try:
            _, current_digest, _, _ = comparison_evidence(decision.evaluation, decision.project)
        except (ValueError, KeyError, TypeError):
            continue
        if current_digest == decision.evidence_digest:
            valid.append(decision)
    unique = {}
    for decision in valid:
        key = (decision.project.team_id, decision.evaluation.candidate_model_version_id, decision.evaluation_id)
        unique.setdefault(key, decision)
    measured = events.filter(created_at__gte=start, created_at__lt=end)
    first_open = events.filter(kind='workspace_opened').order_by('created_at').first()
    first_decision = decisions.order_by('created_at').first()
    elapsed = (max(0, (first_decision.created_at - first_open.created_at).total_seconds())
               if first_open and first_decision else None)
    return {
        'scope': 'project' if project else 'tenant', 'week_start': start.isoformat(), 'week_end': end.isoformat(),
        'storage': 'installation_database', 'external_analytics': 'disabled',
        'weekly_teams_with_decisions': len({key[0] for key in unique}),
        'weekly_improvement_cycles': len(unique),
        'weekly_accepted_improvements': sum(d.accepted_improvement for d in unique.values()),
        'weekly_rejected_candidates': sum(d.outcome == 'reject' for d in unique.values()),
        'workspace_sessions': measured.filter(kind='workspace_opened').values('session_id', 'project_id').distinct().count(),
        'reported_active_seconds': sum(measured.values_list('active_milliseconds', flat=True)) / 1000,
        'time_to_first_decision_seconds': elapsed if project else None,
        'timing_basis': 'Browser-reported interaction time; server attempt wall time includes loading and checkpointing. Missing timings stay null.',
        'decisions': [{'decision_id': str(d.decision_id), 'evaluation_run': str(d.evaluation.run_id),
            'candidate': str(d.evaluation.candidate_model_version.model_version_id), 'outcome': d.outcome,
            'accepted_improvement': d.accepted_improvement,
            'training': job_timing(d.training.job), 'evaluation': job_timing(d.evaluation.job)} for d in unique.values()],
        'model_acquisition': [{'import_id': str(item.import_id), **job_timing(item.job)}
            for item in imports.filter(created_at__gte=start, created_at__lt=end) if item.job_id],
    }
