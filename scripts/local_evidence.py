#!/usr/bin/env python3
"""Run one command and write a local evidence record (ANVIL-002).

The record conforms to docs/engineering/schemas/local-evidence.v1.json.
A dirty worktree is refused before the command starts. Skip, xfail, and
timeout counts must be zero or the record is not written.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "engineering" / "schemas" / "local-evidence.v1.json"

# Fixture qualifications that are collected only when their verified local
# input is present. A missing fixture is not recorded as a runtime skip.
FIXTURE_TESTS = (
    (
        "MODELANVIL_MLX_TEST_MODEL_DIR",
        "modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests."
        "test_frozen_four_bit_base_actual_update_exact_resume_and_corruption",
    ),
    (
        "MODELANVIL_GGUF_TEST_MODEL",
        "modelanvil.runners.test_gguf_runtime.GGUFNative."
        "test_actual_cpu_generation_cancellation_and_unload",
    ),
)

_RAN = re.compile(r"^Ran (?P<collected>\d+) tests? in ", re.MULTILINE)
_SUMMARY = re.compile(r"^(?P<status>OK|FAILED)(?: \((?P<details>.*)\))?\s*$", re.MULTILINE)
_NODE_LINE = re.compile(
    r"^(?:ℹ|#) (?P<key>tests|suites|pass|fail|skipped|todo|cancelled) (?P<value>\d+)\s*$",
    re.MULTILINE,
)


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validation_errors(document: dict, schema: dict | None = None) -> list[str]:
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema or load_schema())
    messages = []
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        messages.append(f"{location}: {error.message}")
    for index, run in enumerate(document.get("runs") or []):
        if not isinstance(run, dict):
            continue
        excluded = run.get("excluded_ids")
        count = run.get("excluded_by_tag")
        if isinstance(excluded, list) and isinstance(count, int) and count != len(excluded):
            messages.append(
                f"runs/{index}: excluded_by_tag is {count} but excluded_ids has {len(excluded)} entries"
            )
        collected = run.get("collected")
        passed = run.get("passed")
        if isinstance(collected, int) and isinstance(passed, int) and passed > collected:
            messages.append(f"runs/{index}: passed {passed} exceeds collected {collected}")
    return messages


def _detail_counts(details: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not details:
        return counts
    for part in details.split(","):
        key, value = part.strip().rsplit("=", 1)
        counts[key.strip()] = int(value)
    return counts


def _django_runs(text: str, command: str) -> list[dict]:
    runs = []
    matches = list(_RAN.finditer(text))
    for index, match in enumerate(matches):
        collected = int(match.group("collected"))
        window_end = matches[index + 1].start() if index + 1 < len(matches) else match.end() + 800
        summary = _SUMMARY.search(text[match.end() : window_end])
        details = summary.group("details") if summary and summary.group("details") else ""
        counts = _detail_counts(details)
        skipped = counts.get("skipped", 0)
        failures = counts.get("failures", 0)
        errors = counts.get("errors", 0)
        xfailed = counts.get("expected failures", 0)
        timeout = counts.get("timeouts", 0)
        passed = collected - skipped - failures - errors - xfailed
        name = "tests" if len(matches) == 1 else f"tests-{index + 1}"
        runs.append(
            _run(
                name=name,
                command=command,
                collected=collected,
                passed=passed,
                skipped=skipped,
                xfailed=xfailed,
                timeout=timeout,
            )
        )
    return runs


def _node_runs(text: str, command: str) -> list[dict]:
    """Parse one node:test summary. Later duplicate keys belong to a later run."""
    blocks: list[dict[str, int]] = []
    current: dict[str, int] = {}
    for match in _NODE_LINE.finditer(text):
        key = match.group("key")
        if key == "tests" and current:
            blocks.append(current)
            current = {}
        current[key] = int(match.group("value"))
    if current.get("tests") is not None:
        blocks.append(current)
    runs = []
    for index, block in enumerate(blocks):
        name = "node-tests" if len(blocks) == 1 else f"node-tests-{index + 1}"
        runs.append(
            _run(
                name=name,
                command=command,
                collected=block.get("tests", 0),
                passed=block.get("pass", 0),
                skipped=block.get("skipped", 0),
                xfailed=block.get("todo", 0),
                timeout=block.get("cancelled", 0),
            )
        )
    return runs


def _run(*, name: str, command: str, collected: int, passed: int, skipped: int, xfailed: int, timeout: int) -> dict:
    return {
        "name": name,
        "command": command,
        "collected": collected,
        "excluded_by_tag": 0,
        "passed": passed,
        "skipped": skipped,
        "xfailed": xfailed,
        "timeout": timeout,
        "excluded_ids": [],
    }


def parse_runs(text: str, command: str) -> list[dict]:
    runs = _django_runs(text, command)
    runs.extend(_node_runs(text, command))
    if runs:
        return runs
    return [_run(name="command", command=command, collected=0, passed=0, skipped=0, xfailed=0, timeout=0)]


def git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def machine() -> dict:
    node = subprocess.run(["node", "--version"], check=True, capture_output=True, text=True)
    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "node": node.stdout.strip(),
    }


def _command_tags(argv: list[str], flag: str) -> list[str]:
    found = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        prefix = f"--{flag}="
        if arg.startswith(prefix):
            found.append(arg[len(prefix) :])
        elif arg == f"--{flag}" and index + 1 < len(argv):
            found.append(argv[index + 1])
            index += 1
        index += 1
    return found


def _iter_tests(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def tagged_test_ids(root: Path, *, tag: str) -> list[str]:
    """Return Django test IDs that carry `tag`, without executing them."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    previous = os.getcwd()
    os.chdir(root)
    try:
        import django

        django.setup()
        from modelanvil.core.test_runner import Runner

        runner = Runner(verbosity=0, interactive=False, tags={tag})
        return sorted(test.id() for test in _iter_tests(runner.build_suite()))
    finally:
        os.chdir(previous)


def uncollected_fixture_tests() -> list[str]:
    return [test_id for env_name, test_id in FIXTURE_TESTS if not os.environ.get(env_name)]


def _records_test_counts(argv: list[str]) -> bool:
    joined = shlex.join(argv)
    markers = ("manage.py", "django", "pytest", "npm", "make test")
    return "test" in joined and any(marker in joined for marker in markers)


def build_record(
    *,
    root: Path,
    argv: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    sha: str,
    porcelain: str,
) -> dict:
    command = shlex.join(argv)
    runs = parse_runs(stdout + ("\n" + stderr if stderr else ""), command)
    exclude_tags = _command_tags(argv, "exclude-tag")
    if exclude_tags:
        excluded: list[str] = []
        for tag in exclude_tags:
            excluded.extend(tagged_test_ids(root, tag=tag))
        excluded = sorted(set(excluded))
        for run in runs:
            run["excluded_by_tag"] = len(excluded)
            run["excluded_ids"] = excluded
    document = {
        "schema_version": "1",
        "label": "local",
        "sha": sha,
        "git_status_porcelain": porcelain,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": machine(),
        "command": command,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "runs": runs,
    }
    if _records_test_counts(argv):
        document["fixture_tests_not_collected"] = uncollected_fixture_tests()
    return document


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


def run_command(root: Path, argv: list[str]) -> tuple[int, str, str]:
    process = subprocess.Popen(
        argv,
        cwd=root,
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


def write_record(root: Path, argv: list[str], output: Path) -> int:
    porcelain = git_output(root, "status", "--porcelain")
    if porcelain != "":
        print("local evidence requires an empty git status --porcelain", file=sys.stderr)
        print(porcelain, file=sys.stderr, end="")
        return 2
    sha = git_output(root, "rev-parse", "HEAD").strip()
    exit_code, stdout, stderr = run_command(root, argv)
    document = build_record(
        root=root,
        argv=argv,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        sha=sha,
        porcelain=porcelain,
    )
    errors = validation_errors(document)
    if errors:
        print("local evidence record does not conform:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 3 if exit_code == 0 else exit_code
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a command and write a local evidence record.")
    parser.add_argument("--output", required=True, type=Path, help="Path of the JSON record to write")
    parser.add_argument("--root", type=Path, default=ROOT, help="Git worktree to record")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run, after --")
    args = parser.parse_args(argv)
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("pass the command after --")
    return write_record(args.root.resolve(), command, args.output)


if __name__ == "__main__":
    sys.exit(main())
