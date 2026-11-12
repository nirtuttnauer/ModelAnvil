"""Active tenant and project context is visible to getters and cleared by reset."""
from __future__ import annotations

import uuid

from django.http import HttpRequest
from django.test import SimpleTestCase

from modelanvil.core.tenancy import (
    bind_request,
    get_active_project,
    get_active_request,
    get_active_tenant,
    reset_context,
    set_active_project,
    set_active_tenant,
)


class TenancyContextTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_context()

    def tearDown(self) -> None:
        reset_context()

    def test_set_active_tenant_and_project_are_returned_by_getters(self) -> None:
        tenant_id = uuid.uuid4()
        project_id = uuid.uuid4()
        set_active_tenant(tenant_id)
        set_active_project(project_id)
        self.assertEqual(get_active_tenant(), tenant_id)
        self.assertEqual(get_active_project(), project_id)

    def test_reset_context_clears_tenant_and_project_to_unscoped(self) -> None:
        set_active_tenant(uuid.uuid4())
        set_active_project(uuid.uuid4())
        request = HttpRequest()
        bind_request(request)
        set_active_tenant(uuid.uuid4())
        set_active_project(uuid.uuid4())
        self.assertIs(get_active_request(), request)

        reset_context()

        self.assertIsNone(get_active_tenant())
        self.assertIsNone(get_active_project())
        self.assertIsNone(get_active_request())

    def test_second_set_after_reset_does_not_see_the_first_tenant(self) -> None:
        first_tenant = uuid.uuid4()
        first_project = uuid.uuid4()
        second_tenant = uuid.uuid4()
        second_project = uuid.uuid4()
        set_active_tenant(first_tenant)
        set_active_project(first_project)
        reset_context()
        set_active_tenant(second_tenant)
        set_active_project(second_project)

        self.assertEqual(get_active_tenant(), second_tenant)
        self.assertNotEqual(get_active_tenant(), first_tenant)
        self.assertEqual(get_active_project(), second_project)
        self.assertNotEqual(get_active_project(), first_project)

    def test_next_request_after_reset_does_not_keep_the_previous_tenant(self) -> None:
        previous_tenant = uuid.uuid4()
        previous_project = uuid.uuid4()
        previous_request = HttpRequest()
        bind_request(previous_request)
        set_active_tenant(previous_tenant)
        set_active_project(previous_project)
        reset_context()

        next_request = HttpRequest()
        bind_request(next_request)
        self.assertIs(get_active_request(), next_request)
        self.assertIsNone(get_active_tenant())
        self.assertIsNone(get_active_project())

        next_tenant = uuid.uuid4()
        set_active_tenant(next_tenant)
        self.assertEqual(get_active_tenant(), next_tenant)
        self.assertNotEqual(get_active_tenant(), previous_tenant)
        self.assertIsNone(get_active_project())
