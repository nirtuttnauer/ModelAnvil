"""Project-scoped acquisition, typed decisions and OCR with immutable lineage."""
import hashlib
import io
import json
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, MethodNotAllowed
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.artifacts.models import Artifact, LineageEdge
from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.models import Project, check_resource_access
from modelanvil.jobs.models import WorkerPool
from modelanvil.runners import specialists
from modelanvil.runners.model_catalog import _store, launch_import
from modelanvil.runners.models import InferenceRequest, ModelVersion
from modelanvil.runners.training.runtime import digest


def project_scope():
    project = Project.all_objects.filter(pk=get_active_project(), tenant_id=get_active_tenant()).first()
    if project is None:
        raise serializers.ValidationError('Select a project for specialist inference.')
    return project


class StrictInput(serializers.Serializer):
    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('Unsupported request fields.')
        return attrs


class AcquireInput(StrictInput):
    kind = serializers.ChoiceField(choices=['laya', 'ocr'])
    name = serializers.CharField(max_length=180)
    pool = serializers.IntegerField(min_value=1)
    accepted_license = serializers.CharField(max_length=64)
    idempotency_key = serializers.CharField(max_length=128)


class DecisionInput(StrictInput):
    model = serializers.UUIDField()
    device = serializers.ChoiceField(choices=['cpu', 'mps:0'], default='cpu')
    state = serializers.JSONField()
    questions = serializers.JSONField()


class OcrInput(StrictInput):
    model = serializers.UUIDField()
    image_artifact = serializers.UUIDField()
    device = serializers.ChoiceField(choices=['mlx:0'], default='mlx:0')
    max_tokens = serializers.IntegerField(min_value=32, max_value=1024, default=512)


class SpecialistViewSet(TenantScopedViewSet):
    queryset = ModelVersion.objects.select_related('model', 'tokenizer').filter(
        architecture_ref__in=['modelanvil.laya.v1', 'modelanvil.ocr.v1']).exclude(state__in=['archived', 'rejected'])
    serializer_class = None
    http_method_names = ['get', 'post', 'head', 'options']

    def create(self, request):
        raise MethodNotAllowed('POST')

    def retrieve(self, request, pk=None):
        raise NotFound()

    def list(self, request):
        project_scope()
        return Response({'models': [{'id': str(v.model_version_id), 'name': v.model.name,
            'kind': v.metadata['format'], 'source': v.metadata['source'],
            'load_tested': v.inference_requests.filter(status='completed').exists()} for v in self.get_queryset()],
            'catalog': {k: specialists.import_plan(k) for k in specialists.PINS}})

    @action(detail=False, methods=['post'])
    def acquire(self, request):
        project = project_scope()
        form = AcquireInput(data=request.data); form.is_valid(raise_exception=True)
        value = form.validated_data
        pool = WorkerPool.all_objects.filter(pk=value['pool'], tenant_id=get_active_tenant()).first()
        if pool is None:
            raise serializers.ValidationError('Select an accessible model-import pool.')
        try:
            item = launch_import(specialists.import_plan(value['kind']), name=value['name'], tenant=get_active_tenant(),
                project=project, pool=pool, idempotency_key=value['idempotency_key'], accepted_license=value['accepted_license'])
        except (ValueError, IntegrityError) as exc:
            raise serializers.ValidationError(str(exc) if isinstance(exc, ValueError) else 'Model name or acquisition key already exists.') from None
        return Response({'import_id': str(item.import_id), 'job_id': str(item.job.job_id), 'status': item.status}, status=201)

    @action(detail=False, methods=['post'], url_path='upload-image')
    def upload_image(self, request):
        project = project_scope()
        file = request.data.get('file')
        if file is None or not hasattr(file, 'read') or not 0 < file.size <= 8 * 1024**2:
            raise serializers.ValidationError('Upload a PNG or JPEG of at most 8 MiB.')
        header = file.read(8); file.seek(0)
        if not (header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff')):
            raise serializers.ValidationError('Upload PNG or JPEG image bytes.')
        try:
            ref = _store(file, tenant=get_active_tenant(), project=project.pk, name='image', size=file.size,
                metadata={'kind': 'ocr_image'}, media_type='image/png' if header.startswith(b'\x89PNG') else 'image/jpeg')
        except (ValueError, OSError):
            raise serializers.ValidationError('Image upload failed.') from None
        return Response(ref, status=201)

    @action(detail=False, methods=['post'])
    def decisions(self, request):
        return self._infer(request, 'laya', DecisionInput)

    @action(detail=False, methods=['post'])
    def ocr(self, request):
        return self._infer(request, 'ocr', OcrInput)

    def _infer(self, request, kind, form_class):
        project = project_scope()
        form = form_class(data=request.data); form.is_valid(raise_exception=True)
        value = form.validated_data
        version = self.get_queryset().filter(model_version_id=value['model'], architecture_ref=f'modelanvil.{kind}.v1').first()
        if version is None:
            raise NotFound('Specialist model is unavailable in this project.')
        inputs = {k: value[k] for k in ('state', 'questions')} if kind == 'laya' else {'max_tokens': value['max_tokens']}
        image = None
        if kind == 'ocr':
            image = Artifact.all_objects.filter(artifact_id=value['image_artifact'], tenant_id=get_active_tenant()).first()
            if image is None or not check_resource_access(image, project.pk, get_active_tenant()):
                raise NotFound('Image is unavailable in this project.')
            if image.metadata.get('kind') != 'ocr_image':
                raise serializers.ValidationError('Upload the image through the OCR image endpoint.')
        identity = {'inputs': inputs, **({'image_sha256': image.sha256} if image else {})}
        record = InferenceRequest.all_objects.create(tenant_id=get_active_tenant(), project=project, model_version=version,
            principal_id=str(request.user.pk), input_digest=digest(identity), configuration={'kind': kind, 'device': value['device'],
                **({'max_tokens': value['max_tokens'], 'image_artifact': str(image.artifact_id)} if image else {})})
        try:
            result = specialists.execute(version, tenant=get_active_tenant(), project=project.pk,
                kind=kind, device=value['device'], inputs=inputs, image=image)
            result['request_id'] = str(record.request_id)
            if image:
                result['provenance']['image'] = {'artifact_id': str(image.artifact_id), 'sha256': image.sha256, 'byte_size': image.byte_size}
                self._save_ocr(result, image, version, record, project)
            InferenceRequest.all_objects.filter(pk=record.pk).update(status='completed', completed_at=timezone.now(),
                usage=result['usage'], elapsed_seconds=result['elapsed_seconds'], output_digest=digest(result))
            return Response(result)
        except Exception as exc:
            InferenceRequest.all_objects.filter(pk=record.pk).update(status='failed', completed_at=timezone.now())
            raise serializers.ValidationError(str(exc) if isinstance(exc, ValueError) else 'Specialist inference failed; check runtime compatibility.') from None

    @staticmethod
    @transaction.atomic
    def _save_ocr(result, image, version, record, project):
        source = result['provenance']
        identity = digest({'image': image.sha256, 'model': source['snapshot_sha256'], 'text': result['text']})
        envelope = {'schema_version': '1.0', 'sample_id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'ocr:{identity}')),
            'source_group_id': f'source-sha256:{image.sha256}',
            'blocks': [{'block_id': 'text', 'type': 'text', 'text': result['text'], 'location': {'source_path': 'image/1'}}],
            'provenance': {'source_snapshot_ref': f'sha256:{image.sha256}', 'source_record_key': 'image/1',
                'content_sha256': hashlib.sha256(result['text'].encode()).hexdigest(),
                'transformation_revision_ref': 'modelanvil.glm-ocr.v1'},
            'metadata': {'source_format': 'ocr', 'model': source, 'image_dimensions': result['image_dimensions'],
                         'normalization': 'exif_transpose_rgb', 'review_required': True}}
        payload = (json.dumps(envelope, ensure_ascii=False, allow_nan=False) + '\n').encode()
        ref = _store(io.BytesIO(payload), tenant=image.tenant_id, project=project.pk, name='ocr.jsonl',
            metadata={'kind': 'ocr_dataset_input', 'inference_request_id': str(record.request_id)}, media_type='application/x-ndjson')
        output = Artifact.all_objects.get(artifact_id=ref['artifact_id'], tenant_id=image.tenant_id)
        manifest = Artifact.all_objects.get(artifact_id=version.artifact_manifest_id, tenant_id=image.tenant_id)
        for parent, relation in ((image, 'ocr_text'), (manifest, 'ocr_model')):
            LineageEdge.all_objects.create(tenant_id=image.tenant_id, parent_artifact=parent, child_artifact=output,
                relation=relation, detail={'request_id': str(record.request_id), 'input_digest': record.input_digest})
        result.update(output_artifact=ref, envelope=envelope)
