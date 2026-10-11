"""Contract schema versioning rules.

ModelAnvil treats every machine contract (sample envelope, adapter manifest,
job dispatch, worker heartbeat, artifact record) as a versioned document.
This module encodes the versioning rules the plan mandates:

- Versions are semver-ish ``MAJOR.MINOR.PATCH`` strings.
- ``MAJOR`` bump => breaking change; older producers may be rejected.
- ``MINOR`` bump => additive; older consumers must tolerate new fields.
- ``PATCH`` bump => backward-compatible clarification/fix.

``ContractVersion`` and ``is_compatible`` are the single implementation of
these rules so the data plane, runner registry, and API all agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

__all__ = [
    "ContractVersion",
    "parse_version",
    "is_compatible",
    "CONTRACTS",
    "ContractId",
    "supported_versions",
]


class ContractId:
    """Stable identifiers for the machine contracts in the platform."""

    SAMPLE_ENVELOPE = "sample-envelope"
    ADAPTER_MANIFEST = "adapter-manifest"
    JOB_DISPATCH = "job-dispatch"
    WORKER_HEARTBEAT = "worker-heartbeat"
    WORKER_RESULT = "worker-result"
    ARTIFACT_RECORD = "artifact-record"
    BUDGET_LEDGER = "budget-ledger"

    ALL = (
        SAMPLE_ENVELOPE,
        ADAPTER_MANIFEST,
        JOB_DISPATCH,
        WORKER_HEARTBEAT,
        WORKER_RESULT,
        ARTIFACT_RECORD,
        BUDGET_LEDGER,
    )


@dataclass(frozen=True, order=True)
class ContractVersion:
    """An ordered, comparable contract schema version."""

    major: int
    minor: int
    patch: int

    @property
    def tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(text: str) -> ContractVersion:
    """Parse a ``MAJOR.MINOR`` or ``MAJOR.MINOR.PATCH`` version string.

    Two-part versions (the form the canonical sample-envelope and
    adapter-manifest schemas use as a ``const``) are normalized to a
    patch of ``0``. Raises ``ValueError`` for malformed or non-numeric
    versions.
    """
    if not isinstance(text, str):
        raise ValueError(f"version must be a string, got {type(text)!r}")
    parts = text.strip().split(".")
    if len(parts) not in (2, 3):
        raise ValueError(
            f"version must be MAJOR.MINOR or MAJOR.MINOR.PATCH, got {text!r}"
        )
    if len(parts) == 2:
        parts.append("0")
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError as exc:  # pragma: no cover - message re-raised below
        raise ValueError(f"version components must be integers: {text!r}") from exc
    if min(major, minor, patch) < 0:
        raise ValueError(f"version components must be non-negative: {text!r}")
    return ContractVersion(major, minor, patch)


def is_compatible(
    producer: str | ContractVersion,
    consumer: str | ContractVersion,
    *,
    allow_additive: bool = True,
) -> bool:
    """Return ``True`` if a ``producer`` document can be read by ``consumer``.

    Rules:
    - Same major: compatible. If ``allow_additive`` is false, the minor must
      also match (strict mode for runners that cannot tolerate new fields).
    - Different major: incompatible (breaking change).
    """
    p = producer if isinstance(producer, ContractVersion) else parse_version(producer)
    c = consumer if isinstance(consumer, ContractVersion) else parse_version(consumer)
    if p.major != c.major:
        return False
    if not allow_additive:
        return p.minor == c.minor
    return True


#: Default minimum/maximum supported version per contract.
#:
#: ``min`` is the oldest contract version the platform still accepts;
#: ``max`` is the newest version it understands. Producers outside the
#: window are rejected at the boundary with a stable error code. Keys are
#: the string contract ids from :class:`ContractId`.
CONTRACTS: Dict[str, Dict[str, str]] = {
    ContractId.SAMPLE_ENVELOPE: {"min": "1.0", "max": "1.0"},
    ContractId.ADAPTER_MANIFEST: {"min": "1.0", "max": "1.0"},
    ContractId.JOB_DISPATCH: {"min": "1.0", "max": "1.0"},
    ContractId.WORKER_HEARTBEAT: {"min": "1.0", "max": "1.0"},
    ContractId.WORKER_RESULT: {"min": "1.0", "max": "1.0"},
    ContractId.ARTIFACT_RECORD: {"min": "1.0", "max": "1.0"},
    ContractId.BUDGET_LEDGER: {"min": "1.0", "max": "1.0"},
}


def supported_versions(contract: str) -> Tuple[ContractVersion, ContractVersion]:
    """Return the ``(min, max)`` inclusive version window for a contract id.

    Raises ``KeyError`` for an unknown contract and ``ValueError`` for a
    malformed window.
    """
    window = CONTRACTS.get(contract)
    if window is None:
        raise KeyError(f"unknown contract: {contract!r}")
    return parse_version(window["min"]), parse_version(window["max"])
