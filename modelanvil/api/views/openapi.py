"""OpenAPI specification view.

Publishes the canonical OpenAPI 3.1 contract loaded from contracts.schemas.
"""
from __future__ import annotations

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from contracts.schemas import load_schema


@api_view(["GET"])
@permission_classes([AllowAny])
def openapi_spec(_request) -> JsonResponse:
    """Serve the published OpenAPI 3.1 specification."""
    schema = load_schema("openapi")
    return JsonResponse(schema, json_dumps_params={"indent": 2})
