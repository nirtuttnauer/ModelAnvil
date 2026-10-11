"""Repository / API connector for structured datasets (WP-04)."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from contracts.validate import validate_envelope
from modelanvil.data.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorItem,
    ConnectorResult,
)


class RepositoryConnector(BaseConnector):
    """Acquires records from a repository or API endpoint with pinned revisions."""

    def __init__(
        self,
        config: ConnectorConfig,
        *,
        transport: Optional[Callable[[str, dict[str, str]], tuple[int, bytes, dict[str, str]]]] = None,
    ) -> None:
        super().__init__(config)
        self.transport = transport or self._default_transport
        self.cursor: Optional[str] = None
        self.page_number: int = 1
        self.processed_ids: set[str] = set()

    def _validate_destination(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Disallowed URL scheme {parsed.scheme!r}; only HTTP(S) permitted.")
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"):
            raise ValueError(f"Destination {host!r} is forbidden (SSRF protection).")
        if self.config.allowed_domains and not any(
            host == d.lower() or host.endswith("." + d.lower()) for d in self.config.allowed_domains
        ):
            raise ValueError(f"Host {host!r} is not in the allowed domains list.")

    def _default_transport(self, url: str, headers: dict[str, str]) -> tuple[int, bytes, dict[str, str]]:
        import urllib.request

        self._validate_destination(url)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
            return resp.status, resp.read(), dict(resp.headers)

    def acquire(self, *, limit: Optional[int] = None) -> ConnectorResult:
        """Fetch records from the repository/API and map to canonical envelopes."""
        self._validate_destination(self.config.target_uri)
        result = ConnectorResult()
        headers = dict(self.config.headers)
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        uri = self.config.target_uri
        if self.config.pin_revision:
            sep = "&" if "?" in uri else "?"
            uri = f"{uri}{sep}ref={self.config.pin_revision}"

        try:
            status, body, _resp_headers = self.transport(uri, headers)
            if status != 200:
                result.failure_count += 1
                result.failures.append({"url": uri, "status": status, "error": f"HTTP {status}"})
                return result

            # Parse records: handle JSON array, JSON Lines, or object with 'records' / 'data'
            records: list[dict[str, Any]] = []
            text_data = body.decode("utf-8")
            if text_data.strip().startswith("["):
                records = json.loads(text_data)
            elif "\n" in text_data and text_data.strip().startswith("{"):
                for line in text_data.strip().splitlines():
                    if line.strip():
                        records.append(json.loads(line))
            else:
                parsed_json = json.loads(text_data)
                if isinstance(parsed_json, dict):
                    records = parsed_json.get("records") or parsed_json.get("data") or [parsed_json]
                elif isinstance(parsed_json, list):
                    records = parsed_json

            max_items = limit or self.config.max_requests
            for idx, raw_record in enumerate(records[:max_items]):
                item_id = str(raw_record.get("id") or raw_record.get("sample_id") or uuid.uuid4())
                if item_id in self.processed_ids:
                    continue

                serialized = json.dumps(raw_record, sort_keys=True).encode("utf-8")
                item_sha256 = hashlib.sha256(serialized).hexdigest()

                # Build canonical sample envelope if not already conforming
                if "schema_version" in raw_record and "blocks" in raw_record:
                    envelope = raw_record
                else:
                    text_content = (
                        raw_record.get("text")
                        or raw_record.get("content")
                        or json.dumps(raw_record)
                    )
                    envelope = {
                        "schema_version": "1.0",
                        "sample_id": str(uuid.uuid4()),
                        "source_group_id": f"repo-{self.config.pin_revision or 'main'}",
                        "blocks": [
                            {
                                "block_id": f"blk-{idx}",
                                "type": "text",
                                "text": str(text_content),
                            }
                        ],
                        "provenance": {
                            "source_snapshot_ref": f"repo-snap-{self.config.pin_revision or 'head'}",
                            "source_record_key": item_id,
                            "content_sha256": item_sha256,
                        },
                    }

                try:
                    valid_envelope = validate_envelope(envelope)
                    item = ConnectorItem(
                        item_id=item_id,
                        envelope=valid_envelope,
                        content_sha256=item_sha256,
                        byte_size=len(serialized),
                        raw_content=serialized.decode("utf-8", errors="replace"),
                    )
                    result.items.append(item)
                    result.byte_count += item.byte_size
                    self.processed_ids.add(item_id)
                except Exception as exc:  # noqa: BLE001
                    result.failure_count += 1
                    result.failures.append({"item_id": item_id, "error": str(exc)})

            result.item_count = len(result.items)
            result.compute_manifest_digest()
            result.checkpoint = self.checkpoint()
            return result

        except Exception as exc:  # noqa: BLE001
            result.failure_count += 1
            result.failures.append({"url": uri, "error": str(exc)})
            return result

    def checkpoint(self) -> dict[str, Any]:
        return {
            "connector_type": "repository",
            "cursor": self.cursor,
            "page_number": self.page_number,
            "processed_count": len(self.processed_ids),
            "processed_ids": list(self.processed_ids),
            "pin_revision": self.config.pin_revision,
        }

    def resume(self, checkpoint_data: dict[str, Any]) -> None:
        self.cursor = checkpoint_data.get("cursor")
        self.page_number = checkpoint_data.get("page_number", 1)
        self.processed_ids = set(checkpoint_data.get("processed_ids", []))
        if checkpoint_data.get("pin_revision"):
            self.config.pin_revision = checkpoint_data["pin_revision"]
