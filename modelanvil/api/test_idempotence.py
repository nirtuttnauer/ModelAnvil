"""Scoped replay for JSON writes that send Idempotency-Key."""
from django.test import TestCase
from rest_framework import serializers
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from modelanvil.api.idempotence import idempotent_write
from modelanvil.core.models import IdempotencyKey
from modelanvil.core.tenancy import reset_context, set_active_project, set_active_tenant
from modelanvil.identity.models import Project, Team, Tenant, User


class IdempotentWriteTests(TestCase):
    path = '/api/v1/resources/'

    def setUp(self):
        reset_context()
        self.addCleanup(reset_context)
        self.tenant = Tenant.objects.create(slug='idem', name='Idem')
        self.user = User.objects.create_user('writer@example.com', 'unused-password')
        team = Team.objects.create(tenant_id=self.tenant.pk, slug='team', name='Team')
        self.project = Project.objects.create(
            tenant_id=self.tenant.pk, team=team, slug='one', name='One',
        )
        set_active_tenant(self.tenant.pk)
        set_active_project(self.project.pk)
        self.factory = APIRequestFactory()
        self.calls = 0

    def request(self, body, key=None, *, method='POST', path=None):
        extra = {}
        if key is not None:
            extra['HTTP_IDEMPOTENCY_KEY'] = key
        django_request = getattr(self.factory, method.lower())(
            path or self.path, body, format='json', **extra,
        )
        request = Request(django_request, parsers=[JSONParser()])
        request.user = self.user
        return request

    def write(self, status=201, body=None):
        payload = {'id': 'row-1', 'name': 'alpha'} if body is None else body

        def _write():
            self.calls += 1
            return Response(payload, status=status)

        return _write

    def test_missing_key_calls_write_and_stores_nothing(self):
        response = idempotent_write(self.request({'name': 'alpha'}), self.write())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data, {'id': 'row-1', 'name': 'alpha'})
        self.assertEqual(self.calls, 1)
        self.assertFalse(IdempotencyKey.all_objects.exists())

        blank = idempotent_write(self.request({'name': 'beta'}, key='   '), self.write(body={'id': 'row-2'}))
        self.assertEqual(blank.status_code, 201)
        self.assertEqual(blank.data, {'id': 'row-2'})
        self.assertEqual(self.calls, 2)
        self.assertFalse(IdempotencyKey.all_objects.exists())

    def test_successful_write_stores_status_body_and_completion(self):
        response = idempotent_write(
            self.request({'name': 'alpha', 'n': 2}, key='store-me'),
            self.write(status=201),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.calls, 1)
        record = IdempotencyKey.all_objects.get()
        self.assertEqual(record.key, 'store-me')
        self.assertEqual(record.http_method, 'POST')
        self.assertEqual(record.path, self.path)
        self.assertEqual(record.tenant_id, self.tenant.pk)
        self.assertEqual(record.principal, f'{self.user.pk}:{self.project.pk}')
        self.assertEqual(record.response_status, 201)
        self.assertEqual(record.response_body, {'id': 'row-1', 'name': 'alpha'})
        self.assertIsNotNone(record.completed_at)

    def test_replay_returns_stored_status_and_body_without_calling_write(self):
        body = {'name': 'alpha', 'n': 2}
        first = idempotent_write(self.request(body, key='same'), self.write(status=200))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.calls, 1)

        replay = idempotent_write(
            self.request({'n': 2, 'name': 'alpha'}, key='same'),
            self.write(status=500, body={'id': 'should-not-run'}),
        )
        self.assertEqual(self.calls, 1)
        self.assertEqual(replay.status_code, first.status_code)
        self.assertEqual(replay.data, first.data)
        self.assertEqual(IdempotencyKey.all_objects.count(), 1)

    def test_same_key_with_different_body_returns_409(self):
        idempotent_write(self.request({'name': 'alpha'}, key='same'), self.write())
        conflict = idempotent_write(
            self.request({'name': 'beta'}, key='same'),
            self.write(body={'id': 'should-not-run'}),
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(
            conflict.data,
            {'detail': 'Idempotency key already used with different inputs.'},
        )
        self.assertEqual(self.calls, 1)
        record = IdempotencyKey.all_objects.get()
        self.assertEqual(record.response_body, {'id': 'row-1', 'name': 'alpha'})

    def test_key_longer_than_128_characters_is_rejected(self):
        with self.assertRaises(serializers.ValidationError) as caught:
            idempotent_write(self.request({'name': 'alpha'}, key='k' * 129), self.write())
        self.assertIn('128', str(caught.exception))
        self.assertEqual(self.calls, 0)
        self.assertFalse(IdempotencyKey.all_objects.exists())

        accepted = idempotent_write(self.request({'name': 'alpha'}, key='k' * 128), self.write())
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(self.calls, 1)
        self.assertEqual(IdempotencyKey.all_objects.get().key, 'k' * 128)
