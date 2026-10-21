"""Policy administration retains the budget admission and accounting contract."""
import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key


@override_settings(ALLOWED_HOSTS=['testserver'])
class BudgetManagementTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug='budget-management', name='Budget management')
        self.client = APIClient()
        self.auth(Role.ADMIN)

    def auth(self, role, tenant=None):
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=tenant or self.tenant, name=role, role=role, secret_hash=hashed)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')

    def create(self, **changes):
        return self.client.post('/api/v1/budget-policies/', {'name': 'CPU steps', 'period': 'lifetime',
            'unit': 'training_steps', 'limit_amount': '100', 'currency': '', **changes}, format='json')

    def test_admin_manages_positive_quantity_limits_without_monetary_confusion(self):
        self.assertEqual(self.create(limit_amount='0').status_code, 400)
        self.assertEqual(self.create(currency='USD').status_code, 400)
        response = self.create(); self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['allowance']['scope'], 'tenant')
        self.assertEqual(Decimal(response.data['allowance']['remaining_amount']), 100)
        self.assertEqual(self.create().status_code, 400)
        self.assertEqual(BudgetPolicy.all_objects.count(), 1)
        url = f"/api/v1/budget-policies/{response.data['policy_id']}/"
        for role in (Role.ENGINEER, Role.MANAGER, Role.VIEWER):
            self.auth(role)
            self.assertFalse(self.client.get('/api/v1/budget-policies/permissions/').data['can_administer'])
            self.assertEqual(self.create(name='denied').status_code, 403)
            self.assertEqual(self.client.patch(url, {'enabled': False}, format='json').status_code, 403)
        self.auth(Role.ADMIN)
        self.assertEqual(self.client.patch(url, {'enabled': False}, format='json').status_code, 200)

    def test_allowance_reconciles_reservation_settlement_release_and_period(self):
        data = self.create().data
        policy = BudgetPolicy.all_objects.get(policy_id=data['policy_id'])
        one = BudgetReservation.reserve(tenant_id=self.tenant.pk, policy=policy, job_id=uuid.uuid4(), estimated_amount=20)
        two = BudgetReservation.reserve(tenant_id=self.tenant.pk, policy=policy, job_id=uuid.uuid4(), estimated_amount=30)
        one.settle(10); one.settle(10)
        response = self.client.get(f'/api/v1/budget-policies/{policy.policy_id}/')
        values = response.data['allowance']
        self.assertEqual(Decimal(values['reserved_amount']), 30)
        self.assertEqual(Decimal(values['settled_amount']), 10)
        self.assertEqual(Decimal(values['remaining_amount']), 60)
        two.release()
        self.assertEqual(Decimal(self.client.get(f'/api/v1/budget-policies/{policy.policy_id}/').data['allowance']['remaining_amount']), 90)

    def test_existing_commitments_block_limit_and_unit_changes(self):
        data = self.create().data
        policy = BudgetPolicy.all_objects.get(policy_id=data['policy_id'])
        BudgetReservation.reserve(tenant_id=self.tenant.pk, policy=policy, job_id=uuid.uuid4(), estimated_amount=40)
        url = f'/api/v1/budget-policies/{policy.policy_id}/'
        for changes in ({'limit_amount': 39}, {'unit': 'bank_acquisition_records'}, {'period': 'daily'}):
            self.assertEqual(self.client.patch(url, changes, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'limit_amount': 40}, format='json').status_code, 200)
        with self.assertRaises(ValueError):
            BudgetReservation.reserve(tenant_id=self.tenant.pk, policy=policy, job_id=uuid.uuid4(), estimated_amount=1)
        policy.refresh_from_db(); self.assertEqual(policy.unit, 'training_steps')

    def test_other_tenants_cannot_read_or_edit_policy(self):
        data = self.create().data
        self.auth(Role.ADMIN, Tenant.objects.create(slug='other-budget', name='Other'))
        self.assertEqual(self.client.get('/api/v1/budget-policies/').data['results'], [])
        self.assertEqual(self.client.patch(f"/api/v1/budget-policies/{data['policy_id']}/", {'enabled': False}, format='json').status_code, 404)
