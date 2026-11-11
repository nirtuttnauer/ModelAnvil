"""Schema-version window checks for canonical documents.

These tests load the vendored sample-envelope schema through the contracts
package and exercise ``validate_envelope``. No network and no new schema file.
"""

from __future__ import annotations

import unittest

from contracts.errors import ErrorCode
from contracts.schemas import load_schema
from contracts.validate import InvalidDocumentError, validate_envelope
from contracts.versioning import ContractId, parse_version, supported_versions


def _minimal_envelope(schema_version: str | None) -> dict:
    """Build the smallest sample envelope the canonical schema accepts.

    Field names and constraints come from the loaded schema. The body matches
    the minimal document already used by the data-registry contract test.
    """
    document = {
        "sample_id": "b51630a7-06a9-4d9a-998e-1f959a9e1e11",
        "source_group_id": "group-1",
        "blocks": [{"block_id": "b1", "type": "text", "text": "hello"}],
        "provenance": {
            "source_snapshot_ref": "snap-1",
            "source_record_key": "row-1",
            "content_sha256": "a" * 64,
        },
    }
    if schema_version is not None:
        document["schema_version"] = schema_version
    return document


class SchemaVersionWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema("sample-envelope")
        cls.window = supported_versions(ContractId.SAMPLE_ENVELOPE)

    def test_missing_schema_version_is_rejected(self) -> None:
        document = _minimal_envelope(None)
        self.assertNotIn("schema_version", document)
        self.assertIn("schema_version", self.schema["required"])
        with self.assertRaises(InvalidDocumentError) as caught:
            validate_envelope(document)
        error = caught.exception
        self.assertIn(error.code, ErrorCode.ALL)
        self.assertEqual(error.code, ErrorCode.VALIDATION_FAILED)
        rendered = error.to_api_error().to_dict()["error"]
        self.assertEqual(rendered["code"], ErrorCode.VALIDATION_FAILED)
        self.assertTrue(rendered["details"])
        blob = " ".join(item["message"] for item in rendered["details"])
        self.assertIn("schema_version", blob)

    def test_malformed_schema_version_is_rejected(self) -> None:
        document = _minimal_envelope("v1.0")
        with self.assertRaises(ValueError):
            parse_version(document["schema_version"])
        with self.assertRaises(InvalidDocumentError) as caught:
            validate_envelope(document)
        error = caught.exception
        self.assertEqual(error.code, ErrorCode.SCHEMA_VERSION_UNSUPPORTED)
        self.assertIn(error.code, ErrorCode.ALL)
        rendered = error.to_api_error().to_dict()["error"]
        self.assertEqual(rendered["code"], ErrorCode.SCHEMA_VERSION_UNSUPPORTED)
        self.assertEqual(rendered["details"][0]["path"], ".schema_version")
        self.assertIn("v1.0", rendered["details"][0]["message"])

    def test_major_outside_contracts_window_is_rejected(self) -> None:
        low, high = self.window
        outside_versions = [f"{high.major + 1}.0"]
        if low.major > 0:
            outside_versions.append(f"{low.major - 1}.0")
        for outside in outside_versions:
            parsed = parse_version(outside)
            self.assertTrue(parsed < low or parsed > high)
            self.assertNotIn(parsed.major, range(low.major, high.major + 1))
            document = _minimal_envelope(outside)
            with self.assertRaises(InvalidDocumentError) as caught:
                validate_envelope(document)
            error = caught.exception
            self.assertEqual(error.code, ErrorCode.SCHEMA_VERSION_UNSUPPORTED)
            self.assertEqual(error.status_code, 422)
            self.assertIn(error.code, ErrorCode.ALL)
            rendered = error.to_api_error(request_id="req-anvil-056").to_dict()["error"]
            self.assertEqual(rendered["code"], "schema_version_unsupported")
            self.assertEqual(rendered["request_id"], "req-anvil-056")
            self.assertEqual(rendered["details"][0]["path"], ".schema_version")
            self.assertIn(str(parsed), rendered["details"][0]["message"])
            self.assertIn(str(low), rendered["message"])
            self.assertIn(str(high), rendered["message"])

    def test_minimal_document_inside_window_is_accepted(self) -> None:
        const = self.schema["properties"]["schema_version"]["const"]
        parsed = parse_version(const)
        low, high = self.window
        self.assertGreaterEqual(parsed, low)
        self.assertLessEqual(parsed, high)
        document = _minimal_envelope(const)
        accepted = validate_envelope(document)
        self.assertIs(accepted, document)
        self.assertEqual(accepted["schema_version"], const)
