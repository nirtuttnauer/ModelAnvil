"""Explicit ledger scope and UTC filters; tenant policies remain shared."""
from datetime import datetime, time, timedelta, timezone
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from modelanvil.core.tenancy import get_active_project
from modelanvil.jobs.access import accessible_jobs
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.runners.models import AlignmentRun


class LedgerFilters(serializers.Serializer):
    scope = serializers.ChoiceField(choices=['project', 'tenant'], required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    unit = serializers.CharField(max_length=64, required=False, allow_blank=True)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)

    def validate(self, data):
        if data.get('date_from') and data.get('date_to') and data['date_from'] > data['date_to']:
            raise serializers.ValidationError('Start date must not follow end date.')
        return data


def ledger_filters(request, queryset, *, reservation=False):
    form = LedgerFilters(data={key: value for key, value in request.query_params.items() if key in LedgerFilters().fields})
    form.is_valid(raise_exception=True); filters = form.validated_data
    project = get_active_project()
    scope = filters.get('scope', 'project' if project else 'tenant')
    if scope == 'tenant' and getattr(request.user, 'project_id', None):
        raise PermissionDenied('This key can inspect its project ledger only.')
    if scope == 'project' and project:
        ids = list(accessible_jobs().values_list('job_id', flat=True))
        ids.extend(get_accessible_queryset(AlignmentRun).values_list('run_id', flat=True))
        queryset = queryset.filter(job_id__in=ids) if reservation else queryset.filter(Q(reservation__job_id__in=ids) | Q(detail__project_id=str(project)))
    field = 'reserved_at' if reservation else 'occurred_at'
    if filters.get('date_from'):
        queryset = queryset.filter(**{field+'__gte': datetime.combine(filters['date_from'], time.min, timezone.utc)})
    if filters.get('date_to'):
        queryset = queryset.filter(**{field+'__lt': datetime.combine(filters['date_to']+timedelta(days=1), time.min, timezone.utc)})
    if filters.get('unit'):
        queryset = queryset.filter(**{'policy__unit' if reservation else 'unit': filters['unit']})
    if 'currency' in filters:
        queryset = queryset.filter(**{'policy__currency' if reservation else 'currency': filters['currency']})
    return queryset, {'scope': scope, 'project_id': str(project) if scope == 'project' and project else None,
        'filters': {key: str(value) for key, value in filters.items()}, 'timezone': 'UTC',
        'policy_scope': 'Tenant-wide shared policies; filtered project usage does not change policy allowance.'}
