"""Bounded classification review for the pinned Apple adapter journey."""
import hashlib
import json
import random
import re
from contextlib import contextmanager

from django.db import transaction

from modelanvil.identity.models import check_resource_access
from modelanvil.runners.models import EvaluationRun, EvaluationSuite, EvaluationSuiteVersion, TrainingRun
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.runtime import digest, read_artifact

PROFILE = 'guided-native'
RUNTIME_ID = 'modelanvil.guided-native-evaluation.v1'
CONTRACT_DIGEST = digest({'runtime': RUNTIME_ID, 'cases': 64, 'tokens': 32, 'device': 'mps:0',
                         'format': 'model', 'labels': 8, 'source': hf_runtime.LARGE_GUIDED_SOURCE})
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}\Z')
MEMORY_BYTES = 32 * 1024**3  # The 1.7B base and its adapter evaluate on the Apple GPU of a 32 GiB host.


def classification_labels(labels):
    if (not isinstance(labels, list) or not 2 <= len(labels) <= 8
            or any(not isinstance(label, str) or not LABEL.fullmatch(label) or label != label.strip() for label in labels)
            or len(set(labels)) != len(labels)):
        raise ValueError('Classification requires 2–8 distinct labels, each 1–64 letters, numbers, spaces, underscores, dots or hyphens.')
    return labels


def classification_case(row):
    blocks = row.get('blocks', [])
    if (len(blocks) < 2 or any(b.get('type') != 'text' or b.get('role') not in ('system', 'user', 'assistant') for b in blocks)
            or blocks[-1].get('role') != 'assistant' or blocks[-2].get('role') != 'user'):
        raise ValueError('Classification examples need a conversation ending in an assistant label. Plain text datasets are not classification tasks.')
    label = blocks[-1]['text']
    if not LABEL.fullmatch(label) or label != label.strip():
        raise ValueError('Each assistant response must be one exact classification label of at most 64 characters.')
    messages = [{'role': b['role'], 'content': b['text']} for b in blocks[:-1]]
    return {'case_id': row['sample_id'], 'sample_id': row['sample_id'], 'source_group_id': row['source_group_id'],
            'input_prompt': messages[-1]['content'], 'messages': messages, 'expected_output': label, 'slice': label}


def held_out_cases(training):
    revision = training.dataset_revision
    if revision is None or not revision.manifest_artifact or not check_resource_access(revision, training.project_id, training.tenant_id):
        raise ValueError('The original training dataset is unavailable in this project.')
    raw = read_artifact(revision.manifest_artifact, training.tenant_id, training.project_id)
    if hashlib.sha256(raw).hexdigest() != revision.manifest_digest:
        raise ValueError('Training dataset no longer matches its pinned manifest.')
    prepared = json.loads(raw)
    rows = [classification_case(row) for row in prepared['rows']]
    labels = classification_labels(sorted({row['expected_output'] for row in rows}))
    test_ids = set(prepared['split_manifest']['test'])
    cases = [row for row in rows if row['sample_id'] in test_ids]
    if not 1 <= len(cases) <= 64:
        raise ValueError('Use a protected test split with 1–64 examples, or import a separate protected classification suite. Training and validation examples cannot be evaluated here.')
    return cases, labels


def validate_classification_suite(suite, labels=None):
    from modelanvil.runners.eval_executor import validate_local_suite
    from modelanvil.runners.inference import validate_messages
    validate_local_suite(suite.cases, suite.scorer_type, suite.scorer_config, require_source_groups=True)
    if suite.scorer_type != 'exact_match' or suite.protected_role != 'protected_eval':
        raise ValueError('Use a protected exact-match classification suite.')
    labels = classification_labels(labels or suite.scorer_config.get('labels') or sorted({c['expected_output'] for c in suite.cases}))
    for case in suite.cases:
        if case['expected_output'] not in labels:
            raise ValueError('Every expected output must be one of the task labels.')
        messages = case.get('messages', [{'role': 'user', 'content': case['input_prompt']}])
        validate_messages(messages)
        if messages[-1]['role'] != 'user':
            raise ValueError('Classification evaluation input must end with a user message.')
    return labels


def native_pair(run):
    from modelanvil.runners.inference import snapshot, model_chat_template
    training = TrainingRun.all_objects.filter(tenant_id=run.tenant_id, output_model_version=run.candidate_model_version,
        status='completed', job__status='succeeded', recipe_type='lora_adapter').first()
    if (training is None or not check_resource_access(training, run.project_id, run.tenant_id)
            or training.base_model_version_id != run.baseline_model_version_id):
        raise ValueError('Compare a completed guided adapter with its exact training base model.')
    candidate = snapshot(run.candidate_model_version, run.tenant_id, run.project_id)
    base = snapshot(run.baseline_model_version, run.tenant_id, run.project_id)
    if (not candidate.get('guided_large') or candidate.get('source') != hf_runtime.LARGE_GUIDED_SOURCE
            or base.get('source') != hf_runtime.LARGE_GUIDED_SOURCE or not candidate.get('adapter')):
        raise ValueError('Guided evaluation supports the pinned SmolLM2-1.7B Apple adapter profile.')
    for name, ref in base['files'].items():
        if candidate['files'].get(name, {}).get('sha256') != ref.get('sha256'):
            raise ValueError('The adapter and baseline do not contain the exact same base files.')
    template = model_chat_template(run.candidate_model_version)
    if not template or template != model_chat_template(run.baseline_model_version):
        raise ValueError('Candidate and baseline must share their pinned native chat template.')
    return training, candidate, hashlib.sha256(template.encode()).hexdigest()


@contextmanager
def native_predictors(run, max_tokens, context):
    """Load one adapter once; disabling it uses the verified identical base bytes."""
    from modelanvil.runners.inference import generate, local_session
    native_pair(run)
    with local_session(run.candidate_model_version, tenant=run.tenant_id, project=run.project_id, device='mps:0') as session:
        if session['device'] != 'mps:0' or not hasattr(session['model'], 'disable_adapter'):
            raise ValueError('Native evaluation requires the actual Apple adapter runtime; CPU fallback is unavailable.')
        def predict(case, *, baseline=False):
            messages = case.get('messages', [{'role': 'user', 'content': case['input_prompt']}])
            def answer():
                return ''.join(part.get('text', '') for part in generate(session, messages, max_tokens=max_tokens,
                    temperature=0, seed=42, prompt_format='model', cancelled=lambda: not context.heartbeat()))
            if baseline:
                with session['model'].disable_adapter():
                    return answer()
            return answer()
        yield predict


def prepare_managed_evaluation(training, *, allow_new_allowance):
    from modelanvil.budgets.models import BudgetPolicy
    from modelanvil.jobs.models import Worker, WorkerPool
    from modelanvil.runners.models import LocalTrainingHost
    from modelanvil.runners.training.managed import host_status
    from modelanvil.runners.eval_worker import BUILD_DIGEST
    if not host_status()['available']:
        raise ValueError(host_status()['message'])
    host = LocalTrainingHost.objects.get(name='local')
    if host.device != 'mps:0' or host.memory_bytes < MEMORY_BYTES:
        raise ValueError('Guided classification evaluation requires Apple GPU compute with at least 32 GiB RAM.')
    policy = BudgetPolicy.all_objects.filter(tenant_id=training.tenant_id, name='Guided evaluation allowance').first()
    if policy is None:
        if not allow_new_allowance:
            raise ValueError('The workspace owner needs to enable its guided evaluation allowance.')
        policy = BudgetPolicy.all_objects.create(tenant_id=training.tenant_id, name='Guided evaluation allowance',
            period='lifetime', unit='evaluation_cases', limit_amount=10000)
    pool, _ = WorkerPool.all_objects.get_or_create(tenant_id=training.tenant_id, name=f'Managed native evaluation · {CONTRACT_DIGEST[:8]}')
    worker, _ = Worker.all_objects.get_or_create(tenant_id=training.tenant_id, pool=pool, name=pool.name,
        defaults={'slots': 1, 'capabilities': {'managed_local': True,
            'evaluation_runtime': CONTRACT_DIGEST, 'evaluation_build': BUILD_DIGEST, 'memory_bytes': host.memory_bytes,
            'gpu_backend': 'mps', 'gpu_device': 'mps:0'}})
    if (pool.status != 'active' or not policy.enabled or policy.unit != 'evaluation_cases' or policy.currency
            or worker.capabilities.get('evaluation_runtime') != CONTRACT_DIGEST
            or worker.capabilities.get('evaluation_build') != BUILD_DIGEST):
        raise ValueError('Managed evaluation capacity or allowance is paused or stale. Ask the installation owner to restart the managed service.')
    return {'pool': pool.pk, 'budget_policy_id': str(policy.policy_id), 'max_tokens': 32, 'profile': PROFILE}


@transaction.atomic
def prepare_evaluation(training, *, suite=None, allow_new_allowance=False):
    training = TrainingRun.all_objects.select_for_update().get(pk=training.pk)
    if training.status != 'completed' or not training.output_model_version_id or not training.base_model_version_id:
        raise ValueError('Complete training before evaluating its selected candidate.')
    if not training.project_id:
        raise ValueError('Guided evaluation needs a project-scoped training run.')
    if suite is None:
        cases, labels = held_out_cases(training)
        logical, _ = EvaluationSuite.all_objects.get_or_create(tenant_id=training.tenant_id,
            name=f'Classification test · {training.dataset_revision.revision_id}', defaults={'project_id': training.project_id})
        if not check_resource_access(logical, training.project_id, training.tenant_id):
            raise ValueError('The classification suite is unavailable in this project.')
        suite, _ = EvaluationSuiteVersion.all_objects.get_or_create(tenant_id=training.tenant_id, suite=logical, revision_no=1,
            defaults={'project_id': training.project_id, 'cases': cases, 'scorer_type': 'exact_match',
                'scorer_config': {'labels': labels}, 'protected_role': 'protected_eval'})
        if suite.cases != cases or suite.scorer_config != {'labels': labels}:
            raise ValueError('The saved protected test suite no longer matches the dataset.')
    else:
        if not check_resource_access(suite, training.project_id, training.tenant_id):
            raise ValueError('The imported evaluation suite is unavailable in this project.')
        labels = validate_classification_suite(suite)
    run = EvaluationRun.all_objects.filter(tenant_id=training.tenant_id, project_id=training.project_id,
        candidate_model_version=training.output_model_version, baseline_model_version=training.base_model_version,
        suite_version=suite, protocol_ref__profile=PROFILE).order_by('-created_at').first()
    if run is None:
        run = EvaluationRun.all_objects.create(tenant_id=training.tenant_id, project_id=training.project_id,
            candidate_model_version=training.output_model_version, baseline_model_version=training.base_model_version,
            suite_version=suite, protocol_ref={'profile': PROFILE, 'training_run_id': str(training.run_id)})
    from modelanvil.runners.eval_worker import resolve_inputs
    resolve_inputs(run, 32)
    launch = prepare_managed_evaluation(training, allow_new_allowance=allow_new_allowance)
    warnings = []
    missing = sorted(set(labels) - {case['expected_output'] for case in suite.cases})
    if missing:
        warnings.append('The held-out split does not cover these labels: ' + ', '.join(missing) + '. Macro-F1 includes them with zero support.')
    return run, suite, launch, labels, warnings


def classification_metrics(rows, labels):
    matrix = [[0] * (len(labels) + 1) for _ in labels]
    for row in rows:
        actual = labels.index(row['expected_output'])
        predicted = row['candidate_output'].strip()
        matrix[actual][labels.index(predicted) if predicted in labels else len(labels)] += 1
    f1 = []
    for index in range(len(labels)):
        tp = matrix[index][index]
        fp = sum(row[index] for row in matrix) - tp
        fn = sum(matrix[index]) - tp
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    return {'accuracy': sum(matrix[i][i] for i in range(len(labels))) / len(rows) if rows else None,
            'macro_f1': sum(f1) / len(labels) if rows else None, 'confusion_matrix': matrix}


def decision_report(run):
    if run.protocol_ref.get('profile') != PROFILE:
        return None
    labels = validate_classification_suite(run.suite_version)
    rows = list(run.case_results.order_by('case_id').values('case_id', 'expected_output', 'candidate_output', 'passed', 'slice_name'))
    baseline = {row['case_id']: row for row in run.protocol_ref.get('baseline_results', [])}
    base_rows = [{**row, 'candidate_output': baseline[row['case_id']]['candidate_output']} for row in rows if row['case_id'] in baseline]
    changes = [{'case_id': row['case_id'], 'expected_output': row['expected_output'], 'candidate_output': row['candidate_output'],
                'baseline_output': baseline[row['case_id']]['candidate_output'],
                'change': ('improved' if row['passed'] else 'regressed') if row['passed'] != baseline[row['case_id']]['passed'] else 'unchanged'} for row in rows
               if row['case_id'] in baseline and row['candidate_output'] != baseline[row['case_id']]['candidate_output']]
    complete = run.status == 'completed' and len(rows) == len(base_rows) == len(run.suite_version.cases)
    delta, interval = None, None
    if complete:
        differences = [int(row['passed']) - int(baseline[row['case_id']]['passed']) for row in rows]
        delta = sum(differences) / len(differences)
        # Bounded deterministic paired bootstrap; this is descriptive, not a release gate.
        if len(rows) >= 2:
            rng = random.Random(42)
            samples = sorted(sum(rng.choice(differences) for _ in differences) / len(differences) for _ in range(2000))
            interval = [samples[49], samples[1949]]
    return {'available': complete, 'reason': '' if complete else 'Complete all candidate and baseline cases before deciding.',
        'candidate': classification_metrics(rows, labels), 'baseline': classification_metrics(base_rows, labels),
        'case_changes': {'improved': sum(c['change'] == 'improved' for c in changes),
            'regressed': sum(c['change'] == 'regressed' for c in changes),
            'unchanged': len(base_rows) - sum(c['change'] != 'unchanged' for c in changes), 'changed_cases': changes},
        'complete_cases': len(base_rows), 'total_cases': len(run.suite_version.cases), 'labels': labels,
        'accuracy_delta': delta, 'accuracy_delta_interval': interval,
        'uncertainty_method': 'Paired percentile bootstrap, 2000 resamples, seed 42; unavailable with fewer than two cases. Small suites cannot establish broad quality.',
        'training_run_id': run.protocol_ref.get('training_run_id'), 'export_available': complete,
        'resource_evidence': run.protocol_ref.get('pins', {}).get('environment', {}), 'production_qualified': False}
