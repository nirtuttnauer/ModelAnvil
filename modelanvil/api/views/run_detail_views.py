"""Read-only run-detail projection joining one logical run and its evidence.

The browser links a durable job, a training run and an evaluation run through
one deep link. This module projects the recorded rows behind that link: the
job, its worker attempts, pinned inputs, checkpoints, metrics, budget
accounting and the recorded evidence level. It reports only what was written to
the database; it never executes, resumes or replays work, and every recovery
step is reported as unavailable with the blocking reason spelled out.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.urls import path
from django.utils import timezone
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.core.pagination import CursorPagination
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role, role_at_least, get_accessible_queryset
from modelanvil.jobs.access import accessible_jobs, cancellation_endpoint
from modelanvil.jobs.models import Job, JobAttempt, Worker
from modelanvil.runners.evidence import evaluation_evidence, training_evidence
from modelanvil.runners.models import EvaluationRun, TrainingRun

KINDS = ("job", "training", "evaluation")
MAX_METRICS = 200
MAX_CHECKPOINTS = 50
MAX_USAGE_EVENTS = 25
DESIRED_NOTE = (
    "Desired action is recorded separately from observed state; the worker "
    "acknowledges it, and this view never assumes it took effect."
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _bounded(rows: list[Any], limit: int) -> dict[str, Any]:
    """Keep the most recent rows of a chronological series."""
    return {"total": len(rows), "truncated": len(rows) > limit, "rows": rows[-limit:]}


def _is_worker_run(run) -> bool:
    return (getattr(run, "hardware_config", None) or {}).get("execution_mode") == "worker"


def _permission(request) -> dict[str, Any]:
    role = getattr(request, "modelanvil_role", None)
    return {
        "role": role,
        "required": Role.ENGINEER,
        "satisfied": role_at_least(role, Role.ENGINEER),
    }


def _usage_projection(tenant_id, job_id) -> dict[str, Any]:
    if job_id is None:
        return {"reservations": [], "events": [], "events_truncated": False}
    reservations = BudgetReservation.all_objects.filter(
        tenant_id=tenant_id, job_id=job_id
    ).select_related("policy").order_by("reserved_at")
    events = UsageEvent.objects.filter(tenant_id=tenant_id, reservation__job_id=job_id).order_by(
        "-occurred_at"
    )[:MAX_USAGE_EVENTS]
    return {
        "reservations": [
            {
                "reservation_id": str(item.reservation_id),
                "policy": str(item.policy_id),
                "policy_name": item.policy.name,
                "unit": item.policy.unit,
                "state": item.state,
                "estimated_amount": str(item.estimated_amount),
                "settled_amount": None if item.settled_amount is None else str(item.settled_amount),
                "reserved_at": _iso(item.reserved_at),
                "settled_at": _iso(item.settled_at),
            }
            for item in reservations
        ],
        "events": [
            {
                "usage_id": str(event.usage_id),
                "quantity": str(event.quantity),
                "unit": event.unit,
                "reservation": str(event.reservation_id) if event.reservation_id else None,
                "occurred_at": _iso(event.occurred_at),
                "detail": event.detail,
            }
            for event in events
        ],
        "events_truncated": len(events) >= MAX_USAGE_EVENTS,
    }


def _ownership_projection(job: Job | None) -> dict[str, Any]:
    if job is None:
        return {
            "state": "not_applicable",
            "worker": None,
            "worker_status": None,
            "lease_expires_at": None,
            "reason": "This run has no durable job, so no worker holds it.",
        }
    if job.status != Job.Status.RUNNING:
        return {
            "state": "released",
            "worker": None,
            "worker_status": None,
            "lease_expires_at": _iso(job.lease_expires_at),
            "reason": f"The job is '{job.status}' and holds no worker claim.",
        }
    worker = job.claimed_by
    if worker is None:
        return {
            "state": "unknown",
            "worker": None,
            "worker_status": None,
            "lease_expires_at": _iso(job.lease_expires_at),
            "reason": (
                "The job records a running state without a worker claim; ownership is unknown "
                "and no actor can be attributed to this run."
            ),
        }
    lease_expired = job.lease_expires_at is not None and job.lease_expires_at <= timezone.now()
    if worker.status == Worker.Status.OFFLINE or lease_expired:
        return {
            "state": "lost",
            "worker": worker.name,
            "worker_status": worker.status,
            "lease_expires_at": _iso(job.lease_expires_at),
            "reason": (
                "The claiming worker is offline or its lease expired; the run stops progressing "
                "until lease reconciliation records a terminal state or re-queues the job."
            ),
        }
    return {
        "state": "held",
        "worker": worker.name,
        "worker_status": worker.status,
        "lease_expires_at": _iso(job.lease_expires_at),
        "reason": "The recorded worker claim is current until its lease expires.",
    }


def _resume_candidate(run, checkpoints, pins) -> dict[str, Any]:
    """Report the committed checkpoint a resume would restart from, if any."""
    latest = max(checkpoints, key=lambda item: item.step) if checkpoints else None
    if latest is None:
        return {
            "available": False,
            "reason": "No checkpoint has been committed for this run, so there is nothing to resume from.",
            "checkpoint_id": None,
            "step": None,
            "state_digest": None,
            "contract_digest": None,
        }
    contract = (latest.weights_manifest or {}).get("pins") or {}
    blockers = []
    if not latest.is_valid:
        blockers.append("The latest checkpoint is recorded as invalid.")
    if latest.step != run.current_step:
        blockers.append("The latest checkpoint does not match the committed training cursor.")
    if not pins or contract.get("contract_digest") != pins.get("contract_digest"):
        blockers.append("The latest checkpoint was written under a different pinned runtime contract.")
    return {
        "available": not blockers,
        "reason": (
            "The latest committed checkpoint matches the pinned runtime contract and the training cursor."
            if not blockers
            else " ".join(blockers)
        ),
        "checkpoint_id": str(latest.checkpoint_id),
        "step": latest.step,
        "state_digest": latest.state_digest,
        "contract_digest": contract.get("contract_digest"),
    }


def _checkpoint_projection(run, pins) -> dict[str, Any]:
    checkpoints = list(run.checkpoints.all())
    checkpoints.sort(key=lambda item: item.step)
    rows = [
        {
            "checkpoint_id": str(checkpoint.checkpoint_id),
            "step": checkpoint.step,
            "state_digest": checkpoint.state_digest,
            "is_valid": checkpoint.is_valid,
            "contract_digest": (checkpoint.weights_manifest or {}).get("pins", {}).get("contract_digest"),
            "weights_sha256": _weights_sha256(checkpoint.weights_manifest or {}),
            "created_at": _iso(checkpoint.created_at),
        }
        for checkpoint in checkpoints
    ]
    return {**_bounded(rows, MAX_CHECKPOINTS), "resume_candidate": _resume_candidate(run, checkpoints, pins)}


def _weights_sha256(manifest) -> str | None:
    weights = manifest.get("weights") if isinstance(manifest.get("weights"), dict) else manifest
    return weights.get("weights_sha256")


def _period_start(policy) -> date:
    local_day = timezone.localdate(timezone.now())
    if policy.period == BudgetPolicy.Period.DAILY:
        return local_day
    if policy.period == BudgetPolicy.Period.MONTHLY:
        return local_day.replace(day=1)
    return date(1970, 1, 1)


def _budget_projection(run) -> dict[str, Any]:
    """Recheck budget authority for this run's job against the ledger."""
    reservation_id = getattr(run, "resource_reservation_id", None)
    if not reservation_id:
        return {
            "state": "none",
            "policy": None,
            "reservable": False,
            "headroom": None,
            "reason": "This run holds no budget reservation, so no compute budget backs a retry.",
        }
    reservation = BudgetReservation.all_objects.filter(
        tenant_id=run.tenant_id, reservation_id=reservation_id
    ).select_related("policy").first()
    if reservation is None:
        return {
            "state": "missing",
            "policy": None,
            "reservable": False,
            "headroom": None,
            "reason": "The reservation recorded for this run is no longer present.",
        }
    policy = reservation.policy
    base = {"policy": str(policy.policy_id), "policy_name": policy.name}
    if reservation.state != BudgetReservation.State.RESERVED:
        return {
            **base,
            "state": reservation.state,
            "reservable": False,
            "headroom": None,
            "reason": (
                "The reservation for this job is already settled or released. The accounting "
                "ledger keys reservations per job and refuses a second charge, so the recorded "
                "state would not back a re-queued execution."
            ),
        }
    if not policy.enabled:
        return {
            **base,
            "state": reservation.state,
            "reservable": False,
            "headroom": None,
            "reason": "The budget policy behind this run is disabled.",
        }
    committed = BudgetReservation.all_objects.filter(
        tenant_id=run.tenant_id, policy=policy, period_start=_period_start(policy)
    ).aggregate(total=Sum(Case(
        When(state=BudgetReservation.State.RESERVED, then=F("estimated_amount")),
        When(state=BudgetReservation.State.SETTLED, then=F("settled_amount")),
        default=Value(Decimal("0")),
        output_field=DecimalField(max_digits=24, decimal_places=6),
    )))["total"] or Decimal("0")
    headroom = policy.limit_amount - committed
    return {
        **base,
        "state": reservation.state,
        "reservable": headroom >= 0,
        "headroom": str(headroom),
        "reason": (
            "An enabled policy holds an open reservation for this job."
            if headroom >= 0
            else "The policy limit is already consumed, so no reservation covers a retry."
        ),
    }


def _recovery_projection(request, run, job, pins) -> dict[str, Any]:
    """Explain whether the recorded evidence permits a resume, and what blocks it."""
    permission = _permission(request)
    resume_candidate = _resume_candidate(run, list(run.checkpoints.all()), pins)
    budget = _budget_projection(run)
    blocked_by = []
    if not permission["satisfied"]:
        blocked_by.append(
            f"This API key holds the '{permission['role']}' role; recovery actions require "
            f"the '{Role.ENGINEER}' role."
        )
    if job is None:
        blocked_by.append("This run has no durable job to re-queue.")
    elif job.status not in (Job.Status.FAILED, Job.Status.INTERRUPTED):
        blocked_by.append(
            f"The job is '{job.status}'; recovery applies to failed or interrupted jobs only."
        )
    elif job.desired_action != Job.DesiredAction.RUN:
        blocked_by.append("The job still carries an unacknowledged cancel request.")
    if not resume_candidate["available"]:
        blocked_by.append(resume_candidate["reason"])
    if not budget["reservable"]:
        blocked_by.append(budget["reason"])
    blocked_by.append(
        "This API is read-only and exposes no action that re-reserves budget and re-queues the "
        "job. Recovery stays an operator path until that write contract exists."
    )
    return {
        "available": False,
        "permission": permission,
        "checkpoint": resume_candidate,
        "budget": budget,
        "blocked_by": blocked_by,
        "operator_path": (
            "Lease reconciliation re-queues a job automatically while attempts remain. Otherwise "
            "launch a new run from the same pinned inputs; prior attempts, checkpoints and usage "
            "events for this run are append-only and stay readable."
        ),
        "preserves_history": (
            "Attempts, checkpoints and recorded usage for this run are append-only; no action "
            "offered in this view deletes or rewrites them."
        ),
    }


def _cancel_projection(job: Job | None, run) -> dict[str, Any]:
    if job is not None:
        requested = (
            job.desired_action == Job.DesiredAction.CANCEL and job.status != Job.Status.CANCELLED
        )
        active = job.status in (Job.Status.QUEUED, Job.Status.RUNNING)
        return {
            "available": active and not requested,
            "requested": requested,
            "acknowledged": job.status == Job.Status.CANCELLED,
            "endpoint": cancellation_endpoint(job),
            "blocked_by": (
                ["Cancellation is already requested and stays requested until the worker acknowledges it."]
                if requested
                else ([] if active else [f"The job is '{job.status}' and no longer accepts cancellation."])
            ),
        }
    terminal = run.status in (
        TrainingRun.Status.COMPLETED,
        TrainingRun.Status.FAILED,
        TrainingRun.Status.CANCELLED,
    )
    return {
        "available": not terminal,
        "requested": run.status == TrainingRun.Status.CANCELLED,
        "acknowledged": run.status == TrainingRun.Status.CANCELLED,
        "endpoint": f"/api/v1/training-runs/{run.run_id}/cancel/",
        "blocked_by": (
            [] if not terminal else [f"The run is '{run.status}' and no longer accepts cancellation."]
        ),
    }


def _training_links(run, job) -> dict[str, Any]:
    evaluations = EvaluationRun.objects.filter(
        tenant_id=run.tenant_id, candidate_model_version=run.output_model_version
    ) if run.output_model_version_id else EvaluationRun.objects.none()
    return {
        "job": str(job.job_id) if job else None,
        "training_run": str(run.run_id),
        "output_model_version": str(run.output_model_version.model_version_id)
        if run.output_model_version_id
        else None,
        "base_model_version": str(run.base_model_version.model_version_id)
        if run.base_model_version_id
        else None,
        "tokenizer_version": str(run.tokenizer_version.tokenizer_id)
        if run.tokenizer_version_id
        else None,
        "dataset_revision": str(run.dataset_revision.revision_id) if run.dataset_revision_id else None,
        "evaluation_runs": [str(item.run_id) for item in evaluations],
    }


def _training_payload(request, run) -> dict[str, Any]:
    job = run.job
    pins = (run.hardware_config or {}).get("pins") or {}
    metrics = [{key: value for key, value in row.items() if key != "sample_id"} for row in (run.metrics_log or [])]
    return {
        "kind": "training",
        "id": str(run.run_id),
        "name": job.name if job else f"Training run {str(run.run_id)[:8]}",
        "project": str(run.project_id) if run.project_id else None,
        "execution_mode": "worker" if _is_worker_run(run) else "simulation",
        "observed": {
            "state": run.status,
            # The durable job can disagree with the run's own state while an
            # attempt is reconciled or re-queued; both recorded values are shown.
            "job_state": job.status if job else None,
            "current_step": run.current_step,
            "total_steps": run.total_steps,
            "progress": (run.current_step / run.total_steps) if run.total_steps else None,
            "latest_loss": run.latest_loss,
            "attempts": f"{job.attempt_count}/{job.effective_max_attempts()}" if job else None,
            "created_at": _iso(run.created_at),
            "started_at": _iso(run.started_at),
            "completed_at": _iso(run.completed_at),
            "updated_at": _iso(run.updated_at),
        },
        "desired": {
            "action": job.desired_action if job else "cancel" if run.status == TrainingRun.Status.CANCELLED else "run",
            "acknowledged": (job.status == Job.Status.CANCELLED) if job
            else run.status in (TrainingRun.Status.CANCELLED, TrainingRun.Status.COMPLETED, TrainingRun.Status.FAILED),
            "note": DESIRED_NOTE,
        },
        "inputs": {
            "dataset_revision": str(run.dataset_revision.revision_id) if run.dataset_revision_id else None,
            "dataset_manifest_digest": run.dataset_manifest_digest or None,
            "base_model_version": str(run.base_model_version.model_version_id)
            if run.base_model_version_id
            else None,
            "tokenizer_version": str(run.tokenizer_version.tokenizer_id)
            if run.tokenizer_version_id
            else None,
            "recipe_type": run.recipe_type,
            "initialization_seed": run.initialization_seed,
            "total_steps": run.total_steps,
            "runtime_contract": pins.get("contract_digest"),
            "pinned_inputs": pins or None,
            "job_payload": job.payload if job else None,
            "job_requirements": job.requirements if job else None,
        },
        "metrics": {**_bounded(metrics, MAX_METRICS), "latest_loss": run.latest_loss},
        "checkpoints": _checkpoint_projection(run, pins),
        "usage": _usage_projection(run.tenant_id, job.job_id if job else None),
        "links": _training_links(run, job),
        "evidence": training_evidence(run),
        "actions": {
            "cancel": _cancel_projection(job, run),
            "resume": _recovery_projection(request, run, job, pins),
        },
        "ownership": _ownership_projection(job),
    }


def _job_payload(request, job) -> dict[str, Any]:
    run = job.training_runs.first()
    return {
        "kind": "job",
        "id": str(job.job_id),
        "name": job.name,
        "project": None,
        "execution_mode": "worker",
        "observed": {
            "state": job.status,
            "job_state": job.status,
            "current_step": None,
            "total_steps": None,
            "progress": None,
            "latest_loss": None,
            "attempts": f"{job.attempt_count}/{job.effective_max_attempts()}",
            "created_at": _iso(job.created_at),
            "started_at": None,
            "completed_at": None,
            "updated_at": _iso(job.updated_at),
        },
        "desired": {
            "action": job.desired_action,
            "acknowledged": job.status == Job.Status.CANCELLED,
            "note": DESIRED_NOTE,
        },
        "inputs": {
            "payload": job.payload,
            "requirements": job.requirements,
            "priority": job.priority,
            "pool": job.pool.name,
            "pool_status": job.pool.status,
            "depends_on": job.depends_on,
            "training_run": str(run.run_id) if run else None,
        },
        "metrics": {"total": 0, "truncated": False, "rows": [], "latest_loss": None},
        "checkpoints": None,
        "usage": _usage_projection(job.tenant_id, job.job_id),
        "links": {
            "job": str(job.job_id),
            "training_run": str(run.run_id) if run else None,
            "evaluation_runs": [],
            "dataset_revision": None,
            "model_version": None,
        },
        "evidence": None,
        "actions": {
            "cancel": _cancel_projection(job, None),
            "resume": {
                "available": False,
                "permission": _permission(request),
                "blocked_by": [
                    "This API is read-only and exposes no re-queue action. Lease reconciliation "
                    "re-queues a job while attempts remain; otherwise resubmit through the jobs API.",
                ],
                "operator_path": (
                    "Job attempts are append-only; re-queuing never removes the attempts that "
                    "already recorded a failure."
                ),
                "preserves_history": "Job attempts are append-only and are never removed.",
            },
        },
        "ownership": _ownership_projection(job),
    }


def _evaluation_payload(request, run) -> dict[str, Any]:
    metrics = [
        {
            "key": metric.key,
            "slice_name": metric.slice_name,
            "value": metric.value,
            "sample_count": metric.sample_count,
            "uncertainty_interval": metric.uncertainty_interval,
        }
        for metric in run.metrics.all()
    ]
    candidate = run.candidate_model_version
    source_run = candidate.metadata.get("source_run_id") if candidate else None
    terminal = run.status in (EvaluationRun.Status.COMPLETED, EvaluationRun.Status.FAILED)
    return {
        "kind": "evaluation",
        "id": str(run.run_id),
        "name": f"Evaluation {str(run.run_id)[:8]}",
        "project": str(run.project_id) if run.project_id else None,
        "execution_mode": "configuration",
        "observed": {
            "state": run.status,
            "job_state": None,
            "current_step": None,
            "total_steps": None,
            "progress": None,
            "latest_loss": None,
            "attempts": None,
            "created_at": _iso(run.created_at),
            "started_at": _iso(getattr(run, "started_at", None)),
            "completed_at": _iso(run.completed_at),
            "updated_at": _iso(run.updated_at),
        },
        "desired": {
            "action": "run",
            "acknowledged": terminal,
            "note": (
                "An evaluation records configuration and its callback results; it is never "
                "leased to a worker and has no cancel action."
            ),
        },
        "inputs": {
            "suite_version": str(run.suite_version.suite_version_id) if run.suite_version_id else None,
            "suite_name": run.suite_version.suite.name if run.suite_version_id else None,
            "candidate_model_version": str(candidate.model_version_id) if candidate else None,
            "baseline_model_version": str(run.baseline_model_version.model_version_id)
            if run.baseline_model_version_id
            else None,
            "protocol_ref": run.protocol_ref,
        },
        "metrics": {**_bounded(metrics, MAX_METRICS), "latest_loss": None},
        "checkpoints": None,
        "usage": _usage_projection(run.tenant_id, None),
        "links": {
            "job": None,
            "evaluation_run": str(run.run_id),
            "training_run": source_run,
            "model_version": str(candidate.model_version_id) if candidate else None,
            "dataset_revision": None,
        },
        "evidence": evaluation_evidence(run),
        "actions": {
            "cancel": {
                "available": False,
                "requested": False,
                "acknowledged": False,
                "endpoint": None,
                "blocked_by": ["Evaluations are recorded by the API and expose no cancellation."],
            },
            "resume": {
                "available": False,
                "permission": _permission(request),
                "blocked_by": [
                    "Evaluations carry no checkpoints, so there is nothing to resume from; "
                    "re-running creates a new evaluation run and keeps this record intact."
                ],
                "preserves_history": "Recorded metrics and case results are never rewritten.",
            },
        },
        "ownership": {
            "state": "not_applicable",
            "worker": None,
            "worker_status": None,
            "lease_expires_at": None,
            "reason": "Evaluations are recorded by the API, not leased to a worker.",
        },
    }


def _resolve(kind: str, run_id):
    tenant_id = get_active_tenant()
    if tenant_id is None or kind not in KINDS:
        return None
    if kind == "job":
        return accessible_jobs().filter(job_id=run_id).select_related("pool").first()
    if kind == "training":
        return (
            get_accessible_queryset(TrainingRun).filter(run_id=run_id)
            .select_related(
                "job",
                "pool",
                "tokenizer_version",
                "base_model_version",
                "dataset_revision",
                "output_model_version",
            )
            .prefetch_related("checkpoints")
            .first()
        )
    return (
        get_accessible_queryset(EvaluationRun).filter(run_id=run_id)
        .select_related("suite_version", "candidate_model_version", "baseline_model_version")
        .prefetch_related("metrics")
        .first()
    )


class RunDetailView(APIView):
    """One durable projection of a logical run and the evidence behind it."""

    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER

    def get(self, request, kind, run_id):
        record = _resolve(kind, run_id)
        if record is None:
            raise NotFound()
        if kind == "job":
            payload = _job_payload(request, record)
        elif kind == "training":
            payload = _training_payload(request, record)
        else:
            payload = _evaluation_payload(request, record)
        payload["generated_at"] = _iso(timezone.now())
        return Response(payload)


class RunDetailAttemptsView(APIView):
    """Cursor-paged worker attempts for the job linked to one run."""

    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER

    def get(self, request, kind, run_id):
        tenant_id = get_active_tenant()
        if tenant_id is None:
            raise NotFound()
        job = None
        if kind == "job":
            job = _resolve(kind, run_id)
        elif kind == "training":
            run = _resolve(kind, run_id)
            job = run.job if run else None
        else:
            raise NotFound()
        if job is None:
            raise NotFound()
        attempts = JobAttempt.objects.filter(tenant_id=tenant_id, job=job).select_related("worker")
        paginator = CursorPagination()
        paginator.ordering = "-started_at"
        page = paginator.paginate_queryset(attempts, request, view=self)
        rows = [
            {
                "attempt_id": str(attempt.attempt_id),
                "job_id": str(job.job_id),
                "worker": attempt.worker.name if attempt.worker_id else None,
                "worker_status": attempt.worker.status if attempt.worker_id else None,
                "status": attempt.status,
                "progress": attempt.progress,
                "error": attempt.error,
                "lease_expires_at": _iso(attempt.lease_expires_at),
                "started_at": _iso(attempt.started_at),
                "completed_at": _iso(attempt.completed_at),
                "has_result": attempt.result_envelope is not None,
            }
            for attempt in (page or [])
        ]
        return paginator.get_paginated_response(rows)


urlpatterns = [
    path("run-details/<str:kind>/<uuid:run_id>/", RunDetailView.as_view(), name="run-detail"),
    path(
        "run-details/<str:kind>/<uuid:run_id>/attempts/",
        RunDetailAttemptsView.as_view(),
        name="run-detail-attempts",
    ),
]
