"""Review destinations before changing project restrictions; export safe diagnostics only."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modelanvil.api.views.activation import selected_project
from modelanvil.core.models import ActivationEvent, ProjectPrivacyPolicy, record_audit
from modelanvil.core.privacy import origin, project_policy
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role


class PolicyInput(serializers.Serializer):
    offline = serializers.BooleanField()
    acquisition_origins = serializers.ListField(child=serializers.CharField(max_length=255), max_length=30)
    measurement_retention_days = serializers.IntegerField(min_value=1, max_value=365)

    def validate_acquisition_origins(self, values):
        from django.conf import settings
        if any(origin(value) != value or value not in settings.MODELANVIL_ACQUISITION_ORIGINS for value in values):
            raise serializers.ValidationError('Select exact origins approved by the installation owner. Paths, credentials and additional hosts cannot be granted here.')
        return sorted(set(values))

    def validate(self, attrs):
        if set(self.initial_data) != set(self.fields):
            raise serializers.ValidationError('Submit only offline, acquisition_origins and measurement_retention_days.')
        return attrs


class ProjectPrivacy(APIView):
    permission_classes = [IsAuthenticated, TenantRBAC]

    def initial(self, request, *args, **kwargs):
        self.required_role = Role.VIEWER if request.method in ('GET', 'HEAD', 'OPTIONS') else Role.ADMIN
        return super().initial(request, *args, **kwargs)

    def get(self, request):
        project = selected_project()
        return self.response(project)

    def response(self, project):
        response = Response(project_policy(project.tenant_id, project.pk))
        response['Cache-Control'] = 'no-store'
        return response

    @transaction.atomic
    def put(self, request):
        project = selected_project()
        form = PolicyInput(data=request.data); form.is_valid(raise_exception=True)
        ProjectPrivacyPolicy.all_objects.update_or_create(tenant_id=project.tenant_id, project=project, defaults=form.validated_data)
        record_audit('update', 'project_privacy', project.pk, input_snapshot={'offline': form.validated_data['offline'],
            'origin_count': len(form.validated_data['acquisition_origins']), 'measurement_retention_days': form.validated_data['measurement_retention_days']})
        return self.response(project)


class PurgeMeasurements(ProjectPrivacy):
    http_method_names = ['post', 'options']
    @transaction.atomic
    def post(self, request):
        project = selected_project()
        if request.data != {'confirm': 'delete_expired_measurements'}:
            raise serializers.ValidationError('Confirm delete_expired_measurements after reviewing the retention period. Product data and decisions are retained.')
        days = project_policy(project.tenant_id, project.pk)['measurement_retention_days']
        count, _ = ActivationEvent.all_objects.filter(tenant_id=project.tenant_id, project=project,
            created_at__lt=timezone.now()-timedelta(days=days)).delete()
        record_audit('delete', 'expired_measurements', project.pk, input_snapshot={'count': count, 'retention_days': days})
        return Response({'deleted_measurements': count, 'retention_days': days})

class Diagnostics(ProjectPrivacy):
    http_method_names = ['get', 'head', 'options']
    def get(self, request):
        from modelanvil.build_info import build_info
        from modelanvil.jobs.models import Job
        project = selected_project()
        if request.query_params:
            raise serializers.ValidationError('Diagnostic exports never include content. Remove optional parameters.')
        response = Response({'schema_version': 'modelanvil.private-diagnostics.v1', 'build': build_info(),
            'privacy': project_policy(project.tenant_id, project.pk),
            'job_counts': list(Job.all_objects.filter(tenant_id=project.tenant_id, project=project).values('status').annotate(count=Count('pk'))),
            'content_collection': False, 'retention': 'No server-side diagnostic bundle is retained. The downloaded copy is controlled by its owner.'})
        response['Cache-Control'] = 'no-store'
        response['Content-Disposition'] = 'attachment; filename="modelanvil-diagnostics.json"'
        return response

