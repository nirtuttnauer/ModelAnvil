"""Release lifecycle management: Frozen gates, audited exceptions, export bundles, quantization, and endpoint promotion/rollback (TECH-020-021, TECH-024 / PRD Scenario 10)."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping, Optional, Sequence

from django.utils import timezone

from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.releases.models import (
    DeploymentRevision,
    GateResult,
    ReleaseException,
    ReleaseVersion,
    ServingEndpoint,
)
from modelanvil.runners.models import EvaluationRun, ModelVersion
from modelanvil.runners.evidence import release_evidence, evaluation_evidence


class ReleasePromotionBlockedError(Exception):
    """Raised when an attempt is made to promote an unqualified or failing release version."""
    pass


class TombstoneAccessDeniedError(Exception):
    """Raised when export bundle references a deleted or tombstoned asset (TECH-024)."""
    pass


def evaluate_release_gates(
    release_version: ReleaseVersion,
    criteria: Sequence[dict[str, Any]],  # [{"key": ..., "required_value": ..., "eval_run": ...}]
) -> bool:
    """Evaluate candidate release against frozen gate criteria.

    A failing criterion blocks promotion unless an audited exception is recorded (TECH-021).
    """
    # There is no trusted production qualification writer yet. Client metadata,
    # fixture scores and policy exceptions cannot establish runtime evidence.
    GateResult.objects.update_or_create(
        release_version=release_version, criterion_key="runtime_evidence",
        defaults={"tenant_id": release_version.tenant_id, "passed": False,
                  "details": release_evidence(release_version),
                  "evidence_digest": hashlib.sha256(b"production-runtime-unqualified").hexdigest(),
                  "checked_at": timezone.now()},
    )
    all_passed = False

    for crit in criteria:
        key = crit["key"]
        eval_run: Optional[EvaluationRun] = crit.get("eval_run")
        passed = False
        details = {}

        if key == "min_accuracy":
            req_acc = crit.get("required_value", 0.8)
            actual_acc = None
            if (eval_run and eval_run.status == EvaluationRun.Status.COMPLETED
                    and evaluation_evidence(eval_run)["production_qualified"]
                    and eval_run.candidate_model_version_id == release_version.model_version_id):
                acc_metric = eval_run.metrics.filter(key="accuracy").first()
                if acc_metric and acc_metric.value is not None:
                    actual_acc = acc_metric.value
                    passed = (actual_acc >= req_acc)
            details = {"required_accuracy": req_acc, "actual_accuracy": actual_acc}

        elif key == "license_compliance":
            # Check model license is open/permissive
            lic = release_version.model_version.license_evidence if release_version.model_version else "unknown"
            passed = lic in ("apache-2.0", "mit", "bsd-3-clause", "open-rail")
            details = {"license": lic}

        elif key == "no_regression":
            passed = False
            details = {"regression_detected": not passed}

        elif key == "quantization_eval":
            passed = False
            details = crit.get("details", {})

        else:
            passed = False

        evidence_digest = hashlib.sha256(
            f"{key}-{passed}-{json.dumps(details, sort_keys=True)}".encode("utf-8")
        ).hexdigest()

        gate_res, _ = GateResult.objects.update_or_create(
            release_version=release_version,
            criterion_key=key,
            defaults={
                "tenant_id": release_version.tenant_id,
                "evaluation_run": eval_run,
                "passed": passed,
                "evidence_digest": evidence_digest,
                "details": details,
                "checked_at": timezone.now(),
            },
        )

        # Check if failing gate has an authorized exception
        has_valid_exception = gate_res.exceptions.filter(is_valid=True).exists()
        if not passed and not has_valid_exception:
            all_passed = False

    if all_passed:
        release_version.status = ReleaseVersion.Status.QUALIFIED
    else:
        release_version.status = ReleaseVersion.Status.REJECTED

    release_version.save()
    return all_passed


def record_policy_exception(
    gate_result: GateResult,
    actor_id: str,
    permitted_policy_id: str,
    reason: str,
) -> ReleaseException:
    """Record an audited policy exception waiving a failing gate result (TECH-021)."""
    exc = ReleaseException.objects.create(
        tenant_id=gate_result.tenant_id,
        gate_result=gate_result,
        actor_id=actor_id,
        permitted_policy_id=permitted_policy_id,
        reason=reason,
        is_valid=True,
    )
    # Re-evaluate parent version status if all failing gates now have exceptions
    parent = gate_result.release_version
    unresolved_failures = False
    for gr in parent.gate_results.all():
        if not gr.passed and not gr.exceptions.filter(is_valid=True).exists():
            unresolved_failures = True
            break

    if not unresolved_failures and release_evidence(parent)["production_qualified"]:
        parent.status = ReleaseVersion.Status.QUALIFIED
        parent.save()

    return exc


def quantize_and_evaluate(
    release_version: ReleaseVersion,
    quantization_type: str = "int8",
    baseline_accuracy: float = 0.90,
    allowed_accuracy_drop: float = 0.03,
) -> dict[str, Any]:
    """Evaluate supported quantization, post-conversion accuracy, and size reduction (PRD Scenario 10)."""
    # INT8 yields ~50% byte size reduction with minimal perplexity degradation
    compression_ratio = 0.50 if quantization_type == "int8" else 0.25
    post_accuracy = round(baseline_accuracy - 0.015, 4)
    accuracy_drop = round(baseline_accuracy - post_accuracy, 4)
    passed = accuracy_drop <= allowed_accuracy_drop

    spec = {
        "quantization_type": quantization_type,
        "compression_ratio": compression_ratio,
        "baseline_accuracy": baseline_accuracy,
        "post_accuracy": post_accuracy,
        "accuracy_drop": accuracy_drop,
        "evaluation_passed": False,
        "simulated_evaluation_passed": passed,
        "execution_evidence": {"level": "simulation", "source": "Fixed compression and accuracy deltas; no weight conversion or inference"},
    }

    release_version.quantization_spec = spec
    release_version.save()
    return spec


def export_release_bundle(release_version: ReleaseVersion) -> dict[str, Any]:
    """Export release metadata and any verified, committed local model bundle."""
    # Re-check tombstones (fail closed on tombstoned assets)
    if release_version.model_version:
        tombstone = DeletionTombstone.objects.filter(
            tenant_id=release_version.tenant_id,
            resource_id=str(release_version.model_version.model_version_id),
        ).first()
        if tombstone:
            raise TombstoneAccessDeniedError(
                f"Cannot export: Base model version {release_version.model_version.model_version_id} has been tombstoned ({tombstone.reason})."
            )

    from modelanvil.releases.artifacts import release_model_bundle
    material = release_model_bundle(release_version)

    model_card = release_version.model_card or {
        "name": release_version.release.name,
        "revision_no": release_version.revision_no,
        "candidate_type": release_version.candidate_type,
        "license": release_version.model_version.license_evidence if release_version.model_version else "apache-2.0",
        "intended_use": "Configuration preview; weights and production inference unverified",
        "hashes": {
            "weights_sha256": None,
        },
    }

    bundle = {
        "execution_evidence": release_evidence(release_version),
        "release_name": release_version.release.name,
        "release_version_id": str(release_version.release_version_id),
        "revision_no": release_version.revision_no,
        "status": release_version.status,
        "model_card": model_card,
        "quantization": release_version.quantization_spec,
        "gate_results": [
            {
                "criterion_key": gr.criterion_key,
                "passed": gr.passed,
                "waived_by_exception": gr.exceptions.filter(is_valid=True).exists(),
            }
            for gr in release_version.gate_results.all()
        ],
        "independent_loading_evidence": {
            "load_tested": False,
            "runtime_format": None,
            "verified_at": None,
            "reason": "Metadata-only release export contains no executable model weights",
        },
    }
    if material:
        artifact = material["artifact"]
        bundle["model_artifact"] = {
            "artifact_id": str(artifact.artifact_id), "sha256": artifact.sha256,
            "byte_size": artifact.byte_size, "download_endpoint": f"/api/v1/artifacts/{artifact.artifact_id}/download/",
        }
        bundle["model_bundle"] = material["bundle"]
        bundle["loading_verification"] = material["verification"]
        bundle["independent_loading_evidence"]["reason"] = "Committed model bytes passed a local runtime smoke check; independent loading and production qualification remain unverified."
        bundle["independent_loading_evidence"]["runtime_format"] = material["verification"].get("format")
    return bundle


def promote_endpoint(
    endpoint: ServingEndpoint,
    release_version: ReleaseVersion,
    serving_config: Optional[dict[str, Any]] = None,
    *, simulation: bool = False,
) -> DeploymentRevision:
    """Promote an endpoint to a qualified release version with atomic pointer update (TECH-021)."""
    if not simulation and not release_evidence(release_version)["production_qualified"]:
        raise ReleasePromotionBlockedError("Production serving is unqualified. Fixture gates and policy exceptions cannot authorize deployment.")
    if not simulation and release_version.status not in (ReleaseVersion.Status.QUALIFIED, ReleaseVersion.Status.PROMOTED):
        raise ReleasePromotionBlockedError(
            f"Cannot promote release version in status '{release_version.status}'. Must be 'qualified'."
        )

    prev_deployment = endpoint.active_deployment
    next_rev = (endpoint.deployments.count()) + 1

    deployment = DeploymentRevision.objects.create(
        tenant_id=endpoint.tenant_id,
        endpoint=endpoint,
        release_version=release_version,
        revision_no=next_rev,
        previous_deployment=prev_deployment,
        serving_config={**(serving_config or {}), "execution_evidence": {"level": "simulation", "live_serving_verified": False}},
        readiness_state=DeploymentRevision.ReadinessState.PENDING,
    )

    endpoint.active_deployment = deployment
    endpoint.save()

    release_version.status = ReleaseVersion.Status.DRAFT if simulation else ReleaseVersion.Status.PROMOTED
    release_version.save()

    return deployment


def rollback_endpoint(endpoint: ServingEndpoint) -> DeploymentRevision:
    """Atomic rollback of serving endpoint to previous deployment revision (PRD Scenario 10)."""
    current_dep = endpoint.active_deployment
    if not current_dep or not current_dep.previous_deployment:
        raise ValueError("Cannot rollback: No previous deployment revision exists for this endpoint.")

    target_prev = current_dep.previous_deployment

    # Re-verify tombstone on target release before rollback (TECH-024)
    if target_prev.release_version.model_version:
        tombstone = DeletionTombstone.objects.filter(
            tenant_id=endpoint.tenant_id,
            resource_id=str(target_prev.release_version.model_version.model_version_id),
        ).first()
        if tombstone:
            raise TombstoneAccessDeniedError(
                f"Rollback denied: Target deployment model {target_prev.release_version.model_version.model_version_id} has been tombstoned."
            )

    current_dep.readiness_state = DeploymentRevision.ReadinessState.ROLLED_BACK
    current_dep.save()

    endpoint.active_deployment = target_prev
    endpoint.save()

    return target_prev
