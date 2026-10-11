"""Canonical JSON Schema documents, loaded from the engineering pack.

The JSON Schema files under ``docs/engineering/schemas/`` are the
source of truth. This module loads them into memory once and exposes them
by name so the data plane, runner registry, and API validate against the
exact same documents the plan specifies.

A copy of each schema is also vendored under ``contracts/schemas/`` for
use in deployments where the docs tree is not shipped; the loader prefers
the vendored copy when present and falls back to the docs tree.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

__all__ = ["load_schema", "schema_name", "SCHEMA_NAMES", "schema_path"]

#: Name -> (contract id, filename) for the canonical schemas.
SCHEMA_NAMES: Dict[str, Dict[str, str]] = {
    "sample-envelope": {
        "contract": "sample-envelope",
        "file": "sample-envelope.schema.json",
    },
    "adapter-manifest": {
        "contract": "adapter-manifest",
        "file": "adapter-manifest.schema.json",
    },
    "openapi": {
        "contract": "openapi",
        "file": "openapi.json",
    },
}

_PACKAGE_DIR = Path(__file__).resolve().parent


def _candidate_paths(name: str) -> List[Path]:
    meta = SCHEMA_NAMES[name]
    vendored = _PACKAGE_DIR / "schemas" / meta["file"]
    docs = _PACKAGE_DIR.parent / "docs" / "engineering" / "schemas" / meta["file"]
    return [vendored, docs]


def schema_path(name: str) -> Path:
    """Return the first existing path for a named schema, else raise."""
    if name not in SCHEMA_NAMES:
        known = ", ".join(sorted(SCHEMA_NAMES))
        raise KeyError(f"unknown schema {name!r}; known: {known}")
    for path in _candidate_paths(name):
        if path.exists():
            return path
    raise FileNotFoundError(
        f"no schema file found for {name!r} in "
        + " or ".join(str(p) for p in _candidate_paths(name))
    )


def schema_name(name: str) -> str:
    """Return the contract identifier associated with schema ``name``."""
    if name not in SCHEMA_NAMES:
        raise KeyError(f"unknown schema {name!r}")
    return SCHEMA_NAMES[name]["contract"]


@lru_cache(maxsize=16)
def _load_cached(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_schema(name: str) -> Dict[str, Any]:
    """Load and return the canonical JSON Schema for ``name``.

    Results are cached in memory; subsequent calls for the same schema
    return the cached dictionary without re-reading the filesystem.
    """
    path = schema_path(name)
    return _load_cached(str(path))
