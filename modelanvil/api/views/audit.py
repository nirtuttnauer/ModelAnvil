"""Read-only tenant audit trail API."""
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from modelanvil.core.models import AuditEvent
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = ("event_id", "actor_id", "actor_kind", "action", "resource_type", "resource_id", "input_snapshot", "result", "created_at")
        read_only_fields = fields


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditEvent.objects.all()
    serializer_class = AuditEventSerializer
    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    lookup_field = "event_id"

    def get_queryset(self):
        tenant = get_active_tenant()
        return self.queryset.filter(tenant_id=tenant) if tenant else self.queryset.none()
