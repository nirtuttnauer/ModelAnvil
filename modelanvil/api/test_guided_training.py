import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.core.tenancy import reset_context
from modelanvil.identity.models import ApiKey, Membership, Project, Role, Tenant, User
from modelanvil.runners.models import LocalTrainingHost, ModelVersion
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.managed import host_status, prepare_resources, recommended_source


@override_settings(MODELANVIL_SELF_SERVICE_ACCOUNTS=True)
class AccountTests(TestCase):
    def setUp(self):
        reset_context()
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=True)

    def signup(self, email='new@example.invalid'):
        self.client.get('/api/v1/accounts/status/')
        return self.client.post('/api/v1/accounts/signup/', {'email': email, 'name': 'New user',
            'password': 'a-long-testing-password-937!'}, format='json', HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def test_signup_creates_isolated_scope_and_httponly_session(self):
        response = self.signup()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['token'], 'session')
        self.assertTrue(response.cookies['modelanvil_session']['httponly'])
        self.assertEqual(response.cookies['modelanvil_session']['samesite'], 'Lax')
        self.assertNotIn('mkv_', json.dumps(response.data))
        user = User.objects.get(email='new@example.invalid')
        self.assertTrue(user.check_password('a-long-testing-password-937!'))
        self.assertFalse(user.is_staff)
        tenant = Membership.objects.get(user=user).tenant
        self.assertEqual(Project.all_objects.filter(tenant_id=tenant.pk).count(), 1)
        self.assertEqual(self.client.get('/api/v1/tenants/').data['results'][0]['tenant_id'], str(tenant.pk))

    def test_csrf_is_required_for_account_creation_and_authenticated_writes(self):
        self.assertEqual(self.client.post('/api/v1/accounts/signup/', {}, format='json').status_code, 403)
        self.signup()
        self.assertEqual(self.client.post('/api/v1/projects/', {'name': 'Unsafe'}, format='json').status_code, 403)

    def test_duplicate_dataset_name_has_repair_guidance_and_can_be_renamed(self):
        self.signup()
        headers = {'HTTP_X_CSRFTOKEN': self.client.cookies['csrftoken'].value,
                   'HTTP_X_PROJECT_ID': str(Project.all_objects.get().pk)}
        first = self.client.post('/api/v1/datasets/', {'name': 'My training data'}, format='json', **headers)
        self.assertEqual(first.status_code, 201, first.data)
        repeated = self.client.post('/api/v1/datasets/', {'name': 'My training data'}, format='json', **headers)
        self.assertEqual(repeated.status_code, 400)
        self.assertIn('Choose a different dataset name', repeated.json()['error']['details'][0]['message'])
        renamed = self.client.post('/api/v1/datasets/', {'name': 'My updated training data'}, format='json', **headers)
        self.assertEqual(renamed.status_code, 201, renamed.data)

    def test_new_account_cannot_access_other_project_or_key(self):
        self.signup('one@example.invalid')
        project = Project.all_objects.get()
        other = APIClient(enforce_csrf_checks=True)
        other.get('/api/v1/accounts/status/')
        response = other.post('/api/v1/accounts/signup/', {'email': 'two@example.invalid', 'password': 'another-testing-password-284!'},
                              format='json', HTTP_X_CSRFTOKEN=other.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(other.get('/api/v1/projects/', HTTP_X_PROJECT_ID=str(project.pk)).status_code, 401)
        self.assertEqual(len(other.get('/api/v1/api-keys/').data['results']), 1)

    def test_signout_revokes_session_and_membership_revocation_blocks_access(self):
        self.signup()
        key = ApiKey.objects.get()
        response = self.client.post('/api/v1/accounts/signout/', {}, format='json', HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 204)
        key.refresh_from_db(); self.assertFalse(key.is_active)
        self.client.get('/api/v1/accounts/status/')
        response = self.client.post('/api/v1/accounts/signin/', {'email': 'new@example.invalid', 'password': 'a-long-testing-password-937!'},
                              format='json', HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200, response.data)
        Membership.objects.all().delete()
        self.assertFalse(self.client.get('/api/v1/accounts/status/').data['authenticated'])
        self.assertEqual(self.client.get('/api/v1/projects/').status_code, 401)

    @override_settings(MODELANVIL_SELF_SERVICE_ACCOUNTS=False)
    def test_operator_can_disable_signup(self):
        self.assertFalse(self.client.get('/api/v1/accounts/status/').data['signup_enabled'])
        self.assertEqual(self.signup().status_code, 403)

    def csrf(self):
        return self.client.cookies['csrftoken'].value

    @override_settings(DEBUG=True)
    def test_password_reset_returns_a_code_in_debug_and_signs_in(self):
        self.signup()
        self.client.get('/api/v1/accounts/status/')
        requested = self.client.post('/api/v1/accounts/password-reset/', {'email': 'new@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(requested.status_code, 200, requested.data)
        self.assertIn('reset_code', requested.data)
        unknown = self.client.post('/api/v1/accounts/password-reset/', {'email': 'missing@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(unknown.status_code, 200, unknown.data)
        self.assertNotIn('reset_code', unknown.data)
        confirmed = self.client.post('/api/v1/accounts/password-reset/confirm/', {
            'email': 'new@example.invalid', 'code': requested.data['reset_code'], 'password': 'replacement-testing-password-937!'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertTrue(User.objects.get(email='new@example.invalid').check_password('replacement-testing-password-937!'))
        self.assertEqual(self.client.get('/api/v1/accounts/status/').data['authenticated'], True)

    @override_settings(DEBUG=False)
    def test_password_reset_does_not_reveal_a_code_when_debug_is_off(self):
        self.signup()
        self.client.get('/api/v1/accounts/status/')
        requested = self.client.post('/api/v1/accounts/password-reset/', {'email': 'new@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(requested.status_code, 200, requested.data)
        self.assertNotIn('reset_code', requested.data)
        self.assertIn('not configured', requested.data['delivery'])
        unknown = self.client.post('/api/v1/accounts/password-reset/', {'email': 'missing@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(requested.data, unknown.data)

    @override_settings(DEBUG=True)
    def test_password_reset_revokes_existing_credentials_and_rejects_reused_code(self):
        self.signup()
        old_cookie = self.client.cookies['modelanvil_session'].value
        old_keys = list(ApiKey.objects.filter(created_by__email='new@example.invalid').values_list('pk', flat=True))
        requested = self.client.post('/api/v1/accounts/password-reset/', {'email': 'new@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        payload = {'email': 'new@example.invalid', 'code': requested.data['reset_code'],
                   'password': 'replacement-testing-password-937!'}
        confirmed = self.client.post('/api/v1/accounts/password-reset/confirm/', payload,
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertFalse(ApiKey.objects.filter(pk__in=old_keys, is_active=True).exists())
        old_session = APIClient(); old_session.cookies['modelanvil_session'] = old_cookie
        self.assertFalse(old_session.get('/api/v1/accounts/status/').data['authenticated'])
        repeated = self.client.post('/api/v1/accounts/password-reset/confirm/', payload,
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(repeated.status_code, 400)

    def test_action_consumption_rejects_a_stale_previously_loaded_copy(self):
        from modelanvil.api.views.accounts import consume_action, issue_action, open_action
        from modelanvil.identity.models import AccountAction
        from rest_framework.exceptions import ValidationError
        code = issue_action(AccountAction.Purpose.PASSWORD_RESET, 'new@example.invalid')
        first = open_action(AccountAction.Purpose.PASSWORD_RESET, 'new@example.invalid', code)
        stale = open_action(AccountAction.Purpose.PASSWORD_RESET, 'new@example.invalid', code)
        consume_action(first)
        with self.assertRaises(ValidationError):
            consume_action(stale)

    def test_owner_can_invite_one_teammate_who_can_join(self):
        self.signup('owner@example.invalid')
        self.client.get('/api/v1/accounts/status/')
        self.assertTrue(self.client.get('/api/v1/accounts/status/').data['can_invite'])
        invited = self.client.post('/api/v1/accounts/invitations/', {'email': 'teammate@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(invited.status_code, 201, invited.data)
        self.assertEqual(invited.data['role'], Role.REVIEWER)
        again = self.client.post('/api/v1/accounts/invitations/', {'email': 'second@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(again.status_code, 400, again.json())
        existing = self.client.post('/api/v1/accounts/invitations/', {'email': 'owner@example.invalid'},
            format='json', HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(existing.status_code, 400)
        guest = APIClient(enforce_csrf_checks=True)
        guest.get('/api/v1/accounts/status/')
        accepted = guest.post('/api/v1/accounts/invitations/accept/', {
            'email': 'teammate@example.invalid', 'name': 'Teammate', 'code': invited.data['invite_code'],
            'password': 'teammate-testing-password-937!'}, format='json', HTTP_X_CSRFTOKEN=guest.cookies['csrftoken'].value)
        self.assertEqual(accepted.status_code, 200, accepted.data)
        membership = Membership.objects.get(user__email='teammate@example.invalid')
        self.assertEqual(membership.role, Role.REVIEWER)
        self.assertEqual(membership.tenant_id, Membership.objects.get(user__email='owner@example.invalid').tenant_id)
        self.assertEqual(guest.get('/api/v1/accounts/status/').data['can_invite'], False)


class ManagedHostTests(TestCase):
    def setUp(self):
        reset_context()

    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_model_selection_reports_memory_before_any_setup_or_launch(self):
        from modelanvil.identity.models import generate_api_key
        tenant = Tenant.objects.create(name='Hardware', slug='hardware-options')
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name='viewer', role=Role.VIEWER, secret_hash=hashed)
        client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        host = LocalTrainingHost.objects.create(status='ready', device='mps:0', memory_bytes=32 * 1024**3,
            build_digest=hf_runtime.build_digest(), last_heartbeat_at=timezone.now())
        response = client.get('/api/v1/fine-tuning/options/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['compute']['memory_bytes'], host.memory_bytes)
        self.assertEqual(response.data['model']['memory_requirements']['training']['host_memory_bytes'], 32 * 1024**3)
        self.assertEqual(response.data['model']['memory_requirements']['training']['accelerator_memory_bytes'], 12 * 1024**3)
        self.assertFalse(ModelVersion.all_objects.exists())

    def test_recommended_model_respects_observed_mac_memory(self):
        host = LocalTrainingHost.objects.create(name='local', device='mps:0', memory_bytes=16 * 1024**3)
        self.assertEqual(recommended_source(), hf_runtime.GUIDED_SOURCE)
        host.memory_bytes = 32 * 1024**3; host.save()
        self.assertEqual(recommended_source(), hf_runtime.LARGE_GUIDED_SOURCE)
        host.device = 'cuda:0'; host.save()
        self.assertEqual(recommended_source(), hf_runtime.GUIDED_SOURCE)

    def test_offline_stale_and_changed_build_are_not_ready(self):
        self.assertFalse(host_status()['available'])
        host = LocalTrainingHost.objects.create(status='ready', device='mps:0', memory_bytes=16 * 1024**3,
            build_digest=hf_runtime.build_digest(), last_heartbeat_at=timezone.now())
        self.assertTrue(host_status()['available'])
        self.assertEqual(host_status()['memory_bytes'], 16 * 1024**3)
        self.assertEqual(host_status()['memory_observed_at'], host.last_heartbeat_at)
        self.assertIn('total system memory', host_status()['memory_basis'])
        host.last_heartbeat_at = timezone.now() - timedelta(seconds=16); host.save()
        self.assertFalse(host_status()['available'])
        self.assertIsNone(host_status()['memory_bytes'])
        self.assertIsNone(host_status()['memory_observed_at'])
        host.last_heartbeat_at = timezone.now(); host.build_digest = '0' * 64; host.save()
        self.assertFalse(host_status()['available'])

    def test_setup_is_scoped_idempotent_and_does_not_launch(self):
        from modelanvil.identity.models import Team
        from modelanvil.jobs.models import Worker, WorkerPool, Job
        from modelanvil.budgets.models import BudgetPolicy
        tenant = Tenant.objects.create(name='One', slug='one')
        team = Team.all_objects.create(tenant_id=tenant.pk, name='Team', slug='team')
        project = Project.all_objects.create(tenant_id=tenant.pk, team=team, name='One', slug='one')
        host = LocalTrainingHost.objects.create(status='ready', device='mps:0', memory_bytes=16 * 1024**3,
            build_digest=hf_runtime.build_digest(), last_heartbeat_at=timezone.now())
        class Tokenizer:
            special_tokens_map = {}
            def __len__(self): return 256
        with tempfile.TemporaryDirectory() as directory:
            paths = Path(directory)
            for name in hf_runtime.FILE_HASHES: (paths / name).write_bytes(b'fixture')
            with override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_root': str(paths / 'artifacts')}), \
                 patch('modelanvil.runners.training.managed.verified_model_directory', return_value=paths), \
                 patch.object(hf_runtime, 'require_packages'), patch.object(hf_runtime, 'observed_device', return_value={'device': {'backend': 'mps', 'id': 'mps:0'}}), \
                 patch.object(hf_runtime, '_tokenizer', return_value=Tokenizer()):
                with self.assertRaisesRegex(ValueError, 'workspace owner'):
                    prepare_resources(tenant.pk, project.pk, allow_new_allowance=False)
                self.assertEqual(BudgetPolicy.all_objects.count(), 0)
                legacy_pool = WorkerPool.all_objects.create(tenant_id=tenant.pk, name='Legacy managed pool')
                Worker.all_objects.create(tenant_id=tenant.pk, name='Managed local fine-tuning', pool=legacy_pool)
                first = prepare_resources(tenant.pk, project.pk)
                second = prepare_resources(tenant.pk, project.pk)
                self.assertEqual(first, second)
                self.assertEqual(ModelVersion.all_objects.filter(tenant_id=tenant.pk, project=project).count(), 1)
                self.assertEqual(Worker.all_objects.filter(pool_id=first['pool']).count(), 1)
                self.assertEqual(Worker.all_objects.filter(pool=legacy_pool).count(), 1)
                self.assertEqual(BudgetPolicy.all_objects.count(), 1)
                self.assertEqual(Job.all_objects.count(), 0)
                with self.assertRaises(Project.DoesNotExist):
                    prepare_resources(Tenant.objects.create(slug='other', name='Other').pk, project.pk)


class ManagedAdmissionTests(TestCase):
    def test_busy_managed_worker_remains_compatible_until_heartbeat_is_stale(self):
        from modelanvil.jobs.models import Worker, WorkerPool
        tenant = Tenant.objects.create(name='Busy', slug='busy')
        pool = WorkerPool.all_objects.create(tenant_id=tenant.pk, name='Pool')
        worker = Worker.all_objects.create(tenant_id=tenant.pk, pool=pool, name='Busy', status='busy', slots=0,
            last_heartbeat_at=timezone.now(), capabilities={'managed_local': True,
                'training_runtime': hf_runtime.CONTRACT_DIGEST, 'memory_bytes': 16 * 1024**3,
                'gpu_backend': 'mps', 'gpu_device': 'mps:0', 'gpu_packages': hf_runtime.PACKAGES})
        self.assertTrue(hf_runtime.capable_worker(worker))
        worker.last_heartbeat_at = timezone.now() - timedelta(seconds=61)
        self.assertFalse(hf_runtime.capable_worker(worker))
