"""Owned-project document sessions; all content is reauthorized on every read/run."""
from contextlib import contextmanager
from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.core.ids import uuid7
from modelanvil.core.tenancy import get_active_project,get_active_tenant
from modelanvil.identity.models import Project,get_accessible_queryset
from modelanvil.rag.models import ResearchSession,KnowledgeBase,SourceDocument
from modelanvil.rag import attachments,research,decoder
from modelanvil.runners.models import ModelVersion,InferenceRequest
from modelanvil.runners.training.runtime import digest

class CreateInput(serializers.Serializer):
    title=serializers.CharField(max_length=180)
    model_version=serializers.UUIDField()

class RevisionInput(serializers.Serializer):
    revision_no=serializers.IntegerField(min_value=1)

class AskInput(RevisionInput):
    question=serializers.CharField(max_length=8192,trim_whitespace=False)
    max_tokens=serializers.IntegerField(min_value=1,max_value=128,default=64)
    memory_tokens=serializers.IntegerField(min_value=64,max_value=512,default=256)


def validated(form,data):
    form=form(data=data)
    if set(data)-set(form.fields):raise serializers.ValidationError('Unsupported research request fields.')
    form.is_valid(raise_exception=True);return form.validated_data

class ResearchViewSet(TenantScopedViewSet):
    queryset=ResearchSession.objects.select_related('project','knowledge_base','model_version','index')
    serializer_class=CreateInput
    lookup_field='session_id'
    http_method_names=['get','post','head','options']

    def get_queryset(self):
        return super().get_queryset().filter(project_id=get_active_project())

    def list(self,request):
        project=Project.all_objects.filter(pk=get_active_project(),tenant_id=get_active_tenant()).first()
        if project is None:raise serializers.ValidationError('Select a project for document research.')
        return Response({'sessions':[{'session_id':str(s.session_id),'title':s.title,'revision_no':s.revision_no}
            for s in self.get_queryset().order_by('-updated_at')[:50]],
            'models':[{'id':str(m.model_version_id),'name':m.model.name} for m in get_accessible_queryset(ModelVersion).select_related('model').filter(
                metadata__source__rag_decoder_profile=digest(decoder.PINS)).exclude(state__in=['archived','rejected'])],
            'limits':research.LIMITS})

    def retrieve(self,request,session_id=None):return Response(research.payload(self.get_object()))

    @transaction.atomic
    def create(self,request):
        value=validated(CreateInput,request.data)
        project=Project.all_objects.filter(pk=get_active_project(),tenant_id=get_active_tenant()).first()
        model=get_accessible_queryset(ModelVersion).filter(model_version_id=value['model_version'],
            metadata__source__rag_decoder_profile=digest(decoder.PINS)).exclude(state__in=['archived','rejected']).first()
        if project is None or model is None:raise serializers.ValidationError('Select a project and its provisioned pinned CPU RAG decoder. Use the existing RAG decoder setup command to provision it locally.')
        base=KnowledgeBase.all_objects.create(tenant_id=project.tenant_id,project=project,name='Research '+str(uuid7()))
        session=ResearchSession.all_objects.create(tenant_id=project.tenant_id,project=project,model_version=model,
            title=value['title'],knowledge_base=base)
        return Response(research.payload(session),status=201)

    @contextmanager
    def edit(self,data):
        with transaction.atomic():
            session=self.get_queryset().select_for_update(of=('self',)).get(pk=self.get_object().pk)
            value=validated(RevisionInput,{'revision_no':data.get('revision_no')})
            if value['revision_no']!=session.revision_no:
                from modelanvil.core.exceptions import WorkflowConflict
                raise WorkflowConflict('This session changed; reload before continuing.')
            try:yield session
            except ValueError as exc:raise serializers.ValidationError(str(exc)) from None

    @action(detail=True,methods=['post'])
    def attach(self,request,session_id=None):
        if set(request.data)-{'file','revision_no'}:raise serializers.ValidationError('Submit only file and revision_no.')
        file=request.data.get('file')
        if not hasattr(file,'read') or file.size>1024**2:raise serializers.ValidationError('Attach one PDF/DOCX or UTF-8 code/text file up to1MiB.')
        with self.edit(request.data) as session:
            text,metadata=attachments.extract(file.read(1024**2+1),file.name)
            result=research.attach(session,[{'title':file.name[:180],'source_uri':'attachment:'+str(uuid7()),'content':text,'metadata':metadata}])
        return Response(result)

    @action(detail=True,methods=['post'],url_path='attach-ocr')
    def attach_ocr(self,request,session_id=None):
        if set(request.data)!={'revision_no','request_id'}:raise serializers.ValidationError('Submit revision_no and a completed OCR request_id.')
        identifier=serializers.UUIDField().run_validation(request.data['request_id'])
        with self.edit(request.data) as session:
            record=get_accessible_queryset(InferenceRequest).select_related('model_version').filter(request_id=identifier,project=session.project).first()
            if record is None:raise NotFound()
            text,metadata=attachments.ocr(record)
            result=research.attach(session,[{'title':'Qualified OCR '+str(identifier),'source_uri':'ocr:'+str(identifier),'content':text,'metadata':metadata}])
        return Response(result)

    @action(detail=True,methods=['post'])
    def fetch(self,request,session_id=None):
        if set(request.data)!={'revision_no','urls'}:raise serializers.ValidationError('Submit revision_no and1–2 reviewed URLs.')
        urls=serializers.ListField(child=serializers.CharField(max_length=2048),min_length=1,max_length=2).run_validation(request.data['urls'])
        with self.edit(request.data) as session:result=research.pages(session,urls)
        return Response(result)

    @action(detail=True,methods=['post'])
    def ask(self,request,session_id=None):
        value=validated(AskInput,request.data)
        with self.edit(value) as session:
            result=research.ask(session,**{k:v for k,v in value.items() if k!='revision_no'})
        return Response(result,status=201)

    @action(detail=True,methods=['post'],url_path='clear-memory')
    def clear_memory(self,request,session_id=None):
        validated(RevisionInput,request.data)
        with self.edit(request.data) as session:
            session.turns=[];session.memory={};session.revision_no+=1;session.save()
            result=research.payload(session)
        return Response(result)

    @action(detail=True,methods=['post'],url_path='remove-source')
    def remove_source(self,request,session_id=None):
        if set(request.data)!={'revision_no','document_id'}:raise serializers.ValidationError('Submit revision_no and document_id.')
        key=serializers.UUIDField().run_validation(request.data['document_id'])
        with self.edit(request.data) as session:
            doc=SourceDocument.all_objects.filter(knowledge_base=session.knowledge_base,doc_id=key,tenant_id=session.tenant_id).first()
            if doc is None:raise NotFound()
            doc.is_deleted=True;doc.save(update_fields=['is_deleted','updated_at'])
            session.revision_no+=1;session.save();result=research.payload(session)
        return Response(result)
