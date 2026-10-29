"""Run the pinned CPU character evaluation once through eval_worker.

Stdout is the measured report. The policy and reference are read, not changed.
"""
from __future__ import annotations

import hashlib
import io
import json
import platform
import socket
import time
import uuid

from modelanvil.runners.cpu_character_eval_envelope import POLICY_ID, load_policy, load_reference


def _envelope(sample: dict) -> dict:
    text = sample["text"]
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest != sample["content_sha256"]:
        raise ValueError("Pinned training text does not match its content hash.")
    return {
        "schema_version": "1.0",
        "sample_id": sample["sample_id"],
        "source_group_id": sample["source_group_id"],
        "blocks": [{"block_id": "text", "type": "text", "text": text}],
        "provenance": {
            "source_snapshot_ref": "cpu-character-eval-reference-v1",
            "source_record_key": sample["sample_id"],
            "content_sha256": digest,
        },
    }


def _artifact(tenant, key: str, raw: bytes, media: str):
    from modelanvil.artifacts.models import Artifact
    from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact

    artifact = Artifact.objects.create(
        tenant_id=tenant.pk,
        storage_location_id="local",
        object_key=key,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw),
        media_type=media,
    )
    upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
    return artifact


def _provision(client, name: str, profile: str) -> dict:
    from modelanvil.jobs.models import Worker
    from modelanvil.jobs.setup import observe_local_worker

    response = client.post(
        "/api/v1/workers/setup/",
        {"worker_name": name, "pool": f"{name}-pool", "profile": profile},
        format="json",
    )
    if response.status_code != 201:
        raise RuntimeError(f"Worker setup for {profile} failed: {response.status_code} {response.content!r}")
    worker = Worker.all_objects.get(pk=response.data["worker_id"])
    observe_local_worker(worker, profile, response.data["worker_token"])
    worker.refresh_from_db()
    return {"worker": worker, "pool_id": response.data["pool_id"], "runner_id": response.data["runner_id"]}


def _execute(worker, executor):
    from modelanvil.jobs.executor import execute_claim
    from modelanvil.jobs.models import JobAttempt, claim_job

    descriptor = claim_job(worker)
    if descriptor is None:
        raise RuntimeError(f"Worker {worker.name} claimed no job.")
    outcome = execute_claim(worker, descriptor, executor)
    if outcome.get("status") != "succeeded" or not outcome.get("committed"):
        error = ""
        attempt = JobAttempt.all_objects.filter(attempt_id=descriptor["attempt_id"]).first()
        if attempt is not None:
            error = attempt.error
        raise RuntimeError(f"Worker {worker.name} did not succeed: {outcome} {error}")
    return outcome


def _metric_row(row: dict) -> dict:
    uncertainty = row.get("uncertainty_interval") or row.get("uncertainty") or {}
    return {
        "key": row["key"],
        "slice_name": row["slice_name"],
        "method": uncertainty.get("method"),
        "value": row["value"],
        "sample_count": row["sample_count"],
        "uncertainty": {"method": uncertainty.get("method"), "lower": uncertainty["lower"], "upper": uncertainty["upper"]},
    }


def run_once(reference: dict, *, name: str) -> dict:
    """Train the pinned character base and evaluate it with eval_worker."""
    from django.db import transaction
    from rest_framework.test import APIClient

    from modelanvil.artifacts.models import Dataset
    from modelanvil.budgets.models import BudgetPolicy
    from modelanvil.core.tenancy import set_active_tenant
    from modelanvil.data.publication import publish_prepared_dataset
    from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
    from modelanvil.runners.eval_worker import evaluation_worker_executor
    from modelanvil.runners.models import EvaluationRun, EvaluationSuite, EvaluationSuiteVersion, ModelVersion, TrainingRun
    from modelanvil.runners.training.executor import training_worker_executor

    protocol = reference["protocol"]
    if reference["policy_id"] != POLICY_ID:
        raise ValueError("Reference policy id does not match the frozen policy.")
    token = set_active_tenant(None)
    try:
        with transaction.atomic():
            tenant = Tenant.objects.create(slug=f"eval-{uuid.uuid4().hex[:12]}", name=name)
            set_active_tenant(tenant.pk)
            secret, hashed = generate_api_key()
            ApiKey.objects.create(tenant=tenant, name="admin", role=Role.ADMIN, secret_hash=hashed)
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")
            initialized = client.post(
                "/api/v1/model-versions/initialize-cpu/",
                {"name": name, "seed": protocol["initialization_seed"], "profile": protocol["profile"]},
                format="json",
            )
            if initialized.status_code != 201:
                raise RuntimeError(f"CPU initialization failed: {initialized.status_code} {initialized.content!r}")
            base = ModelVersion.all_objects.get(pk=initialized.data["model_version"]["id"])
            if base.metadata.get("initialization_seed") != protocol["initialization_seed"]:
                raise RuntimeError("Initialized seed does not match the saved reference.")
            rows = [_envelope(sample) for sample in protocol["training_samples"]]
            raw = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
            dataset = Dataset.objects.create(tenant_id=tenant.pk, name=f"{name} samples")
            revision = publish_prepared_dataset(
                dataset,
                _artifact(tenant, f"{name}-samples.jsonl", raw, "application/x-ndjson"),
                validation_percent=0,
                test_percent=0,
            )
            trainer = _provision(client, f"{name}-train", "cpu-character")
            step_budget = BudgetPolicy.objects.create(
                tenant_id=tenant.pk, name=f"{name} steps", period="lifetime", unit="training_steps", limit_amount=100,
            )
            launched = client.post(
                "/api/v1/training-runs/",
                {
                    "recipe_type": "full_sft",
                    "tokenizer_version": base.tokenizer_id,
                    "base_model_version": base.pk,
                    "dataset_revision": revision.pk,
                    "runner_manifest": trainer["runner_id"],
                    "pool": trainer["pool_id"],
                    "budget_policy_id": str(step_budget.policy_id),
                    "total_steps": protocol["training_steps"],
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY=f"{name}-train",
            )
            if launched.status_code != 201:
                raise RuntimeError(f"Training launch failed: {launched.status_code} {launched.content!r}")
            training = TrainingRun.all_objects.get(run_id=launched.data["run_id"])
            _execute(trainer["worker"], training_worker_executor)
            training.refresh_from_db()
            if training.status != "completed" or training.output_model_version_id is None:
                raise RuntimeError("Training did not publish a candidate.")
            trained_pins = training.hardware_config.get("pins") or {}
            if trained_pins.get("optimizer") != protocol["optimizer"] or trained_pins.get("steps") != protocol["training_steps"]:
                raise RuntimeError(f"Training pins do not match the saved reference: {trained_pins.get('optimizer')} steps={trained_pins.get('steps')}")
            evaluator = _provision(client, f"{name}-eval", "cpu-evaluation")
            case_budget = BudgetPolicy.objects.create(
                tenant_id=tenant.pk, name=f"{name} cases", period="lifetime", unit="evaluation_cases", limit_amount=64,
            )
            suite = EvaluationSuite.objects.create(tenant_id=tenant.pk, name=f"{name} suite")
            version = EvaluationSuiteVersion.objects.create(
                tenant_id=tenant.pk,
                suite=suite,
                revision_no=1,
                scorer_type=protocol["scorer_type"],
                scorer_config=protocol["scorer_config"],
                protected_role="protected_eval",
                cases=[
                    {
                        "case_id": case["case_id"],
                        "source_group_id": case["source_group_id"],
                        "input_prompt": case["input_prompt"],
                        "expected_output": case["expected_output"],
                        "slice": case["slice"],
                    }
                    for case in protocol["cases"]
                ],
            )
            created = client.post(
                "/api/v1/evaluation-runs/",
                {
                    "suite_version": version.pk,
                    "candidate_model_version": training.output_model_version_id,
                    "baseline_model_version": base.pk,
                },
                format="json",
            )
            if created.status_code != 201:
                raise RuntimeError(f"Evaluation create failed: {created.status_code} {created.content!r}")
            run = EvaluationRun.all_objects.get(run_id=created.data["run_id"])
            queued = client.post(
                f"/api/v1/evaluation-runs/{run.run_id}/execute/",
                {
                    "pool": evaluator["pool_id"],
                    "budget_policy_id": str(case_budget.policy_id),
                    "max_tokens": protocol["max_tokens"],
                },
                format="json",
            )
            if queued.status_code != 202:
                raise RuntimeError(f"Evaluation queue failed: {queued.status_code} {queued.content!r}")
            started = time.perf_counter()
            _execute(evaluator["worker"], evaluation_worker_executor)
            wall_seconds = time.perf_counter() - started
            run.refresh_from_db()
            if run.status != "completed":
                raise RuntimeError(f"Evaluation status is {run.status}.")
            report = _report(reference, run, training, base, wall_seconds)
    finally:
        set_active_tenant(token)
    return report


def _report(reference, run, training, base, wall_seconds: float) -> dict:
    protocol = reference["protocol"]
    pins = run.protocol_ref["pins"]
    actual_protocol = {
        "initialization_seed": base.metadata["initialization_seed"],
        "profile": protocol["profile"],
        "runtime_id": protocol["runtime_id"],
        "executor": protocol["executor"],
        "training_steps": training.total_steps,
        "optimizer": protocol["optimizer"],
        "max_tokens": pins["max_tokens"],
        "scorer_type": run.suite_version.scorer_type,
        "scorer_config": run.suite_version.scorer_config,
        "decoding": pins["decoding"],
        "device": pins["device"],
        "prompt_format": pins["prompt_format"],
        "training_samples": protocol["training_samples"],
        "cases": [
            {
                "case_id": case["case_id"],
                "source_group_id": case["source_group_id"],
                "input_prompt": case["input_prompt"],
                "expected_output": case["expected_output"],
                "slice": case.get("slice", "all"),
            }
            for case in run.suite_version.cases
        ],
    }
    if actual_protocol != protocol:
        raise RuntimeError(f"Run protocol does not match the saved reference: {actual_protocol}")
    evidence = run.protocol_ref.get("execution_evidence") or {}
    if evidence.get("level") != "integrated_execution":
        raise RuntimeError(f"Evaluation evidence is {evidence!r}.")
    if training.output_model_version.architecture_ref != protocol["runtime_id"]:
        raise RuntimeError("Candidate runtime does not match the saved reference.")
    baseline_by_case = {row["case_id"]: row for row in run.protocol_ref.get("baseline_results") or []}
    cases = []
    for result in run.case_results.order_by("case_id"):
        baseline = baseline_by_case[result.case_id]
        cases.append({
            "case_id": result.case_id,
            "input_prompt": result.input_prompt,
            "expected_output": result.expected_output,
            "slice": result.slice_name,
            "candidate_output": result.candidate_output,
            "baseline_output": baseline["candidate_output"],
            "passed": result.passed,
            "baseline_passed": baseline["passed"],
            "score": result.score,
            "baseline_score": baseline["score"],
        })
    metrics = [
        _metric_row(row)
        for row in run.metrics.order_by("key", "slice_name").values(
            "key", "slice_name", "value", "sample_count", "uncertainty_interval",
        )
    ]
    baseline_metrics = [
        _metric_row(row)
        for row in sorted(run.protocol_ref.get("baseline_metrics") or [], key=lambda item: (item["key"], item["slice_name"]))
    ]
    return {
        "policy_id": reference["policy_id"],
        "contains_measurement": True,
        "protocol": actual_protocol,
        "evidence_level": evidence["level"],
        "candidate_weights_sha256": training.output_model_version.metadata["weights_sha256"],
        "baseline_weights_sha256": base.metadata["weights_sha256"],
        "cases": cases,
        "metrics": metrics,
        "baseline_metrics": baseline_metrics,
        "wall_seconds": wall_seconds,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def main() -> int:
    import os
    import sys
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp(prefix="anvil021-eval-"))
    os.environ["DATABASE_NAME"] = str(root / "db.sqlite3")
    os.environ["MODELANVIL_ARTIFACT_ROOT"] = str(root / "artifacts")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0, stdout=io.StringIO())
    policy = load_policy()
    reference = load_reference()
    if policy["id"] != reference["policy_id"]:
        print("policy id does not match the saved reference", file=sys.stderr)
        return 2
    report = run_once(reference, name="cpu-character-eval")
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
