"""Health / readiness views for the API."""

from __future__ import annotations

from django.http import JsonResponse


def health(_request) -> JsonResponse:
    return JsonResponse({"status": "ok"}, status=200)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def build(_request):
    from modelanvil.build_info import build_info
    return Response(build_info())
