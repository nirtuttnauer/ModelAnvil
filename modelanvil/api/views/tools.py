"""Project-scoped durable tool chats and protected execution evidence."""
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
from modelanvil.core.privacy import project_policy
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.jobs.models import Job,WorkerPool
from modelanvil.runners.models import ModelVersion,InferenceRequest
from modelanvil.runners.inference import copy_verified
from modelanvil.runners import tool_jobs as tools,tool_runtime as runtime,mcp_connections as mcp,tool_sandbox


class ToolInput(StrictInput):
    model=serializers.UUIDField()
    prompt=serializers.CharField(max_length=2048)
    max_tokens=serializers.IntegerField(min_value=1,max_value=128,default=128)
    targets=serializers.ListField(child=serializers.UUIDField(),max_length=3,default=list)
    code_execution=serializers.BooleanField(default=False)
    pool=serializers.IntegerField(min_value=1)
    budget_policy=serializers.UUIDField()
    idempotency_key=serializers.CharField(max_length=128)


class ToolsViewSet(TenantScopedViewSet):
    queryset=ModelVersion.objects.all()
    http_method_names=['get','post','head','options']

    def create(self,request):raise MethodNotAllowed('POST')
    def retrieve(self,request,pk=None):raise MethodNotAllowed('GET')

    def list(self,request):
        project=project_scope();models=[]
        for version in self.get_queryset().filter(architecture_ref=runtime.RUNTIME_ID).select_related('model','tokenizer'):
            try:runtime.candidate_bundle(version,get_active_tenant(),project.pk);runtime.require_packages()
            except (ValueError,KeyError,TypeError,OSError):continue
            models.append({'id':str(version.model_version_id),'name':version.model.name,'source':runtime.SOURCE,'production_qualified':False})
        policy=project_policy(get_active_tenant(),project.pk)
        try:sandbox={'available':True,**tool_sandbox.available()}
        except (ValueError,OSError):sandbox={'available':False,'reason':'Provision the pinned Python image on the local Linux Docker engine.'}
        return Response({'models':models,'limits':runtime.LIMITS,'installed_mcp_targets':policy['installed_mcp_targets'],
            'mcp_targets':policy['mcp_targets'],'code_execution':policy['code_execution'],'sandbox':sandbox,
            'scope':'Exact Qwen3 FP32 CPU native tools. Reviewed read-only MCP and disposable offline Python only. Customer quality and other models require qualification.'})

    @action(detail=False,methods=['post'])
    def discover(self,request):
        project=project_scope()
        if set(request.data)!={'target'}:raise serializers.ValidationError('Submit one installed target UUID.')
        identifier=serializers.UUIDField().run_validation(request.data['target'])
        try:result=mcp.discover(str(identifier),get_active_tenant(),project.pk)
        except (ValueError,OSError) as exc:raise serializers.ValidationError(str(exc)) from None
        result.pop('configuration_signature',None);return Response(result)

    @action(detail=False,methods=['get','post'])
    def jobs(self,request):
        project=project_scope()
        if request.method=='GET':
            rows=get_accessible_queryset(InferenceRequest).filter(configuration__kind=tools.TYPE).order_by('-created_at')[:20]
            return Response([{'request_id':str(r.request_id),'job_id':r.configuration['job_id'],'status':r.status,'created_at':r.created_at} for r in rows])
        form=ToolInput(data=request.data);form.is_valid(raise_exception=True);value=form.validated_data
        version=self.get_queryset().filter(model_version_id=value['model']).first()
        pool=WorkerPool.all_objects.filter(pk=value['pool'],tenant_id=get_active_tenant()).first()
        if version is None or pool is None:raise NotFound('Tool model or worker pool is unavailable.')
        try:record=tools.queue(tenant=get_active_tenant(),project=project,principal=request.user.pk,version=version,prompt=value['prompt'],
            max_tokens=value['max_tokens'],targets=[str(i) for i in value['targets']],code=value['code_execution'],pool=pool,policy_id=value['budget_policy'],key=value['idempotency_key'])
        except (ValueError,IntegrityError) as exc:raise serializers.ValidationError(str(exc) if isinstance(exc,ValueError) else 'Admission key is already in use.') from None
        return Response({'request_id':str(record.request_id),'job_id':record.configuration['job_id'],'status':record.status},status=202)

    def record(self,identifier):
        try:identifier=uuid.UUID(identifier)
        except (ValueError,TypeError):raise NotFound() from None
        record=get_accessible_queryset(InferenceRequest).filter(request_id=identifier,configuration__kind=tools.TYPE).first()
        if record is None:raise NotFound()
        return record

    @action(detail=False,methods=['get'],url_path=r'jobs/(?P<request_id>[^/.]+)')
    def job_status(self,request,request_id=None):
        record=self.record(request_id);job=Job.all_objects.get(tenant_id=record.tenant_id,job_id=record.configuration['job_id'])
        return Response({'request_id':str(record.request_id),'job_id':str(job.job_id),'status':job.status,'desired_action':job.desired_action,
            'attempt_count':job.attempt_count,'usage':record.usage,'trace':record.configuration.get('trace',[]),'trace_artifact':record.configuration.get('trace_artifact'),
            'answer':record.configuration.get('answer','') if record.status=='completed' else '',
            'error':'The bounded tool chat did not complete. Review the retained trace, permissions and worker profile.' if job.status=='failed' else ''})

    @action(detail=False,methods=['get'],url_path=r'jobs/(?P<request_id>[^/.]+)/trace')
    def trace_file(self,request,request_id=None):
        record=self.record(request_id);ref=record.configuration.get('trace_artifact')
        if ref is None:raise serializers.ValidationError('The terminal trace is not available yet.')
        raw=io.BytesIO()
        try:copy_verified(ref,record.tenant_id,record.project_id,raw)
        except (ValueError,OSError):raise serializers.ValidationError('Trace artifact failed verification.') from None
        raw.seek(0);response=FileResponse(raw,as_attachment=True,filename='tool-trace.json',content_type='application/json')
        response['Cache-Control']='no-store';return response

    @action(detail=False,methods=['post'],url_path=r'jobs/(?P<request_id>[^/.]+)/cancel')
    def cancel_job(self,request,request_id=None):
        try:job=tools.cancel(self.record(request_id))
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from None
        return Response({'status':job.status,'desired_action':job.desired_action})


class NativeCompletionInput(StrictInput):
    model=serializers.UUIDField()
    messages=serializers.JSONField()
    tools=serializers.JSONField(default=list)
    tool_choice=serializers.ChoiceField(choices=['auto','none','required'],default='auto')
    max_tokens=serializers.IntegerField(min_value=1,max_value=128,default=128)
    temperature=serializers.ChoiceField(choices=[0],default=0)
    stream=serializers.ChoiceField(choices=[False],default=False)
    budget_policy=serializers.UUIDField()

    def validate(self,attrs):
        attrs=super().validate(attrs)
        from modelanvil.runners import tool_completion,tool_schema
        try:
            tool_schema.tools(attrs['tools']);attrs['messages']=tool_completion.messages(attrs['messages'],attrs['tools'])
            runtime.native_input(attrs['messages'],[] if attrs['tool_choice']=='none' else attrs['tools'],attrs['max_tokens'])
            if attrs['tool_choice']=='required' and not attrs['tools']:raise ValueError('Required tool choice needs offered functions.')
        except (ValueError,TypeError,KeyError) as exc:raise serializers.ValidationError(str(exc)) from None
        return attrs


def compatible_completion(view,request,project):
    from modelanvil.runners import tool_completion
    form=NativeCompletionInput(data=request.data);form.is_valid(raise_exception=True);value=form.validated_data
    version=view.get_queryset().filter(model_version_id=value['model'],architecture_ref=runtime.RUNTIME_ID).first()
    if version is None:raise NotFound('The native tool model is unavailable in this project.')
    key=request.headers.get('Idempotency-Key','')
    if not 1<=len(key)<=128:raise serializers.ValidationError('Use an Idempotency-Key header of1–128 characters.')
    try:
        record,replayed=tool_completion.reserve(tenant=get_active_tenant(),project=project,principal=request.user.pk,version=version,
            value=value,key=key,policy_id=value['budget_policy'])
        if replayed:
            if record.status=='completed':return Response(record.configuration['response'])
            return Response({'request_id':str(record.request_id),'status':record.status,'detail':'This key is already admitted. Use a new key after a failed request.'},status=409)
        def authorized():
            from modelanvil.identity.auth import ApiKeyAuthentication,TenantRBAC
            try:
                principal=ApiKeyAuthentication().authenticate(request)
                return principal is not None and principal[0].pk==request.user.pk and TenantRBAC().has_permission(request,view)
            except Exception:return False
        result=tool_completion.execute(record,authorized)
    except (ValueError,IntegrityError) as exc:raise serializers.ValidationError(str(exc) if isinstance(exc,ValueError) else 'This admission key is already in use.') from None
    return Response(result)
