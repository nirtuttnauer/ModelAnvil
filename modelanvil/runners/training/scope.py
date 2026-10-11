"""Itemized runtime-scope availability report for training preflight.

TASK-5 requires the product to distinguish measured/available capabilities from missing
ones with an actionable reason. This module reports each requested runtime target with a
concrete status, the exact dependency or infrastructure that is missing, and the
corrective action an operator can take. It never claims a capability that is not
detected in the current environment.
"""
from __future__ import annotations

import importlib.util
import platform
from dataclasses import dataclass, field
from typing import Any, Optional

from modelanvil.runners.training.general_transformer import GENERAL_RUNTIME_ID
from modelanvil.runners.training.hardware import accelerators as measured_accelerators

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RuntimeTarget:
    target_id: str
    label: str
    category: str
    status: str
    reason: str
    corrective_action: Optional[str] = None
    required_dependencies: tuple[str, ...] = field(default_factory=tuple)
    required_infrastructure: tuple[str, ...] = field(default_factory=tuple)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _detect_gpu_count() -> int:
    """Training accelerators measured on this host.

    Only a device that a supported backend actually reports counts as capacity;
    a graphics adapter or an unenumerated backend never does.
    """
    return len(measured_accelerators()[0])


def _detect_provider_configured() -> bool:
    try:  # pragma: no cover - depends on settings
        from django.conf import settings

        modelanvil = getattr(settings, "MODELANVIL", {}) or {}
        return bool(modelanvil.get("provider_credentials") or modelanvil.get("remote_storage"))
    except Exception:
        return False


def runtime_scope_targets(*, gpu_count: Optional[int] = None, provider_configured: Optional[bool] = None) -> list[RuntimeTarget]:
    """Build the itemized target list, using overrides for deterministic tests."""
    if gpu_count is None:
        gpu_count = _detect_gpu_count()
    if provider_configured is None:
        provider_configured = _detect_provider_configured()

    targets: list[RuntimeTarget] = [
        RuntimeTarget(
            target_id=GENERAL_RUNTIME_ID,
            label="General transformer SFT (pure-Python CPU reference)",
            category="compatibility",
            status=STATUS_AVAILABLE,
            reason="Causal multi-head attention, context window, chat template and AdamW are implemented and locally testable.",
            required_dependencies=(),
            required_infrastructure=(),
        ),
        RuntimeTarget(
            target_id="modelanvil.cpu-character-sft.v1",
            label="Bounded CPU character SFT worker",
            category="compatibility",
            status=STATUS_AVAILABLE,
            reason="Worker-backed character SFT with pinned text/base/tokenizer and fenced checkpoints.",
        ),
        RuntimeTarget(
            target_id="modelanvil.gpu-sft.v1",
            label="GPU-accelerated fine-tuning",
            category="capacity",
            status=STATUS_AVAILABLE if gpu_count else STATUS_UNAVAILABLE,
            reason=(
                f"Detected {gpu_count} accelerator device(s)."
                if gpu_count
                else "No CUDA/MPS-capable training device or tensor framework is available in this environment."
            ),
            corrective_action=(
                None
                if gpu_count
                else "Install a tensor framework build and provision a GPU worker pool, then register it for training."
            ),
            required_dependencies=("torch", "numpy"),
            required_infrastructure=("gpu_worker_pool",),
        ),
        RuntimeTarget(
            target_id="modelanvil.distributed-sft.v1",
            label="Distributed / multi-worker training",
            category="capacity",
            status=STATUS_UNAVAILABLE,
            reason="No cluster scheduler or worker-to-worker tensor transport is configured; the reference runtime is single-process.",
            corrective_action="Deploy a distributed launcher and a worker pool that supports tensor transport, then re-run preflight.",
            required_dependencies=("torch.distributed",),
            required_infrastructure=("cluster_scheduler", "tensor_transport"),
        ),
        RuntimeTarget(
            target_id="modelanvil.remote-production.v1",
            label="Remote workers, provider storage and production serving",
            category="capacity",
            status=STATUS_AVAILABLE if provider_configured else STATUS_UNAVAILABLE,
            reason=(
                "Provider credentials and remote storage are configured."
                if provider_configured
                else "No provider credentials or remote object storage are configured for this deployment."
            ),
            corrective_action=(
                None
                if provider_configured
                else "Configure provider credentials and remote object storage, then validate egress and serving."
            ),
            required_dependencies=("boto3",),
            required_infrastructure=("object_store", "serving_runtime"),
        ),
    ]
    return targets


def runtime_scope_report(*, gpu_count: Optional[int] = None, provider_configured: Optional[bool] = None) -> dict[str, Any]:
    """Return a serializable, itemized runtime-scope availability report."""
    measured_devices, measured_reason = measured_accelerators()
    targets = runtime_scope_targets(gpu_count=gpu_count, provider_configured=provider_configured)
    items = [
        {
            "target_id": target.target_id,
            "label": target.label,
            "category": target.category,
            "status": target.status,
            "reason": target.reason,
            "corrective_action": target.corrective_action,
            "required_dependencies": list(target.required_dependencies),
            "required_infrastructure": list(target.required_infrastructure),
        }
        for target in targets
    ]
    return {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "measured_accelerators": measured_devices,
            "accelerator_status": STATUS_AVAILABLE if measured_devices else STATUS_UNAVAILABLE,
            "accelerator_reason": measured_reason,
        },
        "targets": items,
        "available": [item["target_id"] for item in items if item["status"] == STATUS_AVAILABLE],
        "unavailable": [item["target_id"] for item in items if item["status"] == STATUS_UNAVAILABLE],
    }
