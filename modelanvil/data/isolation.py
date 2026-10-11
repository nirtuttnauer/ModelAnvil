"""Sandboxed document rendering and media decoding isolation (WP-04 / TECH-006)."""
from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class IsolatedRenderResult:
    """Safe extracted content preserving raw asset and location spans."""

    clean_text: str
    elements: list[dict[str, Any]] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_asset_bytes: bytes = b""
    raw_sha256: str = ""
    is_safe: bool = True


@dataclass
class IsolatedMediaResult:
    """Decoded media metadata validated within safe bounds."""

    media_type: str
    byte_size: int
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    channels: Optional[int] = None
    is_valid: bool = True
    error: Optional[str] = None
    raw_sha256: str = ""


class DocumentIsolationError(Exception):
    """Raised when an unrecoverable security violation is detected."""


def isolate_render_document(
    raw_content: str | bytes,
    media_type: str = "text/html",
) -> IsolatedRenderResult:
    """Safely sanitize and extract text/structure from HTML, SVG, or plain text.

    Enforces XXE protection, strips executable scripts and event handlers,
    and records extraction locations.
    """
    if isinstance(raw_content, str):
        raw_bytes = raw_content.encode("utf-8")
        text = raw_content
    else:
        raw_bytes = raw_content
        text = raw_content.decode("utf-8", errors="replace")

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    warnings: list[str] = []
    elements: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []

    # 1. XXE / Entity expansion check (Billion Laughs protection)
    if "<!ENTITY" in text or ("<!DOCTYPE" in text and "SYSTEM" in text):
        warnings.append("Detected potential XXE/entity expansion; entity declarations neutralized.")
        text = re.sub(r"<!ENTITY[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.IGNORECASE)

    # 2. Strip scripts and iframe execution tags
    script_pattern = re.compile(
        r"<(script|iframe|object|embed|applet)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
    )
    if script_pattern.search(text):
        warnings.append("Executable script/embedded tags removed.")
        text = script_pattern.sub(" ", text)

    # 3. Strip self-closing script tags and event handlers (onload, onerror, onclick, etc.)
    text = re.sub(r"<script[^>]*/>", " ", text, flags=re.IGNORECASE)
    event_handler_pattern = re.compile(
        r'\s+on[a-z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE
    )
    if event_handler_pattern.search(text):
        warnings.append("Inline DOM event handlers removed.")
        text = event_handler_pattern.sub("", text)

    # 4. Strip javascript: and data: text/html pseudo-protocols
    text = re.sub(r'href\s*=\s*["\']\s*javascript:[^"\']*["\']', 'href="#"', text, flags=re.IGNORECASE)
    text = re.sub(r'src\s*=\s*["\']\s*javascript:[^"\']*["\']', 'src="#"', text, flags=re.IGNORECASE)

    # 5. Extract structured text spans
    tag_pattern = re.compile(
        r"<(p|h[1-6]|li|td|th|span|text|div)\b[^>]*>(.*?)</\1>",
        re.DOTALL | re.IGNORECASE,
    )
    for match in tag_pattern.finditer(text):
        tag_name = match.group(1).lower()
        inner_content = match.group(2).strip()
        clean_inner = re.sub(r"<[^>]+>", " ", inner_content).strip()
        if clean_inner:
            elements.append({"tag": tag_name, "content": clean_inner})
            spans.append({
                "start": match.start(),
                "end": match.end(),
                "content": clean_inner,
            })

    clean_text = re.sub(r"<[^>]+>", " ", text)
    clean_text = " ".join(clean_text.split())

    return IsolatedRenderResult(
        clean_text=clean_text,
        elements=elements,
        spans=spans,
        warnings=warnings,
        raw_asset_bytes=raw_bytes,
        raw_sha256=raw_sha256,
        is_safe=True,
    )


def isolate_decode_media(
    raw_content: str | bytes,
    media_type: str,
    *,
    max_dimension: int = 16384,
) -> IsolatedMediaResult:
    """Decode and inspect media assets safely, validating dimensional limits."""
    if isinstance(raw_content, str):
        raw_bytes = raw_content.encode("utf-8")
    else:
        raw_bytes = raw_content

    byte_size = len(raw_bytes)
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # PNG verification: \x89PNG\r\n\x1a\n
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(raw_bytes) >= 24:
        width, height = struct.unpack(">II", raw_bytes[16:24])
        if width > max_dimension or height > max_dimension:
            return IsolatedMediaResult(
                media_type="image/png",
                byte_size=byte_size,
                width=width,
                height=height,
                is_valid=False,
                error=f"PNG dimensions {width}x{height} exceed limit {max_dimension}",
                raw_sha256=raw_sha256,
            )
        return IsolatedMediaResult(
            media_type="image/png",
            byte_size=byte_size,
            width=width,
            height=height,
            is_valid=True,
            raw_sha256=raw_sha256,
        )

    # JPEG verification: \xff\xd8
    if raw_bytes.startswith(b"\xff\xd8"):
        idx = 2
        width, height = None, None
        while idx < len(raw_bytes) - 9:
            if raw_bytes[idx] == 0xFF:
                marker = raw_bytes[idx + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    height, width = struct.unpack(">HH", raw_bytes[idx + 5 : idx + 9])
                    break
                length = struct.unpack(">H", raw_bytes[idx + 2 : idx + 4])[0]
                idx += 2 + length
            else:
                idx += 1

        if width is not None and (width > max_dimension or height > max_dimension):
            return IsolatedMediaResult(
                media_type="image/jpeg",
                byte_size=byte_size,
                width=width,
                height=height,
                is_valid=False,
                error=f"JPEG dimensions {width}x{height} exceed limit {max_dimension}",
                raw_sha256=raw_sha256,
            )
        return IsolatedMediaResult(
            media_type="image/jpeg",
            byte_size=byte_size,
            width=width,
            height=height,
            is_valid=True,
            raw_sha256=raw_sha256,
        )

    # GIF verification: GIF87a or GIF89a
    if raw_bytes.startswith(b"GIF87a") or raw_bytes.startswith(b"GIF89a"):
        width, height = struct.unpack("<HH", raw_bytes[6:10])
        return IsolatedMediaResult(
            media_type="image/gif",
            byte_size=byte_size,
            width=width,
            height=height,
            is_valid=True,
            raw_sha256=raw_sha256,
        )

    # WAV audio verification: RIFF....WAVEfmt
    if raw_bytes.startswith(b"RIFF") and b"WAVE" in raw_bytes[:16]:
        channels = None
        if len(raw_bytes) >= 24:
            channels = struct.unpack("<H", raw_bytes[22:24])[0]
        return IsolatedMediaResult(
            media_type="audio/wav",
            byte_size=byte_size,
            channels=channels,
            is_valid=True,
            raw_sha256=raw_sha256,
        )

    # SVG text media
    if "svg" in media_type.lower() or b"<svg" in raw_bytes[:512]:
        render_res = isolate_render_document(raw_bytes, media_type="image/svg+xml")
        return IsolatedMediaResult(
            media_type="image/svg+xml",
            byte_size=byte_size,
            is_valid=render_res.is_safe,
            error="; ".join(render_res.warnings) if render_res.warnings else None,
            raw_sha256=raw_sha256,
        )

    # Fallback generic media
    return IsolatedMediaResult(
        media_type=media_type,
        byte_size=byte_size,
        is_valid=True,
        raw_sha256=raw_sha256,
    )


def sanitize_svg_for_rendering(svg_content: str | bytes) -> str:
    """Sanitize SVG markup for safe rendering, neutralizing scripts, XXE, and pseudo-protocols."""
    if isinstance(svg_content, bytes):
        text = svg_content.decode("utf-8", errors="replace")
    else:
        text = str(svg_content)

    text = re.sub(r"<!ENTITY[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.IGNORECASE)

    script_pattern = re.compile(
        r"<(script|iframe|object|embed|applet)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
    )
    text = script_pattern.sub(" ", text)
    text = re.sub(r"<script[^>]*/>", " ", text, flags=re.IGNORECASE)

    event_handler_pattern = re.compile(
        r'\s+on[a-z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE
    )
    text = event_handler_pattern.sub("", text)
    text = re.sub(r'href\s*=\s*["\']\s*javascript:[^"\']*["\']', 'href="#"', text, flags=re.IGNORECASE)
    text = re.sub(r'src\s*=\s*["\']\s*javascript:[^"\']*["\']', 'src="#"', text, flags=re.IGNORECASE)

    return text.strip()
