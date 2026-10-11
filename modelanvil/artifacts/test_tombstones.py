"""Tests for artifact and data deletion tombstones (WP-04)."""
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.tombstones import (
    enforce_resource_active,
    is_resource_tombstoned,
    register_tombstone,
)
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import OutboxEvent


class TombstoneTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="tombstone-test", name="Tombstone Test")
        self.artifact = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id,
            storage_location_id="local",
            object_key="models/base.bin",
            sha256="a" * 64,
            byte_size=1024,
            media_type="application/octet-stream",
        )
        self.artifact.mark_verified(verified_sha256="a" * 64, verified_size=1024)

    def test_register_tombstone_marks_artifact_and_emits_outbox_event(self):
        self.assertFalse(is_resource_tombstoned(self.tenant.tenant_id, "artifact", str(self.artifact.artifact_id)))

        tombstone = register_tombstone(
            self.tenant.tenant_id,
            "artifact",
            str(self.artifact.artifact_id),
            reason="Legal retention revocation",
        )

        self.assertEqual(tombstone.resource_id, str(self.artifact.artifact_id))
        self.assertTrue(is_resource_tombstoned(self.tenant.tenant_id, "artifact", str(self.artifact.artifact_id)))

        self.artifact.refresh_from_db()
        self.assertEqual(self.artifact.state, Artifact.State.TOMBSTONED)

        event = OutboxEvent.objects.filter(topic=f"tenant.{self.tenant.tenant_id}.policy.tombstoned").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.payload["event_type"], "policy.tombstoned")

    def test_enforce_resource_active_fails_closed_when_tombstoned(self):
        # Active resource passes
        enforce_resource_active(self.tenant.tenant_id, "artifact", str(self.artifact.artifact_id))

        register_tombstone(self.tenant.tenant_id, "artifact", str(self.artifact.artifact_id), reason="Revoked")

        with self.assertRaises(PermissionDenied):
            enforce_resource_active(self.tenant.tenant_id, "artifact", str(self.artifact.artifact_id))
