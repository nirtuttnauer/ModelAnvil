"""Read-only, tenant-scoped worker inventory, without worker secrets."""
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.jobs.models import Worker, WorkerPool, Job, JobAttempt
from modelanvil.identity.models import Role, role_at_least
from modelanvil.core.models import record_audit


def require_operator(request):
    if not role_at_least(request.modelanvil_role, Role.ADMIN):
        raise PermissionDenied('Compute administration requires an administrator.')


class PoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkerPool
        fields = ("id", "name", "status", "queue_name", "result_egress", "created_at")


class PoolViewSet(TenantScopedViewSet):
    queryset = WorkerPool.objects.all()
    serializer_class = PoolSerializer
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request):
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed('POST')

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def drain(self, request, pk=None):
        require_operator(request)
        pool = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
        draining = serializers.BooleanField().run_validation(request.data.get('draining', True))
        pool.status = 'draining' if draining else 'active'; pool.save(update_fields=['status', 'updated_at'])
        record_audit('pool.drain' if draining else 'pool.resume', 'worker_pool', None,
            actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
            input_snapshot={'pool_id': pool.pk, 'active_jobs': pool.jobs.filter(status='running').count(), 'completion_policy': 'finish active jobs; block new claims'})
        return Response(self.get_serializer(pool).data)

    @action(detail=True, methods=['post'], url_path='result-policy')
    @transaction.atomic
    def result_policy(self, request, pk=None):
        require_operator(request)
        pool = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
        if pool.jobs.filter(status='running').exists():
            raise serializers.ValidationError('Wait until all active or unresolved ownership is released before changing result egress.')
        pool.result_egress = serializers.ChoiceField(choices=WorkerPool.ResultEgress.values).run_validation(request.data.get('result_egress'))
        pool.save(update_fields=['result_egress', 'updated_at'])
        record_audit('pool.result_policy', 'worker_pool', None, actor_id=request.modelanvil_actor_id,
            actor_kind=request.modelanvil_actor_kind, input_snapshot={'pool_id': pool.pk, 'result_egress': pool.result_egress})
        return Response(self.get_serializer(pool).data)


class WorkerSerializer(serializers.ModelSerializer):
    pool_name = serializers.CharField(source="pool.name", read_only=True)
    connection_state = serializers.SerializerMethodField()
    capacity = serializers.SerializerMethodField()

    def get_capacity(self, obj):
        from modelanvil.jobs.setup import connection_state
        active = list(JobAttempt.all_objects.filter(tenant_id=obj.tenant_id, worker=obj, status=JobAttempt.Status.RUNNING).select_related('job'))
        allocated = sum(attempt.slots_reserved for attempt in active)
        connected = connection_state(obj) == 'connected' and obj.status in ('available', 'busy') and not obj.drain_requested and obj.pool.status == 'active'
        return {'configured_slots': obj.slots + allocated, 'allocated_slots': allocated,
            'free_slots': obj.slots if connected else None, 'active_jobs': len(active),
            'ownership_unresolved': any(not attempt.lease_expires_at or attempt.lease_expires_at <= timezone.now()
                or attempt.job.status != 'running' or attempt.job.claimed_by_id != obj.pk for attempt in active),
            'drain_requested': obj.drain_requested, 'drain_acknowledged_at': obj.drain_acknowledged_at,
            'observed_at': timezone.now(), 'reason': 'Fresh worker and current allocation records.' if connected else 'Free capacity is unavailable while disconnected, stale, offline or drained.'}

    def get_connection_state(self, obj):
        from modelanvil.jobs.setup import connection_state
        return connection_state(obj)

    class Meta:
        model = Worker
        fields = ("id", "name", "pool", "pool_name", "status", "slots", "capabilities", "capacity", "connection_state", "last_heartbeat_at", "created_at")


class WorkerViewSet(TenantScopedViewSet):
    queryset = Worker.objects.select_related("pool")
    serializer_class = WorkerSerializer
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request):
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed('POST')

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def drain(self, request, pk=None):
        require_operator(request)
        worker = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
        draining = serializers.BooleanField().run_validation(request.data.get('draining', True))
        worker.drain_requested = draining; worker.drain_requested_at = timezone.now() if draining else None
        worker.drain_acknowledged_at = None
        if worker.status != Worker.Status.OFFLINE:
            worker.status = Worker.Status.DRAINING if draining else Worker.Status.BUSY if worker.claimed_jobs.filter(status='running').exists() else Worker.Status.AVAILABLE
        worker.save(update_fields=['drain_requested', 'drain_requested_at', 'drain_acknowledged_at', 'status', 'updated_at'])
        record_audit('worker.drain' if draining else 'worker.resume', 'worker', None,
            actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
            input_snapshot={'worker_id': worker.pk, 'completion_policy': 'finish active jobs; block new claims'})
        return Response(self.get_serializer(worker).data)

    @action(detail=False, methods=['get'], url_path='queue-diagnosis')
    def queue_diagnosis(self, request):
        from modelanvil.jobs.access import accessible_jobs
        rows = []
        jobs = accessible_jobs().filter(status='queued').select_related('pool')
        for job in jobs.order_by('created_at')[:100]:
            workers = list(Worker.all_objects.filter(tenant_id=job.tenant_id, pool=job.pool).select_related('pool'))
            observed = [(w, WorkerSerializer(w).data['capacity']) for w in workers]
            matching = [(w, c) for w, c in observed if all(w.capabilities.get(k) == v for k, v in job.requirements.items() if k != 'slots') and c['configured_slots'] >= job.requirements.get('slots', 1)]
            capacity = [c for _, c in matching]
            reason = 'Pool is draining.' if job.pool.status != 'active' else 'No registered worker matches the required capabilities and configured slots.' if not matching else 'Matching workers have stale, disconnected or drained capacity.' if all(c['free_slots'] is None for c in capacity) else 'Matching workers are allocated; this job is waiting for free slots.' if not any((c['free_slots'] or 0) >= job.requirements.get('slots', 1) for c in capacity) else 'A matching worker has observed capacity; waiting for its next claim.'
            rows.append({'job_id': str(job.job_id), 'name': job.name, 'pool_id': job.pool_id,
                'queue_age_seconds': round((timezone.now()-job.created_at).total_seconds(), 1),
                'requirements': job.requirements, 'matching_workers': len(matching), 'reason': reason})
        return Response({'rows': rows, 'total': jobs.count(), 'truncated': jobs.count() > 100, 'observed_at': timezone.now()})
