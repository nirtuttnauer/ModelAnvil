"""Baseline evaluation executor with case-level scoring, uncertainty, and slices (WP-07 / TECH-020)."""
from __future__ import annotations

import math
from typing import Any, Callable, Optional
from django.db import transaction
from django.utils import timezone

from modelanvil.runners.models import (
    EvaluationCaseResult,
    EvaluationMetric,
    EvaluationRun,
    EvaluationSuiteVersion,
    ModelVersion,
)

SCORER_VERSION = 'modelanvil.local-scorers.v1'


def default_eval_scorer(
    predicted: str,
    expected: str,
    scorer_type: str = "exact_match",
    config: Optional[dict[str, Any]] = None,
) -> tuple[float, bool]:
    """Score prediction against expected output. Returns (score, passed)."""
    p = (predicted or "").strip()
    e = (expected or "").strip()
    config = config or {}

    if scorer_type == "exact_match":
        passed = (p == e)
        return (1.0 if passed else 0.0), passed

    if scorer_type == "substring":
        passed = (e in p)
        return (1.0 if passed else 0.0), passed

    if scorer_type == "numeric_tolerance":
        tol = float(config.get("tolerance", 1e-4))
        try:
            val_p = float(p)
            val_e = float(e)
            if not math.isfinite(val_p) or not math.isfinite(val_e):
                return 0.0, False
            diff = abs(val_p - val_e)
            passed = diff <= tol
            score = max(0.0, 1.0 - (diff / (abs(val_e) + 1e-8)))
            return score, passed
        except (ValueError, TypeError):
            return 0.0, False

    # Default fallback
    passed = (p == e)
    return (1.0 if passed else 0.0), passed


def validate_local_suite(cases, scorer_type, scorer_config):
    if not isinstance(cases, list) or not 1 <= len(cases) <= 64:
        raise ValueError('A local evaluation suite requires 1–64 cases.')
    if scorer_type not in {'exact_match', 'substring', 'numeric_tolerance'}:
        raise ValueError('Select exact_match, substring, or numeric_tolerance scoring.')
    if not isinstance(scorer_config, dict):
        raise ValueError('Scorer configuration must be a JSON object.')
    tolerance = scorer_config.get('tolerance', 0.0001)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('Numeric tolerance must be a finite nonnegative number.')
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('Evaluation cases must be JSON objects.')
        case_id = case.get('case_id')
        if not isinstance(case_id, str) or not 1 <= len(case_id) <= 128 or case_id in seen:
            raise ValueError('Cases require unique case_id strings of 1–128 characters.')
        seen.add(case_id)
        for field, limit in [('input_prompt', 1024), ('expected_output', 4096)]:
            if not isinstance(case.get(field), str) or len(case[field]) > limit:
                raise ValueError(f'{field} must be text up to {limit} characters.')
        if not isinstance(case.get('slice', 'all'), str) or not 1 <= len(case.get('slice', 'all')) <= 64:
            raise ValueError('Slice names must have 1–64 characters.')
        for field in ('source_group_id', 'sample_id'):
            if field in case and (not isinstance(case[field], str) or not 1 <= len(case[field]) <= 128):
                raise ValueError(f'{field} must be an identifier of 1–128 characters when supplied.')


def _aggregate_metrics(results):
    groups = {}
    for result in results:
        for slice_name in dict.fromkeys(['all', result['slice_name']]):
            groups.setdefault(slice_name, []).append(result)
    metrics = []
    for slice_name, cases in groups.items():
        n = len(cases)
        accuracy = sum(c['passed'] for c in cases) / n
        # Wilson intervals retain uncertainty for all-pass/all-fail and small samples.
        z = 1.959963984540054
        denominator = 1 + z * z / n
        center = (accuracy + z * z / (2 * n)) / denominator
        radius = z * math.sqrt(accuracy * (1 - accuracy) / n + z * z / (4 * n * n)) / denominator
        lower, upper = max(0, center - radius), min(1, center + radius)
        bounds = {'lower': round(lower, 4), 'upper': round(upper, 4), 'ci_low': round(lower, 4), 'ci_high': round(upper, 4), 'confidence': 0.95, 'method': 'wilson'}
        metrics.append({'key': 'accuracy', 'slice_name': slice_name, 'value': round(accuracy, 4), 'sample_count': n, 'uncertainty_interval': bounds})
    return metrics


@transaction.atomic
def execute_evaluation_run(run, runner_fn, *, baseline_runner_fn=None, decoding_params=None):
    """Execute actual caller-owned inference; persist scores only after every case succeeds."""
    decoding_params = decoding_params or {'max_tokens': 8}
    results, baseline_results = [], []
    run.status = EvaluationRun.Status.RUNNING
    run.save(update_fields=['status', 'updated_at'])
    for index, case in enumerate(run.suite_version.cases or []):
        case_id = str(case.get('case_id') or case.get('id') or index)
        prompt = str(case.get('input_prompt') or case.get('input') or '')
        expected = str(case.get('expected_output') or '')
        slice_name = str(case.get('slice') or 'all')
        predicted = runner_fn(prompt, decoding_params)
        if not isinstance(predicted, str):
            raise ValueError('Model inference must return decoded text.')
        score, passed = default_eval_scorer(predicted, expected, run.suite_version.scorer_type, run.suite_version.scorer_config)
        if not math.isfinite(score):
            raise ValueError('Scorer returned a non-finite value.')
        result = {'case_id': case_id, 'input_prompt': prompt, 'candidate_output': predicted, 'expected_output': expected, 'score': score, 'passed': passed, 'failure_reason': '' if passed else f'Expected {expected!r}, got {predicted!r}', 'slice_name': slice_name}
        results.append(result)
        if baseline_runner_fn is not None:
            baseline_output = baseline_runner_fn(prompt, decoding_params)
            if not isinstance(baseline_output, str):
                raise ValueError('Baseline inference must return decoded text.')
            baseline_score, baseline_passed = default_eval_scorer(baseline_output, expected, run.suite_version.scorer_type, run.suite_version.scorer_config)
            if not math.isfinite(baseline_score):
                raise ValueError('Baseline scorer returned a non-finite value.')
            baseline_results.append({**result, 'candidate_output': baseline_output, 'score': baseline_score, 'passed': baseline_passed})
    for result in results:
        EvaluationCaseResult.objects.create(tenant_id=run.tenant_id, run=run, **result)
    for metric in _aggregate_metrics(results):
        EvaluationMetric.objects.create(tenant_id=run.tenant_id, run=run, **metric)
    if baseline_results:
        run.protocol_ref = {**run.protocol_ref, 'baseline_results': baseline_results, 'baseline_metrics': _aggregate_metrics(baseline_results)}
    run.status = EvaluationRun.Status.COMPLETED
    run.completed_at = timezone.now()
    run.save(update_fields=['status', 'completed_at', 'protocol_ref', 'updated_at'])
    return run


@transaction.atomic
def run_baseline_evaluation(suite_version: EvaluationSuiteVersion, candidate_model_version: ModelVersion, *, baseline_model_version: Optional[ModelVersion] = None, runner_fn: Optional[Callable[[str, dict[str, Any]], str]] = None, decoding_params: Optional[dict[str, Any]] = None) -> EvaluationRun:
    """Existing callback/fixture entrypoint; the absent callback remains explicitly simulation."""
    decoding_params = decoding_params or {'temperature': 0.0, 'max_tokens': 256, 'seed': 42}
    run = EvaluationRun.objects.create(tenant_id=candidate_model_version.tenant_id, project_id=candidate_model_version.project_id, suite_version=suite_version, candidate_model_version=candidate_model_version, baseline_model_version=baseline_model_version,
        protocol_ref={**decoding_params, 'execution_evidence': {'level': 'integrated_execution' if runner_fn is not None else 'simulation', 'source': 'Caller-supplied runner callback; hardware unverified' if runner_fn is not None else 'Fixture echoes expected answers; no candidate inference'}}, status=EvaluationRun.Status.PENDING)
    if runner_fn is None:
        # Explicit fixture compatibility, never used by the HTTP local execution action.
        outputs = iter(str(c.get('expected_output') or '') for c in suite_version.cases or [])
        runner_fn = lambda _prompt, _params: next(outputs)
    return execute_evaluation_run(run, runner_fn, decoding_params=decoding_params)
