"""Tenant-scoped read access to priced usage and reconciliation."""
from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.budgets.models import RateRevision, UsageAdjustment, UsageEvent
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key


@override_settings(ALLOWED_HOSTS=["testserver"])
class AccountingApiTests(TestCase):
    def test_usage_response_discloses_priced_and_adjusted_amounts(self):
        tenant = Tenant.objects.create(slug="accounting-api", name="Accounting API")
        secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name="viewer", role=Role.VIEWER, secret_hash=digest)
        occurred = datetime(2026, 10, 9, tzinfo=timezone.utc)
        rate = RateRevision.objects.create(
            tenant_id=tenant.pk, revision="usd-v1", provider="owned", resource_kind="gpu",
            unit="gpu_seconds", unit_price=Decimal("1"), currency="USD",
            effective_from=occurred, source="schedule",
        )
        event = UsageEvent.record(tenant_id=tenant.pk, provider_event_key="api-bill", quantity=10,
                                 unit=rate.unit, rate_revision=rate.revision, occurred_at=occurred)
        UsageAdjustment.record(tenant_id=tenant.pk, usage_event=event, amount_delta="-2",
                               reason="Credit", source_event_key="credit")
        client = APIClient()
        response = client.get(f"/api/v1/usage-events/{event.usage_id}/",
                              HTTP_AUTHORIZATION=f"Bearer {secret}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("amount", response.json())
        self.assertEqual(response.json()["amount"], "10.000000")
        self.assertEqual(response.json()["net_amount"], "8.000000")
        self.assertEqual(response.json()["currency"], "USD")
