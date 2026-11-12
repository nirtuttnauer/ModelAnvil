"""Contract tests for the structured API error envelope."""

from __future__ import annotations

import json
import unittest
from typing import Any

from contracts.errors import ApiError, ErrorCode, error_from_exception


def _registered_codes() -> tuple[str, ...]:
    return tuple(
        value
        for name, value in vars(ErrorCode).items()
        if name.isupper() and isinstance(value, str)
    )


def _contains_exception(value: Any) -> bool:
    if isinstance(value, BaseException):
        return True
    if isinstance(value, dict):
        return any(_contains_exception(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_exception(item) for item in value)
    return False


class ApiErrorEnvelopeTests(unittest.TestCase):
    def test_every_registered_code_is_accepted(self) -> None:
        codes = _registered_codes()
        self.assertTrue(codes)
        self.assertEqual(codes, ErrorCode.ALL)
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            error = ApiError(
                code=code,
                message="human readable summary",
                details=[{"path": "field", "message": "bad"}],
            )
            self.assertEqual(error.code, code)
            body = error.to_dict()["error"]
            self.assertEqual(body["code"], code)
            self.assertEqual(body["message"], "human readable summary")
            self.assertEqual(body["details"], [{"path": "field", "message": "bad"}])
            self.assertFalse(_contains_exception(body))

    def test_unregistered_code_raises_value_error(self) -> None:
        for code in ("", "not_a_code", "VALIDATION_FAILED", "internal"):
            with self.subTest(code=code):
                with self.assertRaisesRegex(ValueError, "unregistered"):
                    ApiError(code=code, message="rejected")

    def test_to_dict_uses_documented_fields_without_secrets(self) -> None:
        password = "pw-sample"
        token = "tok-sample"
        error = ApiError(
            code=ErrorCode.VALIDATION_FAILED,
            message="human readable summary",
            status_code=422,
            details=[{"path": "name", "message": "required"}],
            request_id="req-055",
        )
        payload = error.to_dict()
        self.assertEqual(set(payload), {"error"})
        body = payload["error"]
        self.assertEqual(set(body), {"code", "message", "details", "request_id"})
        self.assertEqual(body["code"], ErrorCode.VALIDATION_FAILED)
        self.assertEqual(body["message"], "human readable summary")
        self.assertEqual(body["details"], [{"path": "name", "message": "required"}])
        self.assertEqual(body["request_id"], "req-055")
        self.assertNotIn("status_code", body)
        self.assertNotIn("exception", body)
        rendered = json.dumps(payload)
        self.assertNotIn(password, rendered)
        self.assertNotIn(token, rendered)
        self.assertFalse(_contains_exception(payload))

        bare = ApiError(code=ErrorCode.INTERNAL, message="Internal server error", status_code=500)
        bare_body = bare.to_dict()["error"]
        self.assertEqual(set(bare_body), {"code", "message"})

        leaked = RuntimeError(f"password={password} token={token}")
        setattr(leaked, "password", password)
        setattr(leaked, "token", token)
        hidden = error_from_exception(leaked).to_dict()
        hidden_text = json.dumps(hidden)
        self.assertEqual(hidden["error"]["code"], ErrorCode.INTERNAL)
        self.assertNotIn(password, hidden_text)
        self.assertNotIn(token, hidden_text)
        self.assertNotIn("password", hidden_text)
        self.assertNotIn("token", hidden_text)
        self.assertNotIn("RuntimeError", hidden_text)
        self.assertFalse(_contains_exception(hidden))

    def test_error_from_exception_maps_api_error_to_its_stable_code(self) -> None:
        for code in ErrorCode.ALL:
            original = ApiError(
                code=code,
                message="stable",
                status_code=409,
                details=[{"path": "(root)", "message": "conflict"}],
                request_id="req-map",
            )
            mapped = error_from_exception(original)
            self.assertIs(mapped, original)
            self.assertEqual(mapped.code, code)
            self.assertIn(mapped.code, ErrorCode.ALL)
            body = mapped.to_dict()["error"]
            self.assertEqual(body["code"], code)
            self.assertEqual(body["message"], "stable")
            self.assertEqual(body["details"], [{"path": "(root)", "message": "conflict"}])
            self.assertFalse(_contains_exception(body))

    def test_unknown_exception_maps_to_internal_error(self) -> None:
        mapped = error_from_exception(KeyError("missing-key"))
        self.assertIsInstance(mapped, ApiError)
        self.assertEqual(mapped.code, ErrorCode.INTERNAL)
        self.assertEqual(mapped.status_code, 500)
        self.assertEqual(mapped.message, "Internal server error")
        body = mapped.to_dict()["error"]
        self.assertEqual(body["code"], ErrorCode.INTERNAL)
        self.assertEqual(body["message"], "Internal server error")
        self.assertNotIn("missing-key", json.dumps(body))
        self.assertFalse(_contains_exception(body))
