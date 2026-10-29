"""Reproduction envelope for the pinned CPU character evaluation.

The policy stores a rule, not a tolerance. The tolerance is the maximum
absolute difference of each numeric field across three repeat runs. Text
and boolean fields have no tolerance. A failing check does not change the
policy id.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "scripts" / "cpu-character-eval-reproduction-policy.json"
REFERENCE_PATH = (
    ROOT / "docs" / "engineering" / "verification" / "anvil-021-cpu-character-eval" / "reference-report.json"
)
POLICY_ID = "cpu-character-eval-reproduction-v1"

_STORED_TOLERANCE_KEYS = {"tolerance", "absolute_tolerance", "numeric_tolerance", "tolerances"}
_MEASUREMENT_KEYS = {
    "candidate_output",
    "baseline_output",
    "score",
    "baseline_score",
    "passed",
    "baseline_passed",
    "weights_sha256",
    "candidate_weights_sha256",
    "baseline_weights_sha256",
    "value",
    "accuracy",
    "wall_seconds",
    "spread",
    "tolerances",
}
_EXACT_CASE = (
    "case_id",
    "input_prompt",
    "expected_output",
    "slice",
    "candidate_output",
    "baseline_output",
    "passed",
    "baseline_passed",
)
_NUMERIC_CASE = ("score", "baseline_score")
_EXACT_METRIC = ("key", "slice_name", "method")
_NUMERIC_METRIC = ("value", "sample_count", "lower", "upper")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_policy(path: Path = POLICY_PATH) -> dict:
    return load_json(path)


def load_reference(path: Path = REFERENCE_PATH) -> dict:
    return load_json(path)


def _forbidden_keys(document, forbidden: set[str], prefix: str = "") -> list[str]:
    found = []
    if isinstance(document, dict):
        for key, value in document.items():
            location = f"{prefix}.{key}" if prefix else key
            if key in forbidden:
                found.append(location)
            found.extend(_forbidden_keys(value, forbidden, location))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            found.extend(_forbidden_keys(value, forbidden, f"{prefix}[{index}]"))
    return found


def reference_problems(policy: dict, reference: dict) -> list[str]:
    """Problems in the pre-measurement policy and reference. Empty means usable."""
    problems = []
    if policy.get("id") != POLICY_ID:
        problems.append(f"policy id is {policy.get('id')!r}")
    if reference.get("policy_id") != policy.get("id"):
        problems.append("reference policy_id does not match the policy id")
    if reference.get("contains_measurement") is not False:
        problems.append("reference contains_measurement must be false")
    if policy.get("claim") != "reproduction_only" or reference.get("claim") != "reproduction_only":
        problems.append("claim must be reproduction_only")
    if policy.get("quality_claim") is not False:
        problems.append("quality_claim must be false")
    stored = _forbidden_keys(policy, _STORED_TOLERANCE_KEYS)
    if stored:
        problems.append("policy stores a tolerance: " + ", ".join(stored))
    measured = _forbidden_keys(reference, _MEASUREMENT_KEYS | _STORED_TOLERANCE_KEYS)
    if measured:
        problems.append("reference contains a measurement: " + ", ".join(measured))
    protocol = reference.get("protocol")
    if not isinstance(protocol, dict) or not protocol.get("cases") or not protocol.get("training_samples"):
        problems.append("reference protocol is missing pinned cases or training samples")
    if not isinstance(policy.get("spread_rule"), str) or "maximum absolute difference" not in policy["spread_rule"]:
        problems.append("spread rule is missing")
    if not isinstance(policy.get("widening"), str) or "new policy id" not in policy["widening"]:
        problems.append("widening rule is missing")
    return problems


def _metric(row: dict) -> dict:
    uncertainty = row.get("uncertainty") or {}
    return {
        "key": row["key"],
        "slice_name": row["slice_name"],
        "method": row.get("method") or uncertainty.get("method"),
        "value": row["value"],
        "sample_count": row["sample_count"],
        "lower": row["lower"] if "lower" in row else uncertainty["lower"],
        "upper": row["upper"] if "upper" in row else uncertainty["upper"],
    }


def canonical_report(report: dict) -> dict:
    cases = []
    for case in sorted(report["cases"], key=lambda item: item["case_id"]):
        cases.append({field: case[field] for field in (*_EXACT_CASE, *_NUMERIC_CASE)})
    metrics = sorted((_metric(row) for row in report["metrics"]), key=lambda item: (item["key"], item["slice_name"]))
    baseline = sorted(
        (_metric(row) for row in report["baseline_metrics"]),
        key=lambda item: (item["key"], item["slice_name"]),
    )
    return {
        "policy_id": report["policy_id"],
        "contains_measurement": True,
        "protocol": report["protocol"],
        "evidence_level": report["evidence_level"],
        "candidate_weights_sha256": report["candidate_weights_sha256"],
        "baseline_weights_sha256": report["baseline_weights_sha256"],
        "cases": cases,
        "metrics": metrics,
        "baseline_metrics": baseline,
    }


def exact_values(report: dict) -> dict:
    body = canonical_report(report)
    values = {
        "policy_id": body["policy_id"],
        "protocol": body["protocol"],
        "evidence_level": body["evidence_level"],
        "candidate_weights_sha256": body["candidate_weights_sha256"],
        "baseline_weights_sha256": body["baseline_weights_sha256"],
    }
    for index, case in enumerate(body["cases"]):
        for field in _EXACT_CASE:
            values[f"cases[{index}].{field}"] = case[field]
    for label, rows in (("metrics", body["metrics"]), ("baseline_metrics", body["baseline_metrics"])):
        for index, row in enumerate(rows):
            for field in _EXACT_METRIC:
                values[f"{label}[{index}].{field}"] = row[field]
    return values


def numeric_values(report: dict) -> dict[str, float]:
    body = canonical_report(report)
    values: dict[str, float] = {}
    for index, case in enumerate(body["cases"]):
        for field in _NUMERIC_CASE:
            values[f"cases[{index}].{field}"] = float(case[field])
    for label, rows in (("metrics", body["metrics"]), ("baseline_metrics", body["baseline_metrics"])):
        for index, row in enumerate(rows):
            for field in _NUMERIC_METRIC:
                values[f"{label}[{index}].{field}"] = float(row[field])
    return values


def measured_spread(repeats: list[dict]) -> dict:
    """Tolerance per numeric field. Exact disagreements are listed and not given a tolerance."""
    if len(repeats) != 3:
        raise ValueError("The spread rule uses exactly three repeat runs.")
    exact = [exact_values(item) for item in repeats]
    disagreements = []
    keys = list(exact[0])
    for key in keys:
        observed = [item[key] for item in exact]
        if any(item != observed[0] for item in observed[1:]):
            disagreements.append({"field": key, "values": observed})
    numbers = [numeric_values(item) for item in repeats]
    tolerances = {}
    for key in numbers[0]:
        observed = [item[key] for item in numbers]
        tolerances[key] = max(observed) - min(observed)
    return {"tolerances": tolerances, "exact_disagreements": disagreements}


def check_run(policy: dict, reference: dict, repeats: list[dict], candidate: dict) -> dict:
    """Check one run. Does not modify the policy or write a tolerance back."""
    problems = reference_problems(policy, reference)
    failures = [{"field": "policy", "reason": item} for item in problems]
    if len(repeats) != policy.get("repeat_runs"):
        failures.append({"field": "repeats", "reason": "three committed repeat runs are required"})
    if failures:
        return {"ok": False, "policy_id": policy.get("id"), "tolerances": {}, "failures": failures}
    spread = measured_spread(repeats)
    for item in repeats:
        if item.get("protocol") != reference["protocol"]:
            failures.append({"field": "protocol", "reason": "a repeat run does not match the saved reference"})
            break
        if item.get("evidence_level") != policy["evidence_level"]:
            failures.append({"field": "evidence_level", "reason": "a repeat run is not integrated_execution"})
            break
    for disagreement in spread["exact_disagreements"]:
        failures.append({
            "field": disagreement["field"],
            "reason": "exact field differed across the three repeat runs; the tolerance was not widened",
        })
    if candidate.get("protocol") != reference["protocol"]:
        failures.append({"field": "protocol", "reason": "the checked run does not match the saved reference"})
    if candidate.get("evidence_level") != policy["evidence_level"]:
        failures.append({"field": "evidence_level", "reason": "the checked run is not integrated_execution"})
    if not failures:
        baseline = exact_values(repeats[0])
        observed = exact_values(candidate)
        for key, expected in baseline.items():
            if observed.get(key) != expected:
                failures.append({
                    "field": key,
                    "reason": "exact field differs from the first repeat run; text and boolean fields have no tolerance",
                })
        first = numeric_values(repeats[0])
        current = numeric_values(candidate)
        for key, tolerance in spread["tolerances"].items():
            difference = abs(current[key] - first[key])
            if difference > tolerance:
                failures.append({
                    "field": key,
                    "reason": "numeric field exceeds the spread measured before this check",
                    "difference": difference,
                    "tolerance": tolerance,
                })
    return {
        "ok": not failures,
        "policy_id": policy["id"],
        "tolerances": spread["tolerances"],
        "exact_disagreements": spread["exact_disagreements"],
        "failures": failures,
    }
