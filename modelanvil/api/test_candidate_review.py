"""Frozen candidate review and isolated standard-library consumer verification."""
import io
import json
import subprocess
import tempfile
import zipfile
import venv
import os
from pathlib import Path

from django.test import TestCase

from modelanvil.api import test_durable_evaluation as fixture
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import claim_job
from modelanvil.runners.eval_worker import evaluation_worker_executor
from modelanvil.runners.training.general_runtime import generate_candidate_completion
from modelanvil.releases.models import ReleaseVersion
from modelanvil.releases.artifacts import release_model_bundle


class CandidateReviewTests(TestCase):
    artifact = fixture.DurableEvaluationTests.artifact
    envelope = fixture.DurableEvaluationTests.envelope
    payload = fixture.DurableEvaluationTests.payload
    launch = fixture.DurableEvaluationTests.launch
    execute = fixture.DurableEvaluationTests.execute
    suite = fixture.DurableEvaluationTests.suite
    _suite_pk = fixture.DurableEvaluationTests._suite_pk
    pending_eval = fixture.DurableEvaluationTests.pending_eval
    queued = fixture.DurableEvaluationTests.queued

    def setUp(self):
        fixture.DurableEvaluationTests.setUp(self)
        self.evaluation = self.queued()
        outcome = execute_claim(self.evaluator, claim_job(self.evaluator, self.evaluation.job), evaluation_worker_executor)
        self.assertEqual(outcome['status'], 'succeeded', outcome)
        self.body = {'name': 'Reviewed local candidate', 'candidate_model_version': str(self.candidate.model_version_id),
            'evaluation_run': str(self.evaluation.run_id), 'min_accuracy': 0.8}

    def review(self):
        response = self.client.post('/api/v1/release-versions/create-candidate/', self.body, format='json')
        self.assertEqual(response.status_code, 201, response.json())
        return response.data

    def test_review_freezes_actual_results_and_preserves_failures_and_submission_identity(self):
        data = self.review()
        review = data['local_review']
        self.assertEqual(review['state'], 'failing')
        quality = next(c for c in review['criteria'] if c['key'] == 'min_accuracy')
        self.assertEqual(quality['actual'], 0); self.assertFalse(quality['passed'])
        self.assertFalse(review['production_qualified'])
        self.assertEqual(review['provenance']['committed_steps'], 2)
        self.assertEqual(self.client.post('/api/v1/release-versions/create-candidate/', self.body, format='json').status_code, 200)
        self.assertEqual(ReleaseVersion.all_objects.count(), 1)
        for method in (self.client.patch, self.client.delete):
            self.assertEqual(method(f"/api/v1/release-versions/{data['release_version_id']}/", {}, format='json').status_code, 400)

    def test_zip_bytes_load_in_clean_subprocess_with_matching_generated_tokens(self):
        data = self.review()
        response = self.client.get(f"/api/v1/release-versions/{data['release_version_id']}/download/")
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response['Content-Type'], 'application/zip')
        version = ReleaseVersion.all_objects.get(release_version_id=data['release_version_id'])
        expected = generate_candidate_completion(release_model_bundle(version)['bundle'], 'x', 2)
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                archive.extractall(directory)
            environment = Path(directory)/'consumer-environment'
            venv.EnvBuilder(with_pip=False).create(environment)
            python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            isolated = subprocess.run([str(python), '-I', '-c', "import importlib.util; assert all(importlib.util.find_spec(name) is None for name in ['modelanvil', 'django', 'torch', 'numpy'])"], capture_output=True, text=True, timeout=30)
            self.assertEqual(isolated.returncode, 0, isolated.stderr)
            completed = subprocess.run([str(python), '-I', str(Path(directory)/'infer.py'), directory,
                '--prompt', 'x', '--max-tokens', '2'], cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            actual = json.loads(completed.stdout)
            self.assertEqual(actual['generated_token_ids'], expected['generated_token_ids'])
            self.assertEqual(actual['weights_sha256'], expected['weights_sha256'])
            weights = Path(directory)/'model.safetensors'; weights.write_bytes(weights.read_bytes()+b'bad')
            corrupted = subprocess.run([str(python), '-I', str(Path(directory)/'infer.py'), directory],
                capture_output=True, text=True, timeout=30)
            self.assertNotEqual(corrupted.returncode, 0)

    def test_other_candidate_and_incomplete_evaluation_cannot_satisfy_review(self):
        other = {**self.body, 'candidate_model_version': str(self.base.model_version_id)}
        self.assertEqual(self.client.post('/api/v1/release-versions/create-candidate/', other, format='json').status_code, 400)
        self.evaluation.status = 'failed'; self.evaluation.save()
        self.assertEqual(self.client.post('/api/v1/release-versions/create-candidate/', self.body, format='json').status_code, 400)
        self.assertFalse(ReleaseVersion.all_objects.exists())

    def test_trained_reference_candidate_is_available_in_authenticated_chat(self):
        # Project scope is mandatory for chat; the model remains tenant-shared.
        from modelanvil.identity.models import Team, Project
        team = Team.objects.create(tenant_id=self.tenant.pk, name='team', slug='team')
        project = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='pilot', slug='pilot')
        headers = {'HTTP_X_PROJECT_ID': str(project.pk)}
        models = self.client.get('/api/v1/inference/models/', **headers)
        self.assertEqual(models.status_code, 200, models.content)
        self.assertIn(str(self.candidate.model_version_id), [v['id'] for v in models.data['data']])
        response = self.client.post('/api/v1/inference/chat/completions', {
            'model': str(self.candidate.model_version_id), 'messages': [{'role':'user', 'content':'x'}],
            'device':'cpu', 'temperature':0, 'max_tokens':2, 'prompt_format':'plain'}, format='json', **headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertGreater(response.data['usage']['completion_tokens'], 0)
        self.assertLessEqual(response.data['usage']['completion_tokens'], 2)

    def test_repeated_downloads_have_identical_bytes_and_frozen_consumer(self):
        from unittest.mock import patch
        data = self.review(); path=f'/api/v1/release-versions/{data["release_version_id"]}/download/'
        first=self.client.get(path)
        with patch('modelanvil.releases.review._consumer', side_effect=AssertionError('Current source must not replace frozen consumer')):
            second=self.client.get(path)
        self.assertEqual(first.status_code,200,first.content[:100]); self.assertEqual(second.status_code,200,second.content[:100])
        self.assertEqual(first.content,second.content);self.assertEqual(first['ETag'],second['ETag'])
        with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
            self.assertTrue(all(info.date_time==(1980,1,1,0,0,0) for info in archive.infolist()))
            import hashlib
            self.assertEqual(hashlib.sha256(archive.read('infer.py')).hexdigest(),data['local_review']['export_consumer']['sha256'])
            self.assertIn('model.safetensors',archive.namelist());self.assertIn('tokenizer_config.json',archive.namelist())

    def test_incomplete_current_evaluation_blocks_every_export_and_redacts_old_case_content(self):
        data=self.review(); ident=data['release_version_id']
        self.evaluation.status='failed';self.evaluation.save()
        for path in [f'/api/v1/release-versions/{ident}/download/', f'/api/v1/release-versions/{ident}/export-bundle/']:
            self.assertEqual(self.client.get(path).status_code,400)
        response=self.client.get(f'/api/v1/release-versions/{ident}/')
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(response.data['review_freshness']['valid']);self.assertEqual(response.data['local_review']['state'],'stale')
        self.assertNotIn('cases',response.data['local_review']);self.assertNotIn('cases',response.data['bundle_manifest']['local_review'])
        self.assertNotIn('export_consumer',response.data['bundle_manifest'])

    def test_changed_results_and_frozen_consumer_fail_current_evidence_checks(self):
        data=self.review(); ident=data['release_version_id']; path=f'/api/v1/release-versions/{ident}/download/'
        case=self.evaluation.case_results.first();old=case.candidate_output;case.candidate_output='Changed after review';case.save()
        self.assertEqual(self.client.get(path).status_code,400)
        case.candidate_output=old;case.save();self.assertEqual(self.client.get(path).status_code,200)
        version=ReleaseVersion.all_objects.get(release_version_id=ident)
        version.bundle_manifest={**version.bundle_manifest,'export_consumer':'Y2hhbmdlZA=='};version.save()
        self.assertEqual(self.client.get(path).status_code,400)

    def test_configuration_or_simulation_status_cannot_claim_actual_worker_export(self):
        from modelanvil.runners.models import TrainingRun
        run=TrainingRun.all_objects.get(output_model_version=self.candidate)
        run.hardware_config={**run.hardware_config,'pins':{**run.hardware_config['pins'],'contract_digest':'unverified'}};run.save()
        response=self.client.post('/api/v1/release-versions/create-candidate/',self.body,format='json')
        self.assertEqual(response.status_code,400,response.content);self.assertFalse(ReleaseVersion.all_objects.exists())

    def test_incomplete_legacy_review_refuses_actionably(self):
        from modelanvil.runners.training.runtime import digest
        data=self.review();version=ReleaseVersion.all_objects.get(release_version_id=data['release_version_id'])
        review=version.bundle_manifest['local_review'];review.pop('evidence_digest');version.manifest_digest=digest(review);version.save()
        response=self.client.get(f'/api/v1/release-versions/{version.release_version_id}/download/')
        self.assertEqual(response.status_code,400,response.content)
