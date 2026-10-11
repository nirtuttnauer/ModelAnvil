"""Extension manifest builder and validator (TECH-028)."""
from __future__ import annotations

import hashlib
from typing import Any

from contracts.validate import validate_adapter_manifest


def validate_extension_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate extension manifest dictionary against canonical JSON schema."""
    return validate_adapter_manifest(manifest)


class AdapterManifestBuilder:
    """Fluent builder for constructing schema-conformant extension adapter manifests."""

    def __init__(self, adapter_id: str, version: str) -> None:
        self.adapter_id = adapter_id
        self.version = version
        self.platform_api = "1.0"
        self.image = f"registry.modelanvil.internal/{adapter_id}:{version}@sha256:{hashlib.sha256(adapter_id.encode('utf-8')).hexdigest()}"
        self.license = "apache-2.0"
        self.capabilities: list[dict[str, Any]] = []
        self.resources = {
            "cpu_cores": 2.0,
            "memory_bytes": 4 * 1024 * 1024 * 1024,
            "gpu_count": 0,
            "disk_bytes": 10 * 1024 * 1024 * 1024,
            "distributed": False,
        }
        self.permissions = {
            "network_hosts": [],
            "artifact_access": ["read_job_inputs", "write_attempt_staging"],
            "secret_kinds": [],
        }
        self.dependencies: list[dict[str, Any]] = []

    def with_license(self, license_name: str) -> AdapterManifestBuilder:
        self.license = license_name
        return self

    def with_image(self, image_ref: str) -> AdapterManifestBuilder:
        self.image = image_ref
        return self

    def with_resources(
        self,
        cpu_cores: float = 2.0,
        memory_bytes: int = 4 * 1024 * 1024 * 1024,
        gpu_count: int = 0,
        disk_bytes: int = 10 * 1024 * 1024 * 1024,
        distributed: bool = False,
    ) -> AdapterManifestBuilder:
        self.resources = {
            "cpu_cores": cpu_cores,
            "memory_bytes": memory_bytes,
            "gpu_count": gpu_count,
            "disk_bytes": disk_bytes,
            "distributed": distributed,
        }
        return self

    def with_permissions(
        self,
        network_hosts: list[str] | None = None,
        artifact_access: list[str] | None = None,
        secret_kinds: list[str] | None = None,
    ) -> AdapterManifestBuilder:
        self.permissions = {
            "network_hosts": network_hosts or [],
            "artifact_access": artifact_access or ["read_job_inputs", "write_attempt_staging"],
            "secret_kinds": secret_kinds or [],
        }
        return self

    def add_capability(
        self,
        kind: str,
        input_schema_refs: list[str],
        output_schema_refs: list[str],
        formats: list[str] | None = None,
        architectures: list[str] | None = None,
        recovery: str = "verified_checkpoint",
    ) -> AdapterManifestBuilder:
        cap: dict[str, Any] = {
            "kind": kind,
            "input_schema_refs": input_schema_refs,
            "output_schema_refs": output_schema_refs,
            "recovery": recovery,
        }
        if formats:
            cap["formats"] = formats
        if architectures:
            cap["architectures"] = architectures
        self.capabilities.append(cap)
        return self

    def add_dependency(self, name: str, version: str, digest: str) -> AdapterManifestBuilder:
        self.dependencies.append({"name": name, "version": version, "digest": digest})
        return self

    def build(self) -> dict[str, Any]:
        """Construct manifest dictionary and validate against canonical schema."""
        if not self.capabilities:
            # Default read capability if none specified
            self.add_capability(
                kind="read",
                input_schema_refs=["urn:modelanvil:schema:sample-envelope:1.0"],
                output_schema_refs=["urn:modelanvil:schema:sample-envelope:1.0"],
            )

        manifest = {
            "schema_version": "1.0",
            "adapter_id": self.adapter_id,
            "version": self.version,
            "platform_api": self.platform_api,
            "image": self.image,
            "license": self.license,
            "capabilities": self.capabilities,
            "resources": self.resources,
            "permissions": self.permissions,
            "dependencies": self.dependencies,
        }
        return validate_extension_manifest(manifest)
