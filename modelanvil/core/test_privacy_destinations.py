"""Acquisition stops at destinations outside the installed allowlist, before any connection."""
import io
from unittest.mock import patch
from urllib.request import Request

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from modelanvil.core.privacy import PrivacyRefused, _Redirects, open_acquisition, require_destination
from modelanvil.core.tenancy import reset_context


@override_settings(MODELANVIL_OFFLINE=False)
class AcquisitionDestinationTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        reset_context()
        self.addCleanup(reset_context)
        for target in ('socket.create_connection', 'socket.getaddrinfo'):
            patcher = patch(target, side_effect=AssertionError('live network'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_require_destination_refuses_an_unexpected_http_host(self):
        self.assertNotIn('http://evil.example', settings.MODELANVIL_ACQUISITION_ORIGINS)
        self.assertNotIn('https://evil.example', settings.MODELANVIL_ACQUISITION_ORIGINS)
        with self.assertRaises(PrivacyRefused):
            require_destination('http://evil.example')

    def test_require_destination_refuses_a_literal_ip_outside_the_allowlist(self):
        destination = 'https://203.0.113.5'
        self.assertNotIn(destination, settings.MODELANVIL_ACQUISITION_ORIGINS)
        with self.assertRaisesMessage(PrivacyRefused, 'not allowed') as caught:
            require_destination(destination + '/weights.bin')
        self.assertIn(destination, str(caught.exception))

    def test_require_destination_accepts_an_installed_origin(self):
        allowed = 'https://huggingface.co'
        self.assertIn(allowed, settings.MODELANVIL_ACQUISITION_ORIGINS)
        self.assertEqual(require_destination(allowed + '/org/model'), allowed)

    def test_open_acquisition_refuses_unexpected_destinations_before_connecting(self):
        unexpected = (
            Request('http://evil.example/weights.bin'),
            Request('https://203.0.113.5/weights.bin'),
        )
        for request in unexpected:
            with self.subTest(url=request.full_url):
                with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('opener used')):
                    with self.assertRaises(PrivacyRefused):
                        open_acquisition(request, timeout=1)

    def test_open_acquisition_accepts_an_installed_origin_without_a_live_connection(self):
        allowed = 'https://huggingface.co/org/model'
        payload = io.BytesIO(b'weights')
        self.assertIn('https://huggingface.co', settings.MODELANVIL_ACQUISITION_ORIGINS)
        with patch('urllib.request.OpenerDirector.open', return_value=payload) as opened:
            result = open_acquisition(Request(allowed), timeout=1)
        self.assertIs(result, payload)
        self.assertEqual(opened.call_args.args[0].full_url, allowed)
        self.assertEqual(opened.call_args.kwargs['timeout'], 1)

    def test_redirect_refuses_an_unexpected_next_hop_and_accepts_an_installed_one(self):
        request = Request('https://huggingface.co/file', headers={'Range': 'bytes=0-1'})
        handler = _Redirects()
        for url in ('http://evil.example/file', 'https://203.0.113.5/file'):
            with self.subTest(url=url):
                with self.assertRaises(PrivacyRefused):
                    handler.redirect_request(request, None, 302, 'Found', {}, url)
        installed = 'https://cdn-lfs.huggingface.co/file'
        self.assertIn('https://cdn-lfs.huggingface.co', settings.MODELANVIL_ACQUISITION_ORIGINS)
        redirected = handler.redirect_request(request, None, 302, 'Found', {}, installed)
        self.assertEqual(redirected.full_url, installed)
        self.assertEqual(redirected.get_header('Range'), 'bytes=0-1')
