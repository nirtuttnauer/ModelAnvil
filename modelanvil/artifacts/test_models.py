"""Artifact and dataset integrity tests."""
from django.test import TestCase

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.identity.models import Tenant


class ArtifactModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="artifact-test", name="Artifact Test")

    def test_artifacts_are_tenant_scoped_and_committed_only_after_verification(self):
        staged = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id,
            storage_location_id="local-dev",
            object_key="org/x/staging/a/file.jsonl",
            sha256="a" * 64,
            byte_size=12,
            media_type="application/jsonl",
            state=Artifact.State.STAGING,
        )
        self.assertIsNone(staged.committed_at)
        staged.mark_verified(verified_sha256="a" * 64, verified_size=12)
        staged.refresh_from_db()
        self.assertEqual(staged.state, Artifact.State.COMMITTED)
        self.assertIsNotNone(staged.committed_at)

    def test_published_dataset_revision_is_immutable(self):
        dataset = Dataset.objects.create(tenant_id=self.tenant.tenant_id, name="training")
        revision = DatasetRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            dataset=dataset,
            revision_no=1,
            manifest_digest="b" * 64,
        )
        revision.publish()
        revision.refresh_from_db()
        with self.assertRaises(ValueError):
            revision.manifest_digest = "c" * 64
            revision.save()
