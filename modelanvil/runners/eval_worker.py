"""Pinned CPU inference with per-case fenced commits and durable accounting."""
import hashlib
import json
from contextlib import contextmanager, nullcontext
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.budgets.models import BudgetReservation, UsageEvent
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Job, JobAttempt, OutboxEvent, Worker, dispatch_topic
from modelanvil.runners.eval_executor import SCORER_VERSION, _aggregate_metrics, default_eval_scorer, validate_local_suite
from modelanvil.runners.models import EvaluationCaseResult, EvaluationMetric, EvaluationRun
from modelanvil.runners.training.runtime import digest

from modelanvil.runners.training.sequence_envelope import generated_token_ceiling

RUNTIME_ID = 'modelanvil.local-cpu-evaluation.v1'
CONTRACT = {'runtime': RUNTIME_ID, 'cases': 64, 'max_tokens': generated_token_ceiling(), 'decoding': 'greedy', 'formats': ['plain', 'native_template']}
CONTRACT_DIGEST = digest(CONTRACT)
BUILD_DIGEST = hashlib.sha256(b''.join((Path(__file__).parent / name).read_bytes()
    for name in ('eval_worker.py', 'eval_executor.py', 'local_execution.py', 'inference.py',
        'training/runtime.py', 'training/general_runtime.py', 'training/general_transformer.py',
        'training/autograd.py', 'training/engine.py', 'training/registry.py', 'training/hf_runtime.py',
        'guided_evaluation.py'))).hexdigest()
MEMORY_BYTES = 512 * 1024 * 1024
# The pre-beta CPU implementation is retained; only this known historical build may validate completed evidence.
LEGACY_CPU_BUILD = '89a1654d8178a0ace9923711aa42b49e7d5d267c00cf235e1f86c63d71a82912'


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
            if run.protocol_ref.get('profile') == 'guided-native':
                train_ids.update(prepared['split_manifest'].get('validation', []))
            rows = [r for r in prepared['rows'] if r['sample_id'] in train_ids]
            groups = {r['source_group_id'] for r in rows}
            texts = {'\n'.join(b['text'] for b in r['blocks'] if b['type'] == 'text') for r in rows}
            prompts = [[{'role': b.get('role'), 'content': b.get('text')} for b in r['blocks'][:-1]] for r in rows]
            if any(c.get('sample_id') in train_ids or c.get('source_group_id') in groups or c['input_prompt'] in texts
                   or c.get('messages') in prompts for c in cases):
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
    from modelanvil.runners import guided_evaluation as guided
    native = run.protocol_ref.get('profile') == guided.PROFILE
    if run.suite_version.protected_role != 'protected_eval':
        raise ValueError('Queue a suite version declared as protected evaluation.')
    validate_local_suite(run.suite_version.cases, run.suite_version.scorer_type, run.suite_version.scorer_config)
    if not check_resource_access(run.suite_version, run.project_id, run.tenant_id):
        raise ValueError('The evaluation suite is unavailable in this project.')
    template_digest = None
    if native:
        _, _, template_digest = guided.native_pair(run)
        guided.validate_classification_suite(run.suite_version)
    candidate = model_inputs(run.candidate_model_version, run.tenant_id, run.project_id)
    baseline = model_inputs(run.baseline_model_version, run.tenant_id, run.project_id) if run.baseline_model_version_id else None
    if baseline and run.baseline_model_version.tokenizer_id != run.candidate_model_version.tokenizer_id:
        raise ValueError('Use candidate and baseline versions with the same pinned tokenizer.')
    if baseline and baseline['device'] != candidate['device']:
        raise ValueError('Candidate and baseline must evaluate on the same device.')
    ceiling = generated_token_ceiling()
    if type(max_tokens) is not int or not 1 <= max_tokens <= ceiling:
        raise ValueError(f'Choose 1–{ceiling} generated tokens per case.')
    if native:
        # The guided profile renders every case through the pinned native template on the Apple GPU used for training.
        prompt_format, device = 'model', 'mps:0'
    else:
        prompt_format, device = evaluation_prompt_format(run), candidate['device']
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
                    if native:
                        messages = case.get('messages', [{'role': 'user', 'content': case['input_prompt']}])
                        encoded_len = len(tokenizer.encode(rendered_prompt(tokenizer, messages, 'model'), add_special_tokens=False))
                    elif prompt_format == 'native_template':
                        prompt = rendered_prompt(tokenizer, [{'role': 'user', 'content': case['input_prompt']}], 'model')
                        encoded_len = len(tokenizer.encode(prompt, add_special_tokens=False))
                    else:
                        encoded_len = len(tokenizer.encode(case['input_prompt'], add_special_tokens=True))
                    if encoded_len + max_tokens > limit:
                        raise ValueError('A case prompt and output exceed the selected snapshot context limit.')
    runtime_id = guided.RUNTIME_ID if native else RUNTIME_ID
    native_pins = {'template_sha256': template_digest, 'contract_digest': guided.CONTRACT_DIGEST} if native else {}
    return {'candidate': candidate, 'baseline': baseline, 'pins': {
        'runtime': runtime_id, 'build_digest': BUILD_DIGEST, 'scorer_version': SCORER_VERSION,
        'protected_role': run.suite_version.protected_role, 'candidate': candidate['pins'],
        'baseline': baseline['pins'] if baseline else None,
        'suite_digest': digest({'cases': run.suite_version.cases, 'scorer': run.suite_version.scorer_type,
                              'config': run.suite_version.scorer_config}),
        'max_tokens': max_tokens, 'decoding': 'greedy', 'prompt_format': prompt_format, 'device': device, **native_pins,
        'environment': {'runtime': runtime_id, 'build_digest': BUILD_DIGEST, 'device': device, 'prompt_format': prompt_format,
                        'decoding': 'greedy', **({'template_sha256': template_digest, 'precision': 'fp32', 'adapter': 'rank16', 'seed': 42} if native else {})},
        'training_overlap': check_training_overlap(run)}}


def verified_evaluation_inputs(run):
    """Verify completed old CPU evidence without treating it as permission to execute old code."""
    pins = run.protocol_ref.get('pins', {})
    inputs = resolve_inputs(run, pins.get('max_tokens'))
    expected = inputs['pins']
    if (run.status == 'completed' and pins.get('runtime') == RUNTIME_ID
            and pins.get('build_digest') == LEGACY_CPU_BUILD
            and pins.get('environment', {}).get('build_digest') == LEGACY_CPU_BUILD):
        expected['build_digest'] = LEGACY_CPU_BUILD
        expected['environment']['build_digest'] = LEGACY_CPU_BUILD
    if expected != pins:
        raise ValueError('Evaluation inputs or runtime no longer match their frozen evidence.')
    return inputs


@transaction.atomic
def queue_evaluation(run, *, pool, policy, max_tokens):
    from modelanvil.runners import guided_evaluation as guided
    native = run.protocol_ref.get('profile') == guided.PROFILE
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
    requirements = {'slots': 1, 'evaluation_runtime': guided.CONTRACT_DIGEST if native else CONTRACT_DIGEST, 'evaluation_build': BUILD_DIGEST}
    if native:
        requirements['gpu_device'] = device
    elif device != 'cpu':
        requirements.update(gpu_backend=device.split(':')[0], gpu_device=device)
    memory = guided.MEMORY_BYTES if native else MEMORY_BYTES
    workers = Worker.all_objects.filter(tenant_id=run.tenant_id, pool=pool, status='available', slots__gte=1)
    if not any(_worker_can_evaluate(w, requirements, memory, connection_state) for w in workers):
        raise ValueError('Connect an installed evaluation worker with matching runtime, device and sufficient memory.')
    if policy.tenant_id != run.tenant_id or policy.unit != 'evaluation_cases' or policy.currency:
        raise ValueError('Select an enabled evaluation_cases quantity budget.')
    job_id = uuid7()
    BudgetReservation.reserve(tenant_id=run.tenant_id, policy=policy, job_id=job_id,
                              estimated_amount=len(run.suite_version.cases))
    job = Job.all_objects.create(tenant_id=run.tenant_id, job_id=job_id, pool=pool,
        name=f'Evaluation {str(run.run_id)[:8]}', requirements=requirements,
        payload={'type': 'qualified_evaluation', 'run_id': str(run.run_id)})
    OutboxEvent.all_objects.create(tenant_id=run.tenant_id,
        topic=dispatch_topic(run.tenant_id, pool.queue_name, pool.name),
        payload={'event_type': 'job.queued', 'job_id': str(job.job_id)})
    run.job = job
    run.protocol_ref = {**{key: run.protocol_ref[key] for key in ('profile', 'training_run_id') if key in run.protocol_ref},
        'execution_request': request, 'pins': inputs['pins'],
        'total_cases': len(run.suite_version.cases), 'completed_cases': 0, 'baseline_results': [],
        'execution_evidence': {'level': 'configuration_only', 'source': ('Budgeted native evaluation awaiting actual case outputs.' if native else
                                                                        'Budgeted CPU evaluation awaiting actual case outputs.')}}
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


def _worker_can_evaluate(worker, requirements, memory, connection_state):
    """Mirror claim-time matching so queueing refuses work no connected worker could claim."""
    caps = worker.capabilities or {}
    return (connection_state(worker) == 'connected' and caps.get('memory_bytes', 0) >= memory
            and all(caps.get(key) == value for key, value in requirements.items() if key != 'slots'))


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
    from modelanvil.runners import guided_evaluation as guided
    if context.attempt.worker.capabilities.get('memory_bytes', 0) < MEMORY_BYTES:
        raise ValueError('Evaluation worker memory is below the runtime requirement.')
    run = EvaluationRun.all_objects.select_related('suite_version', 'candidate_model_version__tokenizer',
        'baseline_model_version__tokenizer').get(run_id=descriptor['payload']['run_id'],
            tenant_id=context.attempt.tenant_id, job=context.attempt.job_id)
    native = run.protocol_ref.get('profile') == guided.PROFILE
    max_tokens = run.protocol_ref['pins']['max_tokens']
    inputs = resolve_inputs(run, max_tokens)
    if inputs['pins'] != run.protocol_ref['pins']:
        raise ValueError('Evaluation inputs or runtime changed since launch.')
    if native and context.attempt.worker.capabilities.get('gpu_device') != 'mps:0':
        raise ValueError('The native evaluation worker must use the pinned Apple GPU.')
    with transaction.atomic():
        current = locked_run(context, run.run_id)
        current.status = 'running'; current.started_at = current.started_at or timezone.now()
        import platform
        current.protocol_ref['environment'] = {'python': platform.python_version(), 'platform': platform.platform(),
            'device': inputs['pins']['device'], 'runtime': inputs['pins']['runtime'], 'build_digest': BUILD_DIGEST,
            'scorer_version': SCORER_VERSION}
        current.save(update_fields=['status', 'started_at', 'protocol_ref', 'updated_at'])
    # The guided profile loads the adapter once and scores its exact base by disabling the adapter.
    with (guided.native_predictors(run, max_tokens, context) if native else nullcontext(None)) as native_predict:
        for case in run.suite_version.cases:
            if run.case_results.filter(case_id=case['case_id']).exists():
                continue
            if not context.heartbeat(run.case_results.count() / len(run.suite_version.cases)):
                return
            if native_predict:
                output = native_predict(case)
            else:
                with predictor(run.candidate_model_version, inputs['candidate'], run, max_tokens, context) as predict:
                    output = predict(case['input_prompt'])
            baseline_result = None
            if inputs['baseline']:
                if native_predict:
                    baseline_output = native_predict(case, baseline=True)
                else:
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
                    templated = current.protocol_ref.get('pins', {}).get('prompt_format') == 'native_template'
                    current.protocol_ref['execution_evidence'] = {'level': 'integrated_execution',
                        'source': ('Actual candidate/baseline inference with pinned bytes, template, suite and fenced case commits; production qualification unavailable.'
                                   if native else
                                   'Actual native-template candidate/baseline inference with pinned bytes, suite and fenced case commits; production qualification unavailable.'
                                   if templated else
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
