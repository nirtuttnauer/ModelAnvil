"""Release gate evaluation rules for alignment policies (TECH-019, TECH-021 / PRD Scenario 13)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from modelanvil.runners.models import AlignmentRun, EvaluationRun, ModelVersion
from modelanvil.runners.evidence import evaluation_evidence


class AlignmentReleaseGateError(Exception):
    """Raised or recorded when alignment policy fails release criteria."""
    pass


@dataclass
class AlignmentReleaseGateResult:
    passed: bool
    promoted: bool
    rejection_reasons: list[str] = field(default_factory=list)
    independent_eval_score: Optional[float] = None
    baseline_eval_score: Optional[float] = None
    reward_hacking_detected: bool = False
    details: dict = field(default_factory=dict)


def evaluate_alignment_release_gate(
    alignment_run: AlignmentRun,
    independent_eval_run: Optional[EvaluationRun] = None,
    min_required_accuracy: float = 0.70,
) -> AlignmentReleaseGateResult:
    """Evaluate whether an aligned policy model meets strict independent release gates.

    CRITICAL INVARIANT: Rising learned reward alone CANNOT satisfy policy release gates without
    independent held-out human or verifier evaluation (TECH-019 / PRD Scenario 13).
    """
    reasons: list[str] = [
        "Bounded CPU alignment has no production model qualification."
        if alignment_run.execution_pins
        else "Alignment uses fixture execution; production model qualification is unavailable."
    ]
    output_model = alignment_run.output_model_version

    if not output_model:
        reasons.append("Alignment run has no output model version.")
        return AlignmentReleaseGateResult(
            passed=False, promoted=False, rejection_reasons=reasons
        )

    # Check 1: Stop limits & execution status
    if alignment_run.status != AlignmentRun.Status.COMPLETED:
        reasons.append(f"Alignment run did not complete successfully (status: {alignment_run.status}, stop reason: {alignment_run.stop_reason}).")

    # Check 2: Exploit & reward hacking check
    reward_hacking = alignment_run.latest_metrics.get("reward_hacking_detected", False)
    exploit_detected = alignment_run.latest_metrics.get("exploit_detected", False)
    if reward_hacking or exploit_detected:
        reasons.append("Policy promotion denied: Reward hacking / exploit detected during alignment run.")

    # Check 3: MANDATORY Independent Evaluation Check
    # Rising learned reward CANNOT satisfy release gates by itself!
    if independent_eval_run is None:
        reasons.append(
            "Policy promotion denied: Rising learned reward cannot satisfy release gates by itself. "
            "Independent held-out human or verifier evaluation is required."
        )

    indep_score = None
    baseline_eval_score = None

    if independent_eval_run is not None:
        if not evaluation_evidence(independent_eval_run)["production_qualified"]:
            reasons.append("Independent evaluation has no production runtime evidence.")
        if independent_eval_run.status != EvaluationRun.Status.COMPLETED:
            reasons.append(f"Independent evaluation run is not completed (status: {independent_eval_run.status}).")

        # Check 4: Accuracy on independent suite
        accuracy_metric = independent_eval_run.metrics.filter(key="accuracy").first()
        indep_score = accuracy_metric.value if accuracy_metric else None

        if indep_score is None:
            reasons.append("Independent evaluation has no valid accuracy metric.")
        elif indep_score < min_required_accuracy:
            reasons.append(
                f"Independent evaluation score ({indep_score}) is below required release threshold ({min_required_accuracy})."
            )

        # Check 5: Regression against baseline
        if independent_eval_run.baseline_model_version:
            baseline_metric = EvaluationRun.objects.filter(
                candidate_model_version=independent_eval_run.baseline_model_version,
                suite_version=independent_eval_run.suite_version,
                status=EvaluationRun.Status.COMPLETED,
            ).order_by("-completed_at").first()
            if baseline_metric:
                base_acc = baseline_metric.metrics.filter(key="accuracy").first()
                if base_acc and base_acc.value is not None:
                    baseline_eval_score = base_acc.value
                    if indep_score is not None and indep_score < baseline_eval_score:
                        reasons.append(
                            f"Regression detected: Aligned model score ({indep_score}) is lower than baseline ({baseline_eval_score})."
                        )

    passed = (len(reasons) == 0)
    if passed:
        output_model.state = ModelVersion.State.QUALIFIED
        output_model.save()
    else:
        output_model.state = ModelVersion.State.REJECTED
        output_model.save()

    return AlignmentReleaseGateResult(
        passed=passed,
        promoted=passed,
        rejection_reasons=reasons,
        independent_eval_score=indep_score,
        baseline_eval_score=baseline_eval_score,
        reward_hacking_detected=reward_hacking or exploit_detected,
        details={
            "output_model_version_id": str(output_model.model_version_id),
            "final_model_state": output_model.state,
            "alignment_algorithm": alignment_run.algorithm,
        },
    )
