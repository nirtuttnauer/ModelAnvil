"""Project-scoped pinned CPU embeddings and durable pgvector build requests."""
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from django.db import IntegrityError

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.api.views.specialists import project_scope, StrictInput
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.jobs.models import WorkerPool
from modelanvil.rag.models import EmbeddingSpace, EmbeddingBuild, IndexVersion, EmbeddingCandidate
from modelanvil.rag import embedding_adapter as adapter, embedding_jobs as builds
from modelanvil.runners.training.runtime import digest


class SpaceSerializer(serializers.ModelSerializer):
    class Meta:
        model=EmbeddingSpace
        fields=('space_id','name','model_name','model_revision','license_expression','dimension','normalized','distance_metric','metadata')
        read_only_fields=fields


class SpaceInput(StrictInput):
    name=serializers.CharField(max_length=200)
    accepted_license=serializers.ChoiceField(choices=['apache-2.0'])


class EncodeInput(StrictInput):
    texts=serializers.ListField(child=serializers.CharField(trim_whitespace=False,max_length=32768),min_length=1,max_length=16)


class BuildInput(StrictInput):
    source_index=serializers.UUIDField()
    space=serializers.UUIDField()
    pool=serializers.IntegerField(min_value=1)
    budget_policy=serializers.UUIDField()
    idempotency_key=serializers.CharField(max_length=128)


class EmbeddingSpaceViewSet(TenantScopedViewSet):
    queryset=EmbeddingSpace.objects.exclude(model_revision='')
    serializer_class=SpaceSerializer
    lookup_field='space_id'
    http_method_names=['get','post','head','options']

    def create(self,request,*args,**kwargs):
        incoming=SpaceInput(data=request.data);incoming.is_valid(raise_exception=True)
        project=project_scope()
        try:
            adapter.environment();adapter.verified_directory()
            if EmbeddingSpace.all_objects.filter(tenant_id=get_active_tenant(),name=incoming.validated_data['name']).exists():
                raise ValueError('Choose a unique embedding space name in this workspace.')
            space=EmbeddingSpace.all_objects.create(tenant_id=get_active_tenant(),project=project,name=incoming.validated_data['name'],
                model_name=adapter.PINS['model'],model_revision=adapter.PINS['revision'],license_expression=adapter.PINS['license'],
                dimension=adapter.PINS['dimension'],normalized=True,distance_metric='cosine',
                metadata={'profile_digest':digest(adapter.PINS),'runtime':builds.runtime_digest(),'device':'cpu','hardware_qualified':False})
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from exc
        except IntegrityError:raise serializers.ValidationError('Choose a unique embedding space name in this workspace.') from None
        return Response(self.get_serializer(space).data,status=201)

    @action(detail=False,methods=['get'])
    def profile(self,request):
        reason='';available=True
        try:adapter.environment();adapter.verified_directory()
        except ValueError as exc:available=False;reason=str(exc)
        return Response({'model':adapter.PINS['model'],'revision':adapter.PINS['revision'],'license':adapter.PINS['license'],
            'dimension':adapter.PINS['dimension'],'normalized':True,'device':'cpu','max_content_tokens':254,
            'batch_size':adapter.BATCH_SIZE,'max_index_chunks':adapter.MAX_CHUNKS,'available':available,'reason':reason,
            'network_inference':False,'hardware_qualified':False})

    @action(detail=True,methods=['post'])
    def encode(self,request,space_id=None):
        space=self.get_object();incoming=EncodeInput(data=request.data);incoming.is_valid(raise_exception=True)
        try:
            pins=builds.space_pins(space)
            matrix=adapter.encode_space(incoming.validated_data['texts'],space)
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from exc
        return Response({'space':str(space.space_id),'pins':pins,'vectors':matrix.tolist(),
            'runtime':builds.runtime_digest(),'unit':'normalized_float32_vector','device':'cpu'})


class BuildSerializer(serializers.ModelSerializer):
    job_id=serializers.UUIDField(source='job.job_id',read_only=True)
    index_id=serializers.UUIDField(source='index.index_id',read_only=True)
    source_index_id=serializers.UUIDField(source='source_index.index_id',read_only=True)
    job_status=serializers.CharField(source='job.status',read_only=True)
    index_status=serializers.CharField(source='index.status',read_only=True)
    total_chunks=serializers.IntegerField(source='index.chunks_count',read_only=True)
    class Meta:
        model=EmbeddingBuild
        fields=('build_id','job_id','index_id','source_index_id','job_status','index_status','completed_chunks','total_chunks','error','created_at','updated_at')
        read_only_fields=fields


class EmbeddingBuildViewSet(TenantScopedViewSet):
    queryset=EmbeddingBuild.objects.select_related('job','index','source_index')
    serializer_class=BuildSerializer
    lookup_field='build_id'
    http_method_names=['get','post','head','options']

    def create(self,request,*args,**kwargs):
        incoming=BuildInput(data=request.data);incoming.is_valid(raise_exception=True);v=incoming.validated_data
        project=project_scope();tenant=get_active_tenant()
        source=get_accessible_queryset(IndexVersion).filter(index_id=v['source_index'],knowledge_base__in=get_accessible_queryset(IndexVersion._meta.get_field('knowledge_base').related_model)).first()
        space=get_accessible_queryset(EmbeddingSpace).filter(space_id=v['space']).first()
        pool=WorkerPool.all_objects.filter(pk=v['pool'],tenant_id=tenant).first()
        if not source or not space or not pool:raise NotFound()
        try:build=builds.queue(source=source,space=space,project=project,principal=request.modelanvil_actor_id,pool=pool,policy_id=v['budget_policy'],key=v['idempotency_key'])
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from exc
        return Response(self.get_serializer(build).data,status=202)

    @action(detail=True,methods=['post'])
    def cancel(self,request,build_id=None):
        build=self.get_object()
        try:builds.cancel(build)
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from exc
        build.refresh_from_db();return Response(self.get_serializer(build).data)

    @action(detail=True,methods=['post'])
    def retry(self,request,build_id=None):
        build=self.get_object()
        try:builds.retry(build)
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from exc
        build.refresh_from_db();return Response(self.get_serializer(build).data,status=202)


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model=EmbeddingCandidate
        fields=('candidate_id','space','source','export','source_digest','export_digest','protocol','report','created_at')
        read_only_fields=fields


class EmbeddingCandidateViewSet(TenantScopedViewSet):
    queryset=EmbeddingCandidate.objects.all()
    serializer_class=CandidateSerializer
    lookup_field='candidate_id'
    http_method_names=['get','head','options']
