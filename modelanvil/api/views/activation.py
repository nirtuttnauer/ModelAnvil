"""Authenticated, explicitly scoped local measurement. No arbitrary event payloads."""
from datetime import date

from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from modelanvil.core.activation import activation_report
from modelanvil.core.models import ActivationEvent
from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Project, Role, role_at_least


class EventInput(serializers.Serializer):
    event_id = serializers.UUIDField()
    session_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=['workspace_opened', 'activity'])
    active_milliseconds = serializers.IntegerField(min_value=0, max_value=60000, default=0)

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('Only event/session IDs, kind and active milliseconds are accepted. Content must not be submitted.')
        if attrs['kind'] == 'workspace_opened' and attrs['active_milliseconds']:
            raise serializers.ValidationError('Workspace-open events cannot contain active time.')
        return attrs


def selected_project():
    project = Project.all_objects.filter(pk=get_active_project(), tenant_id=get_active_tenant()).first()
    if project is None:
        raise NotFound('Select a project for local measurement.')
    return project


class ActivationEvents(APIView):
    permission_classes = [IsAuthenticated, TenantRBAC]
    required_role = Role.VIEWER
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'activation'

    def post(self, request):
        project = selected_project()
        serializer = EventInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        event, created = ActivationEvent.all_objects.get_or_create(tenant_id=project.tenant_id,
            project=project, event_id=data['event_id'], defaults={k: v for k, v in data.items() if k != 'event_id'})
        if any(getattr(event, k) != v for k, v in data.items()):
            return Response({'detail': 'Event ID already used for another measurement.'}, status=409)
        response = Response({'event_id': str(event.event_id)}, status=201 if created else 200)
        response['Cache-Control'] = 'no-store'
        return response


class ActivationReport(APIView):
    permission_classes = [IsAuthenticated, TenantRBAC]
    required_role = Role.VIEWER

    def get(self, request):
        project = selected_project() if get_active_project() else None
        if project is None and not role_at_least(getattr(request, 'modelanvil_role', None), Role.ADMIN):
            raise PermissionDenied('Select a project, or use an administrator credential for tenant totals.')
        try:
            week = date.fromisoformat(request.query_params['week']) if 'week' in request.query_params else None
        except ValueError as exc:
            raise serializers.ValidationError('Use an ISO date for week, for example 2026-10-19.') from exc
        response = Response(activation_report(get_active_tenant(), project, week))
        response['Cache-Control'] = 'no-store'
        return response
