"""Durable models for Releases, Frozen Gate Results, Policy Exceptions, Endpoints, and Deployments (WP-15 / TECH-020-021)."""
from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from modelanvil.core.models import TenantContextModel
from modelanvil.runners.models import EvaluationRun, ModelVersion


class Release(TenantContextModel):
    """Logical release definition belonging to an organization/tenant."""

    release_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="releases"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name"), name="release_tenant_name_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class ReleaseVersion(TenantContextModel):
    """Immutable candidate release version with model card and bundle manifests (TECH-021)."""

    class CandidateType(models.TextChoices):
        MODEL = "model", "Model Weights"
        ADAPTER = "adapter", "Adapter Weights"
        PIPELINE = "pipeline", "RAG Pipeline"
        CONTEXT = "context", "Context Recipe"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        EVALUATING = "evaluating", "Evaluating"
        QUALIFIED = "qualified", "Qualified"
        REJECTED = "rejected", "Rejected"
        PROMOTED = "promoted", "Promoted"
        ARCHIVED = "archived", "Archived"

    release_version_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="release_versions"
    )
    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="versions")
    revision_no = models.PositiveIntegerField(default=1)
    candidate_type = models.CharField(max_length=32, choices=CandidateType.choices, default=CandidateType.MODEL)
    candidate_ref = models.CharField(max_length=128)
    model_version = models.ForeignKey(
        ModelVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="release_versions"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    manifest_digest = models.CharField(max_length=64, blank=True)
    model_card = models.JSONField(default=dict, blank=True)
    bundle_manifest = models.JSONField(default=dict, blank=True)
    quantization_spec = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("release", "revision_no"), name="release_version_uniq")
        ]

    def clean(self) -> None:
        if self.release_id and str(self.release.tenant_id) != str(self.tenant_id):
            raise ValidationError("Release version and release must share a tenant.")
        if self.model_version_id and str(self.model_version.tenant_id) != str(self.tenant_id):
            raise ValidationError("Release version and model version must share a tenant.")
        if self.release_id and self.project_id and self.release.project_id and str(self.release.project_id) != str(self.project_id):
            from modelanvil.identity.models import check_resource_access
            if not check_resource_access(self.release, self.project_id, self.tenant_id):
                raise ValidationError("Release version and release must share the same project.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.project_id and self.release_id and self.release.project_id:
            self.project = self.release.project
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.release.name} r{self.revision_no} [{self.status}]"


class GateResult(TenantContextModel):
    """Frozen verification result for an individual release gate criterion (TECH-021)."""

    gate_result_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    release_version = models.ForeignKey(ReleaseVersion, on_delete=models.CASCADE, related_name="gate_results")
    criterion_key = models.CharField(max_length=64)  # min_accuracy, no_regression, license_check, quantization_eval
    evaluation_run = models.ForeignKey(
        EvaluationRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="gate_results"
    )
    passed = models.BooleanField(default=False)
    evidence_digest = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("release_version", "criterion_key"), name="gate_result_version_key_uniq")
        ]

    def __str__(self) -> str:
        return f"Gate {self.criterion_key} for {self.release_version} ({'PASSED' if self.passed else 'FAILED'})"


class ReleaseException(TenantContextModel):
    """Authorized, audited policy exception waiving a failing gate result (TECH-021 / PRD Scenario 10)."""

    exception_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    gate_result = models.ForeignKey(GateResult, on_delete=models.CASCADE, related_name="exceptions")
    actor_id = models.CharField(max_length=128)
    permitted_policy_id = models.CharField(max_length=128)
    reason = models.TextField()
    is_valid = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Exception for {self.gate_result.criterion_key} by {self.actor_id}"


class ServingEndpoint(TenantContextModel):
    """Production serving endpoint with an atomic pointer to the active deployment revision (TECH-021)."""

    endpoint_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="serving_endpoints"
    )
    endpoint_key = models.CharField(max_length=128)
    name = models.CharField(max_length=200)
    active_deployment = models.ForeignKey(
        "DeploymentRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_for_endpoint",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "endpoint_key"), name="serving_endpoint_tenant_key_uniq")
        ]

    def __str__(self) -> str:
        return f"Endpoint {self.endpoint_key} (Active: {self.active_deployment_id})"


class DeploymentRevision(TenantContextModel):
    """Versioned deployment configuration of a release version on an endpoint (TECH-021)."""

    class ReadinessState(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        ROLLED_BACK = "rolled_back", "Rolled Back"

    deployment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="deployments"
    )
    endpoint = models.ForeignKey(ServingEndpoint, on_delete=models.CASCADE, related_name="deployments")
    release_version = models.ForeignKey(ReleaseVersion, on_delete=models.PROTECT, related_name="deployments")
    revision_no = models.PositiveIntegerField(default=1)
    previous_deployment = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="subsequent_deployments"
    )
    serving_config = models.JSONField(default=dict, blank=True)
    readiness_state = models.CharField(max_length=16, choices=ReadinessState.choices, default=ReadinessState.READY)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("endpoint", "revision_no"), name="deployment_revision_endpoint_rev_uniq")
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.project_id and self.endpoint_id and self.endpoint.project_id:
            self.project = self.endpoint.project
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Deployment {self.endpoint.endpoint_key} r{self.revision_no} ({self.readiness_state})"
