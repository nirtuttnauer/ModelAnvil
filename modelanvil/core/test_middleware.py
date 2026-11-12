"""RequestIdMiddleware assigns one id and does not reflect a malformed header."""
import json
import uuid

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from modelanvil.core import tenancy
from modelanvil.core.middleware import ExceptionMiddleware, RequestIdMiddleware

WELL_FORMED = '550e8400-e29b-41d4-a716-446655440000'


class RequestIdMiddlewareTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        tenancy.reset_context()
        self.addCleanup(tenancy.reset_context)

    def _cycle(self, header=None, *, explode=False):
        seen = {}

        def get_response(request):
            seen['request_id'] = request.modelanvil_request_id
            seen['bound'] = tenancy.get_active_request()
            if explode:
                raise RuntimeError('boom')
            return HttpResponse('ok')

        inner = ExceptionMiddleware(get_response) if explode else get_response
        middleware = RequestIdMiddleware(inner)
        extra = {}
        if header is not None:
            extra['HTTP_X_REQUEST_ID'] = header
        request = self.factory.get('/health', **extra)
        response = middleware(request)
        return request, response, seen

    def _assert_canonical(self, value):
        self.assertIsInstance(value, str)
        self.assertTrue(value)
        self.assertNotIn('\r', value)
        self.assertNotIn('\n', value)
        parsed = uuid.UUID(value)
        self.assertEqual(str(parsed), value)
        return parsed

    def test_missing_header_assigns_a_nonempty_id(self):
        request, response, seen = self._cycle()
        request_id = request.modelanvil_request_id
        parsed = self._assert_canonical(request_id)
        self.assertEqual(parsed.version, 7)
        self.assertEqual(response['X-Request-Id'], request_id)
        self.assertEqual(seen['request_id'], request_id)
        self.assertIs(seen['bound'], request)

        again, again_response, _ = self._cycle()
        self.assertNotEqual(again.modelanvil_request_id, request_id)
        self.assertEqual(again_response['X-Request-Id'], again.modelanvil_request_id)

    def test_well_formed_header_is_reused(self):
        request, response, seen = self._cycle(WELL_FORMED)
        self.assertEqual(request.modelanvil_request_id, WELL_FORMED)
        self.assertEqual(response['X-Request-Id'], WELL_FORMED)
        self.assertEqual(seen['request_id'], WELL_FORMED)
        self.assertIs(seen['bound'], request)
        self._assert_canonical(response['X-Request-Id'])

    def test_uppercase_header_reuses_the_same_uuid(self):
        inbound = WELL_FORMED.upper()
        request, response, _seen = self._cycle(inbound)
        self.assertEqual(request.modelanvil_request_id, WELL_FORMED)
        self.assertEqual(response['X-Request-Id'], WELL_FORMED)
        self.assertEqual(uuid.UUID(response['X-Request-Id']), uuid.UUID(inbound))

    def test_empty_header_is_ignored(self):
        request, response, seen = self._cycle('')
        parsed = self._assert_canonical(request.modelanvil_request_id)
        self.assertEqual(parsed.version, 7)
        self.assertNotEqual(request.modelanvil_request_id, '')
        self.assertEqual(response['X-Request-Id'], request.modelanvil_request_id)
        self.assertEqual(seen['request_id'], request.modelanvil_request_id)

    def test_crlf_header_is_not_reflected(self):
        payloads = (
            '\r\n',
            '\n',
            '\r',
            'evil\r\nX-Injected: yes',
            WELL_FORMED + '\r\n',
            WELL_FORMED + '\nX-Injected: yes',
            '\r\n' + WELL_FORMED,
        )
        for raw in payloads:
            with self.subTest(raw=raw):
                request, response, seen = self._cycle(raw)
                request_id = request.modelanvil_request_id
                parsed = self._assert_canonical(request_id)
                self.assertEqual(parsed.version, 7)
                self.assertEqual(response['X-Request-Id'], request_id)
                self.assertEqual(seen['request_id'], request_id)
                self.assertNotEqual(response['X-Request-Id'], raw)
                self.assertNotIn('evil', response['X-Request-Id'])
                self.assertNotIn('Injected', response['X-Request-Id'])
                if WELL_FORMED in raw:
                    self.assertNotEqual(response['X-Request-Id'], WELL_FORMED)

    def test_non_uuid_header_is_not_reflected(self):
        raw = 'super-secret-token-value'
        request, response, _seen = self._cycle(raw)
        parsed = self._assert_canonical(request.modelanvil_request_id)
        self.assertEqual(parsed.version, 7)
        self.assertEqual(response['X-Request-Id'], request.modelanvil_request_id)
        self.assertNotIn(raw, response['X-Request-Id'])

    def test_generated_id_does_not_embed_credentials(self):
        token = 'super-secret-token-value'
        request = self.factory.get('/health', HTTP_AUTHORIZATION=f'Bearer {token}')
        seen = {}

        def get_response(incoming):
            seen['request_id'] = incoming.modelanvil_request_id
            return HttpResponse('ok')

        response = RequestIdMiddleware(get_response)(request)
        request_id = response['X-Request-Id']
        parsed = self._assert_canonical(request_id)
        self.assertEqual(parsed.version, 7)
        self.assertEqual(seen['request_id'], request_id)
        self.assertNotIn(token, request_id)
        self.assertNotIn('Bearer', request_id)
        self.assertNotIn('secret', request_id)

    def test_error_response_keeps_the_request_id(self):
        for header in (None, WELL_FORMED, '', 'evil\r\nX-Injected: yes'):
            with self.subTest(header=header):
                request, response, _seen = self._cycle(header, explode=True)
                request_id = request.modelanvil_request_id
                self._assert_canonical(request_id)
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response['X-Request-Id'], request_id)
                self.assertNotIn('\r', response['X-Request-Id'])
                self.assertNotIn('\n', response['X-Request-Id'])
                if header is not None and (header == '' or '\r' in header or '\n' in header):
                    self.assertNotEqual(response['X-Request-Id'], header)
                body = json.loads(response.content)
                self.assertEqual(body['error']['request_id'], request_id)
