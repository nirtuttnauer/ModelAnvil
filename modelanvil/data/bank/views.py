"""API views for Dataset Bank discovery, cards, preview, preflight, and acquisition (WP-06 / TECH-010).

Nothing in this module fabricates dataset content: previews, samples and
published versions come from bytes actually fetched from a qualified upstream
revision. Sources without qualification evidence are refused with a visible
reason.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import permissions, serializers, status, viewsets
from decimal import Decimal
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.data.bank.acquisition import (
    AcquisitionCapacityError,
    AcquisitionRefused,
    access_acquisition,
    acquisition_state,
    cancel_acquisition,
    launch_acquisition,
    preview_samples,
    resume_acquisition,
    upstream_head_revision,
)
from modelanvil.data.bank.catalog import DatasetBankCatalog
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role


class AcquisitionRequestSerializer(serializers.Serializer):
    project_policy = serializers.DictField(required=False, default=dict)
    source_revision = serializers.CharField(required=False, allow_blank=False, max_length=255)
    record_limit = serializers.IntegerField(required=False, min_value=1)
    split_seed = serializers.CharField(required=False, default="0", max_length=1024)
    budget_policy_id = serializers.UUIDField(required=False)
    estimated_amount = serializers.DecimalField(required=False, max_digits=24, decimal_places=6,
                                                min_value=Decimal("0.000001"))
    pool = serializers.CharField(required=False, max_length=200)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Provide a JSON object.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({field: "Unknown acquisition field." for field in unknown})
        return super().to_internal_value(data)

    def validate_project_policy(self, policy):
        for flag in ("allow_share_alike", "gated_credentials_accepted"):
            if flag in policy and type(policy[flag]) is not bool:
                raise serializers.ValidationError(f"{flag} must be a boolean.")
        if "record_limit" in policy:
            value = policy["record_limit"]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise serializers.ValidationError("record_limit must be a positive integer.")
        return policy


def _qualification_payload(card: Any) -> dict[str, Any]:
    return {
        "status": card.status,
        "qualified_on": card.qualified_on,
        "connector": card.connector,
        "upstream_repository": card.upstream_repository,
        "pinned_revision": card.pinned_revision,
        "revision_resolved_on": card.revision_resolved_on,
        "revision_selection": card.revision_selection,
        "qualified_revisions": card.qualified_revisions,
        "include_patterns": card.include_patterns,
        "license_paths": card.license_paths,
        "record_selection": card.record_selection,
        "record_limit": card.record_limit,
        "record_limit_max": card.record_limit_max,
        "preview_limit": card.preview_limit,
        "measured_upstream_records": card.measured_upstream_records,
        "measured_upstream_bytes": card.measured_upstream_bytes,
        "measured_selected_records": card.measured_selected_records,
        "measured_selected_bytes": card.measured_selected_bytes,
        "measured_transfer_seconds": card.measured_transfer_seconds,
        "measurement_environment": card.measurement_environment,
        "verified_record_digests": card.verified_record_digests,
        "blocked_reason": "" if card.qualified else card.blocked_reason,
        "evidence": card.evidence,
    }


class DatasetBankViewSet(viewsets.ViewSet):
    """Endpoints for open dataset bank search, source cards, sample preview, preflight, and acquisition."""

    permission_classes = (permissions.IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    write_role = Role.ENGINEER

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.catalog = DatasetBankCatalog.load_from_file()

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        self.required_role = Role.VIEWER if request.method == "GET" else self.write_role
        super().initial(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="sources")
    def list_sources(self, request: Request) -> Response:
        q = request.query_params.get("q")
        modality = request.query_params.get("modality")
        task = request.query_params.get("task")
        eligible_only = request.query_params.get("eligible_only", "true").lower() == "true"

        results = self.catalog.search(
            query=q, modality=modality, task=task, eligible_only=eligible_only
        )
        data = [
            {
                "id": s.id,
                "name": s.name,
                "category": s.category,
                "source_kind": s.source_kind,
                "description": s.description,
                "source_url": s.source_url,
                "modalities": s.modalities,
                "use_cases": s.use_cases,
                "license": s.license_expression,
                "eligibility": s.eligibility,
                "download_enabled": s.download_enabled,
                "size_bytes": s.size_bytes,
                "is_size_measured": s.is_size_measured,
                "acquisition_status": s.acquisition.status,
                "acquisition_available": s.acquisition_available,
                "acquisition_blocked_reason": "" if s.acquisition.qualified else s.acquisition.blocked_reason,
                "pinned_revision": s.acquisition.pinned_revision,
                "acquisition_record_limit": s.acquisition.record_limit,
            }
            for s in results
        ]
        return Response({
            "sources": data,
            "count": len(data),
            "catalog_status": self.catalog.catalog_status,
            "catalog_checked_on": self.catalog.checked_on,
            "qualified_count": len(self.catalog.qualified_sources()),
        })

    @action(detail=False, methods=["get"], url_path=r"sources/(?P<source_id>[^/.]+)")
    def retrieve_source(self, request: Request, source_id: str) -> Response:
        s = self.catalog.get_source(source_id)
        if not s:
            return Response({"detail": f"Source {source_id!r} not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "id": s.id,
            "name": s.name,
            "category": s.category,
            "source_kind": s.source_kind,
            "description": s.description,
            "source_url": s.source_url,
            "modalities": s.modalities,
            "use_cases": s.use_cases,
            "license": s.license_expression,
            "obligations": {
                "retain_notices": s.obligations.retain_license_and_notices,
                "share_alike": s.obligations.share_alike,
                "gated": s.obligations.gated,
                "attribution_required": s.obligations.attribution_required,
                "evidence_urls": s.obligations.evidence_urls,
                "notes": s.obligations.notes,
            },
            "eligibility": s.eligibility,
            "download_enabled": s.download_enabled,
            "rejection_reason": s.rejection_reason,
            "size_bytes": s.size_bytes,
            "record_count": s.record_count,
            "is_size_measured": s.is_size_measured,
            "acquisition": _qualification_payload(s.acquisition),
            "acquisition_available": s.acquisition_available,
        })

    @action(detail=False, methods=["get"], url_path=r"sources/(?P<source_id>[^/.]+)/preview")
    def preview_source(self, request: Request, source_id: str) -> Response:
        """Bounded real sample preview with the launch disclosure, or a refusal."""
        try:
            source = self.catalog.assert_acquirable(source_id)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        try:
            limit = int(request.query_params.get("limit", 0)) or None
            samples = preview_samples(source, limit=limit)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - sanitized upstream failure
            return Response(
                {"detail": f"Upstream preview is unavailable: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        card = source.acquisition
        tenant_id = get_active_tenant()
        project = get_active_project()
        return Response({
            "source_id": source.id,
            "samples_are_real_upstream_records": True,
            "source_revision": card.pinned_revision,
            "samples": samples,
            "launch_disclosure": {
                "source_revision": card.pinned_revision,
                "revision_resolved_on": card.revision_resolved_on,
                "upstream_repository": card.upstream_repository,
                "connector": card.connector,
                "catalog_status": self.catalog.catalog_status,
                "catalog_checked_on": self.catalog.checked_on,
                "access": {
                    "gated": source.obligations.gated,
                    "credentials_required": source.obligations.gated,
                    "share_alike": source.obligations.share_alike,
                },
                "license": source.license_expression,
                "obligations": {
                    "retain_notices": source.obligations.retain_license_and_notices,
                    "attribution_required": source.obligations.attribution_required,
                    "evidence_urls": source.obligations.evidence_urls,
                    "notes": source.obligations.notes,
                },
                "scope": {
                    "include_patterns": card.include_patterns,
                    "record_selection": card.record_selection,
                    "record_limit": card.record_limit,
                    "record_limit_max": card.record_limit_max,
                    "available_records": card.measured_upstream_records,
                    "measured_selected_bytes": card.measured_selected_bytes,
                },
                "destination": {
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "project_id": str(project) if project is not None else None,
                    "artifact_object_key_prefix": f"bank/{source.id}/",
                    "artifact_backend": settings.MODELANVIL["artifact_backend"],
                },
                "qualification_evidence": _qualification_payload(card),
            },
        })

    @action(detail=False, methods=["post"], url_path=r"sources/(?P<source_id>[^/.]+)/preflight")
    def preflight_source(self, request: Request, source_id: str) -> Response:
        tenant_id = get_active_tenant() or getattr(request, "tenant_id", None) or getattr(request.user, "tenant_id", None)
        serializer = AcquisitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        policy = data.get("project_policy") or {}
        if "record_limit" in data:
            policy["record_limit"] = data["record_limit"]
        try:
            result = self.catalog.preflight_download(
                source_id, tenant_id=str(tenant_id), project_policy=policy,
                source_revision=data.get("source_revision"),
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=False, methods=["get"], url_path=r"sources/(?P<source_id>[^/.]+)/upstream")
    def upstream_source(self, request: Request, source_id: str) -> Response:
        """Compare the pinned qualified revision with the current upstream head."""
        try:
            source = self.catalog.assert_acquirable(source_id)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        if source.acquisition.connector == "qualified_http_subset_v1":
            return Response({"source_id": source.id, "pinned_revision": source.acquisition.pinned_revision,
                "upstream_head_revision": None, "moved": None,
                "acquirable_revisions": source.acquisition.qualified_revisions,
                "automatic_update_check_supported": False,
                "note": "This source uses a frozen content-pinned subset. Requalification is required to admit new samples or upstream ranges."})
        try:
            head = upstream_head_revision(source)
        except Exception as exc:  # noqa: BLE001 - sanitized upstream failure
            return Response(
                {"detail": f"Upstream revision check is unavailable: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        card = source.acquisition
        return Response({
            "source_id": source.id,
            "pinned_revision": card.pinned_revision,
            "upstream_head_revision": head,
            "moved": head != card.pinned_revision,
            "acquirable_revisions": card.qualified_revisions,
            "note": (
                "A moved upstream head is not acquirable until it is qualified; "
                "only revisions with qualification evidence can be published."
            ),
        })

    @action(detail=False, methods=["post"], url_path=r"sources/(?P<source_id>[^/.]+)/acquisitions")
    def launch_acquisition(self, request: Request, source_id: str) -> Response:
        tenant_id = get_active_tenant()
        if not tenant_id:
            return Response({"detail": "Active tenant is required."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AcquisitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            launch = launch_acquisition(
                tenant_id=tenant_id,
                source_id=source_id,
                project_id=get_active_project(),
                catalog=self.catalog,
                project_policy=data.get("project_policy"),
                source_revision=data.get("source_revision"),
                record_limit=data.get("record_limit"),
                split_seed=data["split_seed"],
                budget_policy_id=data.get("budget_policy_id"),
                estimated_amount=data.get("estimated_amount"),
                pool_name=data.get("pool"),
            )
        except AcquisitionCapacityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - sanitized upstream failure
            return Response(
                {"detail": f"Upstream planning is unavailable: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            acquisition_state(launch.snapshot),
            status=status.HTTP_201_CREATED if launch.created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path=r"acquisitions/(?P<snapshot_id>[^/.]+)")
    def retrieve_acquisition(self, request: Request, snapshot_id: str) -> Response:
        snapshot = self._acquisition(snapshot_id)
        if isinstance(snapshot, Response):
            return snapshot
        return Response(acquisition_state(snapshot))

    @action(detail=False, methods=["post"], url_path=r"acquisitions/(?P<snapshot_id>[^/.]+)/cancel")
    def cancel_acquisition(self, request: Request, snapshot_id: str) -> Response:
        snapshot = self._acquisition(snapshot_id)
        if isinstance(snapshot, Response):
            return snapshot
        try:
            cancel_acquisition(snapshot)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        snapshot.refresh_from_db()
        return Response(acquisition_state(snapshot))

    @action(detail=False, methods=["post"], url_path=r"acquisitions/(?P<snapshot_id>[^/.]+)/resume")
    def resume_acquisition(self, request: Request, snapshot_id: str) -> Response:
        snapshot = self._acquisition(snapshot_id)
        if isinstance(snapshot, Response):
            return snapshot
        serializer = AcquisitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            resume_acquisition(
                snapshot,
                pool_name=data.get("pool"),
                budget_policy_id=data.get("budget_policy_id"),
                estimated_amount=data.get("estimated_amount"),
            )
        except AcquisitionCapacityError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        snapshot.refresh_from_db()
        return Response(acquisition_state(snapshot), status=status.HTTP_202_ACCEPTED)

    def _acquisition(self, snapshot_id: str) -> Any:
        tenant_id = get_active_tenant()
        if not tenant_id:
            return Response({"detail": "Active tenant is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return access_acquisition(snapshot_id, requesting_tenant_id=tenant_id, project_id=get_active_project())
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["get"], url_path="presets")
    def list_presets(self, request: Request) -> Response:
        presets = self.catalog.list_presets()
        data = [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "tasks": p.tasks,
                "modalities": p.modalities,
                "source_ids": p.source_ids,
                "preparation_recipe": p.preparation_recipe,
                "profile": p.profile,
                "qualified_source_ids": [
                    source_id for source_id in p.source_ids
                    if (self.catalog.get_source(source_id) or None)
                    and self.catalog.get_source(source_id).acquisition.qualified
                ],
            }
            for p in presets
        ]
        return Response({
            "presets": data,
            "count": len(data),
            "note": "A preset lists candidate sources; only individually qualified sources can be acquired.",
        })

    @action(detail=False, methods=["get"], url_path="held")
    def list_held_candidates(self, request: Request) -> Response:
        data = [
            {
                "name": h.name,
                "source_url": h.source_url,
                "reason": h.reason,
                "checked_on": h.checked_on,
                "download_enabled": False,
            }
            for h in self.catalog.held_candidates
        ]
        return Response({"held_candidates": data, "count": len(data)})
