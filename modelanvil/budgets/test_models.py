"""Budget/usage admission regression tests."""
from django.test import TestCase
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

import modelanvil.budgets.models as budget_models
from modelanvil.identity.models import Tenant


class BudgetModelTests(TestCase):
    def test_budget_policy_and_reservation_contract_exists(self):
        self.assertTrue(hasattr(budget_models, "BudgetPolicy"))
        self.assertTrue(hasattr(budget_models, "BudgetReservation"))

    def test_usage_event_is_idempotent_per_provider_key(self):
        self.assertTrue(hasattr(budget_models, "UsageEvent"))
        tenant = Tenant.objects.create(slug="budget-test", name="Budget Test")
        policy = budget_models.BudgetPolicy.objects.create(
            tenant_id=tenant.tenant_id, name="monthly", period="monthly",
            unit="gpu_seconds", limit_amount=100,
        )
        reservation = budget_models.BudgetReservation.reserve(
            tenant_id=tenant.tenant_id, policy=policy, job_id="00000000-0000-0000-0000-000000000001",
            estimated_amount=60,
        )
        self.assertEqual(reservation.state, budget_models.BudgetReservation.State.RESERVED)
        with self.assertRaises(ValueError):
            budget_models.BudgetReservation.reserve(
                tenant_id=tenant.tenant_id, policy=policy, job_id="00000000-0000-0000-0000-000000000002",
                estimated_amount=50,
            )
        first = budget_models.UsageEvent.record(
            tenant_id=tenant.tenant_id, provider_event_key="bill-1", quantity=10,
            unit="gpu_seconds", reservation=reservation,
        )
        duplicate = budget_models.UsageEvent.record(
            tenant_id=tenant.tenant_id, provider_event_key="bill-1", quantity=10,
            unit="gpu_seconds", reservation=reservation,
        )
        self.assertEqual(first.pk, duplicate.pk)

    def test_settled_reservation_consumes_actual_not_estimated_amount(self):
        tenant = Tenant.objects.create(slug="settled-budget", name="Settled Budget")
        policy = budget_models.BudgetPolicy.objects.create(
            tenant_id=tenant.tenant_id, name="monthly", period="monthly",
            unit="gpu_seconds", limit_amount=100,
        )
        first = budget_models.BudgetReservation.reserve(
            tenant_id=tenant.tenant_id, policy=policy,
            job_id="00000000-0000-0000-0000-000000000011", estimated_amount=60,
        )
        first.settle(20)
        second = budget_models.BudgetReservation.reserve(
            tenant_id=tenant.tenant_id, policy=policy,
            job_id="00000000-0000-0000-0000-000000000012", estimated_amount=70,
        )
        self.assertEqual(second.estimated_amount, 70)

    def test_daily_budget_resets_on_next_calendar_day(self):
        tenant = Tenant.objects.create(slug="daily-budget", name="Daily Budget")
        policy = budget_models.BudgetPolicy.objects.create(
            tenant_id=tenant.tenant_id, name="daily", period="daily",
            unit="gpu_seconds", limit_amount=100,
        )
        with patch("modelanvil.budgets.models.timezone.now", return_value=datetime(2026, 10, 8, 12, tzinfo=dt_timezone.utc)):
            budget_models.BudgetReservation.reserve(
                tenant_id=tenant.tenant_id, policy=policy,
                job_id="00000000-0000-0000-0000-000000000021", estimated_amount=90,
            )
        with patch("modelanvil.budgets.models.timezone.now", return_value=datetime(2026, 10, 9, 12, tzinfo=dt_timezone.utc)):
            reservation = budget_models.BudgetReservation.reserve(
                tenant_id=tenant.tenant_id, policy=policy,
                job_id="00000000-0000-0000-0000-000000000022", estimated_amount=90,
            )
        self.assertEqual(reservation.estimated_amount, 90)
