"""GGUF admission and accounting regressions; native execution is a separate bounded check."""
import os
import tempfile
from unittest import TestCase, skipUnless
from unittest.mock import Mock

from django.test import tag

from modelanvil.runners.gguf_runtime import GGUFSession


class GGUFGuards(TestCase):
    def test_oversize_weights_are_refused_before_optional_runtime_loading(self):
        with tempfile.NamedTemporaryFile() as weights:
            weights.truncate(1024**3 + 1)
            with self.assertRaisesRegex(ValueError, '1 GiB limit'):
                GGUFSession(weights.name)

    def session(self):
        session = GGUFSession.__new__(GGUFSession)
        session.context_limit = 2048
        session.has_chat_template = False
        return session

    def generate(self, session, **kwargs):
        return session.generate([{'role': 'user', 'content': 'A question'}], max_tokens=8,
            temperature=0, seed=42, prompt_format='plain', started=0, **kwargs)

    def test_output_reservation_refuses_overflow_before_native_generation(self):
        session = self.session()
        session._json = Mock(return_value={'tokens': list(range(2045))})
        session._generated_tokens = Mock()
        session._request = Mock()
        with self.assertRaisesRegex(ValueError, 'prompt and output'):
            list(self.generate(session, cancelled=lambda: False))
        session._generated_tokens.assert_not_called()
        session._request.assert_not_called()

    def test_already_cancelled_request_does_not_start_native_generation(self):
        session = self.session()
        session._json = Mock(return_value={'tokens': [1, 2]})
        session._generated_tokens = Mock(side_effect=[12, 12])
        session._request = Mock()
        result = list(self.generate(session, cancelled=lambda: True))
        self.assertEqual(result[-1]['usage']['completion_tokens'], 0)
        self.assertEqual(result[-1]['finish_reason'], 'cancelled')
        session._request.assert_not_called()

    def test_cancellation_accounts_for_native_tokens_beyond_delivered_text(self):
        session = self.session()
        session._json = Mock(return_value={'tokens': [1, 2]})
        session._generated_tokens = Mock(side_effect=[10, 13])
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_lines.return_value = iter([
            b'data: {"choices":[{"text":"one"}]}',
            b'data: {"choices":[{"text":"not delivered"}]}',
        ])
        session._request = Mock(return_value=response)
        session._wait_idle = Mock()
        stopped = [False]
        iterator = self.generate(session, cancelled=lambda: stopped[0])
        self.assertEqual(next(iterator), {'text': 'one'})
        stopped[0] = True
        result = list(iterator)
        self.assertEqual(result[-1]['usage'], {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5})
        self.assertEqual(result[-1]['finish_reason'], 'cancelled')
        session._wait_idle.assert_called_once()
        response.__exit__.assert_called_once()

    def test_generator_disconnect_closes_stream_and_waits_for_native_work(self):
        session = self.session()
        session._json = Mock(return_value={'tokens': [1, 2]})
        session._generated_tokens = Mock(return_value=0)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_lines.return_value = iter([b'data: {"choices":[{"text":"first"}]}'])
        session._request = Mock(return_value=response)
        session._wait_idle = Mock()
        iterator = self.generate(session, cancelled=lambda: False)
        next(iterator)
        iterator.close()
        response.__exit__.assert_called_once()
        session._wait_idle.assert_called_once()

    def test_unknown_or_invalid_native_usage_is_refused(self):
        for value in ('-1', 'nan', '1.5', 'inf', None):
            with self.subTest(value=value):
                session = self.session()
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                response.text = '' if value is None else 'llamacpp:tokens_predicted_total ' + value
                session._request = Mock(return_value=response)
                with self.assertRaisesRegex(ValueError, 'measured token usage'):
                    session._generated_tokens()


@tag('gguf')
@skipUnless(os.environ.get('MODELANVIL_GGUF_TEST_MODEL'), 'Provide the pinned local GGUF fixture explicitly.')
class GGUFNative(TestCase):
    def test_actual_cpu_generation_cancellation_and_unload(self):
        import requests
        from modelanvil.runners.inference import generate
        model = GGUFSession(os.environ['MODELANVIL_GGUF_TEST_MODEL'])
        address = model.base_url
        session = {'format': 'gguf', 'model': model, 'device': 'cpu'}
        messages = [{'role': 'user', 'content': 'What is 2 + 2?'}]
        try:
            first = list(generate(session, messages, max_tokens=8))
            second = list(generate(session, messages, max_tokens=8))
            self.assertTrue(''.join(p.get('text', '') for p in first))
            self.assertEqual(''.join(p.get('text', '') for p in first),
                             ''.join(p.get('text', '') for p in second))
            self.assertGreater(first[-1]['usage']['completion_tokens'], 0)
            self.assertLessEqual(first[-1]['usage']['completion_tokens'], 8)
            stopped = [False]
            parts = []
            for part in generate(session, messages, max_tokens=64, cancelled=lambda: stopped[0]):
                parts.append(part)
                if 'text' in part:
                    stopped[0] = True
            self.assertEqual(parts[-1]['finish_reason'], 'cancelled')
            self.assertLess(parts[-1]['usage']['completion_tokens'], 64)
            with self.assertRaisesRegex(ValueError, 'prompt and output'):
                list(generate(session, [{'role': 'user', 'content': 'word ' * 2200}], max_tokens=8))
            iterator = generate(session, messages, max_tokens=64)
            next(iterator)
            iterator.close()
            self.assertFalse(model._json('/slots')[0]['is_processing'])
            response = requests.post(address + '/v1/completions',
                                     json={'prompt': 'hello', 'max_tokens': 8}, timeout=5)
            self.assertEqual(response.status_code, 401)
        finally:
            model.close()
        with self.assertRaises(requests.ConnectionError):
            requests.get(address + '/health', timeout=2)
