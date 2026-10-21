"""Authenticated local serving, failed startup retention and verified rollback."""
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from modelanvil.api import test_candidate_review as fixture
from modelanvil.identity.models import ApiKey, Role
from modelanvil.releases.models import DeploymentRevision, ServingEndpoint


class LocalServingTests(TestCase):
    artifact = fixture.CandidateReviewTests.artifact
    envelope = fixture.CandidateReviewTests.envelope
    payload = fixture.CandidateReviewTests.payload
    launch = fixture.CandidateReviewTests.launch
    execute = fixture.CandidateReviewTests.execute
    suite = fixture.CandidateReviewTests.suite
    _suite_pk = fixture.CandidateReviewTests._suite_pk
    pending_eval = fixture.CandidateReviewTests.pending_eval
    queued = fixture.CandidateReviewTests.queued
    review = fixture.CandidateReviewTests.review

    def setUp(self):
        fixture.CandidateReviewTests.setUp(self)
        self.body.update(min_accuracy=0, license_record={'spdx': 'mit', 'source': 'Test owner declaration', 'notice': 'Test reference weights only'})
        self.version = self.review()
        self.assertEqual(self.version['local_review']['state'], 'approved')
        response = self.client.post('/api/v1/serving-endpoints/', {'name': 'Local serving', 'endpoint_key': 'local'}, format='json')
        self.assertEqual(response.status_code, 201, response.json())
        self.endpoint = response.data['endpoint_id']
        self.path = f'/api/v1/serving-endpoints/{self.endpoint}/'
        self.deploy_body = {'release_version_id': self.version['release_version_id']}

    def test_authenticated_actual_serving_and_failed_startup_preserves_previous_pointer(self):
        response = self.client.post(self.path+'deploy-local/', self.deploy_body, format='json')
        self.assertEqual(response.status_code, 201, response.json())
        first = response.data['deployment_id']
        self.assertEqual(response.data['readiness_state'], 'ready')
        self.assertEqual(response.data['release_version_id'], self.version['release_version_id'])
        endpoint_record = self.client.get(self.path).data
        self.assertEqual(endpoint_record['active_deployment']['release_version_id'], self.version['release_version_id'])
        self.assertEqual(endpoint_record['deployments'][0]['release_version_id'], self.version['release_version_id'])
        result = self.client.post(self.path+'completions/', {'prompt': 'x', 'max_tokens': 2}, format='json')
        self.assertEqual(result.status_code, 200, result.json())
        self.assertEqual(result.data['deployment_id'], first)
        self.assertGreater(result.data['usage']['completion_tokens'], 0)
        self.assertFalse(result.data['production_qualified'])
        self.assertEqual(APIClient().get(self.path+'local-health/').status_code, 401)
        with patch('modelanvil.releases.local_serving.bounded_inference', side_effect=RuntimeError('Interrupted startup')):
            failed = self.client.post(self.path+'deploy-local/', self.deploy_body, format='json')
        self.assertEqual(failed.status_code, 409)
        endpoint = ServingEndpoint.all_objects.get(endpoint_id=self.endpoint)
        self.assertEqual(str(endpoint.active_deployment.deployment_id), first)
        self.assertEqual(endpoint.deployments.filter(readiness_state='failed').count(), 1)
        self.assertEqual(self.client.get(self.path+'local-health/').data['state'], 'ready')

    def test_rollback_reprobes_previous_revision_and_runtime_drift_blocks_inference(self):
        first = self.client.post(self.path+'deploy-local/', self.deploy_body, format='json').data
        second = self.client.post(self.path+'deploy-local/', self.deploy_body, format='json').data
        rollback = self.client.post(self.path+'rollback/', {}, format='json')
        self.assertEqual(rollback.status_code, 200, rollback.json())
        self.assertEqual(rollback.data['revision_no'], 3)
        self.assertNotEqual(rollback.data['deployment_id'], second['deployment_id'])
        self.assertEqual(self.client.get(self.path+'local-health/').status_code, 200)
        endpoint = ServingEndpoint.all_objects.get(endpoint_id=self.endpoint)
        prior = endpoint.active_deployment_id
        with patch('modelanvil.releases.local_serving.bounded_inference', side_effect=ValueError('Previous bytes are tombstoned')):
            failed = self.client.post(self.path+'rollback/', {}, format='json')
        self.assertEqual(failed.status_code, 409)
        endpoint.refresh_from_db(); self.assertEqual(endpoint.active_deployment_id, prior)
        DeploymentRevision.all_objects.filter(pk=prior).update(serving_config={'backend': 'modelanvil.local-on-demand-cpu.v1', 'build_digest': 'old'})
        self.assertEqual(self.client.get(self.path+'local-health/').status_code, 503)
        self.assertEqual(self.client.post(self.path+'completions/', {'prompt':'x'}, format='json').status_code, 400)

    def test_missing_license_failing_quality_and_engineer_permission_block_deploy(self):
        from modelanvil.releases.models import ReleaseVersion
        version = ReleaseVersion.all_objects.get(release_version_id=self.version['release_version_id'])
        version.bundle_manifest['local_review']['criteria'][0]['passed'] = False
        version.save()
        self.assertEqual(self.client.post(self.path+'deploy-local/', self.deploy_body, format='json').status_code, 409)
        self.assertIsNone(ServingEndpoint.all_objects.get(endpoint_id=self.endpoint).active_deployment_id)
        ApiKey.objects.filter(tenant=self.tenant).update(role=Role.ENGINEER)
        self.assertEqual(self.client.post(self.path+'deploy-local/', self.deploy_body, format='json').status_code, 403)

    def test_component_tombstone_stops_health_and_inference_without_switching_history(self):
        from modelanvil.artifacts.models import DeletionTombstone
        response = self.client.post(self.path+'deploy-local/', self.deploy_body, format='json')
        self.assertEqual(response.status_code, 201)
        DeletionTombstone.all_objects.create(tenant_id=self.tenant.pk,
            resource_id=str(self.candidate.model_version_id), resource_type='model_version', reason='Test access withdrawal')
        self.assertEqual(self.client.get(self.path+'local-health/').status_code, 503)
        self.assertEqual(self.client.post(self.path+'completions/', {'prompt':'x'}, format='json').status_code, 400)
        self.assertEqual(ServingEndpoint.all_objects.get(endpoint_id=self.endpoint).deployments.count(), 1)
