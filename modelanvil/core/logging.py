"""Structured JSON logging formatter.

Emits one JSON object per log record with the request/tenant context, so
log aggregation is trivial and every line is attributable to a tenant and
request.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from modelanvil.core.tenancy import get_active_request, get_active_tenant


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
        status = getattr(record, 'status_code', None)
        if type(status) is int:
            payload['http_status'] = status
        return json.dumps(payload, default=str)
