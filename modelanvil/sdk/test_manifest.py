"""Validation tests for extension manifests (TECH-028).

The canonical required fields and property types live in
``contracts/schemas/adapter-manifest.schema.json``.
"""
from unittest import TestCase

from contracts.validate import InvalidDocumentError
from modelanvil.sdk.manifest import AdapterManifestBuilder, validate_extension_manifest


def _detail_text(error: InvalidDocumentError) -> str:
    parts = [error.message]
    for detail in error.details:
        parts.append(detail.path)
        parts.append(detail.message)
    return "\n".join(parts)


class ExtensionManifestValidationTests(TestCase):
    def _minimal(self) -> dict:
        return AdapterManifestBuilder("custom.sensor.adapter", "1.0.0").build()

    def test_minimal_builder_manifest_is_accepted(self):
        """A minimal manifest from AdapterManifestBuilder passes validation."""
        manifest = self._minimal()
        accepted = validate_extension_manifest(manifest)

        self.assertEqual(accepted["schema_version"], "1.0")
        self.assertEqual(accepted["adapter_id"], "custom.sensor.adapter")
        self.assertEqual(accepted["version"], "1.0.0")
        self.assertEqual(accepted["platform_api"], "1.0")
        self.assertIn("@sha256:", accepted["image"])
        self.assertTrue(accepted["license"])
        self.assertIsInstance(accepted["capabilities"], list)
        self.assertGreaterEqual(len(accepted["capabilities"]), 1)
        self.assertIsInstance(accepted["resources"], dict)
        self.assertIsInstance(accepted["permissions"], dict)
        self.assertIsInstance(accepted["dependencies"], list)

    def test_missing_required_license_is_rejected(self):
        """``license`` is a documented required field; a manifest without it is rejected."""
        manifest = self._minimal()
        del manifest["license"]

        with self.assertRaises(InvalidDocumentError) as caught:
            validate_extension_manifest(manifest)

        self.assertIn("license", _detail_text(caught.exception))

    def test_capabilities_string_is_rejected(self):
        """``capabilities`` is a list; a string in that field is rejected."""
        manifest = self._minimal()
        manifest["capabilities"] = "read"

        with self.assertRaises(InvalidDocumentError) as caught:
            validate_extension_manifest(manifest)

        text = _detail_text(caught.exception)
        self.assertIn("capabilities", text)
        self.assertIn("array", text)

    def test_empty_document_is_rejected(self):
        """An empty document is missing every documented required field."""
        with self.assertRaises(InvalidDocumentError) as caught:
            validate_extension_manifest({})

        text = _detail_text(caught.exception)
        for field in (
            "schema_version",
            "adapter_id",
            "version",
            "platform_api",
            "image",
            "license",
            "capabilities",
            "resources",
            "permissions",
            "dependencies",
        ):
            self.assertIn(field, text)
