"""Bounded hyperparameter sweeps and budget enforcement (WP-08 / TECH-017)."""
from __future__ import annotations

import itertools
from typing import Any, Optional

from django.core.exceptions import ValidationError

from modelanvil.runners.models import TokenizerVersion, TrainingRun
from modelanvil.runners.training.engine import TrainingEngine
from modelanvil.runners.training.preflight import validate_training_preflight


def run_bounded_parameter_sweep(
    *,
    tenant_id: str,
    recipe_type: str,
    tokenizer_version: TokenizerVersion,
    base_hyperparameters: dict[str, Any],
    search_space: dict[str, list[Any]],
    budget_limit_dollars: float,
    steps_per_trial: int = 20,
    hardware_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Execute a bounded parameter sweep across discrete hyperparameter options within budget limits.

    Guarantees:
    - Preflights each combination and tallies cumulative estimated cost.
    - If cumulative cost exceeds budget_limit_dollars, rejects before compute dispatch.
    - Deterministically runs each trial, records checkpoints/metrics, and selects the best trial.
    """
    keys = list(search_space.keys())
    value_lists = [search_space[k] for k in keys]
    combinations = list(itertools.product(*value_lists))

    if not combinations:
        raise ValidationError("Search space is empty.")

    # 1. Preflight all combinations and compute cumulative cost
    trial_configs: list[dict[str, Any]] = []
    cumulative_cost = 0.0

    for combo in combinations:
        hp = dict(base_hyperparameters)
        for k, v in zip(keys, combo):
            hp[k] = v
        hp["max_steps"] = steps_per_trial

        preflight = validate_training_preflight(
            recipe_type=recipe_type,
            tokenizer_version=tokenizer_version,
            hyperparameters=hp,
            hardware_config=hardware_config,
        )
        trial_cost = preflight["estimated_cost_dollars"]
        cumulative_cost += trial_cost
        trial_configs.append({"hyperparameters": hp, "preflight": preflight, "cost": trial_cost})

    if cumulative_cost > budget_limit_dollars:
        raise ValidationError(
            f"Sweep cumulative cost (${cumulative_cost:.2f}) exceeds authorized budget limit (${budget_limit_dollars:.2f})."
        )

    # 2. Execute trials
    engine = TrainingEngine()
    results: list[dict[str, Any]] = []

    for idx, cfg in enumerate(trial_configs):
        run = TrainingRun.objects.create(
            tenant_id=tenant_id,
            recipe_type=recipe_type,
            tokenizer_version=tokenizer_version,
            hyperparameters=cfg["hyperparameters"],
            total_steps=steps_per_trial,
            initialization_seed=1000 + idx,
        )
        engine.train_steps(run, steps_per_trial, checkpoint_interval=steps_per_trial)
        run.refresh_from_db()

        results.append({
            "trial_index": idx,
            "run_id": str(run.run_id),
            "hyperparameters": cfg["hyperparameters"],
            "final_loss": run.latest_loss,
            "status": run.status,
            "cost_dollars": cfg["cost"],
        })

    # 3. Rank trials by final loss
    best_trial = min(results, key=lambda x: x["final_loss"] if x["final_loss"] is not None else float("inf"))

    return {
        "status": "completed",
        "total_trials": len(results),
        "cumulative_cost_dollars": round(cumulative_cost, 4),
        "budget_limit_dollars": budget_limit_dollars,
        "best_trial": best_trial,
        "trials": results,
    }
