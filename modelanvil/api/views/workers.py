"""Worker protocol endpoints (WP-03).

Increment A implements the control-plane side of the durable execution
contract from ADR-001:

* ``POST /workers/register``   — a worker (or gateway) registers itself into
  a pool, declaring its capabilities and slot count.
* ``POST /workers/claim``      — an available worker atomically claims a
  compatible job attempt, receiving a fencing token and a lease.
* ``POST /workers/heartbeat``  — renews the lease; an expired lease is
  reconciled by the control plane.
* ``POST /workers/result``     — a worker commits a verified result; stale
  (lower-fencing-token) results are rejected.

Workers authenticate with the same bearer API keys; the active tenant is
resolved from the key so a worker can only claim/commit within its own
tenant. In a hybrid deployment the scoped gateway proxies these endpoints
outbound — the worker never needs an inbound broker endpoint.

The claim / lease-renewal / result-commit logic lives in
:mod:`modelanvil.jobs.models` (``claim_job`` / ``renew_lease`` /
``commit_result``) — the canonical, transactional implementation of the
protocol. These views only translate HTTP <-> that protocol and enforce
tenant scoping.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import path
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from contracts import ApiError, ErrorCode, validate_envelope
from modelanvil.core.models import record_audit
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.models import Role, role_at_least
from modelanvil.jobs.models import (
    Job,
    JobAttempt,
    Worker,
    WorkerCredential,
    WorkerPool,
    claim_job,
    commit_result,
    dispatch_topic,
    generate_worker_credential,
    renew_lease,
)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
class WorkerRegisterSerializer(serializers.Serializer):
    worker_name = serializers.CharField(max_length=200)
    pool = serializers.CharField(max_length=100)
    capabilities = serializers.DictField(default=dict)
    slots = serializers.IntegerField(default=1, min_value=1, max_value=1024)
    runner_manifest = serializers.DictField(required=False)


class WorkerClaimSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField(min_value=1)
    pool = serializers.CharField(max_length=100)
    # Optional explicit job; if omitted the control plane picks one.
    job_id = serializers.UUIDField(required=False, allow_null=True)


class WorkerHeartbeatSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField(min_value=1)
    attempt_id = serializers.UUIDField()
    fencing_token = serializers.CharField(min_length=1, max_length=64, trim_whitespace=False)
    progress = serializers.FloatField(required=False, min_value=0.0, max_value=1.0)


class WorkerResultSerializer(serializers.Serializer):
    worker_id = serializers.IntegerField(min_value=1)
    attempt_id = serializers.UUIDField()
    fencing_token = serializers.CharField(min_length=1, max_length=64, trim_whitespace=False)
    status = serializers.ChoiceField(choices=["succeeded", "failed", "interrupted"])
    result_envelope = serializers.DictField(required=False)
    error = serializers.CharField(required=False, allow_blank=True)
    artifacts = serializers.ListField(child=serializers.DictField(), required=False, default=list)


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------
def _error(code: str, message: str, status_code: int) -> Response:
    api_error = ApiError(code, message, status_code)
    api_error.request_id = None
    return Response(api_error.to_dict(), status=status_code)


def _require_worker_admin(request) -> Response | None:
    if (
        getattr(request, "modelanvil_actor_kind", None) == "worker_credential"
        or not role_at_least(getattr(request, "modelanvil_role", None), Role.ADMIN)
    ):
        record_audit(
            action="admin_denied",
            resource_type="worker_administration",
            actor_id=getattr(request, "modelanvil_actor_id", None) or getattr(request.user, "id", None),
            actor_kind=getattr(request, "modelanvil_actor_kind", "api_key"),
            input_snapshot={"path": request.path, "method": request.method, "role": getattr(request, "modelanvil_role", None)},
            result="denied",
            tenant_id=get_active_tenant(),
        )
        return _error(ErrorCode.FORBIDDEN, "Administrator credentials are required.", 403)
    return None


def _authorize_worker_identity(request, worker_id: int) -> Response | None:
    if getattr(request, "modelanvil_actor_kind", None) == "worker_credential":
        if getattr(request, "modelanvil_worker_id", None) != worker_id:
            return _error(ErrorCode.FORBIDDEN, "Worker credential is bound to a different worker.", 403)
        return None
    return _require_worker_admin(request)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def register(request) -> Response:
    """Register a worker into a pool for the active tenant."""
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)
    denied = _require_worker_admin(request)
    if denied is not None:
        return denied

    ser = WorkerRegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    pool, _ = WorkerPool.objects.get_or_create(
        tenant_id=tenant, name=ser.validated_data["pool"]
    )
    worker = Worker(
        tenant_id=tenant,
        name=ser.validated_data["worker_name"],
        pool=pool,
        capabilities=ser.validated_data.get("capabilities", {}),
        slots=ser.validated_data["slots"],
        status=Worker.Status.AVAILABLE,
    )
    worker.save()
    worker_token, token_hash = generate_worker_credential()
    credential = WorkerCredential.objects.create(
        tenant_id=tenant,
        worker=worker,
        secret_hash=token_hash,
    )
    record_audit("create", "worker", input_snapshot={"worker_id": worker.id, "pool": pool.name})

    return Response(
        {
            "worker_id": str(worker.id),
            "pool": pool.name,
            "queue_name": dispatch_topic(tenant, pool.queue_name, pool.name),
            "status": worker.status,
            "slots": worker.slots,
            "worker_token": worker_token,
            "worker_token_expires_at": credential.expires_at.isoformat(),
            "result_egress": pool.result_egress,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def claim(request) -> Response:
    """Atomically claim a job attempt. Returns a fencing token + lease."""
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)

    ser = WorkerClaimSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    denied = _authorize_worker_identity(request, ser.validated_data["worker_id"])
    if denied is not None:
        return denied

    worker = Worker.objects.filter(
        id=ser.validated_data["worker_id"], tenant_id=tenant
    ).first()
    if worker is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Worker not found in this tenant.", 404)
    pool = WorkerPool.objects.filter(pk=worker.pool_id, tenant_id=tenant).first()
    if pool is None or pool.name != ser.validated_data["pool"]:
        return _error(ErrorCode.CONFLICT, "Requested pool does not match the registered worker.", 409)
    if pool.status != "active":
        return _error(ErrorCode.CONFLICT, "Worker pool is draining; not taking new work.", 409)
    if worker.status == Worker.Status.DRAINING:
        return _error(ErrorCode.CONFLICT, "Worker is draining; not taking new work.", 409)
    if worker.status == Worker.Status.OFFLINE:
        return _error(ErrorCode.CONFLICT, "Worker is offline; not taking new work.", 409)
    if worker.slots <= 0:
        return _error(ErrorCode.JOB_NOT_CLAIMABLE, "Worker has no free slots.", 409)

    # Optional explicit job (looked up within the tenant); otherwise the
    # control plane picks the highest-priority queued job in the pool.
    explicit_job: Job | None = None
    if ser.validated_data.get("job_id"):
        explicit_job = Job.objects.filter(
            job_id=ser.validated_data["job_id"], tenant_id=tenant
        ).first()
        if explicit_job is None:
            return _error(ErrorCode.RESOURCE_NOT_FOUND, "Job not found in this tenant.", 404)

    descriptor = claim_job(worker, explicit_job)
    if descriptor is None:
        return Response(
            {"claimed": False, "reason": "no_work"}, status=status.HTTP_200_OK
        )

    record_audit("job_lifecycle", "job", descriptor["job_id"], input_snapshot={"claim": str(worker.id)})

    return Response(
        {
            "claimed": True,
            "job_id": descriptor["job_id"],
            "attempt_id": descriptor["attempt_id"],
            "fencing_token": descriptor["fencing_token"],
            "lease_expires_at": descriptor["lease_expires_at"].isoformat(),
            "payload": descriptor["payload"],
            "tenant_id": descriptor["tenant_id"],
            "requirements": descriptor["requirements"],
            "result_egress": descriptor["result_egress"],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def heartbeat(request) -> Response:
    """Renew the lease on a running attempt."""
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)

    ser = WorkerHeartbeatSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    denied = _authorize_worker_identity(request, ser.validated_data["worker_id"])
    if denied is not None:
        return denied

    attempt = JobAttempt.objects.filter(
        attempt_id=ser.validated_data["attempt_id"], worker_id=ser.validated_data["worker_id"], tenant_id=tenant
    ).first()
    if attempt is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Attempt not found.", 404)

    ok = renew_lease(
        attempt,
        ser.validated_data["fencing_token"],
        ser.validated_data.get("progress"),
    )
    if not ok:
        return _error(ErrorCode.STALE_FENCE_TOKEN, "Stale fencing token; attempt is fenced.", 403)

    pool = WorkerPool.objects.filter(pk=attempt.job.pool_id, tenant_id=tenant).first()
    if pool is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Pool not found.", 404)
    return Response({
        "ok": True,
        "lease_expires_at": attempt.lease_expires_at.isoformat(),
        "desired_action": attempt.desired_action,
        "result_egress": pool.result_egress,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_result(request) -> Response:
    """Commit a verified result. Stale results are rejected."""
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)

    ser = WorkerResultSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    denied = _authorize_worker_identity(request, ser.validated_data["worker_id"])
    if denied is not None:
        return denied

    attempt = JobAttempt.objects.filter(
        attempt_id=ser.validated_data["attempt_id"], worker_id=ser.validated_data["worker_id"], tenant_id=tenant
    ).first()
    if attempt is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Attempt not found.", 404)

    pool = WorkerPool.objects.filter(pk=attempt.job.pool_id, tenant_id=tenant).first()
    if pool is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Pool not found.", 404)
    if pool.result_egress not in WorkerPool.ResultEgress.values or (
        pool.result_egress == WorkerPool.ResultEgress.METADATA_ONLY
        and ("result_envelope" in ser.validated_data or ser.validated_data.get("error")
             or ser.validated_data.get("artifacts"))
    ):
        return _error(ErrorCode.FORBIDDEN, "Result content is forbidden by the pool egress policy.", 403)

    # Validate the result envelope against the canonical schema if present.
    result_envelope = ser.validated_data.get("result_envelope")
    if result_envelope:
        try:
            validate_envelope(result_envelope)
        except Exception as exc:  # noqa: BLE001
            return _error(
                ErrorCode.VALIDATION_FAILED, f"Result envelope invalid: {exc}", 400
            )

    try:
        ok = commit_result(
            attempt,
            ser.validated_data["fencing_token"],
            ser.validated_data["status"],
            result_envelope=result_envelope,
            error=ser.validated_data.get("error", ""),
        )
    except ValidationError:
        return _error(ErrorCode.FORBIDDEN, "Result content is forbidden by the pool egress policy.", 403)
    if not ok:
        return _error(ErrorCode.STALE_FENCE_TOKEN, "Stale fencing token; result rejected.", 403)

    record_audit("job_lifecycle", "job", attempt.job.job_id, input_snapshot={"result": ser.validated_data["status"]})
    return Response({"ok": True, "status": ser.validated_data["status"]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def revoke_credential(request, worker_id: int) -> Response:
    """Revoke all active credentials for one tenant-owned worker."""
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)
    denied = _require_worker_admin(request)
    if denied is not None:
        return denied
    worker = Worker.objects.filter(pk=worker_id, tenant_id=tenant).first()
    if worker is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Worker not found in this tenant.", 404)
    WorkerCredential.objects.filter(
        worker=worker,
        tenant_id=tenant,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    record_audit("update", "worker", worker.id, input_snapshot={"credential_revoked": True})
    return Response({"ok": True, "credential_revoked": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def configure_result_egress(request, pool_id: int) -> Response:
    """Only a tenant administrator may change a pool's result-egress boundary."""
    denied = _require_worker_admin(request)
    if denied is not None:
        return denied
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)
    pool = WorkerPool.objects.select_for_update().filter(pk=pool_id, tenant_id=tenant).first()
    if pool is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Pool not found.", 404)
    mode = request.data.get("result_egress")
    if mode not in WorkerPool.ResultEgress.values:
        return _error(ErrorCode.VALIDATION_FAILED, "Invalid result-egress mode.", 400)
    pool.result_egress = mode
    pool.save(update_fields=("result_egress", "updated_at"))
    record_audit("update", "worker_pool", input_snapshot={"pool_id": pool.pk, "result_egress": mode})
    return Response({"ok": True, "result_egress": mode})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def drain_worker(request, worker_id: int) -> Response:
    """Mark a worker as draining. It will finish running jobs but accept no new claims."""
    denied = _require_worker_admin(request)
    if denied is not None:
        return denied
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)
    worker = Worker.objects.select_for_update().filter(pk=worker_id, tenant_id=tenant).first()
    if worker is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Worker not found in this tenant.", 404)
    worker.status = Worker.Status.DRAINING
    worker.save(update_fields=("status", "updated_at"))
    record_audit("update", "worker", worker.id, input_snapshot={"status": Worker.Status.DRAINING})
    return Response({"ok": True, "worker_id": worker.id, "status": worker.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def activate_worker(request, worker_id: int) -> Response:
    """Return a draining worker to available status."""
    denied = _require_worker_admin(request)
    if denied is not None:
        return denied
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)
    worker = Worker.objects.select_for_update().filter(pk=worker_id, tenant_id=tenant).first()
    if worker is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Worker not found in this tenant.", 404)
    worker.status = Worker.Status.AVAILABLE
    worker.save(update_fields=("status", "updated_at"))
    record_audit("update", "worker", worker.id, input_snapshot={"status": Worker.Status.AVAILABLE})
    return Response({"ok": True, "worker_id": worker.id, "status": worker.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def drain_pool(request, pool_id: int) -> Response:
    """Mark a pool as draining. All workers in the pool refuse new claims."""
    denied = _require_worker_admin(request)
    if denied is not None:
        return denied
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)
    pool = WorkerPool.objects.select_for_update().filter(pk=pool_id, tenant_id=tenant).first()
    if pool is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Pool not found.", 404)
    pool.status = "draining"
    pool.save(update_fields=("status", "updated_at"))
    record_audit("update", "worker_pool", pool.pk, input_snapshot={"status": "draining"})
    return Response({"ok": True, "pool_id": pool.pk, "status": pool.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def activate_pool(request, pool_id: int) -> Response:
    """Return a draining pool to active status."""
    denied = _require_worker_admin(request)
    if denied is not None:
        return denied
    tenant = get_active_tenant()
    if tenant is None:
        return _error(ErrorCode.FORBIDDEN, "No active tenant for worker.", 403)
    pool = WorkerPool.objects.select_for_update().filter(pk=pool_id, tenant_id=tenant).first()
    if pool is None:
        return _error(ErrorCode.RESOURCE_NOT_FOUND, "Pool not found.", 404)
    pool.status = "active"
    pool.save(update_fields=("status", "updated_at"))
    record_audit("update", "worker_pool", pool.pk, input_snapshot={"status": "active"})
    return Response({"ok": True, "pool_id": pool.pk, "status": pool.status})


urls = [
    path("register/", register, name="worker-register"),
    path("claim/", claim, name="worker-claim"),
    path("heartbeat/", heartbeat, name="worker-heartbeat"),
    path("result/", report_result, name="worker-result"),
    path("pools/<int:pool_id>/egress/", configure_result_egress, name="worker-pool-egress"),
    path("pools/<int:pool_id>/drain/", drain_pool, name="worker-pool-drain"),
    path("pools/<int:pool_id>/activate/", activate_pool, name="worker-pool-activate"),
    path("<int:worker_id>/drain/", drain_worker, name="worker-drain"),
    path("<int:worker_id>/activate/", activate_worker, name="worker-activate"),
    path("<int:worker_id>/credential/revoke/", revoke_credential, name="worker-credential-revoke"),
]
