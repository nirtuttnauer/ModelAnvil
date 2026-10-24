"""Project-scoped bounded speech jobs and verified playable output."""
import io
import uuid
from django.db import IntegrityError
from django.http import FileResponse
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound,MethodNotAllowed
from rest_framework.response import Response
from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.api.views.specialists import StrictInput,project_scope
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.jobs.models import Job,WorkerPool
from modelanvil.runners.models import ModelVersion,InferenceRequest
from modelanvil.runners import audio_generation as audio
from modelanvil.runners.inference import copy_verified
from modelanvil.runners.model_catalog import _store


class GenerateInput(StrictInput):
    model=serializers.UUIDField()
    text=serializers.CharField(max_length=96)
    seed=serializers.IntegerField(min_value=0,max_value=2147483647,default=42)
    max_seconds=serializers.IntegerField(min_value=1,max_value=6,default=6)
    pool=serializers.IntegerField(min_value=1)
    budget_policy=serializers.UUIDField()
    idempotency_key=serializers.CharField(max_length=128)


class AudioViewSet(TenantScopedViewSet):
    queryset=ModelVersion.objects.select_related('model','tokenizer','processor').filter(architecture_ref=audio.runtime.RUNTIME_ID).exclude(state__in=('archived','rejected'))
    serializer_class=None
    http_method_names=['get','post','head','options']

    def create(self,request):raise MethodNotAllowed('POST')
    def retrieve(self,request,pk=None):raise NotFound()

    def list(self,request):
        project=project_scope();models=[]
        for version in self.get_queryset():
            try:plan=audio.candidate_bundle(version,get_active_tenant(),project.pk)
            except (ValueError,KeyError,TypeError,OSError):continue
            models.append({'id':str(version.model_version_id),'name':version.model.name,'trained':plan['trained'],
                'source':audio.runtime.SOURCE,'processor_id':str(version.processor.processor_id),'production_qualified':False})
        return Response({'models':models,'profile':audio.runtime.PROCESSOR,
            'quality_scope':'English TTS with fixed published demo conditioning. Human/customer quality is unqualified; ASR and voice cloning require separate profiles.'})

    @action(detail=False,methods=['post'],url_path='upload-audio')
    def upload_audio(self,request):
        project=project_scope();file=request.data.get('file')
        if file is None or not hasattr(file,'read') or not 0<file.size<=4*1024**2:raise serializers.ValidationError('Upload a PCM16 WAV/FLAC of at most4MiB.')
        raw=file.read(4*1024**2+1);media='audio/flac' if raw.startswith(b'fLaC') else 'audio/wav'
        try:
            _,pin=audio.runtime.math.decode_audio(raw,media)
            ref=_store(io.BytesIO(raw),tenant=get_active_tenant(),project=project.pk,name='source.flac' if media=='audio/flac' else 'source.wav',
                media_type=media,metadata={'kind':'speech_source','normalization':pin})
        except (ValueError,OSError):raise serializers.ValidationError('Audio decoding failed or the source exceeds the supported profile.') from None
        return Response({'artifact':ref,'normalization':pin},status=201)

    @action(detail=False,methods=['get','post'])
    def jobs(self,request):
        project=project_scope()
        if request.method=='GET':
            records=get_accessible_queryset(InferenceRequest).filter(configuration__kind=audio.TYPE).order_by('-created_at')[:20]
            return Response([{'request_id':str(r.request_id),'job_id':r.configuration['job_id'],'status':r.status,'created_at':r.created_at} for r in records])
        form=GenerateInput(data=request.data);form.is_valid(raise_exception=True);value=form.validated_data
        version=self.get_queryset().filter(model_version_id=value['model']).first()
        pool=WorkerPool.all_objects.filter(pk=value['pool'],tenant_id=get_active_tenant()).first()
        if version is None or pool is None:raise NotFound('Speech model or worker pool is unavailable.')
        try:
            record=audio.queue(tenant=get_active_tenant(),project=project,principal=request.user.pk,version=version,
                text=value['text'],seed=value['seed'],max_seconds=value['max_seconds'],pool=pool,policy_id=value['budget_policy'],key=value['idempotency_key'])
        except (ValueError,IntegrityError) as exc:
            raise serializers.ValidationError(str(exc) if isinstance(exc,ValueError) else 'This admission key is already in use.') from None
        return Response({'request_id':str(record.request_id),'job_id':record.configuration['job_id'],'status':record.status},status=202)

    def record(self,identifier):
        try:identifier=uuid.UUID(identifier)
        except (ValueError,TypeError):raise NotFound() from None
        record=get_accessible_queryset(InferenceRequest).filter(request_id=identifier,configuration__kind=audio.TYPE).first()
        if record is None:raise NotFound()
        return record

    @action(detail=False,methods=['get'],url_path=r'jobs/(?P<request_id>[^/.]+)')
    def job_status(self,request,request_id=None):
        record=self.record(request_id);job=Job.all_objects.get(job_id=record.configuration['job_id'],tenant_id=record.tenant_id)
        attempt=job.attempts.first()
        try:result=audio.read_result(record) if job.status=='succeeded' else None
        except (ValueError,OSError,TypeError,KeyError):raise serializers.ValidationError('Speech output is unavailable or failed verification.') from None
        return Response({'request_id':str(record.request_id),'job_id':str(job.job_id),'status':job.status,'desired_action':job.desired_action,
            'attempt_count':job.attempt_count,'progress':attempt.progress if attempt else 0,'usage':record.usage,'result':result,
            'error':'Speech did not produce a complete verified WAV; inspect worker and qualification evidence.' if job.status=='failed' else ''})

    @action(detail=False,methods=['get'],url_path=r'jobs/(?P<request_id>[^/.]+)/audio')
    def output_audio(self,request,request_id=None):
        record=self.record(request_id)
        if record.status!='completed':raise serializers.ValidationError('Speech is not complete.')
        try:
            result=audio.read_result(record);raw=io.BytesIO();copy_verified(result['audio'],record.tenant_id,record.project_id,raw);raw.seek(0)
        except (ValueError,OSError,TypeError,KeyError):raise serializers.ValidationError('Speech output failed verification.') from None
        response=FileResponse(raw,content_type='audio/wav',as_attachment=request.query_params.get('download')=='1',filename='speech.wav')
        response['ETag']='"'+result['audio']['sha256']+'"';return response

    @action(detail=False,methods=['post'],url_path=r'jobs/(?P<request_id>[^/.]+)/cancel')
    def cancel_job(self,request,request_id=None):
        try:job=audio.cancel(self.record(request_id))
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from None
        return Response({'status':job.status,'desired_action':job.desired_action})
