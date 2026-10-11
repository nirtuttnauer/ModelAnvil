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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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
