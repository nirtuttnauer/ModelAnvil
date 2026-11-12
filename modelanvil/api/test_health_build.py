"""Health and build payloads stay free of filesystem paths and environment values.

``production_qualified`` stays false. That flag name is the one allowed
occurrence of the word in the rendered payload. A true flag, a readiness
claim, or an absolute path interpolated from ``Path(__file__)`` fails these
checks.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import resolve
from rest_framework.test import APIClient

import modelanvil.build_info as build_info_module
from modelanvil.api.views.health import health
from modelanvil.build_info import PROTOCOL, build_info
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key

# Marker planted in the environment for the duration of each test.
# It is not a credential.
_PROBE_NAME = "ANVIL063_PROBE_SECRET"
_PROBE_VALUE = "anvil063-env-probe-7f3c9a2e"

_FORBIDDEN_CLAIMS = ("production-ready",)
_PATH_MARKERS = ("/workspace", "/home")
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"
)
_SECRET_KEY = re.compile(r"(SECRET|TOKEN|PASSWORD|CREDENTIAL|PRIVATE)", re.IGNORECASE)


def _rendered_forms(payload: object) -> list[str]:
    return [json.dumps(payload, sort_keys=True), str(payload)]


def _workspace_paths() -> list[str]:
    paths = []
    for filename in (build_info_module.__file__, health.__code__.co_filename):
        resolved = str(Path(filename).resolve())
        paths.append(resolved)
        paths.append(str(Path(resolved).parent))
    return paths


@override_settings(ALLOWED_HOSTS=["testserver"])
class HealthBuildPayloadTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self._previous_probe = os.environ.get(_PROBE_NAME)
        os.environ[_PROBE_NAME] = _PROBE_VALUE
        build_info.cache_clear()
        self.addCleanup(self._restore_probe)
        self.addCleanup(build_info.cache_clear)
        self.addCleanup(set_active_tenant, None)

    def _restore_probe(self) -> None:
        if self._previous_probe is None:
            os.environ.pop(_PROBE_NAME, None)
        else:
            os.environ[_PROBE_NAME] = self._previous_probe

    def _assert_no_paths_or_env(self, text: str) -> None:
        if _PROBE_VALUE in text:
            self.fail(f"payload contains the value of {_PROBE_NAME}")
        secret_key = settings.SECRET_KEY
        if secret_key and secret_key in text:
            self.fail("payload contains the Django secret key")
        for name, value in os.environ.items():
            if not value or len(value) < 8:
                continue
            secret_like = _SECRET_KEY.search(name) is not None
            path_like = value.startswith("/")
            if (secret_like or path_like) and value in text:
                self.fail(f"payload contains the value of environment variable {name}")
        for marker in _PATH_MARKERS:
            self.assertNotIn(marker, text)
        for path in _workspace_paths():
            self.assertNotIn(path, text)
        match = _ABSOLUTE_PATH.search(text)
        self.assertIsNone(
            match,
            f"payload contains an absolute path: {match.group(0) if match else ''}",
        )

    def _assert_build_payload(self, payload: dict) -> None:
        self.assertEqual(
            set(payload),
            {"revision", "source_digest", "protocol", "dataset_formats", "production_qualified"},
        )
        self.assertIsInstance(payload["revision"], str)
        self.assertTrue(payload["revision"])
        self.assertIsInstance(payload["source_digest"], str)
        self.assertEqual(len(payload["source_digest"]), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in payload["source_digest"]))
        self.assertEqual(payload["protocol"], PROTOCOL)
        self.assertIsInstance(payload["dataset_formats"], list)
        self.assertIn("jsonl", payload["dataset_formats"])
        self.assertIs(payload["production_qualified"], False)
        for text in _rendered_forms(payload):
            lowered = text.lower()
            self.assertEqual(lowered.count("qualified"), 1)
            self.assertIn("production_qualified", text)
            for claim in _FORBIDDEN_CLAIMS:
                self.assertNotIn(claim, lowered)
            self._assert_no_paths_or_env(text)

    def test_health_returns_ok_without_paths_or_environment_values(self) -> None:
        resolved = resolve("/api/v1/health/")
        self.assertIs(resolved.func, health)

        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        body = response.content.decode()
        self.assertNotIn("qualified", body.lower())
        for claim in _FORBIDDEN_CLAIMS:
            self.assertNotIn(claim, body.lower())
        self._assert_no_paths_or_env(body)

    def test_build_info_includes_revision_digest_and_protocol(self) -> None:
        build_info.cache_clear()
        self._assert_build_payload(build_info())

    def test_authenticated_build_view_matches_build_info(self) -> None:
        tenant = Tenant.objects.create(slug="health-build", name="Health build")
        secret, hashed = generate_api_key()
        ApiKey.objects.create(
            tenant=tenant,
            name="health-build",
            role=Role.ENGINEER,
            secret_hash=hashed,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")
        build_info.cache_clear()
        response = self.client.get("/api/v1/build/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload, build_info())
        self._assert_build_payload(payload)
        body = response.content.decode()
        if secret in body:
            self.fail("build response contains the API key")
        self._assert_no_paths_or_env(body)
        lowered = body.lower()
        self.assertEqual(lowered.count("qualified"), 1)
        for claim in _FORBIDDEN_CLAIMS:
            self.assertNotIn(claim, lowered)

    def test_unauthenticated_build_view_does_not_return_paths(self) -> None:
        response = self.client.get("/api/v1/build/")
        self.assertIn(response.status_code, (401, 403))
        body = response.content.decode()
        self.assertNotIn("source_digest", body)
        self._assert_no_paths_or_env(body)
