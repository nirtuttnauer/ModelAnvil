"""Core models: tenant context, audit events, idempotency keys.

The tenancy model is the most important invariant in the platform. Two
enforcement layers work together:

1. **Field-level** — every tenant-scoped row carries a ``tenant_id`` and a
   database index on it. Queries *must* filter by tenant.
2. **Queryset-level** — :class:`TenantScopedQuerySet` /
   :class:`TenantScopedManager` automatically scope queries to the active
   tenant, so a missing manual filter cannot leak another tenant's data.

The active tenant is resolved per-request from the authenticated principal
(API key or session) and stored on the request; see
:mod:`modelanvil.core.tenancy`.
"""

from __future__ import annotations

import uuid

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.tenancy import get_active_tenant


class TenantScopedQuerySet(models.QuerySet):
    """A queryset automatically filtered to the active tenant.

    If no tenant is active (e.g. a system/background task), the queryset is
    *not* filtered — callers in that context are responsible for scoping.
    This is deliberate: silently returning nothing would hide bugs.
    """

    def _apply_tenant(self) -> "TenantScopedQuerySet":
        tenant = get_active_tenant()
        if tenant is not None:
            return super().filter(tenant_id=tenant)
        return self

    def all(self) -> "TenantScopedQuerySet":
        return self._apply_tenant()

    def filter(self, *args: Any, **kwargs: Any) -> "TenantScopedQuerySet":
        queryset = super().filter(*args, **kwargs)
        tenant = get_active_tenant()
        if tenant is not None:
            # Use the base QuerySet method: calling filter() here re-enters
            # this override and recurses indefinitely.
            queryset = models.QuerySet.filter(queryset, tenant_id=tenant)
        return queryset


class TenantScopedManager(models.Manager):
    def get_queryset(self) -> TenantScopedQuerySet:
        return TenantScopedQuerySet(self.model, using=self._db)._apply_tenant()

    def all(self) -> TenantScopedQuerySet:
        return self.get_queryset()


class TenantContextModel(models.Model):
    """Abstract base for every tenant-scoped model.

    Adds a ``tenant_id`` UUID and the scoped manager. Concrete models
    subclass this and define their own fields.
    """

    tenant_id = models.UUIDField(
        db_index=True,
        help_text="Owning tenant. Set automatically from the active tenant context on save.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantScopedManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.tenant_id:
            tenant = get_active_tenant()
            if tenant is None:
                raise ValueError(
                    f"{self.__class__.__name__}.tenant_id not set and no active "
                    "tenant context; refusing to save an unscoped row"
                )
            self.tenant_id = tenant
        super().save(*args, **kwargs)


class AuditEvent(TenantContextModel):
    """An immutable, append-only audit record of a significant action.

    Audit rows are never updated or deleted. The event captures *who* did
    *what* to *which* resource, with a JSON snapshot of the relevant input,
    so the audit trail is self-contained.
    """

    class Action(models.TextChoices):
        CREATE = "create"
        UPDATE = "update"
        DELETE = "delete"
        AUTH = "auth"
        JOB_LIFECYCLE = "job_lifecycle"
        BUDGET = "budget"
        TENANCY = "tenancy"

    event_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_kind = models.CharField(
        max_length=16,
        choices=[("user", "user"), ("api_key", "api_key"), ("worker", "worker"), ("system", "system")],
        default="system",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    resource_type = models.CharField(max_length=64)
    resource_id = models.UUIDField(null=True, blank=True)
    input_snapshot = models.JSONField(default=dict, blank=True)
    result = models.CharField(max_length=16, choices=[("ok", "ok"), ("denied", "denied"), ("error", "error")], default="ok")

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["resource_type", "resource_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.resource_type}:{self.resource_id} by {self.actor_id}"


def record_audit(
    action: str,
    resource_type: str,
    resource_id: Any = None,
    *,
    actor_id: Any = None,
    actor_kind: str = "system",
    input_snapshot: dict | None = None,
    result: str = "ok",
    tenant_id: Any = None,
) -> AuditEvent:
    """Write an audit event, inheriting the active tenant/actor context."""
    if tenant_id is None:
        tenant_id = get_active_tenant()
    from modelanvil.core.tenancy import get_active_project
    snapshot = dict(input_snapshot or {})
    if actor_id is not None:
        try: actor_id = uuid.UUID(str(actor_id))
        except (ValueError, TypeError):
            snapshot['actor_reference'] = f'{actor_kind}:{actor_id}'
            actor_id = None
    event = AuditEvent(
        tenant_id=tenant_id or uuid7(),
        project_id=get_active_project(),
        actor_id=actor_id,
        actor_kind=actor_kind,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        input_snapshot=snapshot,
        result=result,
    )
    event.save()
    return event


class ProjectPrivacyPolicy(TenantContextModel):
    """An administrator's restriction on the installation's acquisition destinations."""

    project = models.OneToOneField('identity.Project', on_delete=models.CASCADE)
    offline = models.BooleanField(default=False)
    acquisition_origins = models.JSONField(default=list)
    external_generation_targets = models.JSONField(default=list)
    mcp_targets = models.JSONField(default=list)
    code_execution = models.BooleanField(default=False)
    measurement_retention_days = models.PositiveSmallIntegerField(default=30)


class ActivationEvent(TenantContextModel):
    """Content-free measurements stored only in this installation."""

    event_id = models.UUIDField()
    session_id = models.UUIDField(db_index=True)
    project = models.ForeignKey('identity.Project', on_delete=models.CASCADE)
    kind = models.CharField(max_length=24, choices=[('workspace_opened', 'Workspace opened'), ('activity', 'Activity')])
    active_milliseconds = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('tenant_id', 'project', 'event_id'), name='activation_event_unique')]


class ImprovementDecision(TenantContextModel):
    """An explicit decision about one verified candidate/baseline comparison."""

    decision_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT)
    evaluation = models.ForeignKey('runners.EvaluationRun', on_delete=models.PROTECT)
    training = models.ForeignKey('runners.TrainingRun', on_delete=models.PROTECT)
    outcome = models.CharField(max_length=8, choices=[('accept', 'Accept'), ('reject', 'Reject')])
    evidence_digest = models.CharField(max_length=64)
    candidate_accuracy = models.FloatField()
    baseline_accuracy = models.FloatField()
    accepted_improvement = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('tenant_id', 'project', 'evaluation'), name='improvement_decision_unique')]


class IdempotencyKey(TenantContextModel):
    """Durable idempotency record for mutating API requests.

    A client supplies an ``Idempotency-Key`` header on a mutating request.
    The first request executes and stores its response; replays with the
    same key return the stored response without re-executing. Keys are
    scoped to (tenant, method, path, key) so identical keys on different
    endpoints never collide.
    """

    key = models.CharField(max_length=128, db_index=True)
    principal = models.CharField(max_length=160, default="legacy")
    http_method = models.CharField(max_length=8)
    path = models.CharField(max_length=512)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        unique_together = ("tenant_id", "principal", "http_method", "path", "key")
        ordering = ("-created_at",)

    def is_expired(self, ttl_seconds: int) -> bool:
        if self.completed_at is None:
            return False
        cutoff = timezone.now() - timezone.timedelta(seconds=ttl_seconds)
        return self.completed_at < cutoff
