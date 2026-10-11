"""Pinned rates and append-only reconciliation accounting."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from modelanvil.budgets import models
from modelanvil.identity.models import Tenant


class AccountingTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="accounting", name="Accounting")
        self.occurred_at = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)

    def test_usage_is_priced_from_a_pinned_rate_revision(self):
        self.assertTrue(hasattr(models, "RateRevision"), "Rate revisions are not implemented")
        rate = models.RateRevision.objects.create(
            tenant_id=self.tenant.pk, revision="gpu-v1", provider="owned",
            resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal("0.002500"),
            currency="USD", effective_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
            source="operator price schedule",
        )
        event = models.UsageEvent.record(
            tenant_id=self.tenant.pk, provider_event_key="gpu-1", quantity=120,
            unit="gpu_seconds", rate_revision=rate.revision, occurred_at=self.occurred_at,
        )
        self.assertEqual(event.amount, Decimal("0.300000"))
        self.assertEqual(event.currency, "USD")
        self.assertEqual(event.rate_revision, "gpu-v1")

    def test_replay_cannot_change_a_pinned_rate(self):
        for revision, price in [("first", "0.001"), ("second", "0.002")]:
            models.RateRevision.objects.create(
                tenant_id=self.tenant.pk, revision=revision, provider="owned",
                resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal(price),
                currency="USD", effective_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
                source="price schedule",
            )
        kwargs = dict(tenant_id=self.tenant.pk, provider_event_key="replay",
                      quantity=1, unit="gpu_seconds", occurred_at=self.occurred_at)
        first = models.UsageEvent.record(**kwargs, rate_revision="first")
        duplicate = models.UsageEvent.record(**kwargs, rate_revision="first")
        self.assertEqual(first.pk, duplicate.pk)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            models.UsageEvent.record(**kwargs, rate_revision="second")

    def test_rate_revisions_cannot_be_rewritten_or_deleted(self):
        rate = models.RateRevision.objects.create(
            tenant_id=self.tenant.pk, revision="immutable", provider="owned",
            resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal("0.001"),
            currency="USD", effective_from=self.occurred_at, source="schedule",
        )
        with self.assertRaises(ValidationError):
            rate.unit_price = Decimal("1")
            rate.save()
        with self.assertRaises(ValidationError):
            models.RateRevision.all_objects.filter(pk=rate.pk).update(unit_price=1)
        with self.assertRaises(ValidationError):
            rate.delete()
        with self.assertRaises(ValidationError):
            models.RateRevision.objects.filter(pk=rate.pk).delete()

    def test_invalid_rate_price_and_effective_range_are_rejected(self):
        kwargs = dict(
            tenant_id=self.tenant.pk, revision="invalid", provider="owned",
            resource_kind="gpu", unit="gpu_seconds", currency="USD",
            effective_from=self.occurred_at, source="schedule",
        )
        with self.assertRaises(ValidationError):
            models.RateRevision.objects.create(**kwargs, unit_price=Decimal("-1"))
        with self.assertRaises(ValidationError):
            models.RateRevision.objects.create(**kwargs, unit_price=Decimal("1"),
                                              effective_until=self.occurred_at)

    def test_adjustments_are_idempotent_without_overwriting_original_usage(self):
        self.assertTrue(hasattr(models, "UsageAdjustment"), "Adjustments are not implemented")
        rate = models.RateRevision.objects.create(
            tenant_id=self.tenant.pk, revision="adjustable", provider="owned",
            resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal("0.0025"),
            currency="USD", effective_from=self.occurred_at, source="schedule",
        )
        event = models.UsageEvent.record(
            tenant_id=self.tenant.pk, provider_event_key="original", quantity=120,
            unit="gpu_seconds", rate_revision=rate.revision, occurred_at=self.occurred_at,
        )
        kwargs = dict(tenant_id=self.tenant.pk, usage_event=event,
                      source_event_key="bill-correction", amount_delta="-0.050000",
                      reason="Provider credit")
        first = models.UsageAdjustment.record(**kwargs)
        duplicate = models.UsageAdjustment.record(**kwargs)
        self.assertEqual(first.pk, duplicate.pk)
        self.assertEqual(event.net_amount(), Decimal("0.250000"))
        event.refresh_from_db()
        self.assertEqual(event.quantity, 120)
        self.assertEqual(event.amount, Decimal("0.300000"))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            models.UsageAdjustment.record(**{**kwargs, "amount_delta": "0.100000"})
        with self.assertRaises(ValidationError):
            first.reason = "Silent overwrite"
            first.save()
        with self.assertRaises(ValidationError):
            models.UsageAdjustment.all_objects.filter(pk=first.pk).delete()

    def test_usage_history_is_append_only(self):
        event = models.UsageEvent.record(
            tenant_id=self.tenant.pk, provider_event_key="immutable-usage",
            quantity=1, unit="gpu_seconds",
        )
        with self.assertRaises(ValidationError):
            event.quantity = Decimal("2")
            event.save()
        with self.assertRaises(ValidationError):
            models.UsageEvent.all_objects.filter(pk=event.pk).update(quantity=2)
        with self.assertRaises(ValidationError):
            event.delete()

    def test_delayed_replay_uses_original_occurred_time(self):
        occurred = datetime(2020, 1, 1, tzinfo=timezone.utc)
        models.RateRevision.objects.create(
            tenant_id=self.tenant.pk, revision="historical", provider="owned",
            resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal("1"),
            currency="USD", effective_from=occurred,
            effective_until=occurred + timedelta(days=1), source="historical schedule",
        )
        kwargs = dict(tenant_id=self.tenant.pk, provider_event_key="late-replay",
                      quantity=1, unit="gpu_seconds", rate_revision="historical")
        original = models.UsageEvent.record(**kwargs, occurred_at=occurred)
        replay = models.UsageEvent.record(**kwargs)
        self.assertEqual(replay.pk, original.pk)

    def test_non_finite_usage_is_rejected_without_writing_a_row(self):
        for quantity in ["NaN", "Infinity", "-Infinity"]:
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                models.UsageEvent.record(
                    tenant_id=self.tenant.pk, provider_event_key="invalid-number",
                    quantity=quantity, unit="gpu_seconds",
                )
        self.assertFalse(models.UsageEvent.all_objects.exists())

    def test_bulk_upsert_cannot_rewrite_an_accounting_record(self):
        rate = models.RateRevision.objects.create(
            tenant_id=self.tenant.pk, revision="bulk", provider="owned",
            resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal("1"),
            currency="USD", effective_from=self.occurred_at, source="schedule",
        )
        replacement = models.RateRevision(
            tenant_id=self.tenant.pk, revision=rate.revision, provider="owned",
            resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal("2"),
            currency="USD", effective_from=self.occurred_at, source="schedule",
        )
        with self.assertRaises(ValidationError):
            models.RateRevision.all_objects.bulk_create(
                [replacement], update_conflicts=True, update_fields=["unit_price"],
                unique_fields=["tenant_id", "revision"],
            )
        rate.refresh_from_db()
        self.assertEqual(rate.unit_price, Decimal("1"))

    def test_rate_is_authorized_by_tenant_unit_and_effective_interval(self):
        other = Tenant.objects.create(slug="accounting-other", name="Other")
        rate = models.RateRevision.objects.create(
            tenant_id=self.tenant.pk, revision="scoped", provider="owned",
            resource_kind="gpu", unit="gpu_seconds", unit_price=Decimal("1"),
            currency="USD", effective_from=self.occurred_at,
            effective_until=self.occurred_at + timedelta(days=1), source="schedule",
        )
        kwargs = dict(provider_event_key="scoped-usage", quantity=1,
                      unit=rate.unit, rate_revision=rate.revision)
        with self.assertRaises(models.RateRevision.DoesNotExist):
            models.UsageEvent.record(tenant_id=other.pk, occurred_at=self.occurred_at, **kwargs)
        with self.assertRaises(ValueError):
            models.UsageEvent.record(tenant_id=self.tenant.pk, **{**kwargs, "unit": "cpu_seconds"},
                                     occurred_at=self.occurred_at)
        for occurred in [self.occurred_at - timedelta(seconds=1), rate.effective_until]:
            with self.assertRaises(ValueError):
                models.UsageEvent.record(tenant_id=self.tenant.pk, occurred_at=occurred, **kwargs)
        self.assertFalse(models.UsageEvent.all_objects.exists())

    def test_cross_tenant_and_unpriced_adjustments_are_rejected(self):
        event = models.UsageEvent.record(tenant_id=self.tenant.pk, provider_event_key="unpriced",
                                        quantity=1, unit="gpu_seconds")
        other = Tenant.objects.create(slug="adjustment-other", name="Other")
        for tenant in [self.tenant, other]:
            with self.assertRaises(ValueError):
                models.UsageAdjustment.record(tenant_id=tenant.pk, usage_event=event,
                                              amount_delta="1", reason="Bill", source_event_key="bill")
        self.assertFalse(models.UsageAdjustment.all_objects.exists())
        self.assertIsNone(event.net_amount())
