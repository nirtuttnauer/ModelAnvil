"""ModelAnvil canonical contracts.

Pure-Python package holding the source-of-truth machine contracts for the
ModelAnvil control plane. Nothing in this package may import Django; the
Django apps, DRF serializers, and worker protocol all import from here so
that a single canonical definition is shared across every boundary.

Public surface:

- ``schemas``: loaded JSON Schema documents (canonical, versioned).
- ``validate``: JSON Schema validation with stable, structured errors.
- ``errors``: the shared API error model and error-code registry.
- ``versioning``: contract/manifest schema version rules and comparison.
"""

from contracts.errors import ApiError, ErrorCode, error_from_exception
from contracts.schemas import load_schema, schema_name, SCHEMA_NAMES
from contracts.validate import (
    InvalidDocumentError,
    ValidationErrorDetail,
    validate_document,
    validate_envelope,
    validate_adapter_manifest,
    parse_json,
)
from contracts.versioning import (
    ContractVersion,
    parse_version,
    is_compatible,
    CONTRACTS,
)

__all__ = [
    "ApiError",
    "ErrorCode",
    "error_from_exception",
    "load_schema",
    "schema_name",
    "SCHEMA_NAMES",
    "InvalidDocumentError",
    "ValidationErrorDetail",
    "validate_document",
    "validate_envelope",
    "validate_adapter_manifest",
    "parse_json",
    "ContractVersion",
    "parse_version",
    "is_compatible",
    "CONTRACTS",
]

__version__ = "0.1.0"
