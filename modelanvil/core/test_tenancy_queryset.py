"""Regression coverage for tenant-scoped query behavior."""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")

import django

django.setup()

from django.test import TestCase

from modelanvil.core.tenancy import reset_context, set_active_tenant
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import WorkerPool


class TenantScopedQuerySetTests(TestCase):
    def tearDown(self) -> None:
        reset_context()

    def test_filter_applies_active_tenant_once(self) -> None:
        tenant = Tenant.objects.create(slug="scope-test", name="Scope")
        set_active_tenant(tenant.tenant_id)
        pool = WorkerPool.all_objects.create(tenant_id=tenant.tenant_id, name="cpu")

        self.assertEqual(list(WorkerPool.objects.filter(name="cpu")), [pool])

    def test_filter_does_not_return_other_tenant_rows(self) -> None:
        first = Tenant.objects.create(slug="scope-first", name="First")
        second = Tenant.objects.create(slug="scope-second", name="Second")
        WorkerPool.all_objects.create(tenant_id=first.tenant_id, name="cpu")
        WorkerPool.all_objects.create(tenant_id=second.tenant_id, name="cpu")

        set_active_tenant(first.tenant_id)
        self.assertEqual(list(WorkerPool.objects.filter(name="cpu").values_list("tenant_id", flat=True)), [first.tenant_id])
