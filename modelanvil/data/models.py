"""Source registry and immutable ingestion snapshot metadata."""
from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel


class DataSource(TenantContextModel):
    class Kind(models.TextChoices):
        UPLOAD = "upload", "Upload"
        OBJECT_STORE = "object_store", "Object store"
        REPOSITORY = "repository", "Repository/API"
        CRAWLER = "crawler", "Crawler"

    source_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="data_sources"
    )
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    configuration = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    suspended_reason = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name"), name="data_source_tenant_name_uniq")]


class SourceSnapshot(TenantContextModel):
    class State(models.TextChoices):
        INGESTING = "ingesting", "Ingesting"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    snapshot_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="source_snapshots"
    )
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT, related_name="snapshots")
    source_revision = models.CharField(max_length=255)
    manifest_digest = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.INGESTING)
    item_count = models.PositiveBigIntegerField(default=0)
    failure_count = models.PositiveBigIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "source", "source_revision"), name="source_snapshot_revision_uniq")]

    def clean(self) -> None:
        if self.source_id and str(self.source.tenant_id) != str(self.tenant_id):
            raise ValidationError("Source snapshot and source must share a tenant.")
        if self.source_id and self.project_id and self.source.project_id and str(self.source.project_id) != str(self.project_id):
            raise ValidationError("Source snapshot and source must share the same project.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.project_id and self.source_id and self.source.project_id:
            self.project = self.source.project
        if self.pk and type(self).all_objects.filter(pk=self.pk, state=self.State.READY).exists():
            old = type(self).all_objects.get(pk=self.pk)
            immutable = ("source_id", "tenant_id", "source_revision", "manifest_digest", "item_count", "failure_count")
            if any(getattr(old, field) != getattr(self, field) for field in immutable) or self.state != self.State.READY:
                raise ValueError("Ready source snapshots are immutable.")
        self.full_clean(exclude=("source",))
        super().save(*args, **kwargs)

    def mark_ready(self, *, manifest_digest: str, item_count: int, failure_count: int = 0) -> None:
        if self.state != self.State.INGESTING:
            raise ValueError("Only ingesting snapshots can become ready.")
        if len(manifest_digest) != 64 or any(c not in "0123456789abcdef" for c in manifest_digest):
            raise ValueError("Manifest digest must be lowercase SHA-256 hex.")
        if item_count < 0 or failure_count < 0 or failure_count > item_count:
            raise ValueError("Snapshot counts are invalid.")
        if failure_count:
            raise ValueError("A snapshot with failed records cannot be published ready.")
        self.manifest_digest = manifest_digest
        self.item_count = item_count
        self.failure_count = failure_count
        self.state = self.State.READY
        self.completed_at = timezone.now()
        self.save(update_fields=("manifest_digest", "item_count", "failure_count", "state", "completed_at", "updated_at"))

    def delete(self, *args: Any, **kwargs: Any):
        if self.state == self.State.READY:
            raise ValueError("Ready source snapshots are immutable and cannot be deleted.")
        return super().delete(*args, **kwargs)


def validate_sample_envelope(document: Any) -> dict[str, Any]:
    """Validate against the canonical sample-envelope contract."""
    from contracts.validate import validate_envelope

    return validate_envelope(document)


class RecipeRun(TenantContextModel):
    """Frozen recipe bindings and fenced, immutable step/row checkpoints."""
    run_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, related_name='recipe_runs')
    job = models.OneToOneField('jobs.Job', on_delete=models.PROTECT, related_name='recipe_run')
    recipe = models.ForeignKey('artifacts.Artifact', on_delete=models.PROTECT, related_name='recipe_runs')
    model_version = models.ForeignKey('runners.ModelVersion', null=True, blank=True, on_delete=models.PROTECT, related_name='recipe_runs')
    dataset = models.ForeignKey('artifacts.Dataset', null=True, blank=True, on_delete=models.PROTECT, related_name='recipe_runs')
    principal_id = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=128)
    input_digest = models.CharField(max_length=64)
    frozen = models.JSONField(default=dict)
    checkpoints = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default='queued')
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('tenant_id','project','principal_id','idempotency_key'), name='recipe_run_admission_unique')]
