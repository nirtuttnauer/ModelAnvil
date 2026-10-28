import hashlib
import io
import json
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from modelanvil.runners.training import test_cpu_runtime as cpu
from modelanvil.artifacts.models import Artifact, DatasetRevision


class ResourceInspectionTests(TestCase):
    setUp = cpu.CpuRuntimeTests.setUp
    artifact = cpu.CpuRuntimeTests.artifact
    envelope = cpu.CpuRuntimeTests.envelope

    def test_exact_revision_inspection_returns_verified_records_and_source_splits(self):
        response = self.client.get(f'/api/v1/dataset-revisions/{self.dataset.revision_id}/inspect/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual([row['assigned_split'] for row in response.data['rows']], ['train', 'train'])
        self.assertTrue(response.data['capabilities']['train'])
        search = self.client.get(f'/api/v1/dataset-revisions/{self.dataset.revision_id}/inspect/?query=ab%20ab')
        self.assertEqual(search.data['total'], 1)
        self.dataset.manifest_digest = '0'*64
        DatasetRevision.all_objects.filter(pk=self.dataset.pk).update(manifest_digest=self.dataset.manifest_digest)
        self.assertEqual(self.client.get(f'/api/v1/dataset-revisions/{self.dataset.revision_id}/inspect/').status_code, 400)

    def test_preview_creates_no_resources_and_matches_published_recipe_and_samples(self):
        from modelanvil.data.publication import publish_prepared_dataset
        source = b'text,group\nfirst example,a\nsecond example,b\n'
        config = {'source_format': 'csv', 'text_field': 'text', 'group_field': 'group',
            'validation_percent': 0, 'test_percent': 0, 'split_seed': '7', 'dedup': True}
        count = Artifact.all_objects.count()
        preview = self.client.post('/api/v1/datasets/preview/', {
            'file': SimpleUploadedFile('source.csv', source), 'configuration': json.dumps(config)}, format='multipart')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(Artifact.all_objects.count(), count)
        artifact = self.artifact('new.csv', source, 'text/csv')
        published = publish_prepared_dataset(self.dataset.dataset, artifact, **config)
        self.assertEqual(preview.data['recipe_digest'], published.recipe_digest)
        inspected = self.client.get(f'/api/v1/dataset-revisions/{published.revision_id}/inspect/')
        self.assertEqual(preview.data['rows'], inspected.data['rows'])
        body = {**config, 'input_artifact_id': str(artifact.artifact_id)}
        first = self.client.post(f'/api/v1/datasets/{self.dataset.dataset.dataset_id}/prepare/', body, format='json', HTTP_IDEMPOTENCY_KEY='publication-retry')
        repeated = self.client.post(f'/api/v1/datasets/{self.dataset.dataset.dataset_id}/prepare/', body, format='json', HTTP_IDEMPOTENCY_KEY='publication-retry')
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data['revision_id'], repeated.data['revision_id'])
        changed = publish_prepared_dataset(self.dataset.dataset, artifact, **{**config, 'split_seed': '8'})
        self.assertNotEqual(changed.pk, published.pk)

    def test_invalid_preview_returns_actionable_failure_without_publication(self):
        before = DatasetRevision.all_objects.count()
        response = self.client.post('/api/v1/datasets/preview/', {
            'file': SimpleUploadedFile('bad.csv', b'wrong\nvalue\n'),
            'configuration': json.dumps({'source_format': 'csv', 'text_field': 'text'})}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(DatasetRevision.all_objects.count(), before)

    def test_model_lineage_exposes_verified_artifact_without_weight_payload(self):
        response = self.client.get(f'/api/v1/model-versions/{self.base.model_version_id}/lineage/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['artifacts']), 1)
        self.assertEqual(response.data['tokenizer_id'], str(self.tok.tokenizer_id))
        self.assertNotIn('data_b64', str(response.data))
