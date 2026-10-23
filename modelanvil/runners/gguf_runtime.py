"""Bounded CPU llama.cpp inference without Python object or disk caches."""
from __future__ import annotations

import gc
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_WEIGHT_BYTES = 1024**3


class GGUFSession:
    def __init__(self, path):
        path = Path(path)
        if not 0 < path.stat().st_size <= MAX_WEIGHT_BYTES:
            raise ValueError('CPU GGUF weights must fit within the verified 1 GiB limit.')
        try:
            import gguf
            import requests
            import xllamacpp
        except ImportError:
            raise ValueError('Install requirements.inference.txt for CPU GGUF inference.') from None
        try:
            reader = gguf.GGUFReader(str(path))
            architecture = reader.fields['general.architecture'].contents()
            context = reader.fields.get(f'{architecture}.context_length')
            context = context.contents() if context else 2048
            self.has_chat_template = bool(reader.fields.get('tokenizer.chat_template'))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError('GGUF model metadata is invalid or unsupported.') from None
        if type(context) is not int or context < 1:
            raise ValueError('GGUF model has an invalid context limit.')
        self.context_limit = min(context, 2048)
        del reader
        params = xllamacpp.CommonParams()
        params.model.path = str(path)
        params.n_ctx = self.context_limit
        params.n_parallel = 1
        params.n_predict = 256
        params.n_gpu_layers = 0
        params.no_op_offload = True
        params.no_kv_offload = True
        params.cpuparams.n_threads = 1
        params.cpuparams_batch.n_threads = 1
        params.ctx_shift = False
        params.warmup = False
        params.cache_prompt = False
        params.cache_idle_slots = False
        params.cache_ram_mib = 0
        params.path_prompt_cache = ''
        params.slot_save_path = ''
        params.hostnames = ['127.0.0.1']
        params.port = 0
        params.endpoint_props = False
        params.endpoint_slots = True
        params.endpoint_metrics = True
        params.api_keys = [secrets.token_urlsafe(32)]
        try:
            self.server = xllamacpp.Server(params)
        except RuntimeError:
            raise ValueError('GGUF runtime could not load the verified model.') from None
        self.base_url = self.server.listening_address
        address = urlsplit(self.base_url)
        if address.scheme != 'http' or address.hostname != '127.0.0.1' or not address.port:
            self.close()
            raise ValueError('GGUF runtime did not bind to a private loopback port.')
        self.http = requests.Session()
        self.http.trust_env = False
        self.http.headers['Authorization'] = 'Bearer ' + params.api_keys[0]

    def close(self):
        if getattr(self, 'http', None) is not None:
            self.http.close()
            self.http = None
        self.server = None
        gc.collect()

    def _request(self, path, body=None, *, stream=False):
        import requests
        try:
            response = self.http.request('GET' if body is None else 'POST', self.base_url + path,
                                         json=body, stream=stream, timeout=(5, 30), allow_redirects=False)
            if response.status_code != 200:
                response.close()
                raise ValueError('GGUF runtime rejected the request; check model inputs and context.')
            return response
        except requests.RequestException:
            raise ValueError('GGUF runtime is unavailable or exceeded its bounded response time.') from None

    def _json(self, path, body=None):
        with self._request(path, body) as response:
            return response.json()

    def _generated_tokens(self):
        with self._request('/metrics') as response:
            for line in response.text.splitlines():
                if line.startswith('llamacpp:tokens_predicted_total '):
                    value = float(line.split()[1])
                    if value >= 0 and value.is_integer():
                        return int(value)
        raise ValueError('GGUF runtime did not report measured token usage.')

    def _wait_idle(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not any(slot['is_processing'] for slot in self._json('/slots')):
                return
            time.sleep(0.01)
        raise ValueError('GGUF generation did not stop within its cancellation limit.')

    def generate(self, messages, *, max_tokens, temperature, seed, prompt_format, cancelled, started):
        from modelanvil.runners.inference import rendered_prompt
        chat = prompt_format == 'model' and self.has_chat_template
        prompt = (self._json('/apply-template', {'messages': messages})['prompt'] if chat
                  else rendered_prompt(None, messages, 'plain' if prompt_format == 'model' else prompt_format))
        tokens = self._json('/tokenize', {'content': prompt, 'add_special': True, 'parse_special': True})['tokens']
        if not tokens or len(tokens) + max_tokens > self.context_limit:
            raise ValueError(f'GGUF prompt and output must fit within {self.context_limit} tokens; shorten the conversation.')
        before = self._generated_tokens()
        finish = 'length'
        if cancelled():
            finish = 'cancelled'
        else:
            body = {'messages': messages} if chat else {'prompt': prompt}
            body.update(max_tokens=max_tokens, temperature=temperature, seed=seed, stream=True,
                        stream_options={'include_usage': True}, cache_prompt=False)
            path = '/v1/chat/completions' if chat else '/v1/completions'
            try:
                with self._request(path, body, stream=True) as response:
                    for line in response.iter_lines(chunk_size=1):
                        if cancelled():
                            finish = 'cancelled'
                            break
                        if not line.startswith(b'data: ') or line == b'data: [DONE]':
                            continue
                        part = json.loads(line[6:])
                        if part.get('error'):
                            raise ValueError('GGUF generation failed in the native runtime.')
                        for choice in part.get('choices', []):
                            text = choice.get('delta', {}).get('content') if chat else choice.get('text')
                            finish = choice.get('finish_reason') or finish
                            if text:
                                yield {'text': text}
            finally:
                # Closing the HTTP stream cancels native work; account for tokens already computed.
                self._wait_idle()
        count = self._generated_tokens() - before
        if count < 0 or count > max_tokens:
            raise ValueError('GGUF runtime returned inconsistent measured usage.')
        yield {'finish_reason': finish, 'elapsed_seconds': time.monotonic() - started,
               'usage': {'prompt_tokens': len(tokens), 'completion_tokens': count,
                         'total_tokens': len(tokens) + count}}
