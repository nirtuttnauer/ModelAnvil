"""Tenant-scoped registry APIs for data sources, runners, and budgets."""
from decimal import Decimal
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role, role_at_least
from modelanvil.core.models import record_audit
from modelanvil.data.models import DataSource, SourceSnapshot
from modelanvil.runners.models import AdapterRegistryEntry, RunnerManifest
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent


class TenantScopedViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    write_role = Role.ENGINEER

    def initial(self, request, *args, **kwargs):
        self.required_role = Role.VIEWER if request.method in ("GET", "HEAD", "OPTIONS") else getattr(self, "action_write_roles", {}).get(self.action, self.write_role)
        return super().initial(request, *args, **kwargs)

    def get_queryset(self):
        tenant_id = get_active_tenant()
        if tenant_id is None:
            return self.queryset.none()
        qs = self.queryset.filter(tenant_id=tenant_id)
        if hasattr(self.queryset.model, "project"):
            from modelanvil.identity.models import get_accessible_queryset
            accessible_pks = get_accessible_queryset(self.queryset.model).values("pk")
            qs = qs.filter(pk__in=accessible_pks)
        return qs

    def get_serializer(self, *args, **kwargs):
        """Scope all writable relations, including subclass/custom-action serializers."""
        from modelanvil.core.tenancy import get_active_project
        from modelanvil.identity.models import Project, get_accessible_queryset
        serializer = super().get_serializer(*args, **kwargs)
        if not hasattr(serializer, "fields"):
            return serializer
        tenant = get_active_tenant()
        project = get_active_project()
        for name, field in serializer.fields.items():
            qs = getattr(field, "queryset", None)
            if qs is None or field.read_only:
                continue
            if qs.model is Project:
                scoped = qs.filter(tenant_id=tenant) if tenant else qs.none()
                field.queryset = scoped.filter(pk=project) if project else scoped
            elif hasattr(qs.model, "tenant_id"):
                field.queryset = get_accessible_queryset(qs.model)
        # A scoped key cannot erase or move ownership by supplying null/project.
        incoming = kwargs.get("data")
        if incoming is not None and "project" in incoming and project:
            if str(incoming.get("project")) != str(project):
                raise serializers.ValidationError({"project": "Resource must belong to the active project."})
        return serializer

    def perform_create(self, serializer):
        kwargs = {"tenant_id": get_active_tenant()}
        if hasattr(serializer.Meta.model, "project"):
            from modelanvil.core.tenancy import get_active_project
            active_project = get_active_project()
            if active_project:
                kwargs["project_id"] = active_project
        serializer.save(**kwargs)


class DataSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataSource
        fields = ("source_id", "project", "name", "kind", "configuration", "enabled", "suspended_reason", "created_at", "updated_at")
        read_only_fields = ("source_id", "created_at", "updated_at")


class DataSourceViewSet(TenantScopedViewSet):
    queryset = DataSource.objects.all()
    serializer_class = DataSourceSerializer
    lookup_field = "source_id"


class SourceSnapshotSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "source" in self.fields:
            from modelanvil.identity.models import get_accessible_queryset
            self.fields["source"].queryset = get_accessible_queryset(DataSource)

    class Meta:
        model = SourceSnapshot
        fields = ("snapshot_id", "project", "source", "source_revision", "manifest_digest", "state", "item_count", "failure_count", "started_at", "completed_at", "detail")
        read_only_fields = ("snapshot_id", "manifest_digest", "state", "item_count", "failure_count", "started_at", "completed_at")


class SourceSnapshotViewSet(TenantScopedViewSet):
    queryset = SourceSnapshot.objects.select_related("source")
    serializer_class = SourceSnapshotSerializer
    lookup_field = "snapshot_id"

    def perform_create(self, serializer):
        source = serializer.validated_data["source"]
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_project
        if not check_resource_access(source, get_active_project(), get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        kwargs = {"tenant_id": get_active_tenant()}
        active_project = get_active_project() or getattr(source, "project_id", None)
        if active_project:
            kwargs["project_id"] = active_project
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        if "source" in serializer.validated_data:
            source = serializer.validated_data["source"]
            from modelanvil.identity.models import check_resource_access
            from modelanvil.core.tenancy import get_active_project
            if not check_resource_access(source, get_active_project(), get_active_tenant()):
                from rest_framework.exceptions import NotFound
                raise NotFound()
        serializer.save()


class RunnerManifestSerializer(serializers.ModelSerializer):
    class Meta:
        model = RunnerManifest
        fields = ("id", "manifest_id", "name", "version", "digest", "manifest", "enabled", "compatibility", "created_at", "updated_at")
        read_only_fields = ("manifest_id", "created_at", "updated_at")


class RunnerManifestViewSet(TenantScopedViewSet):
    queryset = RunnerManifest.objects.all()
    serializer_class = RunnerManifestSerializer
    lookup_field = "manifest_id"
    write_role = Role.ADMIN


class AdapterRegistrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AdapterRegistryEntry
        fields = ("entry_id", "name", "version", "manifest_digest", "manifest", "enabled", "compatibility", "created_at", "updated_at")
        read_only_fields = ("entry_id", "created_at", "updated_at")


class AdapterRegistryViewSet(TenantScopedViewSet):
    queryset = AdapterRegistryEntry.objects.all()
    serializer_class = AdapterRegistrySerializer
    lookup_field = "entry_id"
    write_role = Role.MANAGER


class BudgetPolicySerializer(serializers.ModelSerializer):
    allowance = serializers.SerializerMethodField()

    def get_allowance(self, policy):
        period_start, _ = BudgetReservation.current_commitment(policy)
        amounts = BudgetReservation.all_objects.filter(policy=policy, period_start=period_start).aggregate(
            reserved=Sum('estimated_amount', filter=Q(state=BudgetReservation.State.RESERVED)),
            settled=Sum('settled_amount', filter=Q(state=BudgetReservation.State.SETTLED)))
        reserved, settled = amounts['reserved'] or Decimal('0'), amounts['settled'] or Decimal('0')
        return {'scope': 'tenant', 'period_start': str(period_start),
                'reserved_amount': str(reserved), 'settled_amount': str(settled),
                'remaining_amount': str(max(Decimal('0'), policy.limit_amount - reserved - settled))}

    def validate_name(self, value):
        existing = BudgetPolicy.all_objects.filter(tenant_id=get_active_tenant(), name=value)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError('This policy name already exists. Inspect the existing policy before retrying.')
        return value

    def validate(self, attrs):
        value = lambda field, default=None: attrs.get(field, getattr(self.instance, field, default))
        if value('limit_amount', Decimal('0')) <= 0:
            raise serializers.ValidationError({'limit_amount': 'Use a positive budget limit.'})
        if value('unit') in ('training_steps', 'bank_acquisition_records', 'evaluation_cases', 'embedding_attempts') and value('currency', ''):
            raise serializers.ValidationError({'currency': 'This policy limits resource quantities; leave currency empty.'})
        if self.instance:
            if self.instance.reservations.exists() and any(value(field) != getattr(self.instance, field)
                    for field in ('period', 'unit', 'currency')):
                raise serializers.ValidationError('A policy with reservations retains its period, unit and currency. Create a new policy.')
            _, commitment = BudgetReservation.current_commitment(self.instance)
            if value('limit_amount') < commitment:
                raise serializers.ValidationError({'limit_amount': 'The limit cannot be below already committed usage and active reservations.'})
        return attrs

    class Meta:
        model = BudgetPolicy
        fields = ("policy_id", "name", "period", "unit", "limit_amount", "currency", "enabled", "stop_behavior", "allowance", "created_at", "updated_at")
        read_only_fields = ("policy_id", "allowance", "created_at", "updated_at")


class BudgetPolicyViewSet(TenantScopedViewSet):
    queryset = BudgetPolicy.objects.all()
    serializer_class = BudgetPolicySerializer
    lookup_field = "policy_id"
    write_role = Role.ADMIN

    @action(detail=False, methods=['get'])
    def permissions(self, request):
        return Response({'can_administer': role_at_least(getattr(request, 'modelanvil_role', None), Role.ADMIN),
                         'scope': 'tenant'})

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                super().perform_create(serializer)
        except IntegrityError as exc:
            raise serializers.ValidationError({'name': 'Policy registration conflicted. Refresh policies before retrying.'}) from exc
        record_audit('create', 'budget_policy', serializer.instance.policy_id,
                     input_snapshot={'unit': serializer.instance.unit, 'limit_amount': str(serializer.instance.limit_amount)})

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        # Use the same lock as reservation admission while validating a new limit.
        self.queryset = self.queryset.select_for_update()
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        serializer.save()
        record_audit('update', 'budget_policy', serializer.instance.policy_id,
                     input_snapshot={'enabled': serializer.instance.enabled, 'limit_amount': str(serializer.instance.limit_amount)})


class BudgetReservationSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    period_start = serializers.DateField(read_only=True)
    def get_source(self, obj):
        from modelanvil.api.ledger_source import reservation_source
        return reservation_source(obj)

    unit = serializers.CharField(source="policy.unit", read_only=True)
    currency = serializers.CharField(source="policy.currency", read_only=True)
    policy_name = serializers.CharField(source="policy.name", read_only=True)
    class Meta:
        model = BudgetReservation
        fields = ("reservation_id", "policy", "policy_name", "unit", "currency", "job_id", "estimated_amount", "settled_amount", "state", "reserved_at", "settled_at", "period_start", "source")
        read_only_fields = fields


class BudgetReservationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BudgetReservation.objects.select_related("policy")
    serializer_class = BudgetReservationSerializer
    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    lookup_field = "reservation_id"

    def get_queryset(self):
        from modelanvil.api.ledger_filters import ledger_filters
        tenant = get_active_tenant()
        qs = self.queryset.filter(tenant_id=tenant) if tenant else self.queryset.none()
        return ledger_filters(self.request, qs, reservation=True)[0]


class UsageEventSerializer(serializers.ModelSerializer):
    source = serializers.SerializerMethodField()
    adjustments = serializers.SerializerMethodField()
    reservation_id = serializers.UUIDField(source='reservation.reservation_id', read_only=True, allow_null=True)
    def get_source(self, obj):
        from modelanvil.api.ledger_source import reservation_source
        return reservation_source(obj.reservation)
    def get_adjustments(self, obj):
        from modelanvil.budgets.models import UsageAdjustment
        return [{'adjustment_id': str(item.adjustment_id), 'amount_delta': str(item.amount_delta), 'reason': item.reason,
            'source_event_key': item.source_event_key, 'created_at': item.created_at} for item in
            UsageAdjustment.all_objects.filter(tenant_id=obj.tenant_id, usage_event=obj)]

    net_amount = serializers.DecimalField(
        max_digits=24, decimal_places=6, read_only=True, allow_null=True,
    )

    class Meta:
        model = UsageEvent
        fields = ("usage_id", "provider_event_key", "quantity", "unit", "reservation", "rate_revision", "amount", "currency", "net_amount", "occurred_at", "observed_at", "detail", "source", "adjustments", "reservation_id")
        read_only_fields = fields


class UsageEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UsageEvent.objects.select_related("reservation")
    serializer_class = UsageEventSerializer
    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    lookup_field = "usage_id"

    def get_queryset(self):
        from modelanvil.api.ledger_filters import ledger_filters
        tenant = get_active_tenant()
        qs = self.queryset.filter(tenant_id=tenant) if tenant else self.queryset.none()
        return ledger_filters(self.request, qs)[0]

    @action(detail=False, methods=['get'])
    @transaction.atomic
    def export(self, request):
        from modelanvil.api.ledger_filters import ledger_filters
        from django.utils import timezone
        cutoff = timezone.now()
        events = self.get_queryset().filter(created_at__lte=cutoff)
        reservations, scope = ledger_filters(request, BudgetReservation.all_objects.filter(tenant_id=get_active_tenant()), reservation=True)
        event_count, reservation_count = events.count(), reservations.count()
        rows = list(events[:20000]); holds = list(reservations[:20000])
        return Response({'scope': scope, 'as_of': cutoff, 'event_count': event_count, 'reservation_count': reservation_count,
            'complete': event_count <= 20000 and reservation_count <= 20000,
            'limits': 'Bounded local export supports 20,000 events and 20,000 reservations; larger exports are explicitly partial.',
            'events': UsageEventSerializer(rows, many=True).data,
            'reservations': BudgetReservationSerializer(holds, many=True).data})

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """Aggregate cost and usage breakdown for the active tenant."""
        tenant_id = get_active_tenant()
        if not tenant_id:
            return Response({"error": "No active tenant"}, status=400)
        from modelanvil.api.ledger_filters import ledger_filters
        events, scope = ledger_filters(request, self.get_queryset())
        by_unit = {}
        for ev in events:
            unit = (ev.unit, ev.currency)
            if unit not in by_unit:
                by_unit[unit] = {
                    "unit": ev.unit,
                    "total_quantity": Decimal("0"),
                    "total_amount": Decimal("0"),
                    "event_count": 0,
                    "currency": ev.currency,
                    "priced_event_count": 0,
                    "unpriced_event_count": 0,
                }
            by_unit[unit]["total_quantity"] += ev.quantity
            net = ev.net_amount()
            if net is None:
                by_unit[unit]["unpriced_event_count"] += 1
            else:
                by_unit[unit]["total_amount"] += net
                by_unit[unit]["priced_event_count"] += 1
            by_unit[unit]["event_count"] += 1

        policies = BudgetPolicy.objects.filter(tenant_id=tenant_id)
        active_reservations = BudgetReservation.objects.filter(
            tenant_id=tenant_id, state=BudgetReservation.State.RESERVED
        )
        active_reservations, _ = ledger_filters(request, active_reservations, reservation=True)
        reserved = {}
        for reservation in active_reservations.select_related("policy"):
            key = (reservation.policy.unit, reservation.policy.currency)
            group = reserved.setdefault(key, {"unit": key[0], "currency": key[1], "reserved_amount": Decimal("0"), "reservation_count": 0})
            group["reserved_amount"] += reservation.estimated_amount
            group["reservation_count"] += 1
        reserved_rows = [{**row, "reserved_amount": str(row["reserved_amount"])} for row in reserved.values()]

        return Response({
            "tenant_id": str(tenant_id),
            "scope": scope,
            "observed_at": timezone.now(),
            "usage_by_unit": [
                {
                    "unit": data["unit"],
                    "total_quantity": str(data["total_quantity"]),
                    "total_amount": str(data["total_amount"]) if data["priced_event_count"] else None,
                    "event_count": data["event_count"],
                    "currency": data["currency"],
                    "priced_event_count": data["priced_event_count"],
                    "unpriced_event_count": data["unpriced_event_count"],
                }
                for u, data in by_unit.items()
            ],
            "total_policies": policies.count(),
            "active_reservations_count": active_reservations.count(),
            "reserved_by_unit": reserved_rows,
            "total_reserved_amount": reserved_rows[0]["reserved_amount"] if len(reserved_rows) == 1 else ("0" if not reserved_rows else None),
        })
