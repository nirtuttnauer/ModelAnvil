"""PostgreSQL concurrent provider callback idempotency."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.db import connections
from django.test import TransactionTestCase, tag

from modelanvil.budgets.models import UsageEvent
from modelanvil.identity.models import Tenant


@tag("pg")
class AccountingConcurrencyTests(TransactionTestCase):
    def test_simultaneous_callback_creation_returns_the_same_event(self):
        tenant = Tenant.objects.create(slug="concurrent-billing", name="Concurrent Billing")
        both_creating = threading.Barrier(2)
        first_committed = threading.Event()
        local = threading.local()
        original_save = UsageEvent.save

        def ordered_save(event, *args, **kwargs):
            both_creating.wait(timeout=10)
            if local.index == 1:
                if not first_committed.wait(timeout=10):
                    raise AssertionError("First callback did not commit")
            return original_save(event, *args, **kwargs)

        def record(index):
            local.index = index
            try:
                result = UsageEvent.record(
                    tenant_id=tenant.pk, provider_event_key="simultaneous-callback",
                    quantity=1, unit="gpu_seconds",
                )
                return result.pk
            finally:
                if index == 0:
                    first_committed.set()
                connections.close_all()

        with patch.object(UsageEvent, "save", ordered_save):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(record, index) for index in range(2)]
                results = [future.result(timeout=20) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(UsageEvent.all_objects.count(), 1)
