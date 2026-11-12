"""Payloads passed through execute_claim stay data.

Executors are installed by operators. A payload that contains shell
metacharacters or a Python snippet is handed to the stub unchanged.
execute_claim does not invoke subprocess, os.system, eval, or exec on that
payload. A shell spawned by execute_claim fails the test. A shell spawned
by the stub does not.
"""
import importlib
import os
import subprocess
import tempfile
import traceback
import uuid
from pathlib import Path

from django.test import TestCase

from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job

_TOKEN = "ANVIL075PAYLOAD"
_SHELLS = {"sh", "bash", "dash", "zsh", "ksh", "ash", "busybox", "cmd", "powershell", "pwsh"}
_SUBPROCESS_CALLS = (
    "run",
    "call",
    "check_call",
    "check_output",
    "Popen",
    "getoutput",
    "getstatusoutput",
)
_OS_CALLS = (
    "system",
    "popen",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "posix_spawn",
    "posix_spawnp",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
)


def _result_envelope():
    return {
        "schema_version": "1.0",
        "sample_id": str(uuid.uuid4()),
        "source_group_id": "executor-payload-fixture",
        "blocks": [{"block_id": "b1", "type": "text", "text": "data"}],
        "provenance": {
            "source_snapshot_ref": "fixture-snapshot",
            "source_record_key": "fixture-record",
            "content_sha256": "0" * 64,
        },
    }


def _payload(marker: Path) -> dict:
    """Shell metacharacters and a Python snippet that would create `marker`."""
    shell = f"touch {marker} # {_TOKEN}; echo anvil | cat > /dev/null"
    python = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran')  # {_TOKEN}\n"
    )
    return {
        "shell": shell,
        "python": python,
        "metacharacters": f";|&$`<>(){{}}[]!#'\"\\ \n {_TOKEN}",
    }


def _program_name(value) -> str:
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str) or not value:
        return ""
    return os.path.basename(value)


def _spawns_shell(kind: str, args, kwargs) -> bool:
    if kind in {"os.system", "os.popen"}:
        return True
    if kwargs.get("shell") is True:
        return True
    candidates = list(args)
    for key in ("args", "executable", "file"):
        if key in kwargs:
            candidates.append(kwargs[key])
    for item in candidates:
        if _program_name(item) in _SHELLS:
            return True
    return False


def _preview(args, kwargs) -> str:
    text = repr((args, kwargs))
    if len(text) > 400:
        return text[:400] + "..."
    return text


class _ExecuteClaimGuard:
    """Record subprocess, os.system, eval, and exec calls made by execute_claim."""

    def __init__(self, needles):
        self.needles = tuple(needles)
        self.violations = []
        self.stub_shells = 0
        self._patched = []

    def __enter__(self):
        import builtins

        targets = [(subprocess, name, f"subprocess.{name}") for name in _SUBPROCESS_CALLS]
        targets.extend((os, name, f"os.{name}") for name in _OS_CALLS if hasattr(os, name))
        targets.append((builtins, "eval", "eval"))
        targets.append((builtins, "exec", "exec"))
        try:
            for owner, name, kind in targets:
                original = getattr(owner, name)
                setattr(owner, name, self._wrap(kind, original))
                self._patched.append((owner, name, original))
            importlib.reload(importlib.import_module("modelanvil.jobs.executor"))
        except Exception:
            self._restore()
            raise
        return self

    def _restore(self):
        for owner, name, original in reversed(self._patched):
            setattr(owner, name, original)
        self._patched.clear()

    def __exit__(self, exc_type, exc, tb):
        self._restore()
        importlib.reload(importlib.import_module("modelanvil.jobs.executor"))
        return False

    def _wrap(self, kind, original):
        def wrapped(*args, **kwargs):
            self._observe(kind, args, kwargs)
            return original(*args, **kwargs)

        return wrapped

    def _on_payload(self, args, kwargs) -> bool:
        blob = repr((args, kwargs))
        return any(needle and needle in blob for needle in self.needles)

    def _from_stub(self, stack) -> bool:
        return any(frame.name == "stub_executor" for frame in stack)

    def _from_execute_claim(self, stack) -> bool:
        return any(
            frame.name == "execute_claim" and frame.filename.endswith("executor.py")
            for frame in stack
        )

    def _observe(self, kind, args, kwargs):
        stack = traceback.extract_stack()
        if self._from_stub(stack):
            if _spawns_shell(kind, args, kwargs):
                self.stub_shells += 1
            return
        if not self._from_execute_claim(stack):
            return
        if self._on_payload(args, kwargs) or _spawns_shell(kind, args, kwargs):
            self.violations.append({"kind": kind, "call": _preview(args, kwargs)})


class ExecutorPayloadDataTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="executor-payload", name="Executor Payload")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="cpu")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="executor-payload-worker",
            slots=1,
            capabilities={"accelerator": "cpu"},
        )

    def _job(self, payload):
        return Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="payload data task",
            payload=payload,
            requirements={"accelerator": "cpu"},
        )

    def _execute(self, payload, stub, marker):
        job = self._job(payload)
        descriptor = claim_job(self.worker, job)
        self.assertIsNotNone(descriptor)
        self.assertFalse(marker.exists(), "claim delivered the payload to a shell")
        module = importlib.import_module("modelanvil.jobs.executor")
        execute_claim = getattr(module, "execute_claim", None)
        self.assertTrue(callable(execute_claim), "claimed execution entry point is missing")
        needles = (_TOKEN, str(marker))
        with _ExecuteClaimGuard(needles) as guard:
            execute_claim = importlib.import_module("modelanvil.jobs.executor").execute_claim
            outcome = execute_claim(self.worker, descriptor, stub)
        return job, outcome, guard

    def test_shell_and_python_payload_is_delivered_as_data(self):
        with tempfile.TemporaryDirectory(prefix="anvil-075-") as directory:
            marker = Path(directory) / "payload-was-executed"
            payload = _payload(marker)
            self.assertNotIn(" ", str(marker))
            exec(payload["python"])  # fixture proof: the snippet is runnable Python
            self.assertEqual(marker.read_text(), "ran")
            marker.unlink()
            self.assertEqual(os.system(payload["shell"]), 0)
            self.assertTrue(marker.is_file())
            marker.unlink()
            observed = {}

            def stub_executor(descriptor, context):
                observed["payload"] = descriptor["payload"]
                observed["heartbeat"] = context.heartbeat(progress=0.5)
                return _result_envelope()

            job, outcome, guard = self._execute(payload, stub_executor, marker)

            self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "succeeded"})
            self.assertEqual(observed["payload"], payload)
            self.assertIsInstance(observed["payload"], dict)
            self.assertTrue(observed["heartbeat"])
            self.assertFalse(marker.exists())
            self.assertEqual(guard.violations, [])
            self.assertEqual(guard.stub_shells, 0)
            job.refresh_from_db()
            self.worker.refresh_from_db()
            attempt = JobAttempt.objects.get(job=job)
            self.assertEqual(job.status, Job.Status.SUCCEEDED)
            self.assertEqual(job.payload, payload)
            self.assertEqual(self.worker.slots, 1)
            self.assertEqual(attempt.status, JobAttempt.Status.SUCCEEDED)
            self.assertEqual(attempt.result_envelope["blocks"][0]["text"], "data")

    def test_stub_shell_is_not_charged_to_execute_claim(self):
        with tempfile.TemporaryDirectory(prefix="anvil-075-") as directory:
            marker = Path(directory) / "payload-was-executed"
            payload = _payload(marker)
            observed = {}

            def stub_executor(descriptor, context):
                observed["payload"] = descriptor["payload"]
                os.system(":")
                return _result_envelope()

            job, outcome, guard = self._execute(payload, stub_executor, marker)

            self.assertEqual(outcome, {"claimed": True, "committed": True, "status": "succeeded"})
            self.assertEqual(observed["payload"], payload)
            self.assertFalse(marker.exists())
            self.assertEqual(guard.violations, [])
            self.assertGreaterEqual(guard.stub_shells, 1)
            job.refresh_from_db()
            self.assertEqual(job.payload, payload)
            self.assertEqual(job.status, Job.Status.SUCCEEDED)
