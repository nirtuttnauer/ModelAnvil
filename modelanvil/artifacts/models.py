"""Tenant-scoped immutable artifacts and dataset revisions (WP-04 foundation).

Metadata commits are separate from object transfer: an Artifact begins in
STAGING and becomes visible only after its checksum/size are verified. Dataset
revisions are immutable snapshots; publishing advances a dataset pointer but
never modifies an earlier revision.
"""
from __future__ import annotations

import re

from datetime import timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel


def _transfer_expiry():
    return timezone.now() + timedelta(hours=24)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Artifact(TenantContextModel):
    class State(models.TextChoices):
        STAGING = "staging", "Staging"
        COMMITTED = "committed", "Committed"
        TOMBSTONED = "tombstoned", "Tombstoned"
        FAILED = "failed", "Failed"

    artifact_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="artifacts"
    )
    storage_location_id = models.CharField(max_length=128)
    object_key = models.CharField(max_length=1024)
    object_version = models.CharField(max_length=256, null=True, blank=True)
    sha256 = models.CharField(max_length=64)
    byte_size = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=255)
    state = models.CharField(max_length=16, choices=State.choices, default=State.STAGING)
    committed_at = models.DateTimeField(null=True, blank=True)
    tombstoned_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "storage_location_id", "object_key", "object_version"),
                name="artifact_scoped_object_version_uniq",
            )
        ]
        indexes = [models.Index(fields=("tenant_id", "sha256"))]

    def clean(self) -> None:
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ValidationError({"sha256": "Must be a lowercase SHA-256 hex digest."})
        if self.byte_size < 0:
            raise ValidationError({"byte_size": "Must be non-negative."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk and type(self).all_objects.filter(pk=self.pk).exists():
            previous = type(self).all_objects.get(pk=self.pk)
            if (isinstance(previous.metadata,dict) and previous.metadata.get('application_feedback_id')
                    and (not isinstance(self.metadata,dict) or self.metadata.get('application_feedback_id')!=previous.metadata['application_feedback_id'])):
                raise ValueError('Feedback artifact provenance is immutable.')
            if isinstance(previous.metadata, dict) and 'cpu_export' in previous.metadata and (self.metadata != previous.metadata or self.project_id != previous.project_id):
                raise ValueError('Prepared CPU export provenance and project are immutable.')
            protected = ("tenant_id", "storage_location_id", "object_key", "object_version", "sha256", "byte_size", "media_type")
            if previous.state == self.State.COMMITTED and any(getattr(previous, field) != getattr(self, field) for field in protected):
                raise ValueError("Committed artifact metadata is immutable.")
            if previous.state == self.State.TOMBSTONED and self.state != self.State.TOMBSTONED:
                raise ValueError("Tombstoned artifacts cannot be restored.")
        self.full_clean(exclude=None)
        super().save(*args, **kwargs)

    def mark_verified(self, *, verified_sha256: str | None = None, verified_size: int | None = None) -> None:
        if self.state != self.State.STAGING:
            raise ValueError("Only staging artifacts can be committed.")
        if verified_sha256 != self.sha256 or verified_size != self.byte_size:
            raise ValueError("Verified checksum and size must match the staged artifact metadata.")
        self.state = self.State.COMMITTED
        self.committed_at = timezone.now()
        self.save(update_fields=("state", "committed_at", "updated_at"))

    def tombstone(self) -> None:
        if self.state != self.State.COMMITTED:
            raise ValueError("Only committed artifacts can be tombstoned.")
        self.state = self.State.TOMBSTONED
        self.tombstoned_at = timezone.now()
        self.save(update_fields=("state", "tombstoned_at", "updated_at"))

    def delete(self, *args: Any, **kwargs: Any):
        if self.state in (self.State.COMMITTED, self.State.TOMBSTONED):
            raise ValueError("Committed artifacts must be tombstoned, not deleted.")
        return super().delete(*args, **kwargs)


class Dataset(TenantContextModel):
    dataset_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="datasets"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    current_revision = models.ForeignKey(
        "DatasetRevision", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="current_for_datasets",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name"), name="dataset_tenant_name_uniq")]
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class DatasetRevision(TenantContextModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    revision_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="dataset_revisions"
    )
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="revisions")
    revision_no = models.PositiveIntegerField()
    schema_version = models.CharField(max_length=32, default="1.0")
    manifest_digest = models.CharField(max_length=64)
    manifest_artifact = models.ForeignKey(Artifact, null=True, blank=True, on_delete=models.PROTECT, related_name="dataset_revisions")
    recipe_digest = models.CharField(max_length=64, blank=True)
    source_snapshots = models.JSONField(default=list, blank=True)
    row_count = models.PositiveBigIntegerField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("dataset", "revision_no"), name="dataset_revision_no_uniq")]
        ordering = ("-revision_no",)

    def clean(self) -> None:
        if self.dataset_id and str(self.dataset.tenant_id) != str(self.tenant_id):
            raise ValidationError("Dataset revision and dataset must share a tenant.")
        if self.manifest_artifact_id and str(self.manifest_artifact.tenant_id) != str(self.tenant_id):
            raise ValidationError("Dataset revision and manifest artifact must share a tenant.")
        if self.dataset_id and self.project_id and self.dataset.project_id and str(self.dataset.project_id) != str(self.project_id):
            from modelanvil.identity.models import check_resource_access
            if not check_resource_access(self.dataset, self.project_id, self.tenant_id):
                raise ValidationError("Dataset revision and dataset must share the same project.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.project_id and self.dataset_id and self.dataset.project_id:
            self.project = self.dataset.project
        if self.pk and type(self).all_objects.filter(pk=self.pk).exists():
            previous = type(self).all_objects.get(pk=self.pk)
            if previous.state == self.State.PUBLISHED:
                immutable = ("dataset_id", "tenant_id", "revision_no", "schema_version", "manifest_digest", "manifest_artifact_id", "recipe_digest", "source_snapshots", "row_count", "metadata")
                if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                    raise ValueError("Published dataset revisions are immutable.")
                if self.state != self.State.PUBLISHED:
                    raise ValueError("Published dataset revisions cannot change state.")
        self.clean()
        self.full_clean(exclude=("dataset", "manifest_artifact"))
        super().save(*args, **kwargs)

    @transaction.atomic
    def publish(self) -> None:
        if self.state != self.State.DRAFT:
            raise ValueError("Only draft dataset revisions can be published.")
        if self.manifest_artifact_id:
            artifact = self.manifest_artifact
            if artifact.state != Artifact.State.COMMITTED or artifact.tenant_id != self.tenant_id:
                raise ValueError("Dataset manifest must be a committed artifact in the same tenant.")
        self.state = self.State.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=("state", "published_at", "updated_at"))
        Dataset.all_objects.filter(pk=self.dataset_id, tenant_id=self.tenant_id).update(current_revision=self)

    def delete(self, *args: Any, **kwargs: Any):
        if self.state == self.State.PUBLISHED:
            raise ValueError("Published dataset revisions are immutable and cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.dataset.name} r{self.revision_no}"


class LineageEdge(TenantContextModel):
    edge_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    parent_artifact = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="outgoing_lineage")
    child_artifact = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="incoming_lineage")
    relation = models.CharField(max_length=64)
    producing_job_id = models.UUIDField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "parent_artifact", "child_artifact", "relation"), name="lineage_edge_unique")]

    def clean(self) -> None:
        if self.parent_artifact_id == self.child_artifact_id:
            raise ValidationError("An artifact cannot be its own lineage parent.")
        if self.parent_artifact.tenant_id != self.tenant_id or self.child_artifact.tenant_id != self.tenant_id:
            raise ValidationError("Lineage artifacts must belong to the same tenant as the edge.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class WorkerArtifactGrant(TenantContextModel):
    """Short-lived input download authority for one worker execution."""

    grant_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    attempt = models.ForeignKey("jobs.JobAttempt", on_delete=models.PROTECT, related_name="artifact_grants")
    worker = models.ForeignKey("jobs.Worker", on_delete=models.PROTECT, related_name="artifact_grants")
    artifact = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="worker_grants")
    fencing_token = models.CharField(max_length=64)
    artifact_snapshot = models.JSONField()
    storage_fingerprint = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            previous = type(self).all_objects.get(pk=self.pk)
            immutable = ("tenant_id", "grant_id", "attempt_id", "worker_id", "artifact_id", "fencing_token",
                         "artifact_snapshot", "storage_fingerprint", "expires_at", "created_at")
            if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                raise ValueError("Worker artifact grant scope and expiry are immutable.")
            if previous.revoked_at is not None and self.revoked_at != previous.revoked_at:
                raise ValueError("Worker artifact grant revocation is immutable.")
        super().save(*args, **kwargs)


class TransferSession(TenantContextModel):
    """Durable manifest for a resumable upload to a staging artifact."""

    class State(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"
        ABORTED = "aborted", "Aborted"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed"

    class Direction(models.TextChoices):
        UPLOAD = "upload", "Upload"

    transfer_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="transfer_sessions")
    direction = models.CharField(max_length=16, choices=Direction.choices, default=Direction.UPLOAD)
    source_ref = models.CharField(max_length=512, blank=True)
    staging_prefix = models.CharField(max_length=1024, blank=True)
    multipart_ref = models.CharField(max_length=512, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.OPEN)
    bytes_verified = models.PositiveBigIntegerField(default=0)
    part_manifest = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(default=_transfer_expiry, db_index=True)
    parts_purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "artifact"),
                condition=models.Q(state="open"),
                name="one_open_transfer_per_artifact",
            ),
        ]
        indexes = [models.Index(fields=("tenant_id", "state", "expires_at"))]

    def clean(self) -> None:
        if self.artifact_id and self.artifact.tenant_id != self.tenant_id:
            raise ValidationError("Transfer session and artifact must belong to the same tenant.")
        if self.bytes_verified < 0:
            raise ValidationError({"bytes_verified": "Must be non-negative."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.staging_prefix:
            self.staging_prefix = f"staging/transfers/{self.transfer_id}"
        self.full_clean()
        super().save(*args, **kwargs)


class DeletionTombstone(TenantContextModel):
    """Audited deletion / policy tombstone marking a resource revoked.

    Current authorization, retrieval, context lab, and export paths check
    tombstones to fail closed on tombstoned assets.
    """

    tombstone_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    resource_type = models.CharField(max_length=64, db_index=True)
    resource_id = models.CharField(max_length=128, db_index=True)
    policy_epoch = models.PositiveBigIntegerField(default=1)
    reason = models.TextField(blank=True)
    detail = models.JSONField(default=dict, blank=True)
    tombstoned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "resource_type", "resource_id"),
                name="tombstone_tenant_resource_uniq",
            )
        ]
        indexes = [
            models.Index(fields=("tenant_id", "resource_type", "resource_id")),
        ]

    def __str__(self) -> str:
        return f"tombstone {self.resource_type}:{self.resource_id} (tenant {self.tenant_id})"
