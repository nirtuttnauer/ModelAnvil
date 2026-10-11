"""Worker-specific input download grants, separate from tenant artifact CRUD."""
from django.http import StreamingHttpResponse
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modelanvil.artifacts.worker_access import GrantDownload, discover_download_grants, issue_download_grant
from modelanvil.artifacts.models import WorkerArtifactGrant
from modelanvil.core.models import record_audit
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.models import Role, role_at_least


class DownloadGrantSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField(min_value=1)
    attempt_id = serializers.UUIDField()
    artifact_id = serializers.UUIDField()
    ttl_seconds = serializers.IntegerField(min_value=1, max_value=300, default=60)


class GrantDiscoverySerializer(serializers.Serializer):
    worker_id = serializers.IntegerField(min_value=1)
    attempt_id = serializers.UUIDField()
    fencing_token = serializers.CharField(min_length=1, max_length=64, trim_whitespace=False)
    cursor = serializers.RegexField(
        regex=r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z",
        required=False, trim_whitespace=False,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def discover(request):
    if getattr(request, "modelanvil_actor_kind", None) != "worker_credential":
        raise PermissionDenied("Use the scoped worker credential for discovery.")
    serializer = GrantDiscoverySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if serializer.validated_data["worker_id"] != request.modelanvil_worker_id:
        raise PermissionDenied("Worker credential is bound to a different worker.")
    response = Response(discover_download_grants(
        tenant_id=get_active_tenant(), credential_id=request.auth.pk, **serializer.validated_data,
    ))
    response["Cache-Control"] = "private, no-store"
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def issue(request):
    if not role_at_least(getattr(request, "modelanvil_role", None), Role.ADMIN):
        record_audit("create", "worker_artifact_grant",
                     actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                     actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                     input_snapshot={"path": request.path, "role": getattr(request, "modelanvil_role", None)},
                     result="denied",
                     tenant_id=get_active_tenant())
        raise PermissionDenied()
    with transaction.atomic():
        serializer = DownloadGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant = issue_download_grant(tenant_id=get_active_tenant(), **serializer.validated_data)
        record_audit("create", "worker_artifact_grant", grant.grant_id,
                     actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
                     input_snapshot={"artifact_id": str(grant.artifact.artifact_id),
                                     "attempt_id": str(grant.attempt.attempt_id), "worker_id": grant.worker_id})
        return Response({"grant_id": str(grant.grant_id), "artifact_id": str(grant.artifact.artifact_id),
                         "expires_at": grant.expires_at.isoformat(),
                         "download_path": f"/api/v1/workers/artifact-grants/{grant.grant_id}/download/"}, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def revoke(request, grant_id):
    if not role_at_least(getattr(request, "modelanvil_role", None), Role.ADMIN):
        record_audit("update", "worker_artifact_grant", grant_id,
                     actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
                     actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
                     input_snapshot={"path": request.path, "role": getattr(request, "modelanvil_role", None)},
                     result="denied",
                     tenant_id=get_active_tenant())
        raise PermissionDenied()
    with transaction.atomic():
        grant = WorkerArtifactGrant.all_objects.select_for_update().filter(
            tenant_id=get_active_tenant(), grant_id=grant_id,
        ).first()
        if grant is None:
            raise NotFound()
        if grant.revoked_at is None:
            grant.revoked_at = timezone.now()
            grant.save(update_fields=("revoked_at", "updated_at"))
            record_audit("update", "worker_artifact_grant", grant.grant_id,
                         actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
                         input_snapshot={"revoked": True})
        return Response({"ok": True, "revoked": True})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download(request, grant_id):
    if getattr(request, "modelanvil_actor_kind", None) != "worker_credential":
        raise PermissionDenied("Use the bound worker credential for this grant.")
    content = GrantDownload(tenant_id=get_active_tenant(), grant_id=grant_id,
                            worker_id=request.modelanvil_worker_id, credential_id=request.auth.pk)
    response = StreamingHttpResponse(content, content_type=content.artifact.media_type)
    response["Content-Length"] = str(content.artifact.byte_size)
    response["ETag"] = f'"{content.artifact.sha256}"'
    response["X-ModelAnvil-Attempt-ID"] = content.attempt_id
    response["Content-Disposition"] = 'attachment; filename="artifact.bin"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
