"""Web acquisition crawler contract with Scrapling adapter and durable checkpoints (WP-04 / TECH-006)."""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

from contracts.validate import validate_envelope
from modelanvil.data.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorItem,
    ConnectorResult,
)


@dataclass
class CrawlCheckpoint:
    """Durable checkpoint state for web crawl resumption."""

    visited_urls: list[str] = field(default_factory=list)
    pending_queue: list[str] = field(default_factory=list)
    extracted_count: int = 0
    bytes_downloaded: int = 0
    requests_made: int = 0
    status: str = "running"  # running, paused, cancelled, completed
    last_url: Optional[str] = None


class ScraplingCrawlerConnector(BaseConnector):
    """Crawler adhering to TECH-006 boundaries with durable checkpointing."""

    _FORBIDDEN_HOSTS = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "169.254.169.254",
        "metadata.google.internal",
    }

    def __init__(
        self,
        config: ConnectorConfig,
        *,
        transport: Optional[Callable[[str, dict[str, str]], tuple[int, bytes, dict[str, str]]]] = None,
    ) -> None:
        super().__init__(config)
        self.transport = transport or self._default_transport
        self.visited_urls: set[str] = set()
        self.queue: list[str] = [config.target_uri]
        self.requests_made: int = 0
        self.bytes_downloaded: int = 0
        self.status: str = "running"
        self._cancelled: bool = False

    def is_url_allowed(self, url: str) -> tuple[bool, str]:
        """Verify URL matches domain, path, and security limits."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Disallowed scheme: {parsed.scheme}"

        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname in self._FORBIDDEN_HOSTS:
            return False, f"Denied destination / SSRF host: {hostname}"

        if self.config.allowed_domains:
            matched = any(
                hostname == d.lower() or hostname.endswith("." + d.lower())
                for d in self.config.allowed_domains
            )
            if not matched:
                return False, f"Hostname {hostname} not in allowed domains"

        if self.config.allowed_paths:
            path = parsed.path or "/"
            matched_path = any(path.startswith(p) for p in self.config.allowed_paths)
            if not matched_path:
                return False, f"Path {path} not in allowed paths"

        return True, ""

    def _default_transport(self, url: str, headers: dict[str, str]) -> tuple[int, bytes, dict[str, str]]:
        import urllib.request

        allowed, reason = self.is_url_allowed(url)
        if not allowed:
            raise PermissionError(reason)

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
            return resp.status, resp.read(), dict(resp.headers)

    def cancel(self) -> None:
        """Cancel ongoing crawl."""
        self._cancelled = True
        self.status = "cancelled"

    def pause(self) -> dict[str, Any]:
        """Pause crawl and return checkpoint."""
        self.status = "paused"
        return self.checkpoint()

    def acquire(self, *, limit: Optional[int] = None) -> ConnectorResult:
        """Run crawler within configured request, byte, domain, and path limits."""
        result = ConnectorResult()
        max_req = limit or self.config.max_requests

        while self.queue and self.requests_made < max_req and not self._cancelled:
            if self.bytes_downloaded >= self.config.max_bytes:
                break

            current_url = self.queue.pop(0)
            if current_url in self.visited_urls:
                continue

            allowed, reason = self.is_url_allowed(current_url)
            if not allowed:
                result.failure_count += 1
                result.failures.append({"url": current_url, "error": reason})
                self.visited_urls.add(current_url)
                continue

            self.visited_urls.add(current_url)
            self.requests_made += 1

            headers = dict(self.config.headers)
            if self.config.auth_token:
                headers["Authorization"] = f"Bearer {self.config.auth_token}"

            try:
                status, body, _resp_headers = self.transport(current_url, headers)
                self.bytes_downloaded += len(body)

                if status != 200:
                    result.failure_count += 1
                    result.failures.append({"url": current_url, "status": status, "error": f"HTTP {status}"})
                    continue

                # Extract HTML text and links safely
                text_content, discovered_links = self._extract_html_content(body, current_url)

                # Queue newly discovered links within domain boundary
                for link in discovered_links:
                    if link not in self.visited_urls and link not in self.queue:
                        link_allowed, _ = self.is_url_allowed(link)
                        if link_allowed:
                            self.queue.append(link)

                content_sha = hashlib.sha256(body).hexdigest()
                envelope = {
                    "schema_version": "1.0",
                    "sample_id": str(uuid.uuid4()),
                    "source_group_id": f"crawl-{urlparse(current_url).hostname}",
                    "blocks": [
                        {
                            "block_id": f"blk-{self.requests_made}",
                            "type": "text",
                            "text": text_content,
                        }
                    ],
                    "provenance": {
                        "source_snapshot_ref": f"crawl-snap-{urlparse(current_url).hostname}",
                        "source_record_key": current_url,
                        "content_sha256": content_sha,
                    },
                }

                valid_envelope = validate_envelope(envelope)
                item = ConnectorItem(
                    item_id=current_url,
                    envelope=valid_envelope,
                    content_sha256=content_sha,
                    byte_size=len(body),
                    raw_content=body.decode("utf-8", errors="replace"),
                    extraction_locations={"url": current_url, "status": status},
                )
                result.items.append(item)
                result.byte_count += item.byte_size

            except Exception as exc:  # noqa: BLE001
                result.failure_count += 1
                result.failures.append({"url": current_url, "error": str(exc)})

        if not self.queue:
            self.status = "completed"

        result.item_count = len(result.items)
        result.compute_manifest_digest()
        result.checkpoint = self.checkpoint()
        return result

    def _extract_html_content(self, body: bytes, base_url: str) -> tuple[str, list[str]]:
        """Safely extract plain text and discover absolute hrefs without script execution."""
        html_text = body.decode("utf-8", errors="replace")

        # Strip scripts and styles
        cleaned = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)

        # Discover links
        hrefs = re.findall(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\']', cleaned, flags=re.IGNORECASE)
        resolved_links: list[str] = []
        for href in hrefs:
            href = href.strip()
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            abs_url = urljoin(base_url, href)
            # Remove fragment
            abs_url = abs_url.split("#")[0]
            resolved_links.append(abs_url)

        # Strip remaining tags to obtain clean text
        text_only = re.sub(r"<[^>]+>", " ", cleaned)
        clean_text = " ".join(text_only.split())
        return clean_text, resolved_links

    def checkpoint(self) -> dict[str, Any]:
        cp = CrawlCheckpoint(
            visited_urls=list(self.visited_urls),
            pending_queue=list(self.queue),
            extracted_count=len(self.visited_urls),
            bytes_downloaded=self.bytes_downloaded,
            requests_made=self.requests_made,
            status=self.status,
            last_url=self.queue[0] if self.queue else None,
        )
        return asdict(cp)

    def resume(self, checkpoint_data: dict[str, Any]) -> None:
        self.visited_urls = set(checkpoint_data.get("visited_urls", []))
        self.queue = list(checkpoint_data.get("pending_queue", []))
        self.bytes_downloaded = int(checkpoint_data.get("bytes_downloaded", 0))
        self.requests_made = int(checkpoint_data.get("requests_made", 0))
        self.status = checkpoint_data.get("status", "running")
        self._cancelled = (self.status == "cancelled")
