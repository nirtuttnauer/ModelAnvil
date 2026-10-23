"""Explicit project-scoped compatible providers. Credentials stay on the API host."""
from contextlib import contextmanager
from copy import deepcopy
import json
import math
import time
from urllib.parse import urlsplit
import urllib.request
import uuid

from django.conf import settings

NAMESPACE = uuid.UUID('264db0a6-845e-43b5-b71a-42f7c7618e05')


def configured(tenant, project):
    scope = f'{tenant}:{project}'
    values = settings.MODELANVIL_EXTERNAL_PROVIDERS.get(scope, {})
    keys = settings.MODELANVIL_EXTERNAL_PROVIDER_KEYS.get(scope, {})
    if not isinstance(values, dict) or len(values) > 16:
        raise ValueError('Invalid installed provider configuration.')
    result = {}
    for key, value in values.items():
        if (not isinstance(key, str) or not 1 <= len(key) <= 80 or not isinstance(value, dict)
                or set(value) != {'name', 'endpoint', 'model', 'credential_id'}
                or any(not isinstance(v, str) or not v.strip() or len(v) > 2048 for v in value.values())):
            raise ValueError('Invalid installed provider configuration.')
        endpoint = urlsplit(value['endpoint'])
        secret = keys.get(value['credential_id']) if isinstance(keys, dict) else None
        if not isinstance(secret, str) or not 1 <= len(secret) <= 2048 or '\r' in secret or '\n' in secret:
            raise ValueError('The installed provider credential is unavailable.')
        if (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or not endpoint.hostname
                or endpoint.scheme != 'https' and not (settings.DEBUG and endpoint.scheme == 'http' and endpoint.hostname in ('127.0.0.1', '::1'))
                or not endpoint.path.endswith('/chat/completions')):
            raise ValueError('Provider endpoints require HTTPS, no embedded secrets and the exact chat/completions path.')
        identifier = str(uuid.uuid5(NAMESPACE, f'{tenant}:{project}:{key}'))
        result[identifier] = {**deepcopy(value), 'api_key': secret}
    return result


def public_target(identifier, value):
    return {'id': identifier, **{k: v for k, v in value.items() if k != 'api_key'}}


def installed_targets(tenant, project):
    return [public_target(identifier, value) for identifier, value in configured(tenant, project).items()]


def resolve(identifier, tenant, project):
    from modelanvil.core.privacy import project_policy
    policy = project_policy(tenant, project)
    value = configured(tenant, project).get(str(identifier))
    if policy['offline'] or str(identifier) not in policy['external_generation_targets'] or value is None:
        raise ValueError('This external provider is unavailable or disabled in project Privacy settings.')
    return value


def catalog(tenant, project):
    from modelanvil.core.privacy import project_policy
    policy = project_policy(tenant, project)
    return [{**value, 'object': 'model', 'format': 'external', 'owned_by': 'external-provider',
        'load_tested': False, 'chat_template': '', 'devices': ['external'], 'max_tokens': 256,
        'context_limit': None, 'tokenizer_kind': 'upstream', 'base_model_id': None, 'training_run_id': None}
        for value in installed_targets(tenant, project) if not policy['offline'] and value['id'] in policy['external_generation_targets']]


def accessible_request(record, tenant, project):
    if record.model_version_id is not None:
        from modelanvil.identity.models import check_resource_access
        return check_resource_access(record.model_version, project, tenant)
    try:
        value = resolve(record.provider_snapshot['id'], tenant, project)
        return public_target(record.provider_snapshot['id'], value) == record.provider_snapshot
    except (ValueError, KeyError):
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@contextmanager
def session(value, messages, *, max_tokens, temperature, seed, prompt_format, device):
    if device != 'external' or prompt_format != 'model' or not math.isfinite(temperature):
        raise ValueError('External providers require their native chat formatting and external device.')
    body = json.dumps({'model': value['model'], 'messages': messages, 'max_tokens': max_tokens,
        'temperature': temperature, 'seed': seed, 'stream': True, 'stream_options': {'include_usage': True}}, allow_nan=False).encode()
    request = urllib.request.Request(value['endpoint'], data=body,
        headers={'Authorization': 'Bearer ' + value['api_key'], 'Content-Type': 'application/json', 'Accept': 'text/event-stream, application/json'}, method='POST')
    # No environment proxy, netrc, cookies, redirects or browser credential transport.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            if response.headers.get_content_type() != 'text/event-stream':
                raise ValueError('Expected a compatible event stream.')
            yield parts(response)
    except Exception:
        # Upstream URLs, response bodies and authentication errors may contain secrets.
        raise ValueError('External generation failed; check the selected endpoint, credential and provider limits.') from None


def parts(response):
    started = time.monotonic()
    pending, total, output_size = b'', 0, 0
    usage, finish = None, None
    while True:
        if time.monotonic() - started > 30:
            raise ValueError('External generation exceeded its time limit.')
        raw = response.read1(4096)
        if not raw:
            raise ValueError('External stream ended without completion.')
        total += len(raw); pending += raw
        pending = pending.replace(b'\r\n', b'\n')
        if total > 256 * 1024 or len(pending) > 65536:
            raise ValueError('External stream exceeded its size limit.')
        while b'\n\n' in pending:
            event, pending = pending.split(b'\n\n', 1)
            data = b'\n'.join(line[5:].lstrip() for line in event.split(b'\n') if line.startswith(b'data:'))
            if not data:
                continue
            if data == b'[DONE]':
                if finish is None:
                    raise ValueError('External stream omitted its finish reason.')
                yield {'finish_reason': finish, 'usage': usage, 'elapsed_seconds': time.monotonic() - started}
                return
            item = json.loads(data)
            if not isinstance(item, dict) or 'error' in item:
                raise ValueError('External provider returned an error.')
            if item.get('usage') is not None:
                supplied = item['usage']
                keys = ('prompt_tokens', 'completion_tokens', 'total_tokens')
                if (not isinstance(supplied, dict) or any(type(supplied.get(k)) is not int or not 0 <= supplied[k] <= 10000000 for k in keys)
                        or supplied['prompt_tokens'] + supplied['completion_tokens'] != supplied['total_tokens']):
                    raise ValueError('Invalid provider token usage.')
                usage = {k: supplied[k] for k in keys}
            choices = item.get('choices')
            if not isinstance(choices, list) or len(choices) > 1:
                raise ValueError('Expected one external completion.')
            if choices:
                choice = choices[0]
                delta = choice.get('delta', {})
                if not isinstance(delta, dict) or set(delta) - {'role', 'content'}:
                    raise ValueError('Only text completions are supported.')
                text = delta.get('content')
                if text is not None:
                    if not isinstance(text, str) or finish is not None:
                        raise ValueError('Invalid external text output.')
                    output_size += len(text)
                    if output_size > 32000:
                        raise ValueError('External output exceeds the text limit.')
                    if text:
                        yield {'text': text}
                reason = choice.get('finish_reason')
                if reason is not None:
                    if finish is not None or reason not in ('stop', 'length'):
                        raise ValueError('Unsupported external finish reason.')
                    finish = reason
