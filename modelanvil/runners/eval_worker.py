"""Pinned CPU inference with per-case fenced commits and durable accounting."""
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.budgets.models import BudgetReservation, UsageEvent
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Job, JobAttempt, OutboxEvent, Worker, dispatch_topic
from modelanvil.runners.eval_executor import _aggregate_metrics, default_eval_scorer, validate_local_suite
from modelanvil.runners.models import EvaluationCaseResult, EvaluationMetric, EvaluationRun
from modelanvil.runners.training.runtime import digest

RUNTIME_ID = 'modelanvil.local-cpu-evaluation.v1'
CONTRACT = {'runtime': RUNTIME_ID, 'cases': 64, 'max_tokens': 32, 'decoding': 'greedy', 'formats': ['plain', 'native_template']}
CONTRACT_DIGEST = digest(CONTRACT)
BUILD_DIGEST = hashlib.sha256(b''.join((Path(__file__).parent / name).read_bytes()
    for name in ('eval_worker.py', 'eval_executor.py', 'local_execution.py', 'inference.py',
        'training/runtime.py', 'training/general_runtime.py', 'training/general_transformer.py',
        'training/autograd.py', 'training/engine.py', 'training/registry.py', 'training/hf_runtime.py'))).hexdigest()
MEMORY_BYTES = 512 * 1024 * 1024


def model_inputs(version, tenant, project):
    from modelanvil.runners.training import runtime, general_runtime
    from modelanvil.runners.local_execution import load_reference_bundle
    from modelanvil.runners.inference import snapshot, verified_artifact
    if version.architecture_ref in (runtime.RUNTIME_ID, general_runtime.RUNTIME_ID):
        bundle, artifact, _ = load_reference_bundle(version, tenant=tenant, project=project)
        return {'kind': 'reference', 'device': 'cpu', 'bundle': bundle,
                'pins': {'version': str(version.model_version_id), 'artifact_id': str(artifact.artifact_id),
                         'sha256': artifact.sha256, 'tokenizer': str(version.tokenizer.tokenizer_id)}}
    from modelanvil.runners.capabilities import model_capabilities
    capability = model_capabilities(version)['chat']
    if not capability['eligible']:
        raise ValueError(capability.get('reason') or 'Select a loadable snapshot or supported reference bundle for evaluation.')
    plan = snapshot(version, tenant, project)
    if plan['format'] != 'safetensors':
        raise ValueError('This evaluation profile currently supports CPU reference and Safetensors snapshots.')
    devices = capability.get('devices') or []
    if plan.get('guided_large'):
        device = next((item for item in devices if str(item).startswith('mps')), None)
        if device is None:
            raise ValueError('The 1.7B guided candidate evaluates on the Apple GPU used for training.')
    elif 'cpu' in devices:
        device = 'cpu'
    else:
        raise ValueError('Select a CPU-loadable snapshot or supported CPU reference bundle for evaluation.')
    files = {name: {'sha256': verified_artifact(ref, tenant, project).sha256, 'byte_size': ref['byte_size']}
             for name, ref in plan['files'].items()}
    return {'kind': 'snapshot', 'device': device, 'pins': {'version': str(version.model_version_id),
            'artifact_id': str(version.artifact_manifest_id), 'tokenizer': str(version.tokenizer.tokenizer_id), 'files': files}}


def check_training_overlap(run):
    """Check known actual lineage; absent external provenance stays disclosed."""
    from modelanvil.runners.models import TrainingRun
    from modelanvil.runners.training.runtime import read_artifact
    cases = run.suite_version.cases
    known = False
    for version in (run.candidate_model_version, run.baseline_model_version):
        if version is None:
            continue
        seen = set()
        while version and version.pk not in seen:
            if len(seen) >= 32:
                raise ValueError('Training lineage exceeds this bounded evaluation inspection.')
            seen.add(version.pk)
            training = TrainingRun.all_objects.filter(tenant_id=run.tenant_id, output_model_version=version).first()
            if training is None:
                break
            dataset = training.dataset_revision
            if dataset is None or not dataset.manifest_artifact or not check_resource_access(dataset, run.project_id, run.tenant_id):
                raise ValueError('Known training inputs are unavailable for overlap checking.')
            raw = read_artifact(dataset.manifest_artifact, run.tenant_id, run.project_id)
            if hashlib.sha256(raw).hexdigest() != dataset.manifest_digest:
                raise ValueError('Known training manifest no longer matches its pinned digest.')
            prepared = json.loads(raw)
            train_ids = set(prepared['split_manifest']['train'])
            rows = [r for r in prepared['rows'] if r['sample_id'] in train_ids]
            groups = {r['source_group_id'] for r in rows}
            texts = {'\n'.join(b['text'] for b in r['blocks'] if b['type'] == 'text') for r in rows}
            if any(c.get('sample_id') in train_ids or c.get('source_group_id') in groups or c['input_prompt'] in texts for c in cases):
                raise ValueError('Evaluation cases overlap known training samples or source groups.')
            known = True
            version = training.base_model_version
    return 'known_lineage_checked' if known else 'external_training_history_unknown'


def evaluation_prompt_format(run):
    """Guided chat snapshots are scored through their native template, not raw prompt text."""
    from modelanvil.runners.training import hf_runtime
    versions = [run.candidate_model_version]
    if run.baseline_model_version_id:
        versions.append(run.baseline_model_version)
    if any(version.architecture_ref != hf_runtime.RUNTIME_ID or not getattr(version.tokenizer, 'chat_template', '') for version in versions):
        return 'plain'
    return 'native_template'


def resolve_inputs(run, max_tokens):
    validate_local_suite(run.suite_version.cases, run.suite_version.scorer_type, run.suite_version.scorer_config)
    if not check_resource_access(run.suite_version, run.project_id, run.tenant_id):
        raise ValueError('The evaluation suite is unavailable in this project.')
    candidate = model_inputs(run.candidate_model_version, run.tenant_id, run.project_id)
    baseline = model_inputs(run.baseline_model_version, run.tenant_id, run.project_id) if run.baseline_model_version_id else None
    if baseline and run.baseline_model_version.tokenizer_id != run.candidate_model_version.tokenizer_id:
        raise ValueError('Use candidate and baseline versions with the same pinned tokenizer.')
    if baseline and baseline['device'] != candidate['device']:
        raise ValueError('Candidate and baseline must evaluate on the same device.')
    if type(max_tokens) is not int or not 1 <= max_tokens <= 32:
        raise ValueError('Choose 1–32 generated tokens per case.')
    prompt_format = evaluation_prompt_format(run)
    if prompt_format == 'native_template' and (candidate['kind'] != 'snapshot' or (baseline and baseline['kind'] != 'snapshot')):
        raise ValueError('Native-template comparison requires Safetensors snapshots for the candidate and baseline.')
    from modelanvil.runners.training import runtime, general_runtime
    for inputs in (candidate, baseline):
        if inputs and inputs['kind'] == 'reference':
            bundle = inputs['bundle']
            module = general_runtime if bundle['config.json'].get('runtime') == general_runtime.RUNTIME_ID else runtime
            for case in run.suite_version.cases:
                encoded = module.encode(case['input_prompt'], bundle['tokenizer_config.json'])
                if len(encoded) + max_tokens > bundle['config.json'].get('context_window', 64):
                    raise ValueError('A case prompt and output exceed the selected reference context limit.')
        elif inputs:
            from modelanvil.runners.inference import rendered_prompt, snapshot, staged_snapshot
            from transformers import AutoTokenizer
            version = run.candidate_model_version if inputs is candidate else run.baseline_model_version
            plan = snapshot(version, run.tenant_id, run.project_id)
            tokenizer_files = {name: ref for name, ref in plan['files'].items()
                               if not name.endswith(('.safetensors', '.gguf'))}
            with staged_snapshot(tokenizer_files, run.tenant_id, run.project_id) as directory:
                config = json.loads((directory / 'config.json').read_text())
                tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
                limit = min(2048, config.get('max_position_embeddings', 2048))
                for case in run.suite_version.cases:
                    if prompt_format == 'native_template':
                        prompt = rendered_prompt(tokenizer, [{'role': 'user', 'content': case['input_prompt']}], 'model')
                        encoded_len = len(tokenizer.encode(prompt, add_special_tokens=False))
                    else:
                        encoded_len = len(tokenizer.encode(case['input_prompt'], add_special_tokens=True))
                    if encoded_len + max_tokens > limit:
                        raise ValueError('A case prompt and output exceed the selected snapshot context limit.')
    return {'candidate': candidate, 'baseline': baseline, 'pins': {
        'runtime': RUNTIME_ID, 'build_digest': BUILD_DIGEST, 'candidate': candidate['pins'],
        'baseline': baseline['pins'] if baseline else None,
        'suite_digest': digest({'cases': run.suite_version.cases, 'scorer': run.suite_version.scorer_type,
                              'config': run.suite_version.scorer_config}),
        'max_tokens': max_tokens, 'decoding': 'greedy', 'prompt_format': prompt_format, 'device': candidate['device'],
        'training_overlap': check_training_overlap(run)}}


@transaction.atomic
def queue_evaluation(run, *, pool, policy, max_tokens):
    request = {'pool': pool.pk, 'budget_policy_id': str(policy.policy_id), 'max_tokens': max_tokens}
    if run.job_id:
        if run.protocol_ref.get('execution_request') != request:
            raise ValueError('This evaluation already has a different frozen execution request.')
        return run
    if run.status != 'pending':
        raise ValueError('Only an unexecuted pending evaluation can be queued.')
    inputs = resolve_inputs(run, max_tokens)
    if pool.tenant_id != run.tenant_id or pool.status != 'active':
        raise ValueError('Select an active evaluation pool in this organization.')
    from modelanvil.jobs.setup import connection_state
    device = inputs['pins']['device']
    workers = Worker.all_objects.filter(tenant_id=run.tenant_id, pool=pool, status='available', slots__gte=1)
    if not any(_worker_can_evaluate(w, device, connection_state) for w in workers):
        raise ValueError('Connect an installed evaluation worker with matching runtime, device and sufficient memory.')
    if policy.tenant_id != run.tenant_id or policy.unit != 'evaluation_cases' or policy.currency:
        raise ValueError('Select an enabled evaluation_cases quantity budget.')
    job_id = uuid7()
    BudgetReservation.reserve(tenant_id=run.tenant_id, policy=policy, job_id=job_id,
                              estimated_amount=len(run.suite_version.cases))
    job = Job.all_objects.create(tenant_id=run.tenant_id, job_id=job_id, pool=pool,
        name=f'Evaluation {str(run.run_id)[:8]}', requirements={'slots': 1,
            'evaluation_runtime': CONTRACT_DIGEST, 'evaluation_build': BUILD_DIGEST,
            **({} if device == 'cpu' else {'gpu_backend': device.split(':')[0], 'gpu_device': device})},
        payload={'type': 'qualified_evaluation', 'run_id': str(run.run_id)})
    OutboxEvent.all_objects.create(tenant_id=run.tenant_id,
        topic=dispatch_topic(run.tenant_id, pool.queue_name, pool.name),
        payload={'event_type': 'job.queued', 'job_id': str(job.job_id)})
    run.job = job
    run.protocol_ref = {'execution_request': request, 'pins': inputs['pins'],
        'total_cases': len(run.suite_version.cases), 'completed_cases': 0, 'baseline_results': [],
        'execution_evidence': {'level': 'configuration_only', 'source': 'Budgeted CPU evaluation awaiting actual case outputs.'}}
    run.save(update_fields=['job', 'protocol_ref', 'updated_at'])
    return run


def locked_run(context, run_id):
    attempt = JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job = Job.all_objects.select_for_update().get(pk=attempt.job_id)
    if (attempt.status != 'running' or attempt.fencing_token != context.fencing_token
            or not attempt.lease_expires_at or attempt.lease_expires_at <= timezone.now()
            or job.status != 'running' or job.fencing_token != context.fencing_token
            or job.claimed_by_id != attempt.worker_id):
        context.lease_lost = True
        raise ValueError('Evaluation publication refused after lease loss.')
    if job.desired_action == 'cancel':
        context.cancel_requested = True
        raise ValueError('Evaluation cancellation requested.')
    return EvaluationRun.all_objects.select_for_update().get(run_id=run_id, tenant_id=job.tenant_id, job=job)


def _worker_can_evaluate(worker, device, connection_state):
    caps = worker.capabilities or {}
    if (connection_state(worker) != 'connected' or caps.get('evaluation_runtime') != CONTRACT_DIGEST
            or caps.get('evaluation_build') != BUILD_DIGEST or caps.get('memory_bytes', 0) < MEMORY_BYTES):
        return False
    if device != 'cpu' and (caps.get('gpu_device') != device or caps.get('gpu_backend') != device.split(':')[0]):
        return False
    return True


@contextmanager
def predictor(version, inputs, run, max_tokens, context):
    if inputs['kind'] == 'reference':
        from modelanvil.runners.training.registry import generate_completion
        from modelanvil.runners.training import general_runtime
        if version.architecture_ref == general_runtime.RUNTIME_ID:
            yield lambda prompt: general_runtime.generate_candidate_completion(inputs['bundle'], prompt,
                max_new_tokens=max_tokens, heartbeat=context.heartbeat)['completion']
        else:
            yield lambda prompt: generate_completion(inputs['bundle'], prompt, max_new_tokens=max_tokens)['completion']
    else:
        from modelanvil.runners.inference import generate, local_session
        prompt_format = 'model' if run.protocol_ref['pins'].get('prompt_format') == 'native_template' else 'plain'
        with local_session(version, tenant=run.tenant_id, project=run.project_id, device=inputs.get('device', 'cpu')) as session:
            def predict(prompt):
                return ''.join(part.get('text', '') for part in generate(session,
                    [{'role': 'user', 'content': prompt}], max_tokens=max_tokens, temperature=0, prompt_format=prompt_format,
                    cancelled=lambda: not context.heartbeat()))
            yield predict


def evaluation_worker_executor(descriptor, context):
    if context.attempt.worker.capabilities.get('memory_bytes', 0) < MEMORY_BYTES:
        raise ValueError('Evaluation worker memory is below the runtime requirement.')
    run = EvaluationRun.all_objects.select_related('suite_version', 'candidate_model_version__tokenizer',
        'baseline_model_version__tokenizer').get(run_id=descriptor['payload']['run_id'],
            tenant_id=context.attempt.tenant_id, job=context.attempt.job_id)
    max_tokens = run.protocol_ref['pins']['max_tokens']
    inputs = resolve_inputs(run, max_tokens)
    if inputs['pins'] != run.protocol_ref['pins']:
        raise ValueError('Evaluation inputs or runtime changed since launch.')
    with transaction.atomic():
        current = locked_run(context, run.run_id)
        current.status = 'running'; current.started_at = current.started_at or timezone.now()
        current.save(update_fields=['status', 'started_at', 'updated_at'])
    for case in run.suite_version.cases:
        if run.case_results.filter(case_id=case['case_id']).exists():
            continue
        if not context.heartbeat(run.case_results.count() / len(run.suite_version.cases)):
            return
        with predictor(run.candidate_model_version, inputs['candidate'], run, max_tokens, context) as predict:
            output = predict(case['input_prompt'])
        baseline_result = None
        if inputs['baseline']:
            with predictor(run.baseline_model_version, inputs['baseline'], run, max_tokens, context) as predict:
                baseline_output = predict(case['input_prompt'])
            score, passed = default_eval_scorer(baseline_output, case['expected_output'], run.suite_version.scorer_type, run.suite_version.scorer_config)
            baseline_result = {'case_id': case['case_id'], 'candidate_output': baseline_output, 'score': score,
                               'passed': passed, 'slice_name': case.get('slice', 'all')}
        score, passed = default_eval_scorer(output, case['expected_output'], run.suite_version.scorer_type, run.suite_version.scorer_config)
        if not context.heartbeat():
            return
        with transaction.atomic():
            current = locked_run(context, run.run_id)
            if not current.case_results.filter(case_id=case['case_id']).exists():
                EvaluationCaseResult.all_objects.create(tenant_id=run.tenant_id, run=current,
                    case_id=case['case_id'], input_prompt=case['input_prompt'], expected_output=case['expected_output'],
                    candidate_output=output, score=score, passed=passed, slice_name=case.get('slice', 'all'),
                    failure_reason='' if passed else 'Candidate did not satisfy the pinned scorer.')
                if baseline_result:
                    current.protocol_ref['baseline_results'].append(baseline_result)
                current.protocol_ref['completed_cases'] = current.case_results.count()
                native = current.protocol_ref.get('pins', {}).get('prompt_format') == 'native_template'
                current.protocol_ref['execution_evidence'] = {'level': 'integrated_execution',
                    'source': ('Actual native-template candidate/baseline inference with pinned bytes, suite and fenced case commits; production qualification unavailable.'
                               if native else
                               'Actual CPU candidate/baseline inference with pinned bytes, suite and fenced case commits; production qualification unavailable.')}
                current.save(update_fields=['protocol_ref', 'updated_at'])
    # Job result commit below determines terminal state and settles recorded cases.


@transaction.atomic
def finalize_evaluation(job, status):
    run = EvaluationRun.all_objects.select_for_update().filter(job=job, tenant_id=job.tenant_id).first()
    if run is None:
        raise ValueError('Evaluation job has no matching owner.')
    if run.status in ('completed', 'failed', 'cancelled'):
        return run
    rows = list(run.case_results.values('case_id', 'passed', 'score', 'slice_name'))
    complete = len(rows) == run.protocol_ref['total_cases']
    terminal = 'completed' if status == 'succeeded' and complete else 'cancelled' if status == 'cancelled' else 'failed'
    if terminal == 'completed':
        for metric in _aggregate_metrics(rows):
            EvaluationMetric.all_objects.get_or_create(tenant_id=run.tenant_id, run=run,
                key=metric['key'], slice_name=metric['slice_name'], defaults={k:v for k,v in metric.items() if k not in ('key','slice_name')})
        baseline = run.protocol_ref['baseline_results']
        run.protocol_ref['baseline_metrics'] = _aggregate_metrics(baseline) if baseline else []
    run.status = terminal; run.completed_at = timezone.now()
    run.save(update_fields=['status', 'completed_at', 'protocol_ref', 'updated_at'])
    reservation = BudgetReservation.all_objects.get(job_id=job.job_id, tenant_id=run.tenant_id)
    if reservation.state == 'reserved':
        reservation.settle(len(rows))
    UsageEvent.record(tenant_id=run.tenant_id, provider_event_key=f'evaluation:{job.job_id}', quantity=len(rows),
        unit='evaluation_cases', reservation=reservation,
        detail={'run_id': str(run.run_id), 'committed_cases': len(rows), 'complete': complete})
