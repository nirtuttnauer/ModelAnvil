"""Scoped replay for JSON resource writes that callers may retry after network loss."""
import hashlib
import json
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from modelanvil.core.models import IdempotencyKey
from modelanvil.core.tenancy import get_active_tenant, get_active_project


@transaction.atomic
def idempotent_write(request, write):
    key = request.headers.get('Idempotency-Key', '').strip()
    if not key:
        return write()
    if len(key) > 128:
        raise serializers.ValidationError('Idempotency-Key supports at most 128 characters.')
    request_hash = hashlib.sha256(json.dumps(request.data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    record, _ = IdempotencyKey.all_objects.select_for_update().get_or_create(tenant_id=get_active_tenant(),
        principal=f'{request.user.pk}:{get_active_project() or "tenant"}', key=key, http_method=request.method,
        path=request.path, defaults={'request_hash': request_hash})
    if record.request_hash != request_hash:
        return Response({'detail': 'Idempotency key already used with different inputs.'}, status=409)
    if record.response_status:
        return Response(record.response_body, status=record.response_status)
    response = write()
    if 200 <= response.status_code < 300:
        record.response_status = response.status_code
        record.response_body = json.loads(JSONRenderer().render(response.data))
        record.completed_at = timezone.now()
        record.save(update_fields=['response_status', 'response_body', 'completed_at'])
    return response
