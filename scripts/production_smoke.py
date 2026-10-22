"""HTTPS/proxy checks and optional sign-in against a production staging stack."""
import argparse
from pathlib import Path
import http.cookiejar
import json
import re
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True, help='HTTPS origin, including staging port')
    parser.add_argument('--ca', help='Local staging CA; omitted for public certificates')
    parser.add_argument('--credentials', help='Optional private JSON file with staging email and password')
    args = parser.parse_args()
    parsed = urlsplit(args.origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
        parser.error('--origin must be an HTTPS origin')
    context = ssl.create_default_context(cafile=args.ca)
    cookies = http.cookiejar.CookieJar()
    client = build_opener(HTTPSHandler(context=context), HTTPCookieProcessor(cookies))

    def request(path, data=None, headers=None):
        req = Request(args.origin + path, data=data, headers=headers or {})
        try:
            response = client.open(req, timeout=15)
        except HTTPError as response_error:
            response = response_error
        with response:
            return response.status, response.headers, response.read()

    status, headers, index = request('/')
    assert status == 200 and b'<div id="root"' in index, 'Built application is unavailable'
    assert headers['Cache-Control'] == 'no-cache', 'Entry point must not be immutable'
    assert headers['Strict-Transport-Security'] == 'max-age=3600; includeSubDomains', 'HTTPS policy is missing'
    assets = re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', index)
    assert assets, 'Built assets are missing'
    for asset in assets:
        status, headers, body = request(asset.decode())
        assert status == 200 and body and 'text/html' not in headers['Content-Type'], 'Asset was not served'
        assert 'immutable' in headers['Cache-Control'], 'Hashed assets must be cacheable'
    assert request('/training')[2] == index, 'SPA route fallback failed'
    assert request('/assets/does-not-exist.js')[0] == 404, 'Missing assets must not return the SPA'
    assert request('/api/v1/health/')[0] == 200, 'Liveness probe failed'
    assert request('/api/v1/ready/')[0] == 200, 'Database readiness failed'
    assert request('/static/admin/css/base.css')[0] == 200, 'Django static files are missing'

    status, _, body = request('/api/v1/accounts/status/', headers={'X-Forwarded-Proto': 'http'})
    assert status == 200 and json.loads(body)['signup_enabled'] is False, 'Proxy scheme or signup configuration failed'
    csrf = next(cookie for cookie in cookies if cookie.name == 'csrftoken')
    assert csrf.secure, 'CSRF cookie must require HTTPS'
    data = json.dumps({'email': 'nobody@example.test', 'password': 'incorrect-test-password'}).encode()
    headers = {'Content-Type': 'application/json', 'Origin': args.origin}
    assert request('/api/v1/accounts/signin/', data, headers)[0] == 403, 'Missing CSRF was accepted'
    headers['X-CSRFToken'] = csrf.value
    assert request('/api/v1/accounts/signin/', data, headers)[0] == 401, 'Valid same-origin CSRF did not reach authentication'
    headers['Origin'] = 'https://other.example'
    assert request('/api/v1/accounts/signin/', data, headers)[0] == 403, 'Foreign origin was accepted'
    if args.credentials:
        credentials = Path(args.credentials).read_bytes()
        headers['Origin'] = args.origin
        status, _, body = request('/api/v1/accounts/signin/', credentials, headers)
        assert status == 200 and json.loads(body)['token'] == 'session', 'Staging sign-in failed'
        session = next(cookie for cookie in cookies if cookie.name == 'modelanvil_session')
        assert session.secure and session.has_nonstandard_attr('HttpOnly'), 'Browser session must be secure and HttpOnly'
        assert request('/api/v1/build/')[0] == 200, 'Authenticated session failed'
    print(json.dumps({'status': 'passed', 'checks': ['verified TLS', 'built assets', 'SPA routing',
        'static files', 'database readiness', 'proxy scheme', 'secure CSRF cookie', 'CSRF rejection', 'signup disabled']}))


if __name__ == '__main__':
    main()
