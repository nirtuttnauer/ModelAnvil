"""Core middleware: request-id and structured exception handling.

:class:`RequestIdMiddleware` assigns a stable id to every request (honoring
an inbound ``X-Request-Id``) and binds the request/tenant context.

:class:`ExceptionMiddleware` catches unhandled exceptions and renders them
as the shared structured error envelope, so a raw stack trace never reaches
a client and every error has a stable machine code.
"""

from __future__ import annotations

import logging
from typing import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

from contracts import ApiError, ErrorCode, error_from_exception
from modelanvil.core.ids import uuid7
from modelanvil.core import tenancy
from modelanvil.core.signals import bind_request

logger = logging.getLogger("modelanvil.core")


class RequestIdMiddleware:
    """Assign and propagate a request id; bind the request context."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("X-Request-Id") or str(uuid7())
        request.modelanvil_request_id = request_id  # type: ignore[attr-defined]
        bind_request(request)
        response = self.get_response(request)
        response["X-Request-Id"] = request_id
        return response


class ExceptionMiddleware:
    """Render unhandled exceptions as the shared error envelope."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            response = self.get_response(request)
        except Exception as exc:  # noqa: BLE001 - top-level safety net
            api_error = error_from_exception(exc)
            request_id = getattr(request, "modelanvil_request_id", None)
            if api_error.status_code >= 500:
                logger.exception(
                    "unhandled exception",
                    extra={
                        "request_id": request_id,
                        "tenant": str(getattr(request, "modelanvil_tenant", None)),
                    },
                )
            api_error.request_id = request_id
            body = api_error.to_dict()
            resp = JsonResponse(body, status=api_error.status_code)
            resp["X-Request-Id"] = request_id or ""
            return resp
        return response
