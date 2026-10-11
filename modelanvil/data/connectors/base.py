"""Base connector contracts and result structures (WP-04 / TECH-005, TECH-006)."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ConnectorConfig:
    """Bounded configuration for data acquisition connectors."""

    target_uri: str
    auth_token: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    rate_limit_per_second: float = 10.0
    allowed_domains: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    max_requests: int = 1000
    max_bytes: int = 50 * 1024 * 1024  # 50MB default boundary
    max_concurrency: int = 4
    pin_revision: Optional[str] = None


@dataclass
class ConnectorItem:
    """One acquired record with provenance and hash."""

    item_id: str
    envelope: dict[str, Any]
    content_sha256: str
    byte_size: int
    raw_content: Optional[str | bytes] = None
    extraction_locations: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorResult:
    """Result of an acquisition run with immutable manifest digest."""

    items: list[ConnectorItem] = field(default_factory=list)
    item_count: int = 0
    byte_count: int = 0
    failure_count: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    manifest_digest: str = ""
    checkpoint: Optional[dict[str, Any]] = None

    def compute_manifest_digest(self) -> str:
        """Compute stable SHA-256 over ordered item content digests."""
        hasher = hashlib.sha256()
        for item in sorted(self.items, key=lambda x: x.item_id):
            hasher.update(item.content_sha256.encode("ascii"))
        self.manifest_digest = hasher.hexdigest()
        return self.manifest_digest


class BaseConnector(ABC):
    """Abstract data acquisition connector."""

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config

    @abstractmethod
    def acquire(self, *, limit: Optional[int] = None) -> ConnectorResult:
        """Acquire records within configured boundaries."""
        ...

    @abstractmethod
    def checkpoint(self) -> dict[str, Any]:
        """Serialize current acquisition state for durable resumption."""
        ...

    @abstractmethod
    def resume(self, checkpoint_data: dict[str, Any]) -> None:
        """Restore state from a durable checkpoint."""
        ...
