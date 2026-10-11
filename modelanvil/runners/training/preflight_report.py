"""Read-only admission preview; launch repeats every check before reserving compute."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.utils import timezone

from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.budgets.models import BudgetReservation
from modelanvil.jobs.models import Worker
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training.registry import capable_worker, resolve_inputs, runtime_for_architecture, checkpoint_bundle
from modelanvil.runners.training.runtime import digest

TOKEN_SALT = 'modelanvil.training-preflight.v1'
TOKEN_MAX_AGE = 600


def classify_reason(message):
    text = message.lower()
    if any(word in text for word in ('worker', 'memory', 'pool')):
        return 'capacity', 'Activate a pool with a free worker slot and the declared runtime and memory.'
    if 'budget' in text:
        return 'budget', 'Select an enabled training_steps policy with sufficient remaining budget.'
    return 'compatibility', 'Select matching published data, base weights, tokenizer and verified runner; correct the indicated input and check again.'


def storage_capacity(required_bytes):
    """Local shared-host envelope; disk space is observed, never reserved by this check."""
    root = artifact_storage_backend().root
    paths = {'artifacts': root}
    database = settings.DATABASES['default']
    if database['ENGINE'].endswith('sqlite3') and not str(database['NAME']).startswith(('file:', ':memory:')):
        paths['checkpoints'] = Path(database['NAME']).resolve().parent
    result = {}
    for label, path in paths.items():
        while not path.exists():
            path = path.parent
        result[label] = {'available_bytes': shutil.disk_usage(path).free, 'required_bytes': required_bytes}
    return result


def estimate_from_pilot(inputs, *, tenant, pool, project):
    estimate = {
        'known': False, 'source': 'No matching completed worker pilot.', 'assumptions': [],
        'units': {'duration': 'CPU seconds (engine only)', 'tokens': 'next-token pairs', 'currency': None},
        'currency': None, 'uncertainty': 'Unknown; no confidence interval has been measured.',
        'estimated_duration_seconds': None,
        'estimated_cost': {'known': False, 'value': None, 'reason': 'No measured monetary rate or currency is configured.'},
    }
    if not inputs:
        return estimate
    pins = inputs['pins']
    if pins.get('accelerator'):
        estimate['units']['duration'] = 'GPU wall seconds (unknown until a matching GPU pilot is qualified)'
        estimate['source'] = 'GPU estimate unavailable; CPU process time is not GPU elapsed time.'
        return estimate
    seqs = inputs['sequences']
    pairs = sum(len(seqs[i % len(seqs)]) - 1 for i in range(pins['steps']))
    estimate['total_tokens'] = pairs
    estimate['assumptions'] = ['One step passes one encoded sample; samples cycle in manifest order.',
        'Queue time, database writes, checkpoint storage and retries are excluded.',
        'Linear scaling by next-token pairs assumes the pilot worker hardware; placement and timing variation are unmeasured.']
    from modelanvil.identity.models import get_accessible_queryset
    pilots = get_accessible_queryset(TrainingRun, tenant_id=tenant, project_id=project).filter(pool=pool, status='completed').order_by('-completed_at')[:20]
    for run in pilots:
        prior = (run.hardware_config or {}).get('pins', {})
        if any(prior.get(k) != pins.get(k) for k in ('runtime', 'contract_digest', 'build_digest', 'config', 'optimizer', 'tokenizer_digest')):
            continue
        checkpoint = run.checkpoints.filter(step=run.total_steps).first()
        if not checkpoint:
            continue
        try:
            checkpoint_bundle(run, checkpoint)
            metrics = list(run.checkpoints.order_by('step').values_list('metrics', flat=True))
            measured_pairs = sum(m['training_pairs'] for m in metrics)
            cpu = sum(m['cpu_seconds'] for m in metrics)
            if measured_pairs <= 0 or cpu <= 0 or len(metrics) != run.total_steps:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        estimate.update(known=True, source=f'Measured completed worker pilot {run.run_id}',
            pilot={'run_id': str(run.run_id), 'cpu_seconds': cpu, 'training_pairs': measured_pairs},
            estimated_duration_seconds=cpu * pairs / measured_pairs)
        break
    return estimate


def build_preflight_report(*, recipe_type, tokenizer_version, base_model_version=None, dataset_revision=None,
                           pool=None, runner=None, total_steps=100, budget_policy=None,
                           execution_mode='worker', tenant=None, project=None, initialization_seed=42):
    checks = []
    inputs = None

    def check(key, category, ok, reason, action='', detail=None):
        checks.append({'check': key, 'category': category, 'status': 'pass' if ok else 'fail',
                       'blocking': not ok, 'reason': reason, 'corrective_action': None if ok else action,
                       'detail': detail or {}})

    module = runtime_for_architecture(getattr(base_model_version, 'architecture_ref', None))
    recipes = module.CONTRACT.get('recipes', [module.CONTRACT['recipe']]) if module else ['full_sft']
    supported_recipe = recipe_type in recipes
    check('recipe-execution-mode', 'compatibility', execution_mode == 'worker' and supported_recipe,
          'Worker recipe must match the selected runtime.', 'Choose a supported worker recipe: ' + ', '.join(recipes) + '.')
    for key, resource in [('dataset_revision', dataset_revision), ('base_model_version', base_model_version),
                          ('tokenizer_version', tokenizer_version), ('runner_manifest', runner), ('pool', pool)]:
        check(key, 'compatibility', resource is not None, f'{key}: selected accessible resource.' if resource else f'{key}: missing or inaccessible.',
              f'Select an accessible {key.replace("_", " ")}.')
    if dataset_revision:
        check('dataset-published', 'compatibility', dataset_revision.state == 'published',
              'Dataset must be published with immutable prepared text.', 'Publish a prepared dataset revision.')
    if base_model_version and tokenizer_version:
        check('model-tokenizer', 'compatibility', base_model_version.tokenizer_id == tokenizer_version.pk,
              'Base weights must pin the selected tokenizer.', 'Select the tokenizer pinned by the base model.')
    if runner and module:
        check('runner-contract', 'compatibility', runner.enabled and runner.digest == digest(module.runner_manifest())
              and runner.manifest == module.runner_manifest() and runner.compatibility.get('contract_digest') == module.CONTRACT_DIGEST,
              'Runner must be enabled and match the qualified runtime contract.', 'Register or select the enabled exact runtime manifest.')
    if execution_mode == 'worker' and supported_recipe and all((dataset_revision, base_model_version, tokenizer_version, runner, pool)):
        try:
            inputs = resolve_inputs(dataset=dataset_revision, base=base_model_version, tokenizer=tokenizer_version,
                                    runner=runner, pool=pool, tenant=tenant, project=project, steps=total_steps, require_capacity=False,
                                    recipe_type=recipe_type, initialization_seed=initialization_seed)
            check('pinned-inputs', 'compatibility', True, 'Verified dataset bytes, base weights, tokenizer encoding and runner contract.')
        except (ValueError, TypeError, KeyError) as exc:
            category, action = classify_reason(str(exc))
            check('pinned-inputs', category, False, str(exc), action)
    workers = list(Worker.all_objects.filter(tenant_id=tenant, pool=pool, status__in=['available', 'busy'])) if pool else []
    matching = [w for w in workers if capable_worker(w, base_model_version)] if module else []
    check('worker-memory', 'capacity', bool(matching), 'A worker must declare the selected contract and sufficient memory.',
          'Register a worker with the selected runtime contract and required memory declaration.',
          {'required_memory_bytes': module.LIMITS['memory_bytes'] if module else None, 'matching_workers': len(matching)})
    free = sum(w.slots for w in matching)
    check('worker-slots', 'capacity', bool(pool and pool.status == 'active' and free >= 1),
          f'{free} free matching worker slot(s); one required.', 'Activate the pool and free or add a matching worker slot.', {'available_slots': free, 'required_slots': 1})
    budget = None
    valid_policy = budget_policy and budget_policy.enabled and budget_policy.unit == 'training_steps' and not budget_policy.currency
    if budget_policy:
        period, committed = BudgetReservation.current_commitment(budget_policy)
        budget = {'policy_id': str(budget_policy.policy_id), 'period': budget_policy.period, 'period_start': str(period),
                  'unit': budget_policy.unit, 'currency': budget_policy.currency or None, 'limit': str(budget_policy.limit_amount),
                  'committed': str(committed), 'remaining': str(budget_policy.limit_amount - committed), 'requested': total_steps}
        valid_policy = valid_policy and total_steps > 0 and committed + total_steps <= budget_policy.limit_amount
    check('budget', 'budget', bool(valid_policy), 'Budget must be enabled, use training_steps, and cover the requested sample passes.',
          'Select an enabled training_steps budget, increase its limit or reduce steps.', budget)
    requirements = {}
    if inputs:
        # shortcut: bounded JSON checkpoint sizing plus conservative database overhead; revisit for remote storage or a larger runtime.
        checkpoint_bytes = inputs.get('checkpoint_bytes', len(json.dumps(inputs['bundle']).encode()) + 65536)
        required = checkpoint_bytes * (total_steps + 2)
        requirements = {'runtime': inputs['pins']['runtime'], 'recipe': recipe_type, 'config': inputs['pins']['config'],
                        'optimizer': inputs['pins']['optimizer'], 'cpu_slots': 1, 'memory_bytes': module.LIMITS['memory_bytes'],
                        'storage_bytes': required, 'storage_assumption': 'One full checkpoint per step, candidate copies and 64 KiB overhead per state; shared local host.'}
        if inputs['pins'].get('accelerator'):
            from modelanvil.device_admission import device_available
            try:
                available = device_available(inputs['pins']['accelerator']['device']['id'])
                check('device-admission', 'capacity', available, 'The named local device must be idle across cooperating API and training processes.',
                    'Wait for the current device user to finish, then preview again.')
            except (ValueError, OSError) as exc:
                check('device-admission', 'capacity', False, str(exc), 'Configure the same private device admission directory for local API and workers.')
            requirements.update(gpu_count=1, accelerator=inputs['pins']['accelerator'], precision=module.CONTRACT['precision'],
                storage_assumption='FP32 weights, two FP32 Adam moments, per-step checkpoints and staging/candidate headroom; shared local host.')
            if recipe_type == 'lora_adapter':
                requirements.update(adapter=inputs['pins']['adapter'], trainable_parameters=inputs['pins']['trainable_parameters'],
                    storage_assumption='Immutable shared base references plus FP32 adapter weights and Adam moments per step; shared local host.')
        try:
            space = storage_capacity(required)
            check('storage', 'capacity', all(v['available_bytes'] >= required for v in space.values()),
                  'Local artifact and checkpoint storage must cover the projected states.', 'Free local disk space or reduce steps.', space)
        except (OSError, AttributeError, ValueError) as exc:
            check('storage', 'capacity', False, f'Storage capacity unknown: {exc}', 'Configure readable shared local storage and check again.')
    else:
        check('storage', 'capacity', False, 'Storage requirement unknown until inputs resolve.', 'Correct the input checks, then preview again.')
    blocked = [c['check'] for c in checks if c['blocking']]
    samples = [{'sample_id': s['sample_id'], 'text_preview': s['text'], 'token_ids': s['token_ids'],
                'token_count': len(s['token_ids'])} for s in inputs['samples'][:5]] if inputs else []
    fingerprint = digest({'pins': inputs['pins'], 'recipe': recipe_type, 'project': str(project), 'tenant': str(tenant),
                          'revisions': [str(r.updated_at) for r in (dataset_revision, base_model_version, tokenizer_version, runner, pool, budget_policy)],
                          'storage': str(artifact_storage_backend().root), 'budget_policy': str(budget_policy.policy_id)}) if inputs and budget_policy else None
    return {'status': 'blocked' if blocked else 'approved', 'recipe_type': recipe_type, 'execution_mode': execution_mode,
            'checks': checks, 'blocking_checks': blocked, 'samples': samples, 'sample_count': len(inputs['samples']) if inputs else None,
            'pins': inputs['pins'] if inputs else None, 'requirements': requirements, 'budget': budget,
            'estimate': estimate_from_pilot(inputs, tenant=tenant, pool=pool, project=project), 'fingerprint': fingerprint,
            'checked_at': timezone.now().isoformat(), 'expires_in_seconds': TOKEN_MAX_AGE,
            'runtime_scope': {'targets': [], 'available': [module.RUNTIME_ID] if inputs else [], 'unavailable': []},
            'capacity_note': 'Capacity is observed, not reserved. Launch rechecks; worker claim enforces slots and budget reservation is atomic.'}


def issue_token(report, principal):
    if report['status'] != 'approved':
        return None
    return signing.dumps({'fingerprint': report['fingerprint'], 'principal': str(principal)}, salt=TOKEN_SALT)


def verify_token(token, report, principal):
    try:
        proof = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        raise ValueError('Preflight expired or invalid. Preview again before launch.') from None
    if proof != {'fingerprint': report['fingerprint'], 'principal': str(principal)}:
        raise ValueError('Preflight inputs changed. Preview again before launch.')
