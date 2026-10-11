"""Read-only, tenant-scoped worker inventory, without worker secrets."""
from rest_framework import serializers
from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.jobs.models import Worker, WorkerPool


class PoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkerPool
        fields = ("id", "name", "status", "queue_name", "result_egress", "created_at")


class PoolViewSet(TenantScopedViewSet):
    queryset = WorkerPool.objects.all()
    serializer_class = PoolSerializer
    http_method_names = ["get", "head", "options"]


class WorkerSerializer(serializers.ModelSerializer):
    pool_name = serializers.CharField(source="pool.name", read_only=True)

    class Meta:
        model = Worker
        fields = ("id", "name", "pool", "pool_name", "status", "slots", "capabilities", "last_heartbeat_at", "created_at")


class WorkerViewSet(TenantScopedViewSet):
    queryset = Worker.objects.select_related("pool")
    serializer_class = WorkerSerializer
    http_method_names = ["get", "head", "options"]
