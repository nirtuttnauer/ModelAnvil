"""Publish bounded weighted corpora from accessible immutable prepared revisions."""
from decimal import Decimal
from django.db import IntegrityError
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from rest_framework.response import Response
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Project,Role
from modelanvil.core.tenancy import get_active_tenant,get_active_project
from modelanvil.artifacts.models import DatasetRevision
from modelanvil.data import continued_corpus as corpus

class ComponentInput(serializers.Serializer):
    revision_id=serializers.UUIDField()
    weight=serializers.DecimalField(max_digits=7,decimal_places=3,min_value=Decimal('0.001'),max_value=Decimal('1000'))
    def to_internal_value(self,data):
        if not isinstance(data,dict) or set(data)!=set(self.fields):raise serializers.ValidationError('Use only revision_id and weight.')
        return super().to_internal_value(data)

class CorpusInput(serializers.Serializer):
    name=serializers.CharField(max_length=180)
    components=ComponentInput(many=True,min_length=1,max_length=4)
    train_samples=serializers.IntegerField(min_value=1,max_value=1000)
    seed=serializers.CharField(max_length=128)
    def validate(self,value):
        if set(self.initial_data)!=set(self.fields):raise serializers.ValidationError('Submit name, components, train_samples and seed.')
        return value


def payload(revision):
    return {'id':revision.pk,'revision_id':str(revision.revision_id),'dataset':revision.dataset_id,'name':revision.dataset.name,
        'manifest_digest':revision.manifest_digest,'recipe_digest':revision.recipe_digest,'row_count':revision.row_count,
        'split_counts':revision.metadata['split_counts'],'recipe':revision.metadata['recipe'],'state':revision.state}

class ContinuedCorpora(APIView):
    permission_classes=[IsAuthenticated,TenantRBAC]
    def initial(self,request,*args,**kwargs):
        self.required_role=Role.VIEWER if request.method=='GET' else Role.ENGINEER
        return super().initial(request,*args,**kwargs)
    def get(self,request):
        rows=DatasetRevision.all_objects.select_related('dataset','manifest_artifact').filter(tenant_id=get_active_tenant(),project_id=get_active_project(),metadata__preparation_kind=corpus.VERSION).order_by('-created_at')[:50]
        results=[]
        for row in rows:
            try:corpus.pins(row,get_active_tenant(),get_active_project())
            except ValueError:continue
            results.append(payload(row))
        response=Response({'results':results});response['Cache-Control']='no-store';return response
    def post(self,request):
        form=CorpusInput(data=request.data);form.is_valid(raise_exception=True)
        project=Project.all_objects.filter(pk=get_active_project(),tenant_id=get_active_tenant()).first()
        if project is None:raise serializers.ValidationError('Select a project to publish a corpus.')
        try:revision=corpus.publish(project=project,**form.validated_data)
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from None
        except IntegrityError:raise serializers.ValidationError('Corpus name already exists; choose another name or use its current revision.') from None
        response=Response(payload(revision),status=201);response['Cache-Control']='no-store';return response
