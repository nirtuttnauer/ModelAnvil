#!/usr/bin/env python3
"""One local pre-merge command (ANVIL-009).

Requires Python 3.12 and Node.js 24. Runs the backend suite, the frontend
test/build/storybook suite, and the PostgreSQL `--tag=pg` suite against the
CI Docker images. A failure, skip, expected failure, or timeout exits
non-zero. A clean run writes one ANVIL-002 local evidence record.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from local_evidence import (  # noqa: E402
    machine,
    parse_runs,
    tagged_test_ids,
    uncollected_fixture_tests,
    validation_errors,
)

DEFAULT_OUTPUT = ROOT / "docs" / "engineering" / "verification" / "anvil-009-2026-10-29" / "premerge.json"
COMPOSE_FILE = ROOT / "compose.premerge.yaml"
COMPOSE_PROJECT = "modelanvil-premerge"
# Same published CI password as .github/workflows/ci.yml. Kept out of the record.
PG_PASSWORD = "modelanvil"
CI_IMAGES = ("pgvector/pgvector:pg16", "rabbitmq:4.1-alpine")


def node_rejection(version: str) -> str | None:
    text = version.strip()
    number = text[1:] if text.startswith("v") else text
    major_text = number.split(".", 1)[0]
    if not major_text.isdigit() or int(major_text) != 24:
        found = text or "an unknown version"
        return (
            f"premerge requires Node.js 24; found {found}.\n"
            "Node.js 20 fails the frontend suite. Install Node.js 24, run `nvm use` "
            "from the repository root (.nvmrc), and run `make premerge` again."
        )
    return None


def python_rejection(version_info: tuple[int, ...] | object) -> str | None:
    major = getattr(version_info, "major", None)
    minor = getattr(version_info, "minor", None)
    if major is None:
        major, minor = version_info[0], version_info[1]  # type: ignore[index]
    if (major, minor) != (3, 12):
        return (
            f"premerge requires Python 3.12; found {major}.{minor}.\n"
            "The backend suite matches CI's Python 3.12. Recreate .venv with Python 3.12 "
            "and run `make premerge` again."
        )
    return None


def runtime_problem(runs: list[dict]) -> str | None:
    for run in runs:
        if run["skipped"] or run["xfailed"] or run["timeout"]:
            return (
                f"{run['name']} has a skip, expected failure, or timeout "
                f"(skipped={run['skipped']}, xfailed={run['xfailed']}, timeout={run['timeout']}). "
                "That is a premerge failure."
            )
    return None


def apply_exclusions(run: dict, excluded_ids: list[str]) -> None:
    run["excluded_by_tag"] = len(excluded_ids)
    run["excluded_ids"] = list(excluded_ids)


def _django_only(runs: list[dict]) -> list[dict]:
    return [run for run in runs if run["name"] == "tests" or run["name"].startswith("tests-")]


def _node_only(runs: list[dict]) -> list[dict]:
    return [run for run in runs if run["name"] == "node-tests" or run["name"].startswith("node-tests-")]


def _rename(runs: list[dict], name: str, command: str) -> list[dict]:
    renamed = []
    for index, run in enumerate(runs):
        item = dict(run)
        item["name"] = name if len(runs) == 1 else f"{name}-{index + 1}"
        item["command"] = command
        renamed.append(item)
    return renamed


def _tee(stream, sink: list[str], echo) -> None:
    chunks = []
    while True:
        chunk = stream.read(65536)
        if chunk == "":
            break
        chunks.append(chunk)
        echo.write(chunk)
        echo.flush()
    sink.append("".join(chunks))


def run_argv(argv: list[str], env: dict[str, str], root: Path) -> tuple[int, str, str]:
    process = subprocess.Popen(
        argv,
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    threads = [
        threading.Thread(target=_tee, args=(process.stdout, stdout_parts, sys.stdout)),
        threading.Thread(target=_tee, args=(process.stderr, stderr_parts, sys.stderr)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return process.wait(), stdout_parts[0] if stdout_parts else "", stderr_parts[0] if stderr_parts else ""


def _section(title: str, body: str) -> str:
    return f"== {title} ==\n{body}"


def _combine(stdout: str, stderr: str) -> str:
    if not stderr:
        return stdout
    if stdout and not stdout.endswith("\n"):
        stdout += "\n"
    return stdout + stderr


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("DATABASE_ENGINE", None)
    env.pop("DATABASE_PASSWORD", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT)
    env["DJANGO_SETTINGS_MODULE"] = "modelanvil.settings"
    return env


def backend_command(python: str) -> list[str]:
    return [python, "manage.py", "test", "--noinput", "--exclude-tag=pg", "-v", "1"]


def frontend_commands() -> list[list[str]]:
    return [
        ["npm", "--prefix", "web", "ci"],
        ["npm", "--prefix", "web", "test"],
        ["npm", "--prefix", "web", "run", "build"],
        ["npm", "--prefix", "web", "run", "build-storybook"],
    ]


def pg_command(python: str) -> list[str]:
    return [python, "manage.py", "test", "--noinput", "--tag=pg", "-v", "1"]


def pg_test_env(base: dict[str, str], cache_root: Path) -> dict[str, str]:
    env = base.copy()
    env.update(
        {
            "DATABASE_ENGINE": "postgresql",
            "DATABASE_NAME": "modelanvil",
            "DATABASE_USER": "modelanvil",
            "DATABASE_PASSWORD": PG_PASSWORD,
            "DATABASE_HOST": "127.0.0.1",
            "DATABASE_PORT": "5432",
            "RABBITMQ_URL": "amqp://guest:guest@127.0.0.1:5672/%2F",
            "HF_HOME": str(cache_root / "embedding-model"),
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MODELANVIL_BENCHMARK_CACHE": str(cache_root / "retrieval-benchmark"),
            "MODELANVIL_RAG_DECODER_CACHE": str(cache_root / "rag-decoder"),
            "MODELANVIL_RAG_GENERATION_REPORT": str(cache_root / "rag-generation-report.json"),
            "MODELANVIL_POSITION_REPORT": str(cache_root / "evidence-position-report.json"),
            "MODELANVIL_RETRIEVAL_REPORT": str(cache_root / "retrieval-controls-report.json"),
        }
    )
    return env


def pg_display_command(python: str, cache_root: Path) -> str:
    shown = pg_test_env({}, cache_root)
    shown.pop("DATABASE_PASSWORD")
    prefix = " ".join(f"{key}={value}" for key, value in shown.items())
    return prefix + " " + shlex.join(pg_command(python))


def compose(*args: str) -> list[str]:
    return ["docker", "compose", "-p", COMPOSE_PROJECT, "-f", str(COMPOSE_FILE), *args]


def ensure_pg_images(root: Path) -> tuple[int, str]:
    up = compose("up", "-d", "--wait", "db", "rabbitmq")
    print(_section("docker compose up", shlex.join(up)), flush=True)
    code, stdout, stderr = run_argv(up, os.environ.copy(), root)
    text = _combine(stdout, stderr)
    if code != 0:
        return code, text
    listing_argv = compose("ps", "--format", "{{.Image}}")
    code, stdout, stderr = run_argv(listing_argv, os.environ.copy(), root)
    listing = _combine(stdout, stderr)
    missing = [image for image in CI_IMAGES if image not in listing]
    if code != 0 or missing:
        detail = listing if not missing else listing + "\nmissing CI image(s): " + ", ".join(missing)
        return 1, text + "\n" + detail
    return 0, text + "\n" + listing


def cache_pg_models(python: str, env: dict[str, str], root: Path) -> tuple[int, str]:
    online = env.copy()
    online.pop("HF_HUB_OFFLINE", None)
    online.pop("TRANSFORMERS_OFFLINE", None)
    steps = [
        [python, "-c", "from modelanvil.rag.embedding_model import cache_pinned_model; cache_pinned_model()"],
        [python, "-c", "from modelanvil.rag.benchmark_corpus import cache_corpus; cache_corpus()"],
        [python, "manage.py", "cache_rag_decoder"],
    ]
    chunks = []
    for argv in steps:
        display = shlex.join(argv)
        print(_section("pg cache", display), flush=True)
        code, stdout, stderr = run_argv(argv, online, root)
        chunks.append(_section(display, _combine(stdout, stderr)))
        if code != 0:
            return code, "\n".join(chunks)
    return 0, "\n".join(chunks)


def git_stdout(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def excluded_pg_ids() -> list[str]:
    keys = ("DATABASE_ENGINE", "DATABASE_NAME", "DATABASE_TEST_NAME", "DATABASE_PASSWORD")
    saved = {key: os.environ.get(key) for key in keys}
    os.environ.pop("DATABASE_ENGINE", None)
    os.environ.pop("DATABASE_PASSWORD", None)
    os.environ["DATABASE_NAME"] = "/tmp/modelanvil-premerge/discover.sqlite3"
    os.environ["DATABASE_TEST_NAME"] = "/tmp/modelanvil-premerge/discover-test.sqlite3"
    try:
        return tagged_test_ids(ROOT, tag="pg")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def zero_run(name: str, command: str) -> dict:
    return {
        "name": name,
        "command": command,
        "collected": 0,
        "excluded_by_tag": 0,
        "passed": 0,
        "skipped": 0,
        "xfailed": 0,
        "timeout": 0,
        "excluded_ids": [],
    }


def run_frontend() -> tuple[int, list[str], list[dict]]:
    sections: list[str] = []
    runs: list[dict] = []
    for argv in frontend_commands():
        display = shlex.join(argv)
        print(_section("frontend", display), flush=True)
        code, stdout, stderr = run_argv(argv, os.environ.copy(), ROOT)
        chunk = _combine(stdout, stderr)
        sections.append(_section(display, chunk))
        if argv == ["npm", "--prefix", "web", "test"]:
            parsed = _rename(_node_only(parse_runs(chunk, display)), "frontend", display)
            if code == 0 and not parsed:
                print("frontend output did not include a node:test summary", file=sys.stderr)
                return 1, sections, runs
            runs.extend(parsed)
        elif code == 0:
            if argv == ["npm", "--prefix", "web", "ci"]:
                name = "frontend-install"
            elif "build-storybook" in argv:
                name = "frontend-storybook"
            else:
                name = "frontend-build"
            runs.append(zero_run(name, display))
        if code != 0:
            return code, sections, runs
    return 0, sections, runs


def build_document(*, sha: str, sections: list[str], runs: list[dict]) -> dict:
    return {
        "schema_version": "1",
        "label": "local",
        "sha": sha,
        "git_status_porcelain": "",
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": machine(),
        "command": "make premerge",
        "exit_code": 0,
        "stdout": "\n".join(sections),
        "stderr": "",
        "fixture_tests_not_collected": uncollected_fixture_tests(),
        "runs": runs,
    }


def _report_failure(code: int, runs: list[dict]) -> int:
    problem = runtime_problem(runs)
    if problem:
        print(problem, file=sys.stderr)
        return code or 1
    print(f"premerge failed with exit code {code}", file=sys.stderr)
    return code or 1


def execute(python: str, output: Path) -> int:
    porcelain = git_stdout("status", "--porcelain")
    if porcelain != "":
        print("premerge requires an empty git status --porcelain", file=sys.stderr)
        print(porcelain, file=sys.stderr, end="")
        return 2
    sha = git_stdout("rev-parse", "HEAD").strip()
    env = _base_env()
    work = Path("/tmp/modelanvil-premerge")
    work.mkdir(parents=True, exist_ok=True)
    env["DATABASE_NAME"] = str(work / "dev.sqlite3")
    env["DATABASE_TEST_NAME"] = str(work / "test.sqlite3")
    sections: list[str] = []
    runs: list[dict] = []

    backend = backend_command(python)
    backend_display = (
        f"DATABASE_NAME={env['DATABASE_NAME']} DATABASE_TEST_NAME={env['DATABASE_TEST_NAME']} "
        + shlex.join(backend)
    )
    print(_section("backend", backend_display), flush=True)
    code, stdout, stderr = run_argv(backend, env, ROOT)
    text = _combine(stdout, stderr)
    sections.append(_section(backend_display, text))
    parsed = _rename(_django_only(parse_runs(text, backend_display)), "backend", backend_display)
    if parsed:
        excluded = excluded_pg_ids()
        for run in parsed:
            apply_exclusions(run, excluded)
        runs.extend(parsed)
    if code != 0 or not parsed:
        if code == 0:
            print("backend output did not include a Django test summary", file=sys.stderr)
            return 1
        return _report_failure(code, runs)
    if runtime_problem(runs):
        return _report_failure(1, runs)

    front_code, front_sections, front_runs = run_frontend()
    sections.extend(front_sections)
    runs.extend(front_runs)
    if front_code != 0:
        return _report_failure(front_code, runs)
    if runtime_problem(runs):
        return _report_failure(1, runs)

    cache_root = work / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    try:
        code, docker_text = ensure_pg_images(ROOT)
        sections.append(_section("pgvector docker", docker_text))
        if code != 0:
            exit_code = code
        else:
            code, cache_text = cache_pg_models(python, pg_test_env(env, cache_root), ROOT)
            sections.append(_section("pgvector cache", cache_text))
            if code != 0:
                exit_code = code
            else:
                display = pg_display_command(python, cache_root)
                print(_section("pgvector", display), flush=True)
                code, stdout, stderr = run_argv(pg_command(python), pg_test_env(env, cache_root), ROOT)
                text = _combine(stdout, stderr)
                sections.append(_section(display, text))
                parsed = _rename(_django_only(parse_runs(text, display)), "pgvector", display)
                if code == 0 and not parsed:
                    print("pgvector output did not include a Django test summary", file=sys.stderr)
                    code = 1
                runs.extend(parsed)
                exit_code = code
    finally:
        down = compose("down", "-v", "--remove-orphans")
        print(_section("docker compose down", shlex.join(down)), flush=True)
        down_code, down_out, down_err = run_argv(down, os.environ.copy(), ROOT)
        sections.append(_section(shlex.join(down), _combine(down_out, down_err)))
        if down_code != 0 and exit_code == 0:
            exit_code = down_code

    problem = runtime_problem(runs)
    if problem or exit_code != 0:
        if problem:
            print(problem, file=sys.stderr)
        else:
            print(f"premerge failed with exit code {exit_code}", file=sys.stderr)
        return exit_code or 1

    document = build_document(sha=sha, sections=sections, runs=runs)
    errors = validation_errors(document)
    if errors:
        print("local evidence record does not conform:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"premerge record: {output}")
    return 0


def fail_fast() -> int | None:
    try:
        version = subprocess.run(
            ["node", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print(node_rejection(""), file=sys.stderr)
        return 1
    if version.returncode != 0:
        print(node_rejection(version.stdout.strip() or version.stderr.strip()), file=sys.stderr)
        return 1
    rejection = node_rejection(version.stdout)
    if rejection:
        print(rejection, file=sys.stderr)
        return 1
    rejection = python_rejection(sys.version_info)
    if rejection:
        print(rejection, file=sys.stderr)
        return 1
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        argparse.ArgumentParser(
            description="Run the local pre-merge suites and write an ANVIL-002 record."
        ).print_help()
        return 0
    failed = fail_fast()
    if failed:
        return failed
    parser = argparse.ArgumentParser(
        description="Run the local pre-merge suites and write an ANVIL-002 record."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="ANVIL-002 record path")
    args = parser.parse_args(argv)
    return execute(sys.executable, args.output)


if __name__ == "__main__":
    sys.exit(main())
