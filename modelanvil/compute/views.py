from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.compute.models import ComputeAllocation
from modelanvil.compute.plugins import PluginError, ProviderError, compute_provider, definition, installed_plugins
from modelanvil.compute.service import allocate, reconcile
from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role, role_at_least
from modelanvil.jobs.models import WorkerPool


def actor(request):
    return {"actor_id": getattr(request, "modelanvil_actor_id", None),
            "actor_kind": getattr(request, "modelanvil_actor_kind", "system")}


class AllocationSerializer(serializers.ModelSerializer):
    pool = serializers.IntegerField(source="worker.pool_id")
    worker_connected = serializers.SerializerMethodField()

    def get_worker_connected(self, obj):
        from django.utils import timezone
        return bool(obj.worker.last_heartbeat_at and obj.worker.last_heartbeat_at >= timezone.now() - timezone.timedelta(seconds=60)
                    and obj.state == "active")

    class Meta:
        model = ComputeAllocation
        fields = ("allocation_id", "request_id", "plugin_id", "plugin_digest", "pool", "worker_id", "spec",
                  "provider_resource_id", "provider_status", "state", "worker_connected", "release_requested",
                  "expires_at", "released_at", "error_code", "created_at")
        read_only_fields = fields


class AllocationRequest(serializers.Serializer):
    request_id = serializers.UUIDField()
    plugin_id = serializers.RegexField(r"^[a-z0-9][a-z0-9._-]{0,99}$")
    pool = serializers.PrimaryKeyRelatedField(queryset=WorkerPool.objects.all())
    spec = serializers.DictField()
    lifetime_seconds = serializers.IntegerField(min_value=60, max_value=86400)
    policy_id = serializers.UUIDField()


class AllocationViewSet(TenantScopedViewSet):
    queryset = ComputeAllocation.objects.select_related("worker")
    serializer_class = AllocationSerializer
    lookup_field = "allocation_id"
    write_role = Role.ADMIN
    http_method_names = ["get", "post", "head", "options"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method == "POST" and get_active_project():
            raise PermissionDenied("Compute management requires an organization-scoped administrator key.")

    def create(self, request, *args, **kwargs):
        if get_active_project():
            raise PermissionDenied("Compute provisioning requires an organization-scoped administrator key.")
        serializer = AllocationRequest(data=request.data)
        serializer.fields["pool"].queryset = WorkerPool.all_objects.filter(tenant_id=get_active_tenant())
        serializer.is_valid(raise_exception=True)
        try:
            result = allocate(tenant_id=get_active_tenant(), **serializer.validated_data, **actor(request))
        except (PluginError, ValueError) as exc:
            raise serializers.ValidationError(str(exc)) from None
        return Response(AllocationSerializer(result).data, status=201)

    @action(detail=True, methods=["post"])
    def refresh(self, request, allocation_id=None):
        return Response(AllocationSerializer(reconcile(self.get_object(), **actor(request))).data)

    @action(detail=True, methods=["post"])
    def release(self, request, allocation_id=None):
        if get_active_project():
            raise PermissionDenied("Compute release requires an organization-scoped administrator key.")
        return Response(AllocationSerializer(reconcile(self.get_object(), release=True, **actor(request))).data)


class PluginViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER

    def list(self, request):
        rows = []
        for plugin_id, entry in installed_plugins(get_active_tenant()).items():
            _, digest = definition(plugin_id, get_active_tenant(), entry["kind"])
            rows.append({"id": plugin_id, "kind": entry["kind"], "name": entry.get("name", plugin_id),
                         "digest": digest, "configuration_schema": entry["configuration_schema"],
                         "can_submit": role_at_least(getattr(request, "modelanvil_role", None), Role.ENGINEER),
                         "can_manage": not get_active_project() and role_at_least(getattr(request, "modelanvil_role", None), Role.ADMIN)})
        return Response({"results": rows})

    @action(detail=True, methods=["get"])
    def catalog(self, request, pk=None):
        try:
            provider = compute_provider(pk, get_active_tenant())
            return Response({"results": provider.catalog()})
        except PluginError:
            raise NotFound("Compute plugin is unavailable.") from None
        except ProviderError as exc:
            return Response({"detail": exc.code}, status=502)
        except Exception:
            return Response({"detail": "provider_catalog_unavailable"}, status=502)
