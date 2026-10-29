from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key


@override_settings(ALLOWED_HOSTS=['testserver'])
class DeploymentCapabilitiesTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(slug='beta-capabilities', name='Beta')

    def authenticate(self, role):
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name='test', role=role, secret_hash=hashed)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')

    def test_requires_authentication(self):
        self.assertEqual(self.client.get('/api/v1/deployment-capabilities/').status_code, 401)

    @patch('modelanvil.api.views.deployment.host_status')
    def test_observed_capacity_and_role_do_not_grant_permission(self, host):
        host.return_value = {'available': True, 'busy': False, 'message': 'Ready'}
        self.authenticate(Role.VIEWER)
        response = self.client.get('/api/v1/deployment-capabilities/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['operations']['local_training']['enabled'])
        self.assertFalse(response.data['operations']['evaluation']['enabled'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.authenticate(Role.ENGINEER)
        self.assertTrue(self.client.get('/api/v1/deployment-capabilities/').data['operations']['local_training']['enabled'])
        host.return_value = {'available': False, 'busy': False, 'message': 'Start the managed service.'}
        response = self.client.get('/api/v1/deployment-capabilities/')
        self.assertFalse(response.data['operations']['local_training']['enabled'])
        self.assertEqual(response.data['operations']['local_training']['reason'], 'Start the managed service.')
        self.assertEqual(response.data['operations']['classification']['limits']['max_rows'], 1000)
