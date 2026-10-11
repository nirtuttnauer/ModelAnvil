"""OpenAPI specification contract tests (WP-02 published contracts).

Verifies that the canonical OpenAPI 3.1 contract is published at
``/api/v1/openapi.json`` and matches the registered routes and components.
"""
from __future__ import annotations

import json
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from contracts.schemas import load_schema, schema_path


@override_settings(ALLOWED_HOSTS=["testserver"])
class OpenApiContractTests(TestCase):
    """The OpenAPI 3.1 specification is available and valid."""

    def setUp(self) -> None:
        self.client = APIClient()

    def test_schema_loader_loads_canonical_openapi(self) -> None:
        schema = load_schema("openapi")
        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertEqual(schema["info"]["title"], "ModelAnvil Control Plane REST API")
        self.assertIn("paths", schema)
        self.assertIn("components", schema)

    def test_openapi_endpoint_serves_json_spec(self) -> None:
        response = self.client.get("/api/v1/openapi.json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Content-Type"], "application/json")

        body = response.json()
        self.assertEqual(body["openapi"], "3.1.0")
        self.assertIn("/health/", body["paths"])
        self.assertIn("/ready/", body["paths"])
        self.assertIn("/tenants/", body["paths"])
        self.assertIn("/teams/", body["paths"])
        self.assertIn("/projects/", body["paths"])
        self.assertIn("/project-configs/", body["paths"])
        self.assertIn("/datasets/", body["paths"])
        self.assertIn("/dataset-revisions/", body["paths"])
        self.assertIn("/artifacts/", body["paths"])
        self.assertIn("/jobs/", body["paths"])
        self.assertIn("/budget-policies/", body["paths"])
        self.assertIn("/audit/", body["paths"])

    def test_components_contain_core_schemas_and_security(self) -> None:
        schema = load_schema("openapi")
        components = schema.get("components", {})
        schemas = components.get("schemas", {})

        expected_schemas = [
            "Tenant", "User", "ApiKey", "Membership",
            "Team", "Project", "TeamMembership", "ProjectMembership", "ProjectConfig",
            "Dataset", "DatasetRevision", "DatasetPrepare",
            "Artifact", "Job", "JobAttempt",
            "BudgetPolicy", "BudgetReservation", "UsageEvent", "AuditEvent",
            "ApiErrorEnvelope", "Page",
        ]
        for name in expected_schemas:
            self.assertIn(name, schemas, f"Schema {name} missing from components")

        security = components.get("securitySchemes", {})
        self.assertIn("BearerAuth", security)
        self.assertEqual(security["BearerAuth"]["type"], "http")
        self.assertEqual(security["BearerAuth"]["scheme"], "bearer")

    def test_openapi_is_publicly_accessible(self) -> None:
        # No Authorization header supplied
        response = self.client.get("/api/v1/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), dict)
