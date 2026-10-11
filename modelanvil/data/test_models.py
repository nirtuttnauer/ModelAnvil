from django.core.exceptions import ValidationError
from django.test import TestCase

from modelanvil.data.models import DataSource, SourceSnapshot, validate_sample_envelope
from modelanvil.identity.models import Tenant


class DataRegistryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="data-test", name="Data Test")

    def test_snapshot_requires_complete_success_before_ready_and_is_immutable(self):
        source = DataSource.objects.create(tenant_id=self.tenant.tenant_id, name="upload", kind="upload")
        snapshot = SourceSnapshot.objects.create(
            tenant_id=self.tenant.tenant_id, source=source, source_revision="r1"
        )
        with self.assertRaises(ValueError):
            snapshot.mark_ready(manifest_digest="a" * 64, item_count=2, failure_count=1)
        snapshot.mark_ready(manifest_digest="a" * 64, item_count=2)
        with self.assertRaises(ValueError):
            snapshot.item_count = 3
            snapshot.save()

    def test_sample_envelope_uses_canonical_schema(self):
        doc = {
            "schema_version": "1.0", "sample_id": "b51630a7-06a9-4d9a-998e-1f959a9e1e11",
            "source_group_id": "group-1", "blocks": [{"block_id": "b1", "type": "text", "text": "hello"}],
            "provenance": {"source_snapshot_ref": "snap-1", "source_record_key": "row-1", "content_sha256": "a" * 64},
        }
        self.assertIs(validate_sample_envelope(doc), doc)
        doc["schema_version"] = "99.0"
        with self.assertRaises(Exception):
            validate_sample_envelope(doc)
