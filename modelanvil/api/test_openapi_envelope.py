"""Validity of the published OpenAPI document and its error envelope.

``openapi_spec`` loads the document with ``contracts.schemas.load_schema``.
These tests read that same file. They do not open a socket.
"""
from __future__ import annotations

import json
from typing import Any

from django.test import SimpleTestCase

from contracts.schemas import load_schema, schema_path


def _is_health_path(name: str) -> bool:
    return name.strip("/") == "health"


class OpenApiEnvelopeTests(SimpleTestCase):
    """The served document stays JSON, OpenAPI major version 3, with health and the error envelope."""

    def _document(self) -> dict[str, Any]:
        path = schema_path("openapi")
        parsed = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed, load_schema("openapi"))
        return parsed

    def test_document_is_valid_json_with_openapi_major_3(self) -> None:
        document = self._document()
        version = document["openapi"]
        self.assertIsInstance(version, str)
        major = version.split(".", 1)[0]
        self.assertTrue(major.isdigit(), version)
        self.assertEqual(int(major), 3)

    def test_health_path_remains_defined(self) -> None:
        paths = self._document()["paths"]
        health = [name for name in paths if _is_health_path(name)]
        self.assertTrue(health)
        for name in health:
            operation = paths[name]
            self.assertIsInstance(operation, dict)
            self.assertTrue(operation)

    def test_error_envelope_component_remains_defined(self) -> None:
        components = self._document()["components"]
        envelope = components["schemas"]["ApiErrorEnvelope"]
        self.assertEqual(envelope["type"], "object")
        self.assertIn("error", envelope["required"])
        error = envelope["properties"]["error"]
        self.assertEqual(error["type"], "object")
        self.assertIn("code", error["required"])
        self.assertIn("message", error["required"])
        response = components["responses"]["ErrorResponse"]
        self.assertEqual(
            response["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ApiErrorEnvelope",
        )
