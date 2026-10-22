"""Tenant-scoped REST APIs for Releases, Release Versions, Serving Endpoints, and SBOM generation."""
from __future__ import annotations

import io
import json
import hashlib
import uuid
from django.conf import settings
from django.db import transaction
from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.data.publication import _read_verified_input

from modelanvil.runners.evidence import evidence, training_evidence, model_evidence, evaluation_evidence, release_evidence

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.core.models import record_audit
from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.models import Role, check_resource_access, get_accessible_queryset, role_at_least
from modelanvil.runners.models import ModelVersion, EvaluationRun
from modelanvil.releases.lifecycle import (
    ReleasePromotionBlockedError,
    TombstoneAccessDeniedError,
    evaluate_release_gates,
    export_release_bundle,
    promote_endpoint,
    quantize_and_evaluate,
    rollback_endpoint,
)
from modelanvil.releases.models import (
    DeploymentRevision,
    GateResult,
    Release,
    ReleaseException,
    ReleaseVersion,
    ServingEndpoint,
)
from modelanvil.releases.sbom import generate_model_sbom


class GateResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = GateResult
        fields = ("gate_result_id", "criterion_key", "passed", "evidence_digest", "details", "checked_at")


class ReleaseVersionSerializer(serializers.ModelSerializer):
    local_review = serializers.JSONField(source='bundle_manifest.local_review', read_only=True, default=None)

    def validate(self, attrs):
        if self.instance and self.instance.bundle_manifest.get('local_review'):
            raise serializers.ValidationError('Reviewed releases are immutable; create another candidate revision.')
        return attrs
    execution_evidence = serializers.SerializerMethodField()

    def get_execution_evidence(self, obj):
        return release_evidence(obj)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["recorded_status"] = data["status"]
        if data["status"] in ("qualified", "promoted") and not release_evidence(instance)["production_qualified"]:
            data["status"] = ReleaseVersion.Status.DRAFT
        return data


    gate_results = GateResultSerializer(many=True, read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "release" in self.fields:
            self.fields["release"].queryset = get_accessible_queryset(Release)
        if "model_version" in self.fields:
            self.fields["model_version"].queryset = get_accessible_queryset(ModelVersion)

    class Meta:
        model = ReleaseVersion
        fields = (
            "execution_evidence", "local_review",
            "release_version_id", "project", "release", "revision_no", "candidate_type",
            "candidate_ref", "model_version", "status", "manifest_digest",
            "model_card", "bundle_manifest", "quantization_spec", "gate_results", "created_at"
        )
        read_only_fields = ("release_version_id", "status", "manifest_digest", "bundle_manifest", "created_at")


class ReleaseSerializer(serializers.ModelSerializer):
    versions = ReleaseVersionSerializer(many=True, read_only=True)

    class Meta:
        model = Release
        fields = ("release_id", "project", "name", "description", "versions", "created_at", "updated_at")
        read_only_fields = ("release_id", "versions", "created_at", "updated_at")


class ReleaseViewSet(TenantScopedViewSet):
    queryset = Release.objects.prefetch_related("versions")
    serializer_class = ReleaseSerializer
    lookup_field = "release_id"

    def perform_destroy(self, instance):
        if instance.versions.filter(bundle_manifest__local_review__isnull=False).exists():
            raise serializers.ValidationError('Reviewed release revisions retain their evidence and exports.')
        super().perform_destroy(instance)


class ReleaseVersionViewSet(TenantScopedViewSet):
    queryset = ReleaseVersion.objects.prefetch_related("gate_results")
    serializer_class = ReleaseVersionSerializer
    lookup_field = "release_version_id"

    @action(detail=False, methods=['post'], url_path='create-candidate')
    def create_candidate(self, request):
        from modelanvil.releases.review import create_candidate_review
        name = serializers.CharField(max_length=200).run_validation(request.data.get('name'))
        candidate_id = serializers.UUIDField().run_validation(request.data.get('candidate_model_version'))
        evaluation_id = serializers.UUIDField().run_validation(request.data.get('evaluation_run'))
        threshold = serializers.FloatField(min_value=0, max_value=1).run_validation(request.data.get('min_accuracy', 0.8))
        import math
        if not math.isfinite(threshold):
            raise serializers.ValidationError('Accuracy threshold must be finite.')
        candidate = get_accessible_queryset(ModelVersion).filter(model_version_id=candidate_id).first()
        evaluation = get_accessible_queryset(EvaluationRun).filter(run_id=evaluation_id).first()
        if not candidate or not evaluation:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        license_record = request.data.get('license_record')
        if license_record is not None:
            if not isinstance(license_record, dict) or set(license_record) != {'spdx', 'source', 'notice'}:
                raise serializers.ValidationError('License record requires spdx, source and notice text.')
            license_record = {key: serializers.CharField(max_length=4000).run_validation(value) for key, value in license_record.items()}
        try:
            version, created = create_candidate_review(tenant=get_active_tenant(),
                project=get_active_project() or candidate.project_id, name=name, candidate=candidate,
                evaluation=evaluation, min_accuracy=threshold, license_record=license_record)
        except (ValueError, PermissionError) as exc:
            raise serializers.ValidationError({'review': str(exc)}) from exc
        if created:
            record_audit('release.review', 'release_version', version.release_version_id,
                input_snapshot={'manifest_digest': version.manifest_digest, 'candidate': str(candidate_id),
                                'evaluation': str(evaluation_id), 'scope': 'local_cpu_export'})
        return Response(self.get_serializer(version).data, status=201 if created else 200)

    def perform_destroy(self, instance):
        if instance.bundle_manifest.get('local_review'):
            raise serializers.ValidationError('Reviewed releases retain their evidence and exports.')
        super().perform_destroy(instance)

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, release_version_id=None):
        from django.http import HttpResponse
        from modelanvil.releases.review import candidate_archive
        version = self.get_object()
        try:
            raw = candidate_archive(version)
        except (ValueError, PermissionError) as exc:
            raise serializers.ValidationError({'export': str(exc)}) from exc
        response = HttpResponse(raw, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="candidate-{version.release_version_id}.zip"'
        response['Cache-Control'] = 'no-store'
        return response

    def perform_create(self, serializer):
        from rest_framework.exceptions import NotFound
        release = serializer.validated_data["release"]
        model_version = serializer.validated_data.get("model_version")
        active_project = get_active_project() or getattr(release, "project_id", None)
        if not check_resource_access(release, active_project, get_active_tenant()):
            raise NotFound()
        if model_version and not check_resource_access(model_version, active_project, get_active_tenant()):
            raise NotFound()
        kwargs = {"tenant_id": get_active_tenant()}
        if active_project:
            kwargs["project_id"] = active_project
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        from rest_framework.exceptions import NotFound
        release = serializer.validated_data.get("release", serializer.instance.release)
        model_version = serializer.validated_data.get("model_version", serializer.instance.model_version)
        active_project = get_active_project() or getattr(serializer.instance, "project_id", None) or getattr(release, "project_id", None)
        if not check_resource_access(release, active_project, get_active_tenant()):
            raise NotFound()
        if model_version and not check_resource_access(model_version, active_project, get_active_tenant()):
            raise NotFound()
        serializer.save()

    @action(detail=True, methods=["post"], url_path="exceptions")
    def create_exception(self, request, release_version_id=None):
        """Create a policy exception waiving a failing gate result (requires MANAGER role)."""
        version = self.get_object()
        tenant = get_active_tenant()
        user_role = getattr(request, "modelanvil_role", None)

        if not role_at_least(user_role, Role.MANAGER):
            record_audit(
                action="create_policy_exception",
                resource_type="release_version",
                resource_id=version.release_version_id,
                actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                input_snapshot={"reason": request.data.get("reason"), "role": user_role},
                result="denied",
                tenant_id=tenant,
            )
            return Response(
                {"error": {"code": "forbidden", "message": "Manager role required for policy exceptions."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        gate_result_id = request.data.get("gate_result_id")
        reason = request.data.get("reason")
        policy_id = request.data.get("permitted_policy_id", "default_policy")
        if not gate_result_id or not reason:
            return Response(
                {"error": {"code": "bad_request", "message": "gate_result_id and reason are required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        gate_result_id = serializers.UUIDField().run_validation(gate_result_id)
        gate_result = GateResult.objects.filter(
            tenant_id=tenant,
            release_version=version,
            gate_result_id=gate_result_id,
        ).first()
        if gate_result is None:
            return Response(
                {"error": {"code": "not_found", "message": "Gate result not found."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        exc = ReleaseException.objects.create(
            tenant_id=tenant,
            gate_result=gate_result,
            actor_id=str(getattr(request, "modelanvil_actor_id", "admin")),
            permitted_policy_id=policy_id,
            reason=reason,
        )
        record_audit(
            action="create_policy_exception",
            resource_type="release_version",
            resource_id=version.release_version_id,
            actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
            actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
            input_snapshot={"gate_result_id": str(gate_result.gate_result_id), "exception_id": str(exc.exception_id)},
            result="ok",
            tenant_id=tenant,
        )
        return Response({
            "exception_id": str(exc.exception_id),
            "gate_result_id": str(gate_result.gate_result_id),
            "reason": exc.reason,
            "is_valid": exc.is_valid,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="evaluate-gates")
    def run_gates(self, request, release_version_id=None):
        """Evaluate candidate release against quality, evaluation, and license criteria."""
        version = self.get_object()
        criteria = request.data.get("criteria", [{"key": "license_compliance"}])
        if not isinstance(criteria, list) or len(criteria) > 32:
            raise serializers.ValidationError({"criteria": "Supply at most 32 criteria."})
        resolved = []
        for item in criteria:
            if not isinstance(item, dict) or item.get("key") not in {"min_accuracy", "license_compliance", "no_regression", "quantization_eval"}:
                raise serializers.ValidationError({"criteria": "Unsupported gate criterion."})
            criterion = dict(item)
            if "eval_run" in criterion:
                try:
                    run_id = serializers.UUIDField().run_validation(criterion["eval_run"])
                    evaluation = get_accessible_queryset(EvaluationRun).get(run_id=run_id)
                except (EvaluationRun.DoesNotExist, serializers.ValidationError):
                    raise serializers.ValidationError({"criteria": "Evaluation reference is unavailable."})
                if evaluation.candidate_model_version_id != version.model_version_id:
                    raise serializers.ValidationError({"criteria": "Evaluation must reference this candidate."})
                criterion["eval_run"] = evaluation
            if criterion["key"] == "min_accuracy":
                criterion["required_value"] = serializers.FloatField(min_value=0, max_value=1).run_validation(criterion.get("required_value", 0.8))
            resolved.append(criterion)
        passed = evaluate_release_gates(version, resolved)
        return Response({"passed": passed, "status": version.status})

    @action(detail=True, methods=["post"], url_path="quantize")
    def quantize(self, request, release_version_id=None):
        """Perform INT8/FP8 post-training quantization and verify accuracy drop tolerance."""
        version = self.get_object()
        q_type = request.data.get("quantization_type", "int8")
        spec = quantize_and_evaluate(version, quantization_type=q_type)
        return Response(spec)

    @action(detail=True, methods=["get", "post"], url_path="sbom")
    @transaction.atomic
    def sbom(self, request, release_version_id=None):
        """Generate and retrieve machine-readable SPDX 2.3 Software Bill of Materials."""
        version = self.get_object()
        if request.method == "POST":
            version = ReleaseVersion.objects.select_for_update().get(pk=version.pk)
        try:
            report = generate_model_sbom(version)
            artifact_info = None
            if request.method == "POST":
                raw = json.dumps(report.spdx_document, sort_keys=True, indent=2).encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
                with transaction.atomic():
                    version = ReleaseVersion.objects.select_for_update().get(pk=version.pk)
                    stored = (version.bundle_manifest or {}).get("sbom", {})
                    artifact = Artifact.all_objects.filter(tenant_id=version.tenant_id,
                        pk__in=get_accessible_queryset(Artifact).values("pk"), artifact_id=stored.get("artifact_id"), sha256=digest, state=Artifact.State.COMMITTED).first() if stored.get("artifact_id") else None
                    if artifact is not None:
                        _read_verified_input(artifact, artifact_storage_backend())
                    if artifact is None:
                        artifact = Artifact.objects.create(tenant_id=version.tenant_id, project_id=get_active_project() or version.project_id,
                            storage_location_id="s3" if settings.MODELANVIL.get("artifact_backend") == "s3" else "local",
                            object_key=f"releases/{version.release_version_id}/sbom/{uuid.uuid4()}.spdx.json",
                            sha256=digest, byte_size=len(raw), media_type="application/spdx+json")
                        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
                        record_audit("save_sbom", "release_version", version.release_version_id,
                            tenant_id=version.tenant_id, actor_id=getattr(request, "modelanvil_actor_id", None),
                            actor_kind=getattr(request, "modelanvil_actor_kind", "principal"),
                            input_snapshot={"artifact_id": str(artifact.artifact_id), "sha256": digest, "verified": report.verified})
                    artifact_info = {"artifact_id": str(artifact.artifact_id), "sha256": artifact.sha256,
                                     "download_endpoint": f"/api/v1/artifacts/{artifact.artifact_id}/download/"}
                    version.bundle_manifest = {**(version.bundle_manifest or {}), "sbom": artifact_info}
                    version.save(update_fields=("bundle_manifest", "updated_at"))
            return Response({
                "spdx_id": report.spdx_id,
                "sbom_digest": report.sbom_digest,
                "spdx_document": report.spdx_document,
                "verified": report.verified,
                "warnings": report.warnings,
                "sbom_artifact": artifact_info,
            })
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"], url_path="export-bundle")
    def export(self, request, release_version_id=None):
        """Export recorded metadata and available verified model bytes."""
        version = self.get_object()
        try:
            return Response(export_release_bundle(version))
        except (ValueError, PermissionError, TombstoneAccessDeniedError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class DeploymentRevisionSerializer(serializers.ModelSerializer):
    release_version_id = serializers.UUIDField(source='release_version.release_version_id', read_only=True)
    execution_evidence = serializers.SerializerMethodField()

    def get_execution_evidence(self, obj):
        if obj.serving_config.get('backend') == 'modelanvil.local-on-demand-cpu.v1':
            return evidence('integrated_execution' if obj.serving_config.get('readiness_probe') else 'configuration_only',
                'Local on-demand CPU serving; startup probe recorded. Check live health after restart or interruption; production qualification unavailable.')
        origin = (obj.serving_config or {}).get("execution_evidence", {})
        return evidence("simulation" if origin.get("level") == "simulation" else "unknown",
                        "Endpoint pointer; live serving has not been verified")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["recorded_readiness_state"] = data["readiness_state"]
        if data["readiness_state"] == "ready" and instance.serving_config.get('backend') != 'modelanvil.local-on-demand-cpu.v1':
            data["readiness_state"] = DeploymentRevision.ReadinessState.PENDING
        return data

    class Meta:
        model = DeploymentRevision
        fields = ("execution_evidence", "deployment_id", "release_version", "release_version_id", "revision_no", "readiness_state", "serving_config", "created_at")


class ServingEndpointSerializer(serializers.ModelSerializer):
    active_deployment = DeploymentRevisionSerializer(read_only=True)
    deployments = DeploymentRevisionSerializer(many=True, read_only=True)

    class Meta:
        model = ServingEndpoint
        fields = ("endpoint_id", "project", "endpoint_key", "name", "active_deployment", "deployments", "created_at", "updated_at")
        read_only_fields = ("endpoint_id", "created_at", "updated_at")


class ServingEndpointViewSet(TenantScopedViewSet):
    queryset = ServingEndpoint.objects.select_related("active_deployment")
    serializer_class = ServingEndpointSerializer
    lookup_field = "endpoint_id"

    @action(detail=True, methods=['post'], url_path='deploy-local')
    def deploy_local(self, request, endpoint_id=None):
        if not role_at_least(getattr(request, 'modelanvil_role', None), Role.MANAGER):
            return Response({'detail': 'Manager role is required to deploy local serving.'}, status=403)
        from modelanvil.releases.local_serving import deploy_local
        endpoint = self.get_object()
        identifier = serializers.UUIDField().run_validation(request.data.get('release_version_id'))
        version = get_accessible_queryset(ReleaseVersion).filter(release_version_id=identifier).first()
        if not version:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        deployment = deploy_local(endpoint, version)
        record_audit('serving.deploy_local', 'serving_endpoint', endpoint.endpoint_id,
            input_snapshot={'deployment_id': str(deployment.deployment_id), 'state': deployment.readiness_state})
        return Response(DeploymentRevisionSerializer(deployment).data, status=201 if deployment.readiness_state == 'ready' else 409)

    @action(detail=True, methods=['get'], url_path='local-health')
    def local_health(self, request, endpoint_id=None):
        from modelanvil.releases.local_serving import serve_local
        try:
            result = serve_local(self.get_object(), 'x', 2)
        except (ValueError, PermissionError) as exc:
            return Response({'state': 'unhealthy', 'reason': str(exc), 'production_qualified': False}, status=503)
        return Response({'state': 'ready', **result})

    @action(detail=True, methods=['post'], url_path='completions')
    def completions(self, request, endpoint_id=None):
        from modelanvil.releases.local_serving import serve_local
        prompt = serializers.CharField(max_length=1024, allow_blank=True).run_validation(request.data.get('prompt', ''))
        maximum = serializers.IntegerField(min_value=1, max_value=32).run_validation(request.data.get('max_tokens', 2))
        try:
            return Response(serve_local(self.get_object(), prompt, maximum))
        except (ValueError, PermissionError) as exc:
            raise serializers.ValidationError({'serving': str(exc)}) from exc

    @action(detail=True, methods=["post"], url_path="promote")
    def promote(self, request, endpoint_id=None):
        """Promote endpoint to a qualified release version with atomic pointer update."""
        endpoint = self.get_object()
        tenant = get_active_tenant()
        user_role = getattr(request, "modelanvil_role", None)

        if not role_at_least(user_role, Role.MANAGER):
            record_audit(
                action="promote",
                resource_type="serving_endpoint",
                resource_id=endpoint.endpoint_id,
                actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                input_snapshot={"endpoint_id": str(endpoint.endpoint_id), "role": user_role},
                result="denied",
                tenant_id=tenant,
            )
            return Response(
                {"error": {"code": "forbidden", "message": "Manager role required for endpoint promotion."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        rel_ver_id = serializers.UUIDField().run_validation(request.data.get("release_version_id"))
        rel_ver = ReleaseVersion.objects.filter(tenant_id=endpoint.tenant_id, release_version_id=rel_ver_id).first()
        if rel_ver is None or not check_resource_access(rel_ver, endpoint.project_id or get_active_project(), endpoint.tenant_id):
            record_audit(
                action="promote",
                resource_type="serving_endpoint",
                resource_id=endpoint.endpoint_id,
                actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                input_snapshot={"endpoint_id": str(endpoint.endpoint_id), "release_version_id": str(rel_ver_id)},
                result="denied",
                tenant_id=tenant,
            )
            return Response({"error": {"code": "not_found", "message": "Release version not found."}}, status=status.HTTP_404_NOT_FOUND)

        try:
            deployment = promote_endpoint(endpoint, rel_ver)
            record_audit(
                action="promote",
                resource_type="serving_endpoint",
                resource_id=endpoint.endpoint_id,
                actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                input_snapshot={"endpoint_id": str(endpoint.endpoint_id), "release_version_id": str(rel_ver.release_version_id), "deployment_id": str(deployment.deployment_id)},
                result="ok",
                tenant_id=tenant,
            )
            return Response({
                "status": "promoted",
                "deployment_id": str(deployment.deployment_id),
                "revision_no": deployment.revision_no,
            })
        except ReleasePromotionBlockedError as exc:
            record_audit(action="promote", resource_type="serving_endpoint",
                         resource_id=endpoint.endpoint_id,
                         actor_id=getattr(request, "modelanvil_actor_id", None),
                         actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                         input_snapshot={"reason": "runtime_unqualified"}, result="denied", tenant_id=tenant)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="rollback")
    def rollback(self, request, endpoint_id=None):
        """Atomically rollback endpoint to previous deployment revision."""
        endpoint = self.get_object()
        tenant = get_active_tenant()
        user_role = getattr(request, "modelanvil_role", None)

        if not role_at_least(user_role, Role.MANAGER):
            record_audit(
                action="rollback",
                resource_type="serving_endpoint",
                resource_id=endpoint.endpoint_id,
                actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                input_snapshot={"endpoint_id": str(endpoint.endpoint_id), "role": user_role},
                result="denied",
                tenant_id=tenant,
            )
            return Response(
                {"error": {"code": "forbidden", "message": "Manager role required for endpoint rollback."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            if endpoint.active_deployment and endpoint.active_deployment.serving_config.get('backend') == 'modelanvil.local-on-demand-cpu.v1':
                from modelanvil.releases.local_serving import rollback_local
                deployment = rollback_local(endpoint)
                if deployment.readiness_state != 'ready':
                    return Response(DeploymentRevisionSerializer(deployment).data, status=409)
            else:
                deployment = rollback_endpoint(endpoint)
            record_audit(
                action="rollback",
                resource_type="serving_endpoint",
                resource_id=endpoint.endpoint_id,
                actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                input_snapshot={"endpoint_id": str(endpoint.endpoint_id), "deployment_id": str(deployment.deployment_id)},
                result="ok",
                tenant_id=tenant,
            )
            return Response({
                "status": "rolled_back",
                "deployment_id": str(deployment.deployment_id),
                "revision_no": deployment.revision_no,
                "release_version_id": str(deployment.release_version_id),
            })
        except Exception as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
