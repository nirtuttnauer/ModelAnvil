"""Annotation records, rubric revisions, campaign lifecycle, and approved cumulative snapshots (WP-09, WP-10 / TECH-011-013)."""
from __future__ import annotations

from typing import Any, Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel
from modelanvil.runners.models import ModelVersion


class LabelSchema(TenantContextModel):
    """Schema for task labels: classification, NER spans, preferences, or text generation."""

    class Kind(models.TextChoices):
        CLASSIFICATION = "classification", "Classification"
        NER_SPAN = "ner_span", "NER Span"
        PREFERENCE_RANKING = "preference_ranking", "Preference Ranking"
        TEXT_GENERATION = "text_generation", "Text Generation"
        RUBRIC_SCORING = "rubric_scoring", "Rubric Scoring"

    schema_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    classes = models.JSONField(default=list, blank=True)
    specification = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name"), name="label_schema_tenant_name_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.kind}]"


class RubricRevision(TenantContextModel):
    """Guidelines and evaluation criteria for annotation review and quality."""

    rubric_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=200)
    revision_no = models.PositiveIntegerField(default=1)
    guidelines_text = models.TextField()
    criteria = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name", "revision_no"), name="rubric_revision_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.name} r{self.revision_no}"


class LabelingCampaign(TenantContextModel):
    """Orchestrated iterative labeling campaign managing repeated train-and-next-batch cycles."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class SeedMode(models.TextChoices):
        MANUAL = "manual", "Manual Annotation"
        EXISTING_MODEL = "existing_model", "Existing Model Assisted"

    campaign_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, null=True, blank=True,
        related_name='labeling_campaigns')
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    seed_mode = models.CharField(max_length=24, choices=SeedMode.choices)
    current_cycle = models.PositiveIntegerField(default=0)
    max_cycles = models.PositiveIntegerField(default=3)
    budget_limit_dollars = models.FloatField(default=100.0)
    accumulated_cost_dollars = models.FloatField(default=0.0)
    active_drafting_model = models.ForeignKey(
        ModelVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="active_campaigns"
    )
    held_out_audit_digest = models.CharField(max_length=64, blank=True)
    label_schema = models.ForeignKey(LabelSchema, on_delete=models.PROTECT, related_name="campaigns")
    rubric = models.ForeignKey(
        RubricRevision, null=True, blank=True, on_delete=models.PROTECT, related_name="campaigns"
    )
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name"), name="labeling_campaign_tenant_name_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.seed_mode}) [Cycle {self.current_cycle}/{self.max_cycles}]"


class CampaignBatch(TenantContextModel):
    """An individual work batch within a campaign cycle."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DRAFTING = "drafting", "Drafting"
        REVIEWING = "reviewing", "Reviewing"
        CLOSED = "closed", "Closed"

    batch_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    campaign = models.ForeignKey(LabelingCampaign, on_delete=models.CASCADE, related_name="batches")
    cycle_no = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    assigned_drafting_model = models.ForeignKey(
        ModelVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_batches"
    )
    sample_count = models.PositiveIntegerField(default=0)
    approved_count = models.PositiveIntegerField(default=0)
    snapshot_manifest_digest = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("campaign", "cycle_no"), name="campaign_batch_cycle_uniq")
        ]

    def __str__(self) -> str:
        return f"Batch cycle {self.cycle_no} ({self.status}) for {self.campaign.name}"


class AnnotationTask(TenantContextModel):
    """Unit of annotation work assigned to human reviewers."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DRAFTED = "drafted", "Drafted"
        IN_REVIEW = "in_review", "In Review"
        COMPLETED = "completed", "Completed"
        ADJUDICATED = "adjudicated", "Adjudicated"
        SKIPPED = "skipped", "Skipped"

    task_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    campaign = models.ForeignKey(
        LabelingCampaign, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks"
    )
    batch = models.ForeignKey(
        CampaignBatch, null=True, blank=True, on_delete=models.CASCADE, related_name="tasks"
    )
    sample_ref = models.CharField(max_length=128)
    content = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    assigned_reviewer = models.CharField(max_length=128, blank=True)
    needs_adjudication = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Task {self.task_id} ({self.status}) [{self.sample_ref}]"


class AnnotationRecord(TenantContextModel):
    """Immutable review entry with original model prediction and human correction diff."""

    class Decision(models.TextChoices):
        ACCEPTED_WITHOUT_EDIT = "accepted_without_edit", "Accepted Without Edit"
        CORRECTED = "corrected", "Corrected"
        REJECTED = "rejected", "Rejected"
        SKIPPED = "skipped", "Skipped"

    record_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    task = models.ForeignKey(AnnotationTask, on_delete=models.CASCADE, related_name="records")
    revision_no = models.PositiveIntegerField(default=1)
    reviewer_id = models.CharField(max_length=128)
    original_prediction = models.JSONField(default=dict, blank=True)
    human_label = models.JSONField(default=dict)
    decision = models.CharField(max_length=32, choices=Decision.choices)
    is_blind_preference = models.BooleanField(default=False)
    is_blind_review = models.BooleanField(default=False)
    is_adjudication = models.BooleanField(default=False)
    preference_choice = models.CharField(max_length=32, blank=True)  # "candidate_a", "candidate_b", "tie", "abstain"
    time_spent_seconds = models.FloatField(default=0.0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("task", "revision_no"), name="annotation_record_task_rev_uniq")
        ]

    def __str__(self) -> str:
        return f"Review {self.record_id} r{self.revision_no} ({self.decision})"


class CumulativeSnapshot(TenantContextModel):
    """Committed, immutable cumulative dataset snapshot across completed campaign cycles."""

    snapshot_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    campaign = models.ForeignKey(LabelingCampaign, on_delete=models.CASCADE, related_name="snapshots")
    cycle_no = models.PositiveIntegerField()
    item_count = models.PositiveIntegerField(default=0)
    manifest_digest = models.CharField(max_length=64)
    items = models.JSONField(default=list)
    dataset_revision = models.OneToOneField('artifacts.DatasetRevision', on_delete=models.PROTECT, null=True,
        blank=True, related_name='annotation_snapshot')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("campaign", "cycle_no"), name="cumulative_snapshot_campaign_cycle_uniq")
        ]

    def __str__(self) -> str:
        return f"Snapshot cycle {self.cycle_no} ({self.item_count} items) for {self.campaign.name}"
