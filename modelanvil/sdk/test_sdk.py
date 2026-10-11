"""Unit and scenario tests for WP-14 Extension SDK and Format Qualification (TECH-007, TECH-028 / PRD Scenarios 5, 6)."""
from unittest import TestCase

from contracts.validate import InvalidDocumentError
from modelanvil.sdk.custom_format import (
    CustomFormatValidationError,
    NoCodeRecordMapper,
    SampleCustomFormatAdapter,
)
from modelanvil.sdk.format_qualification import (
    qualify_format_support,
    test_mixed_media_round_trip,
)
from modelanvil.sdk.manifest import AdapterManifestBuilder
from modelanvil.sdk.runtime import (
    ExtensionPreflightError,
    IsolatedExtensionRuntime,
    PermissionDeniedError,
)


class ExtensionSDKTests(TestCase):
    def test_adapter_manifest_builder_and_validation(self):
        """TECH-028: Fluent manifest builder outputs schema-conformant extension declarations."""
        manifest = (
            AdapterManifestBuilder("custom.sensor.adapter", "1.2.0")
            .with_license("apache-2.0")
            .with_permissions(
                network_hosts=["telemetry.internal"],
                artifact_access=["read_job_inputs", "write_attempt_staging"],
            )
            .add_capability(
                kind="read",
                input_schema_refs=["urn:modelanvil:schema:sample-envelope:1.0"],
                output_schema_refs=["urn:modelanvil:schema:sample-envelope:1.0"],
                formats=["sensor_json"],
            )
            .add_dependency("numpy", "1.26.0", "sha256:" + "a" * 64)
            .build()
        )

        self.assertEqual(manifest["adapter_id"], "custom.sensor.adapter")
        self.assertEqual(manifest["version"], "1.2.0")
        self.assertIn("custom.sensor.adapter", manifest["image"])
        self.assertEqual(manifest["permissions"]["network_hosts"], ["telemetry.internal"])

    def test_isolated_runtime_enforces_permissions(self):
        """TECH-028: Isolated runtime blocks unauthorized network probes and storage access."""
        manifest = (
            AdapterManifestBuilder("secure.converter", "1.0.0")
            .with_permissions(network_hosts=["api.approved.com"])
            .build()
        )

        runtime = IsolatedExtensionRuntime(manifest)

        # 1. Allowed network host succeeds
        runtime.verify_network_access("api.approved.com")

        # 2. Denied unauthorized network probe raises PermissionDeniedError
        with self.assertRaises(PermissionDeniedError):
            runtime.verify_network_access("malicious-exfiltration.net")

        # 3. Denied storage access
        with self.assertRaises(PermissionDeniedError):
            runtime.verify_artifact_access("write_to_arbitrary_s3_bucket")

    def test_incompatible_extension_fails_preflight(self):
        """TECH-028: Incompatible platform API fails preflight before any compute is spent."""
        manifest = AdapterManifestBuilder("future.adapter", "1.0.0").build()
        runtime = IsolatedExtensionRuntime(manifest)

        with self.assertRaises(ExtensionPreflightError):
            runtime.preflight_check(target_platform_api="2.0-beta")

    def test_format_qualification_reports(self):
        """PRD Scenario 5: Formal qualification report across all promised formats."""
        formats = ["text", "chat", "code", "table", "svg", "media"]
        for fmt in formats:
            report = qualify_format_support(fmt)
            self.assertEqual(report.status, "supported")
            self.assertTrue(report.storage_supported)
            self.assertTrue(report.parse_supported)
            self.assertTrue(report.round_trip_fidelity)

        # Unknown format requires extension
        report_unknown = qualify_format_support("unknown_binary_blob")
        self.assertEqual(report_unknown.status, "requires_extension")
        self.assertFalse(report_unknown.storage_supported)

    def test_mixed_media_round_trip_fidelity(self):
        """TECH-007: Preserves spans, timestamps, coordinate systems, and ordering without mutation."""
        mixed_sample = {
            "spans": [{"start": 0, "end": 45, "label": "header"}],
            "timestamps": [1728500000.0, 1728500060.0],
            "coordinates": {"box": [10.5, 20.0, 100.5, 200.0], "system": "normalized_xywh"},
            "order": ["text_intro", "image_bbox", "table_metrics", "caption"],
            "payload": "Sensor unit 42 detected pressure anomaly.",
        }

        self.assertTrue(test_mixed_media_round_trip(mixed_sample))

    def test_custom_format_no_code_mapping_and_malformed_rejection(self):
        """PRD Scenario 6: No-code mapper maps proprietary records and rejects malformed inputs."""
        spec = {
            "required_fields": ["sensor_id", "reading", "timestamp"],
            "field_mappings": {"text": "reading"},
            "coordinate_mapping": {"x": "pos_x", "y": "pos_y", "width": "w", "height": "h"},
            "timestamp_field": "timestamp",
        }
        mapper = NoCodeRecordMapper(spec)
        adapter = SampleCustomFormatAdapter(mapper)

        valid_records = [
            {
                "sensor_id": "SN-001",
                "reading": "Telemetry OK: 101.3 kPa",
                "pos_x": 10.0, "pos_y": 20.0, "w": 5.0, "h": 5.0,
                "timestamp": "2026-10-08T12:00:00Z",
            },
            {
                "sensor_id": "SN-002",
                "reading": "Telemetry Alert: 108.9 kPa",
                "pos_x": 15.0, "pos_y": 25.0, "w": 5.0, "h": 5.0,
                "timestamp": "2026-10-08T12:01:00Z",
            },
        ]

        # Valid batch converts cleanly
        converted = adapter.convert_custom_batch(valid_records)
        self.assertEqual(len(converted), 2)
        self.assertEqual(converted[0]["text"], "Telemetry OK: 101.3 kPa")
        self.assertEqual(converted[0]["metadata"]["coordinates"], [10.0, 20.0, 5.0, 5.0])

        # Malformed record missing required field fails closed
        malformed_records = [
            {"sensor_id": "SN-003", "reading": "Missing timestamp!"}
        ]
        with self.assertRaises(CustomFormatValidationError):
            adapter.convert_custom_batch(malformed_records)
