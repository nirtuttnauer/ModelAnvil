"""Health / readiness views for the API."""

from __future__ import annotations

from django.http import JsonResponse


def health(_request) -> JsonResponse:
    return JsonResponse({"status": "ok"}, status=200)
