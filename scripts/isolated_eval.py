#!/usr/bin/env python3
"""Prefetch pinned weights, then run eval with no outbound network.

The proof is a Compose network marked internal. Database and RabbitMQ stay
reachable. HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE are not set and are not
the proof.

Positive path: cache_pinned_model(), cache_corpus(), and cache_rag_decoder,
then the golden-path suite and the PostgreSQL eval on that network.

From the eval container, curl https://huggingface.co must fail.

Negative path: the same eval command with an empty cache must fail, and the
cache directories must still contain no files.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.isolated-eval.yaml"
PROJECT = "modelanvil-isolated-eval"
CURL_URL = "https://huggingface.co"
GOLDEN_PATH_COMMAND = ["python", "manage.py", "test", "--noinput", "--exclude-tag=pg", "-v", "1"]
EVAL_COMMAND = ["python", "manage.py", "test", "--noinput", "--tag=pg", "-v", "1"]
COPY_SKIP = {".git", ".venv", ".venv-gpu", "node_modules", "__pycache__", ".pytest_cache", ".screenshots"}


def _ignore_source(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in COPY_SKIP}


def copy_source(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(ROOT, destination, ignore=_ignore_source, symlinks=False)


def prefetch(cache: Path) -> None:
    """Explicit online prefetch. This is the only step allowed to use the network."""
    huggingface = cache / "huggingface"
    corpus = cache / "retrieval"
    decoder = cache / "decoder"
    for path in (huggingface, huggingface / "hub", corpus, decoder):
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o777)
    env = os.environ.copy()
    env.update(
        HF_HOME=str(huggingface),
        HUGGINGFACE_HUB_CACHE=str(huggingface / "hub"),
        MODELANVIL_BENCHMARK_CACHE=str(corpus),
        MODELANVIL_RAG_DECODER_CACHE=str(decoder),
        DJANGO_SETTINGS_MODULE="modelanvil.settings",
        PYTHONPATH=str(ROOT),
        HF_HUB_DISABLE_TELEMETRY="1",
    )
    env.pop("HF_HUB_OFFLINE", None)
    env.pop("TRANSFORMERS_OFFLINE", None)
    code = "\n".join(
        [
            "from modelanvil.rag.embedding_model import cache_pinned_model",
            "from modelanvil.rag.benchmark_corpus import cache_corpus",
            "print('cache_pinned_model', cache_pinned_model())",
            "print('cache_corpus', cache_corpus())",
        ]
    )
    print("isolated-eval: prefetch cache_pinned_model and cache_corpus", flush=True)
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True)
    print("isolated-eval: prefetch cache_rag_decoder", flush=True)
    subprocess.run([sys.executable, str(ROOT / "manage.py"), "cache_rag_decoder"], cwd=ROOT, env=env, check=True)


def compose_env(source: Path, cache: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        COMPOSE_PROJECT_NAME=PROJECT,
        COMPOSE_ANSI="never",
        DOCKER_BUILDKIT="1",
        ISOLATED_SOURCE=str(source),
        ISOLATED_HF_HOME=str(cache / "huggingface"),
        ISOLATED_CORPUS=str(cache / "retrieval"),
        ISOLATED_DECODER=str(cache / "decoder"),
    )
    return env


def compose_command(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", PROJECT, *args]


def run_streaming(command: list[str], env: dict[str, str]) -> tuple[int, str]:
    print("isolated-eval:", " ".join(command), flush=True)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    chunks: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        chunks.append(line)
    return process.wait(), "".join(chunks)


def regular_files(root: Path) -> list[tuple[str, int]]:
    if not root.exists():
        return []
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found.append((str(path.relative_to(root)), path.stat().st_size))
    return found


def cache_files(cache: Path) -> list[tuple[str, int]]:
    rows = []
    for name in ("huggingface", "retrieval", "decoder"):
        for relative, size in regular_files(cache / name):
            rows.append((f"{name}/{relative}", size))
    return rows


def assert_no_runtime_skips(text: str, label: str) -> None:
    if "skipped=" in text or "expected failures=" in text:
        raise SystemExit(f"{label} reported a runtime skip or expected failure")


def run_suite(env: dict[str, str], command: list[str], *, label: str, overrides: list[str] | None = None) -> int:
    args = ["run", "--rm", *(overrides or []), "eval", *command]
    code, output = run_streaming(compose_command(*args), env)
    print(f"isolated-eval: {label} exit {code}", flush=True)
    assert_no_runtime_skips(output, label)
    return code


def curl_from_eval(env: dict[str, str], extra: list[str] | None = None) -> int:
    args = [
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "curl",
        "eval",
        "--fail",
        "--silent",
        "--show-error",
        "--max-time",
        "20",
        *(extra or []),
        CURL_URL,
    ]
    code, output = run_streaming(compose_command(*args), env)
    print(f"isolated-eval: curl {CURL_URL} {' '.join(extra or [])} exit {code}".rstrip(), flush=True)
    print(output, end="" if output.endswith("\n") or not output else "\n", flush=True)
    return code


def huggingface_address() -> str | None:
    try:
        return socket.getaddrinfo(CURL_URL.removeprefix("https://"), 443, type=socket.SOCK_STREAM)[0][4][0]
    except OSError as exc:
        print(f"isolated-eval: host could not resolve huggingface.co ({exc})", flush=True)
        return None


def prepare_cache(cache: Path) -> None:
    for name in ("huggingface", "retrieval", "decoder"):
        path = cache / name
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o777)


def compose_down(env: dict[str, str]) -> None:
    subprocess.run(compose_command("down", "-v", "--remove-orphans"), cwd=ROOT, env=env, check=False)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="modelanvil-isolated-eval-"))
    source = work / "source"
    filled = work / "cache"
    empty = work / "empty"
    env = compose_env(source, filled)
    try:
        print("isolated-eval: copy source", flush=True)
        copy_source(source)
        prepare_cache(filled)
        prepare_cache(empty)
        prefetch(filled)
        build_code, _output = run_streaming(compose_command("build", "eval"), env)
        if build_code != 0:
            return build_code
        up_code, _output = run_streaming(compose_command("up", "-d", "--wait", "db", "rabbitmq"), env)
        if up_code != 0:
            return up_code

        plain = curl_from_eval(env)
        if plain == 0:
            print("isolated-eval: curl reached huggingface.co; the eval network has egress", flush=True)
            return 1
        address = huggingface_address()
        if address:
            resolved = curl_from_eval(env, ["--resolve", f"huggingface.co:443:{address}"])
            if resolved == 0:
                print("isolated-eval: curl reached huggingface.co by address; the eval network has egress", flush=True)
                return 1

        golden = run_suite(
            env,
            GOLDEN_PATH_COMMAND,
            label="golden-path",
            overrides=[
                "-e",
                "DATABASE_ENGINE=sqlite",
                "-e",
                "DATABASE_NAME=/tmp/modelanvil-golden.sqlite3",
                "-e",
                "DATABASE_TEST_NAME=/tmp/modelanvil-golden-test.sqlite3",
            ],
        )
        if golden != 0:
            print("isolated-eval: golden path failed on the internal network", flush=True)
            return golden or 1

        eval_code = run_suite(env, EVAL_COMMAND, label="eval")
        if eval_code != 0:
            print("isolated-eval: eval failed on the internal network after prefetch", flush=True)
            return eval_code or 1

        empty_env = compose_env(source, empty)
        before = cache_files(empty)
        negative = run_suite(empty_env, EVAL_COMMAND, label="negative-eval")
        after = cache_files(empty)
        print(f"isolated-eval: negative-eval exit {negative}", flush=True)
        print(f"isolated-eval: empty-cache files before {before}", flush=True)
        print(f"isolated-eval: empty-cache files after {after}", flush=True)
        if negative == 0:
            print("isolated-eval: empty-cache eval exited 0", flush=True)
            return 1
        if before or after:
            print("isolated-eval: empty-cache eval wrote files", flush=True)
            return 1
        print("isolated-eval: ok", flush=True)
        return 0
    finally:
        compose_down(env)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
