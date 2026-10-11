"""Outbound HTTP worker. No Django, database or broker initialization."""
from __future__ import annotations

import json
import ipaddress
import argparse
import importlib
import hashlib
import math
import os
import re
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener


class WorkerProtocolError(RuntimeError):
    """Sanitized transport/protocol failure; never includes server bodies or tokens."""


def _canonical_uuid(value):
    return isinstance(value, str) and re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value,
    ) is not None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RemoteExecutionContext:
    def __init__(self, agent, descriptor):
        self.agent = agent
        self.descriptor = descriptor
        self.lease_lost = False
        self.cancel_requested = False
        self._lock = threading.Lock()
        self.result_egress = descriptor.get("result_egress", "envelope")
        if self.result_egress not in {"envelope", "metadata_only"}:
            raise WorkerProtocolError("Unknown result-egress policy.")
        if agent.result_egress == "metadata_only":
            self.result_egress = "metadata_only"

    def identity(self):
        return {"worker_id": self.agent.worker_id, "attempt_id": self.descriptor["attempt_id"],
                "fencing_token": self.descriptor["fencing_token"]}

    def heartbeat(self, progress=None):
        with self._lock:
            if self.cancel_requested or self.lease_lost:
                return False
            payload = self.identity()
            if progress is not None:
                payload["progress"] = progress
            try:
                response = self.agent._post("heartbeat/", payload)
                if response.get("ok") is not True:
                    raise WorkerProtocolError("Lease renewal was not acknowledged.")
                mode = response.get("result_egress", self.result_egress)
                if mode not in {"envelope", "metadata_only"}:
                    raise WorkerProtocolError("Unknown result-egress policy.")
                if mode == "metadata_only":
                    self.result_egress = mode
                self.descriptor["lease_expires_at"] = response["lease_expires_at"]
                self.cancel_requested = response.get("desired_action") == "cancel"
            except (WorkerProtocolError, KeyError):
                self.lease_lost = True
            return not self.cancel_requested and not self.lease_lost

    def remaining_lease(self):
        try:
            expiry = datetime.fromisoformat(self.descriptor["lease_expires_at"])
            remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                self.lease_lost = True
            return remaining
        except (KeyError, TypeError, ValueError):
            self.lease_lost = True
            return 0

    def download_artifact(self, grant_id, *, sha256, byte_size):
        """Return verified input bytes, never a partial or unverified stream."""
        return self.agent._download_artifact(grant_id, sha256=sha256, byte_size=byte_size, context=self)

    def discover_artifacts(self, *, cursor=None):
        """Fetch one page of existing input authority, never issue or download it."""
        if cursor is not None and not _canonical_uuid(cursor):
            raise WorkerProtocolError("Invalid artifact discovery cursor.")
        if self.cancel_requested or self.lease_lost or self.remaining_lease() <= 0:
            raise WorkerProtocolError("Artifact access is no longer active.")
        payload = self.identity()
        if cursor is not None:
            payload["cursor"] = cursor
        response = self.agent._post("artifact-grants/discover/", payload)
        try:
            if (not isinstance(response, dict) or set(response) != {"attempt_id", "grants", "next_cursor"}
                    or response["attempt_id"] != self.descriptor["attempt_id"]
                    or not isinstance(response["grants"], list) or len(response["grants"]) > 32):
                raise ValueError
            next_cursor = response["next_cursor"]
            if next_cursor is not None and not _canonical_uuid(next_cursor):
                raise ValueError
            previous = cursor or ""
            for reference in response["grants"]:
                if (not isinstance(reference, dict)
                        or set(reference) != {"grant_id", "artifact_id", "sha256", "byte_size", "expires_at"}
                        or not _canonical_uuid(reference["grant_id"])
                        or not _canonical_uuid(reference["artifact_id"])
                        or reference["grant_id"] <= previous
                        or not isinstance(reference["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])
                        or isinstance(reference["byte_size"], bool)
                        or not isinstance(reference["byte_size"], int) or reference["byte_size"] < 0):
                    raise ValueError
                expiry = datetime.fromisoformat(reference["expires_at"])
                if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                    raise ValueError
                previous = reference["grant_id"]
            if next_cursor is not None and (next_cursor < previous or next_cursor <= (cursor or "")):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise WorkerProtocolError("Invalid artifact discovery response.") from None
        if self.cancel_requested or self.lease_lost or self.remaining_lease() <= 0:
            raise WorkerProtocolError("Artifact access is no longer active.")
        return response


class RemoteWorkerAgent:
    def __init__(self, *, endpoint_url, worker_token, worker_id, pool,
                 timeout=10.0, heartbeat_interval=10.0, allow_loopback_http=False,
                 result_egress="envelope", artifact_max_bytes=16 * 1024 * 1024):
        try:
            parsed = urlsplit(endpoint_url)
            parsed.port  # Validate a supplied port without including its value in errors.
            invalid = (
                not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in endpoint_url or "#" in endpoint_url
                or "\\" in endpoint_url or any(ord(c) <= 32 or ord(c) == 127 for c in endpoint_url)
                or parsed.path.rstrip("/") != "/api/v1/workers"
            )
            if parsed.scheme == "http" and allow_loopback_http:
                invalid = invalid or not ipaddress.ip_address(parsed.hostname or "").is_loopback
            elif parsed.scheme != "https":
                invalid = True
            if invalid:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("Worker endpoint must be HTTPS; HTTP is limited to explicit numeric loopback opt-in.") from None
        if not isinstance(worker_token, str) or not re.fullmatch(r"mkw_[A-Za-z0-9_-]{43}", worker_token):
            raise ValueError("A scoped worker credential is required.")
        if isinstance(worker_id, bool) or not isinstance(worker_id, int) or worker_id <= 0:
            raise ValueError("A positive integer worker ID is required.")
        if not isinstance(pool, str) or not pool:
            raise ValueError("A pool name is required.")
        if not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("Request timeout must be finite and between zero and 300 seconds.")
        if not math.isfinite(heartbeat_interval) or heartbeat_interval <= 0:
            raise ValueError("Heartbeat interval must be positive and finite.")
        self.endpoint_url = endpoint_url.rstrip("/") + "/"
        self._worker_token = worker_token
        self.worker_id = worker_id
        self.pool = pool
        self.timeout = timeout
        self.heartbeat_interval = heartbeat_interval
        if result_egress not in {"envelope", "metadata_only"}:
            raise ValueError("Unknown result-egress policy.")
        self.result_egress = result_egress
        if (isinstance(artifact_max_bytes, bool) or not isinstance(artifact_max_bytes, int)
                or not 0 < artifact_max_bytes <= 64 * 1024 * 1024):
            raise ValueError("Artifact byte cap must be an integer from 1 through 64 MiB.")
        self.artifact_max_bytes = artifact_max_bytes
        self._opener = build_opener(ProxyHandler({}), _NoRedirect(),
                                    HTTPSHandler(context=ssl.create_default_context()))

    def _post(self, operation, payload):
        if operation not in {"claim/", "heartbeat/", "result/", "artifact-grants/discover/"}:
            raise WorkerProtocolError("Unknown worker operation.")
        try:
            body = json.dumps(payload, allow_nan=False).encode()
            if len(body) > 1024 * 1024:
                raise WorkerProtocolError("Worker request exceeds the one MiB limit.")
            request = Request(
                self.endpoint_url + operation, method="POST", data=body,
                headers={"Authorization": f"Bearer {self._worker_token}", "Content-Type": "application/json"},
            )
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise WorkerProtocolError("Worker response exceeds the one MiB limit.")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise WorkerProtocolError("Worker response must be a JSON object.")
                return data
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise WorkerProtocolError(f"Worker endpoint returned HTTP {code}.") from None
        except (URLError, OSError, ValueError, TypeError):
            raise WorkerProtocolError("Worker transport or JSON encoding failed.") from None

    def _keep_alive(self, context, stop):
        while not stop.is_set():
            remaining = context.remaining_lease()
            if remaining <= 0:
                context.lease_lost = True
                return
            if stop.wait(min(self.heartbeat_interval, remaining / 3)):
                return
            if not context.heartbeat():
                return

    def _download_artifact(self, grant_id, *, sha256, byte_size, context):
        if (not _canonical_uuid(grant_id)
                or not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or isinstance(byte_size, bool) or not isinstance(byte_size, int)
                or not 0 <= byte_size <= self.artifact_max_bytes):
            raise WorkerProtocolError("Invalid artifact grant, digest, or bounded size.")

        deadline = time.monotonic() + self.timeout

        def check_access():
            if (context.cancel_requested or context.lease_lost or context.remaining_lease() <= 0
                    or time.monotonic() >= deadline):
                raise WorkerProtocolError("Artifact access is no longer active.")

        check_access()
        request = Request(
            self.endpoint_url + f"artifact-grants/{grant_id}/download/", method="GET",
            headers={"Authorization": f"Bearer {self._worker_token}", "Accept-Encoding": "identity"},
        )
        try:
            with self._opener.open(request, timeout=min(self.timeout, context.remaining_lease())) as response:
                if (response.status != 200 or response.headers.get("Content-Length") != str(byte_size)
                        or len(response.headers.get_all("Content-Length", [])) != 1
                        or len(response.headers.get_all("X-ModelAnvil-Attempt-ID", [])) != 1
                        or len(response.headers.get_all("Content-Encoding", [])) > 1
                        or response.headers.get("X-ModelAnvil-Attempt-ID") != context.descriptor["attempt_id"]
                        or response.headers.get("Content-Encoding", "identity") != "identity"
                        or response.headers.get("Transfer-Encoding") is not None):
                    raise WorkerProtocolError("Artifact response framing is invalid.")
                content = bytearray()
                digest = hashlib.sha256()
                while True:
                    check_access()
                    chunk = response.read1(min(64 * 1024, byte_size + 1 - len(content)))
                    check_access()
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > byte_size:
                        raise WorkerProtocolError("Artifact response exceeds the expected size.")
                    digest.update(chunk)
                if len(content) != byte_size or digest.hexdigest() != sha256:
                    raise WorkerProtocolError("Artifact integrity verification failed.")
                return bytes(content)
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise WorkerProtocolError(f"Worker artifact endpoint returned HTTP {code}.") from None
        except (HTTPException, URLError, OSError, ValueError, TypeError):
            raise WorkerProtocolError("Artifact transport failed.") from None

    def run_once(self, executor):
        descriptor = self._post("claim/", {"worker_id": self.worker_id, "pool": self.pool})
        if descriptor.get("claimed") is False:
            return {"claimed": False}
        if descriptor.get("claimed") is not True or not all(
            descriptor.get(key) for key in ("attempt_id", "fencing_token", "lease_expires_at")
        ):
            raise WorkerProtocolError("Invalid claim descriptor.")
        context = RemoteExecutionContext(self, descriptor)
        stop = threading.Event()
        keep_alive = threading.Thread(target=self._keep_alive, args=(context, stop), daemon=True)
        result, error, status = None, "", "succeeded"
        # Check ownership and cancellation before invoking operator-installed code.
        if context.remaining_lease() > 0 and context.heartbeat():
            keep_alive.start()
            try:
                # Pass a copy so executor code cannot accidentally mutate fencing identity.
                result = executor(dict(descriptor), context)
                if result is not None:
                    from contracts import validate_envelope
                    validate_envelope(result)
            except Exception:
                result, error, status = None, "Remote executor failed or returned an invalid envelope.", "failed"
            finally:
                stop.set()
                keep_alive.join(self.timeout + 1)
                if keep_alive.is_alive():
                    context.lease_lost = True
            # Final renewal catches cancellation/fence changes after the last periodic heartbeat.
            context.heartbeat()
        if context.lease_lost:
            return {"claimed": True, "committed": False, "status": "lease_lost"}
        if context.cancel_requested:
            result, error, status = None, "", "interrupted"
        if context.result_egress == "metadata_only":
            if result is not None:
                status = "failed"
            result, error = None, ""
        payload = {**context.identity(), "status": status}
        if result is not None:
            payload["result_envelope"] = result
        if error:
            payload["error"] = error
        try:
            response = self._post("result/", payload)
        except WorkerProtocolError:
            # A lost response may already have committed: do not rerun or blindly retry it.
            return {"claimed": True, "committed": False, "status": "commit_unconfirmed"}
        return {"claimed": True, "committed": response.get("ok") is True,
                "status": response.get("status", "commit_unconfirmed")}


def load_executor(spec):
    """Only operator-provided installed Python code; never use a job-supplied name."""
    try:
        module_name, attribute = spec.split(":")
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module_name):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z_]\w*", attribute):
            raise ValueError
        executor = getattr(importlib.import_module(module_name), attribute)
        if not callable(executor):
            raise ValueError
        return executor
    except Exception:
        raise ValueError("Executor must name a trusted installed module:callable.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="HTTPS URL ending in /api/v1/workers/")
    parser.add_argument("--worker-id", required=True, type=int)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--executor", required=True, help="Trusted operator-installed module:callable")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--allow-loopback-http", action="store_true", help="Local development only")
    parser.add_argument("--request-timeout", type=float, default=10.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=10.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--artifact-max-bytes", type=int, default=16 * 1024 * 1024,
                        help="Verified input byte cap (1 byte through 64 MiB; default 16 MiB)")
    parser.add_argument("--result-egress", choices=["envelope", "metadata_only"], default="envelope",
                        help="Local result boundary; a stricter pool policy also applies")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.poll_seconds) or args.poll_seconds <= 0:
            raise ValueError("Polling delay must be positive and finite.")
        executor = load_executor(args.executor)
        agent = RemoteWorkerAgent(
            endpoint_url=args.endpoint, worker_token=os.environ.get("MODELANVIL_WORKER_TOKEN", ""),
            worker_id=args.worker_id, pool=args.pool, timeout=args.request_timeout,
            heartbeat_interval=args.heartbeat_seconds, allow_loopback_http=args.allow_loopback_http,
            result_egress=args.result_egress,
            artifact_max_bytes=args.artifact_max_bytes,
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        while True:
            outcome = agent.run_once(executor)
            print(json.dumps(outcome), flush=True)
            if outcome.get("claimed") and not outcome.get("committed"):
                return 2
            if args.once:
                return 0
            time.sleep(args.poll_seconds)
    except WorkerProtocolError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        # Do not claim cancellation/remote-backend termination on process shutdown.
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
