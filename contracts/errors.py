"""Shared, structured API error model.

Every boundary that rejects a request or a document produces an
:class:`ApiError` with a stable machine-readable ``code``. The DRF layer
renders it as the plan's standard error envelope::

    {
      "error": {
        "code": "validation_failed",
        "message": "human readable summary",
        "details": [...],           # optional, field-level
        "request_id": "...",        # optional, for correlation
      }
    }

Error codes are a closed registry so clients can branch on them without
parsing prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "ErrorCode",
    "ApiError",
    "error_from_exception",
    "ERROR_ENVELOPE_VERSION",
]

#: Version of the error envelope itself (bumped only for breaking changes).
ERROR_ENVELOPE_VERSION = "1.0.0"


class ErrorCode:
    """Closed registry of stable machine error codes."""

    # Validation / contract
    VALIDATION_FAILED = "validation_failed"
    SCHEMA_VERSION_UNSUPPORTED = "schema_version_unsupported"
    DOCUMENT_NOT_JSON = "document_not_json"

    # Authorization / tenancy
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    TENANT_MISMATCH = "tenant_mismatch"
    RESOURCE_NOT_FOUND = "resource_not_found"

    # Jobs / execution protocol
    JOB_NOT_CLAIMABLE = "job_not_claimable"
    STALE_FENCE_TOKEN = "stale_fence_token"
    LEASE_EXPIRED = "lease_expired"
    BUDGET_EXCEEDED = "budget_exceeded"
    BUDGET_LOCKED = "budget_locked"
    INVALID_TRANSITION = "invalid_transition"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"

    # Generic
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    INTERNAL = "internal_error"

    ALL = (
        VALIDATION_FAILED,
        SCHEMA_VERSION_UNSUPPORTED,
        DOCUMENT_NOT_JSON,
        UNAUTHENTICATED,
        FORBIDDEN,
        TENANT_MISMATCH,
        RESOURCE_NOT_FOUND,
        JOB_NOT_CLAIMABLE,
        STALE_FENCE_TOKEN,
        LEASE_EXPIRED,
        BUDGET_EXCEEDED,
        BUDGET_LOCKED,
        INVALID_TRANSITION,
        IDEMPOTENCY_CONFLICT,
        CONFLICT,
        RATE_LIMITED,
        INTERNAL,
    )


@dataclass
class ApiError:
    """A structured, renderable error.

    ``details`` is a list of human/machine pairs; for validation errors each
    entry carries ``path`` and ``message`` so clients can locate the fault.
    """

    code: str
    message: str
    status_code: int = 400
    details: List[Dict[str, Any]] = field(default_factory=list)
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.code not in ErrorCode.ALL:
            raise ValueError(f"unregistered error code: {self.code!r}")

    def to_dict(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            body["details"] = self.details
        if self.request_id:
            body["request_id"] = self.request_id
        return {"error": body}


def error_from_exception(exc: BaseException) -> ApiError:
    """Map an uncaught exception to a safe, generic :class:`ApiError`.

    Never leaks exception text for internal errors; validation-style
    exceptions carry their details through.
    """
    if isinstance(exc, ApiError):
        return exc
    return ApiError(
        code=ErrorCode.INTERNAL,
        message="Internal server error",
        status_code=500,
    )
