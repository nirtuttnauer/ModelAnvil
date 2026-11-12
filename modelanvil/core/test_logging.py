"""JSON log lines stay attributable and keep secret values out of the line."""

import json
import logging
import sys
import uuid

from django.http import HttpRequest
from django.test import SimpleTestCase

from modelanvil.core.logging import JsonFormatter
from modelanvil.core.tenancy import bind_request, reset_context, set_active_tenant

_PLACEHOLDER = "[redacted]"


def _probe(name):
    return "redact-me-" + name


class JsonLogTests(SimpleTestCase):
    def setUp(self):
        reset_context()
        self.formatter = JsonFormatter()

    def tearDown(self):
        reset_context()

    def _record(self, msg="event", level=logging.INFO, args=(), extra=None, exc_info=None):
        logger = logging.getLogger("modelanvil.test")
        return logger.makeRecord(
            logger.name, level, "logging.py", 1, msg, args, exc_info, extra=extra,
        )

    def _payload(self, record):
        text = self.formatter.format(record)
        return text, json.loads(text)

    def test_formatted_record_is_json_with_a_message(self):
        text, payload = self._payload(self._record())
        json.loads(text)
        self.assertEqual(payload["message"], "Application event")
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "modelanvil.test")
        self.assertIn("timestamp", payload)

    def test_error_record_uses_the_error_message_and_exception_type(self):
        probe = _probe("traceback")
        try:
            raise ValueError(probe)
        except ValueError:
            record = self._record(
                msg=probe + " %s", args=(_probe("arg"),), level=logging.ERROR, exc_info=sys.exc_info(),
            )
        text, payload = self._payload(record)
        self.assertEqual(payload["message"], "Application error")
        self.assertEqual(payload["exception_type"], "ValueError")
        self.assertNotIn(probe, text)
        self.assertNotIn(_probe("arg"), text)

    def test_request_and_tenant_context_are_included(self):
        request_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        request = HttpRequest()
        request.modelanvil_request_id = str(request_id)
        bind_request(request)
        set_active_tenant(tenant_id)
        _, payload = self._payload(self._record())
        self.assertEqual(payload["request_id"], str(request_id))
        self.assertEqual(payload["tenant_id"], str(tenant_id))

    def test_request_id_and_tenant_on_the_record_are_included(self):
        request_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        job_id = 7
        _, payload = self._payload(self._record(extra={
            "request_id": str(request_id),
            "tenant": str(tenant_id),
            "job_id": job_id,
            "status_code": 201,
        }))
        self.assertEqual(payload["request_id"], str(request_id))
        self.assertEqual(payload["tenant"], str(tenant_id))
        self.assertEqual(payload["job_id"], job_id)
        self.assertEqual(payload["http_status"], 201)
        self.assertNotIn("tenant_id", payload)

    def test_non_uuid_request_id_extra_stays_off_the_line(self):
        probe = _probe("request")
        text, payload = self._payload(self._record(extra={"request_id": probe}))
        self.assertNotIn("request_id", payload)
        self.assertNotIn(probe, text)

    def test_secret_keys_in_extras_are_replaced_with_a_placeholder(self):
        probes = {
            "password": _probe("password"),
            "token": _probe("token"),
            "authorization": _probe("authorization"),
            "api_key": _probe("api-key"),
            "API_KEY": _probe("upper-api-key"),
        }
        text, payload = self._payload(self._record(extra=probes))
        for key, probe in probes.items():
            self.assertNotIn(probe, text)
            self.assertEqual(payload[key], _PLACEHOLDER)
        self.assertEqual(payload["message"], "Application event")

    def test_secret_keys_in_a_dict_message_are_replaced_with_a_placeholder(self):
        probes = {
            "password": _probe("password"),
            "token": _probe("token"),
            "authorization": _probe("authorization"),
            "api_key": _probe("api-key"),
        }
        message = {"event": "sign-in", "headers": {"Authorization": _probe("header"), "accept": "application/json"}}
        message.update(probes)
        message["items"] = [{"api-key": _probe("nested-api-key"), "name": "worker"}]
        text, payload = self._payload(self._record(msg=message))
        self.assertEqual(payload["message"], "Application event")
        self.assertEqual(payload["event"], "sign-in")
        self.assertEqual(payload["headers"]["accept"], "application/json")
        self.assertEqual(payload["headers"]["Authorization"], _PLACEHOLDER)
        self.assertEqual(payload["items"][0]["api-key"], _PLACEHOLDER)
        self.assertEqual(payload["items"][0]["name"], "worker")
        for key, probe in probes.items():
            self.assertNotIn(probe, text)
            self.assertEqual(payload[key], _PLACEHOLDER)
        self.assertNotIn(_probe("header"), text)
        self.assertNotIn(_probe("nested-api-key"), text)

    def test_nested_secret_in_an_extra_is_replaced_and_plain_extras_stay_off(self):
        probe = _probe("nested-password")
        note = _probe("plain-note")
        text, payload = self._payload(self._record(extra={
            "context": {"password": probe, "job": "train"},
            "note": note,
        }))
        self.assertEqual(payload["context"]["password"], _PLACEHOLDER)
        self.assertEqual(payload["context"]["job"], "train")
        self.assertNotIn(probe, text)
        self.assertNotIn("note", payload)
        self.assertNotIn(note, text)

    def test_dict_message_does_not_replace_request_or_tenant_fields(self):
        request_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        request = HttpRequest()
        request.modelanvil_request_id = str(request_id)
        bind_request(request)
        set_active_tenant(tenant_id)
        _, payload = self._payload(self._record(msg={
            "request_id": _probe("override-request"),
            "tenant": _probe("override-tenant"),
            "tenant_id": _probe("override-tenant-id"),
            "message": _probe("override-message"),
            "password": _probe("password"),
        }))
        self.assertEqual(payload["request_id"], str(request_id))
        self.assertEqual(payload["tenant_id"], str(tenant_id))
        self.assertEqual(payload["message"], "Application event")
        self.assertNotIn("tenant", payload)
        self.assertEqual(payload["password"], _PLACEHOLDER)
        rendered = json.dumps(payload)
        self.assertNotIn(_probe("override-request"), rendered)
        self.assertNotIn(_probe("override-tenant"), rendered)
        self.assertNotIn(_probe("override-message"), rendered)
        self.assertNotIn(_probe("password"), rendered)
