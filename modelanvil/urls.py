"""ModelAnvil root URL configuration.

The public API lives under ``/api/v1/`` and is mounted from the ``api``
namespace assembled in ``modelanvil.urls``. The web shell is served at the
site root (built assets) with a fallback to the SPA.
"""

from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import TemplateView


def health(_request) -> JsonResponse:
    """Liveness probe: cheap, no DB."""
    return JsonResponse(
        {"status": "ok", "service": "modelanvil", "api": "v1"},
        status=200,
    )


def readiness(_request) -> JsonResponse:
    """Readiness probe: confirms the database is reachable."""
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:  # Backend details may contain credentials or private hosts.
        return JsonResponse(
            {"status": "degraded", "reason": "database_unavailable"}, status=503
        )
    return JsonResponse({"status": "ready"}, status=200)


def index(_request):
    """Serve the built web shell (SPA entry)."""
    return TemplateView.as_view(template_name="index.html")(_request)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("modelanvil.api.urls")),
    path("api/v1/health/", health, name="api-health"),
    path("api/v1/ready/", readiness, name="api-ready"),
    path("", index, name="index"),
]
