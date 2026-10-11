"""Custom format no-code mapping and sample extension adapter (TECH-028 / PRD Scenario 6)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from contracts.validate import validate_envelope


class CustomFormatValidationError(Exception):
    """Raised when custom record does not match mapped schema or is malformed."""
    pass


class NoCodeRecordMapper:
    """Maps custom proprietary records into canonical sample envelopes without writing code."""

    def __init__(self, mapping_spec: Mapping[str, Any]) -> None:
        self.spec = mapping_spec
        self.field_mappings: dict[str, str] = self.spec.get("field_mappings", {})
        self.required_fields: list[str] = self.spec.get("required_fields", [])
        self.coordinate_keys: dict[str, str] = self.spec.get("coordinate_mapping", {})
        self.timestamp_key: str = self.spec.get("timestamp_field", "timestamp")

    def map_record(self, raw_record: Mapping[str, Any]) -> dict[str, Any]:
        """Validate raw custom record and project it to canonical sample envelope representation."""
        # 1. Validation check
        for rf in self.required_fields:
            if rf not in raw_record or raw_record[rf] is None or raw_record[rf] == "":
                raise CustomFormatValidationError(f"Missing required custom field '{rf}'.")

        # 2. Extract content & attributes
        text_field = self.field_mappings.get("text", "text")
        text_val = str(raw_record.get(text_field, ""))

        coords = None
        if self.coordinate_keys:
            try:
                coords = [
                    float(raw_record[self.coordinate_keys["x"]]),
                    float(raw_record[self.coordinate_keys["y"]]),
                    float(raw_record[self.coordinate_keys["width"]]),
                    float(raw_record[self.coordinate_keys["height"]]),
                ]
            except (KeyError, ValueError, TypeError) as exc:
                raise CustomFormatValidationError(f"Malformed coordinate values: {exc}") from exc

        timestamp = raw_record.get(self.timestamp_key)

        sample = {
            "schema_version": "1.0",
            "sample_id": hashlib.sha256(json.dumps(raw_record, sort_keys=True).encode("utf-8")).hexdigest()[:32],
            "text": text_val,
            "metadata": {
                "source_format": "custom_mapped",
                "coordinates": coords,
                "timestamp": timestamp,
                "raw_attributes": {k: v for k, v in raw_record.items() if k not in self.field_mappings.values()},
            },
        }
        return sample


class SampleCustomFormatAdapter:
    """Sample extension adapter reading custom sensor/telemetry records and producing canonical training samples."""

    def __init__(self, mapper: NoCodeRecordMapper) -> None:
        self.mapper = mapper

    def convert_custom_batch(self, raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch convert custom records, failing closed on invalid entries."""
        converted = []
        for idx, rec in enumerate(raw_records):
            try:
                envelope = self.mapper.map_record(rec)
                converted.append(envelope)
            except CustomFormatValidationError as exc:
                raise CustomFormatValidationError(f"Record at index {idx} failed custom format validation: {exc}") from exc
        return converted
