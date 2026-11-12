"""Map CLI client HTTP failures without copying credentials into errors.

A fake transport or a patched urllib opener stands in for the network.
4xx and 5xx responses become ModelAnvilClientError. An Authorization bearer
and a token query value stay out of the exception text and client log lines.
"""

from __future__ import annotations

import io
import json
import logging
import os
import traceback
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase

from modelanvil.cli.client import ModelAnvilClient, ModelAnvilClientError


def _bearer() -> str:
    return "anvil" + "071" + "bearer"


def _query_secret() -> str:
    return "anvil" + "071" + "/q"


class _Response:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class _Transport:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return _Response(self.status_code, self.content)

    post = put = patch = delete = get


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


class ClientHttpErrorTests(SimpleTestCase):
    def _rendered(self, error: BaseException, logs: list[str]) -> str:
        parts = [
            str(error),
            repr(error),
            "" if not getattr(error, "args", None) else str(error.args[0]),
            json.dumps(getattr(error, "payload", None), default=str),
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
            "\n".join(logs),
        ]
        cause = getattr(error, "__cause__", None)
        context = getattr(error, "__context__", None)
        for linked in (cause, context):
            if linked is None:
                continue
            parts.append(str(linked))
            parts.append(repr(linked))
            filename = getattr(linked, "filename", None)
            if filename is not None:
                parts.append(str(filename))
        return "\n".join(parts)

    def _assert_hidden(self, error: BaseException, secret: str, logs: list[str]) -> None:
        if secret and secret in self._rendered(error, logs):
            self.fail("client error exposed a raw credential")

    def _client(self, transport, token: str) -> ModelAnvilClient:
        return ModelAnvilClient(
            base_url="http://127.0.0.1:9",
            token=token,
            timeout=0.2,
            transport=transport,
        )

    def test_transport_4xx_and_5xx_become_client_errors(self):
        bearer = _bearer()
        cases = (
            (400, b'{"error":"bad request"}'),
            (401, b'{"error":"unauthorized"}'),
            (403, b'{"error":"forbidden"}'),
            (404, b'{"error":"missing"}'),
            (422, b'{"error":"invalid"}'),
            (500, b'{"error":"unavailable"}'),
            (502, b"bad gateway"),
            (503, b'{"error":"down"}'),
        )
        for status, body in cases:
            with self.subTest(status=status):
                transport = _Transport(status, body)
                client = self._client(transport, bearer)
                with self.assertLogs("modelanvil.cli.client", level="DEBUG") as captured:
                    with self.assertRaises(ModelAnvilClientError) as ctx:
                        client.request("GET", "/api/v1/datasets/")
                error = ctx.exception
                self.assertEqual(error.status_code, status)
                self.assertTrue(str(error).startswith(f"HTTP {status}:"))
                authorization = transport.calls[0][1].get("HTTP_AUTHORIZATION", "")
                if authorization != "Bearer " + bearer:
                    self.fail("request did not send the bearer token")
                self._assert_hidden(error, bearer, captured.output)

    def test_echoed_bearer_and_token_query_stay_out_of_the_error(self):
        bearer = _bearer()
        query_secret = _query_secret()
        path = "/api/v1/datasets/?token=" + query_secret
        encoded = "anvil" + "071" + "%2F" + "q"
        body = json.dumps(
            {
                "detail": "rejected " + bearer,
                "authorization": "Bearer " + bearer,
                "request": "http://127.0.0.1:9" + path,
                "encoded": encoded,
            }
        ).encode("utf-8")
        transport = _Transport(401, body)
        client = self._client(transport, bearer)
        with self.assertLogs("modelanvil.cli.client", level="DEBUG") as captured:
            with self.assertRaises(ModelAnvilClientError) as ctx:
                client.request("POST", path, data={"name": "sample"})
        error = ctx.exception
        self.assertEqual(error.status_code, 401)
        self.assertTrue(str(error).startswith("HTTP 401:"))
        self.assertIn("[redacted]", str(error))
        self._assert_hidden(error, bearer, captured.output)
        self._assert_hidden(error, query_secret, captured.output)
        self._assert_hidden(error, encoded, captured.output)

    def test_token_query_without_bearer_stays_out_of_the_error(self):
        query_secret = _query_secret()
        path = "/api/v1/datasets/?other=1&token=" + query_secret
        transport = _Transport(404, json.dumps({"url": path}).encode("utf-8"))
        with patch.dict(os.environ, {"MODELANVIL_TOKEN": ""}, clear=False):
            client = self._client(transport, "")
        with self.assertLogs("modelanvil.cli.client", level="DEBUG") as captured:
            with self.assertRaises(ModelAnvilClientError) as ctx:
                client.request("GET", path)
        error = ctx.exception
        self.assertEqual(error.status_code, 404)
        self.assertTrue(str(error).startswith("HTTP 404:"))
        authorization = transport.calls[0][1].get("HTTP_AUTHORIZATION")
        self.assertIsNone(authorization)
        self._assert_hidden(error, query_secret, captured.output)

    def test_urllib_http_errors_redact_bearer_and_token_query(self):
        bearer = _bearer()
        query_secret = _query_secret()
        path = "/api/v1/datasets/?token=" + query_secret
        for status in (401, 500):
            with self.subTest(status=status):
                body = json.dumps(
                    {
                        "detail": bearer,
                        "request": "http://127.0.0.1:9" + path,
                    }
                ).encode("utf-8")

                def fake_urlopen(req, timeout=None, body=body, bearer=bearer, status=status):
                    authorization = req.get_header("Authorization")
                    if authorization != "Bearer " + bearer:
                        raise AssertionError("request did not send the bearer token")
                    raise urllib.error.HTTPError(
                        req.full_url,
                        status,
                        "error",
                        hdrs={},
                        fp=io.BytesIO(body),
                    )

                client = ModelAnvilClient(
                    base_url="http://127.0.0.1:9",
                    token=bearer,
                    timeout=0.2,
                )
                with patch("urllib.request.urlopen", fake_urlopen):
                    with self.assertLogs("modelanvil.cli.client", level="DEBUG") as captured:
                        with self.assertRaises(ModelAnvilClientError) as ctx:
                            client.request("GET", path)
                error = ctx.exception
                self.assertEqual(error.status_code, status)
                self.assertTrue(str(error).startswith(f"HTTP {status}:"))
                self.assertIsNone(error.__cause__)
                self.assertIsNone(error.__context__)
                self._assert_hidden(error, bearer, captured.output)
                self._assert_hidden(error, query_secret, captured.output)

    def test_urllib_network_error_redacts_bearer_and_token_query(self):
        bearer = _bearer()
        query_secret = _query_secret()
        path = "/api/v1/datasets/?token=" + query_secret

        def fake_urlopen(req, timeout=None):
            reason = "failed " + req.full_url + " Authorization " + (req.get_header("Authorization") or "")
            raise urllib.error.URLError(reason)

        client = ModelAnvilClient(
            base_url="http://127.0.0.1:9",
            token=bearer,
            timeout=0.2,
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            with self.assertLogs("modelanvil.cli.client", level="DEBUG") as captured:
                with self.assertRaises(ModelAnvilClientError) as ctx:
                    client.request("GET", path)
        error = ctx.exception
        self.assertIsNone(error.status_code)
        self.assertTrue(str(error).startswith("Network error:"))
        self.assertIn("[redacted]", str(error))
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self._assert_hidden(error, bearer, captured.output)
        self._assert_hidden(error, query_secret, captured.output)

    def test_success_response_does_not_log_the_bearer(self):
        bearer = _bearer()
        transport = _Transport(200, b'{"ok": true}')
        client = self._client(transport, bearer)
        logger = logging.getLogger("modelanvil.cli.client")
        handler = _Capture()
        previous = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            result = client.request("GET", "/api/v1/datasets/")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)
        self.assertEqual(result, {"ok": True})
        if bearer in "\n".join(handler.lines):
            self.fail("client log exposed a raw credential")
