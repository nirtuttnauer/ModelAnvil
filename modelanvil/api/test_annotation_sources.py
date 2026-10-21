import json
from django.test import TestCase
from modelanvil.api import test_annotation as labeling
from modelanvil.runners.training import test_cpu_runtime as cpu
from modelanvil.annotation.models import AnnotationRecord, AnnotationTask
from modelanvil.artifacts.models import Artifact, Dataset
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import ApiKey, Team, Project, Role


class AnnotationSourceTests(TestCase):
    setUp = cpu.CpuRuntimeTests.setUp
    artifact = cpu.CpuRuntimeTests.artifact
    envelope = cpu.CpuRuntimeTests.envelope

    def campaign(self):
        response = self.client.post('/api/v1/labeling-campaigns/', {'name': 'Pinned labels', 'kind': 'classification',
            'classes': ['a', 'b'], 'source_revision': str(self.dataset.revision_id), 'max_cycles': 2}, format='json')
        self.assertEqual(response.status_code, 201, response.data); return response.data

    def test_source_selection_review_and_publication_preserve_exact_provenance(self):
        campaign = self.campaign()
        response = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {'limit': 1}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        batch = response.data
        tasks = self.client.get(f'/api/v1/labeling-batches/{batch["batch_id"]}/tasks/').data['results']
        task = tasks[0]
        self.assertEqual(task['content']['source_revision'], str(self.dataset.revision_id))
        reviewed = self.client.post(f'/api/v1/annotation-tasks/{task["task_id"]}/review/', {
            'decision': 'corrected', 'human_label': {'label': 'a'}, 'expected_revision': 1, 'blind_review': True}, format='json')
        self.assertEqual(reviewed.status_code, 201, reviewed.data)
        closed = self.client.post(f'/api/v1/labeling-batches/{batch["batch_id"]}/close/', {}, format='json')
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertTrue(closed.data['dataset_revision_id'])
        inspection = self.client.get(f'/api/v1/dataset-revisions/{closed.data["dataset_revision_id"]}/inspect/').data
        self.assertEqual(inspection['total'], 1); self.assertEqual(inspection['rows'][0]['metadata']['label'], 'a')
        self.assertEqual(inspection['rows'][0]['source_group_id'], task['content']['source_group_id'])
        second = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {'limit': 1}, format='json')
        self.assertEqual(second.status_code, 201, second.data)
        next_task = self.client.get(f'/api/v1/labeling-batches/{second.data["batch_id"]}/tasks/').data['results'][0]
        self.assertNotEqual(next_task['sample_ref'], task['sample_ref'])
        self.assertEqual(self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {'samples': [{'id':'fake','text':'data'}]}, format='json').status_code, 409)

    def test_protected_audit_source_groups_are_excluded_entirely(self):
        rows = [self.envelope(i, text) for i, text in enumerate(['ab', 'cd', 'ef'])]
        rows[1]['source_group_id'] = rows[0]['source_group_id']
        source = self.artifact('protected.jsonl', b''.join(json.dumps(r).encode()+b'\n' for r in rows), 'application/x-ndjson')
        self.dataset = publish_prepared_dataset(self.dataset.dataset, source, validation_percent=0, test_percent=0)
        response = self.client.post('/api/v1/labeling-campaigns/', {'name': 'Protected groups', 'kind': 'classification',
            'classes': ['a','b'], 'source_revision': str(self.dataset.revision_id), 'audit_sample_refs':[rows[0]['sample_id']]}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        batch = self.client.post(f'/api/v1/labeling-campaigns/{response.data["campaign_id"]}/batches/', {'limit': 10}, format='json')
        self.assertEqual(batch.status_code, 201, batch.data)
        tasks = self.client.get(f'/api/v1/labeling-batches/{batch.data["batch_id"]}/tasks/').data['results']
        self.assertEqual([t['sample_ref'] for t in tasks], [rows[2]['sample_id']])

    def test_pinned_text_source_is_rejected_before_creating_preference_campaign(self):
        campaign = self.client.post('/api/v1/labeling-campaigns/', {
            'name': 'Pinned preference', 'kind': 'preference_ranking', 'classes': [],
            'source_revision': str(self.dataset.revision_id),
        }, format='json')
        self.assertEqual(campaign.status_code, 400, campaign.content)
        self.assertIn('both candidate', str(campaign.content))
        self.assertFalse(AnnotationTask.all_objects.exists())


class AnnotationAdjudicationTests(TestCase):
    setUp = labeling.LabelingApiTests.setUp
    auth_client = labeling.LabelingApiTests.auth_client
    campaign = labeling.LabelingApiTests.campaign
    batch = labeling.LabelingApiTests.batch
    review = labeling.LabelingApiTests.review
    close = labeling.LabelingApiTests.close

    def assert_blind_task(self, task, source='A source'):
        for field in ('draft_prediction', 'arena_vote', 'comparison_origin'):
            self.assertNotIn(field, task['content'])
        self.assertEqual(task['content']['text'], source)
        self.assert_blind_record(task['latest_review'])

    def assert_blind_record(self, record):
        self.assertEqual(record['human_label'], {})
        self.assertEqual(record['original_prediction'], {})
        self.assertEqual(record['preference_choice'], '')
        self.assertGreater(record['revision_no'], 0)

    def test_blind_redaction_reaches_every_task_and_history_response(self):
        campaign = self.campaign(kind='preference_ranking', classes=[])
        batch, tasks = self.batch(campaign, [{'id': 'one', 'text': 'A source', 'candidate_a': 'A', 'candidate_b': 'B'}])
        task = AnnotationTask.objects.get(task_id=tasks[0]['task_id'])
        prediction = {'predicted_label': 'candidate_a', 'confidence': .9}
        task.content.update(draft_prediction=prediction, arena_vote={'choice': 'candidate_a'}, comparison_origin={'winner': 'A'})
        task.save(update_fields=['content'])
        self.assertEqual(self.review(tasks[0], label='candidate_b').status_code, 201)
        path = f'/api/v1/annotation-tasks/{task.task_id}/'

        for url, collection in ((path, False), ('/api/v1/annotation-tasks/', True),
                                (f'/api/v1/labeling-batches/{batch["batch_id"]}/tasks/', True)):
            with self.subTest(url=url):
                response = self.client.get(f'{url}?blind=1')
                self.assertEqual(response.status_code, 200, response.content)
                self.assert_blind_task(response.data['results'][0] if collection else response.data)

        history = self.client.get(f'{path}history/?blind=1')
        self.assertEqual(history.status_code, 200, history.content)
        self.assert_blind_record(history.data['results'][0])
        assigned = self.client.post(f'{path}assignment/?blind=1', {'reviewer': ''}, format='json')
        self.assertEqual(assigned.status_code, 200, assigned.content)
        self.assert_blind_task(assigned.data)
        escalated = self.client.post(f'{path}escalate/?blind=1', {'reason': 'Independent review needed'}, format='json')
        self.assertEqual(escalated.status_code, 200, escalated.content)
        self.assert_blind_task(escalated.data)

        visible = self.client.get(path).data
        self.assertEqual(visible['content']['draft_prediction'], prediction)
        self.assertEqual(visible['latest_review']['human_label'], {'label': 'candidate_b'})
        self.assertEqual(visible['latest_review']['preference_choice'], 'candidate_b')
        self.assertEqual(visible['latest_review']['original_prediction'], prediction)
        task.refresh_from_db()
        self.assertEqual(task.content['arena_vote'], {'choice': 'candidate_a'})

    def test_blind_review_by_body_or_query_redacts_response_and_preserves_record(self):
        campaign = self.campaign(kind='preference_ranking', classes=[])
        _, tasks = self.batch(campaign, [
            {'id': 'one', 'text': 'A source', 'candidate_a': 'A', 'candidate_b': 'B'},
            {'id': 'two', 'text': 'Other source', 'candidate_a': 'C', 'candidate_b': 'D'},
        ])
        for task, query, body in ((tasks[0], '', {'blind_review': True}), (tasks[1], '?blind=1', {})):
            with self.subTest(query=query, body=body):
                stored_task = AnnotationTask.objects.get(task_id=task['task_id'])
                prediction = {'predicted_label': 'candidate_a', 'confidence': .9}
                stored_task.content.update(draft_prediction=prediction, arena_vote={'choice': 'candidate_a'}, comparison_origin={'winner': 'A'})
                stored_task.save(update_fields=['content'])
                response = self.client.post(f'/api/v1/annotation-tasks/{task["task_id"]}/review/{query}', {
                    'decision': 'corrected', 'human_label': {'label': 'candidate_b'}, 'expected_revision': 1, **body,
                }, format='json')
                self.assertEqual(response.status_code, 201, response.content)
                self.assert_blind_task(response.data, task['content']['text'])
                record = AnnotationRecord.objects.get(task__task_id=task['task_id'])
                self.assertTrue(record.is_blind_review)
                self.assertEqual(record.human_label, {'label': 'candidate_b'})
                self.assertEqual(record.preference_choice, 'candidate_b')
                self.assertEqual(record.original_prediction, prediction)

    def test_blind_accept_is_rejected_without_creating_a_review(self):
        campaign = self.campaign()
        _, tasks = self.batch(campaign, [{'id': 'one', 'text': 'A source'}])
        task = AnnotationTask.objects.get(task_id=tasks[0]['task_id'])
        task.content['draft_prediction'] = {'predicted_label': 'positive'}
        task.save(update_fields=['content'])
        for query, body in (('', {'blind_review': True}), ('?blind=1', {})):
            response = self.client.post(f'/api/v1/annotation-tasks/{task.task_id}/review/{query}', {
                'decision': 'accepted_without_edit', 'human_label': {'label': 'positive'}, 'expected_revision': 1, **body,
            }, format='json')
            self.assertEqual(response.status_code, 400, response.content)
            self.assertFalse(task.records.exists())

    def test_escalation_requires_manager_and_current_revision_to_resolve(self):
        campaign = self.campaign()
        batch, tasks = self.batch(campaign, [{'id': 'one', 'text': 'A source'}])
        task = tasks[0]
        path = f'/api/v1/annotation-tasks/{task["task_id"]}/'
        engineer = self.auth_client(self.tenant, Role.ENGINEER)
        self.assertEqual(self.review(task).status_code, 201)
        escalated = engineer.post(f'{path}escalate/', {'reason': 'Ambiguous label'}, format='json')
        self.assertEqual(escalated.status_code, 200, escalated.content)
        self.assertTrue(escalated.data['needs_adjudication'])
        self.assertEqual(self.close(batch).status_code, 409)
        self.assertEqual(self.review(task, revision=2).status_code, 409)

        payload = {'decision': 'corrected', 'human_label': {'label': 'negative'}, 'expected_revision': 2, 'adjudicate': True}
        forbidden = engineer.post(f'{path}review/', payload, format='json')
        self.assertEqual(forbidden.status_code, 403, forbidden.content)
        stale = self.client.post(f'{path}review/', {**payload, 'expected_revision': 1}, format='json')
        self.assertEqual(stale.status_code, 409, stale.content)
        self.assertEqual(AnnotationRecord.objects.filter(task__task_id=task['task_id']).count(), 1)

        resolved = self.client.post(f'{path}review/', payload, format='json')
        self.assertEqual(resolved.status_code, 201, resolved.content)
        self.assertFalse(resolved.data['needs_adjudication'])
        self.assertEqual(resolved.data['status'], 'adjudicated')
        self.assertTrue(resolved.data['latest_review']['is_adjudication'])
        closed = self.close(batch)
        self.assertEqual(closed.status_code, 200, closed.content)
        exported = self.client.get(f'/api/v1/annotation-snapshots/{closed.data["snapshot_id"]}/export/').data
        self.assertEqual(exported['items'][0]['human_label'], {'label': 'negative'})
        self.assertTrue(exported['items'][0]['is_adjudication'])

    def test_assignment_conflict_escalation_and_manager_adjudication(self):
        campaign = self.campaign(); batch, tasks = self.batch(campaign, [{'id':'one','text':'A source'}]); task = tasks[0]
        engineer = self.auth_client(self.tenant, Role.ENGINEER)
        key = ApiKey.objects.filter(tenant=self.tenant, role=Role.ENGINEER).first()
        assigned = self.client.post(f'/api/v1/annotation-tasks/{task["task_id"]}/assignment/', {'reviewer':f'api_key:{key.pk}'}, format='json')
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(self.review(task).status_code, 403)
        first = engineer.post(f'/api/v1/annotation-tasks/{task["task_id"]}/review/', {'decision':'corrected','human_label':{'label':'positive'},'expected_revision':1},format='json')
        self.assertEqual(first.status_code, 201, first.data)
        self.client.post(f'/api/v1/annotation-tasks/{task["task_id"]}/assignment/', {'reviewer':''},format='json')
        conflict = self.review(task, label='negative', revision=2)
        self.assertEqual(conflict.status_code, 201, conflict.data); self.assertTrue(conflict.data['needs_adjudication'])
        self.assertEqual(self.close(batch).status_code, 409)
        final = self.client.post(f'/api/v1/annotation-tasks/{task["task_id"]}/review/', {'decision':'corrected','human_label':{'label':'positive'},'expected_revision':3,'adjudicate':True},format='json')
        self.assertEqual(final.status_code, 201, final.data); self.assertFalse(final.data['needs_adjudication'])
        self.assertEqual(self.close(batch).status_code, 200)

    def test_blind_queue_hides_predictions_and_cross_project_campaigns(self):
        campaign = self.campaign(); batch, tasks = self.batch(campaign, [{'id':'one','text':'A source'}])
        task = AnnotationTask.objects.get(task_id=tasks[0]['task_id']); task.content['draft_prediction']={'predicted_label':'positive'};task.save()
        blind = self.client.get(f'/api/v1/labeling-batches/{batch["batch_id"]}/tasks/?blind=1')
        self.assertNotIn('draft_prediction', blind.data['results'][0]['content'])
        team = Team.objects.create(tenant_id=self.tenant.pk, name='Team', slug='team')
        a = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='A', slug='a')
        b = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='B', slug='b')
        task.campaign.project = a;task.campaign.save()
        self.assertEqual(self.client.get(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/', HTTP_X_PROJECT_ID=str(b.pk)).status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/annotation-tasks/{task.task_id}/', HTTP_X_PROJECT_ID=str(b.pk)).status_code, 404)
