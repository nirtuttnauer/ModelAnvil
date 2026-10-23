"""Real HTTP membership/invitation lifecycle and least-privilege review checks."""
import json
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.core.models import AuditEvent
from modelanvil.core.tenancy import reset_context
from modelanvil.identity.models import AccountAction, ApiKey, Membership, Project, Role, User, generate_api_key


@override_settings(MODELANVIL_SELF_SERVICE_ACCOUNTS=True)
class TeamAccessTests(TestCase):
    def setUp(self):
        reset_context(); cache.clear()
        self.owner = APIClient(enforce_csrf_checks=True)
        self.owner.get('/api/v1/accounts/status/')
        result = self.post(self.owner, '/api/v1/accounts/signup/', {
            'email': 'owner@example.invalid', 'name': 'Owner', 'password': 'owner-testing-password-937!'})
        self.assertEqual(result.status_code, 200)
        self.project = Project.all_objects.get()
        self.headers = {'HTTP_X_PROJECT_ID': str(self.project.pk)}

    def post(self, client, path, body, **headers):
        return client.post(path, body, format='json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value, **headers)

    def invite(self, email='reviewer@example.invalid'):
        result = self.post(self.owner, '/api/v1/accounts/invitations/', {'email': email}, **self.headers)
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data['role'], Role.REVIEWER)
        self.assertEqual(result['Cache-Control'], 'no-store')
        return result.data['invite_code']

    def guest(self):
        client = APIClient(enforce_csrf_checks=True); client.get('/api/v1/accounts/status/'); return client

    def accept(self, client, code, email='reviewer@example.invalid'):
        return self.post(client, '/api/v1/accounts/invitations/accept/', {
            'email': email, 'name': 'Reviewer', 'password': 'reviewer-testing-password-937!', 'code': code})

    def test_invitation_wrong_account_expiry_revoke_replay_and_secret_omission(self):
        secret = self.invite()
        action = AccountAction.objects.get(purpose='invitation')
        self.assertNotEqual(action.secret_hash, secret)
        self.assertEqual(self.accept(self.guest(), secret, 'wrong@example.invalid').status_code, 400)
        listing = self.owner.get('/api/v1/accounts/invitations/').data
        self.assertNotIn(secret, json.dumps(listing, default=str))
        self.assertNotIn('secret_hash', json.dumps(listing, default=str))
        action.expires_at = timezone.now() - timedelta(seconds=1); action.save()
        self.assertEqual(self.accept(self.guest(), secret).status_code, 400)
        secret = self.invite(); action = AccountAction.objects.latest('created_at')
        response = self.owner.delete(f'/api/v1/accounts/invitations/{action.pk}/', HTTP_X_CSRFTOKEN=self.owner.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.accept(self.guest(), secret).status_code, 400)
        secret = self.invite(); guest = self.guest()
        self.assertEqual(self.accept(guest, secret).status_code, 200)
        self.assertEqual(self.accept(self.guest(), secret).status_code, 400)
        self.assertNotIn(secret, json.dumps(list(AuditEvent.all_objects.values()), default=str))
        self.assertEqual(self.owner.get('/api/v1/accounts/invitations/').data['invitations'][0]['status'], 'accepted')

    def test_reviewer_submits_labels_but_cannot_launch_manage_or_publish(self):
        code = self.invite(); guest = self.guest(); self.assertEqual(self.accept(guest, code).status_code, 200)
        campaign = self.post(self.owner, '/api/v1/labeling-campaigns/', {'name': 'Reviews', 'kind': 'classification', 'classes': ['positive', 'negative']}, **self.headers)
        self.assertEqual(campaign.status_code, 201, campaign.data)
        cid = campaign.data['campaign_id']
        batch = self.post(self.owner, f'/api/v1/labeling-campaigns/{cid}/batches/', {'samples': [{'id': 'source-1', 'text': 'Good'}]}, **self.headers)
        self.assertEqual(batch.status_code, 201, batch.data)
        bid = batch.data['batch_id']
        tasks = guest.get(f'/api/v1/labeling-batches/{bid}/tasks/', **self.headers)
        self.assertEqual(tasks.status_code, 200)
        task = tasks.data['results'][0]
        review = self.post(guest, f'/api/v1/annotation-tasks/{task["task_id"]}/review/', {'decision': 'corrected', 'human_label': {'label': 'positive'}, 'expected_revision': 1}, **self.headers)
        self.assertEqual(review.status_code, 201, review.data)
        self.assertEqual(review.data['latest_review']['human_label'], {'label': 'positive'})
        blocked = [('/api/v1/labeling-campaigns/', {}), (f'/api/v1/labeling-batches/{bid}/close/', {}),
            ('/api/v1/accounts/invitations/', {'email': 'no@example.invalid'}), ('/api/v1/api-keys/', {'name': 'Escalate', 'role': 'owner'}),
            ('/api/v1/memberships/', {}), ('/api/v1/training-runs/', {}), ('/api/v1/evaluation-runs/', {}), ('/api/v1/serving-endpoints/', {}), ('/api/v1/releases/', {})]
        for path, body in blocked:
            with self.subTest(path=path): self.assertEqual(self.post(guest, path, body, **self.headers).status_code, 403)
        self.assertEqual(guest.get('/api/v1/accounts/invitations/').status_code, 403)
        self.assertEqual(guest.get('/api/v1/accounts/access/').data['role'], 'reviewer')

    def test_membership_removal_revokes_existing_browser_and_bearer_credentials(self):
        code = self.invite(); guest = self.guest(); self.assertEqual(self.accept(guest, code).status_code, 200)
        member = Membership.objects.get(user__email='reviewer@example.invalid')
        secret, hashed = generate_api_key()
        key = ApiKey.objects.create(tenant=member.tenant, created_by=member.user, role=Role.ENGINEER, secret_hash=hashed, name='Existing personal key')
        bearer = APIClient(); bearer.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        # Existing keys cannot outlive a user's role or membership.
        self.assertEqual(bearer.get('/api/v1/accounts/access/').data['role'], Role.REVIEWER)
        self.assertEqual(bearer.post('/api/v1/training-runs/', {}, format='json').status_code, 403)
        response = self.owner.delete(f'/api/v1/memberships/{member.pk}/', HTTP_X_CSRFTOKEN=self.owner.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(guest.get('/api/v1/accounts/status/').data['authenticated'])
        self.assertEqual(guest.get('/api/v1/projects/').status_code, 401)
        self.assertEqual(bearer.get('/api/v1/projects/').status_code, 401)
        key.refresh_from_db(); self.assertFalse(key.is_active)
        self.assertEqual(self.post(guest, '/api/v1/accounts/signin/', {'email': 'reviewer@example.invalid', 'password': 'reviewer-testing-password-937!'}).status_code, 401)

    def test_raw_membership_deletion_still_fails_closed_for_personal_key(self):
        self.invite(); guest = self.guest()
        member = Membership.objects.get(user__email='owner@example.invalid')
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=member.tenant, created_by=member.user, role=Role.OWNER, secret_hash=hashed, name='Personal key')
        member.delete()
        bearer = APIClient(); bearer.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(bearer.get('/api/v1/projects/').status_code, 401)

    def test_invitation_cross_tenant_revoke_and_view_are_denied(self):
        self.invite(); action = AccountAction.objects.get(purpose='invitation')
        other = self.guest()
        self.assertEqual(self.post(other, '/api/v1/accounts/signup/', {'email': 'other@example.invalid', 'password': 'other-testing-password-937!'}).status_code, 200)
        self.assertEqual(other.get('/api/v1/accounts/invitations/').data['invitations'], [])
        self.assertEqual(other.delete(f'/api/v1/accounts/invitations/{action.pk}/', HTTP_X_CSRFTOKEN=other.cookies['csrftoken'].value).status_code, 404)

    def test_invitation_methods_fail_closed_without_server_errors(self):
        self.invite(); action = AccountAction.objects.get(purpose='invitation')
        self.assertEqual(self.owner.get(f'/api/v1/accounts/invitations/{action.pk}/').status_code, 405)
        self.assertEqual(self.owner.delete('/api/v1/accounts/invitations/', HTTP_X_CSRFTOKEN=self.owner.cookies['csrftoken'].value).status_code, 405)

    def test_engineer_cannot_mint_owner_key_and_owner_cannot_remove_self(self):
        member = Membership.objects.get(user__email='owner@example.invalid')
        self.assertEqual(self.owner.delete(f'/api/v1/memberships/{member.pk}/', HTTP_X_CSRFTOKEN=self.owner.cookies['csrftoken'].value).status_code, 400)
        member.role = Role.ENGINEER; member.save()
        response = self.post(self.owner, '/api/v1/api-keys/', {'name': 'Escalate', 'role': 'owner'})
        self.assertEqual(response.status_code, 400)


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, tag
from modelanvil.identity.models import Team, Tenant


@tag('pg')
@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks')
class ConcurrentInvitationTests(TransactionTestCase):
    def setUp(self):
        reset_context(); cache.clear()
        self.tenant = Tenant.objects.create(slug='concurrent-invites', name='Team')
        team = Team.all_objects.create(tenant_id=self.tenant.pk, slug='team', name='Team')
        Project.all_objects.create(tenant_id=self.tenant.pk, team=team, slug='project', name='Project')
        self.secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name='Owner service key', role=Role.OWNER, secret_hash=hashed)

    def test_simultaneous_issue_allows_only_one_pending_invitation(self):
        barrier = Barrier(2)
        def issue(number):
            close_old_connections()
            try:
                client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.secret}')
                barrier.wait(timeout=10)
                return client.post('/api/v1/accounts/invitations/', {'email': f'parallel-{number}@example.invalid'}, format='json').status_code
            finally:
                reset_context(); close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(issue, [1, 2]))
        self.assertEqual(sorted(statuses), [201, 400])
        self.assertEqual(AccountAction.objects.filter(tenant=self.tenant, purpose='invitation', used_at__isnull=True, revoked_at__isnull=True).count(), 1)
