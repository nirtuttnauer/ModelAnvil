"""Structured JSON logging formatter.

Emits one JSON object per log record with the request/tenant context, so
log aggregation is trivial and every line is attributable to a tenant and
request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from modelanvil.core.tenancy import get_active_request, get_active_tenant


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request = get_active_request()
        if request is not None:
            payload["request_id"] = getattr(request, "modelanvil_request_id", None)
        tenant = get_active_tenant()
        if tenant is not None:
            payload["tenant_id"] = str(tenant)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Merge any extra structured fields.
        for key in ("request_id", "tenant", "job_id", "attempt_id"):
            value = getattr(record, key, None)
            if value is not None and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)
