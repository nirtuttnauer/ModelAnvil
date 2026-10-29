"""Pytest for the ANVIL-002 local evidence record.

A conforming sample passes. Missing SHA, a dirty worktree, a missing exit
code, or a non-zero skip count fails validation.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "engineering" / "schemas" / "local-evidence.v1.json"
EXAMPLES = ROOT / "docs" / "engineering" / "verification" / "anvil-002-2026-10-29"


def _load():
    spec = importlib.util.spec_from_file_location("local_evidence", ROOT / "scripts" / "local_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load()


def sample() -> dict:
    return {
        "schema_version": "1",
        "label": "local",
        "sha": "3200915506331979c712c17ffd0b1817f95fda75",
        "git_status_porcelain": "",
        "recorded_at": "2026-10-29T03:54:00+00:00",
        "machine": {
            "hostname": "evidence-host",
            "os": "Linux-6.12-x86_64",
            "arch": "x86_64",
            "python": "3.12.3",
            "node": "v22.23.4",
        },
        "command": "make check",
        "exit_code": 0,
        "stdout": "System check identified no issues (0 silenced).\n",
        "stderr": "",
        "runs": [
            {
                "name": "command",
                "command": "make check",
                "collected": 0,
                "excluded_by_tag": 0,
                "passed": 0,
                "skipped": 0,
                "xfailed": 0,
                "timeout": 0,
                "excluded_ids": [],
            }
        ],
    }


def test_schema_file_is_valid_json_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    import jsonschema

    jsonschema.Draft202012Validator.check_schema(schema)


def test_sample_record_conforms():
    assert evidence.validation_errors(sample()) == []


def test_missing_sha_fails():
    document = sample()
    del document["sha"]
    assert evidence.validation_errors(document)


def test_dirty_status_fails():
    document = sample()
    document["git_status_porcelain"] = " M Makefile\n"
    assert evidence.validation_errors(document)


def test_missing_exit_code_fails():
    document = sample()
    del document["exit_code"]
    assert evidence.validation_errors(document)


def test_nonzero_skip_count_fails():
    document = sample()
    document["runs"][0]["skipped"] = 1
    assert evidence.validation_errors(document)


def test_nonzero_xfail_and_timeout_fail():
    for field in ("xfailed", "timeout"):
        document = sample()
        document["runs"][0][field] = 1
        assert evidence.validation_errors(document), field


def test_django_skip_summary_is_rejected():
    text = "Ran 6 tests in 0.040s\n\nOK (skipped=1)\n"
    runs = evidence.parse_runs(text, "python manage.py test --exclude-tag=pg")
    assert runs[0]["collected"] == 6
    assert runs[0]["passed"] == 5
    assert runs[0]["skipped"] == 1
    document = sample()
    document["runs"] = runs
    assert evidence.validation_errors(document)


def test_clean_django_and_node_summaries_count_passes():
    django = "Ran 4 tests in 0.010s\n\nOK\n"
    parsed = evidence.parse_runs(django, "python manage.py test --exclude-tag=pg")
    assert parsed[0]["collected"] == 4
    assert parsed[0]["passed"] == 4
    assert parsed[0]["skipped"] == 0
    node = "ℹ tests 3\nℹ pass 3\nℹ fail 0\nℹ skipped 0\n"
    parsed = evidence.parse_runs(node, "npm test")
    assert parsed[0]["collected"] == 3
    assert parsed[0]["passed"] == 3
    assert parsed[0]["skipped"] == 0
    tap = "# tests 249\n# pass 249\n# fail 0\n# skipped 0\n# todo 0\n# cancelled 0\n"
    parsed = evidence.parse_runs(tap, "npm test")
    assert parsed[0]["collected"] == 249
    assert parsed[0]["passed"] == 249
    assert parsed[0]["skipped"] == 0


def test_wrapper_writes_a_conforming_record_from_a_clean_repo(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "evidence@example.com")
    _git(root, "config", "user.name", "Evidence Test")
    (root / "README").write_text("evidence\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    output = tmp_path / "record.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "local_evidence.py"),
            "--root",
            str(root),
            "--output",
            str(output),
            "--",
            sys.executable,
            "-c",
            "print('local-ok')",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    document = json.loads(output.read_text(encoding="utf-8"))
    assert evidence.validation_errors(document) == []
    assert document["label"] == "local"
    assert document["sha"] == _git(root, "rev-parse", "HEAD").strip()
    assert document["git_status_porcelain"] == ""
    assert document["exit_code"] == 0
    assert "local-ok" in document["stdout"]
    assert document["command"] == shlex_join([sys.executable, "-c", "print('local-ok')"])
    assert document["runs"][0]["skipped"] == 0


def test_wrapper_refuses_a_dirty_worktree(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "evidence@example.com")
    _git(root, "config", "user.name", "Evidence Test")
    (root / "README").write_text("evidence\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    (root / "README").write_text("dirty\n", encoding="utf-8")
    output = tmp_path / "record.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "local_evidence.py"),
            "--root",
            str(root),
            "--output",
            str(output),
            "--",
            sys.executable,
            "-c",
            "print('nope')",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert not output.exists()


def test_recorded_examples_conform_when_present():
    if not EXAMPLES.exists():
        return
    files = sorted(EXAMPLES.glob("*.json"))
    assert files, "the make check record is the first example"
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert evidence.validation_errors(document) == [], path.name
        assert document["label"] == "local"
        assert document["git_status_porcelain"] == ""


def shlex_join(argv: list[str]) -> str:
    import shlex

    return shlex.join(argv)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    return completed.stdout
