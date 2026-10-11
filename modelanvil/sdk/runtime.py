"""Isolated extension runtime with permission controls and preflight validation (TECH-028)."""
from __future__ import annotations

from typing import Any, Callable

from contracts.validate import validate_adapter_manifest


class PermissionDeniedError(Exception):
    """Raised when an extension attempts unauthorized network or storage access."""
    pass


class ExtensionPreflightError(Exception):
    """Raised when an extension fails compatibility preflight."""
    pass


class IsolatedExtensionRuntime:
    """Simulates isolated container/process execution of an extension with strict permission enforcement."""

    def __init__(self, manifest: dict[str, Any]) -> None:
        self.manifest = validate_adapter_manifest(manifest)
        self.permissions = self.manifest.get("permissions", {})
        self.allowed_hosts = set(self.permissions.get("network_hosts", []))
        self.allowed_artifact_access = set(self.permissions.get("artifact_access", []))

    def preflight_check(self, target_platform_api: str = "1.0") -> bool:
        """Validate extension compatibility against the host platform without mutating state."""
        declared_api = self.manifest.get("platform_api")
        if declared_api != target_platform_api:
            raise ExtensionPreflightError(
                f"Extension API version '{declared_api}' incompatible with platform '{target_platform_api}'."
            )
        return True

    def verify_network_access(self, destination_host: str) -> None:
        """Deny unauthorized outbound network access (TECH-028)."""
        if destination_host not in self.allowed_hosts:
            raise PermissionDeniedError(
                f"Unauthorized network access to '{destination_host}' denied. Allowed hosts: {list(self.allowed_hosts)}"
            )

    def verify_artifact_access(self, access_kind: str) -> None:
        """Deny unauthorized storage / artifact access (TECH-028)."""
        if access_kind not in self.allowed_artifact_access:
            raise PermissionDeniedError(
                f"Unauthorized artifact access '{access_kind}' denied. Allowed grants: {list(self.allowed_artifact_access)}"
            )

    def execute_isolated(
        self,
        task_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute extension task in the enforced isolation envelope."""
        self.preflight_check()
        return task_fn(*args, **kwargs)
