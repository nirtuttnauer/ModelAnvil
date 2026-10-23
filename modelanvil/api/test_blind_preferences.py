"""Formal blind pairs use actual numerical generation and independent credential fixtures."""
import base64
import io
import json

from django.test import TransactionTestCase
from rest_framework.test import APIClient

from modelanvil.api import test_specialists as fixtures
from modelanvil.annotation.models import AnnotationTask, CumulativeSnapshot
from modelanvil.artifacts.models import Artifact
from modelanvil.identity.models import ApiKey, Role, generate_api_key
from modelanvil.runners.model_catalog import _store
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion
from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
from modelanvil.runners.training.runtime import RUNTIME_ID


class BlindPreferenceTests(TransactionTestCase):
    version = fixtures.SpecialistApiTests.version

    def setUp(self):
        fixtures.SpecialistApiTests.setUp(self)
        self.key.role = Role.ADMIN; self.key.save(update_fields=['role'])
        self.reviewers = [self.auth('First reviewer'), self.auth('Second reviewer')]
        self.assigned = [f'api_key:{key.pk}' for _, key in self.reviewers]
        tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef \n')]
        tokenizer = TokenizerVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
            name='Actual shared chars', vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
        self.models = []
        for index, target in enumerate(('b', 'c')):
            policy = CausalTextModel(len(tokens), n_embd=4, lora_r=2, lora_alpha=4, seed=42)
            for _ in range(4): policy.compute_loss_and_step([1, tokens.index('a'), tokens.index(target), 2], .1)
            raw, manifest = pack_safetensors(policy.export_tensors())
            bundle = {'config.json': {'runtime': RUNTIME_ID, 'vocab_size': len(tokens), 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
                'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(),
                'tokenizer_config.json': {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}}
            ref = _store(io.BytesIO(json.dumps(bundle).encode()), tenant=self.tenant.pk, project=self.project.pk, name='actual.json')
            model = Model.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name=f'Private model {index}')
            version = ModelVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project, model=model,
                tokenizer=tokenizer, architecture_ref=RUNTIME_ID, artifact_manifest_id=ref['artifact_id'])
            self.models.append(version)
        self.messages = [{'role': 'user', 'content': 'a'}]
        results = []
        for version in self.models:
            reply = self.client.post('/api/v1/inference/chat/completions', {'model': str(version.model_version_id),
                'messages': self.messages, 'max_tokens': 4}, format='json')
            self.assertEqual(reply.status_code, 200, reply.content)
            data = reply.json(); self.assertGreater(data['usage']['completion_tokens'], 0)
            results.append({'request_id': data['id'].removeprefix('chatcmpl-'), 'text': data['choices'][0]['message']['content']})
        self.assertNotEqual(results[0]['text'], results[1]['text'])
        conversation = self.client.post('/api/v1/chat-conversations/', {'title': 'Actual pair', 'messages': [],
            'configuration': {'model': str(self.models[0].model_version_id), 'max_tokens': 4}}, format='json')
        self.assertEqual(conversation.status_code, 201, conversation.content)
        self.conversation = conversation.json()['conversation_id']
        pair = self.client.post('/api/v1/chat-comparisons/', {'conversation_id': self.conversation,
            'messages': self.messages, 'responses': results}, format='json')
        self.assertEqual(pair.status_code, 201, pair.content); self.pair = pair.json()
        campaign = self.client.post('/api/v1/labeling-campaigns/', {'name': 'Formal preference fixture',
            'kind': 'preference_ranking', 'guidelines': 'Choose the accurate response; explain uncertainty.', 'max_cycles': 1}, format='json')
        self.assertEqual(campaign.status_code, 201, campaign.content); self.campaign = campaign.json()
        self.path = '/api/v1/labeling-campaigns/' + self.campaign['campaign_id'] + '/generated-pairs/'

    def auth(self, name):
        secret, hashed = generate_api_key()
        key = ApiKey.objects.create(tenant=self.tenant, project=self.project, name=name, role=Role.REVIEWER, secret_hash=hashed)
        client = APIClient(); client.credentials(HTTP_AUTHORIZATION='Bearer ' + secret)
        return client, key

    def start(self):
        response = self.client.post(self.path, {'comparisons': [self.pair['comparison_id']], 'reviewers': self.assigned}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.batch = response.json(); self.task = AnnotationTask.all_objects.get(batch__batch_id=self.batch['batch_id'])
        return self.batch

    def vote(self, reviewer, choice='candidate_a', revision=1, *, reason='Rubric accuracy inspected.', adjudicate=False):
        return reviewer.post(f'/api/v1/annotation-tasks/{self.task.task_id}/review/', {'decision': 'corrected',
            'human_label': {'label': choice, 'reason': reason}, 'expected_revision': revision,
            'blind_review': False, 'adjudicate': adjudicate}, format='json')

    def close(self):
        return self.client.post(f'/api/v1/labeling-batches/{self.batch["batch_id"]}/close/', {}, format='json')

    def test_forced_blinding_and_related_resources_cannot_reveal_mapping(self):
        self.start(); reviewer = self.reviewers[0][0]
        for query in ('', '?blind=0', '?blind=1'):
            response = reviewer.get(f'/api/v1/annotation-tasks/{self.task.task_id}/{query}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()['content']), {'prompt', 'candidate_a', 'candidate_b'})
            self.assertNotIn('"_preference":', response.content.decode())
            self.assertNotIn(self.pair['comparison_id'], response.content.decode())
        self.assertEqual(reviewer.get('/api/v1/chat-comparisons/' + self.pair['comparison_id'] + '/').status_code, 404)
        self.assertEqual(reviewer.get('/api/v1/chat-conversations/' + self.conversation + '/').status_code, 404)
        self.assertEqual(reviewer.get(self.path).status_code, 403)

    def test_missing_reviews_reasons_and_revision_conflicts_never_become_labels(self):
        self.start(); self.assertEqual(self.close().status_code, 409)
        self.assertEqual(self.vote(self.reviewers[0][0], reason='').status_code, 400)
        self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 201)
        self.assertEqual(self.close().status_code, 409)
        self.assertEqual(self.vote(self.reviewers[1][0], revision=1).status_code, 409)
        self.assertEqual(self.vote(self.reviewers[1][0], revision=2).status_code, 201)
        closed = self.close(); self.assertEqual(closed.status_code, 200, closed.content)
        snapshot = CumulativeSnapshot.all_objects.get(snapshot_id=closed.json()['snapshot_id'])
        proof = snapshot.qualification['formal_preference']
        self.assertTrue(proof['alignment_eligible'], proof)
        self.assertEqual(proof['coverage']['missing_reviews'], 0)
        self.assertEqual(proof['coverage']['unanimous_pairs'], 1)
        from modelanvil.runners.alignment.execution import read_preferences
        pairs, _ = read_preferences(Artifact.all_objects.get(artifact_id=proof['artifact']['artifact_id']), tenant=self.tenant.pk, project=self.project.pk)
        self.assertEqual(len(pairs), 1); self.assertEqual(len(pairs[0]['metadata']['reviews']), 2)
        self.assertEqual(self.close().json(), closed.json())

    def test_disagreement_requires_explicit_manager_adjudication_and_preserves_history(self):
        self.start(); self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 201)
        self.assertEqual(self.vote(self.reviewers[1][0], 'candidate_b', 2).status_code, 201)
        self.assertEqual(self.close().status_code, 409)
        self.assertEqual(self.vote(self.reviewers[0][0], revision=3, adjudicate=True).status_code, 403)
        self.assertEqual(self.vote(self.client, revision=3, adjudicate=True).status_code, 201)
        self.assertEqual(self.task.records.count(), 3)
        self.assertEqual(self.task.records.filter(is_blind_preference=True).count(), 3)
        self.assertEqual(self.close().status_code, 200)

    def test_ties_and_abstentions_are_covered_but_never_binary_training_choices(self):
        self.start(); self.assertEqual(self.vote(self.reviewers[0][0], 'tie').status_code, 201)
        self.assertEqual(self.vote(self.reviewers[1][0], 'tie', 2).status_code, 201)
        closed = self.close(); self.assertEqual(closed.status_code, 200, closed.content)
        proof = closed.json()['qualification']['formal_preference']
        self.assertFalse(proof['alignment_eligible']); self.assertEqual(proof['excluded']['tie'], 1)

    def test_changed_rubric_models_and_unassigned_credentials_are_refused(self):
        self.start()
        outsider, _ = self.auth('Not assigned')
        self.assertEqual(self.vote(outsider).status_code, 400)
        self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 201)
        self.assertEqual(self.vote(self.reviewers[1][0], revision=2).status_code, 201)
        closed = self.close(); self.assertEqual(closed.status_code, 200, closed.content)
        url = '/api/v1/annotation-snapshots/' + closed.json()['snapshot_id'] + '/preference-pairs/'
        first = self.client.get(url); self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['schema_version'], 'modelanvil.preference-pairs.v1')
        self.assertEqual(self.reviewers[0][0].get(url).status_code, 403)
        ModelVersion.all_objects.filter(pk=self.models[0].pk).update(metadata={'changed': True})
        self.assertEqual(self.client.get(url).status_code, 400)
        self.assertEqual(self.task.records.count(), 2)

    def test_new_protected_evaluation_prompt_blocks_review_after_assignment(self):
        from modelanvil.runners.models import EvaluationSuite, EvaluationSuiteVersion
        self.start()
        suite = EvaluationSuite.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='Protected control')
        EvaluationSuiteVersion.all_objects.create(tenant_id=self.tenant.pk, suite=suite,
            cases=[{'input_prompt': 'a', 'expected_output': 'protected'}])
        self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 400)
        self.assertFalse(self.task.records.exists())

    def test_changed_rubric_refuses_review_without_rewriting_history(self):
        from modelanvil.annotation.models import RubricRevision
        self.start()
        RubricRevision.all_objects.filter(rubric_id=self.campaign['rubric']['rubric_id']).update(guidelines_text='Changed after assignment')
        self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 400)
        self.assertFalse(self.task.records.exists())

    def test_correction_keeps_original_votes_and_requires_adjudication(self):
        self.start()
        self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 201)
        self.assertEqual(self.vote(self.reviewers[1][0], revision=2).status_code, 201)
        corrected = self.vote(self.reviewers[0][0], 'candidate_b', 3)
        self.assertEqual(corrected.status_code, 201, corrected.content)
        self.assertTrue(corrected.json()['needs_adjudication'])
        self.assertEqual(self.task.records.get(revision_no=1).human_label['label'], 'candidate_a')
        self.assertEqual(self.task.records.get(revision_no=3).human_label['label'], 'candidate_b')
        self.assertEqual(self.close().status_code, 409)

    def test_original_generator_credential_cannot_be_assigned_after_role_change(self):
        manager, key = self.auth('Separate assigning manager')
        key.role = Role.ADMIN; key.save(update_fields=['role'])
        self.key.role = Role.REVIEWER; self.key.save(update_fields=['role'])
        reply = manager.post(self.path, {'comparisons': [self.pair['comparison_id']],
            'reviewers': [f'api_key:{self.key.pk}', self.assigned[0]]}, format='json')
        self.assertEqual(reply.status_code, 400, reply.content)
        self.assertFalse(AnnotationTask.all_objects.exists())

    def test_formal_batch_completes_even_when_legacy_cycle_cap_is_larger(self):
        from modelanvil.annotation.models import LabelingCampaign
        LabelingCampaign.all_objects.filter(campaign_id=self.campaign['campaign_id']).update(max_cycles=3)
        self.start(); self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 201)
        self.assertEqual(self.vote(self.reviewers[1][0], revision=2).status_code, 201)
        self.assertEqual(self.close().status_code, 200)
        self.assertEqual(LabelingCampaign.all_objects.get(campaign_id=self.campaign['campaign_id']).status, 'completed')

    def test_disagreement_does_not_block_a_remaining_assigned_review(self):
        third, key = self.auth('Third assigned reviewer')
        self.assigned.append(f'api_key:{key.pk}')
        self.start(); self.assertEqual(self.vote(self.reviewers[0][0]).status_code, 201)
        self.assertEqual(self.vote(self.reviewers[1][0], 'candidate_b', 2).status_code, 201)
        self.assertEqual(self.vote(self.client, revision=3, adjudicate=True).status_code, 400)
        self.assertEqual(self.vote(third, revision=3).status_code, 201)
        self.assertEqual(self.vote(self.client, revision=4, adjudicate=True).status_code, 201)
        self.assertEqual(self.close().status_code, 200)

    def test_promoting_an_assigned_key_does_not_permit_an_informed_manager_vote(self):
        self.start()
        reviewer, key = self.reviewers[0]
        key.role = Role.MANAGER; key.save(update_fields=['role'])
        self.assertEqual(self.vote(reviewer).status_code, 403)
        self.assertFalse(self.task.records.exists())

    def test_legacy_campaign_without_an_origin_is_not_mistaken_for_formal_blinding(self):
        from modelanvil.annotation.models import LabelingCampaign
        from modelanvil.runners.models import ChatComparison
        campaign = LabelingCampaign.all_objects.get(campaign_id=self.campaign['campaign_id'])
        self.assertNotIn('origin', campaign.configuration)
        ChatComparison.all_objects.filter(comparison_id=self.pair['comparison_id']).update(review_campaign=campaign)
        reviewer = self.reviewers[0][0]
        self.assertEqual(reviewer.get('/api/v1/chat-comparisons/' + self.pair['comparison_id'] + '/').status_code, 200)
        self.assertEqual(reviewer.get('/api/v1/chat-conversations/' + self.conversation + '/').status_code, 200)

    def test_pinned_source_excludes_the_whole_audit_group_before_assignment(self):
        import hashlib
        import uuid
        from modelanvil.artifacts.models import Dataset
        from modelanvil.data.publication import publish_prepared_dataset
        from modelanvil.annotation.models import LabelingCampaign
        rows = [{'schema_version': '1.0', 'sample_id': str(uuid.uuid4()), 'source_group_id': 'shared-source',
            'blocks': [{'block_id': 'text', 'type': 'text', 'text': text}],
            'provenance': {'source_snapshot_ref': 'authored-control', 'source_record_key': str(i),
                'content_sha256': hashlib.sha256(text.encode()).hexdigest()}} for i, text in enumerate(('a', 'c'))]
        ref = _store(io.BytesIO(''.join(json.dumps(row)+'\n' for row in rows).encode()),
            tenant=self.tenant.pk, project=self.project.pk, name='source.jsonl', media_type='application/x-ndjson')
        dataset = Dataset.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='Group exclusion control')
        revision = publish_prepared_dataset(dataset, Artifact.all_objects.get(artifact_id=ref['artifact_id']),
            detect=False, dedup=False, validation_percent=0, test_percent=0)
        LabelingCampaign.all_objects.filter(campaign_id=self.campaign['campaign_id']).update(configuration={'audit_sample_refs': [rows[1]['sample_id']]})
        response = self.client.post(self.path, {'comparisons': [self.pair['comparison_id']], 'reviewers': self.assigned,
            'source_revision': str(revision.revision_id)}, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(AnnotationTask.all_objects.exists())
