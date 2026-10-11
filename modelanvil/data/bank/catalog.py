"""Open Dataset Bank catalog loader, manifest validator, and preflight engine (WP-06 / TECH-010)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from django.core.exceptions import ValidationError


@dataclass
class LicenseObligations:
    spdx_expression: str
    retain_license_and_notices: bool = True
    share_alike: bool = False
    gated: bool = False
    commercial_allowed: bool = True
    attribution_required: bool = True
    evidence_urls: list[str] = field(default_factory=list)
    notes: str = ""


UNQUALIFIED_REASON = (
    "No acquisition connector is implemented for this source and no upstream bytes were ever "
    "fetched for it. A license declaration alone does not qualify a source for acquisition."
)


@dataclass
class AcquisitionCard:
    """Acquisition qualification evidence for one source.

    ``status`` is ``qualified`` only when a connector has actually fetched
    upstream bytes at a pinned immutable revision and verified them. Every
    other source stays explicitly unavailable with a published reason.
    """

    status: str = "unqualified"
    qualified_on: str = ""
    connector: str = ""
    upstream_repository: str = ""
    pinned_revision: str = ""
    revision_resolved_on: str = ""
    revision_selection: str = ""
    qualified_revisions: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)
    license_paths: list[str] = field(default_factory=list)
    record_selection: str = ""
    record_limit: int = 0
    record_limit_max: int = 0
    preview_limit: int = 0
    measured_upstream_records: Optional[int] = None
    measured_upstream_bytes: Optional[int] = None
    measured_selected_records: Optional[int] = None
    measured_selected_bytes: Optional[int] = None
    measured_transfer_seconds: Optional[int] = None
    measurement_environment: str = ""
    verified_record_digests: bool = False
    blocked_reason: str = UNQUALIFIED_REASON
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified(self) -> bool:
        return self.status == "qualified" and bool(self.pinned_revision)

    def revision_is_qualified(self, revision: str) -> bool:
        return self.qualified and revision in self.qualified_revisions


@dataclass
class SourceCard:
    id: str
    name: str
    category: str
    source_kind: str
    description: str
    source_url: str
    modalities: list[str]
    use_cases: list[str]
    license_expression: str
    obligations: LicenseObligations
    eligibility: str  # "eligible", "opt_in_required", "gated_required", "ineligible"
    connector_status: str
    size_bytes: Optional[int]
    record_count: Optional[int]
    download_enabled: bool = True
    rejection_reason: str = ""
    upstream_checked_on: Optional[str] = None
    fetch: dict[str, Any] = field(default_factory=dict)
    preparation: dict[str, Any] = field(default_factory=dict)
    acquisition: AcquisitionCard = field(default_factory=AcquisitionCard)

    @property
    def is_size_measured(self) -> bool:
        return self.size_bytes is not None and self.size_bytes > 0

    @property
    def acquisition_available(self) -> bool:
        """License eligibility and acquisition qualification are separate claims."""
        return self.download_enabled and self.acquisition.qualified


@dataclass
class PresetCard:
    id: str
    title: str
    description: str
    tasks: list[str]
    modalities: list[str]
    source_ids: list[str]
    preparation_recipe: str
    profile: str = "permissive_and_attribution"


@dataclass
class HeldCandidateCard:
    name: str
    source_url: str
    reason: str
    checked_on: str
    download_enabled: bool = False


class DatasetBankCatalog:
    """Validated catalog of dataset presets and candidate manifests."""

    def __init__(
        self,
        *,
        schema_version: str,
        catalog_status: str,
        policy: dict[str, Any],
        sources: list[SourceCard],
        presets: list[PresetCard],
        held_candidates: list[HeldCandidateCard],
        checked_on: str = "",
    ) -> None:
        self.schema_version = schema_version
        self.catalog_status = catalog_status
        self.policy = policy
        self.checked_on = checked_on
        self._sources = {s.id: s for s in sources}
        self._presets = {p.id: p for p in presets}
        self.held_candidates = held_candidates

    @classmethod
    def load_from_file(cls, path: str | Path | None = None) -> DatasetBankCatalog:
        if path is None:
            # Default to repo root catalog/dataset-presets.json
            repo_root = Path(__file__).resolve().parent.parent.parent.parent
            path = repo_root / "catalog" / "dataset-presets.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetBankCatalog:
        schema_version = data.get("schema_version", "1.0")
        catalog_status = data.get("catalog_status", "draft")
        policy = data.get("policy", {})
        checked_on = str(data.get("checked_on", ""))

        sources: list[SourceCard] = []
        for raw_s in data.get("sources", []):
            card = cls._parse_source_card(raw_s)
            sources.append(card)

        presets: list[PresetCard] = []
        for raw_p in data.get("presets", []):
            preset = PresetCard(
                id=raw_p.get("id", ""),
                title=raw_p.get("name") or raw_p.get("title") or raw_p.get("id", ""),
                description=raw_p.get("description", ""),
                tasks=raw_p.get("tasks", []),
                modalities=raw_p.get("modalities", []),
                source_ids=raw_p.get("source_ids", []),
                preparation_recipe=raw_p.get("preparation_recipe", "default"),
                profile=raw_p.get("profile", "permissive_and_attribution"),
            )
            presets.append(preset)

        held_candidates: list[HeldCandidateCard] = []
        for raw_h in data.get("held_candidates", []):
            held_candidates.append(
                HeldCandidateCard(
                    name=raw_h.get("name", ""),
                    source_url=raw_h.get("source_url", ""),
                    reason=raw_h.get("reason", ""),
                    checked_on=raw_h.get("checked_on", ""),
                    download_enabled=False,
                )
            )

        return cls(
            schema_version=schema_version,
            catalog_status=catalog_status,
            policy=policy,
            checked_on=checked_on,
            sources=sources,
            presets=presets,
            held_candidates=held_candidates,
        )

    @classmethod
    def _parse_source_card(cls, raw: dict[str, Any]) -> SourceCard:
        lic_data = raw.get("license") or {}
        spdx = str(lic_data.get("spdx_expression") or "").strip()
        share_alike = bool(lic_data.get("share_alike", False))
        is_gated = (
            "gated" in str(raw.get("connector_status", "")).lower()
            or "credentials" in str(raw.get("description", "")).lower()
            or "xlam" in str(raw.get("id", "")).lower()
        )

        obligations = LicenseObligations(
            spdx_expression=spdx,
            retain_license_and_notices=bool(lic_data.get("retain_license_and_notices", True)),
            share_alike=share_alike,
            gated=is_gated,
            evidence_urls=lic_data.get("evidence_urls", []),
            notes=str(lic_data.get("notes", "")),
        )

        # Policy validation
        download_enabled = True
        rejection_reason = ""
        eligibility = "eligible"

        spdx_lower = spdx.lower()
        if not spdx or spdx_lower in ("unclear", "unknown", "proprietary"):
            download_enabled = False
            rejection_reason = "Unclear or missing declared dataset license."
            eligibility = "ineligible"
        elif any(indicator in spdx_lower for indicator in ("-nc", "noncommercial", "non-commercial")) or re.search(r"\b(nc)\b", spdx_lower):
            download_enabled = False
            rejection_reason = "Noncommercial-only licenses are excluded from the open bank."
            eligibility = "ineligible"
        elif any(indicator in spdx_lower for indicator in ("-nd", "no-derivatives")) or re.search(r"\b(nd)\b", spdx_lower):
            download_enabled = False
            rejection_reason = "No-derivatives licenses are excluded from the open bank."
            eligibility = "ineligible"
        elif share_alike:
            eligibility = "opt_in_required"
        elif is_gated:
            eligibility = "gated_required"

        return SourceCard(
            id=raw.get("id", ""),
            name=raw.get("name", ""),
            category=raw.get("category", ""),
            source_kind=raw.get("source_kind", ""),
            description=raw.get("description", ""),
            source_url=raw.get("source_url", ""),
            modalities=raw.get("modalities", []),
            use_cases=raw.get("use_cases", []),
            license_expression=spdx,
            obligations=obligations,
            eligibility=eligibility,
            connector_status=raw.get("connector_status", ""),
            size_bytes=raw.get("size_bytes"),
            record_count=raw.get("record_count"),
            download_enabled=download_enabled,
            rejection_reason=rejection_reason,
            upstream_checked_on=lic_data.get("upstream_declaration_checked_on"),
            fetch=raw.get("fetch", {}),
            preparation=raw.get("preparation", {}),
            acquisition=cls._parse_acquisition_card(raw.get("acquisition") or {}),
        )

    @staticmethod
    def _parse_acquisition_card(raw: dict[str, Any]) -> AcquisitionCard:
        card = AcquisitionCard()
        card.status = str(raw.get("status") or "unqualified")
        card.qualified_on = str(raw.get("qualified_on") or "")
        card.connector = str(raw.get("connector") or "")
        card.upstream_repository = str(raw.get("upstream_repository") or "")
        card.pinned_revision = str(raw.get("pinned_revision") or "")
        card.revision_resolved_on = str(raw.get("revision_resolved_on") or "")
        card.revision_selection = str(raw.get("revision_selection") or "")
        card.qualified_revisions = list(raw.get("qualified_revisions") or [])
        card.include_patterns = list(raw.get("include_patterns") or [])
        card.license_paths = list(raw.get("license_paths") or [])
        card.record_selection = str(raw.get("record_selection") or "")
        card.record_limit = int(raw.get("record_limit") or 0)
        card.record_limit_max = int(raw.get("record_limit_max") or 0)
        card.preview_limit = int(raw.get("preview_limit") or 0)
        card.measured_upstream_records = raw.get("measured_upstream_records")
        card.measured_upstream_bytes = raw.get("measured_upstream_bytes")
        card.measured_selected_records = raw.get("measured_selected_records")
        card.measured_selected_bytes = raw.get("measured_selected_bytes")
        card.measured_transfer_seconds = raw.get("measured_transfer_seconds")
        card.measurement_environment = str(raw.get("measurement_environment") or "")
        card.verified_record_digests = bool(raw.get("verified_record_digests", False))
        card.blocked_reason = str(raw.get("blocked_reason") or UNQUALIFIED_REASON)
        card.evidence = raw.get("evidence") or {}
        if card.status == "qualified" and not card.pinned_revision:
            card.status = "unqualified"
            card.blocked_reason = "Qualification evidence declares no pinned upstream revision."
        if card.status != "qualified" and not card.blocked_reason:
            card.blocked_reason = UNQUALIFIED_REASON
        return card

    def get_source(self, source_id: str) -> Optional[SourceCard]:
        return self._sources.get(source_id)

    def get_preset(self, preset_id: str) -> Optional[PresetCard]:
        return self._presets.get(preset_id)

    def list_sources(self) -> list[SourceCard]:
        return list(self._sources.values())

    def list_presets(self) -> list[PresetCard]:
        return list(self._presets.values())

    def search(
        self,
        query: Optional[str] = None,
        *,
        modality: Optional[str] = None,
        task: Optional[str] = None,
        eligible_only: bool = True,
    ) -> list[SourceCard]:
        """Search and filter sources across task, modality, license, and name."""
        results: list[SourceCard] = []
        q = (query or "").lower().strip()

        for source in self._sources.values():
            if eligible_only and not source.download_enabled:
                continue

            if modality and modality.lower() not in [m.lower() for m in source.modalities]:
                continue

            if task and task.lower() not in [u.lower() for u in source.use_cases]:
                continue

            if q:
                match = (
                    q in source.id.lower()
                    or q in source.name.lower()
                    or q in source.description.lower()
                    or q in source.category.lower()
                    or any(q in m.lower() for m in source.modalities)
                    or any(q in u.lower() for u in source.use_cases)
                )
                if not match:
                    continue

            results.append(source)
        return results

    def qualified_sources(self) -> list[SourceCard]:
        """Sources with a connector that has actually fetched and verified upstream bytes."""
        return [source for source in self._sources.values() if source.acquisition.qualified]

    def preflight_download(
        self,
        source_id: str,
        *,
        tenant_id: str,
        project_policy: Optional[dict[str, Any]] = None,
        source_revision: Optional[str] = None,
    ) -> dict[str, Any]:
        """Validate destination, scope, and policy conditions before launching transfer (BANK03, BANK04)."""
        policy = project_policy or {}

        # 1. Check if source is in held candidates
        def _norm(s: str) -> str:
            return re.sub(r"[-_\s]+", "", s.lower())

        for held in self.held_candidates:
            if _norm(held.name) in _norm(source_id) or _norm(source_id) in _norm(held.name):
                raise ValidationError(
                    f"Candidate {held.name!r} is held from download: {held.reason}"
                )

        source = self.get_source(source_id)
        if not source:
            raise ValidationError(f"Source {source_id!r} does not exist in catalog.")

        if not source.download_enabled:
            raise ValidationError(
                f"Source {source.name!r} download is blocked: {source.rejection_reason}"
            )

        # 2. Check share-alike requirements
        if source.obligations.share_alike and not policy.get("allow_share_alike", False):
            raise ValidationError(
                f"Source {source.name!r} is under share-alike license ({source.license_expression}). "
                "Project policy must explicitly set allow_share_alike=True to enable download."
            )

        # 3. Check gated access requirements
        if source.obligations.gated and not policy.get("gated_credentials_accepted", False):
            raise ValidationError(
                f"Source {source.name!r} requires accepted user agreement and access credentials."
            )

        # 4. Acquisition qualification is a separate, evidence-backed claim
        self.assert_acquirable(source_id, source_revision=source_revision)
        card = source.acquisition
        revision = source_revision or card.pinned_revision

        # 5. Storage & tenancy bounds
        max_quota_bytes = policy.get("max_storage_quota_bytes", 100 * 1024 * 1024 * 1024)
        source_size = source.size_bytes or 0
        if source_size > max_quota_bytes:
            raise ValidationError(
                f"Source estimated size ({source_size} B) exceeds project quota ({max_quota_bytes} B)."
            )

        record_limit = int(policy.get("record_limit") or card.record_limit or 0)
        if record_limit <= 0:
            record_limit = card.record_limit
        if card.record_limit_max and record_limit > card.record_limit_max:
            raise ValidationError(
                f"Requested scope ({record_limit} records) exceeds the qualified bound "
                f"({card.record_limit_max} records)."
            )

        return {
            "status": "approved",
            "source_id": source.id,
            "source_name": source.name,
            "tenant_id": tenant_id,
            "license": source.license_expression,
            "obligations": {
                "retain_notices": source.obligations.retain_license_and_notices,
                "share_alike": source.obligations.share_alike,
                "attribution_required": source.obligations.attribution_required,
                "evidence_urls": source.obligations.evidence_urls,
                "notes": source.obligations.notes,
            },
            "access": {
                "gated": source.obligations.gated,
                "credentials_accepted": bool(policy.get("gated_credentials_accepted", False)),
                "share_alike_opt_in": bool(policy.get("allow_share_alike", False)),
                "license_paths": card.license_paths,
            },
            "source_revision": revision,
            "source_url": source.source_url,
            "upstream_repository": card.upstream_repository,
            "catalog_status": self.catalog_status,
            "catalog_checked_on": self.checked_on,
            "scope": {
                "include_patterns": card.include_patterns,
                "record_selection": card.record_selection,
                "record_limit": record_limit,
                "record_limit_max": card.record_limit_max,
                "available_records": card.measured_upstream_records,
                "measured_selected_bytes": card.measured_selected_bytes,
                "measured_transfer_seconds": card.measured_transfer_seconds,
            },
            "qualification_evidence": {
                "connector": card.connector,
                "qualified_on": card.qualified_on,
                "revision_resolved_on": card.revision_resolved_on,
                "revision_selection": card.revision_selection,
                "verified_record_digests": card.verified_record_digests,
                "measurement_environment": card.measurement_environment,
                "evidence": card.evidence,
            },
            "is_size_measured": source.is_size_measured,
            "estimated_bytes": source.size_bytes,
        }

    def assert_acquirable(
        self, source_id: str, *, source_revision: Optional[str] = None
    ) -> SourceCard:
        """Return the source only when an implemented connector has qualified it.

        License eligibility, a catalog entry, or a declared fetch pattern never
        substitute for a qualification record with a pinned upstream revision.
        """
        source = self.get_source(source_id)
        if not source:
            raise ValidationError(f"Source {source_id!r} does not exist in catalog.")
        card = source.acquisition
        if not card.qualified:
            raise ValidationError(
                f"Source {source.name!r} is not qualified for acquisition: {card.blocked_reason}"
            )
        if source_revision and not card.revision_is_qualified(str(source_revision)):
            raise ValidationError(
                f"Upstream revision {source_revision!r} of {source.name!r} is not qualified. "
                f"Only {card.pinned_revision} has verified qualification evidence."
            )
        return source
