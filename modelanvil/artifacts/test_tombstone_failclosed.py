"""Fail-closed regressions for artifact tombstone enforcement.

These tests cover register_tombstone, is_resource_tombstoned, and
enforce_resource_active. Refusal is django.core.exceptions.PermissionDenied.
"""
import uuid

from django.core.exceptions import PermissionDenied
from django.test import TestCase

from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.artifacts.tombstones import (
    enforce_resource_active,
    is_resource_tombstoned,
    register_tombstone,
)
from modelanvil.identity.models import Tenant


class TombstoneFailClosedTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="tombstone-failclosed", name="Tombstone Fail Closed")
        self.artifact = self._committed_artifact("models/failclosed.bin", "a")

    def test_registered_artifact_is_tombstoned_and_refused(self):
        resource_id = str(self.artifact.artifact_id)
        self.assertFalse(is_resource_tombstoned(self.tenant.tenant_id, "artifact", resource_id))
        enforce_resource_active(self.tenant.tenant_id, "artifact", resource_id)

        tombstone = register_tombstone(
            self.tenant.tenant_id,
            "artifact",
            resource_id,
            reason="Legal retention revocation",
        )

        self.assertEqual(tombstone.resource_id, resource_id)
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", resource_id))
        with self.assertRaises(PermissionDenied) as refusal:
            enforce_resource_active(self.tenant.tenant_id, "artifact", resource_id)
        self.assertIn("tombstoned", str(refusal.exception))
        self.assertNotIn("HTTP", str(refusal.exception))

    def test_registered_non_artifact_is_tombstoned_and_refused(self):
        resource_id = str(uuid.uuid4())
        self.assertFalse(is_resource_tombstoned(self.tenant.tenant_id, "document", resource_id))
        enforce_resource_active(self.tenant.tenant_id, "document", resource_id)

        register_tombstone(self.tenant.tenant_id, "document", resource_id, reason="Revoked")

        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "document", resource_id))
        with self.assertRaises(PermissionDenied) as refusal:
            enforce_resource_active(self.tenant.tenant_id, "document", resource_id)
        self.assertIn("tombstoned", str(refusal.exception))

    def test_unknown_artifact_id_fails_closed(self):
        unknown = str(uuid.uuid4())
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", unknown))
        with self.assertRaises(PermissionDenied) as refusal:
            enforce_resource_active(self.tenant.tenant_id, "artifact", unknown)
        self.assertIn("unknown", str(refusal.exception))

        register_tombstone(self.tenant.tenant_id, "artifact", unknown, reason="Unknown artifact id")
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", unknown))
        with self.assertRaises(PermissionDenied) as refusal:
            enforce_resource_active(self.tenant.tenant_id, "artifact", unknown)
        self.assertIn("tombstoned", str(refusal.exception))

    def test_unresolved_artifact_id_registration_still_tombstones(self):
        resource_id = "not-a-uuid"
        tombstone = register_tombstone(
            self.tenant.tenant_id,
            "artifact",
            resource_id,
            reason="Unresolvable id",
        )
        self.assertEqual(tombstone.resource_id, resource_id)
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", resource_id))
        with self.assertRaises(PermissionDenied) as refusal:
            enforce_resource_active(self.tenant.tenant_id, "artifact", resource_id)
        self.assertIn("tombstoned", str(refusal.exception))

    def test_missing_identifiers_fail_closed(self):
        resource_id = str(self.artifact.artifact_id)
        cases = (
            ("", "artifact", resource_id),
            (None, "artifact", resource_id),
            (self.tenant.tenant_id, "", resource_id),
            (self.tenant.tenant_id, "   ", resource_id),
            (self.tenant.tenant_id, "artifact", ""),
            (self.tenant.tenant_id, "artifact", None),
            (self.tenant.tenant_id, "artifact", "   "),
        )
        for tenant_id, resource_type, missing_id in cases:
            self.assertTrue(is_resource_tombstoned(tenant_id, resource_type, missing_id))
            with self.assertRaises(PermissionDenied) as refusal:
                enforce_resource_active(tenant_id, resource_type, missing_id)
            self.assertIn("missing", str(refusal.exception))

        before = DeletionTombstone.objects.count()
        with self.assertRaises(PermissionDenied):
            register_tombstone(self.tenant.tenant_id, "artifact", "", reason="blank")
        with self.assertRaises(PermissionDenied):
            register_tombstone(self.tenant.tenant_id, "artifact", None, reason="none")
        with self.assertRaises(PermissionDenied):
            register_tombstone(self.tenant.tenant_id, "artifact", "   ", reason="blank")
        self.assertEqual(DeletionTombstone.objects.count(), before)
        enforce_resource_active(self.tenant.tenant_id, "artifact", resource_id)

    def test_primary_key_registration_refuses_the_public_artifact_id(self):
        tombstone = register_tombstone(
            self.tenant.tenant_id,
            "artifact",
            self.artifact.pk,
            reason="Registered by primary key",
        )
        self.assertEqual(tombstone.resource_id, str(self.artifact.pk))
        self.artifact.refresh_from_db()
        self.assertEqual(self.artifact.state, Artifact.State.TOMBSTONED)
        public_id = str(self.artifact.artifact_id)
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", public_id))
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", self.artifact.pk))
        with self.assertRaises(PermissionDenied) as refusal:
            enforce_resource_active(self.tenant.tenant_id, "artifact", public_id)
        self.assertIn("tombstoned", str(refusal.exception))

    def test_direct_artifact_tombstone_fails_closed(self):
        self.artifact.tombstone()
        resource_id = str(self.artifact.artifact_id)
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", resource_id))
        with self.assertRaises(PermissionDenied) as refusal:
            enforce_resource_active(self.tenant.tenant_id, "artifact", resource_id)
        self.assertIn("tombstoned", str(refusal.exception))

    def test_artifact_id_from_another_tenant_fails_closed(self):
        other = Tenant.objects.create(slug="tombstone-other-tenant", name="Other Tenant")
        resource_id = str(self.artifact.artifact_id)
        self.assertTrue(is_resource_tombstoned(other.tenant_id, "artifact", resource_id))
        with self.assertRaises(PermissionDenied):
            enforce_resource_active(other.tenant_id, "artifact", resource_id)
        enforce_resource_active(self.tenant.tenant_id, "artifact", resource_id)

    def _committed_artifact(self, object_key, digest_char):
        artifact = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id,
            storage_location_id="local",
            object_key=object_key,
            sha256=digest_char * 64,
            byte_size=1024,
            media_type="application/octet-stream",
        )
        artifact.mark_verified(verified_sha256=digest_char * 64, verified_size=1024)
        return artifact
