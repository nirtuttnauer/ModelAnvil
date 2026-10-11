"""Per-request active-tenant and active-project context.

The active tenant and optional active project are stored on the current request
object by the authentication layer (API key or session) or set explicitly.
Helpers here read them so models and managers can scope queries without every
call site re-deriving them.

The context is request-scoped (not thread-local) so it is safe under the
sync request model and under ``asgiref`` sync threads.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

from django.http import HttpRequest

_TENANT_VAR: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "modelanvil_active_tenant", default=None
)
_PROJECT_VAR: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "modelanvil_active_project", default=None
)
_REQUEST_VAR: ContextVar[Optional[HttpRequest]] = ContextVar(
    "modelanvil_active_request", default=None
)


def set_active_tenant(tenant_id: Optional[uuid.UUID]) -> None:
    """Set the active tenant for the current context/request."""
    _TENANT_VAR.set(tenant_id)
    request = _REQUEST_VAR.get()
    if request is not None:
        setattr(request, "modelanvil_tenant", tenant_id)


def get_active_tenant() -> Optional[uuid.UUID]:
    """Return the active tenant UUID, or ``None`` if unscoped."""
    tenant = _TENANT_VAR.get()
    if tenant is not None:
        return tenant
    request = _REQUEST_VAR.get()
    if request is not None:
        return getattr(request, "modelanvil_tenant", None)
    return None


def set_active_project(project_id: Optional[uuid.UUID]) -> None:
    """Set the active project for the current context/request."""
    _PROJECT_VAR.set(project_id)
    request = _REQUEST_VAR.get()
    if request is not None:
        setattr(request, "modelanvil_project_id", project_id)


def get_active_project() -> Optional[uuid.UUID]:
    """Return the active project UUID, or ``None`` if unscoped."""
    project = _PROJECT_VAR.get()
    if project is not None:
        return project
    request = _REQUEST_VAR.get()
    if request is not None:
        return getattr(request, "modelanvil_project_id", None)
    return None


def get_active_request() -> Optional[HttpRequest]:
    return _REQUEST_VAR.get()


def bind_request(request: HttpRequest) -> None:
    """Bind the request into the context so handlers can read it."""
    _REQUEST_VAR.set(request)
    set_active_tenant(getattr(request, "modelanvil_tenant", None))
    set_active_project(getattr(request, "modelanvil_project_id", None))


def reset_context() -> None:
    """Clear tenant + project + request bindings (call at request end)."""
    _TENANT_VAR.set(None)
    _PROJECT_VAR.set(None)
    _REQUEST_VAR.set(None)
