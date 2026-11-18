"""Request plugin IDs are operator names. Module paths are not IDs."""
import os
import traceback
import uuid
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from modelanvil.compute.plugins import (
    DEFERRED_UNTIL_PILOT,
    PluginError,
    definition,
    provider_claim,
    task_executor,
    validate_configuration,
)


def _marker():
    return "-".join(("plugin", "config", "marker", "069"))


def _task_entry(tenant_id):
    return {
        "contract_version": "1.0",
        "kind": "task",
        "tenant_ids": [str(tenant_id)],
        "executor": "modelanvil.compute.examples:uppercase",
        "configuration_schema": {"type": "object", "additionalProperties": False},
    }


class PluginIdTests(SimpleTestCase):
    def test_module_path_ids_are_rejected_and_not_imported(self):
        tenant_id = uuid.uuid4()
        marker = _marker()
        for plugin_id in ("os.system", "pkg.mod:func"):
            with self.subTest(plugin_id=plugin_id, installed=False):
                with self.assertRaises(PluginError) as caught:
                    definition(plugin_id, tenant_id, "task")
                self.assertNotIn(marker, str(caught.exception))
            entry = _task_entry(tenant_id)
            entry["note"] = marker
            with self.subTest(plugin_id=plugin_id, installed=True):
                with override_settings(MODELANVIL_PLUGINS={plugin_id: entry}):
                    with patch("modelanvil.compute.plugins.importlib.import_module") as importer:
                        with self.assertRaises(PluginError) as caught:
                            definition(plugin_id, tenant_id, "task")
                        self.assertNotIn(marker, str(caught.exception))
                        with self.assertRaises(PluginError):
                            task_executor(plugin_id, {}, tenant_id=tenant_id, digest="a" * 64)
                        importer.assert_not_called()

    def test_plain_operator_id_still_resolves(self):
        tenant_id = uuid.uuid4()
        entry = _task_entry(tenant_id)
        with override_settings(MODELANVIL_PLUGINS={"uppercase": entry}):
            resolved, digest = definition("uppercase", tenant_id, "task")
        self.assertEqual(resolved["executor"], entry["executor"])
        self.assertEqual(len(digest), 64)
        self.assertEqual(provider_claim("uppercase"), "operator_installed")

    def test_deferred_ids_raise_plugin_error_and_stay_deferred(self):
        tenant_id = uuid.uuid4()
        self.assertTrue(DEFERRED_UNTIL_PILOT)
        self.assertNotIn("runpod", DEFERRED_UNTIL_PILOT)
        self.assertEqual(provider_claim("runpod"), "implemented_unqualified")
        for plugin_id in sorted(DEFERRED_UNTIL_PILOT):
            with self.subTest(plugin_id=plugin_id):
                self.assertEqual(provider_claim(plugin_id), "deferred")
                with self.assertRaises(PluginError):
                    definition(plugin_id, tenant_id, "compute")
                entry = _task_entry(tenant_id)
                entry["kind"] = "compute"
                entry["factory"] = "modelanvil.compute.examples:uppercase"
                with override_settings(MODELANVIL_PLUGINS={plugin_id: entry}):
                    with patch("modelanvil.compute.plugins.importlib.import_module") as importer:
                        self.assertEqual(provider_claim(plugin_id), "deferred")
                        with self.assertRaises(PluginError) as caught:
                            definition(plugin_id, tenant_id, "compute")
                        importer.assert_not_called()
                self.assertNotIn("uppercase", str(caught.exception))

    def test_validate_configuration_does_not_require_or_echo_a_secret(self):
        marker = _marker()
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string", "maxLength": 16}},
        }
        with patch.dict(os.environ, {}, clear=True):
            validate_configuration(schema, {"text": "hello"})
            with self.assertRaises(PluginError) as invalid:
                validate_configuration(schema, {"text": marker, "note": marker})
            with self.assertRaises(PluginError) as remote:
                validate_configuration({"$ref": "https://example.invalid/" + marker}, {"token": marker})
            blob = marker + ("x" * 20000)
            with self.assertRaises(PluginError) as oversized:
                validate_configuration(
                    {"type": "object", "additionalProperties": False, "properties": {"text": {"type": "string"}}},
                    {"text": blob},
                )
        for caught in (invalid, remote, oversized):
            error = caught.exception
            rendered = "".join(traceback.format_exception(error))
            rendered += repr(error.args)
            if error.__cause__ is not None:
                rendered += "".join(traceback.format_exception(error.__cause__))
            self.assertNotIn(marker, rendered)
            self.assertNotIn(marker, str(error))
            lowered = str(error).lower()
            self.assertNotIn("secret", lowered)
            self.assertNotIn("credential", lowered)
            self.assertNotIn("token", lowered)
