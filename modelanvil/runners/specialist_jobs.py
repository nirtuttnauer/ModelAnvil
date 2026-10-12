"""Budgeted specialist requests using the existing durable claim protocol."""
import hashlib
import io
import json
from pathlib import Path
import uuid

from django.db import transaction
from django.utils import timezone

from modelanvil.artifacts.models import Artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.core.models import IdempotencyKey
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Job, JobAttempt, OutboxEvent, Worker, dispatch_topic
from modelanvil.runners import specialists
from modelanvil.runners.inference import copy_verified
from modelanvil.runners.model_catalog import _store
from modelanvil.runners.models import InferenceRequest, ModelVersion
from modelanvil.runners.training.hf_runtime import file_ref
from modelanvil.runners.training.runtime import digest

TYPE = 'specialist_inference'
MAX_ATTEMPTS = 3
UNIT = 'specialist_attempts'


def runtime_digest():
    root = specialists.RUNTIME.parents[1]
    paths = [specialists.RUNTIME, specialists.__file__, __file__,
        root / 'modelanvil/api/views/specialists.py', root / 'modelanvil/runners/specialist_pins.json',
        root / 'modelanvil/device_admission.py', root / 'modelanvil/runners/inference.py',
        root / 'modelanvil/runners/training/hf_runtime.py', root / 'requirements.specialists.txt']
    return digest([hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths])


@transaction.atomic
def queue(*, tenant, project, principal, version, kind, device, inputs, image, layout, pool, policy_id, key):
    from scripts.specialist_runtime import validate_decision, validate_ocr
    (validate_decision if kind == 'laya' else validate_ocr)(inputs)
    allowed = ['cpu', 'mps:0'] if kind == 'laya' else ['cpu'] if kind == 'layout' else ['mlx:0']
    if device not in allowed or (layout and kind != 'ocr'):
        raise ValueError('Choose a supported specialist device and layout combination.')
    specialists.snapshot(version, tenant, project.pk, kind)
    if layout:
        specialists.snapshot(layout, tenant, project.pk, 'layout')
    if kind != 'laya' and (image is None or not check_resource_access(image, project.pk, tenant)
                           or image.metadata.get('kind') != 'ocr_image' or image.byte_size > 8 * 1024**2):
        raise ValueError('Select an accessible bounded OCR source.')
    frozen = {'kind':kind, 'device':device, 'inputs':inputs, 'model':str(version.model_version_id),
        'snapshot':version.metadata['snapshot_manifest'], 'image':file_ref(image) if image else None,
        'layout':str(layout.model_version_id) if layout else None,
        'layout_snapshot':layout.metadata['snapshot_manifest'] if layout else None, 'runtime':runtime_digest()}
    fingerprint = digest({'frozen':frozen, 'pool':pool.pk, 'budget_policy':str(policy_id)})
    identity = dict(tenant_id=tenant, principal=str(principal), http_method='POST',
                    path=f'/specialists/{project.pk}/jobs', key=key)
    admission, created = IdempotencyKey.all_objects.select_for_update().get_or_create(
        **identity, defaults={'request_hash':fingerprint})
    if not created:
        if admission.request_hash != fingerprint:
            raise ValueError('This idempotency key belongs to different specialist inputs.')
        return InferenceRequest.all_objects.get(request_id=admission.response_body['request_id'], tenant_id=tenant, project=project)
    if (str(pool.tenant_id) != str(tenant) or pool.status != 'active' or pool.result_egress != 'envelope'
            or not Worker.all_objects.filter(tenant_id=tenant, pool=pool, status__in=['available','busy'],
                capabilities__specialist_runtime=frozen['runtime'], capabilities__specialist_device=device).exists()):
        raise ValueError('Select an active envelope pool with a worker for this exact specialist runtime and device.')
    policy = BudgetPolicy.all_objects.filter(tenant_id=tenant, policy_id=policy_id, enabled=True, unit=UNIT, currency='').first()
    if policy is None:
        raise ValueError('Select an enabled specialist_attempts quota without currency pricing.')
    job_id = uuid.uuid4()
    BudgetReservation.reserve(tenant_id=tenant, policy=policy, job_id=job_id, estimated_amount=MAX_ATTEMPTS)
    record = InferenceRequest.all_objects.create(tenant_id=tenant, project=project, principal_id=str(principal),
        model_version=version, input_digest=digest(frozen), status='queued',
        configuration={'kind':kind, 'device':device, 'job_id':str(job_id), 'frozen':frozen})
    Job.all_objects.create(tenant_id=tenant, job_id=job_id, pool=pool, name=f'{kind.upper()} document job',
        max_attempts=MAX_ATTEMPTS, payload={'type':TYPE, 'request_id':str(record.request_id),
            'input_digest':record.input_digest}, requirements={'slots':1, 'specialist_runtime':frozen['runtime'], 'specialist_device':device})
    admission.response_body = {'request_id':str(record.request_id)}; admission.response_status = 202
    admission.completed_at = timezone.now(); admission.save()
    return record


def owning_request(job, lock=False):
    qs = InferenceRequest.all_objects.select_related('project', 'model_version__tokenizer')
    if lock:
        qs = qs.select_for_update()
    record = qs.get(request_id=job.payload['request_id'], tenant_id=job.tenant_id)
    if record.configuration.get('job_id') != str(job.job_id) or record.input_digest != job.payload['input_digest']:
        raise ValueError('Specialist job ownership changed.')
    return record


def live_request(context):
    attempt = JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job = Job.all_objects.select_for_update().get(pk=attempt.job_id)
    if (attempt.status != 'running' or job.status != 'running' or attempt.fencing_token != context.fencing_token
            or job.fencing_token != context.fencing_token or job.claimed_by_id != attempt.worker_id
            or not attempt.lease_expires_at or attempt.lease_expires_at <= timezone.now() or job.desired_action == 'cancel'):
        raise ValueError('Specialist job cancelled or fenced out.')
    from modelanvil.jobs.models import WorkerPool
    pool = WorkerPool.all_objects.select_for_update().get(pk=job.pool_id, tenant_id=job.tenant_id)
    if pool.result_egress != 'envelope':
        raise ValueError('Specialist result content is forbidden by the pool egress policy.')
    return owning_request(job, lock=True)


def read_result(record):
    ref = record.configuration.get('result') or record.configuration.get('checkpoint')
    if not ref or ref['byte_size'] > 2 * 1024**2:
        raise ValueError('Specialist result checkpoint is unavailable or exceeds its limit.')
    stream = io.BytesIO(); copy_verified(ref, record.tenant_id, record.project_id, stream)
    value = json.loads(stream.getvalue())
    if value['request_id'] != str(record.request_id) or value['input_digest'] != record.input_digest:
        raise ValueError('Specialist result checkpoint identity changed.')
    return value['result']


def specialist_executor(descriptor, context):
    if descriptor.get('payload', {}).get('type') != TYPE:
        raise ValueError('This executor accepts specialist jobs only.')
    if not context.heartbeat(progress=0):
        return None
    with transaction.atomic():
        record = live_request(context)
        frozen = record.configuration['frozen']
        if digest(frozen) != record.input_digest or frozen['runtime'] != runtime_digest():
            raise ValueError('Specialist inputs or runtime changed; queue a new request.')
        if record.configuration.get('checkpoint'):
            read_result(record)  # Verify bytes before reusing a completed result.
            return None
        reservation = BudgetReservation.all_objects.get(tenant_id=record.tenant_id, job_id=context.attempt.job.job_id)
        if reservation.state != 'reserved':
            raise ValueError('Specialist attempt quota is unavailable.')
        UsageEvent.record(tenant_id=record.tenant_id, provider_event_key=f'specialist:{context.attempt.attempt_id}',
            quantity=1, unit=UNIT, reservation=reservation, detail={'request_id':str(record.request_id),
            'attempt_id':str(context.attempt.attempt_id), 'runtime':frozen['runtime']})
        record.status = 'running'; record.save(update_fields=['status','updated_at'])
    version = record.model_version
    layout = ModelVersion.all_objects.get(model_version_id=frozen['layout'], tenant_id=record.tenant_id) if frozen['layout'] else None
    if (version.metadata.get('snapshot_manifest') != frozen['snapshot'] or
            layout and layout.metadata.get('snapshot_manifest') != frozen['layout_snapshot']):
        raise ValueError('The queued specialist model snapshot changed.')
    image = Artifact.all_objects.get(artifact_id=frozen['image']['artifact_id'], tenant_id=record.tenant_id) if frozen['image'] else None
    if image and file_ref(image) != frozen['image']:
        raise ValueError('The queued specialist source changed.')
    result = specialists.execute(version, tenant=record.tenant_id, project=record.project_id,
        kind=frozen['kind'], device=frozen['device'], inputs=frozen['inputs'], image=image, layout=layout, context=context)
    result['request_id'] = str(record.request_id)
    if image:
        result['provenance']['image'] = frozen['image']
    if not context.heartbeat(progress=1):
        return None
    with transaction.atomic():
        record = live_request(context)
        payload = json.dumps({'request_id':str(record.request_id), 'input_digest':record.input_digest,
                              'result':result}, allow_nan=False).encode()
        if len(payload) > 2 * 1024**2:
            raise ValueError('Specialist checkpoint exceeds its byte limit.')
        ref = _store(io.BytesIO(payload), tenant=record.tenant_id, project=record.project_id,
            name='specialist-result.json', metadata={'kind':'specialist_checkpoint', 'request_id':str(record.request_id)}, media_type='application/json')
        record.configuration = {**record.configuration, 'checkpoint':ref}
        record.save(update_fields=['configuration','updated_at'])
    return None


def finalize_job(job, status):
    """Called inside commit/reconciliation's fence transaction, including failures."""
    record = owning_request(job, lock=True)
    reservation = BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id, job_id=job.job_id)
    if status == 'succeeded':
        if job.pool.result_egress != 'envelope':
            raise ValueError('Specialist result content is forbidden by the pool egress policy.')
        result = read_result(record)
        if record.configuration['kind'] == 'ocr':
            from modelanvil.api.views.specialists import SpecialistViewSet
            image = Artifact.all_objects.get(artifact_id=record.configuration['frozen']['image']['artifact_id'], tenant_id=job.tenant_id)
            SpecialistViewSet._save_ocr(result, image, record.model_version, record, record.project)
        payload = json.dumps({'request_id':str(record.request_id), 'input_digest':record.input_digest,
                              'result':result}, allow_nan=False).encode()
        ref = _store(io.BytesIO(payload), tenant=record.tenant_id, project=record.project_id,
            name='specialist-result.json', metadata={'kind':'specialist_result', 'request_id':str(record.request_id)}, media_type='application/json')
        record.configuration = {**record.configuration, 'result':ref}
        record.usage = result['usage']; record.elapsed_seconds = result['elapsed_seconds']; record.output_digest = digest(result)
    record.status = 'completed' if status == 'succeeded' else status
    record.completed_at = timezone.now(); record.save()
    if reservation.state == 'reserved':
        used = sum(reservation.usage_events.values_list('quantity', flat=True))
        reservation.settle(used)


@transaction.atomic
def cancel(record):
    job = Job.all_objects.select_for_update().get(job_id=record.configuration['job_id'], tenant_id=record.tenant_id)
    if job.status in {'succeeded','failed'}:
        raise ValueError('This specialist job is already terminal.')
    job.desired_action = 'cancel'
    if job.status in {'queued','interrupted'}:
        job.status = 'cancelled'; finalize_job(job, 'cancelled')
    job.save(update_fields=['desired_action','status','updated_at'])
    return job


@transaction.atomic
def retry(record):
    job = Job.all_objects.select_for_update().get(job_id=record.configuration['job_id'], tenant_id=record.tenant_id)
    record = owning_request(job, lock=True)
    if job.status not in {'failed','interrupted'} or job.desired_action == 'cancel' or job.attempt_count >= MAX_ATTEMPTS:
        raise ValueError('Only failed/interrupted jobs with remaining attempts can be retried.')
    reservation = BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id, job_id=job.job_id)
    # Retain the original period: reclaiming unused quota cannot evade its limit.
    policy = BudgetPolicy.all_objects.select_for_update().get(pk=reservation.policy_id)
    _, commitment = BudgetReservation.current_commitment(policy)
    if (not policy.enabled or reservation.period_start != BudgetReservation.current_commitment(policy)[0]
            or commitment + MAX_ATTEMPTS - (reservation.settled_amount or 0) > policy.limit_amount):
        raise ValueError('Retry quota is unavailable; queue a new request under the current budget.')
    reservation.state = 'reserved'; reservation.settled_amount = None; reservation.settled_at = None; reservation.save()
    job.status = 'queued'; job.save(update_fields=['status','updated_at'])
    record.status = 'queued'; record.completed_at = None; record.save(update_fields=['status','completed_at','updated_at'])
    OutboxEvent.objects.create(tenant_id=job.tenant_id, topic=dispatch_topic(job.tenant_id, job.pool.queue_name, job.pool.name),
        payload={'event_type':'job.queued', 'job_id':str(job.job_id)})
    return job
