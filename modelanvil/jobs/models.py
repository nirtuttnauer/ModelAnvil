"""Durable execution models (WP-03).

This is the heart of the control plane. The design follows ADR-001:

* **Job** — the durable unit of work. Created and validated in one
  transaction with an outbox event. Has a stable state machine.
* **JobAttempt** — a single execution of a job by a worker. Carries a
  **fencing token** and a renewable **lease**. Stale (lower-token) results
  are rejected, so a crashed-and-restarted worker can never commit a
  duplicate or out-of-order result.
* **Worker / WorkerPool** — execution capacity. Workers have bounded
  slots and a status (available / busy / draining). A saturated or
  draining worker stops claiming.
* **Outbox** — transactional event queue. Domain writes and their dispatch
  events commit atomically; a flusher publishes to the broker and marks the
  event confirmed. Duplicate delivery is possible and handled by idempotent
  claims.

Reconciliation (lease expiry, abandoned claims) is driven by
:func:`reconcile_expired_leases`, safe to run from a management command or
a periodic task.
"""

from __future__ import annotations

import hashlib
import secrets

from datetime import datetime
from typing import Any, Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel


def _lease_delta() -> timezone.timedelta:
    return timezone.timedelta(seconds=settings.MODELANVIL["worker_lease_seconds"])


def _grace_delta() -> timezone.timedelta:
    return timezone.timedelta(seconds=settings.MODELANVIL["worker_heartbeat_grace_seconds"])


def _worker_credential_expiry() -> datetime:
    return timezone.now() + timezone.timedelta(
        seconds=settings.MODELANVIL["worker_credential_seconds"]
    )


def dispatch_topic(tenant_id: Any, queue_name: str, pool_name: str) -> str:
    """Return a tenant-isolated broker queue name for a worker pool."""
    return f"tenant.{tenant_id}.{queue_name or pool_name}"


def generate_worker_credential() -> tuple[str, str]:
    """Return a one-time worker bearer token and its stored SHA-256 digest."""
    token = "mkw_" + secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Worker pools & workers
# ---------------------------------------------------------------------------
class WorkerPool(TenantContextModel):
    """A named pool of workers (e.g. ``gpu-training``, ``cpu-eval``)."""

    class ResultEgress(models.TextChoices):
        ENVELOPE = "envelope"
        METADATA_ONLY = "metadata_only"

    name = models.CharField(max_length=100)
    status = models.CharField(
        max_length=16, choices=[("active", "active"), ("draining", "draining")], default="active"
    )
    queue_name = models.CharField(max_length=200, blank=True)
    # Compatibility default is not a private-workload safety claim.
    result_egress = models.CharField(max_length=16, choices=ResultEgress.choices, default=ResultEgress.ENVELOPE)

    class Meta:
        unique_together = ("tenant_id", "name")
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class Worker(TenantContextModel):
    """A registered worker with bounded execution slots."""

    class Status(models.TextChoices):
        AVAILABLE = "available"
        BUSY = "busy"
        DRAINING = "draining"
        OFFLINE = "offline"

    name = models.CharField(max_length=200)
    pool = models.ForeignKey(WorkerPool, on_delete=models.CASCADE, related_name="workers")
    capabilities = models.JSONField(default=dict, blank=True)
    slots = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.AVAILABLE)
    last_heartbeat_at = models.DateTimeField(null=True)
    drain_requested = models.BooleanField(default=False)
    drain_requested_at = models.DateTimeField(null=True, blank=True)
    drain_acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("tenant_id", "name")
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"

    @property
    def free_slots(self) -> int:
        return self.slots


class WorkerCredential(TenantContextModel):
    """Short-lived, revocable bearer credential bound to exactly one worker."""

    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="credentials")
    secret_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(default=_worker_credential_expiry, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "worker"),
                condition=models.Q(revoked_at__isnull=True),
                name="one_active_worker_credential",
            )
        ]
        indexes = [models.Index(fields=("tenant_id", "worker", "revoked_at"))]

    def clean(self) -> None:
        if self.worker_id and self.worker.tenant_id != self.tenant_id:
            raise ValidationError("Worker credential and worker must belong to the same tenant.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------
class Job(TenantContextModel):
    """A durable unit of work with a stable lifecycle."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        CANCELLED = "cancelled"
        INTERRUPTED = "interrupted"

    class DesiredAction(models.TextChoices):
        RUN = "run", "Run"
        CANCEL = "cancel", "Cancel"

    job_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, null=True, blank=True,
        related_name='execution_jobs')
    name = models.CharField(max_length=200)
    pool = models.ForeignKey(WorkerPool, on_delete=models.PROTECT, related_name="jobs")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    desired_action = models.CharField(
        max_length=16, choices=DesiredAction.choices, default=DesiredAction.RUN
    )
    requirements = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    # Execution bookkeeping (set on claim).
    claimed_by = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name="claimed_jobs"
    )
    fencing_token = models.CharField(max_length=64, blank=True)
    lease_expires_at = models.DateTimeField(null=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=0)  # 0 => use platform default
    priority = models.IntegerField(default=0)
    scheduled_at = models.DateTimeField(null=True)
    depends_on = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("-priority", "created_at")
        indexes = [
            models.Index(fields=["pool", "status"]),
            models.Index(fields=["status", "lease_expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.status}] foliage" if False else f"{self.name} [{self.status}]"

    @transaction.atomic
    def save(self, *args: Any, **kwargs: Any) -> None:
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            OutboxEvent.objects.create(
                tenant_id=self.tenant_id,
                topic=dispatch_topic(self.tenant_id, self.pool.queue_name, self.pool.name),
                payload={"event_type": "job.queued", "job_id": str(self.job_id)},
            )

    def effective_max_attempts(self) -> int:
        return self.max_attempts or settings.MODELANVIL["max_attempts_default"]

    @property
    def is_terminal(self) -> bool:
        return self.status in (self.Status.SUCCEEDED, self.Status.FAILED, self.Status.CANCELLED)


# ---------------------------------------------------------------------------
# JobAttempt
# ---------------------------------------------------------------------------
class JobAttempt(TenantContextModel):
    """One execution of a job by a worker.

    ``fencing_token`` is the monotonic guard: a worker may only commit a
    result whose token matches the current attempt's token. When a lease
    expires and the job is re-dispatched, a *new* attempt with a *new*
    token is created, invalidating the stale worker's token.
    """

    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        INTERRUPTED = "interrupted"
        EXPIRED = "expired"

    attempt_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="attempts")
    worker = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name="attempts"
    )
    fencing_token = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    lease_expires_at = models.DateTimeField(null=True)
    slots_reserved = models.PositiveSmallIntegerField(default=1)
    progress = models.FloatField(default=0.0)
    result_envelope = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["status", "lease_expires_at"]),
        ]

    def __str__(self) -> str:
        return f"attempt {self.attempt_id} of job {self.job_id}"

    def is_stale(self, fencing_token: str) -> bool:
        return self.fencing_token != fencing_token

    def lease_expired(self) -> bool:
        return self.lease_expires_at is not None and timezone.now() > self.lease_expires_at


class DeviceClaim(models.Model):
    """Internal physical-device coordination across tenants on one cooperating host/account.

    Tenant ownership is carried by the attempt. There is deliberately no public API:
    physical exclusion must not be split into independent tenant namespaces.
    """
    host_key = models.CharField(max_length=64)
    device_key = models.CharField(max_length=32)
    attempt = models.OneToOneField(JobAttempt, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['host_key','device_key'],name='job_host_device_claim_uniq')]


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------
class OutboxEvent(TenantContextModel):
    """A transactional event to be published to the dispatch broker.

    Written in the same transaction as the domain change that produced it.
    The flusher publishes and marks ``published_at``; unconfirmed events are
    retried. Idempotency is provided by the claim protocol, not by the
    broker.
    """

    event_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    topic = models.CharField(max_length=200)
    payload = models.JSONField(default=dict)
    published_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["published_at", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"outbox {self.topic} {self.event_id}"


@transaction.atomic
def publish_outbox_batch(publisher, limit: int = 100) -> int:
    """Publish pending events and mark only broker-confirmed deliveries.

    The event UUID is stable and must be used by consumers as their
    idempotency key. A crash after broker confirmation but before this
    transaction commits can redeliver the event (at-least-once delivery).
    """
    if limit <= 0:
        return 0
    pending = list(
        OutboxEvent.all_objects.filter(published_at__isnull=True)
        .order_by("created_at", "id")
        .select_for_update(skip_locked=True)[:limit]
    )
    delivered = 0
    for event in pending:
        event.attempts += 1
        message = {
            "event_id": str(event.event_id),
            "tenant_id": str(event.tenant_id),
            "topic": event.topic,
            "payload": event.payload,
        }
        try:
            confirmed = publisher(message)
            if not confirmed:
                raise RuntimeError("broker did not confirm delivery")
        except Exception as exc:  # broker failures leave the record retryable
            event.last_error = str(exc)[:2000]
            event.save(update_fields=("attempts", "last_error", "updated_at"))
            continue
        event.published_at = timezone.now()
        event.last_error = ""
        event.save(update_fields=("attempts", "published_at", "last_error", "updated_at"))
        delivered += 1
    return delivered


# ---------------------------------------------------------------------------
# Durable claim protocol
# ---------------------------------------------------------------------------
def _worker_matches(capabilities, requirements):
    if not isinstance(requirements, dict):
        return False
    if capabilities.get("task_plugin") and any(
        requirements.get(key) != capabilities.get(key) for key in ("task_plugin", "task_plugin_digest")
    ):
        return False
    return all(capabilities.get(name) == value for name, value in requirements.items() if name != "slots")

@transaction.atomic
def claim_job(worker: Worker, job: Optional[Job] = None) -> Optional[dict[str, Any]]:
    """Atomically claim a job for ``worker``.

    Returns a claim descriptor (job/attempt/fencing/lease) or ``None`` if
    there is no claimable work or the worker/pool is unavailable. Locks are
    acquired in job -> worker -> pool order so stale worker objects cannot
    overrun capacity and concurrent claims remain serialized.
    """
    from modelanvil.jobs.setup import setup_worker_ready
    current_worker = Worker.objects.filter(pk=worker.pk).first()
    if current_worker is None or not setup_worker_ready(current_worker):
        return None
    if current_worker.drain_requested:
        Worker.objects.filter(pk=worker.pk, drain_requested=True).update(drain_acknowledged_at=timezone.now())
        return None
    worker_identity = Worker.objects.filter(pk=worker.pk).values(
        "tenant_id", "pool_id", "capabilities", "slots"
    ).first()
    if worker_identity is None:
        return None

    candidates = Job.objects.select_for_update().filter(
        tenant_id=worker_identity["tenant_id"],
        pool_id=worker_identity["pool_id"],
        status=Job.Status.QUEUED,
    )
    if job is not None:
        candidates = candidates.filter(pk=job.pk)
    else:
        candidates = candidates.order_by("-priority", "created_at")
    capabilities = worker_identity["capabilities"]
    job = None
    for candidate in candidates.iterator():
        requirements = candidate.requirements
        if _worker_matches(capabilities, requirements):
            slots_req = requirements.get("slots", 1)
            try:
                slots_req = int(slots_req)
            except (ValueError, TypeError):
                slots_req = 1
            if slots_req > worker_identity["slots"]:
                continue
            job = candidate
            break
    if job is None:
        return None

    current_worker = Worker.objects.select_for_update().filter(pk=worker.pk).first()
    if (
        current_worker is None
        or current_worker.tenant_id != worker_identity["tenant_id"]
        or current_worker.pool_id != worker_identity["pool_id"]
        or current_worker.drain_requested
        or current_worker.status in (Worker.Status.DRAINING, Worker.Status.OFFLINE)
    ):
        return None

    slots_needed = 1
    if isinstance(job.requirements, dict) and "slots" in job.requirements:
        try:
            slots_needed = max(1, int(job.requirements["slots"]))
        except (ValueError, TypeError):
            slots_needed = 1

    if current_worker.slots < slots_needed:
        return None

    pool = WorkerPool.objects.select_for_update().filter(
        pk=current_worker.pool_id, tenant_id=current_worker.tenant_id
    ).first()
    if pool is None or pool.status != "active":
        return None
    if not _worker_matches(current_worker.capabilities, job.requirements):
        return None

    from modelanvil.runners.training.admission import gpu_claim_plan
    try:
        placement=gpu_claim_plan(job,current_worker)
    except (ValueError,KeyError,TypeError,OSError):
        return None
    device_claim=None
    if placement:
        DeviceClaim.objects.get_or_create(**placement)
        device_claim=DeviceClaim.objects.select_for_update().get(**placement)
        if device_claim.attempt_id:
            occupied=JobAttempt.all_objects.filter(pk=device_claim.attempt_id,status='running',lease_expires_at__gt=timezone.now()).exists()
            if occupied:
                return None

    fencing_token = secrets.token_hex(16)
    lease_until = timezone.now() + _lease_delta()

    # Conditional claim: only wins if the job is still queued.
    won = (
        Job.objects.filter(id=job.id, status=Job.Status.QUEUED)
        .update(
            status=Job.Status.RUNNING,
            claimed_by=current_worker,
            fencing_token=fencing_token,
            lease_expires_at=lease_until,
        )
    )
    if not won:
        return None

    attempt = JobAttempt.objects.create(
        job=job,
        tenant_id=current_worker.tenant_id,
        worker=current_worker,
        fencing_token=fencing_token,
        status=JobAttempt.Status.RUNNING,
        lease_expires_at=lease_until,
        slots_reserved=slots_needed,
    )
    if device_claim:
        device_claim.attempt=attempt
        device_claim.save(update_fields=['attempt'])
    job.attempt_count += 1
    job.save(update_fields=["attempt_count"])
    current_worker.slots -= slots_needed
    current_worker.save(update_fields=("slots", "updated_at"))
    worker.slots = current_worker.slots

    return {
        "job_id": str(job.job_id),
        "tenant_id": str(job.tenant_id),
        "attempt_id": str(attempt.attempt_id),
        "fencing_token": fencing_token,
        "lease_expires_at": lease_until,
        "slots_reserved": slots_needed,
        "payload": job.payload,
        "requirements": job.requirements,
        "result_egress": pool.result_egress,
    }


@transaction.atomic
def renew_lease(attempt: JobAttempt, fencing_token: str, progress: Optional[float] = None) -> bool:
    """Renew only the current, unexpired running attempt."""
    now = timezone.now()
    current = JobAttempt.objects.select_for_update().filter(pk=attempt.pk).first()
    if (
        current is None
        or current.status != JobAttempt.Status.RUNNING
        or current.fencing_token != fencing_token
        or current.lease_expires_at is None
        or current.lease_expires_at <= now
    ):
        return False
    job = Job.objects.select_for_update().filter(pk=current.job_id).first()
    if (
        job is None
        or job.status != Job.Status.RUNNING
        or job.fencing_token != fencing_token
        or job.claimed_by_id != current.worker_id
    ):
        return False

    current.lease_expires_at = now + _lease_delta()
    if progress is not None:
        current.progress = progress
    current.save(update_fields=("lease_expires_at", "progress", "updated_at"))
    job.lease_expires_at = current.lease_expires_at
    job.save(update_fields=("lease_expires_at", "updated_at"))
    if current.worker_id:
        Worker.objects.filter(pk=current.worker_id).update(last_heartbeat_at=now)
    setattr(attempt, "lease_expires_at", current.lease_expires_at)
    setattr(attempt, "desired_action", job.desired_action)
    return True


@transaction.atomic
def commit_result(
    attempt: JobAttempt,
    fencing_token: str,
    status: str,
    result_envelope: Optional[dict] = None,
    error: str = "",
) -> bool:
    """Commit a verified result. Returns False if the token is stale.

    On success the worker's slot is released and the job transitions to a
    terminal state.
    """
    now = timezone.now()
    current = JobAttempt.objects.select_for_update().filter(pk=attempt.pk).first()
    if (
        current is None
        or current.status != JobAttempt.Status.RUNNING
        or current.fencing_token != fencing_token
        or current.lease_expires_at is None
        or current.lease_expires_at <= now
    ):
        return False
    job = Job.objects.select_for_update().filter(pk=current.job_id).first()
    if (
        job is None
        or job.status != Job.Status.RUNNING
        or job.fencing_token != fencing_token
        or job.claimed_by_id != current.worker_id
    ):
        return False

    # Keep job -> worker -> pool lock order consistent with claims. Serialize
    # result publication with administrator policy updates; do not rely only
    # on the HTTP view's earlier policy read.
    if current.worker_id:
        worker = Worker.objects.select_for_update().filter(
            pk=current.worker_id, tenant_id=current.tenant_id
        ).first()
        if worker is None:
            return False
    pool = WorkerPool.objects.select_for_update().filter(
        pk=job.pool_id, tenant_id=current.tenant_id
    ).first()
    if pool is None:
        return False
    if pool.result_egress not in WorkerPool.ResultEgress.values or (
        pool.result_egress == WorkerPool.ResultEgress.METADATA_ONLY
        and (result_envelope is not None or error)
    ):
        raise ValidationError("Result content is forbidden by the pool egress policy.")

    current.status = status
    current.result_envelope = result_envelope
    current.error = error
    current.completed_at = now
    current.save(update_fields=("status", "result_envelope", "error", "completed_at", "updated_at"))

    if current.worker_id:
        Worker.objects.filter(id=current.worker_id).update(
            slots=models.F("slots") + current.slots_reserved
        )

    if status == JobAttempt.Status.SUCCEEDED:
        job_status = Job.Status.SUCCEEDED
    elif status == JobAttempt.Status.FAILED:
        job_status = Job.Status.FAILED
    elif job.desired_action == Job.DesiredAction.CANCEL:
        job_status = Job.Status.CANCELLED
    else:
        job_status = Job.Status.INTERRUPTED
    if job.payload.get('type') == 'qualified_training':
        if job.desired_action == Job.DesiredAction.CANCEL:
            job_status = Job.Status.CANCELLED
        from modelanvil.runners.training.registry import finalize_job
        finalize_job(job, job_status)
    if job.payload.get('type') == 'qualified_evaluation':
        if job.desired_action == Job.DesiredAction.CANCEL:
            job_status = Job.Status.CANCELLED
        from modelanvil.runners.eval_worker import finalize_evaluation
        finalize_evaluation(job, job_status)
    if job.payload.get('type') == 'model_import':
        from modelanvil.runners.model_catalog import finalize_import
        finalize_import(job, job_status)
    if job.payload.get('type') == 'specialist_inference':
        if job.desired_action == Job.DesiredAction.CANCEL:
            job_status = Job.Status.CANCELLED
        from modelanvil.runners.specialist_jobs import finalize_job as finalize_specialist
        finalize_specialist(job, job_status)
    if job.payload.get('type') == 'recipe_execution':
        if job.desired_action == Job.DesiredAction.CANCEL:
            job_status = Job.Status.CANCELLED
        from modelanvil.data.recipe_jobs import finalize_job as finalize_recipe
        finalize_recipe(job, job_status)
    if job.payload.get('type') == 'embedding_build':
        from modelanvil.rag.embedding_jobs import finalize_job as finalize_embedding
        if job.desired_action == Job.DesiredAction.CANCEL:
            job_status = Job.Status.CANCELLED
        job_status = finalize_embedding(job, job_status)
        if job_status == Job.Status.FAILED and current.status == JobAttempt.Status.SUCCEEDED:
            current.status = JobAttempt.Status.FAILED
            current.save(update_fields=['status','updated_at'])
    if job.payload.get('type') == 'qualified_dpo' or hasattr(job, 'alignment_run'):
        from modelanvil.runners.alignment.mps_dpo import finalize_job as finalize_dpo
        job_status = finalize_dpo(job, job_status)
        if job_status == Job.Status.FAILED and current.status == JobAttempt.Status.SUCCEEDED:
            current.status = JobAttempt.Status.FAILED
            current.save(update_fields=['status', 'updated_at'])
    DeviceClaim.objects.filter(attempt_id=current.pk).update(attempt=None)
    job.status = job_status
    job.lease_expires_at = None
    job.claimed_by = None
    job.fencing_token = ""
    job.save(update_fields=("status", "lease_expires_at", "claimed_by", "fencing_token", "updated_at"))
    return True


@transaction.atomic
def reconcile_expired_leases(*, job_ids=None) -> int:
    """Reconcile attempts whose leases have expired.

    Marks the attempt expired, releases the worker slot, and re-queues the
    job if it has remaining attempts. Returns the number of reconciled
    attempts. Safe to run periodically.
    """
    now = timezone.now()
    expired = JobAttempt.objects.select_for_update().filter(
        status=JobAttempt.Status.RUNNING, lease_expires_at__lt=now
    ).order_by("lease_expires_at", "pk")
    if job_ids is not None:
        expired = expired.filter(job__job_id__in=job_ids)

    count = 0
    for attempt in expired:
        job = Job.objects.select_for_update().filter(pk=attempt.job_id).first()
        current_job_attempt = bool(
            job
            and job.status == Job.Status.RUNNING
            and job.fencing_token == attempt.fencing_token
        )
        cancellation_pending = bool(
            current_job_attempt and job.desired_action == Job.DesiredAction.CANCEL
        )
        attempt.status = JobAttempt.Status.EXPIRED
        attempt.completed_at = now
        attempt.error = attempt.error or "Worker lease expired."
        attempt.save(update_fields=("status", "completed_at", "error", "updated_at"))
        if attempt.worker_id:
            if cancellation_pending:
                Worker.objects.filter(id=attempt.worker_id).update(status=Worker.Status.OFFLINE)
            else:
                Worker.objects.filter(id=attempt.worker_id).update(
                    slots=models.F("slots") + attempt.slots_reserved
                )
        if current_job_attempt and cancellation_pending:
            job.status = Job.Status.INTERRUPTED
            job.claimed_by = None
            job.lease_expires_at = None
            job.fencing_token = ""
            job.save(update_fields=("status", "claimed_by", "lease_expires_at", "fencing_token", "updated_at"))
        elif current_job_attempt:
            if job.attempt_count < job.effective_max_attempts():
                job.status = Job.Status.QUEUED
                job.claimed_by = None
                job.lease_expires_at = None
                job.fencing_token = ""
                job.save(update_fields=("status", "claimed_by", "lease_expires_at", "fencing_token", "updated_at"))
                OutboxEvent.objects.create(
                    tenant_id=job.tenant_id,
                    topic=dispatch_topic(job.tenant_id, job.pool.queue_name, job.pool.name),
                    payload={"event_type": "job.queued", "job_id": str(job.job_id)},
                )
            else:
                job.status = Job.Status.FAILED
                job.claimed_by = None
                job.lease_expires_at = None
                job.fencing_token = ""
                job.save(update_fields=("status", "claimed_by", "lease_expires_at", "fencing_token", "updated_at"))
        if current_job_attempt and job.status in (Job.Status.FAILED, Job.Status.INTERRUPTED) and job.payload.get('type') == 'qualified_training':
            from modelanvil.runners.training.registry import finalize_job
            finalize_job(job, job.status)
        if current_job_attempt and job.status in (Job.Status.FAILED, Job.Status.INTERRUPTED) and job.payload.get('type') == 'qualified_evaluation':
            from modelanvil.runners.eval_worker import finalize_evaluation
            finalize_evaluation(job, job.status)
        if current_job_attempt and job.status in (Job.Status.FAILED, Job.Status.INTERRUPTED) and job.payload.get('type') == 'specialist_inference':
            from modelanvil.runners.specialist_jobs import finalize_job as finalize_specialist
            finalize_specialist(job, job.status)
        if current_job_attempt and job.status in (Job.Status.FAILED, Job.Status.INTERRUPTED) and job.payload.get('type') == 'recipe_execution':
            from modelanvil.data.recipe_jobs import finalize_job as finalize_recipe
            finalize_recipe(job, job.status)
        if current_job_attempt and job.status in (Job.Status.FAILED, Job.Status.INTERRUPTED, Job.Status.CANCELLED) and job.payload.get('type') == 'embedding_build':
            from modelanvil.rag.embedding_jobs import finalize_job as finalize_embedding
            finalize_embedding(job, job.status)
        DeviceClaim.objects.filter(attempt_id=attempt.pk).update(attempt=None)
        if current_job_attempt and (job.payload.get('type') == 'qualified_dpo' or hasattr(job, 'alignment_run')):
            from modelanvil.runners.alignment.mps_dpo import finalize_job as finalize_dpo
            resolved = finalize_dpo(job, job.status)
            if resolved != job.status:
                job.status = resolved
                job.save(update_fields=['status', 'updated_at'])
        count += 1
    return count
