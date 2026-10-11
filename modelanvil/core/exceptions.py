"""DRF exception handler rendering the shared structured error envelope.

Registered in ``REST_FRAMEWORK["EXCEPTION_HANDLER"]``. It maps DRF
exceptions and the contracts :class:`ApiError` to the plan's envelope::

    {"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}

Unknown exceptions become a generic 500 with no internal detail leakage.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions as drf_exceptions
from rest_framework.views import APIView

from contracts import ApiError, ErrorCode, error_from_exception

logger = logging.getLogger("modelanvil.core")


class WorkflowConflict(drf_exceptions.APIException):
    status_code = 409
    default_code = "conflict"
    default_detail = "The workflow changed. Refresh before continuing."


def _request_id(request: Any) -> str | None:
    return getattr(request, "modelanvil_request_id", None)


def _envelope(api_error: ApiError) -> JsonResponse:
    api_error.request_id = _request_id(api_error.request)  # type: ignore[attr-defined]
    return JsonResponse(api_error.to_dict(), status=api_error.status_code)


def api_exception_handler(exc: Exception, context: dict | None = None) -> JsonResponse | None:
    """Map an exception to a structured JSON error response."""
    request: Any = (context or {}).get("request")

    if isinstance(exc, ApiError):
        api_error = exc
    elif isinstance(exc, Http404):
        api_error = ApiError(ErrorCode.RESOURCE_NOT_FOUND, "The requested resource was not found.", 404)
    elif isinstance(exc, DjangoPermissionDenied):
        api_error = ApiError(ErrorCode.FORBIDDEN, "You do not have permission to perform this action.", 403)
    elif isinstance(exc, drf_exceptions.NotAuthenticated):
        api_error = ApiError(ErrorCode.UNAUTHENTICATED, "Authentication credentials were not provided.", 401)
    elif isinstance(exc, drf_exceptions.AuthenticationFailed):
        api_error = ApiError(ErrorCode.UNAUTHENTICATED, "Authentication failed.", 401)
    elif isinstance(exc, drf_exceptions.PermissionDenied):
        api_error = ApiError(ErrorCode.FORBIDDEN, "You do not have permission to perform this action.", 403)
    elif isinstance(exc, drf_exceptions.NotFound):
        api_error = ApiError(ErrorCode.RESOURCE_NOT_FOUND, "The requested resource was not found.", 404)
    elif isinstance(exc, drf_exceptions.ValidationError):
        details = [
            {"path": _dotted(k), "message": "; ".join(str(m) for m in v) if isinstance(v, (list, tuple)) else str(v)}
            for k, v in (exc.detail.items() if isinstance(exc.detail, dict) else [])
        ] or [{"path": "(root)", "message": str(exc.detail)}]
        api_error = ApiError(ErrorCode.VALIDATION_FAILED, "Validation failed.", 400, details=details)
    elif isinstance(exc, drf_exceptions.MethodNotAllowed):
        api_error = ApiError(ErrorCode.INVALID_TRANSITION, "Method not allowed.", 405)
    elif isinstance(exc, drf_exceptions.NotAcceptable):
        api_error = ApiError(ErrorCode.CONFLICT, "Not acceptable.", 406)
    elif isinstance(exc, WorkflowConflict):
        api_error = ApiError(ErrorCode.CONFLICT, str(exc.detail), 409)
    elif isinstance(exc, drf_exceptions.APIException):
        api_error = error_from_exception(exc)
        api_error.status_code = getattr(exc, "status_code", 500)
    else:
        api_error = error_from_exception(exc)
        if api_error.status_code >= 500:
            logger.exception("unhandled DRF exception")

    api_error.request_id = _request_id(request)
    resp = JsonResponse(api_error.to_dict(), status=api_error.status_code)
    if request is not None and api_error.request_id:
        resp["X-Request-Id"] = api_error.request_id
    return resp


def _dotted(key: str) -> str:
    return ".".join(str(part) for part in key.split("."))
