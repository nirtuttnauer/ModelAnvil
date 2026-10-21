from django.test import TestCase
from modelanvil.runners.training import test_cpu_runtime as cpu
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.budgets.models import BudgetReservation
from modelanvil.runners.models import TrainingRun
import json


class TrainingWorkbenchTests(TestCase):
    setUp = cpu.CpuRuntimeTests.setUp
    artifact = cpu.CpuRuntimeTests.artifact
    envelope = cpu.CpuRuntimeTests.envelope
    payload = cpu.CpuRuntimeTests.payload
    launch = cpu.CpuRuntimeTests.launch
    execute = cpu.CpuRuntimeTests.execute

    def test_source_validation_returns_repairable_issues_without_loading_a_model(self):
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        raw = b'q,a,unused\nQuestion,Answer,\nQuestion,Answer,\nAnother,,\nWrong,42,\n'
        mapping = {'mode': 'prompt_response', 'prompt_field': 'q', 'response_field': 'a'}
        with patch('modelanvil.api.views.guided_training.verified_model_directory', side_effect=AssertionError('Inspection must not load model resources')):
            result = self.client.post('/api/v1/fine-tuning/inspect-source/', {'file': SimpleUploadedFile('source.csv', raw), 'source_mapping': json.dumps(mapping)}, format='multipart')
        self.assertEqual(result.status_code, 200, result.data)
        report = result.data['validation']
        self.assertEqual(report['mapping'], mapping)
        self.assertEqual(report['checked_rows'], 4)
        self.assertEqual(report['duplicate_rows'], 1)
        self.assertEqual(report['invalid_rows'], 1)
        invalid = self.client.post('/api/v1/fine-tuning/inspect-source/', {'file': SimpleUploadedFile('source.csv', raw), 'source_mapping': '{invalid'}, format='multipart')
        self.assertEqual(invalid.status_code, 400)

    def test_column_inspection_preview_and_publication_use_the_same_recipe(self):
        from pathlib import Path
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        raw = ('customer question,agent answer\n' + '\n'.join(f'Question {i},Answer {i}' for i in range(6))).encode()
        mapping = {'mode': 'prompt_response', 'prompt_field': 'customer question', 'response_field': 'agent answer'}
        inspected = self.client.post('/api/v1/fine-tuning/inspect-source/', {'file': SimpleUploadedFile('source.csv', raw)}, format='multipart')
        self.assertEqual(inspected.status_code, 200, inspected.data)
        self.assertEqual(inspected.data['columns'], ['customer question', 'agent answer'])
        class Tokenizer:
            def __call__(self, text, **options): return {'input_ids': list(text.encode()), 'offset_mapping': [(i, i + 1) for i in range(len(text))]}
        with patch('modelanvil.api.views.guided_training.verified_model_directory', return_value=Path('/synthetic-tokenizer')), patch('modelanvil.api.views.guided_training.local_tokenizer', return_value=Tokenizer()):
            preview = self.client.post('/api/v1/fine-tuning/preview/', {'file': SimpleUploadedFile('source.csv', raw), 'source_mapping': json.dumps(mapping)}, format='multipart')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data['sample_rows'][0]['blocks'][1]['text'], 'Answer 0')
        artifact = self.artifact('mapped.csv', raw, 'application/x-ndjson')
        prepared = self.client.post(f'/api/v1/datasets/{self.dataset.dataset.dataset_id}/prepare/',
            {'input_artifact_id': str(artifact.artifact_id), 'source_format': 'training', 'source_mapping': mapping, 'dedup': {'exact': True, 'near': False}}, format='json')
        self.assertEqual(prepared.status_code, 201, prepared.data)
        self.assertEqual(prepared.data['recipe_digest'], preview.data['recipe_digest'])
        invalid = self.client.post('/api/v1/fine-tuning/preview/', {'file': SimpleUploadedFile('source.csv', raw), 'source_mapping': '{invalid'}, format='multipart')
        self.assertEqual(invalid.status_code, 400)

    def test_export_choices_match_the_completed_runtime_and_recipe(self):
        from types import SimpleNamespace
        from modelanvil.api.views.training_views import training_export_options
        from modelanvil.runners.training import hf_runtime, mlx_runtime
        for runtime, recipe, expected in [(hf_runtime.RUNTIME_ID, 'full_sft', ['native', 'json']),
                                         (hf_runtime.RUNTIME_ID, 'lora_adapter', ['native', 'adapter', 'json']),
                                         (mlx_runtime.RUNTIME_ID, 'qlora_adapter', ['native', 'json'])]:
            run = SimpleNamespace(status='completed', recipe_type=recipe, hardware_config={'execution_mode': 'worker', 'pins': {'runtime': runtime}})
            self.assertEqual([option['format'] for option in training_export_options(run)], expected)
            for status in ['pending', 'running', 'failed', 'cancelled']:
                run.status = status; self.assertEqual(training_export_options(run), [])

    def test_completed_reference_export_downloads_a_verified_json_bundle(self):
        from modelanvil.runners.training.registry import verify_bundle
        run = self.execute(self.launch(total_steps=2))
        path = f'/api/v1/training-runs/{run.run_id}/'
        detail = self.client.get(path)
        self.assertEqual([option['format'] for option in detail.data['export_options']], ['json'])
        response = self.client.get(path + 'download/?export_format=json')
        self.assertEqual(response.status_code, 200)
        raw = b''.join(response.streaming_content); response.close()
        self.assertEqual(int(response['Content-Length']), len(raw))
        bundle = json.loads(raw)
        self.assertTrue(verify_bundle(bundle)['is_loadable'])
        self.assertIn('model.safetensors.b64', bundle)
        self.assertEqual(self.client.get(path + 'download/?export_format=gguf').status_code, 400)
        self.assertEqual(self.client.get(path + 'download/?export_format=native').status_code, 400)


    def test_custom_learning_rate_is_pinned_and_a_real_pilot_is_metered(self):
        run = self.launch(purpose='pilot', total_steps=2, hyperparameters={'learning_rate':0.1})
        self.assertEqual(run.hardware_config['purpose'], 'pilot')
        self.assertEqual(run.hardware_config['pins']['optimizer']['learning_rate'], 0.1)
        run = self.execute(run)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.job.job_id).settled_amount, 2)
        report = self.client.post('/api/v1/training-runs/preflight/', {**self.payload(), 'hyperparameters':{'learning_rate':0.1}},format='json')
        self.assertTrue(report.data['estimate']['known'], report.data)
        self.assertIsNone(report.data['estimate']['currency']); self.assertFalse(report.data['estimate']['estimated_cost']['known'])
        oversized = self.client.post('/api/v1/training-runs/', {**self.payload(), 'purpose':'pilot','total_steps':11},format='json',HTTP_IDEMPOTENCY_KEY='oversized-pilot')
        self.assertEqual(oversized.status_code, 400)

    def test_validation_is_measured_on_separate_source_groups_and_bad_controls_fail_before_jobs(self):
        rows = [self.envelope(i, 'ab cd') for i in range(20)]
        source = self.artifact('validation.jsonl', b''.join(json.dumps(row).encode()+b'\n' for row in rows), 'application/x-ndjson')
        self.dataset = publish_prepared_dataset(self.dataset.dataset,source,validation_percent=50,test_percent=0)
        run = self.execute(self.launch(total_steps=2,hyperparameters={'validation_interval':1}))
        self.assertTrue(all(metric['validation_loss'] > 0 for metric in run.metrics_log))
        self.assertTrue(all(metric['validation_samples'] > 0 for metric in run.metrics_log))
        for options in [{'learning_rate':0}, {'validation_interval':True}, {'optimizer':'invented'}]:
            response = self.client.post('/api/v1/training-runs/preflight/',{**self.payload(),'hyperparameters':options},format='json')
            self.assertEqual(response.data['status'], 'blocked', response.data)
        self.assertEqual(TrainingRun.all_objects.count(), 1)
