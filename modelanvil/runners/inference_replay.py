"""Opt-in durable completion replay; never re-execute an ambiguous request."""
import hashlib
import json

from django.db import OperationalError, transaction
from django.utils import timezone
from rest_framework import serializers

from modelanvil.core.exceptions import WorkflowConflict
from modelanvil.core.models import IdempotencyKey
from modelanvil.core.tenancy import get_active_project, get_active_tenant

RETENTION_SECONDS = 7 * 24 * 3600


def reserve(request, options, identity):
    supplied = request.headers.get('Idempotency-Key')
    if supplied is None:
        return None, False
    key = supplied.strip()
    if not key or len(key) > 128:
        raise serializers.ValidationError('Idempotency-Key requires 1–128 non-whitespace characters.')
    request_hash = hashlib.sha256(json.dumps({'options': options, 'model_identity': identity},
        sort_keys=True, separators=(',', ':'), default=str, allow_nan=False).encode()).hexdigest()
    actor = f'{getattr(request, "modelanvil_actor_kind", "principal")}:{getattr(request, "modelanvil_actor_id", request.user.pk)}'
    lookup = {'tenant_id': get_active_tenant(), 'principal': f'inference:{actor}:{get_active_project()}',
              'http_method': request.method, 'path': request.path, 'key': key}
    try:
        with transaction.atomic():
            record, created = IdempotencyKey.all_objects.select_for_update().get_or_create(**lookup,
                defaults={'request_hash': request_hash})
            if not created and record.is_expired(RETENTION_SECONDS):
                record.delete()
                record = IdempotencyKey.all_objects.create(**lookup, request_hash=request_hash)
                created = True
            if record.request_hash != request_hash:
                raise WorkflowConflict('Idempotency-Key already used with different inputs or model pins.')
            if not created and record.response_status is None:
                raise WorkflowConflict('This inference key is still in progress or interrupted. It will not be executed again; use a new key to authorize another generation.')
            if not created and record.response_status != 200:
                raise WorkflowConflict('The original inference did not complete. Use a new key to authorize another generation.')
            return record, not created
    except OperationalError as exc:
        if 'locked' not in str(exc).lower():
            raise
        raise WorkflowConflict('Inference replay admission is busy. Retry the same key.') from None


def finish(record, body=None):
    if record is not None:
        IdempotencyKey.all_objects.filter(pk=record.pk, response_status__isnull=True).update(
            response_status=200 if body is not None else 409, response_body=body,
            completed_at=timezone.now(), updated_at=timezone.now())


def headers(response, record, replayed=False):
    if record is not None:
        response['Idempotency-Retention'] = str(RETENTION_SECONDS)
        response['Idempotency-Replayed'] = 'true' if replayed else 'false'
    return response


def events(body, check, *, include_usage):
    """Replay saved text in bounded SSE frames while checking current authority."""
    base = {k: body[k] for k in ('id', 'created', 'model')}
    def event(delta, finish=None):
        return {**base, 'object': 'chat.completion.chunk',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
    try:
        check()
        yield 'data: ' + json.dumps(event({'role': 'assistant'})) + '\n\n'
        text = body['choices'][0]['message']['content']
        for start in range(0, len(text), 4096):
            check()
            yield 'data: ' + json.dumps(event({'content': text[start:start+4096]})) + '\n\n'
        check()
        final = event({}, body['choices'][0]['finish_reason'])
        final['modelanvil'] = body['modelanvil']
        yield 'data: ' + json.dumps(final) + '\n\n'
        if include_usage and body['usage'] is not None:
            check()
            yield 'data: ' + json.dumps({**base, 'object': 'chat.completion.chunk', 'choices': [], 'usage': body['usage']}) + '\n\n'
    except Exception:
        yield 'data: ' + json.dumps({'error': {'message': 'Current inference access changed; cached output withheld.', 'type': 'inference_error'}}) + '\n\n'
    yield 'data: [DONE]\n\n'
