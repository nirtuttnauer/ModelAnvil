"""Authorized, opt-in project feedback; review uses the existing Annotation workspace."""
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.api.views.specialists import StrictInput, project_scope
from modelanvil.annotation import feedback as workflow
from modelanvil.annotation.models import ApplicationFeedback, ApplicationFeedbackPolicy
from modelanvil.core.models import record_audit
from modelanvil.identity.models import Role, get_accessible_queryset, role_at_least
from modelanvil.runners.models import ModelVersion, EvaluationSuiteVersion


class ContentInput(StrictInput):
    prompt=serializers.CharField(max_length=16000,trim_whitespace=False)
    prediction=serializers.CharField(max_length=16000,trim_whitespace=False,allow_blank=True)
    def validate(self,data):
        if sum(len(v.encode()) for v in data.values())>32768:raise serializers.ValidationError('Feedback content supports at most 32 KiB.')
        return data


class FeedbackInput(StrictInput):
    application=serializers.CharField(max_length=128)
    application_version=serializers.CharField(max_length=128)
    event_id=serializers.CharField(max_length=128)
    model_version=serializers.UUIDField()
    source_id=serializers.CharField(max_length=128)
    source_group_id=serializers.CharField(max_length=128)
    rubric=serializers.CharField(max_length=2000)
    verdict=serializers.ChoiceField(choices=['success','failure'])
    evaluation_role=serializers.ChoiceField(choices=['development','final_test'])
    evaluation_suite=serializers.UUIDField(required=False)
    evaluation_case_id=serializers.CharField(max_length=128,required=False)
    authorized=serializers.BooleanField()
    content_consent=serializers.BooleanField(default=False)
    content=ContentInput(required=False)
    def validate(self,data):
        if not data['authorized']:raise serializers.ValidationError('Confirm authorization to import this application feedback.')
        if bool(data.get('evaluation_suite'))!=bool(data.get('evaluation_case_id')):raise serializers.ValidationError('Supply both the evaluation suite and original case ID.')
        return data


class PolicyInput(StrictInput):
    enabled=serializers.BooleanField()
    collect_content=serializers.BooleanField()
    retention_days=serializers.IntegerField(min_value=1,max_value=365)


class FeedbackSerializer(serializers.ModelSerializer):
    campaign_id=serializers.UUIDField(source='campaign.campaign_id',read_only=True,allow_null=True)
    review_state=serializers.SerializerMethodField()
    def get_review_state(self,event):
        if event.deleted_at:return 'deleted'
        if event.expires_at<=timezone.now():return 'expired'
        if workflow.protected_source(event):return 'protected'
        if event.campaign_id:return 'review_candidate' if event.campaign.status=='active' else event.campaign.status
        return 'metadata_only'
    def to_representation(self,event):
        data=super().to_representation(event)
        if event.deleted_at or event.expires_at<=timezone.now():
            for key in ['application','application_version','source_id','source_group_id','rubric','evaluation_case_id']:data[key]=''
            data['campaign_id']=None
        return data
    class Meta:
        model=ApplicationFeedback
        fields=('feedback_id','application','application_version','source_id','source_group_id','rubric','verdict',
            'origin_role','evaluation_role','evaluation_case_id','content_collected','campaign_id','review_state','expires_at','deleted_at','cleanup_pending','created_at')
        read_only_fields=fields


class ApplicationFeedbackViewSet(TenantScopedViewSet):
    queryset=ApplicationFeedback.objects.select_related('campaign','model_version')
    serializer_class=FeedbackSerializer
    lookup_field='feedback_id'
    http_method_names=['get','post','delete','head','options']
    action_write_roles={'policy':Role.ADMIN,'purge':Role.ADMIN,'destroy':Role.ADMIN}
    def finalize_response(self,request,response,*args,**kwargs):
        response=super().finalize_response(request,response,*args,**kwargs);response['Cache-Control']='private, no-store';return response
    def get_queryset(self):
        return super().get_queryset().filter(project=project_scope())
    def create(self,request,*args,**kwargs):
        form=FeedbackInput(data=request.data);form.is_valid(raise_exception=True);values=form.validated_data;project=project_scope()
        model=get_accessible_queryset(ModelVersion).filter(model_version_id=values['model_version']).first()
        suite=get_accessible_queryset(EvaluationSuiteVersion).filter(suite_version_id=values.get('evaluation_suite')).first() if values.get('evaluation_suite') else None
        if not model or values.get('evaluation_suite') and not suite:raise NotFound()
        try:event,created=workflow.ingest(project=project,principal=str(request.modelanvil_actor_id),values=values,model=model,suite=suite)
        except ValueError as exc:raise serializers.ValidationError(str(exc)) from exc
        record_audit('create','application_feedback',event.feedback_id,input_snapshot={'content_collected':event.content_collected,'deduplicated':not created})
        response=Response(self.get_serializer(event).data,status=201 if created else 200);response['Cache-Control']='no-store';return response
    @action(detail=False,methods=['get','post'])
    @transaction.atomic
    def policy(self,request):
        project=project_scope()
        if request.method=='POST':
            form=PolicyInput(data=request.data);form.is_valid(raise_exception=True)
            maximum=workflow.policy(project)['privacy_maximum_days']
            if form.validated_data['retention_days']>maximum:raise serializers.ValidationError('Feedback retention cannot exceed the project privacy retention period.')
            ApplicationFeedbackPolicy.all_objects.update_or_create(tenant_id=project.tenant_id,project=project,defaults=form.validated_data)
            workflow.shorten_retention(project,form.validated_data['retention_days'])
            record_audit('update','application_feedback_policy',project.pk,input_snapshot=form.validated_data)
        return Response({**workflow.policy(project),'can_administer':role_at_least(request.modelanvil_role,Role.ADMIN)})
    def destroy(self,request,*args,**kwargs):
        event=self.get_object();workflow.erase(event)
        record_audit('delete','application_feedback',event.feedback_id,input_snapshot={'content_erased':True})
        event.refresh_from_db();return Response({'feedback_id':str(event.feedback_id),'cleanup_pending':event.cleanup_pending})
    @action(detail=False,methods=['post'])
    def purge(self,request):
        if request.data!={'confirm':'delete_expired_feedback'}:raise serializers.ValidationError('Confirm delete_expired_feedback, including its owned review and published source artifacts.')
        project=project_scope();count=workflow.purge(project);record_audit('delete','expired_application_feedback',project.pk,input_snapshot={'count':count})
        return Response({'deleted_feedback':count})
