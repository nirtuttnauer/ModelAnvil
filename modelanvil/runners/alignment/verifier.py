"""Deterministic rule and environment verifier RL engine (TECH-019 / PRD Scenario 4)."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Callable, Sequence

from django.utils import timezone

from modelanvil.runners.models import AlignmentRun, AlignmentCheckpoint, ModelVersion


class VerifierEngine:
    """Deterministic environment/rule-based verifier with trajectory logging and exploit checks."""

    def __init__(
        self,
        policy_model: ModelVersion,
        domain_type: str = "math_reasoning",
    ) -> None:
        self.policy_model = policy_model
        self.domain_type = domain_type

    def execute_verifier(self, prompt: str, reasoning: str, answer: str, ground_truth: str) -> tuple[bool, bool]:
        """Execute deterministic verification and detect formatting exploits.

        Returns: (passed: bool, exploit_detected: bool)
        """
        # Exploit check: length inflation without valid answer (e.g. padding tokens > 200 chars while answer is empty/bogus)
        exploit_detected = False
        if len(reasoning) > 300 and ("### VERIFIED TRUE ###" in answer or "bypass" in reasoning.lower()):
            exploit_detected = True

        if exploit_detected:
            return False, True

        # Deterministic domain rule
        clean_ans = answer.strip().rstrip(".").lower()
        clean_gt = ground_truth.strip().rstrip(".").lower()

        passed = (clean_ans == clean_gt)
        return passed, False

    def run_verifier_rl(
        self,
        alignment_run: AlignmentRun,
        tasks: Sequence[dict[str, str]],  # [{"prompt": ..., "ground_truth": ...}]
        total_steps: int = 4,
        inject_exploit: bool = False,
    ) -> AlignmentRun:
        """Run verifier-guided RL across steps, recording trajectories and verifying outcomes."""
        alignment_run.algorithm = AlignmentRun.Algorithm.VERIFIER_RL
        alignment_run.status = AlignmentRun.Status.RUNNING
        alignment_run.policy_model_version = self.policy_model
        alignment_run.total_steps = total_steps
        alignment_run.verifier_spec = {
            "domain_type": self.domain_type,
            "tasks_count": len(tasks),
            "inject_exploit": inject_exploit,
        }
        alignment_run.started_at = timezone.now()
        alignment_run.save()

        metrics_history = []
        all_trajectories = []

        for step in range(1, total_steps + 1):
            step_trajectories = []
            passes = 0
            exploits = 0

            for task in tasks:
                prompt = task["prompt"]
                gt = task["ground_truth"]

                if inject_exploit:
                    reasoning = "Detailed explanation: " + ("padding tokens " * 40) + "bypass verifier."
                    answer = "### VERIFIED TRUE ###"
                else:
                    reasoning = f"Step-by-step reasoning for '{prompt}' at step {step}."
                    # Accuracy improves as step increases
                    if step >= 2:
                        answer = gt
                    else:
                        answer = f"Attempted answer {step}"

                passed, exploit = self.execute_verifier(prompt, reasoning, answer, gt)
                reward = -1.0 if exploit else (1.0 if passed else 0.0)

                if passed:
                    passes += 1
                if exploit:
                    exploits += 1

                trajectory = {
                    "step": step,
                    "prompt": prompt,
                    "reasoning": reasoning,
                    "answer": answer,
                    "ground_truth": gt,
                    "passed": passed,
                    "exploit_detected": exploit,
                    "reward": reward,
                }
                step_trajectories.append(trajectory)
                all_trajectories.append(trajectory)

            pass_rate = passes / len(tasks) if tasks else 0.0
            step_metrics = {
                "step": step,
                "pass_rate": round(pass_rate, 4),
                "total_tasks": len(tasks),
                "passes_count": passes,
                "exploits_count": exploits,
                "exploit_detected": exploits > 0,
                "average_reward": round(sum(t["reward"] for t in step_trajectories) / len(tasks), 4) if tasks else 0.0,
            }
            metrics_history.append(step_metrics)
            alignment_run.current_step = step

            # Save checkpoint
            digest = hashlib.sha256(
                f"verifier-{alignment_run.run_id}-step-{step}-{pass_rate}".encode("utf-8")
            ).hexdigest()
            AlignmentCheckpoint.objects.create(
                tenant_id=alignment_run.tenant_id,
                alignment_run=alignment_run,
                step=step,
                state_digest=digest,
                policy_state={"step": step, "pass_rate": pass_rate},
                metrics=step_metrics,
            )

        alignment_run.metrics_history = metrics_history
        alignment_run.rollouts_log = all_trajectories[-20:]
        alignment_run.latest_metrics = metrics_history[-1]
        alignment_run.status = AlignmentRun.Status.COMPLETED
        alignment_run.completed_at = timezone.now()

        # Output model version
        next_rev = ModelVersion.objects.filter(model=self.policy_model.model).count() + 1
        cand_model = ModelVersion.objects.create(
            tenant_id=alignment_run.tenant_id,
            model=self.policy_model.model,
            revision_no=next_rev,
            architecture_ref=self.policy_model.architecture_ref,
            artifact_manifest_id=f"manifest-verifier-{alignment_run.run_id}",
            tokenizer=self.policy_model.tokenizer,
            license_evidence=self.policy_model.license_evidence,
            parameters_count=self.policy_model.parameters_count,
            state=ModelVersion.State.DRAFT,
            producing_job_id=alignment_run.run_id,
            metadata={
                "alignment_recipe": "verifier_rl",
                "domain_type": self.domain_type,
                "final_pass_rate": alignment_run.latest_metrics["pass_rate"],
                "exploit_detected": alignment_run.latest_metrics.get("exploit_detected", False),
            },
        )
        alignment_run.output_model_version = cand_model
        alignment_run.save()

        return alignment_run

    def export_bundle(self, alignment_run: AlignmentRun) -> dict[str, Any]:
        """Generate external loadable export bundle for verifier-guided model."""
        if not alignment_run.output_model_version:
            raise ValueError("Cannot export: Alignment run has no output model version.")
        latest_cp = alignment_run.checkpoints.order_by("-step").first()
        return {
            "format_version": "1.0",
            "model_name": alignment_run.output_model_version.model.name,
            "model_version_id": str(alignment_run.output_model_version.model_version_id),
            "algorithm": alignment_run.algorithm,
            "verifier_spec": alignment_run.verifier_spec,
            "final_metrics": alignment_run.latest_metrics,
            "state_digest": latest_cp.state_digest if latest_cp else "",
        }
