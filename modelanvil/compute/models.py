"""Owned external compute; provider secrets and responses never enter these rows."""
from modelanvil.core.ids import uuid7

from django.db import models
from modelanvil.core.models import TenantContextModel


class ComputeAllocation(TenantContextModel):
    class State(models.TextChoices):
        PROVISIONING = "provisioning"
        ACTIVE = "active"
        UNCERTAIN = "uncertain"
        RELEASING = "releasing"
        RELEASED = "released"
        FAILED = "failed"

    allocation_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    request_id = models.UUIDField()
    plugin_id = models.CharField(max_length=100)
    plugin_digest = models.CharField(max_length=64)
    spec = models.JSONField()
    worker = models.OneToOneField("jobs.Worker", on_delete=models.PROTECT)
    provider_resource_id = models.CharField(max_length=128, blank=True)
    provider_status = models.CharField(max_length=32, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PROVISIONING)
    release_requested = models.BooleanField(default=False)
    expires_at = models.DateTimeField(db_index=True)
    released_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    reservation = models.OneToOneField("budgets.BudgetReservation", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "request_id"), name="compute_request_tenant_unique")]
        ordering = ("-created_at", "-id")
