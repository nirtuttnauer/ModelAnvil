"""Read-only tenant audit trail API."""
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.core import signing
from django.db.models import Max, Q
from django.utils import timezone
from datetime import datetime, time, timedelta, timezone as utc
from rest_framework.permissions import IsAuthenticated
from modelanvil.core.models import AuditEvent
from modelanvil.core.tenancy import get_active_tenant, get_active_project
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = ("event_id", "project_id", "actor_id", "actor_kind", "action", "resource_type", "resource_id", "input_snapshot", "result", "created_at")
        read_only_fields = fields


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditEvent.objects.all()
    serializer_class = AuditEventSerializer
    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    lookup_field = "event_id"

    def _filtered(self, request, raw=None):
        raw = dict(raw or request.query_params.items())
        form = AuditFilters(data={key: value for key, value in raw.items() if key in AuditFilters().fields})
        form.is_valid(raise_exception=True); filters = form.validated_data
        tenant = get_active_tenant(); project = get_active_project()
        qs = self.queryset.filter(tenant_id=tenant) if tenant else self.queryset.none()
        scope = filters.get('scope', 'project' if project else 'tenant')
        if scope == 'tenant' and getattr(request.user, 'project_id', None):
            raise PermissionDenied('This key can investigate its project audit only.')
        if scope == 'project' and project:
            qs = qs.filter(Q(project_id=project) | Q(project_id__isnull=True, resource_type__in=['budget_policy','worker_pool','worker','runner_manifest']))
        if filters.get('project'):
            if scope == 'project' and project and filters['project'] != project:
                raise PermissionDenied('Select the project in the workspace or use an authorized tenant-wide audit scope.')
            if getattr(request.user, 'project_id', None) and filters['project'] != request.user.project_id:
                raise PermissionDenied('Project audit is outside this key scope.')
            qs = qs.filter(project_id=filters['project'])
        for name, field in [('actor','actor_id'), ('action','action'), ('outcome','result'), ('resource_type','resource_type'), ('resource','resource_id')]:
            if filters.get(name): qs = qs.filter(**{field: filters[name]})
        if filters.get('date_from'): qs = qs.filter(created_at__gte=datetime.combine(filters['date_from'], time.min, utc.utc))
        if filters.get('date_to'): qs = qs.filter(created_at__lt=datetime.combine(filters['date_to']+timedelta(days=1), time.min, utc.utc))
        if filters.get('q'): qs = qs.filter(Q(action__icontains=filters['q']) | Q(resource_type__icontains=filters['q']))
        return qs, {key: str(value) for key, value in filters.items()}, scope

    def get_queryset(self):
        return self._filtered(self.request)[0]

    @action(detail=True, methods=['get'], url_path='resource-state')
    def resource_state(self, request, event_id=None):
        from modelanvil.api.audit_resource import audit_resource_state
        return Response(audit_resource_state(self.get_object()))

    @action(detail=False, methods=['get'])
    def export(self, request):
        principal = str(request.user.pk); project = str(get_active_project() or '')
        cursor = request.query_params.get('cursor')
        if cursor:
            try: snapshot = signing.loads(cursor, salt='audit-export-v1', max_age=3600)
            except signing.BadSignature: raise serializers.ValidationError('Export cursor is invalid or expired.') from None
            if snapshot['principal'] != principal or snapshot['project'] != project or snapshot['tenant'] != str(get_active_tenant()):
                raise PermissionDenied('Export cursor belongs to another principal or workspace scope.')
            qs, filters, scope = self._filtered(request, snapshot['filters'])
        else:
            qs, filters, scope = self._filtered(request)
            maximum = qs.aggregate(maximum=Max('id'))['maximum'] or 0
            snapshot = {'principal': principal, 'project': project, 'tenant': str(get_active_tenant()),
                'filters': filters, 'max_id': maximum, 'last_id': maximum+1, 'total': qs.filter(id__lte=maximum).count(),
                'sent': 0, 'as_of': timezone.now().isoformat()}
        page = list(qs.filter(id__lte=snapshot['max_id'], id__lt=snapshot['last_id']).order_by('-id')[:500])
        snapshot['sent'] += len(page)
        if page: snapshot['last_id'] = page[-1].pk
        more = len(page) == 500 and snapshot['sent'] < min(snapshot['total'], 50000)
        return Response({'results': self.get_serializer(page, many=True).data,
            'next_cursor': signing.dumps(snapshot, salt='audit-export-v1') if more else None,
            'metadata': {'as_of': snapshot['as_of'], 'scope': scope, 'project_id': snapshot['project'] or None,
                'filters': filters, 'timezone': 'UTC', 'total_count': snapshot['total'], 'exported_count': snapshot['sent'],
                'complete': not more and snapshot['sent'] == snapshot['total'],
                'limits': '500 rows per page; 50,000 rows per local export. Further rows are explicitly partial.'}})


class AuditFilters(serializers.Serializer):
    scope = serializers.ChoiceField(choices=['project','tenant'], required=False)
    project = serializers.UUIDField(required=False)
    actor = serializers.UUIDField(required=False)
    action = serializers.CharField(max_length=32, required=False)
    outcome = serializers.ChoiceField(choices=['ok','denied','error'], required=False)
    resource_type = serializers.CharField(max_length=64, required=False)
    resource = serializers.UUIDField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    q = serializers.CharField(max_length=200, required=False)
    def validate(self, values):
        if values.get('date_from') and values.get('date_to') and values['date_from'] > values['date_to']:
            raise serializers.ValidationError('Start date must not follow end date.')
        return values
