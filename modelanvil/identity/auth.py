"""Authentication and authorization for the identity app.

:class:`ApiKeyAuthentication` resolves an ``Authorization: Bearer mkv_...``
credential to a tenant + role. :class:`TenantRBAC` enforces that the active
tenant (from the principal) has at least the required role for the action.

The DRF auth/permission wiring in ``settings.py`` references these.
"""

from __future__ import annotations

import uuid
from typing import Optional

from django.urls import Resolver404, resolve
from rest_framework import authentication, exceptions, permissions
from rest_framework.request import Request
from django.utils import timezone

from modelanvil.core.tenancy import set_active_project, set_active_tenant
from modelanvil.identity.models import ApiKey, Role, Tenant, hash_api_key, role_at_least


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate bearer API keys and set the active tenant."""

    keyword = "Bearer"

    def authenticate(self, request: Request) -> Optional[tuple[object, ApiKey]]:
        auth = authentication.get_authorization_header(request)
        cookie = request.COOKIES.get("modelanvil_session") if not auth else None
        if cookie:
            authentication.SessionAuthentication().enforce_csrf(request)
            auth = f"Bearer {cookie}".encode()
            request.modelanvil_cookie_auth = True
        if not auth:
            return None
        try:
            parts = auth.split()
        except Exception:  # noqa: BLE001
            return None
        if len(parts) != 2 or parts[0].lower() != self.keyword.lower().encode():
            return None
        token = parts[1].decode()
        if token.startswith("mkw_"):
            return self._authenticate_worker_token(request, token)
        if not token.startswith("mkv_"):
            return None

        digest = hash_api_key(token)
        key = ApiKey.objects.filter(secret_hash=digest).first()
        if key is None:
            raise exceptions.AuthenticationFailed("Invalid API key.")
        if not key.is_active or key.is_expired():
            raise exceptions.AuthenticationFailed("API key is inactive or expired.")

        # Resolve the active tenant from the key's tenant.
        tenant = key.tenant
        if not tenant.is_active():
            raise exceptions.AuthenticationFailed("Tenant is not active.")

        if cookie or key.created_by_id:
            from modelanvil.identity.models import Membership
            membership = Membership.objects.filter(tenant=tenant, user=key.created_by, user__is_active=True).first()
            if membership is None:
                raise exceptions.AuthenticationFailed("Workspace access is no longer available.")
            if cookie or not role_at_least(membership.role, key.role):
                key.role = membership.role

        # Resolve project scope from key or request header
        project_id = key.project_id
        header_project = request.headers.get("X-Project-ID") or request.headers.get("X-Project")
        if header_project:
            try:
                parsed_project_id = uuid.UUID(str(header_project).strip())
                if project_id and project_id != parsed_project_id:
                    raise exceptions.AuthenticationFailed("Key is restricted to a different project.")
                from modelanvil.identity.models import Project
                if not Project.objects.filter(tenant_id=tenant.tenant_id, id=parsed_project_id).exists():
                    raise exceptions.AuthenticationFailed("Project not found in active tenant.")
                project_id = parsed_project_id
            except (ValueError, TypeError):
                raise exceptions.AuthenticationFailed("Invalid X-Project-ID header.")

        set_active_tenant(tenant.tenant_id)
        if project_id:
            set_active_project(project_id)
        else:
            set_active_project(None)

        request.modelanvil_tenant = tenant.tenant_id  # type: ignore[attr-defined]
        request.modelanvil_project_id = project_id  # type: ignore[attr-defined]
        request.modelanvil_actor_id = key.id  # type: ignore[attr-defined]
        request.modelanvil_actor_kind = "api_key"  # type: ignore[attr-defined]
        request.modelanvil_role = key.role  # type: ignore[attr-defined]

        key.last_used_at = timezone.now()
        key.save(update_fields=["last_used_at"])

        # DRF's IsAuthenticated permission checks request.user.is_authenticated.
        # API keys are the authenticated principal, so mark the instance for
        # the lifetime of this request.
        key.is_authenticated = True
        return (key, key)

    @staticmethod
    def _authenticate_worker_token(request: Request, token: str):
        """Resolve a revocable token to exactly one registered worker."""
        try:
            route_name = resolve(request.path_info).url_name
        except Resolver404 as exc:
            raise exceptions.AuthenticationFailed("Worker credentials cannot access this endpoint.") from exc
        if route_name not in {"worker-claim", "worker-heartbeat", "worker-result", "worker-artifact-download",
                              "worker-artifact-grant-discover"}:
            raise exceptions.AuthenticationFailed("Worker credentials cannot access this endpoint.")

        from modelanvil.jobs.models import WorkerCredential

        credential = WorkerCredential.all_objects.select_related("worker").filter(
            secret_hash=hash_api_key(token),
            revoked_at__isnull=True,
        ).first()
        if credential is None or credential.expires_at <= timezone.now():
            raise exceptions.AuthenticationFailed("Worker credential is invalid, revoked, or expired.")
        tenant = Tenant.objects.filter(tenant_id=credential.tenant_id).first()
        if tenant is None or not tenant.is_active():
            raise exceptions.AuthenticationFailed("Tenant is not active.")
        if credential.worker.tenant_id != credential.tenant_id:
            raise exceptions.AuthenticationFailed("Worker credential scope is invalid.")

        set_active_tenant(tenant.tenant_id)
        set_active_project(None)
        request.modelanvil_tenant = tenant.tenant_id  # type: ignore[attr-defined]
        request.modelanvil_project_id = None  # type: ignore[attr-defined]
        request.modelanvil_actor_id = credential.id  # type: ignore[attr-defined]
        request.modelanvil_actor_kind = "worker_credential"  # type: ignore[attr-defined]
        request.modelanvil_role = Role.WORKER  # type: ignore[attr-defined]
        request.modelanvil_worker_id = credential.worker_id  # type: ignore[attr-defined]

        credential.last_used_at = timezone.now()
        credential.save(update_fields=["last_used_at"])
        credential.worker.is_authenticated = True
        return (credential.worker, credential)

    def authenticate_header(self, request: Request) -> str:
        return self.keyword


class TenantRBAC(permissions.BasePermission):
    """Enforce a minimum role for the active tenant.

    Views declare the required role by setting ``required_role`` (a
    :class:`Role` value). The active tenant/role come from the
    authenticated principal set by :class:`ApiKeyAuthentication`.
    """

    message = "Insufficient role for this action."

    def has_permission(self, request: Request, view: object) -> bool:
        required = getattr(view, "required_role", None)
        if required is None:
            return True
        role = getattr(request, "modelanvil_role", None)
        return role_at_least(role, required)
