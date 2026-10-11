"""Tenant-scoped budget admission, reservations, and idempotent usage events."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.utils import timezone

from modelanvil.core.models import TenantContextModel, TenantScopedManager, TenantScopedQuerySet


class BudgetPolicy(TenantContextModel):
    class Period(models.TextChoices):
        DAILY = "daily", "Daily"
        MONTHLY = "monthly", "Monthly"
        LIFETIME = "lifetime", "Lifetime"

    policy_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=200)
    period = models.CharField(max_length=16, choices=Period.choices)
    unit = models.CharField(max_length=64)
    limit_amount = models.DecimalField(max_digits=24, decimal_places=6)
    currency = models.CharField(max_length=3, blank=True)
    enabled = models.BooleanField(default=True)
    stop_behavior = models.CharField(max_length=16, default="stop")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name"), name="budget_policy_tenant_name_uniq")]

    def clean(self) -> None:
        if self.limit_amount < 0:
            raise ValidationError({"limit_amount": "Budget limit must be non-negative."})


class BudgetReservation(TenantContextModel):
    class State(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        SETTLED = "settled", "Settled"
        RELEASED = "released", "Released"

    reservation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    policy = models.ForeignKey(BudgetPolicy, on_delete=models.PROTECT, related_name="reservations")
    job_id = models.UUIDField()
    estimated_amount = models.DecimalField(max_digits=24, decimal_places=6)
    settled_amount = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.RESERVED)
    period_start = models.DateField(db_index=True)
    reserved_at = models.DateTimeField(default=timezone.now)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "job_id", "policy"), name="budget_reservation_job_policy_uniq"),
        ]

    @classmethod
    @transaction.atomic
    def reserve(cls, *, tenant_id: Any, policy: BudgetPolicy, job_id: Any, estimated_amount: Any) -> "BudgetReservation":
        amount = Decimal(str(estimated_amount))
        if amount <= 0:
            raise ValueError("Reservation amount must be positive.")
        locked_policy = BudgetPolicy.all_objects.select_for_update().get(pk=policy.pk, tenant_id=tenant_id)
        if not locked_policy.enabled:
            raise ValueError("Budget policy is disabled.")
        if not locked_policy.unit:
            raise ValueError("Budget policy unit is required.")
        existing = cls.all_objects.filter(tenant_id=tenant_id, job_id=job_id, policy=locked_policy).first()
        if existing:
            if existing.estimated_amount != amount:
                raise ValueError("Idempotency conflict: reservation amount changed for this job.")
            return existing
        now = timezone.now()
        period_start, committed = cls.current_commitment(locked_policy)
        if committed + amount > locked_policy.limit_amount:
            raise ValueError("Budget limit exceeded.")
        return cls.objects.create(
            tenant_id=tenant_id, policy=locked_policy, job_id=job_id,
            estimated_amount=amount, state=cls.State.RESERVED, period_start=period_start,
            reserved_at=now,
        )

    @classmethod
    def current_commitment(cls, policy):
        """The same period and committed usage for preview and locked admission."""
        local_day = timezone.localdate()
        if policy.period == BudgetPolicy.Period.DAILY:
            period_start = local_day
        elif policy.period == BudgetPolicy.Period.MONTHLY:
            period_start = local_day.replace(day=1)
        else:
            period_start = date(1970, 1, 1)
        aggregate = cls.all_objects.filter(
            tenant_id=policy.tenant_id, policy=policy, period_start=period_start
        ).aggregate(total=Sum(Case(
            When(state=cls.State.RESERVED, then=F("estimated_amount")),
            When(state=cls.State.SETTLED, then=F("settled_amount")),
            default=Value(Decimal("0")),
            output_field=DecimalField(max_digits=24, decimal_places=6),
        )))
        committed = Decimal(aggregate["total"] or 0)
        return period_start, committed

    @transaction.atomic
    def settle(self, actual_amount: Any) -> None:
        amount = Decimal(str(actual_amount))
        if amount < 0:
            raise ValueError("Settled amount must be non-negative.")
        reservation = type(self).all_objects.select_for_update().get(pk=self.pk)
        if reservation.state == self.State.SETTLED:
            if reservation.settled_amount != amount:
                raise ValueError("Conflicting settlement for reservation.")
            return
        if reservation.state != self.State.RESERVED:
            raise ValueError("Only reserved budgets can be settled.")
        reservation.state = self.State.SETTLED
        reservation.settled_amount = amount
        reservation.settled_at = timezone.now()
        reservation.save(update_fields=("state", "settled_amount", "settled_at", "updated_at"))
        self.state, self.settled_amount, self.settled_at = reservation.state, amount, reservation.settled_at

    @transaction.atomic
    def release(self) -> None:
        reservation = type(self).all_objects.select_for_update().get(pk=self.pk)
        if reservation.state == self.State.RELEASED:
            return
        if reservation.state != self.State.RESERVED:
            raise ValueError("Only reserved budgets can be released.")
        reservation.state = self.State.RELEASED
        reservation.save(update_fields=("state", "updated_at"))
        self.state = reservation.state


class AppendOnlyQuerySetMixin:
    def bulk_create(self, objs, *args, **kwargs):
        # Bulk paths bypass save()/clean(); use normal creation for ledger rows.
        raise ValidationError("Accounting records require validated individual inserts.")

    def update(self, **kwargs):
        raise ValidationError("Accounting records are append-only.")

    def delete(self):
        raise ValidationError("Accounting records are append-only.")


class AppendOnlyQuerySet(AppendOnlyQuerySetMixin, models.QuerySet):
    pass


class ScopedAppendOnlyQuerySet(AppendOnlyQuerySetMixin, TenantScopedQuerySet):
    pass


class ScopedAppendOnlyManager(TenantScopedManager):
    def get_queryset(self):
        return ScopedAppendOnlyQuerySet(self.model, using=self._db)._apply_tenant()


class AppendOnlyRecord(TenantContextModel):
    objects = ScopedAppendOnlyManager()
    all_objects = models.Manager.from_queryset(AppendOnlyQuerySet)()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Accounting records are append-only.")
        # Uniqueness is enforced by the database, so get_or_create can resolve
        # concurrent inserts with its savepoint/IntegrityError retry path.
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Accounting records are append-only.")


class RateRevision(AppendOnlyRecord):
    revision = models.CharField(max_length=128)
    provider = models.CharField(max_length=128)
    resource_kind = models.CharField(max_length=64)
    unit = models.CharField(max_length=64)
    unit_price = models.DecimalField(max_digits=24, decimal_places=6)
    currency = models.CharField(max_length=3)
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=("tenant_id", "revision"), name="rate_revision_tenant_revision_uniq",
        )]

    def clean(self):
        if not self.unit_price.is_finite() or self.unit_price < 0:
            raise ValidationError({"unit_price": "Rate price must be finite and non-negative."})
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValidationError({"effective_until": "Effective end must follow the start."})
        if len(self.currency) != 3 or not self.currency.isalpha() or self.currency != self.currency.upper():
            raise ValidationError({"currency": "Currency must be a three-letter uppercase code."})


class UsageEvent(AppendOnlyRecord):
    usage_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provider_event_key = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=24, decimal_places=6)
    unit = models.CharField(max_length=64)
    reservation = models.ForeignKey(BudgetReservation, null=True, blank=True, on_delete=models.PROTECT, related_name="usage_events")
    rate_revision = models.CharField(max_length=128, blank=True)
    amount = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    observed_at = models.DateTimeField(default=timezone.now)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "provider_event_key"), name="usage_event_tenant_provider_key_uniq")]
        ordering = ("-occurred_at",)

    def net_amount(self) -> Decimal | None:
        """Return the original priced amount plus append-only bill corrections."""
        if self.amount is None:
            return None
        delta = UsageAdjustment.all_objects.filter(
            tenant_id=self.tenant_id, usage_event=self,
        ).aggregate(total=Sum("amount_delta"))["total"]
        return self.amount + (delta or Decimal("0"))

    def _check_replay(self, quantity, unit, reservation, rate_revision, occurred_at, detail):
        if (
            self.quantity != quantity or self.unit != unit
            or self.reservation_id != getattr(reservation, "pk", None)
            or self.rate_revision != rate_revision or self.detail != (detail or {})
            or (occurred_at is not None and self.occurred_at != occurred_at)
        ):
            raise ValueError("Provider event key was replayed with conflicting usage.")

    @classmethod
    @transaction.atomic
    def record(cls, *, tenant_id: Any, provider_event_key: str, quantity: Any, unit: str,
               reservation: BudgetReservation | None = None, rate_revision: str = "",
               occurred_at: Any = None, detail: dict | None = None) -> "UsageEvent":
        amount = Decimal(str(quantity))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Usage quantity must be finite and non-negative.")
        if reservation is not None and (reservation.tenant_id != tenant_id or reservation.policy.unit != unit):
            raise ValueError("Usage event and reservation must share tenant and unit.")
        existing = cls.all_objects.filter(
            tenant_id=tenant_id, provider_event_key=provider_event_key,
        ).first()
        if existing is not None:
            existing._check_replay(amount, unit, reservation, rate_revision, occurred_at, detail)
            return existing
        occurred = occurred_at or timezone.now()
        charge, currency = None, ""
        if rate_revision:
            rate = RateRevision.all_objects.get(tenant_id=tenant_id, revision=rate_revision)
            if rate.unit != unit or occurred < rate.effective_from or (
                rate.effective_until is not None and occurred >= rate.effective_until
            ):
                raise ValueError("Rate revision does not apply to this usage unit and time.")
            charge = (amount * rate.unit_price).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
            currency = rate.currency
        try:
            event, created = cls.objects.get_or_create(
                tenant_id=tenant_id, provider_event_key=provider_event_key,
                defaults={"quantity": amount, "unit": unit, "reservation": reservation,
                          "rate_revision": rate_revision, "occurred_at": occurred,
                          "amount": charge, "currency": currency,
                          "detail": detail or {}},
            )
        except IntegrityError:
            event = cls.all_objects.get(tenant_id=tenant_id, provider_event_key=provider_event_key)
            created = False
        if not created:
            event._check_replay(amount, unit, reservation, rate_revision, occurred_at, detail)
        return event


class UsageAdjustment(AppendOnlyRecord):
    adjustment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    usage_event = models.ForeignKey(UsageEvent, on_delete=models.PROTECT, related_name="adjustments")
    amount_delta = models.DecimalField(max_digits=24, decimal_places=6)
    reason = models.CharField(max_length=1000)
    source_event_key = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=("tenant_id", "source_event_key"), name="usage_adjustment_tenant_source_uniq",
        )]

    def clean(self):
        if self.usage_event_id and (
            self.usage_event.tenant_id != self.tenant_id or self.usage_event.amount is None
        ):
            raise ValidationError("Adjustment requires priced usage in the same tenant.")

    @classmethod
    @transaction.atomic
    def record(cls, *, tenant_id: Any, usage_event: UsageEvent, amount_delta: Any,
               reason: str, source_event_key: str) -> "UsageAdjustment":
        amount = Decimal(str(amount_delta))
        if not amount.is_finite():
            raise ValueError("Adjustment amount must be finite.")
        if usage_event.tenant_id != tenant_id or usage_event.amount is None:
            raise ValueError("Adjustment requires priced usage in the same tenant.")
        # Serialize reconciliation against one usage row; the unique source key
        # also protects duplicate provider callbacks across different usage rows.
        UsageEvent.all_objects.select_for_update().get(pk=usage_event.pk, tenant_id=tenant_id)
        adjustment, created = cls.all_objects.get_or_create(
            tenant_id=tenant_id, source_event_key=source_event_key,
            defaults={"usage_event": usage_event, "amount_delta": amount, "reason": reason},
        )
        if not created and (
            adjustment.usage_event_id != usage_event.pk
            or adjustment.amount_delta != amount or adjustment.reason != reason
        ):
            raise ValueError("Source event key was replayed with conflicting adjustment.")
        return adjustment
