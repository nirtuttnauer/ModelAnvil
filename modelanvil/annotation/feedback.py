"""Opt-in private application failures use the existing human review/publication path."""
import hashlib
import json
import logging
from datetime import timedelta
from django.db import transaction, IntegrityError
from django.db.models import Q, F
from django.utils import timezone
from modelanvil.annotation.models import ApplicationFeedback, ApplicationFeedbackPolicy, AnnotationRecord, AnnotationTask, LabelSchema, RubricRevision
from modelanvil.annotation.campaign_engine import CampaignEngine
from modelanvil.core.privacy import project_policy
from modelanvil.identity.models import check_resource_access, get_accessible_queryset
from modelanvil.runners.models import EvaluationSuiteVersion

DEVELOPMENT_ROLES = {'development','development_inspected','training_feedback_inspected'}


def fingerprint(tenant,value):
    return hashlib.sha256((str(tenant)+'\n'+value).encode()).hexdigest()


def prompt_fingerprint(tenant,value):
    return fingerprint(tenant,' '.join(value.casefold().split()))


def policy(project):
    row=ApplicationFeedbackPolicy.all_objects.filter(tenant_id=project.tenant_id,project=project).first()
    maximum=project_policy(project.tenant_id,project.pk)['measurement_retention_days']
    return {'enabled':bool(row and row.enabled),'collect_content':bool(row and row.collect_content),
        'retention_days':min(row.retention_days,maximum) if row else maximum,'privacy_maximum_days':maximum,
        'default_collection':'metadata_only','external_collection':False}


def protected_source(event,prompt=None):
    if event.origin_role=='final_test':return True
    if get_accessible_queryset(ApplicationFeedback,project_id=event.project_id,tenant_id=event.tenant_id).filter(origin_role='final_test',source_group_digest=event.source_group_digest).exists():return True
    for suite in get_accessible_queryset(EvaluationSuiteVersion,project_id=event.project_id,tenant_id=event.tenant_id).exclude(protected_role__in=DEVELOPMENT_ROLES):
        for case in suite.cases:
            if not isinstance(case,dict):continue
            if (case.get('source_group_id')==event.source_group_id
                    or event.prompt_digest and isinstance(case.get('input_prompt'),str) and prompt_fingerprint(event.tenant_id,case['input_prompt'])==event.prompt_digest):
                return True
    return False


def require_live(event):
    if event.deleted_at or event.expires_at<=timezone.now():raise ValueError('This feedback has expired or been deleted.')
    if protected_source(event):raise ValueError('Final-test cases and their source groups cannot enter training feedback.')
    if event.evaluation_suite_id and not check_resource_access(event.evaluation_suite,event.project_id,event.tenant_id):raise ValueError('The original evaluation source is no longer accessible.')
    if not check_resource_access(event.model_version,event.project_id,event.tenant_id):raise ValueError('The original model version is no longer accessible.')


def development_inspected_groups(tenant):
    groups=set()
    for suite in EvaluationSuiteVersion.all_objects.filter(tenant_id=tenant, protected_role='development_inspected'):
        for case in suite.cases or []:
            group=case.get('source_group_id') if isinstance(case, dict) else None
            if isinstance(group, str) and group.strip(): groups.add(group.strip())
    return groups


def assert_uninspected_cases(tenant,cases):
    if not isinstance(cases,list) or any(not isinstance(c,dict) for c in cases):raise ValueError('Supply a list of evaluation cases.')
    inspected=development_inspected_groups(tenant)
    if any(isinstance(c.get('source_group_id'), str) and c['source_group_id'].strip() in inspected for c in cases):
        raise ValueError('Development corrections and their source groups cannot be declared clean protected evaluation.')
    exposed=get_accessible_queryset(ApplicationFeedback,tenant_id=tenant)
    groups={fingerprint(tenant,c['source_group_id']) for c in cases if isinstance(c.get('source_group_id'),str) and c['source_group_id']}
    prompts={prompt_fingerprint(tenant,c.get('input_prompt','')) for c in cases if isinstance(c.get('input_prompt'),str) and c['input_prompt']}
    from modelanvil.rag.models import EmbeddingTrainingExposure
    embedding_exposure=get_accessible_queryset(EmbeddingTrainingExposure,tenant_id=tenant).filter(role='training')
    if embedding_exposure.filter(Q(source_group_digest__in=groups)|Q(prompt_digest__in=prompts)).exists():
        raise ValueError('Inspected embedding training text and source groups cannot be declared clean protected evaluation.')
    if exposed.filter(Q(source_group_digest__in=groups)|Q(prompt_digest__in=prompts)).exists():
        raise ValueError('Inspected application feedback and related source groups cannot be declared clean protected evaluation.')


@transaction.atomic
def ingest(*,project,principal,values,model,suite=None):
    from modelanvil.identity.models import Tenant
    Tenant.objects.select_for_update().get(pk=project.tenant_id)
    ApplicationFeedbackPolicy.all_objects.select_for_update().filter(tenant_id=project.tenant_id,project=project).first()
    current=policy(project)
    if not current['enabled']:raise ValueError('Application feedback collection is disabled in this project.')
    content=values.get('content');collected=bool(content)
    if collected and values['verdict']!='failure':raise ValueError('Content is collected only for observed development failures.')
    if collected and (not current['collect_content'] or not values.get('content_consent')):
        raise ValueError('Content requires project opt-in and explicit consent for this event.')
    if not collected and values.get('content_consent'):raise ValueError('Content consent must describe actual supplied content.')
    request_digest=hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    receipt=fingerprint(project.tenant_id,json.dumps([str(project.pk),values['application'],values['event_id']]))
    existing=ApplicationFeedback.all_objects.select_for_update().filter(tenant_id=project.tenant_id,project=project,receipt_key=receipt).first()
    if existing:
        if existing.request_digest!=request_digest:raise ValueError('This application event ID already identifies different feedback.')
        return existing,False
    if suite:
        case=next((c for c in suite.cases if c.get('case_id')==values.get('evaluation_case_id')),None)
        if not case or case.get('source_group_id')!=values['source_group_id']:
            raise ValueError('Select the original evaluation case and its exact source group.')
        if content and case.get('input_prompt')!=content['prompt']:
            raise ValueError('Feedback content must retain the selected case input unchanged.')
    event=ApplicationFeedback(tenant_id=project.tenant_id,project=project,receipt_key=receipt,request_digest=request_digest,
        application=values['application'],application_version=values['application_version'],source_id=values['source_id'],
        source_group_id=values['source_group_id'],source_group_digest=fingerprint(project.tenant_id,values['source_group_id']),
        prompt_digest=prompt_fingerprint(project.tenant_id,content['prompt']) if collected else '',model_version=model,
        rubric=values['rubric'],verdict=values['verdict'],origin_role=values['evaluation_role'],evaluation_role='development_inspected' if values['evaluation_role']=='development' else 'final_test',
        evaluation_suite=suite,evaluation_case_id=values.get('evaluation_case_id',''),content_collected=collected,
        consented_by=principal if collected else '',expires_at=timezone.now()+timedelta(days=current['retention_days']))
    if collected and protected_source(event):raise ValueError('Final-test content and related source groups cannot enter development feedback.')
    try:
        with transaction.atomic():event.save()
    except IntegrityError:
        existing=ApplicationFeedback.all_objects.get(tenant_id=project.tenant_id,project=project,receipt_key=receipt)
        if existing.request_digest!=request_digest:raise ValueError('This application event ID already identifies different feedback.')
        return existing,False
    if collected and event.verdict=='failure':
        name=f'Application feedback {event.feedback_id}'
        schema=LabelSchema.all_objects.create(tenant_id=project.tenant_id,name=name,kind='text_generation')
        rubric=RubricRevision.all_objects.create(tenant_id=project.tenant_id,name=name,guidelines_text=event.rubric)
        campaign=CampaignEngine().create_campaign(tenant_id=project.tenant_id,name=name,label_schema=schema,rubric=rubric,
            seed_mode='existing_model',active_drafting_model=model,max_cycles=1,
            configuration={'origin':'application_feedback','feedback_id':str(event.feedback_id),'draft_prompt':'{text}\n'})
        campaign.project=project;campaign.save(update_fields=['project','updated_at'])
        batch=CampaignEngine().start_batch(campaign,[{'id':str(event.feedback_id),'text':content['prompt'],
            'source_group_id':event.source_group_id,'evaluation_role':'development_inspected',
            'draft_prediction':{'predicted_label':content['prediction'],'model_version_id':str(model.model_version_id),
                'origin':'authorized_application_feedback'},'provenance':{'application':event.application,
                'application_version':event.application_version,'source_id':event.source_id,'feedback_id':str(event.feedback_id)}}])
        batch.status='reviewing';batch.save(update_fields=['status','updated_at'])
        event.campaign=campaign;event.evaluation_role='development_inspected';event.save(update_fields=['campaign','evaluation_role','updated_at'])
        if suite and suite.protected_role in DEVELOPMENT_ROLES:
            suite.protected_role='development_inspected';suite.save(update_fields=['protected_role','updated_at'])
    return event,True


def campaign_feedback(campaign):
    return ApplicationFeedback.all_objects.filter(tenant_id=campaign.tenant_id,campaign=campaign).first()


def require_campaign_live(campaign):
    event=campaign_feedback(campaign)
    if event:require_live(event)
    return event


def artifact_live(artifact):
    from modelanvil.artifacts.models import Artifact
    # A second registry row for the same storage object cannot strip expiry.
    ids=set(Artifact.all_objects.filter(tenant_id=artifact.tenant_id,storage_location_id=artifact.storage_location_id,
        object_key=artifact.object_key,metadata__has_key='application_feedback_id').values_list('metadata__application_feedback_id',flat=True))
    ids.discard(None)
    if isinstance(artifact.metadata,dict) and artifact.metadata.get('application_feedback_id'):ids.add(artifact.metadata['application_feedback_id'])
    for id in ids:
        event=ApplicationFeedback.all_objects.select_related('model_version').filter(tenant_id=artifact.tenant_id,feedback_id=id).first()
        if not event or event.project_id!=artifact.project_id:raise ValueError('Feedback artifact source is unavailable.')
        require_live(event)


def hidden_campaigns(tenant):
    return ApplicationFeedback.all_objects.filter(tenant_id=tenant).filter(Q(deleted_at__isnull=False)|Q(expires_at__lte=timezone.now())).exclude(campaign__isnull=True).values('campaign_id')


@transaction.atomic
def erase(event):
    event=ApplicationFeedback.all_objects.select_for_update().get(pk=event.pk)
    if event.deleted_at:
        if event.cleanup_pending:transaction.on_commit(lambda:cleanup_files(event))
        return
    artifacts=[]
    if event.campaign_id:
        campaign=event.campaign
        campaign.status='cancelled';campaign.save(update_fields=['status','updated_at'])
        for snapshot in campaign.snapshots.select_related('dataset_revision__manifest_artifact'):
            revision=snapshot.dataset_revision
            if revision:
                artifacts.append(revision.manifest_artifact)
                from modelanvil.artifacts.models import Artifact
                source=Artifact.all_objects.filter(tenant_id=event.tenant_id,artifact_id=revision.metadata.get('input_artifact_id')).first()
                if source:artifacts.append(source)
            type(snapshot).all_objects.filter(pk=snapshot.pk).update(items=[])
        AnnotationRecord.all_objects.filter(task__campaign=campaign).update(original_prediction={},human_label={})
        AnnotationTask.all_objects.filter(campaign=campaign).update(content={},status='skipped')
        # Rubrics may contain application-specific information; erase this owned copy.
        RubricRevision.all_objects.filter(pk=campaign.rubric_id).update(guidelines_text='Deleted application feedback rubric.')
    from modelanvil.artifacts.storage import artifact_storage_backend
    from modelanvil.artifacts.tombstones import register_tombstone
    for artifact in artifacts:
        register_tombstone(event.tenant_id,'artifact',str(artifact.artifact_id),reason='Application feedback content deletion')

    event.application=event.application_version=event.source_id=event.source_group_id=event.rubric=event.evaluation_case_id=''
    event.consented_by='';event.deleted_at=timezone.now();event.cleanup_pending=bool(artifacts);event.save()
    if artifacts:transaction.on_commit(lambda:cleanup_files(event))


def purge(project=None):
    events=ApplicationFeedback.all_objects.filter(Q(deleted_at__isnull=True,expires_at__lte=timezone.now())|Q(cleanup_pending=True))
    if project:events=events.filter(tenant_id=project.tenant_id,project=project)
    count=0
    for event in events.iterator():
        count+=int(event.deleted_at is None);erase(event)
    return count


def shorten_retention(project,days):
    ApplicationFeedback.all_objects.filter(tenant_id=project.tenant_id,project=project,deleted_at__isnull=True,
        expires_at__gt=F('created_at')+timedelta(days=days)).update(expires_at=F('created_at')+timedelta(days=days))


def cleanup_files(event):
    from modelanvil.artifacts.models import Artifact
    from modelanvil.artifacts.storage import artifact_storage_backend
    artifacts=[]
    if event.campaign_id:
        for snapshot in event.campaign.snapshots.select_related('dataset_revision__manifest_artifact'):
            if snapshot.dataset_revision_id:
                revision=snapshot.dataset_revision
                artifacts.append(revision.manifest_artifact)
                source=Artifact.all_objects.filter(tenant_id=event.tenant_id,artifact_id=revision.metadata.get('input_artifact_id')).first()
                if source:artifacts.append(source)
    try:
        for artifact in artifacts:artifact_storage_backend().delete(artifact.tenant_id,artifact.object_key)
    except Exception:
        logging.getLogger(__name__).warning('Application feedback physical erasure is pending retry.')
        return
    ApplicationFeedback.all_objects.filter(pk=event.pk,deleted_at__isnull=False).update(cleanup_pending=False)
