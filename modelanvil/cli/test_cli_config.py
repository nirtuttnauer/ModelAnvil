"""CLI config file mode and display redaction.

These tests write only under a temporary MODELANVIL_CONFIG path.
Failure text compares booleans so the stored token is not echoed.
"""

from __future__ import annotations

import io
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from modelanvil.cli.config import get_setting, load_config, redacted_config, save_config
from modelanvil.cli.main import main

# Placeholder stored by the tests. Do not print it.
_TOKEN = "example-token"


@contextmanager
def _temporary_config(path: Path):
    removed = {
        key: os.environ.pop(key)
        for key in list(os.environ)
        if key.startswith("MODELANVIL_")
    }
    os.environ["MODELANVIL_CONFIG"] = str(path)
    try:
        yield path
    finally:
        os.environ.pop("MODELANVIL_CONFIG", None)
        os.environ.update(removed)


class CliConfigModeTests(SimpleTestCase):
    def test_save_config_mode_is_owner_read_write(self):
        self.assertEqual(os.name, "posix")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "nested" / "config.json"
            previous_umask = os.umask(0)
            try:
                with _temporary_config(cfg):
                    save_config({"url": "http://127.0.0.1:9", "token": _TOKEN})
                    created = stat.S_IMODE(cfg.stat().st_mode)
                    cfg.chmod(0o644)
                    replaced_before = stat.S_IMODE(cfg.stat().st_mode)
                    save_config({"url": "http://127.0.0.1:9", "token": _TOKEN})
                    replaced = stat.S_IMODE(cfg.stat().st_mode)
            finally:
                os.umask(previous_umask)
            self.assertEqual(created, 0o600)
            self.assertEqual(replaced_before, 0o644)
            self.assertEqual(replaced, 0o600)

    def test_save_config_uses_temporary_path_not_home(self):
        home_file = Path.home() / ".modelanvil" / "config.json"
        before = home_file.stat().st_mtime_ns if home_file.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            with _temporary_config(cfg):
                save_config({"url": "http://127.0.0.1:9", "token": _TOKEN})
                self.assertEqual(Path(os.environ["MODELANVIL_CONFIG"]), cfg)
                self.assertTrue(cfg.is_file())
            # On macOS the temp dir is under /var, a symlink to /private/var; compare resolved paths.
            self.assertEqual(os.path.commonpath([os.path.realpath(tmp), str(cfg.resolve())]), os.path.realpath(tmp))
        after = home_file.stat().st_mtime_ns if home_file.exists() else None
        self.assertEqual(before, after)

    def test_load_config_and_get_setting_return_the_stored_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            with _temporary_config(cfg):
                save_config({"url": "http://127.0.0.1:9", "token": _TOKEN, "tenant": "local"})
                loaded = load_config()
                setting = get_setting("token")
                self.assertEqual(loaded.get("url"), "http://127.0.0.1:9")
                self.assertEqual(loaded.get("tenant"), "local")
                self.assertEqual(loaded.get("token") == _TOKEN, True)
                self.assertEqual(setting == _TOKEN, True)
                raw = cfg.read_text(encoding="utf-8")
                self.assertEqual(_TOKEN in raw, True)


class CliConfigRedactionTests(SimpleTestCase):
    def test_redacted_config_never_includes_the_raw_token(self):
        source = {
            "url": "http://127.0.0.1:9",
            "token": _TOKEN,
            "password": _TOKEN,
            "nested": {"api_token": _TOKEN, "name": "dev"},
            "notes": ["keep", {"refresh-token": _TOKEN}],
        }
        redacted = redacted_config(source)
        encoded = json.dumps(redacted)
        self.assertEqual(_TOKEN in encoded, False)
        self.assertEqual(redacted["token"], "***")
        self.assertEqual(redacted["password"], "***")
        self.assertEqual(redacted["nested"]["api_token"], "***")
        self.assertEqual(redacted["nested"]["name"], "dev")
        self.assertEqual(redacted["notes"][0], "keep")
        self.assertEqual(redacted["notes"][1]["refresh-token"], "***")
        self.assertEqual(source["token"] == _TOKEN, True)
        self.assertEqual(source["nested"]["api_token"] == _TOKEN, True)
        self.assertIsNot(redacted, source)
        self.assertIsNot(redacted["nested"], source["nested"])

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            with _temporary_config(cfg):
                save_config({"url": "http://127.0.0.1:9", "token": _TOKEN})
                from_file = redacted_config()
                self.assertEqual(from_file["token"], "***")
                self.assertEqual(from_file["url"], "http://127.0.0.1:9")
                self.assertEqual(_TOKEN in json.dumps(from_file), False)
                self.assertEqual(load_config().get("token") == _TOKEN, True)
                self.assertEqual(get_setting("token") == _TOKEN, True)

    def test_config_show_prints_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            with _temporary_config(cfg):
                save_config({"url": "http://127.0.0.1:9", "token": _TOKEN, "tenant": "local"})
                text_out = io.StringIO()
                with patch("sys.stdout", text_out):
                    text_code = main(["config", "show"])
                text = text_out.getvalue()
                json_out = io.StringIO()
                with patch("sys.stdout", json_out):
                    json_code = main(["--json", "config", "show"])
                payload = json.loads(json_out.getvalue())
            self.assertEqual(text_code, 0)
            self.assertEqual(json_code, 0)
            self.assertIn("token: ***", text)
            self.assertIn("url: http://127.0.0.1:9", text)
            self.assertEqual(_TOKEN in text, False)
            self.assertEqual(payload["token"], "***")
            self.assertEqual(payload["url"], "http://127.0.0.1:9")
            self.assertEqual(payload["tenant"], "local")
            self.assertEqual(_TOKEN in json.dumps(payload), False)
