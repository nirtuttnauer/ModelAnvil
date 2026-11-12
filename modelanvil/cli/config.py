"""CLI configuration management.

Supports environment variables and file-based configuration (~/.modelanvil/config.json).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path.home() / ".modelanvil"
CONFIG_FILE = CONFIG_DIR / "config.json"
REDACTED = "***"
# Compact alphanumeric markers. "api_key" and "api-key" both become "apikey".
_SECRET_MARKERS = ("token", "password", "passwd", "secret", "apikey", "credential")


def get_config_path() -> Path:
    custom = os.environ.get("MODELANVIL_CONFIG")
    if custom:
        return Path(custom)
    return CONFIG_FILE


def load_config() -> Dict[str, Any]:
    path = get_config_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: Dict[str, Any]) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.open applies umask and leaves an existing file's mode unchanged.
    # chmod forces owner read/write only on POSIX after the replace.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    handle = os.fdopen(descriptor, "w", encoding="utf-8")
    try:
        json.dump(data, handle, indent=2)
        handle.flush()
    finally:
        handle.close()
        if os.name == "posix":
            os.chmod(path, 0o600)


def _is_secret_key(key: Any) -> bool:
    compact = "".join(ch for ch in str(key).lower() if ch.isalnum())
    return any(marker in compact for marker in _SECRET_MARKERS)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(key):
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def redacted_config(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a copy with token and password-like values replaced by '***'."""
    source = load_config() if data is None else data
    if not isinstance(source, dict):
        return {}
    redacted = _redact(source)
    return redacted if isinstance(redacted, dict) else {}


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    # 1. Environment variable
    env_key = f"MODELANVIL_{key.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]
    # 2. Config file
    cfg = load_config()
    return cfg.get(key, default)


def set_setting(key: str, value: str) -> None:
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
