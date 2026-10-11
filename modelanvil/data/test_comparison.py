"""Tests for revision comparison and export manifests (WP-05)."""
from django.test import TestCase

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.data.comparison import compare_revisions, export_revision_manifest
from modelanvil.identity.models import Tenant


class ComparisonTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="compare-test", name="Compare Test")
        self.dataset = Dataset.objects.create(tenant_id=self.tenant.tenant_id, name="demo-dataset")
        self.rev1 = DatasetRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            dataset=self.dataset,
            revision_no=1,
            manifest_digest="1" * 64,
            recipe_digest="a" * 64,
            row_count=100,
            source_snapshots=["snap-1"],
            metadata={"recipe": {"detect": True}, "drop_report": {"drop_reason_counts": {"privacy": 5}}},
        )
        self.rev2 = DatasetRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            dataset=self.dataset,
            revision_no=2,
            manifest_digest="2" * 64,
            recipe_digest="b" * 64,
            row_count=120,
            source_snapshots=["snap-1", "snap-2"],
            metadata={"recipe": {"detect": False}, "drop_report": {"drop_reason_counts": {"privacy": 2, "quality": 1}}},
        )

    def test_compare_revisions_computes_deltas(self):
        diff = compare_revisions(self.rev1, self.rev2)

        self.assertEqual(diff.base_revision_no, 1)
        self.assertEqual(diff.target_revision_no, 2)
        self.assertEqual(diff.row_count_delta, 20)
        self.assertTrue(diff.manifest_digest_changed)
        self.assertTrue(diff.recipe_digest_changed)
        self.assertEqual(diff.snapshots_added, ["snap-2"])
        self.assertEqual(diff.snapshots_removed, [])
        self.assertEqual(diff.drop_report_diff["privacy"], -3)
        self.assertEqual(diff.drop_report_diff["quality"], 1)
        self.assertIn("detect", diff.recipe_diff)

    def test_export_revision_manifest_creates_verifiable_manifest(self):
        manifest = export_revision_manifest(self.rev1)

        self.assertEqual(manifest["dataset_name"], "demo-dataset")
        self.assertEqual(manifest["revision_no"], 1)
        self.assertEqual(manifest["row_count"], 100)
        self.assertTrue(len(manifest["export_sha256"]) == 64)
