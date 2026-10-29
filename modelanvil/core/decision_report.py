"""Compare candidate and baseline cases without treating a small sample as a win."""
from __future__ import annotations

import math

DECISIVE_CASES = 30


def wilson_interval(passed, total):
    if type(total) is not int or total < 1 or type(passed) is not int or not 0 <= passed <= total:
        raise ValueError('Uncertainty needs a counted sample.')
    accuracy = passed / total
    z = 1.959963984540054
    denominator = 1 + z * z / total
    center = (accuracy + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(accuracy * (1 - accuracy) / total + z * z / (4 * total * total)) / denominator
    lower, upper = max(0.0, center - radius), min(1.0, center + radius)
    return {'lower': round(lower, 4), 'upper': round(upper, 4), 'confidence': 0.95, 'method': 'wilson'}


def _rows(values, label):
    if not isinstance(values, list) or not values or any(not isinstance(row, dict) for row in values):
        raise ValueError(f'{label} must be a non-empty list of case rows.')
    rows = {}
    for row in values:
        case_id = row.get('case_id')
        passed = row.get('passed')
        if not isinstance(case_id, str) or not case_id or type(passed) is not bool or case_id in rows:
            raise ValueError(f'{label} rows need a unique case id and a boolean pass.')
        slice_name = row.get('slice_name') or row.get('slice') or 'all'
        if not isinstance(slice_name, str) or not slice_name:
            raise ValueError(f'{label} slice names must be text.')
        rows[case_id] = {'passed': passed, 'slice_name': slice_name}
    return rows


def _relation(candidate_interval, baseline_interval, count):
    if count < DECISIVE_CASES or not (candidate_interval['lower'] > baseline_interval['upper'] or candidate_interval['upper'] < baseline_interval['lower']):
        return 'inconclusive'
    if candidate_interval['lower'] > baseline_interval['upper']:
        return 'improved'
    return 'regressed'


def _slice_report(name, candidate_rows, baseline_rows):
    count = len(candidate_rows)
    candidate_passed = sum(row['passed'] for row in candidate_rows)
    baseline_passed = sum(baseline_rows[row['case_id']]['passed'] for row in candidate_rows)
    candidate_interval = wilson_interval(candidate_passed, count)
    baseline_interval = wilson_interval(baseline_passed, count)
    return {
        'slice': name,
        'sample_count': count,
        'candidate_accuracy': round(candidate_passed / count, 4),
        'baseline_accuracy': round(baseline_passed / count, 4),
        'candidate_uncertainty': candidate_interval,
        'baseline_uncertainty': baseline_interval,
        'relation': _relation(candidate_interval, baseline_interval, count),
    }


def build_report(*, candidate_rows, baseline_rows, evidence_level, status, pins=None, candidate_id=None,
                 baseline_id=None, suite_id=None, runtime_seconds=None):
    """Describe a comparison. Small samples stay inconclusive instead of becoming a win."""
    pins = pins or {}
    report = {
        'eligible': False,
        'production_qualified': False,
        'hardware_qualified': False,
        'loss_is_not_quality': True,
        'minimum_decisive_cases': DECISIVE_CASES,
        'candidate_model_version': candidate_id,
        'baseline_model_version': baseline_id,
        'suite_version': suite_id,
        'prompt_format': pins.get('prompt_format'),
        'candidate_pins': pins.get('candidate'),
        'baseline_pins': pins.get('baseline'),
        'runtime_seconds': runtime_seconds if isinstance(runtime_seconds, (int, float)) and math.isfinite(runtime_seconds) else None,
        'decisive': False,
        'recommended_outcome': 'unavailable',
        'sample_count': 0,
        'candidate_accuracy': None,
        'baseline_accuracy': None,
        'candidate_uncertainty': None,
        'baseline_uncertainty': None,
        'slices': [],
        'improved_slices': [],
        'regressed_slices': [],
        'gate': {'passed': False, 'reason': 'This comparison cannot support a decision.'},
    }
    if status != 'completed' or evidence_level != 'integrated_execution':
        report['gate']['reason'] = 'A decision report requires a completed comparison with integrated execution evidence.'
        return report
    try:
        candidate = _rows(candidate_rows, 'Candidate')
        baseline = _rows(baseline_rows, 'Baseline')
    except ValueError as exc:
        report['gate']['reason'] = str(exc)
        return report
    if set(candidate) != set(baseline):
        report['gate']['reason'] = 'Candidate and baseline must cover the same cases.'
        return report
    paired = [{'case_id': case_id, **row} for case_id, row in sorted(candidate.items())]
    overall = _slice_report('all', paired, baseline)
    slices = [overall]
    names = sorted({row['slice_name'] for row in paired if row['slice_name'] != 'all'})
    for name in names:
        chosen = [row for row in paired if row['slice_name'] == name]
        slices.append(_slice_report(name, chosen, baseline))
    improved = [row['slice'] for row in slices if row['relation'] == 'improved']
    regressed = [row['slice'] for row in slices if row['relation'] == 'regressed']
    decisive = overall['relation'] in ('improved', 'regressed')
    if overall['relation'] == 'improved' and not regressed:
        recommended = 'accept'
        reason = 'Candidate accuracy is above the baseline on this sample, and the uncertainty intervals do not overlap.'
    elif overall['relation'] == 'regressed':
        recommended = 'reject'
        reason = 'Candidate accuracy is below the baseline on this sample, and the uncertainty intervals do not overlap.'
    elif overall['relation'] == 'improved' and regressed:
        recommended = 'inconclusive'
        reason = 'At least one slice regressed, so this comparison is not an accept.'
    else:
        recommended = 'inconclusive'
        reason = f'A sample under {DECISIVE_CASES} cases, or overlapping uncertainty, cannot be called a win or a loss.'
    report.update({
        'eligible': True,
        'decisive': decisive,
        'recommended_outcome': recommended,
        'sample_count': overall['sample_count'],
        'candidate_accuracy': overall['candidate_accuracy'],
        'baseline_accuracy': overall['baseline_accuracy'],
        'candidate_uncertainty': overall['candidate_uncertainty'],
        'baseline_uncertainty': overall['baseline_uncertainty'],
        'slices': slices,
        'improved_slices': improved,
        'regressed_slices': regressed,
        'gate': {'passed': recommended == 'accept', 'reason': reason},
    })
    return report


def report_for_run(run):
    from modelanvil.core.activation import job_timing
    from modelanvil.runners.evidence import evaluation_evidence

    evidence = evaluation_evidence(run)
    protocol = run.protocol_ref or {}
    pins = protocol.get('pins') if isinstance(protocol.get('pins'), dict) else {}
    candidate_rows = [
        {'case_id': row.case_id, 'passed': row.passed, 'slice_name': row.slice_name}
        for row in run.case_results.order_by('case_id')
    ]
    runtime = None
    if run.job_id:
        timing = job_timing(run.job)
        runtime = timing.get('execution_seconds')
    return build_report(
        candidate_rows=candidate_rows,
        baseline_rows=protocol.get('baseline_results') or [],
        evidence_level=evidence.get('level'),
        status=run.status,
        pins=pins,
        candidate_id=str(run.candidate_model_version_id) if run.candidate_model_version_id else None,
        baseline_id=str(run.baseline_model_version_id) if run.baseline_model_version_id else None,
        suite_id=str(run.suite_version_id) if run.suite_version_id else None,
        runtime_seconds=runtime,
    )
