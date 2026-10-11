"""Core signal registrations.

Wires the active-tenant context into the request lifecycle. The
``request_started`` signal fires once per request; we bind the request and
(once authentication has run) the tenant. ``request_finished`` resets the
context so no tenant leaks between requests.
"""

from __future__ import annotations

import logging

from django.core.signals import request_finished, request_started

from modelanvil.core import tenancy

logger = logging.getLogger("modelanvil.core")


def _on_request_started(sender: type, **_kwargs: object) -> None:
    # The request object is not passed by request_started; the middleware
    # handles binding. This hook is a no-op placeholder kept for symmetry
    # and to guarantee the contextvar is initialized per request context.
    tenancy.reset_context()


def _on_request_finished(sender: type, **_kwargs: object) -> None:
    tenancy.reset_context()


def bind_request(request: object) -> None:
    """Bind the request (and any pre-set tenant) into the context.

    Called from :class:`modelanvil.core.middleware.RequestIdMiddleware` at
    the start of processing, before authentication.
    """
    tenancy.bind_request(request)  # type: ignore[arg-type]


request_started.connect(_on_request_started, dispatch_uid="modelanvil.core.request_started")
request_finished.connect(_on_request_finished, dispatch_uid="modelanvil.core.request_finished")
