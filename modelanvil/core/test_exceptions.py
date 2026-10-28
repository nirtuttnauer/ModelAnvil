"""Validation messages remain readable at the browser/API boundary."""
import json
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from modelanvil.core.exceptions import api_exception_handler


class ValidationMessageTests(SimpleTestCase):
    def test_workflow_refusal_preserves_plain_message(self):
        message = 'Select an active pool with a matching recipe worker.'
        response = api_exception_handler(ValidationError(message))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['error']['details'],
                         [{'path': '(root)', 'message': message}])

    def test_multiple_refusals_and_named_fields_keep_their_messages(self):
        for detail, expected in [
            (['Choose a worker.', 'Review the preview.'],
             [{'path': '(root)', 'message': 'Choose a worker.; Review the preview.'}]),
            ({'pool': ['Choose a worker.']}, [{'path': 'pool', 'message': 'Choose a worker.'}]),
        ]:
            response = api_exception_handler(ValidationError(detail))
            self.assertEqual(json.loads(response.content)['error']['details'], expected)
