"""Transfer-part retention cleanup tests."""
import hashlib
import io
import tempfile
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from modelanvil.artifacts.models import Artifact, TransferSession
from modelanvil.artifacts.storage import LocalArtifactStorage
from modelanvil.identity.models import Tenant


class TransferCleanupCommandTests(TestCase):
    def test_prunes_terminal_parts_only_after_retention_and_marks_completion(self):
        tenant = Tenant.objects.create(slug="transfer-cleanup", name="Transfer Cleanup")
        part = b"temporary transfer part"
        artifact = Artifact.objects.create(
            tenant_id=tenant.tenant_id,
            storage_location_id="local",
            object_key="outputs/cleanup.bin",
            sha256=hashlib.sha256(part).hexdigest(),
            byte_size=len(part),
            media_type="application/octet-stream",
        )
        transfer = TransferSession.objects.create(tenant_id=tenant.tenant_id, artifact=artifact)
        key = f"{transfer.staging_prefix}/parts/00001"
        transfer.part_manifest = {
            "1": {"object_key": key, "sha256": hashlib.sha256(part).hexdigest(), "byte_size": len(part)}
        }
        transfer.bytes_verified = len(part)
        transfer.state = TransferSession.State.ABORTED
        transfer.save()
        old_time = timezone.now() - timedelta(days=2)
        TransferSession.objects.filter(pk=transfer.pk).update(updated_at=old_time)

        with tempfile.TemporaryDirectory() as root:
            backend = LocalArtifactStorage(root)
            backend.put(tenant.tenant_id, key, io.BytesIO(part))
            with override_settings(MODELANVIL={"artifact_backend": "filesystem", "artifact_root": root}):
                call_command("prune_transfer_parts", retention_days=1, verbosity=0)

            with self.assertRaises(FileNotFoundError):
                backend.open(tenant.tenant_id, key)
            transfer.refresh_from_db()
            self.assertIsNotNone(transfer.parts_purged_at)
            self.assertEqual(transfer.part_manifest["1"]["object_key"], key)
