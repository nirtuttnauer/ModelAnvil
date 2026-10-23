"""Independent stdlib HTTPS client for the bounded compatible inference contract."""
import argparse
import http.client
import json
from pathlib import Path
import re
import socket
import ssl
import sys
from urllib.parse import urlsplit
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--ca', type=Path, required=True)
    parser.add_argument('--credentials', required=True, help='Private fixture JSON, or - for stdin')
    parser.add_argument('--connect-host', help='Explicit namespace-local TCP destination; TLS still verifies the origin hostname')
    parser.add_argument('--connect-port', type=int)
    parser.add_argument('--key-prefix', default='protocol')
    parser.add_argument('--expect-replay', action='store_true')
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.path not in ('', '/') or origin.query or origin.fragment:
        parser.error('Use an HTTPS origin without credentials, path, query or fragment.')
    data = json.loads(sys.stdin.read(16385) if args.credentials == '-' else Path(args.credentials).read_text())
    assert set(data) == {'key', 'project_id', 'model'}, 'Use private fixture connection fields.'
    assert all(isinstance(v, str) and 1 <= len(v) <= 200 for v in data.values())
    context = ssl.create_default_context(cafile=str(args.ca))
    versions = set()

    class Connection(http.client.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection((args.connect_host or origin.hostname,
                args.connect_port or origin.port or 443), timeout=self.timeout)
            self.sock = self._context.wrap_socket(raw, server_hostname=origin.hostname)

    def call(path, body=None, *, key=None, accept='application/json', auth=True, project=None, tls=context):
        connection = Connection(origin.hostname, origin.port or 443, timeout=30, context=tls)
        headers = {'Host': origin.netloc, 'Accept': accept, 'Content-Type': 'application/json'}
        if auth:
            headers.update(Authorization='Bearer ' + data['key'], **{'X-Project-ID': project or data['project_id']})
        if key:
            headers['Idempotency-Key'] = args.key_prefix + '-' + key
        try:
            connection.request('POST' if body is not None else 'GET', '/api/v1/' + path,
                body=json.dumps(body) if body is not None else None, headers=headers)
            assert connection.sock.getpeercert() and tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED
            versions.add(connection.sock.version())
            response = connection.getresponse(); raw = response.read(1024 * 1024 + 1)
            assert len(raw) <= 1024 * 1024
            return response.status, {key.lower(): value for key, value in response.getheaders()}, raw
        finally:
            connection.close()

    try:
        call('inference/models', auth=False, tls=ssl.create_default_context())
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise AssertionError('Fresh private fixture CA was unexpectedly trusted by default.')
    status, _, raw = call('inference/models', auth=False)
    assert status == 401 and 'error' in json.loads(raw)
    status, _, raw = call('inference/models')
    assert status == 200
    before = json.loads(raw); assert data['model'] in {v['id'] for v in before['data']}
    body = {'model': data['model'], 'messages': [{'role': 'user', 'content': 'a'}],
        'max_tokens': 8, 'temperature': 0, 'seed': 42}
    status, headers, raw = call('inference/chat/completions', body, key='json')
    assert status == 200, raw
    first = json.loads(raw)
    assert first['object'] == 'chat.completion' and re.fullmatch(r'chatcmpl-[a-f0-9]{32}', first['id'])
    assert first['model'] == data['model'] and first['usage']['completion_tokens'] > 0
    assert headers['idempotency-replayed'] == ('true' if args.expect_replay else 'false')
    status, replay_headers, raw = call('inference/chat/completions', body, key='json')
    assert status == 200 and json.loads(raw) == first and replay_headers['idempotency-replayed'] == 'true'
    status, _, raw = call('inference/chat/completions', {**body, 'max_tokens': 7}, key='json')
    assert status == 409 and 'error' in json.loads(raw)

    streamed = {**body, 'stream': True, 'stream_options': {'include_usage': True}}
    def read_stream(replay=False):
        status, response_headers, raw = call('inference/chat/completions', streamed, key='sse', accept='text/event-stream')
        assert status == 200 and response_headers['content-type'].startswith('text/event-stream'), raw
        assert response_headers['idempotency-replayed'] == ('true' if replay or args.expect_replay else 'false')
        assert raw.endswith(b'data: [DONE]\n\n')
        events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith(b'data: ') and line != b'data: [DONE]']
        assert all('error' not in event for event in events)
        identifiers = {event['id'] for event in events}; assert len(identifiers) == 1
        return {'id': next(iter(identifiers)), 'text': ''.join(choice['delta'].get('content', '') for event in events for choice in event['choices']),
            'usage': events[-1]['usage']}
    stream = read_stream(); assert read_stream(True) == stream
    assert stream['text'] == first['choices'][0]['message']['content'] and stream['usage'] == first['usage']
    refusals = []
    for changes in ({'top_p': .5}, {'max_tokens': 257}, {'messages': [{'role': 'user', 'content': 'a' * 63}]}):
        status, _, raw = call('inference/chat/completions', {**body, **changes})
        assert status == 400 and 'error' in json.loads(raw)
        refusals.append(json.loads(raw)['error']['code'])
    status, _, raw = call('inference/models', project=str(uuid.uuid4()))
    assert status in (401, 403, 404) and 'error' in json.loads(raw)
    status, _, raw = call('inference/models'); assert status == 200
    assert next(v for v in json.loads(raw)['data'] if v['id'] == data['model'])['load_tested']
    imported = any(name == 'django' or name.startswith('django.') or name == 'modelanvil' or name.startswith('modelanvil.') for name in sys.modules)
    assert not imported
    result = {'status': 'passed', 'scope': 'Actual HTTPS CPU character inference from an independent client; no physical second-host or production capacity qualification.',
        'tls_versions': sorted(versions), 'ca_verified': True, 'hostname_verification_enabled': context.check_hostname,
        'untrusted_ca_refused': True, 'client_imported_application': imported,
        'json_completion': first, 'stream_completion': stream, 'replay_after_restart': args.expect_replay,
        'structured_refusals': refusals, 'project_scope_refused': True, 'actual_load_observed': True}
    encoded = json.dumps(result, allow_nan=False)
    assert data['key'] not in encoded
    print(encoded)


if __name__ == '__main__':
    main()
