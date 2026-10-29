#!/usr/bin/env python3
"""Clone a pinned SHA, run the documented README install, and train SmolLM2-135M on CPU.

The install commands are the fenced block marked in README.md. No Hub token is
read or sent. A failed download, or a file that does not match the pinned
checksum, exits non-zero before any training step.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_STEPS = 10
DEFAULT_STEPS = 3
REMOTE = "https://github.com/nirtuttnauer/ModelAnvil.git"
INSTALL_START = "<!-- golden-path-install:start -->"
INSTALL_END = "<!-- golden-path-install:end -->"
TRAIN_START = "<!-- golden-path-train:start -->"
TRAIN_END = "<!-- golden-path-train:end -->"
_SHA = re.compile(r"[0-9a-f]{40}")
_FENCE = re.compile(r"```sh\n(.*?)```", re.DOTALL)


def fenced_commands(text: str, start: str, end: str) -> list[str]:
    begin = text.find(start)
    stop = text.find(end, begin + len(start) if begin >= 0 else 0)
    if begin < 0 or stop < 0:
        raise ValueError("README is missing the documented golden-path commands.")
    match = _FENCE.search(text[begin + len(start) : stop])
    if match is None:
        raise ValueError("README golden-path block has no shell fence.")
    commands = [line.strip() for line in match.group(1).splitlines() if line.strip() and not line.strip().startswith("#")]
    if not commands:
        raise ValueError("README golden-path block is empty.")
    return commands


def install_commands(text: str) -> list[str]:
    return fenced_commands(text, INSTALL_START, INSTALL_END)


def train_command(text: str, steps: int) -> str:
    if type(steps) is not int or not 1 <= steps <= MAX_STEPS:
        raise ValueError(f"Golden path trains 1–{MAX_STEPS} CPU steps.")
    commands = fenced_commands(text, TRAIN_START, TRAIN_END)
    if len(commands) != 1 or "--steps" not in commands[0]:
        raise ValueError("README training block must be one command with --steps.")
    updated, count = re.subn(r"--steps\s+\d+", f"--steps {steps}", commands[0], count=1)
    if count != 1 or f"--steps {steps}" not in updated:
        raise ValueError("Could not set the documented training step count.")
    return updated


def verify_snapshot(directory: Path, hashes: dict[str, str], limits: dict) -> None:
    """Fail closed when a pinned file is missing, the wrong size, or retampered."""
    for name, expected in hashes.items():
        path = directory / name
        maximum = limits["weight_bytes"] if name.endswith(".safetensors") else limits["aux_bytes"]
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValueError(f"{name}: pinned file is missing after download") from exc
        if not 1 <= size <= maximum:
            raise ValueError(f"{name}: pinned file is outside its verified size limit")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"{name}: pinned SmolLM2 checksum changed; refusing to train")


def _download_missing(directory: Path, names: list[str], source: dict) -> None:
    from huggingface_hub import hf_hub_download
    from modelanvil.core.privacy import acquisition_scope, install_hub_guard, require_destination

    with acquisition_scope(None, None, public_provisioning=True):
        require_destination("https://huggingface.co")
        install_hub_guard()
        for name in names:
            hf_hub_download(
                source["repo_id"],
                name,
                revision=source["revision"],
                local_dir=str(directory),
                token=False,
            )


def acquire_pinned_base(directory: Path) -> Path:
    from modelanvil.runners.training.hf_runtime import FILE_HASHES, LIMITS, SOURCE

    directory.mkdir(parents=True, exist_ok=True)
    missing = [name for name in FILE_HASHES if not (directory / name).is_file()]
    if missing:
        _download_missing(directory, missing, SOURCE)
    verify_snapshot(directory, FILE_HASHES, LIMITS)
    return directory


def prepare_and_train(directory: Path, steps: int) -> int:
    acquire_pinned_base(directory)
    return run_steps(directory, steps)


def _samples(path: Path) -> None:
    import json
    import uuid

    texts = [
        "ModelAnvil verifies training inputs and saves durable checkpoints.",
        "A telescope collects light from distant stars to study the universe.",
        "Ocean waves move energy across water while tides follow gravitational forces.",
        "A recipe combines measured ingredients before the bread is baked.",
        "Trees absorb sunlight and grow leaves through photosynthesis.",
        "A compiler translates source code into instructions for a computer.",
        "Rainwater flows into streams and eventually reaches the sea.",
        "A bicycle uses two wheels and pedals to move along a road.",
        "An orchestra plays music with strings, wind instruments and percussion.",
        "A library organizes books so that readers can find useful information.",
    ]
    rows = []
    for index, text in enumerate(texts):
        rows.append({
            "schema_version": "1.0",
            "sample_id": str(uuid.uuid4()),
            "source_group_id": str(index),
            "blocks": [{"block_id": "text", "type": "text", "text": text}],
            "provenance": {
                "source_snapshot_ref": "golden-path-synthetic-fixture",
                "source_record_key": str(index),
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
            },
        })
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def run_steps(directory: Path, steps: int) -> int:
    """Train the bounded CPU LoRA profile. Caller has already verified the snapshot."""
    import io
    import json
    import uuid

    from django.core.management import call_command
    from rest_framework.test import APIClient

    from modelanvil.core.tenancy import set_active_tenant
    from modelanvil.identity.management.commands.bootstrap_dev import DEV_API_KEY
    from modelanvil.identity.models import Project, Tenant
    from modelanvil.jobs.executor import execute_claim
    from modelanvil.jobs.models import JobAttempt, Worker, claim_job
    from modelanvil.runners.models import TrainingRun
    from modelanvil.runners.training.executor import training_worker_executor

    if type(steps) is not int or not 1 <= steps <= MAX_STEPS:
        raise ValueError(f"Golden path trains 1–{MAX_STEPS} CPU steps.")
    tenant = Tenant.objects.get(slug="default")
    set_active_tenant(tenant.pk)
    project = Project.objects.get(tenant_id=tenant.pk, slug="primary-llm")
    samples = directory.parent / f"golden-path-samples-{uuid.uuid4().hex}.jsonl"
    _samples(samples)
    name = f"golden-cpu-{uuid.uuid4().hex[:8]}"
    output = io.StringIO()
    call_command(
        "setup_gpu_training",
        tenant_id=tenant.pk,
        project_id=project.pk,
        name=name,
        model_dir=directory,
        samples=samples,
        device="cpu",
        recipe="lora_adapter",
        steps=steps,
        stdout=output,
    )
    installed = json.loads(output.getvalue())
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {DEV_API_KEY}")
    headers = {"HTTP_X_PROJECT_ID": str(project.pk)}
    preview = client.post("/api/v1/training-runs/preflight/", installed["launch"], format="json", **headers)
    if preview.status_code != 200 or preview.data.get("status") != "approved":
        raise RuntimeError(f"preflight refused training: {preview.status_code} {preview.data}")
    launch = client.post(
        "/api/v1/training-runs/",
        {**installed["launch"], "preflight_token": preview.data["preflight_token"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=name,
        **headers,
    )
    if launch.status_code != 201:
        raise RuntimeError(f"launch failed: {launch.status_code} {launch.data}")
    set_active_tenant(tenant.pk)
    run = TrainingRun.all_objects.get(run_id=launch.data["run_id"])
    worker = Worker.all_objects.get(pk=installed["worker_id"])
    descriptor = claim_job(worker)
    if not descriptor:
        raise RuntimeError("CPU worker did not claim the training job")
    outcome = execute_claim(worker, descriptor, training_worker_executor)
    run.refresh_from_db()
    if not (outcome.get("committed") and outcome.get("status") == "succeeded" and run.status == "completed" and run.current_step == steps):
        attempt = JobAttempt.all_objects.filter(job_id=run.job_id).order_by("-started_at").first()
        detail = attempt.error if attempt else ""
        raise RuntimeError(
            f"training did not finish {steps} CPU steps: outcome={outcome} status={run.status} step={run.current_step} error={detail}"
        )
    print(f"completed {run.current_step} SmolLM2-135M CPU LoRA steps", flush=True)
    return run.current_step


def _git(destination: Path, *args: str) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(["git", "-C", str(destination), *args], env=env)
    if completed.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed")


def clone_sha(sha: str, destination: Path) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.run(["git", "init", str(destination)], check=True, env=env)
    _git(destination, "remote", "add", "origin", REMOTE)
    _git(destination, "fetch", "--depth", "1", "origin", sha)
    _git(destination, "checkout", "--detach", "FETCH_HEAD")
    head = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if head != sha:
        raise SystemExit(f"checked out {head}, not {sha}")


def run_shell(command: str, cwd: Path) -> None:
    print(f"+ {command}", flush=True)
    completed = subprocess.run(["bash", "-o", "pipefail", "-c", command], cwd=cwd)
    if completed.returncode != 0:
        raise SystemExit(f"command failed ({completed.returncode}): {command}")


def orchestrate(sha: str, steps: int) -> int:
    if not _SHA.fullmatch(sha):
        print("Pass the 40-character lowercase commit SHA to clone.", file=sys.stderr)
        return 2
    if type(steps) is not int or not 1 <= steps <= MAX_STEPS:
        print(f"Golden path trains 1–{MAX_STEPS} CPU steps.", file=sys.stderr)
        return 2
    destination = Path(tempfile.mkdtemp(prefix="modelanvil-golden-"))
    print(f"cloning {sha} into {destination}", flush=True)
    try:
        clone_sha(sha, destination)
        readme = (destination / "README.md").read_text(encoding="utf-8")
        for command in install_commands(readme):
            run_shell(command, destination)
        run_shell(train_command(readme, steps), destination)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        print(f"golden path left the checkout at {destination}", file=sys.stderr)
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        print(f"golden path failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        print(f"golden path left the checkout at {destination}", file=sys.stderr)
        return 1
    shutil.rmtree(destination)
    print(f"golden path completed {steps} SmolLM2-135M CPU steps at {sha}", flush=True)
    return 0


def train_cli(steps: int) -> int:
    if type(steps) is not int or not 1 <= steps <= MAX_STEPS:
        print(f"Golden path trains 1–{MAX_STEPS} CPU steps.", file=sys.stderr)
        return 2
    if os.environ.get("MODELANVIL_PUBLIC_MODEL_DOWNLOADS") != "1":
        print(
            "Pinned model download is disabled. Set MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1 "
            "for the public SmolLM2 snapshot. Refusing to skip training.",
            file=sys.stderr,
        )
        return 1
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_HUB_TOKEN"):
        os.environ.pop(name, None)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import django

    django.setup()
    directory = root / "data" / "smollm2-135m"
    print("downloading or verifying the pinned public SmolLM2-135M snapshot", flush=True)
    try:
        completed = prepare_and_train(directory, steps)
    except Exception as exc:
        print(f"pinned SmolLM2 CPU run failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    if completed != steps:
        print(f"CPU training stopped at {completed} steps; expected {steps}.", file=sys.stderr)
        return 1
    return 0


def _steps_flag(argv: list[str]) -> int | None:
    if not argv:
        return DEFAULT_STEPS
    if len(argv) != 2 or argv[0] != "--steps":
        print("Usage: scripts/golden_path.sh <sha> [--steps N]", file=sys.stderr)
        return None
    try:
        return int(argv[1])
    except ValueError:
        print("Steps must be an integer from 1 to 10.", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--train" in argv:
        steps = _steps_flag([item for item in argv if item != "--train"])
        if steps is None:
            return 2
        return train_cli(steps)
    if not argv or argv[0].startswith("-"):
        print("Usage: scripts/golden_path.sh <sha> [--steps N]", file=sys.stderr)
        return 2
    steps = _steps_flag(argv[1:])
    if steps is None:
        return 2
    return orchestrate(argv[0], steps)


if __name__ == "__main__":
    sys.exit(main())
