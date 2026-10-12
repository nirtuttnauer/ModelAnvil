"""Durable allocation intents with conservative recovery and verified cleanup."""
import re
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
from modelanvil.compute.models import ComputeAllocation as Allocation
from modelanvil.compute.plugins import PluginError, ProviderError, compute_provider, definition, validate_configuration
from modelanvil.core.models import record_audit
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Worker, WorkerCredential, generate_worker_credential


def allocation_name(allocation):
    return "modelanvil-" + str(allocation.allocation_id)


def _validate_bootstrap(entry):
    image = entry.get("image", "")
    endpoint = entry.get("worker_endpoint", "")
    parsed = urlsplit(endpoint)
    if (not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", image)
            or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/api/v1/workers"
            or "\\" in endpoint or any(ord(c) <= 32 for c in endpoint)
            or not isinstance(entry.get("worker_executor"), str)):
        raise PluginError("Compute plugin requires a pinned image, HTTPS worker endpoint and installed executor.")


def allocate(*, tenant_id, request_id, plugin_id, pool, spec, lifetime_seconds, policy_id, actor_id=None, actor_kind="system"):
    entry, digest = definition(plugin_id, tenant_id, "compute")
    validate_configuration(entry["configuration_schema"], spec)
    _validate_bootstrap(entry)
    task_entry, task_digest = None, None
    if entry.get("task_plugin"):
        task_entry, task_digest = definition(entry["task_plugin"], tenant_id, "task")
        if entry["worker_executor"] != "modelanvil.compute.task_worker:execute":
            raise PluginError("Task-backed compute requires the installed task dispatcher.")
    if pool.tenant_id != tenant_id or pool.status != "active":
        raise PluginError("An active pool in the current tenant is required.")
    # The tenant lock serializes requests before an allocation row exists.
    with transaction.atomic():
        Tenant.objects.select_for_update().get(tenant_id=tenant_id)
        existing = Allocation.all_objects.filter(tenant_id=tenant_id, request_id=request_id).first()
        if existing:
            if (existing.plugin_id != plugin_id or existing.spec != spec or existing.worker.pool_id != pool.pk
                    or existing.reservation.policy.policy_id != policy_id
                    or int((existing.expires_at - existing.created_at).total_seconds()) != lifetime_seconds):
                raise PluginError("Allocation request ID was already used with different parameters.")
            return existing
        provider = compute_provider(plugin_id, tenant_id)
        policy = BudgetPolicy.all_objects.filter(tenant_id=tenant_id, policy_id=policy_id, unit="allocation_seconds", currency="").first()
        if policy is None:
            raise PluginError("An allocation_seconds budget policy in this tenant is required.")
        now = timezone.now()
        capabilities = dict(entry.get("worker_capabilities", {}))
        if task_entry:
            capabilities.update(task_plugin=entry["task_plugin"], task_plugin_digest=task_digest)
        worker = Worker.all_objects.create(tenant_id=tenant_id, pool=pool, name="external-" + str(request_id),
                                           capabilities=capabilities, slots=1)
        token, secret_hash = generate_worker_credential()
        WorkerCredential.all_objects.create(tenant_id=tenant_id, worker=worker, secret_hash=secret_hash,
                                             expires_at=now + timedelta(seconds=lifetime_seconds))
        allocation_id = uuid.uuid4()
        reservation = BudgetReservation.reserve(tenant_id=tenant_id, policy=policy, job_id=allocation_id,
                                                 estimated_amount=lifetime_seconds)
        allocation = Allocation.all_objects.create(tenant_id=tenant_id, allocation_id=allocation_id,
            request_id=request_id, plugin_id=plugin_id, plugin_digest=digest, spec=spec, worker=worker,
            created_at=now, expires_at=now + timedelta(seconds=lifetime_seconds), reservation=reservation)
        record_audit(tenant_id=tenant_id, action="create", resource_type="compute_allocation",
                     resource_id=allocation.allocation_id, actor_id=actor_id, actor_kind=actor_kind,
                     input_snapshot={"plugin_id": plugin_id})

    bootstrap = {"image": entry["image"], "env": {
        "MODELANVIL_WORKER_TOKEN": token, "MODELANVIL_WORKER_ENDPOINT": entry["worker_endpoint"],
        "MODELANVIL_WORKER_ID": str(worker.pk), "MODELANVIL_WORKER_POOL": pool.name,
        "MODELANVIL_WORKER_EXECUTOR": entry["worker_executor"], "MODELANVIL_TENANT_ID": str(tenant_id),
        "MODELANVIL_RESULT_EGRESS": pool.result_egress,
    }}
    if task_entry:
        bootstrap["env"].update(MODELANVIL_TASK_PLUGIN=entry["task_plugin"],
            MODELANVIL_PLUGINS=json.dumps({entry["task_plugin"]: task_entry}))
    try:
        resource = provider.create(allocation_name(allocation), spec, bootstrap)
        _check_resource(allocation, resource)
    except Exception as exc:
        uncertain = not isinstance(exc, ProviderError) or exc.uncertain
        with transaction.atomic():
            current = Allocation.all_objects.select_for_update().get(pk=allocation.pk)
            if current.state != Allocation.State.RELEASED and not current.provider_resource_id:
                current.state = Allocation.State.UNCERTAIN if uncertain else Allocation.State.FAILED
                current.error_code = exc.code if isinstance(exc, ProviderError) else "provider_create_uncertain"
                current.save()
                if not uncertain:
                    _disable_worker(current)
                    current.reservation.release()
    else:
        with transaction.atomic():
            current = Allocation.all_objects.select_for_update().get(pk=allocation.pk)
            if current.state != Allocation.State.RELEASED:
                current.provider_resource_id = resource["id"]
                current.provider_status = resource["status"]
                current.state = Allocation.State.ACTIVE
                current.save()
    allocation.refresh_from_db()
    if allocation.release_requested or allocation.expires_at <= timezone.now():
        return reconcile(allocation, release=True)
    return allocation


def _check_resource(allocation, resource):
    if (not isinstance(resource, dict) or resource.get("name") != allocation_name(allocation)
            or not isinstance(resource.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", resource["id"])
            or not isinstance(resource.get("status"), str) or not re.fullmatch(r"[A-Z_]{1,32}", resource["status"])
            or allocation.provider_resource_id and resource["id"] != allocation.provider_resource_id):
        raise ProviderError("provider_identity_mismatch")


def _disable_worker(allocation):
    Worker.all_objects.filter(pk=allocation.worker_id, tenant_id=allocation.tenant_id).update(status=Worker.Status.OFFLINE)
    WorkerCredential.all_objects.filter(worker_id=allocation.worker_id, revoked_at__isnull=True).update(revoked_at=timezone.now())


def reconcile(allocation, *, release=False, actor_id=None, actor_kind="system"):
    # Commit cancellation intent and credential revocation before network I/O.
    with transaction.atomic():
        current = Allocation.all_objects.select_for_update().get(pk=allocation.pk, tenant_id=allocation.tenant_id)
        if current.state in (Allocation.State.RELEASED, Allocation.State.FAILED):
            return current
        if release or current.release_requested or current.expires_at <= timezone.now():
            current.release_requested = True
            current.save(update_fields=("release_requested", "updated_at"))
            _disable_worker(current)
    return _reconcile(current, actor_id=actor_id, actor_kind=actor_kind)


@transaction.atomic
def _reconcile(allocation, *, actor_id=None, actor_kind="system"):
    allocation = Allocation.all_objects.select_for_update().select_related("worker", "reservation").get(
        pk=allocation.pk, tenant_id=allocation.tenant_id)
    if allocation.state in (Allocation.State.RELEASED, Allocation.State.FAILED):
        return allocation
    try:
        provider = compute_provider(allocation.plugin_id, allocation.tenant_id, allocation.plugin_digest)
        if allocation.provider_resource_id:
            resource = provider.inspect(allocation.provider_resource_id)
        else:
            matches = provider.find(allocation_name(allocation))
            if len(matches) != 1:
                # An eventually consistent list cannot prove a timed-out create
                # failed. Never submit create again with this allocation intent.
                raise ProviderError("provider_create_unresolved")
            resource = matches[0]
        if resource is not None:
            _check_resource(allocation, resource)
            allocation.provider_resource_id = resource["id"]
            allocation.provider_status = resource["status"]
            if allocation.release_requested:
                provider.release(resource["id"])
                resource = provider.inspect(resource["id"])
                if resource is not None:
                    _check_resource(allocation, resource)
        if resource is None or resource["status"] == "TERMINATED":
            allocation.state = Allocation.State.RELEASED
            allocation.released_at = timezone.now()
            _disable_worker(allocation)
            elapsed = Decimal(str(max(0, (allocation.released_at - allocation.created_at).total_seconds())))
            allocation.reservation.settle(elapsed)
        else:
            allocation.state = Allocation.State.RELEASING if allocation.release_requested else Allocation.State.ACTIVE
            allocation.provider_status = resource["status"]
        allocation.error_code = ""
    except (ProviderError, PluginError) as exc:
        allocation.state = Allocation.State.RELEASING if allocation.release_requested else Allocation.State.UNCERTAIN
        allocation.error_code = exc.code if isinstance(exc, ProviderError) else "plugin_unavailable"
    except Exception:
        allocation.state = Allocation.State.RELEASING if allocation.release_requested else Allocation.State.UNCERTAIN
        allocation.error_code = "provider_reconcile_uncertain"
    allocation.save()
    record_audit(tenant_id=allocation.tenant_id, action="update", resource_type="compute_allocation",
                 resource_id=allocation.allocation_id, actor_id=actor_id, actor_kind=actor_kind,
                 input_snapshot={"state": allocation.state,
                     "release_requested": allocation.release_requested}, result="error" if allocation.error_code else "ok")
    return allocation

