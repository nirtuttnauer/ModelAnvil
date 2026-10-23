"""Real HTTP feedback consent, existing human review/publication, erasure and leakage gates."""
from datetime import timedelta
import tempfile
from pathlib import Path
from django.conf import settings
from django.test import TestCase, TransactionTestCase, override_settings, tag
from django.utils import timezone
from rest_framework.test import APIClient
from modelanvil.core.tenancy import reset_context
from modelanvil.identity.models import Tenant, Team, Project, ApiKey, Role, generate_api_key
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion, EvaluationSuite, EvaluationSuiteVersion
from modelanvil.annotation.models import ApplicationFeedback, AnnotationRecord, CumulativeSnapshot, AnnotationTask
from modelanvil.api.resource_inspection import prepared_manifest
from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend


@override_settings(ALLOWED_HOSTS=['testserver'])
class ApplicationFeedbackTests(TestCase):
    def setUp(self):
        reset_context();self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        override=override_settings(MODELANVIL={**settings.MODELANVIL,'artifact_root':self.directory.name});override.enable();self.addCleanup(override.disable)
        self.tenant=Tenant.objects.create(slug='feedback',name='Feedback')
        team=Team.all_objects.create(tenant_id=self.tenant.pk,slug='team',name='Team')
        self.project=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,slug='one',name='One')
        self.other=Project.all_objects.create(tenant_id=self.tenant.pk,team=team,slug='two',name='Two')
        tokenizer=TokenizerVersion.all_objects.create(tenant_id=self.tenant.pk,name='Registered fixture tokenizer')
        model=Model.all_objects.create(tenant_id=self.tenant.pk,name='Registered application model')
        self.model=ModelVersion.all_objects.create(tenant_id=self.tenant.pk,project=self.project,model=model,tokenizer=tokenizer,architecture_ref='fixture',revision_no=1)
        secret,hashed=generate_api_key();self.key=ApiKey.objects.create(tenant=self.tenant,role=Role.OWNER,name='Owner',secret_hash=hashed)
        self.client=APIClient();self.auth='Bearer '+secret;self.scope(self.project)
        self.url='/api/v1/application-feedback/'

    def scope(self,project):self.client.credentials(HTTP_AUTHORIZATION=self.auth,HTTP_X_PROJECT_ID=str(project.pk))
    def policy(self,**changes):
        response=self.client.post(self.url+'policy/',{'enabled':True,'collect_content':True,'retention_days':7,**changes},format='json')
        self.assertEqual(response.status_code,200,response.content);return response.json()
    def payload(self,**changes):
        return {'application':'Private QA app','application_version':'1.0','event_id':'event-one','model_version':str(self.model.model_version_id),
            'source_id':'original-source','source_group_id':'development-group','rubric':'Answer the given question accurately.',
            'verdict':'failure','evaluation_role':'development','authorized':True,'content_consent':True,
            'content':{'prompt':'What is two plus two?','prediction':'The answer is five.'},**changes}
    def ingest(self,**changes):
        response=self.client.post(self.url,self.payload(**changes),format='json');self.assertEqual(response.status_code,201,response.content)
        return ApplicationFeedback.all_objects.get(feedback_id=response.json()['feedback_id'])
    def review_publish(self,event):
        task=AnnotationTask.all_objects.get(campaign=event.campaign)
        response=self.client.post(f'/api/v1/annotation-tasks/{task.task_id}/review/',{'decision':'corrected','human_label':{'label':'The answer is four.'},'expected_revision':1},format='json')
        self.assertEqual(response.status_code,201,response.content)
        response=self.client.post(f'/api/v1/labeling-batches/{task.batch.batch_id}/close/',{},format='json')
        self.assertEqual(response.status_code,200,response.content)
        return CumulativeSnapshot.all_objects.get(campaign=event.campaign)
    def suite(self,role='protected_eval',group='protected-group',prompt='Unseen protected input'):
        suite=EvaluationSuite.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Suite '+str(EvaluationSuite.all_objects.count()))
        return EvaluationSuiteVersion.all_objects.create(tenant_id=self.tenant.pk,project=self.project,suite=suite,cases=[{
            'case_id':'case-one','source_group_id':group,'input_prompt':prompt,'expected_output':'expected'}],cases_count=1,protected_role=role)

    def test_disabled_default_metadata_only_and_per_event_consent(self):
        self.assertFalse(self.client.get(self.url+'policy/').json()['enabled'])
        self.assertEqual(self.client.post(self.url,self.payload(),format='json').status_code,400)
        self.policy(collect_content=False)
        self.assertEqual(self.client.post(self.url,self.payload(),format='json').status_code,400)
        values=self.payload(content_consent=False);values.pop('content')
        response=self.client.post(self.url,values,format='json');self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['review_state'],'metadata_only');self.assertEqual(AnnotationTask.all_objects.count(),0)
        self.policy();self.assertEqual(self.client.post(self.url,self.payload(event_id='two',content_consent=False),format='json').status_code,400)
        self.assertEqual(self.client.post(self.url,self.payload(event_id='two',authorized=False),format='json').status_code,400)

    def test_original_prediction_preserved_and_only_correction_publishes_immutable_training(self):
        self.policy();event=self.ingest();task=AnnotationTask.all_objects.get(campaign=event.campaign)
        self.assertEqual(task.content['draft_prediction']['predicted_label'],'The answer is five.')
        self.assertEqual(CumulativeSnapshot.all_objects.count(),0)
        response=self.client.post(f'/api/v1/annotation-tasks/{task.task_id}/review/',{'decision':'accepted_without_edit','human_label':{'label':'The answer is five.'},'expected_revision':1},format='json')
        self.assertEqual(response.status_code,400)
        snapshot=self.review_publish(event);record=AnnotationRecord.all_objects.get(task=task)
        self.assertEqual(record.original_prediction['predicted_label'],'The answer is five.')
        self.assertEqual(record.human_label['label'],'The answer is four.')
        manifest=prepared_manifest(snapshot.dataset_revision)
        self.assertEqual(len(manifest['rows']),1);self.assertEqual(len(manifest['split_manifest']['train']),1)
        text=manifest['rows'][0]['blocks'][0]['text'];self.assertIn('The answer is four.',text);self.assertNotIn('The answer is five.',text)
        self.assertEqual(manifest['rows'][0]['source_group_id'],event.source_group_id)
        event.refresh_from_db();self.assertEqual(event.evaluation_role,'training_feedback_inspected')
        snapshot.dataset_revision.metadata={'changed':True}
        with self.assertRaises(ValueError):snapshot.dataset_revision.save()

    def test_deduplicate_conflicts_scope_and_role(self):
        self.policy();event=self.ingest()
        response=self.client.post(self.url,self.payload(),format='json');self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(ApplicationFeedback.all_objects.count(),1);self.assertEqual(AnnotationTask.all_objects.count(),1)
        self.assertEqual(self.client.post(self.url,self.payload(rubric='changed'),format='json').status_code,400)
        self.scope(self.other);self.assertEqual(self.client.get(self.url+str(event.feedback_id)+'/').status_code,404)
        self.policy();self.assertEqual(self.client.post(self.url,self.payload(),format='json').status_code,404)
        self.scope(self.project);self.key.role=Role.REVIEWER;self.key.save(update_fields=['role'])
        self.assertEqual(self.client.post(self.url+'policy/',{'enabled':True,'collect_content':True,'retention_days':7},format='json').status_code,403)
        self.assertEqual(self.client.post(self.url,self.payload(event_id='different'),format='json').status_code,403)

    def test_protected_case_group_and_prompt_are_excluded_and_exposure_cannot_be_clean_again(self):
        self.policy();protected=self.suite()
        for changes in [{'source_group_id':'protected-group'},{'content':{'prompt':'Unseen protected input','prediction':'bad'}},{'evaluation_role':'final_test'}]:
            self.assertEqual(self.client.post(self.url,self.payload(**changes),format='json').status_code,400)
        development=self.suite('development',group='development-group',prompt='What is two plus two?')
        event=self.ingest(evaluation_suite=str(development.suite_version_id),evaluation_case_id='case-one')
        development.refresh_from_db();self.assertEqual(development.protected_role,'development_inspected')
        snapshot=self.review_publish(event);development.refresh_from_db();self.assertEqual(development.protected_role,'training_feedback_inspected')
        # Existing clean-evaluation registration must refuse the inspected group.
        response=self.client.post('/api/v1/evaluation-suites/register-cpu/',{'name':'False clean suite','cases':development.cases,'protected_role':'protected_eval'},format='json')
        self.assertEqual(response.status_code,400,response.content)
        with self.captureOnCommitCallbacks(execute=True):self.client.delete(self.url+str(event.feedback_id)+'/')
        response=self.client.post('/api/v1/evaluation-suite-versions/',{'suite':protected.pk,'revision_no':2,'cases':development.cases,'protected_role':'protected_eval'},format='json')
        self.assertEqual(response.status_code,400,response.content)

    def test_expiry_withholds_review_artifact_and_training_before_physical_purge(self):
        self.policy();event=self.ingest();snapshot=self.review_publish(event);revision=snapshot.dataset_revision
        artifact=revision.manifest_artifact
        ApplicationFeedback.all_objects.filter(pk=event.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get(f'/api/v1/labeling-campaigns/{event.campaign.campaign_id}/').status_code,404)
        self.assertEqual(self.client.get(f'/api/v1/artifacts/{artifact.artifact_id}/download/').status_code,404)
        with self.assertRaises(ValueError):prepared_manifest(revision)
        # An alternate row pointing at the same object cannot shed its expiry.
        forged=Artifact.all_objects.create(tenant_id=event.tenant_id,project=self.project,storage_location_id=artifact.storage_location_id,
            object_key=artifact.object_key,sha256=artifact.sha256,byte_size=artifact.byte_size,media_type=artifact.media_type,state='committed')
        self.assertEqual(self.client.get(f'/api/v1/artifacts/{forged.artifact_id}/download/').status_code,404)
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(self.url+'purge/',{'confirm':'delete_expired_feedback'},format='json')
        self.assertEqual(response.status_code,200,response.content);self.assertEqual(response.json()['deleted_feedback'],1)
        artifact.refresh_from_db();self.assertEqual(artifact.state,'tombstoned')
        with self.assertRaises(FileNotFoundError):artifact_storage_backend().open(artifact.tenant_id,artifact.object_key)
        self.assertEqual(AnnotationRecord.all_objects.get(task__campaign=event.campaign).original_prediction,{})
        self.assertEqual(AnnotationTask.all_objects.get(campaign=event.campaign).content,{})
        snapshot.refresh_from_db();self.assertEqual(snapshot.items,[])
        event.refresh_from_db();self.assertEqual(event.source_group_id,'');self.assertTrue(event.source_group_digest)

    def test_policy_shortens_existing_retention_without_extending_it(self):
        self.policy();event=self.ingest();original=event.expires_at
        self.policy(retention_days=1);event.refresh_from_db();self.assertLess(event.expires_at,original)
        shortened=event.expires_at;self.policy(retention_days=20);event.refresh_from_db();self.assertEqual(event.expires_at,shortened)

    def test_storage_erasure_failure_remains_pending_and_can_be_retried(self):
        from unittest.mock import patch
        self.policy();event=self.ingest();snapshot=self.review_publish(event)
        with patch('modelanvil.artifacts.storage.LocalArtifactStorage.delete',side_effect=OSError('controlled unavailable storage')):
            with self.captureOnCommitCallbacks(execute=True):response=self.client.delete(self.url+str(event.feedback_id)+'/')
        self.assertEqual(response.status_code,200,response.content);event.refresh_from_db();self.assertTrue(event.cleanup_pending)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url+'purge/',{'confirm':'delete_expired_feedback'},format='json')
        event.refresh_from_db();self.assertFalse(event.cleanup_pending)
        with self.assertRaises(FileNotFoundError):artifact_storage_backend().open(event.tenant_id,snapshot.dataset_revision.manifest_artifact.object_key)

    def test_declared_final_group_cannot_reenter_training_under_a_new_event_id(self):
        self.policy();values=self.payload(evaluation_role='final_test',content_consent=False);values.pop('content')
        self.assertEqual(self.client.post(self.url,values,format='json').status_code,201)
        self.assertEqual(self.client.post(self.url,self.payload(event_id='changed-role'),format='json').status_code,400)
        response=self.client.post('/api/v1/evaluation-suites/register-cpu/',{'name':'False clean metadata group','cases':[{
            'case_id':'one','source_group_id':'development-group','input_prompt':'unseen prompt','expected_output':'ok'}],
            'protected_role':'protected_eval'},format='json')
        self.assertEqual(response.status_code,400,response.content)

    def test_empty_original_prediction_is_preserved_as_an_observed_failure(self):
        self.policy();event=self.ingest(content={'prompt':'A real model returned no text.','prediction':''})
        task=AnnotationTask.all_objects.get(campaign=event.campaign)
        self.assertEqual(task.content['draft_prediction']['predicted_label'],'')
        self.review_publish(event)


@tag('pg')
@override_settings(ALLOWED_HOSTS=['testserver'])
class ApplicationFeedbackConcurrencyTests(TransactionTestCase):
    setUp=ApplicationFeedbackTests.setUp
    scope=ApplicationFeedbackTests.scope
    policy=ApplicationFeedbackTests.policy
    payload=ApplicationFeedbackTests.payload

    def concurrent(self,functions):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        barrier=Barrier(len(functions))
        def run(fn):
            close_old_connections();reset_context()
            client=APIClient();client.credentials(HTTP_AUTHORIZATION=self.auth,HTTP_X_PROJECT_ID=str(self.project.pk))
            try:barrier.wait();return fn(client)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=len(functions)) as executor:return list(executor.map(run,functions))

    def test_concurrent_retries_create_one_receipt_and_review_candidate(self):
        self.policy()
        codes=self.concurrent([lambda c:c.post(self.url,self.payload(),format='json').status_code]*2)
        self.assertEqual(sorted(codes),[200,201]);self.assertEqual(ApplicationFeedback.all_objects.count(),1)
        self.assertEqual(AnnotationTask.all_objects.count(),1)

    def test_concurrent_inspection_and_clean_registration_cannot_both_commit(self):
        self.policy()
        body={'name':'Concurrent clean case','cases':[{'case_id':'case-one','source_group_id':'development-group',
            'input_prompt':'What is two plus two?','expected_output':'four'}],'protected_role':'protected_eval'}
        codes=self.concurrent([lambda c:c.post(self.url,self.payload(),format='json').status_code,
            lambda c:c.post('/api/v1/evaluation-suites/register-cpu/',body,format='json').status_code])
        self.assertEqual(sorted(codes),[201,400])
