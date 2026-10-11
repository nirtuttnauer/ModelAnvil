"""LLM-as-a-Judge Calibration Engine (Inter-rater agreement & bias detection).

Calculates:
- Statistical inter-rater agreement (Cohen's Kappa κ, percent agreement) against verified human judgments.
- Position bias (favoring Candidate A over Candidate B regardless of content).
- Verbosity bias (favoring longer responses over concise answers).
- Enforces strict platform qualification gate: judges with κ < 0.70 are rejected.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from django.utils import timezone

from modelanvil.runners.models import JudgeCalibration, ModelVersion


@dataclass(frozen=True)
class CalibrationResult:
    agreement_score: float  # Cohen's Kappa κ (-1.0 to +1.0)
    percent_agreement: float  # Raw proportion (0.0 to 1.0)
    position_bias_ratio: float  # Ratio of A choices vs 50%
    verbosity_bias_correlation: float  # Correlation between length difference and score
    status: str  # "qualified" | "rejected"
    rejection_reasons: list[str]


def compute_cohens_kappa(
    judge_choices: Sequence[str],
    human_choices: Sequence[str],
    categories: Sequence[str] = ("candidate_a", "candidate_b", "tie"),
) -> float:
    """Compute Cohen's Kappa κ between judge and human raters."""
    n = len(judge_choices)
    if n == 0 or len(human_choices) != n:
        raise ValueError("Non-matching or empty rating sequences.")

    # 1. Observed agreement Po
    observed_matches = sum(1 for j, h in zip(judge_choices, human_choices) if j == h)
    p_o = observed_matches / n

    # 2. Expected chance agreement Pe
    p_e = 0.0
    for cat in categories:
        p_j = sum(1 for j in judge_choices if j == cat) / n
        p_h = sum(1 for h in human_choices if h == cat) / n
        p_e += p_j * p_h

    if p_e >= 1.0:
        return 1.0 if p_o >= 1.0 else 0.0

    kappa = (p_o - p_e) / (1.0 - p_e)
    return max(-1.0, min(1.0, round(kappa, 4)))


def compute_position_bias(judge_choices: Sequence[str]) -> float:
    """Detect bias favoring Candidate A over Candidate B.

    Returns proportion of Candidate A selections among binary decisions.
    Neutral is 0.50. Deviation > 0.15 indicates significant position bias.
    """
    binary_choices = [c for c in judge_choices if c in ("candidate_a", "candidate_b")]
    if not binary_choices:
        return 0.50
    a_count = sum(1 for c in binary_choices if c == "candidate_a")
    return round(a_count / len(binary_choices), 4)


def compute_verbosity_bias(
    samples: Sequence[Mapping[str, Any]],
    judge_choices: Sequence[str],
) -> float:
    """Detect whether judge systematically favors longer answers.

    Calculates Pearson correlation between (length(A) - length(B)) and
    preference for A vs B. A correlation > 0.40 indicates verbosity bias.
    """
    length_diffs: list[float] = []
    preferred_a_indicators: list[float] = []

    for sample, choice in zip(samples, judge_choices):
        len_a = len(str(sample.get("candidate_a_text", "")))
        len_b = len(str(sample.get("candidate_b_text", "")))
        diff = float(len_a - len_b)

        if choice == "candidate_a":
            ind = 1.0
        elif choice == "candidate_b":
            ind = -1.0
        else:
            ind = 0.0

        length_diffs.append(diff)
        preferred_a_indicators.append(ind)

    n = len(length_diffs)
    if n < 2:
        return 0.0

    mean_diff = sum(length_diffs) / n
    mean_ind = sum(preferred_a_indicators) / n

    cov = sum((d - mean_diff) * (i - mean_ind) for d, i in zip(length_diffs, preferred_a_indicators))
    var_d = sum((d - mean_diff) ** 2 for d in length_diffs)
    var_i = sum((i - mean_ind) ** 2 for i in preferred_a_indicators)

    denom = math.sqrt(var_d * var_i)
    if denom == 0.0:
        return 0.0

    corr = cov / denom
    return max(-1.0, min(1.0, round(corr, 4)))


def calibrate_llm_judge(
    judge_model_version: ModelVersion,
    calibration_dataset: Sequence[Mapping[str, Any]],
    *,
    min_kappa_threshold: float = 0.70,
    max_position_bias_deviation: float = 0.15,
    max_verbosity_bias_threshold: float = 0.40,
) -> tuple[JudgeCalibration, CalibrationResult]:
    """Execute calibration against verified human gold labels and enforce qualification gates."""
    human_choices: list[str] = []
    judge_choices: list[str] = []

    for item in calibration_dataset:
        human_choices.append(item["human_choice"])
        judge_choices.append(item["judge_choice"])

    kappa = compute_cohens_kappa(judge_choices, human_choices)
    percent_agree = round(sum(1 for j, h in zip(judge_choices, human_choices) if j == h) / len(human_choices), 4)
    pos_bias = compute_position_bias(judge_choices)
    verbosity_bias = compute_verbosity_bias(calibration_dataset, judge_choices)

    rejections: list[str] = []
    if kappa < min_kappa_threshold:
        rejections.append(f"Agreement score κ={kappa:.2f} is below minimum threshold of {min_kappa_threshold:.2f}")

    if abs(pos_bias - 0.50) > max_position_bias_deviation:
        rejections.append(f"Position bias ratio {pos_bias:.2f} exceeds allowable deviation (0.50 ± {max_position_bias_deviation:.2f})")

    if verbosity_bias > max_verbosity_bias_threshold:
        rejections.append(f"Verbosity bias correlation {verbosity_bias:.2f} exceeds allowable threshold of {max_verbosity_bias_threshold:.2f}")

    status = "qualified" if not rejections else "rejected"

    cal_record = JudgeCalibration.objects.create(
        tenant_id=judge_model_version.tenant_id,
        judge_model_version=judge_model_version,
        human_sample_ref=f"samples_count_{len(calibration_dataset)}",
        agreement_score=kappa,
        status=status,
        metadata={
            "sample_count": len(calibration_dataset),
            "percent_agreement": percent_agree,
            "position_bias_ratio": pos_bias,
            "verbosity_bias_correlation": verbosity_bias,
            "rejection_reasons": rejections,
            "calibrated_at": timezone.now().isoformat(),
        },
    )

    result = CalibrationResult(
        agreement_score=kappa,
        percent_agreement=percent_agree,
        position_bias_ratio=pos_bias,
        verbosity_bias_correlation=verbosity_bias,
        status=status,
        rejection_reasons=rejections,
    )

    return cal_record, result
