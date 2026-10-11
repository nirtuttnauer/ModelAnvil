"""JSON Schema validation with stable, structured errors.

``validate_document`` is the single entry point every boundary uses to
check a machine document against its canonical schema. It:

1. Checks the document's ``schema_version`` against the contract's
   supported window (rejecting unsupported majors with a stable code).
2. Runs the document through ``jsonschema`` and collects *all* violations,
   not just the first, so a producer gets full feedback in one round trip.
3. Returns either the validated document or raises
   :class:`InvalidDocumentError` carrying structured details that map
   directly onto the shared :class:`contracts.errors.ApiError`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import jsonschema
from jsonschema import Draft202012Validator, ValidationError

from contracts.errors import ApiError, ErrorCode
from contracts.schemas import load_schema
from contracts.versioning import ContractId, is_compatible, parse_version, supported_versions

__all__ = [
    "ValidationErrorDetail",
    "InvalidDocumentError",
    "validate_document",
    "validate_envelope",
    "validate_adapter_manifest",
]


@dataclass
class ValidationErrorDetail:
    """A single structured validation fault."""

    path: str
    message: str
    schema_path: str = ""

    def to_dict(self) -> Dict[str, str]:
        out: Dict[str, str] = {"path": self.path, "message": self.message}
        if self.schema_path:
            out["schema_path"] = self.schema_path
        return out


class InvalidDocumentError(Exception):
    """Raised when a document fails schema or version validation.

    Carries the list of :class:`ValidationErrorDetail` and the HTTP status
    to render. ``to_api_error`` produces the shared error envelope.
    """

    def __init__(
        self,
        details: List[ValidationErrorDetail],
        *,
        code: str = ErrorCode.VALIDATION_FAILED,
        message: str = "Document failed validation",
        status_code: int = 422,
    ) -> None:
        self.details = details
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    @property
    def detail_dicts(self) -> List[Dict[str, str]]:
        return [d.to_dict() for d in self.details]

    def to_api_error(self, request_id: Optional[str] = None) -> ApiError:
        return ApiError(
            code=self.code,
            message=self.message,
            status_code=self.status_code,
            details=self.detail_dicts,
            request_id=request_id,
        )


def _dotted_path(path: List[Any]) -> str:
    """Convert a jsonschema JSON pointer path to a dotted string."""
    if not path:
        return "(root)"
    parts = []
    for seg in path:
        if isinstance(seg, int):
            parts.append(f"[{seg}]")
        else:
            parts.append(f".{seg}" if parts else str(seg))
    return "".join(parts)


def _collect_errors(
    validator: Draft202012Validator, document: Any
) -> List[ValidationErrorDetail]:
    details: List[ValidationErrorDetail] = []
    seen = set()
    for err in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        key = (tuple(err.absolute_path), err.validator, err.message)
        if key in seen:
            continue
        seen.add(key)
        details.append(
            ValidationErrorDetail(
                path=_dotted_path(list(err.absolute_path)),
                message=err.message,
                schema_path=_dotted_path(list(err.schema_path)),
            )
        )
    return details


def _check_version(document: Dict[str, Any], contract: str) -> Optional[InvalidDocumentError]:
    """Return an error if ``schema_version`` is outside the supported window."""
    version_raw = document.get("schema_version")
    if version_raw is None:
        return None  # absence is handled by the schema's required check
    try:
        version = parse_version(str(version_raw))
    except ValueError:
        return InvalidDocumentError(
            [ValidationErrorDetail(path=".schema_version", message=f"malformed version {version_raw!r}")],
            code=ErrorCode.SCHEMA_VERSION_UNSUPPORTED,
            message=f"Unsupported or malformed schema_version {version_raw!r}",
            status_code=422,
        )
    lo, hi = supported_versions(contract)
    if not (lo <= version <= hi):
        return InvalidDocumentError(
            [
                ValidationErrorDetail(
                    path=".schema_version",
                    message=f"{version} outside supported window {lo}..{hi}",
                )
            ],
            code=ErrorCode.SCHEMA_VERSION_UNSUPPORTED,
            message=f"Unsupported schema_version {version} (supported {lo}..{hi})",
            status_code=422,
        )
    return None


def validate_document(
    document: Any,
    schema_name: str,
    *,
    contract: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate ``document`` against the canonical schema ``schema_name``.

    Returns the document unchanged on success. Raises
    :class:`InvalidDocumentError` (or a version error) on failure.
    """
    contract = contract or _default_contract(schema_name)

    # 1) Version window check (only if the document declares one).
    if isinstance(document, dict):
        version_error = _check_version(document, contract)
        if version_error is not None:
            raise version_error

    # 2) Full JSON Schema validation.
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema)
    errors = _collect_errors(validator, document)
    if errors:
        raise InvalidDocumentError(
            errors,
            code=ErrorCode.VALIDATION_FAILED,
            message=f"Document failed validation with {len(errors)} error(s)",
            status_code=422,
        )
    return document


def _default_contract(schema_name: str) -> str:
    """Map a schema name to its canonical contract id.

    The registry in :mod:`contracts.schemas` is the single source of truth
    for this mapping; the schema name and contract id coincide for the
    current contracts.
    """
    from contracts.schemas import SCHEMA_NAMES

    meta = SCHEMA_NAMES.get(schema_name)
    if meta is not None:
        return meta["contract"]
    return schema_name


def validate_envelope(
    document: Any, *, request_id: Optional[str] = None
) -> Dict[str, Any]:
    """Validate a sample-envelope document."""
    return validate_document(
        document, "sample-envelope", contract=ContractId.SAMPLE_ENVELOPE, request_id=request_id
    )


def validate_adapter_manifest(
    document: Any, *, request_id: Optional[str] = None
) -> Dict[str, Any]:
    """Validate an adapter-manifest document."""
    return validate_document(
        document, "adapter-manifest", contract=ContractId.ADAPTER_MANIFEST, request_id=request_id
    )


def parse_json(text: str) -> Any:
    """Parse JSON text, raising a structured error on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidDocumentError(
            [ValidationErrorDetail(path="(root)", message=str(exc))],
            code=ErrorCode.DOCUMENT_NOT_JSON,
            message="Request body is not valid JSON",
            status_code=400,
        ) from exc
