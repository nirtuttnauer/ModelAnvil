"""Production startup refusal and probe sanitization."""
import json
import os
import subprocess
import sys
from unittest.mock import patch

from django.test import SimpleTestCase
from django.db import connections

from modelanvil.urls import readiness


class ProductionSettingsTests(SimpleTestCase):
    def load_settings(self, **changes):
        env = {
            'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': '.',
            'DJANGO_SECRET_KEY': 'test-only-' + 'a1b2c3d4e5f6g7h8i9j0' * 3,
            'DJANGO_ALLOWED_HOSTS': 'localhost',
            'MODELANVIL_PUBLIC_ORIGIN': 'https://localhost:8443',
            'DATABASE_ENGINE': 'postgresql', 'DATABASE_NAME': 'modelanvil',
            'DATABASE_USER': 'modelanvil', 'DATABASE_PASSWORD': 'test-only-password',
            'DATABASE_HOST': 'db',
        }
        for name, value in changes.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        return subprocess.run([sys.executable, '-c',
            'import json; from modelanvil import production as p; '
            'print(json.dumps([p.DEBUG, p.MODELANVIL_SELF_SERVICE_ACCOUNTS, '
            'p.SESSION_COOKIE_SECURE, p.CSRF_COOKIE_SECURE, p.SECURE_SSL_REDIRECT, '
            'p.CSRF_TRUSTED_ORIGINS, p.CORS_ALLOW_ALL_ORIGINS]))'],
            env=env, capture_output=True, text=True, timeout=10)

    def test_secure_defaults_and_signup_disabled_even_when_requested(self):
        result = self.load_settings(MODELANVIL_SELF_SERVICE_ACCOUNTS='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
            [False, False, True, True, True, ['https://localhost:8443'], False])

    def test_required_values_fail_closed(self):
        for name in ('DJANGO_SECRET_KEY', 'DJANGO_ALLOWED_HOSTS', 'MODELANVIL_PUBLIC_ORIGIN',
                     'DATABASE_NAME', 'DATABASE_USER', 'DATABASE_PASSWORD', 'DATABASE_HOST'):
            with self.subTest(name=name):
                result = self.load_settings(**{name: None})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)

    def test_insecure_configuration_is_refused(self):
        for changes in (
            {'DJANGO_DEBUG': '1'}, {'DJANGO_SECRET_KEY': 'short'},
            {'DJANGO_SECRET_KEY': 'a' * 60}, {'DJANGO_ALLOWED_HOSTS': '*'},
            {'DJANGO_ALLOWED_HOSTS': '.localhost'}, {'DATABASE_ENGINE': 'sqlite'},
            {'MODELANVIL_PUBLIC_ORIGIN': 'http://localhost:8443'},
            {'MODELANVIL_PUBLIC_ORIGIN': 'https://other.example'},
            {'MODELANVIL_PUBLIC_ORIGIN': 'https://localhost/path'},
            {'MODELANVIL_PUBLIC_ORIGIN': 'https://localhost?query=1'},
            {'MODELANVIL_PUBLIC_ORIGIN': 'https://user:password@localhost'},
            {'MODELANVIL_PUBLIC_ORIGIN': 'https://localhost:bad'},
        ):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.load_settings(**changes).returncode, 0)

    def test_readiness_queries_database_and_hides_failures(self):
        with patch.object(connections['default'], 'cursor') as cursor:
            self.assertEqual(readiness(None).status_code, 200)
            cursor.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT 1')
        with patch.object(connections['default'], 'cursor', side_effect=RuntimeError('private-password@db')):
            response = readiness(None)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(json.loads(response.content),
                {'status': 'degraded', 'reason': 'database_unavailable'})
