"""Operational qualification test suite (WP-17 / TECH-032).

Verifies:
- Database and storage backup creation with SHA256 checksum manifests.
- Simulated point-in-time recovery drill and corrupted backup rejection.
- Tenant audit trail correlation and completeness.
- Fail-closed deletion tombstone enforcement.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from django.test import TestCase

from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.core.models import AuditEvent, record_audit
from modelanvil.identity.models import Membership, Role, Membership, Role, Tenant, User
from modelanvil.ops.audit_verification import verify_tenant_audit_trail
from modelanvil.ops.backup import generate_backup, verify_restore_drill
from modelanvil.ops.tombstones import verify_tombstone_enforcement


class OperationsQualificationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="ops-tenant", name="Ops Tenant")
        self.user = User.objects.create(email="ops@example.com")
        Membership.objects.create(tenant=self.tenant, user=self.user, role=Role.ADMIN)

    def test_backup_and_restore_drill_verification(self):
        """TECH-032: Verify backup archive generation and point-in-time restore verification."""
        with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as dest_dir:
            # Create a mock storage artifact
            test_file = os.path.join(storage_dir, "weights.bin")
            with open(test_file, "wb") as f:
                f.write(b"model-weights-binary-data-xyz")

            backup_res = generate_backup(
                backup_id="test-backup-001",
                models_to_backup=["identity.tenant", "identity.user"],
                storage_dir=storage_dir,
                dest_dir=dest_dir,
            )

            manifest = backup_res["manifest"]
            self.assertEqual(manifest["backup_id"], "test-backup-001")
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertGreaterEqual(manifest["total_records"], 2)
            self.assertEqual(manifest["storage_total_bytes"], len(b"model-weights-binary-data-xyz"))

            # Run restore drill
            drill = verify_restore_drill(backup_res["backup_path"])
            self.assertTrue(drill["verified"])
            self.assertEqual(drill["status"], "VERIFIED")
            self.assertEqual(drill["artifacts_verified"], 1)

    def test_restore_drill_detects_corrupted_artifact(self):
        """TECH-032: Verify restore drill fails closed if an artifact checksum is altered."""
        with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as dest_dir:
            test_file = os.path.join(storage_dir, "weights.bin")
            with open(test_file, "wb") as f:
                f.write(b"original-data")

            backup_res = generate_backup(
                backup_id="tamper-test",
                models_to_backup=["identity.tenant"],
                storage_dir=storage_dir,
                dest_dir=dest_dir,
            )

            # Tamper with the artifact
            tampered_path = os.path.join(backup_res["backup_path"], "artifacts", "weights.bin")
            with open(tampered_path, "wb") as f:
                f.write(b"corrupted-tampered-data")

            with self.assertRaises(ValueError) as ctx:
                verify_restore_drill(backup_res["backup_path"])
            self.assertIn("checksum corrupted", str(ctx.exception).lower())

    def test_audit_trail_correlation_and_completeness(self):
        """TECH-032: Verify audit entries contain full correlation IDs and snapshots."""
        record_audit(
            action="update",
            resource_type="tenant_settings",
            resource_id=self.tenant.tenant_id,
            actor_id=self.user.id,
            actor_kind="user",
            input_snapshot={"slug": "ops-tenant", "request_id": str(uuid.uuid4())},
            tenant_id=self.tenant.tenant_id,
        )

        audit_report = verify_tenant_audit_trail(self.tenant.tenant_id)
        self.assertTrue(audit_report["all_valid"])
        self.assertEqual(audit_report["invalid_count"], 0)
        self.assertGreaterEqual(audit_report["total_events"], 1)

    def test_deletion_tombstone_enforcement(self):
        """TECH-024 / TECH-032: Tombstone check flags deleted resource as blocked."""
        res_id = str(uuid.uuid4())
        # Before tombstone
        status = verify_tombstone_enforcement(self.tenant.tenant_id, "document", res_id)
        self.assertFalse(status["blocked"])

        # Add tombstone
        DeletionTombstone.objects.create(
            tenant_id=self.tenant.tenant_id,
            resource_type="document",
            resource_id=res_id,
            reason="GDPR right-to-be-forgotten request",
        )

        status_after = verify_tombstone_enforcement(self.tenant.tenant_id, "document", res_id)
        self.assertTrue(status_after["blocked"])
        self.assertTrue(status_after["is_tombstoned"])
        self.assertEqual(status_after["reason"], "GDPR right-to-be-forgotten request")
