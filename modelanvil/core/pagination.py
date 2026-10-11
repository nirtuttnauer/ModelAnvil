"""Cursor-based pagination for the public API.

The plan requires stable, resumable listing. We use an opaque cursor (base64
of the last ordering key) rather than offset pagination so large lists stay
consistent as new rows arrive.
"""

from __future__ import annotations

from typing import Any

from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class CursorPagination(CursorPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
    ordering = "-created_at"

    def get_paginated_response(self, data: Any) -> Response:
        return Response(
            {
                "results": data,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
            }
        )
