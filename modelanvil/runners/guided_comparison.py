"""Held-out or confirmed-question comparison for one completed guided training run."""
from django.db import transaction

from modelanvil.api.resource_inspection import prepared_manifest
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.runners.eval_executor import validate_local_suite
from modelanvil.runners.evidence import training_evidence
from modelanvil.runners.models import EvaluationRun, EvaluationSuite, EvaluationSuiteVersion


METRIC = ('Accuracy is the share of cases whose generated answer equals the expected answer after trimming whitespace. '
          'An accept counts as an improvement only when candidate accuracy is higher than the base model. '
          'Recording a choice does not deploy the model.')


def cases_from_manifest(prepared):
    """Prefer the test split, then validation. Plain rows without a question and answer are skipped."""
    splits = prepared.get('split_manifest') or {}
    held = list(splits.get('test') or []) or list(splits.get('validation') or [])
    rows = {row.get('sample_id'): row for row in prepared.get('rows') or []}
    cases = []
    for sample_id in held:
        row = rows.get(sample_id) or {}
        blocks = row.get('blocks') or []
        user = next((block.get('text') for block in blocks if block.get('role') == 'user' and isinstance(block.get('text'), str)), None)
        assistant = next((block.get('text') for block in blocks if block.get('role') == 'assistant' and isinstance(block.get('text'), str)), None)
        metadata = row.get('metadata') or {}
        user = user or metadata.get('input_text')
        assistant = assistant or metadata.get('label')
        if not isinstance(user, str) or not isinstance(assistant, str):
            continue
        user, assistant = user.strip(), assistant.strip()
        if not user or not assistant or len(user) > 1024 or len(assistant) > 4096:
            continue
        cases.append({'case_id': str(sample_id)[:128], 'input_prompt': user, 'expected_output': assistant,
                      'slice': 'held_out', 'sample_id': sample_id, 'source_group_id': row.get('source_group_id') or sample_id})
        if len(cases) == 64:
            break
    return cases


def normalize_questions(questions):
    if not isinstance(questions, list) or not questions:
        raise ValueError('Confirm 1–64 questions, each with the answer you expect.')
    cases = []
    for index, question in enumerate(questions, 1):
        if not isinstance(question, dict):
            raise ValueError('Each question needs a prompt and an expected answer.')
        prompt = question.get('input_prompt')
        expected = question.get('expected_output')
        if not isinstance(prompt, str) or not isinstance(expected, str) or not prompt.strip() or not expected.strip():
            raise ValueError('Each question needs a prompt and an expected answer.')
        cases.append({'case_id': f'question-{index}', 'input_prompt': prompt.strip(),
                      'expected_output': expected.strip(), 'slice': 'confirmed'})
    validate_local_suite(cases, 'exact_match', {})
    return cases


def _guard(run):
    if run.status != 'completed' or not run.job_id or run.job.status != 'succeeded' or not run.output_model_version_id or not run.base_model_version_id:
        raise ValueError('Finish a real training run that produced a candidate and kept its base model.')
    if run.output_model_version_id == run.base_model_version_id:
        raise ValueError('The candidate and base model must be different versions.')
    config = run.hardware_config or {}
    if config.get('execution_mode') == 'simulation' or training_evidence(run)['level'] == 'simulation':
        raise ValueError('A synthetic training fixture cannot be accepted as an improvement.')
    if config.get('setup_check'):
        raise ValueError('A three-step setup check cannot be accepted as an improvement.')
    if training_evidence(run)['level'] != 'integrated_execution':
        raise ValueError('Only a completed worker-backed training run can be compared.')
    if not run.dataset_revision_id:
        raise ValueError('This run has no published dataset to compare against.')


def held_out_cases(run):
    _guard(run)
    return cases_from_manifest(prepared_manifest(run.dataset_revision))


def existing_comparison(run):
    return EvaluationRun.all_objects.filter(tenant_id=run.tenant_id, project_id=run.project_id,
        candidate_model_version=run.output_model_version, baseline_model_version=run.base_model_version,
        protocol_ref__training_run=str(run.run_id)).order_by('-created_at').first()


def comparison_preview(run):
    try:
        cases = held_out_cases(run)
        reason = ''
        eligible = True
    except ValueError as exc:
        cases, reason, eligible = [], str(exc), False
    current = existing_comparison(run) if run.output_model_version_id else None
    return {'eligible': eligible, 'reason': reason, 'setup_check': bool((run.hardware_config or {}).get('setup_check')),
            'synthetic': (run.hardware_config or {}).get('execution_mode') == 'simulation' or training_evidence(run)['level'] == 'simulation',
            'held_out_count': len(cases), 'held_out_preview': cases[:5], 'metric': METRIC,
            'existing_run_id': str(current.run_id) if current else None,
            'existing_status': current.status if current else None}


def _evaluation_policy(tenant):
    policy, _ = BudgetPolicy.all_objects.get_or_create(tenant_id=tenant, name='Guided evaluation allowance',
        defaults={'unit': 'evaluation_cases', 'period': 'lifetime', 'limit_amount': 1000})
    if not policy.enabled or policy.unit != 'evaluation_cases' or policy.currency:
        raise ValueError('The guided evaluation allowance is paused. Ask the workspace owner to enable an evaluation_cases policy.')
    return policy


@transaction.atomic
def queue_guided_comparison(run, *, questions=None, confirm=False, max_tokens=32):
    if confirm is not True:
        raise ValueError('Confirm the questions before comparing the candidate with the base model.')
    _guard(run)
    current = existing_comparison(run)
    if current and current.status in ('pending', 'running', 'completed') and current.job_id:
        return current, False
    cases = normalize_questions(questions) if questions else held_out_cases(run)
    if not cases:
        raise ValueError('This dataset has no held-out questions. Confirm a short list of questions and the answers you expect.')
    from modelanvil.runners.eval_worker import queue_evaluation
    from modelanvil.runners.training.managed import host_status, refresh_evaluation_capabilities
    from modelanvil.runners.models import LocalTrainingHost
    from modelanvil.jobs.models import Worker
    if not run.pool_id or run.pool.status != 'active':
        raise ValueError('The training pool is unavailable. Restart local training and try the comparison again.')
    status = host_status()
    managed = Worker.all_objects.filter(tenant_id=run.tenant_id, pool=run.pool, capabilities__managed_local=True)
    if managed.exists():
        if not status['available']:
            raise ValueError(status['message'])
        host = LocalTrainingHost.objects.filter(name='local').first()
        for worker in managed:
            if host:
                refresh_evaluation_capabilities(worker, host)
    suite_name = f'Guided comparison {run.run_id}'
    suite = EvaluationSuite.all_objects.filter(tenant_id=run.tenant_id, name=suite_name).first()
    if suite is None:
        suite = EvaluationSuite.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id, name=suite_name,
            description='Confirmed comparison for one guided candidate and its base model.')
    version = suite.versions.order_by('-revision_no').first()
    if version is None or version.cases != cases:
        revision_no = (version.revision_no + 1) if version else 1
        version = EvaluationSuiteVersion.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id, suite=suite,
            revision_no=revision_no, cases=cases, scorer_type='exact_match', scorer_config={}, protected_role='held_out')
    evaluation = EvaluationRun.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id, suite_version=version,
        candidate_model_version=run.output_model_version, baseline_model_version=run.base_model_version, status='pending')
    policy = _evaluation_policy(run.tenant_id)
    queue_evaluation(evaluation, pool=run.pool, policy=policy, max_tokens=max_tokens)
    evaluation.protocol_ref['training_run'] = str(run.run_id)
    evaluation.protocol_ref['case_source'] = 'confirmed_questions' if questions else 'held_out'
    evaluation.save(update_fields=['protocol_ref', 'updated_at'])
    return evaluation, True
