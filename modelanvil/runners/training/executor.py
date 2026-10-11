"""Durable worker execution for training jobs (WP-08 / MA-PM-04)."""
from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from modelanvil.jobs.executor import ExecutionContext
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training.engine import TrainingEngine


def training_worker_executor(descriptor: dict[str, Any], context: ExecutionContext) -> dict[str, Any] | None:
    """Execute a claimed training job against durable worker fencing and heartbeats."""
    payload = descriptor.get("payload", {})
    run_id_str = payload.get("run_id")
    if not run_id_str:
        raise ValueError("Missing run_id in training job payload.")

    try:
        run_uuid = uuid.UUID(str(run_id_str))
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid run_id in training job payload.") from exc

    run = TrainingRun.objects.select_related("tokenizer_version", "base_model_version").filter(
        run_id=run_uuid
    ).first()
    if run is None:
        raise ValueError(f"TrainingRun {run_uuid} not found.")

    from modelanvil.runners.training.registry import is_worker_run, execute_training
    if is_worker_run(run):
        if str(run.job.job_id) != descriptor.get('job_id') or run.job_id != context.attempt.job_id:
            raise ValueError('Training job does not match the claimed run.')
        execute_training(run, context)
        return None

    if run.status in (TrainingRun.Status.COMPLETED, TrainingRun.Status.CANCELLED):
        return None

    # Mark run running
    if run.status == TrainingRun.Status.PENDING:
        run.status = TrainingRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])

    engine = TrainingEngine()

    hp = run.hyperparameters or {}
    ckpt_interval = int(hp.get("checkpoint_interval", 10))
    target_steps = run.total_steps - run.current_step

    def cancel_check() -> bool:
        # Renew lease and verify cancel hasn't been requested
        heartbeat_ok = context.heartbeat(progress=run.current_step / max(run.total_steps, 1))
        return not heartbeat_ok

    engine.train_steps(
        run,
        num_steps=target_steps,
        checkpoint_interval=ckpt_interval,
        cancel_check=cancel_check,
    )

    if run.status == TrainingRun.Status.CANCELLED:
        return None

    return None
