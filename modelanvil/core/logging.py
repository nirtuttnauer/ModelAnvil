"""Structured JSON logging formatter.

Emits one JSON object per log record. Each object has a ``message`` field
(``Application event`` or ``Application error``) and, when that context is
already recorded, ``request_id`` plus ``tenant_id`` from the active request
context or ``request_id`` and ``tenant`` from record extras.

Keys such as ``password``, ``token``, ``authorization``, and ``api_key``
are replaced with ``[redacted]`` when they appear in record extras or in a
dict message. The raw log text and traceback stay off the line.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from modelanvil.core.tenancy import get_active_request, get_active_tenant

_REDACTED = "[redacted]"

# Names that must not be overwritten by a dict message or an extra.
_PROTECTED = frozenset(
    {
        "timestamp",
        "level",
        "logger",
        "message",
        "request_id",
        "tenant_id",
        "tenant",
        "job_id",
        "attempt_id",
        "exception_type",
        "http_status",
    }
)

_SECRET_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "authorization",
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "access_token",
        "refresh_token",
        "id_token",
        "private_key",
        "credential",
        "credentials",
        "api_secret",
        "auth_token",
        "session_token",
    }
)

_SECRET_SUFFIXES = (
    "_password",
    "_passwd",
    "_token",
    "_api_key",
    "_secret",
    "_authorization",
)

_LOG_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__)


def _key_name(key: object) -> str:
    return str(key).replace("-", "_").lower()


def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    name = _key_name(key)
    return name in _SECRET_KEYS or name.endswith(_SECRET_SUFFIXES)


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_is_secret_key(key) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return False


def _redact(value: Any) -> Any:
    """Replace secret-key values with a placeholder. Other values stay."""
    if isinstance(value, dict):
        return {key: _REDACTED if _is_secret_key(key) else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _merge_mapping(payload: dict[str, Any], mapping: dict[Any, Any], *, include_plain: bool) -> None:
    redacted = _redact(mapping)
    for key, value in redacted.items():
        if not isinstance(key, str) or key in _PROTECTED or key in payload:
            continue
        if include_plain or _is_secret_key(key) or _contains_secret(mapping[key]):
            payload[key] = value


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    return {key: value for key, value in record.__dict__.items() if key not in _LOG_RECORD_ATTRS}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": "Application error" if record.levelno >= logging.ERROR else "Application event",
        }
        request = get_active_request()
        if request is not None:
            payload["request_id"] = getattr(request, "modelanvil_request_id", None)
        tenant = get_active_tenant()
        if tenant is not None:
            payload["tenant_id"] = str(tenant)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        # Merge any extra structured fields.
        for key in ("request_id", "tenant", "job_id", "attempt_id"):
            value = getattr(record, key, None)
            if value is not None and key not in payload:
                try:
                    payload[key] = str(uuid.UUID(str(value)))
                except (ValueError, TypeError, AttributeError):
                    if isinstance(value, int):
                        payload[key] = value
        status = getattr(record, "status_code", None)
        if type(status) is int:
            payload["http_status"] = status
        if isinstance(record.msg, dict):
            _merge_mapping(payload, record.msg, include_plain=True)
        _merge_mapping(payload, _record_extras(record), include_plain=False)
        return json.dumps(_redact(payload), default=str)
