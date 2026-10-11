"""Real tensor reload/generation plus import isolation and byte verification."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.core.tenancy import set_active_project, set_active_tenant
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.jobs.models import Job, Worker, WorkerPool, claim_job
from modelanvil.jobs.executor import execute_claim
from modelanvil.runners.model_catalog import _store, model_import_executor
from modelanvil.runners.models import InferenceRequest, ModelImport, ModelVersion


@skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('transformers'), 'Optional transformer runtime is not installed')
class ModelWorkspaceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import torch
        from tokenizers import Tokenizer
        from tokenizers.models import WordLevel
        from tokenizers.pre_tokenizers import Whitespace
        from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast
        cls.fixture = tempfile.TemporaryDirectory()
        raw = Tokenizer(WordLevel({'<unk>': 0, '<bos>': 1, '<eos>': 2, 'hello': 3, 'world': 4, 'a': 5, 'b': 6, 'c': 7}, unk_token='<unk>'))
        raw.pre_tokenizer = Whitespace()
        tokenizer = PreTrainedTokenizerFast(tokenizer_object=raw, unk_token='<unk>', bos_token='<bos>', eos_token='<eos>')
        tokenizer.save_pretrained(cls.fixture.name)
        with torch.random.fork_rng():
            torch.manual_seed(42)
            model = LlamaForCausalLM(LlamaConfig(vocab_size=8, hidden_size=16, intermediate_size=32,
                num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2, max_position_embeddings=64,
                bos_token_id=1, eos_token_id=2))
        model.save_pretrained(cls.fixture.name, safe_serialization=True)
        cls.addClassCleanup(cls.fixture.cleanup)

    def setUp(self):
        storage = tempfile.TemporaryDirectory(); self.addCleanup(storage.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': storage.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='workspace', name='Workspace')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        team = Team.objects.create(tenant_id=self.tenant.pk, name='team', slug='team')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='one', slug='one')
        self.other = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='two', slug='two')
        set_active_project(self.project.pk); self.addCleanup(set_active_project, None)
        secret, hashed = generate_api_key()
        self.key = ApiKey.objects.create(tenant=self.tenant, project=self.project, name='engineer', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.files = {}
        for path in Path(self.fixture.name).iterdir():
            with path.open('rb') as stream:
                self.files[path.name] = _store(stream, tenant=self.tenant.pk, project=self.project.pk, name=path.name)

    def import_model(self, **overrides):
        inputs = {'files': self.files, 'name': 'Tiny real Llama', 'accepted_license': 'apache-2.0', 'idempotency_key': 'local-1', **overrides}
        return self.client.post('/api/v1/model-imports/', inputs, format='json')

    def test_real_local_import_repeat_and_completion_matches_framework(self):
        response = self.import_model()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.import_model().data['candidate_id'], response.data['candidate_id'])
        self.assertEqual(ModelImport.all_objects.count(), 1)
        version = ModelVersion.all_objects.get(model_version_id=response.data['candidate_id'])
        self.assertEqual(version.state, 'draft')
        body = {'model': response.data['candidate_id'], 'messages': [{'role': 'user', 'content': 'hello world'}], 'max_tokens': 4}
        completed = self.client.post('/api/v1/inference/chat/completions', body, format='json')
        self.assertEqual(completed.status_code, 200, completed.content)
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(self.fixture.name, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(self.fixture.name, local_files_only=True, dtype=torch.float32, attn_implementation='eager')
        ids = tok.encode('hello world', add_special_tokens=True)
        with torch.inference_mode():
            result = model.generate(torch.tensor([ids]), max_new_tokens=4, do_sample=False, pad_token_id=2)
        expected = tok.decode(result[0, len(ids):], skip_special_tokens=True, clean_up_tokenization_spaces=False)
        self.assertEqual(completed.data['choices'][0]['message']['content'], expected)
        self.assertEqual(completed.data['usage']['prompt_tokens'], len(ids))
        stream = self.client.post('/api/v1/inference/chat/completions', {**body, 'stream': True, 'stream_options': {'include_usage': True}}, format='json')
        self.assertEqual(stream.status_code, 200)
        iterator = iter(stream.streaming_content)
        events = []
        while True:
            event = next(iterator).decode()
            events.append(event.strip())
            if event == 'data: [DONE]\n\n':
                break
        # A client starts its next request as soon as DONE arrives, before iterator cleanup.
        self.assertEqual(self.client.post('/api/v1/inference/chat/completions', body, format='json').status_code, 200)
        stream.close()
        values = [json.loads(e[6:]) for e in events if e.startswith('data: ') and e != 'data: [DONE]']
        text = ''.join(v['choices'][0]['delta'].get('content', '') for v in values if v.get('choices'))
        self.assertEqual(text, expected)
        self.assertEqual(values[-1]['usage'], completed.data['usage'])
        self.assertEqual(self.client.get('/api/v1/inference/models/').data['data'][0]['id'], str(version.model_version_id))
        version.metadata = {**version.metadata, 'format': 'gguf'}
        with self.assertRaises(ValidationError):
            version.save()

    def test_import_rejects_paths_scope_corruption_and_conflicting_repeat(self):
        self.assertEqual(self.import_model(files={'../model.safetensors': self.files['model.safetensors']}).status_code, 400)
        bad = _store(io.BytesIO(b'bad'), tenant=self.tenant.pk, project=self.other.pk, name='model.safetensors')
        self.assertEqual(self.import_model(files={**self.files, 'model.safetensors': bad}).status_code, 400)
        bad = _store(io.BytesIO(b'not-safetensors'), tenant=self.tenant.pk, project=self.project.pk, name='model.safetensors')
        self.assertEqual(self.import_model(files={**self.files, 'model.safetensors': bad}).status_code, 400)
        self.assertEqual(ModelVersion.all_objects.count(), 0)
        self.assertEqual(self.import_model().status_code, 201)
        self.assertEqual(self.import_model(name='Different name').status_code, 400)

    def test_browser_upload_registers_verified_bytes_and_rejects_invalid_configuration(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        refs = {}
        for path in Path(self.fixture.name).iterdir():
            response = self.client.post('/api/v1/model-imports/upload-file/',
                {'file': SimpleUploadedFile(path.name, path.read_bytes())}, format='multipart')
            self.assertEqual(response.status_code, 201, response.data)
            refs[path.name] = {k: response.data[k] for k in ('artifact_id', 'sha256', 'byte_size')}
        imported = self.import_model(files=refs)
        self.assertEqual(imported.status_code, 201, imported.data)
        config = {'model': imported.data['candidate_id'], 'compare_model': 'malformed'}
        response = self.client.post('/api/v1/chat-conversations/',
            {'title': 'Invalid comparison', 'messages': [], 'configuration': config}, format='json')
        self.assertEqual(response.status_code, 400, response.content)

    def test_import_worker_executes_only_compatible_job_and_publishes_through_fence(self):
        from modelanvil.runners.model_catalog import launch_import
        pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='imports', queue_name='imports')
        worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=pool, name='local', slots=1, capabilities={'model_import': True})
        plan = {'repo_id': 'owner/model', 'revision': 'a' * 40, 'license': 'apache-2.0', 'format': 'safetensors',
                'files': {n: {'byte_size': r['byte_size'], 'sha256': r['sha256']} for n, r in self.files.items()}}
        item = launch_import(plan, name='Downloaded', tenant=self.tenant.pk, project=self.project, pool=pool,
                             accepted_license='apache-2.0', idempotency_key='hub-1')
        claim = claim_job(worker)
        self.assertIsNotNone(claim)
        with patch('modelanvil.runners.model_catalog.download_file', side_effect=lambda item, name, pin, context: self.files[name]):
            result = execute_claim(worker, claim, model_import_executor)
        self.assertTrue(result['committed'], result)
        self.assertEqual(result['status'], 'succeeded', result)
        item.refresh_from_db()
        self.assertIsNotNone(item.candidate)
        self.assertEqual(item.job.status, Job.Status.SUCCEEDED)

    def test_inference_rejects_tampered_artifact_unsupported_options_and_overflow(self):
        response = self.import_model()
        self.assertEqual(response.status_code, 201, response.data)
        body = {'model': response.data['candidate_id'], 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 2}
        self.assertEqual(self.client.post('/api/v1/inference/chat/completions', {**body, 'tools': []}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/v1/inference/chat/completions', {**body, 'max_tokens': 65}, format='json').status_code, 400)
        artifact = Artifact.all_objects.get(artifact_id=self.files['model.safetensors']['artifact_id'])
        from modelanvil.artifacts.storage import artifact_storage_backend
        path = artifact_storage_backend()._path(self.tenant.pk, artifact.object_key, create_parent=False)
        path.write_bytes(b'corrupted')
        self.assertEqual(self.client.post('/api/v1/inference/chat/completions', body, format='json').status_code, 400)

    def test_disconnect_releases_model_and_conversations_use_revision_checks(self):
        imported = self.import_model()
        body = {'model': imported.data['candidate_id'], 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 2, 'stream': True}
        stream = self.client.post('/api/v1/inference/chat/completions', body, format='json')
        self.assertEqual(stream.status_code, 200, stream.content if not stream.streaming else '')
        stream.close()  # Also closes a stream which was never iterated.
        self.assertEqual(InferenceRequest.all_objects.get().status, 'cancelled')
        self.assertEqual(self.client.post('/api/v1/inference/chat/completions', {**body, 'stream': False}, format='json').status_code, 200)
        config = {'model': imported.data['candidate_id'], 'max_tokens': 2, 'device': 'cpu'}
        created = self.client.post('/api/v1/chat-conversations/', {'title': 'Private conversation', 'messages': body['messages'], 'configuration': config}, format='json')
        self.assertEqual(created.status_code, 201, created.content)
        path = f"/api/v1/chat-conversations/{created.data['conversation_id']}/"
        changed = self.client.patch(path, {'title': 'Updated', 'revision_no': 1}, format='json')
        self.assertEqual(changed.status_code, 200, changed.content)
        self.assertEqual(changed.data['revision_no'], 2)
        self.assertEqual(self.client.patch(path, {'title': 'Stale', 'revision_no': 1}, format='json').status_code, 409)
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=self.other, name='other key', role=Role.ENGINEER, secret_hash=hashed)
        other = APIClient(); other.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(other.post('/api/v1/inference/chat/completions', body, format='json').status_code, 404)
        self.assertEqual(other.get('/api/v1/inference/models').data['data'], [])

    def test_download_resumes_partial_bytes_and_rejects_checksum_changes(self):
        from types import SimpleNamespace
        import hashlib
        from modelanvil.artifacts.storage import artifact_storage_backend
        from modelanvil.runners.model_catalog import download_file
        raw = b'actual model file bytes'
        item = ModelImport.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='Resume',
            repo_id='owner/model', revision='a' * 40, files={}, license_expression='apache-2.0', input_digest='b' * 64, idempotency_key='resume')
        cache = artifact_storage_backend().root / '.model-cache' / str(self.tenant.pk) / str(self.project.pk) / item.revision
        cache.mkdir(parents=True)
        path = cache / 'model.safetensors.partial'; path.write_bytes(raw[:6])
        class Reply:
            status_code = 206
            headers = {'Content-Range': f'bytes 6-{len(raw) - 1}/{len(raw)}'}
            def raise_for_status(self): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_content(self, chunk_size): return iter([raw[6:]])
        pin = {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw)}
        with patch('requests.get', return_value=Reply()) as request:
            ref = download_file(item, 'model.safetensors', pin, SimpleNamespace(heartbeat=lambda: True))
            self.assertEqual(request.call_args.kwargs['headers'], {'Range': 'bytes=6-'})
            self.assertIn(item.revision, request.call_args.args[0])
        self.assertEqual(ref['sha256'], pin['sha256'])
        with self.assertRaisesMessage(ValueError, 'checksum'):
            download_file(item, 'model.safetensors', {**pin, 'sha256': '0' * 64}, SimpleNamespace(heartbeat=lambda: True))
        self.assertFalse(path.exists())

    def test_expired_import_attempt_cannot_publish_a_candidate(self):
        from modelanvil.runners.model_catalog import launch_import
        from django.utils import timezone
        from datetime import timedelta
        pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='expiry', queue_name='expiry')
        worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=pool, name='local', slots=1, capabilities={'model_import': True})
        plan = {'repo_id': 'owner/model', 'revision': 'a' * 40, 'license': 'apache-2.0', 'format': 'safetensors',
                'files': {n: {'byte_size': r['byte_size'], 'sha256': r['sha256']} for n, r in self.files.items()}}
        item = launch_import(plan, name='Expired', tenant=self.tenant.pk, project=self.project, pool=pool,
                             accepted_license='apache-2.0', idempotency_key='expiry-1')
        claim = claim_job(worker)
        def expired(item, name, pin, context):
            from modelanvil.jobs.models import JobAttempt
            JobAttempt.all_objects.filter(pk=context.attempt.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
            return self.files[name]
        with patch('modelanvil.runners.model_catalog.download_file', side_effect=expired):
            outcome = execute_claim(worker, claim, model_import_executor)
        self.assertFalse(outcome['committed'])
        item.refresh_from_db()
        self.assertIsNone(item.candidate)
        self.assertEqual(ModelVersion.all_objects.count(), 0)
