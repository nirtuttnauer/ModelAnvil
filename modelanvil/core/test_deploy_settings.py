"""Deploy checks refuse the development SECRET_KEY when DEBUG is off."""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
ERROR_ID = "modelanvil.E001"


class DeploySecretKeyCheckTests(SimpleTestCase):
    def run_deploy_check(self, **env_changes):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["DJANGO_SETTINGS_MODULE"] = "modelanvil.settings"
        env.pop("DJANGO_SECRET_KEY", None)
        env.pop("DJANGO_DEBUG", None)
        for name, value in env_changes.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        return subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_deploy_check_fails_when_debug_is_off_and_the_default_key_is_used(self):
        result = self.run_deploy_check(DJANGO_DEBUG="0")
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn(ERROR_ID, output)

    def test_deploy_check_accepts_a_real_key_when_debug_is_off(self):
        secret = "deploy-check-" + "a1b2c3d4e5" * 6
        result = self.run_deploy_check(DJANGO_DEBUG="0", DJANGO_SECRET_KEY=secret)
        output = result.stdout + result.stderr
        self.assertNotIn(ERROR_ID, output)
        self.assertEqual(result.returncode, 0, output)

    def test_deploy_check_allows_the_development_key_while_debug_is_on(self):
        result = self.run_deploy_check(DJANGO_DEBUG="1")
        output = result.stdout + result.stderr
        self.assertNotIn(ERROR_ID, output)
        self.assertEqual(result.returncode, 0, output)
