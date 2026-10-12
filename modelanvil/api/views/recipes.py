"""Immutable recipe import/export and bounded preview/full durable executions."""
import uuid

from django.db import IntegrityError
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, MethodNotAllowed
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.api.views.specialists import StrictInput, project_scope
from modelanvil.artifacts.models import Artifact, Dataset
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.data.models import RecipeRun
from modelanvil.data import recipe_jobs
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.jobs.models import WorkerPool
from modelanvil.runners.model_catalog import _store
from modelanvil.runners.models import ModelVersion
from modelanvil.runners.training.hf_runtime import file_ref


class RunInput(StrictInput):
    recipe = serializers.UUIDField()
    sources = serializers.DictField(child=serializers.UUIDField())
    model = serializers.UUIDField(required=False)
    device = serializers.ChoiceField(choices=['cpu','mps:0','mlx:0'],default='cpu')
    pool = serializers.IntegerField(min_value=1)
    budget_policy = serializers.UUIDField()
    idempotency_key = serializers.CharField(max_length=128)
    preview = serializers.BooleanField(default=True)
    dataset = serializers.UUIDField(required=False)
    preview_run = serializers.UUIDField(required=False)
    protected_sources = serializers.ListField(child=serializers.UUIDField(),max_length=4,default=list)
    reviewed_preview = serializers.BooleanField(default=False)

    def validate_sources(self, value):
        if not 1 <= len(value) <= 4:
            raise serializers.ValidationError('Select 1–4 source artifacts.')
        return value


def accessible(model, **lookup):
    item=get_accessible_queryset(model).filter(**lookup).first()
    if item is None:raise NotFound('Resource is unavailable in this project.')
    return item


class RecipeViewSet(TenantScopedViewSet):
    queryset = Artifact.objects.filter(metadata__kind='recipe_version',state='committed')
    serializer_class = None
    http_method_names = ['get','post','head','options']

    def retrieve(self,request,pk=None):raise NotFound()

    def list(self,request):
        project_scope()
        return Response([{'artifact_id':str(a.artifact_id),'name':a.metadata['name'],'sha256':a.sha256,
            'created_at':a.created_at} for a in self.get_queryset().order_by('-created_at')[:50]])

    def create(self,request):
        project=project_scope()
        try:ref=recipe_jobs.save_version(request.data,get_active_tenant(),project.pk)
        except (ValueError,TypeError,KeyError,RecursionError) as exc:
            raise serializers.ValidationError(str(exc) if isinstance(exc,ValueError) else 'Invalid typed recipe graph.') from None
        return Response(ref,status=201)

    @action(detail=False,methods=['get'],url_path=r'versions/(?P<version_id>[^/.]+)')
    def version(self,request,version_id=None):
        try:identifier=uuid.UUID(version_id)
        except ValueError:raise NotFound() from None
        artifact=self.get_queryset().filter(artifact_id=identifier).first()
        if artifact is None:raise NotFound()
        try:definition=recipe_jobs.read_json(file_ref(artifact),artifact.tenant_id,artifact.project_id,64000)
        except ValueError:raise serializers.ValidationError('Recipe bytes failed verification.') from None
        return Response({'artifact':file_ref(artifact),'definition':definition})

    @action(detail=False,methods=['post'],url_path='upload-source')
    def upload_source(self,request):
        project=project_scope();file=request.data.get('file');kind=request.data.get('format')
        from modelanvil.data.source_import import MEDIA_TYPES
        if kind not in {'jsonl',*MEDIA_TYPES} or file is None or not hasattr(file,'read') or not 0<file.size<=16*1024**2:
            raise serializers.ValidationError('Choose supported source bytes of at most 16 MiB.')
        try:ref=_store(file,tenant=get_active_tenant(),project=project.pk,name=f'recipe-source.{kind}',size=file.size,
            media_type={'jsonl':'application/x-ndjson',**MEDIA_TYPES}[kind],metadata={'kind':'recipe_source','source_format':kind})
        except (OSError,ValueError):raise serializers.ValidationError('Source upload failed.') from None
        return Response(ref,status=201)

    @action(detail=False,methods=['get','post'])
    def runs(self,request):
        project=project_scope()
        if request.method=='GET':
            return Response([{'run_id':str(r.run_id),'job_id':str(r.job.job_id),'name':r.recipe.metadata['name'],
                'status':r.status,'preview':r.frozen['preview']} for r in get_accessible_queryset(RecipeRun).select_related('job','recipe').order_by('-created_at')[:30]])
        form=RunInput(data=request.data);form.is_valid(raise_exception=True);v=form.validated_data
        if not v['preview'] and not v['reviewed_preview']:
            raise serializers.ValidationError('Review the matching preview before full execution.')
        pool=WorkerPool.all_objects.filter(pk=v['pool'],tenant_id=get_active_tenant()).first()
        policy=BudgetPolicy.all_objects.filter(policy_id=v['budget_policy'],tenant_id=get_active_tenant()).first()
        if pool is None or policy is None:raise NotFound()
        try:
            run=recipe_jobs.queue(tenant=get_active_tenant(),project=project,principal=request.user.pk,
                recipe=accessible(Artifact,artifact_id=v['recipe']),sources={k:accessible(Artifact,artifact_id=a) for k,a in v['sources'].items()},
                model=accessible(ModelVersion,model_version_id=v['model']) if v.get('model') else None,
                device=v['device'],pool=pool,policy=policy,key=v['idempotency_key'],preview=v['preview'],
                dataset=accessible(Dataset,dataset_id=v['dataset']) if v.get('dataset') else None,
                preview_run=accessible(RecipeRun,run_id=v['preview_run']) if v.get('preview_run') else None,
                protected=[accessible(Artifact,artifact_id=a) for a in v['protected_sources']])
        except (ValueError,IntegrityError,TypeError,KeyError) as exc:
            raise serializers.ValidationError(str(exc) if isinstance(exc,ValueError) else 'Recipe admission failed.') from None
        return Response({'run_id':str(run.run_id),'job_id':str(run.job.job_id),'status':run.status,'preview':run.frozen['preview']},status=202)

    @action(detail=False,methods=['get'],url_path=r'runs/(?P<run_id>[^/.]+)')
    def run_status(self,request,run_id=None):
        try:run=accessible(RecipeRun,run_id=uuid.UUID(run_id))
        except ValueError:raise NotFound() from None
        job=run.job;attempt=job.attempts.first()
        result=recipe_jobs.read_json(run.result['report'],run.tenant_id,run.project_id) if job.status=='succeeded' else None
        if result:result={**result,'rows':result['rows'][:20],'rejected':result['rejected'][:20]}
        return Response({'run_id':str(run.run_id),'job_id':str(job.job_id),'status':job.status,'desired_action':job.desired_action,
            'definition':recipe_jobs.read_json(run.frozen['recipe'],run.tenant_id,run.project_id,64000),
            'bindings':{'recipe':str(run.recipe.artifact_id),'sources':{k:v['artifact_id'] for k,v in run.frozen['sources'].items()},
                'model':str(run.model_version.model_version_id) if run.model_version else None,'device':run.frozen['device'],
                'pool':run.frozen['pool'],'budget_policy':run.frozen['budget_policy'],'protected_sources':[r['artifact_id'] for r in run.frozen['protected']]},
            'attempt_count':job.attempt_count,'max_attempts':job.max_attempts,'preview':run.frozen['preview'],
            'completed_steps':[k for k in run.checkpoints if '/' not in k and k!='$result'],
            'saved_rows':sum('/' in k for k in run.checkpoints),'publication':run.result,'result':result,
            'error':attempt.error if attempt and job.status=='failed' else ''})

    @action(detail=False,methods=['post'],url_path=r'runs/(?P<run_id>[^/.]+)/cancel')
    def cancel_run(self,request,run_id=None):
        return self._action(run_id,recipe_jobs.cancel)

    @action(detail=False,methods=['post'],url_path=r'runs/(?P<run_id>[^/.]+)/retry')
    def retry_run(self,request,run_id=None):
        return self._action(run_id,recipe_jobs.retry)

    def _action(self,run_id,operation):
        try:run=accessible(RecipeRun,run_id=uuid.UUID(run_id))
        except ValueError:raise NotFound() from None
        try:job=operation(run)
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from None
        return Response({'status':job.status,'desired_action':job.desired_action})
