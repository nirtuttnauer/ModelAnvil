"""Trusted, bounded local execution against the durable worker protocol.

Executors are installed by operators; job payloads are data and are never
interpreted as Python or shell commands. Long-running executors must call
``context.heartbeat()`` regularly, and stop promptly when it returns false.
"""
from __future__ import annotations

from typing import Any, Callable

from contracts import validate_envelope

from modelanvil.jobs.models import (
    Job,
    JobAttempt,
    Worker,
    claim_job,
    commit_result,
    renew_lease,
)

Executor = Callable[[dict[str, Any], "ExecutionContext"], dict[str, Any] | None]


class ExecutionContext:
    """Lease and cancellation callbacks exposed to a trusted executor."""

    def __init__(self, attempt: JobAttempt, fencing_token: str):
        self.attempt = attempt
        self.fencing_token = fencing_token
        self.lease_lost = False
        self.cancel_requested = False

    def heartbeat(self, progress: float | None = None) -> bool:
        """Renew the lease; return false when cancelled or fenced out."""
        from modelanvil.jobs.setup import credential_active
        worker = self.attempt.worker
        if worker.capabilities.get("setup_profile") and not credential_active(worker):
            self.lease_lost = True
            return False
        if not renew_lease(self.attempt, self.fencing_token, progress):
            self.lease_lost = True
            return False
        self.cancel_requested = (
            getattr(self.attempt, "desired_action", Job.DesiredAction.RUN)
            == Job.DesiredAction.CANCEL
        )
        return not self.cancel_requested


def execute_claim(
    worker: Worker,
    descriptor: dict[str, Any],
    executor: Executor,
) -> dict[str, Any]:
    """Execute and commit a previously claimed descriptor without re-claiming."""
    attempt = JobAttempt.all_objects.filter(
        attempt_id=descriptor.get("attempt_id"),
        worker_id=worker.pk,
        tenant_id=worker.tenant_id,
        fencing_token=descriptor.get("fencing_token"),
        status=JobAttempt.Status.RUNNING,
    ).select_related("job").first()
    if attempt is None or str(attempt.job.job_id) != descriptor.get("job_id"):
        return {"claimed": True, "committed": False, "status": "stale"}

    context = ExecutionContext(attempt, descriptor["fencing_token"])
    attempt_status = JobAttempt.Status.SUCCEEDED
    result_envelope = None
    error = ""
    try:
        result_envelope = executor(descriptor, context)
        if result_envelope is not None:
            validate_envelope(result_envelope)
    except Exception as exc:  # executor and contract failures are durable outcomes
        if context.lease_lost:
            return {"claimed": True, "committed": False, "status": "stale"}
        attempt_status = (
            JobAttempt.Status.INTERRUPTED
            if context.cancel_requested
            else JobAttempt.Status.FAILED
        )
        result_envelope = None
        if attempt_status == JobAttempt.Status.FAILED:
            error = f"{type(exc).__name__}: {exc}"[:4000]
    if context.lease_lost:
        return {"claimed": True, "committed": False, "status": "stale"}
    if context.cancel_requested:
        attempt_status = JobAttempt.Status.INTERRUPTED
        result_envelope = None

    committed = commit_result(
        attempt,
        descriptor["fencing_token"],
        attempt_status,
        result_envelope=result_envelope,
        error=error,
    )
    return {
        "claimed": True,
        "committed": committed,
        "status": attempt_status if committed else "stale",
    }


def execute_one(
    worker: Worker,
    executor: Executor,
) -> dict[str, Any]:
    """Claim and execute one compatible job, then commit through its fence."""
    descriptor = claim_job(worker)
    if descriptor is None:
        return {"claimed": False}
    return execute_claim(worker, descriptor, executor)
