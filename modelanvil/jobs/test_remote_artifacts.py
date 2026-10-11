"""Standalone input-client refusal and framing checks over real HTTP."""
import hashlib
import io
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import SimpleTestCase

from modelanvil.worker_agent import RemoteExecutionContext, RemoteWorkerAgent, WorkerProtocolError


GRANT_ID = "e337b0e3-8c10-45f9-b69c-08b69c4bcacf"
ATTEMPT_ID = "923c9517-7b96-4cb4-8ed1-36d5cd013ad9"


class RemoteArtifactSecurityTests(SimpleTestCase):
    def context(self, endpoint="https://worker.example/api/v1/workers/", **kwargs):
        agent = RemoteWorkerAgent(
            endpoint_url=endpoint, worker_token="mkw_" + "a" * 43, worker_id=1, pool="cpu", **kwargs,
        )
        return RemoteExecutionContext(agent, {
            "attempt_id": ATTEMPT_ID, "fencing_token": "fixture",
            "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
        })

    @contextmanager
    def server(self, *, body=b"input bytes", headers=None, status=200):
        requests = []
        response_headers = {"Content-Length": str(len(body)), "X-ModelAnvil-Attempt-ID": ATTEMPT_ID}
        response_headers.update(headers or {})

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization") == "Bearer mkw_" + "a" * 43))
                self.send_response(status)
                for name, value in response_headers.items():
                    if value is not None:
                        for item in value if isinstance(value, list) else [value]:
                            self.send_header(name, item)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield self.context(f"http://127.0.0.1:{server.server_port}/api/v1/workers/",
                               allow_loopback_http=True), requests
        finally:
            server.shutdown()
            thread.join(2)
            server.server_close()

    def download(self, context, body=b"input bytes"):
        return context.download_artifact(GRANT_ID, sha256=hashlib.sha256(body).hexdigest(), byte_size=len(body))

    def discovery_page(self):
        return {"attempt_id": ATTEMPT_ID, "next_cursor": None, "grants": [{
            "grant_id": GRANT_ID, "artifact_id": ATTEMPT_ID,
            "sha256": hashlib.sha256(b"input bytes").hexdigest(), "byte_size": 11,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        }]}

    def test_discovery_refuses_wrong_attempt_or_malformed_reference_metadata(self):
        context = self.context()
        valid = self.discovery_page()
        bad_references = [
            {"grant_id": GRANT_ID.upper()}, {"artifact_id": "not-a-uuid"}, {"sha256": "z" * 64},
            {"byte_size": True}, {"byte_size": -1}, {"byte_size": "11"},
            {"expires_at": "not-a-timestamp"}, {"expires_at": "2020-01-01T00:00:00+00:00"},
            {"expires_at": "2999-01-01T00:00:00"}, {"object_key": "private-storage-path"},
        ]
        pages = [{**valid, "attempt_id": GRANT_ID}, {**valid, "grants": "bad"},
                 {**valid, "grants": valid["grants"] * 33}, {**valid, "next_cursor": "../private"},
                 {**valid, "object_key": "private-storage-path"}, {},
                 {**valid, "grants": valid["grants"] * 2}]
        pages += [{**valid, "grants": [{**valid["grants"][0], **changes}]} for changes in bad_references]
        for page in pages:
            with self.subTest(fields=tuple(page)), patch.object(context.agent, "_post", return_value=page):
                with self.assertRaises(WorkerProtocolError) as caught:
                    context.discover_artifacts()
                self.assertNotIn("private", str(caught.exception))

    def test_discovery_invalid_cursor_is_rejected_before_http(self):
        context = self.context()
        for cursor in ("../private", GRANT_ID.upper(), True, 1, " " + GRANT_ID):
            with self.subTest(cursor_type=type(cursor).__name__), \
                    patch.object(context.agent, "_post", return_value=self.discovery_page()) as post:
                with self.assertRaises(WorkerProtocolError):
                    context.discover_artifacts(cursor=cursor)
                post.assert_not_called()

    def test_discovery_empty_pages_and_cursor_progress_are_explicit(self):
        context = self.context()
        empty = {"attempt_id": ATTEMPT_ID, "grants": [], "next_cursor": GRANT_ID}
        with patch.object(context.agent, "_post", return_value=empty) as post:
            self.assertEqual(context.discover_artifacts(), empty)
            post.assert_called_once()
        with patch.object(context.agent, "_post", return_value={**empty, "next_cursor": None}) as post:
            self.assertEqual(context.discover_artifacts(cursor=GRANT_ID)["grants"], [])
            post.assert_called_once()
            self.assertEqual(post.call_args.args[1]["cursor"], GRANT_ID)
        for next_cursor in (GRANT_ID, ATTEMPT_ID):
            with patch.object(context.agent, "_post", return_value={**empty, "next_cursor": next_cursor}):
                with self.assertRaises(WorkerProtocolError):
                    context.discover_artifacts(cursor=GRANT_ID)

    def test_discovery_rechecks_cancellation_after_http(self):
        context = self.context()

        def post(_operation, _payload):
            context.cancel_requested = True
            return self.discovery_page()

        with patch.object(context.agent, "_post", side_effect=post):
            with self.assertRaises(WorkerProtocolError):
                context.discover_artifacts()

    def test_download_uses_only_canonical_same_origin_path(self):
        with self.server() as (context, requests):
            self.assertEqual(self.download(context), b"input bytes")
            self.assertEqual(requests, [(f"/api/v1/workers/artifact-grants/{GRANT_ID}/download/", True)])

    def test_malformed_identity_digest_and_size_refuse_before_http(self):
        context = self.context(artifact_max_bytes=64)
        valid = {"grant_id": GRANT_ID, "sha256": hashlib.sha256(b"input bytes").hexdigest(), "byte_size": 11}
        cases = [
            {"grant_id": "https://private.example/leak"}, {"grant_id": GRANT_ID.upper()},
            {"grant_id": "../result/"}, {"grant_id": GRANT_ID + "?credential=private"},
            {"grant_id": None}, {"sha256": "z" * 64}, {"sha256": "A" * 64},
            {"sha256": None}, {"byte_size": True}, {"byte_size": -1},
            {"byte_size": "11"}, {"byte_size": 1.5}, {"byte_size": 65},
        ]
        with patch.object(context.agent._opener, "open") as transport:
            for invalid in cases:
                with self.subTest(fields=tuple(invalid)):
                    with self.assertRaises(WorkerProtocolError) as caught:
                        context.download_artifact(**{**valid, **invalid})
                    self.assertNotIn("private", str(caught.exception))
            transport.assert_not_called()

    def test_framing_and_attempt_mismatch_refuse_content(self):
        for headers in [
            {"Content-Length": None}, {"Content-Length": "invalid"}, {"Content-Length": "10"},
            {"Content-Length": "12"}, {"Content-Encoding": "gzip"}, {"Transfer-Encoding": "chunked"},
            {"X-ModelAnvil-Attempt-ID": None}, {"X-ModelAnvil-Attempt-ID": GRANT_ID},
        ]:
            with self.subTest(headers=headers), self.server(headers=headers) as (context, _requests):
                with self.assertRaises(WorkerProtocolError):
                    self.download(context)

    def test_truncated_response_is_not_returned(self):
        with self.server(body=b"input", headers={"Content-Length": "11"}) as (context, _requests):
            with self.assertRaises(WorkerProtocolError) as caught:
                self.download(context)
            self.assertNotIn("input", str(caught.exception))

    def test_ambiguous_duplicate_headers_are_refused(self):
        for name, value in (("Content-Length", "11"), ("X-ModelAnvil-Attempt-ID", ATTEMPT_ID),
                            ("Content-Encoding", "identity")):
            with self.subTest(header=name), self.server(headers={name: [value, value]}) as (context, _requests):
                with self.assertRaises(WorkerProtocolError):
                    self.download(context)

    def test_redirect_is_not_followed(self):
        with self.server(status=302, headers={"Location": "/credential-leak"}) as (context, requests):
            with self.assertRaises(WorkerProtocolError) as caught:
                self.download(context)
            self.assertEqual(requests, [(f"/api/v1/workers/artifact-grants/{GRANT_ID}/download/", True)])
            self.assertNotIn("mkw_", str(caught.exception))

    def test_partial_content_status_is_not_accepted_as_complete_input(self):
        with self.server(status=206) as (context, _requests):
            with self.assertRaises(WorkerProtocolError):
                self.download(context)

    def test_http_error_body_and_transport_messages_are_not_exposed(self):
        with self.server(status=403, body=b"private server diagnostic") as (context, _requests):
            with self.assertRaises(WorkerProtocolError) as caught:
                self.download(context)
            self.assertEqual(str(caught.exception), "Worker artifact endpoint returned HTTP 403.")
        context = self.context()
        with patch.object(context.agent._opener, "open", side_effect=OSError("private transport diagnostic")):
            with self.assertRaises(WorkerProtocolError) as caught:
                self.download(context)
            self.assertNotIn("private", str(caught.exception))

    def test_cancelled_lost_or_expired_context_never_downloads(self):
        for state in ("cancel_requested", "lease_lost", "expired"):
            context = self.context()
            if state == "expired":
                context.descriptor["lease_expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            else:
                setattr(context, state, True)
            with self.subTest(state=state), patch.object(context.agent._opener, "open") as transport:
                with self.assertRaises(WorkerProtocolError):
                    self.download(context)
                transport.assert_not_called()

    def test_cancellation_during_read_discards_bytes(self):
        with self.server() as (context, _requests):
            original_open = context.agent._opener.open

            def open_response(request, **kwargs):
                response = original_open(request, **kwargs)
                original_read = response.read1

                def read(size):
                    chunk = original_read(size)
                    context.cancel_requested = True
                    return chunk

                response.read1 = read
                return response

            with patch.object(context.agent._opener, "open", side_effect=open_response):
                with self.assertRaises(WorkerProtocolError):
                    self.download(context)

    def test_elapsed_transfer_deadline_discards_received_bytes(self):
        with self.server() as (context, _requests):
            with patch("modelanvil.worker_agent.time.monotonic", side_effect=[0, 0, 0, 11]):
                with self.assertRaises(WorkerProtocolError):
                    self.download(context)

    def test_reads_are_bounded_and_do_not_return_oversized_body(self):
        context = self.context()
        body = b"x" * (128 * 1024)
        sizes = []

        class Response(io.BytesIO):
            status = 200
            headers = Message()
            headers["Content-Length"] = str(len(body))
            headers["X-ModelAnvil-Attempt-ID"] = ATTEMPT_ID

            def read1(self, size=-1, /):
                sizes.append(size)
                return super().read1(size)

        response = Response(body + b"extra")
        with patch.object(context.agent._opener, "open", return_value=response):
            with self.assertRaises(WorkerProtocolError):
                self.download(context, body)
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), 64 * 1024)
        self.assertTrue(response.closed)
