"""Exact-match, fail-closed checks for the isolated extension host allowlist.

These tests call ``verify_network_access`` and ``verify_artifact_access``
directly. A matcher that accepts a scheme, a port, a different case, or a
suffix or prefix of an allowlist entry fails them.
"""

from unittest import TestCase

from modelanvil.sdk.manifest import AdapterManifestBuilder
from modelanvil.sdk.runtime import IsolatedExtensionRuntime, PermissionDeniedError

_GRANTED_HOST = "api.approved.com"
_GRANTED_ARTIFACT = "read_job_inputs"


def _runtime(network_hosts: list[str], artifact_access: list[str]) -> IsolatedExtensionRuntime:
    """Return a runtime whose allowlists are exactly the lists given here.

    ``AdapterManifestBuilder`` replaces an empty artifact list with the
    default grants. The runtime is built from a schema-valid manifest and
    then given these lists, including empty ones, before validation.
    """
    manifest = (
        AdapterManifestBuilder("allowlist.probe", "1.0.0")
        .with_permissions(
            network_hosts=["api.approved.com"],
            artifact_access=["read_job_inputs"],
        )
        .build()
    )
    manifest["permissions"]["network_hosts"] = list(network_hosts)
    manifest["permissions"]["artifact_access"] = list(artifact_access)
    return IsolatedExtensionRuntime(manifest)


class RuntimeAllowlistTests(TestCase):
    def test_empty_network_allowlist_denies_every_destination(self):
        runtime = _runtime([], [_GRANTED_ARTIFACT])
        for destination in ("example.com", "localhost", _GRANTED_HOST):
            with self.subTest(destination=destination):
                with self.assertRaises(PermissionDeniedError):
                    runtime.verify_network_access(destination)

    def test_granted_host_succeeds_only_as_the_exact_string(self):
        runtime = _runtime([_GRANTED_HOST], [_GRANTED_ARTIFACT])
        self.assertIsNone(runtime.verify_network_access(_GRANTED_HOST))
        denied = (
            "https://api.approved.com",
            "http://api.approved.com",
            "https://api.approved.com:443",
            "api.approved.com:443",
            "api.approved.com:80",
            "API.APPROVED.COM",
            "Api.Approved.Com",
            "notapi.approved.com",
            "api.approved.com.evil.com",
            "evil.api.approved.com",
            "api.approved.com.",
            "api.approved.com ",
            " api.approved.com",
            "example.com",
        )
        for destination in denied:
            with self.subTest(destination=destination):
                with self.assertRaises(PermissionDeniedError):
                    runtime.verify_network_access(destination)

    def test_unknown_artifact_kind_is_denied_and_granted_kind_succeeds(self):
        runtime = _runtime([_GRANTED_HOST], [_GRANTED_ARTIFACT])
        self.assertIsNone(runtime.verify_artifact_access(_GRANTED_ARTIFACT))
        for kind in (
            "write_to_arbitrary_s3_bucket",
            "write_attempt_staging",
            "READ_JOB_INPUTS",
            "read_job_inputs.extra",
            "notread_job_inputs",
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(PermissionDeniedError):
                    runtime.verify_artifact_access(kind)

    def test_empty_artifact_allowlist_denies_every_kind(self):
        runtime = _runtime([_GRANTED_HOST], [])
        for kind in (
            _GRANTED_ARTIFACT,
            "write_attempt_staging",
            "write_to_arbitrary_s3_bucket",
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(PermissionDeniedError):
                    runtime.verify_artifact_access(kind)
