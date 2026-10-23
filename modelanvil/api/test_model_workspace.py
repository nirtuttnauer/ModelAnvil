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
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.core.tenancy import set_active_project, set_active_tenant
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.jobs.models import Job, Worker, WorkerPool, claim_job
from modelanvil.jobs.executor import execute_claim
from modelanvil.runners.model_catalog import _store, model_import_executor
from modelanvil.runners.models import InferenceRequest, ModelImport, ModelVersion


@skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('transformers'), 'Optional transformer runtime is not installed')
class ModelWorkspaceTests(TransactionTestCase):
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
        # Transformers 5 stores special tokens in tokenizer_config; the pinned base also has this file.
        (Path(cls.fixture.name) / "special_tokens_map.json").write_text(json.dumps(tokenizer.special_tokens_map))
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

    def test_stream_withholds_prefetched_output_after_authority_or_input_changes(self):
        from django.utils import timezone
        from datetime import timedelta
        cases = ['key', 'expired', 'role', 'model', 'tokenizer', 'artifact']
        for case in cases:
            with self.subTest(case=case):
                imported = self.import_model(idempotency_key='authority-' + case, name='Authority ' + case)
                self.assertEqual(imported.status_code, 201, imported.content)
                version = ModelVersion.all_objects.get(model_version_id=imported.data['candidate_id'])
                body = {'model': str(version.model_version_id), 'messages': [{'role': 'user', 'content': 'hello'}],
                        'max_tokens': 4, 'stream': True}
                response = self.client.post('/api/v1/inference/chat/completions', body, format='json')
                self.assertEqual(response.status_code, 200)
                iterator = iter(response.streaming_content)
                self.assertIn('assistant', next(iterator).decode())
                if case == 'key': ApiKey.objects.filter(pk=self.key.pk).update(is_active=False)
                elif case == 'expired': ApiKey.objects.filter(pk=self.key.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
                elif case == 'role': ApiKey.objects.filter(pk=self.key.pk).update(role=Role.VIEWER)
                elif case == 'model': ModelVersion.all_objects.filter(pk=version.pk).update(state='archived')
                elif case == 'tokenizer': type(version.tokenizer).all_objects.filter(pk=version.tokenizer_id).update(compatibility={'changed': True})
                else: Artifact.all_objects.filter(artifact_id=self.files['model.safetensors']['artifact_id']).update(state='staging')
                events = b''.join(iterator).decode(); response.close()
                self.assertIn('inference_error', events)
                self.assertNotIn('"content":', events)
                self.assertEqual(InferenceRequest.all_objects.latest('created_at').status, 'failed')
                ApiKey.objects.filter(pk=self.key.pk).update(is_active=True, expires_at=None, role=Role.ENGINEER)
                Artifact.all_objects.filter(artifact_id=self.files['model.safetensors']['artifact_id']).update(state='committed')

    def test_buffered_completion_withholds_all_text_when_key_is_revoked_during_generation(self):
        from modelanvil.api.views import model_workspace
        original = model_workspace.generate
        imported = self.import_model()
        def revoked(session, *args, **kwargs):
            for index, part in enumerate(original(session, *args, **kwargs)):
                if index == 1:
                    ApiKey.objects.filter(pk=self.key.pk).update(is_active=False)
                yield part
        body = {'model': imported.data['candidate_id'], 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 4}
        with patch.object(model_workspace, 'generate', side_effect=revoked):
            response = self.client.post('/api/v1/inference/chat/completions', body, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('choices', response.json())
        self.assertEqual(InferenceRequest.all_objects.latest('created_at').status, 'failed')

    def test_stream_context_does_not_overwrite_a_later_request_project(self):
        from modelanvil.core.tenancy import get_active_project
        imported = self.import_model()
        body = {'model': imported.data['candidate_id'], 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 4, 'stream': True}
        response = self.client.post('/api/v1/inference/chat/completions', body, format='json')
        self.assertEqual(response.status_code, 200)
        other = Project.all_objects.create(tenant_id=self.tenant.pk, team=self.project.team, name='Later', slug='later')
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=other, name='later', role=Role.ENGINEER, secret_hash=hashed)
        later = APIClient(); later.credentials(HTTP_AUTHORIZATION='Bearer ' + secret)
        self.assertEqual(later.get('/api/v1/inference/models/').status_code, 200)
        set_active_tenant(self.tenant.pk); set_active_project(other.pk)
        iterator = iter(response.streaming_content)
        events = next(iterator).decode()
        self.assertEqual(get_active_project(), other.pk)
        events += next(iterator).decode()
        self.assertEqual(get_active_project(), other.pk)
        events += b''.join(iterator).decode(); response.close()
        self.assertNotIn('inference_error', events)
        self.assertIn('[DONE]', events)

    def test_grant_revocation_stops_an_already_loaded_stream(self):
        from modelanvil.identity.models import ProjectGrant
        imported = self.import_model()
        other = Project.all_objects.create(tenant_id=self.tenant.pk, team=self.project.team, name='Receiver', slug='receiver')
        grant = ProjectGrant.objects.create(tenant_id=self.tenant.pk, project=self.project,
            granted_to_project=other, resource_type='all')
        ApiKey.objects.filter(pk=self.key.pk).update(project=None)
        body = {'model': imported.data['candidate_id'], 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 4, 'stream': True}
        response = self.client.post('/api/v1/inference/chat/completions', body, format='json', HTTP_X_PROJECT_ID=str(other.pk))
        self.assertEqual(response.status_code, 200)
        iterator = iter(response.streaming_content); next(iterator)
        grant.delete()
        events = b''.join(iterator).decode(); response.close()
        self.assertIn('inference_error', events)
        self.assertNotIn('"content":', events)

    def test_managed_instruction_bases_are_chat_snapshots_only_with_exact_allowlisted_files(self):
        from modelanvil.runners.inference import snapshot, local_session
        from modelanvil.runners.training import hf_runtime
        imported = self.import_model()
        version = ModelVersion.all_objects.get(model_version_id=imported.data['candidate_id'])
        hashes = {name: ref['sha256'] for name, ref in self.files.items()}
        for source, constant in ((hf_runtime.GUIDED_SOURCE, 'GUIDED_FILE_HASHES'), (hf_runtime.LARGE_GUIDED_SOURCE, 'LARGE_GUIDED_FILE_HASHES')):
            with self.subTest(source=source), patch.object(hf_runtime, constant, hashes):
                manifest = _store(io.BytesIO(json.dumps({'source': source, 'files': self.files}).encode()),
                    tenant=self.tenant.pk, project=self.project.pk, name='snapshot.json')
                version.metadata = {'managed_local': True, 'source': source, 'snapshot_manifest': manifest}
                version.artifact_manifest_id = manifest['artifact_id']; version.architecture_ref = hf_runtime.RUNTIME_ID
                ModelVersion.all_objects.filter(pk=version.pk).update(metadata=version.metadata,
                    artifact_manifest_id=version.artifact_manifest_id, architecture_ref=version.architecture_ref)
                catalog = self.client.get('/api/v1/inference/models/')
                self.assertEqual([row['id'] for row in catalog.data['data']], [str(version.model_version_id)])
                plan = snapshot(version, self.tenant.pk, self.project.pk)
                self.assertEqual(plan['format'], 'safetensors')
                self.assertEqual(plan['guided_large'], source == hf_runtime.LARGE_GUIDED_SOURCE)
                with local_session(version, tenant=self.tenant.pk, project=self.project.pk) as session:
                    self.assertEqual(session['format'], 'safetensors')
                for changes in ({'source': {}}, {'managed_local': False}):
                    version.metadata.update(changes)
                    with self.assertRaises(ValueError):
                        snapshot(version, self.tenant.pk, self.project.pk)
                    version.metadata = {'managed_local': True, 'source': source, 'snapshot_manifest': manifest}
                with patch.object(hf_runtime, constant, {**hashes, 'config.json': '0' * 64}):
                    with self.assertRaises(ValueError):
                        snapshot(version, self.tenant.pk, self.project.pk)

    def test_real_local_import_repeat_and_completion_matches_framework(self):
        response = self.import_model()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.import_model().data['candidate_id'], response.data['candidate_id'])
        self.assertEqual(ModelImport.all_objects.count(), 1)
        version = ModelVersion.all_objects.get(model_version_id=response.data['candidate_id'])
        compatibility = self.client.get(f'/api/v1/model-versions/{version.model_version_id}/').data['capabilities']
        self.assertTrue(compatibility['chat']['eligible'])
        self.assertIn('cpu', compatibility['chat']['devices'])
        self.assertFalse(compatibility['train']['eligible'])
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

    def test_import_refuses_safe_but_missing_or_mismatched_tensors(self):
        import torch
        from safetensors.torch import load_file, save
        original=load_file(str(Path(self.fixture.name)/'model.safetensors'))
        for tensors in [dict(list(original.items())[1:]),{**original,next(iter(original)):torch.zeros((1,1))}]:
            ref=_store(io.BytesIO(save(tensors)),tenant=self.tenant.pk,project=self.project.pk,name='model.safetensors')
            failed=self.import_model(files={**self.files,'model.safetensors':ref})
            self.assertEqual(failed.status_code,400,failed.content)
            self.assertEqual(ModelVersion.all_objects.count(),0)

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
        from modelanvil.jobs.setup import observe_local_worker
        self.key.role = Role.ADMIN; self.key.save(update_fields=['role'])
        registered = self.client.post('/api/v1/workers/setup/', {'worker_name':'acquisition', 'pool':'imports', 'profile':'model-import'}, format='json')
        self.assertEqual(registered.status_code, 201, registered.json())
        self.assertIsNone(registered.data['runner_id'])
        worker = Worker.all_objects.get(pk=registered.data['worker_id']); pool = worker.pool
        observe_local_worker(worker, 'model-import', registered.data['worker_token'])
        plan = {'repo_id': 'owner/model', 'revision': 'a' * 40, 'license': 'apache-2.0', 'format': 'safetensors',
                'files': {n: {'byte_size': r['byte_size'], 'sha256': r['sha256']} for n, r in self.files.items()}}
        item = launch_import(plan, name='Downloaded', tenant=self.tenant.pk, project=self.project, pool=pool,
                             accepted_license='apache-2.0', idempotency_key='hub-1')
        self.assertEqual(item.job.project_id,self.project.pk)
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

    def test_device_contention_refuses_allocation_and_close_releases_admission(self):
        from modelanvil.device_admission import device_available, device_lease
        imported = self.import_model()
        body = {'model': imported.data['candidate_id'], 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 2}
        with device_lease('cpu'):
            failed = self.client.post('/api/v1/inference/chat/completions', body, format='json')
            self.assertEqual(failed.status_code, 400, failed.content)
        stream = self.client.post('/api/v1/inference/chat/completions', {**body, 'stream': True}, format='json')
        self.assertEqual(stream.status_code, 200)
        self.assertFalse(device_available('cpu'))
        stream.close()
        self.assertTrue(device_available('cpu'))
        self.assertEqual(self.client.post('/api/v1/inference/chat/completions', body, format='json').status_code, 200)

    def test_conversation_configuration_accepts_and_preserves_chat_comparison_mode(self):
        imported = self.import_model()
        config = {'model': imported.data['candidate_id'], 'compare_model': None, 'compare_device': 'cpu',
                  'device': 'cpu', 'max_tokens': 128, 'temperature': 0, 'seed': 42, 'prompt_format': 'model', 'system_prompt': ''}
        for mode in ('blind', 'base-trained'):
            with self.subTest(mode=mode):
                response = self.client.post('/api/v1/chat-conversations/', {'title': 'Saved chat',
                    'messages': [{'role': 'user', 'content': 'hello'}], 'configuration': {**config, 'comparison_mode': mode}}, format='json')
                self.assertEqual(response.status_code, 201, response.content)
                path = f"/api/v1/chat-conversations/{response.data['conversation_id']}/"
                self.assertEqual(self.client.get(path).data['configuration']['comparison_mode'], mode)
        for extra in ({'comparison_mode': 'unknown'}, {'unrecognized_option': True}):
            response = self.client.post('/api/v1/chat-conversations/', {'title': 'Invalid chat',
                'messages': [], 'configuration': {**config, **extra}}, format='json')
            self.assertEqual(response.status_code, 400, response.content)

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

    def test_hub_credentials_are_explicitly_project_scoped(self):
        from modelanvil.runners.model_catalog import hub_token
        scope=f'{self.tenant.pk}:{self.project.pk}'
        with patch.dict('os.environ',{'HF_TOKEN':'ambient-test-credential'}), override_settings(MODELANVIL_HUB_TOKENS={scope:'scoped-test-credential'}):
            self.assertEqual(hub_token(self.tenant.pk,self.project.pk),'scoped-test-credential')
            self.assertIs(hub_token(self.tenant.pk,self.other.pk),False)

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
        with patch('requests.sessions.Session.get', return_value=Reply()) as request:
            ref = download_file(item, 'model.safetensors', pin, SimpleNamespace(heartbeat=lambda: True))
            self.assertEqual(request.call_args.kwargs['headers'], {'Range': 'bytes=6-'})
            self.assertIn(item.revision, request.call_args.args[0])
        self.assertEqual(ref['sha256'], pin['sha256'])
        with self.assertRaisesMessage(ValueError, 'checksum'):
            download_file(item, 'model.safetensors', {**pin, 'sha256': '0' * 64}, SimpleNamespace(heartbeat=lambda: True))
        self.assertFalse(path.exists())

    def test_download_contains_actual_verified_weights_and_fails_on_corruption(self):
        import zipfile
        from modelanvil.runners.models import TrainingRun
        from modelanvil.runners.training import hf_runtime
        imported = self.import_model()
        version = ModelVersion.all_objects.get(model_version_id=imported.data['candidate_id'])
        run = TrainingRun.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
            tokenizer_version=version.tokenizer, base_model_version=version, status='completed',
            hardware_config={'execution_mode': 'worker', 'pins': {'runtime': hf_runtime.RUNTIME_ID}})
        bundle = {'files': {n: r for n, r in self.files.items() if n in hf_runtime.FILE_HASHES},
                  'provenance.json': {'run_id': str(run.run_id)}}
        path = f'/api/v1/training-runs/{run.run_id}/download/'
        with patch('modelanvil.api.views.training_views.TrainingRunViewSet._worker_bundle', return_value=bundle):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            raw = b''.join(response.streaming_content); response.close()
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(archive.read('model.safetensors'), (Path(self.fixture.name) / 'model.safetensors').read_bytes())
                self.assertEqual(json.loads(archive.read('modelanvil-provenance.json')), bundle)
            with patch('modelanvil.runners.training.registry.verify_bundle', side_effect=AssertionError('Manifest downloads must not allocate a model')):
                manifest = self.client.get(path + '?export_format=json')
                self.assertEqual(manifest.status_code, 200)
                self.assertEqual(json.loads(b''.join(manifest.streaming_content)), bundle)
                manifest.close()
            artifact = Artifact.all_objects.get(artifact_id=self.files['model.safetensors']['artifact_id'])
            from modelanvil.artifacts.storage import artifact_storage_backend
            artifact_storage_backend()._path(self.tenant.pk, artifact.object_key, create_parent=False).write_bytes(b'corrupt')
            self.assertEqual(self.client.get(path).status_code, 400)
            secret, hashed = generate_api_key()
            ApiKey.objects.create(tenant=self.tenant, project=self.other, name='other download key', role=Role.ENGINEER, secret_hash=hashed)
            other = APIClient(); other.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
            self.assertEqual(other.get(path).status_code, 404)

    def test_adapter_export_contains_only_adapter_files_and_base_provenance(self):
        import zipfile
        from modelanvil.runners.models import TrainingRun
        from modelanvil.runners.training import hf_runtime
        imported = self.import_model()
        version = ModelVersion.all_objects.get(model_version_id=imported.data['candidate_id'])
        run = TrainingRun.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
            tokenizer_version=version.tokenizer, base_model_version=version, status='completed', recipe_type='lora_adapter',
            hardware_config={'execution_mode': 'worker', 'pins': {'runtime': hf_runtime.RUNTIME_ID}})
        # File-transfer fixture: archive selection is tested independently of adapter loading.
        files = dict(self.files)
        for name, data in [('adapter_config.json', b'{"base_model_name_or_path":"pinned-base"}'), ('adapter_model.safetensors', b'fixture-adapter-bytes')]:
            files[name] = _store(io.BytesIO(data), tenant=self.tenant.pk, project=self.project.pk, name=name)
        bundle = {'files': files, 'source': hf_runtime.SOURCE, 'provenance.json': {'run_id': str(run.run_id)}}
        path = f'/api/v1/training-runs/{run.run_id}/'
        self.assertEqual([o['format'] for o in self.client.get(path).data['export_options']], ['native', 'adapter', 'json'])
        with patch('modelanvil.api.views.training_views.TrainingRunViewSet._worker_bundle', return_value=bundle):
            response = self.client.get(path + 'download/?export_format=adapter')
            self.assertEqual(response.status_code, 200)
            raw = b''.join(response.streaming_content); response.close()
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(set(archive.namelist()), {'adapter_config.json', 'adapter_model.safetensors', 'modelanvil-provenance.json'})
                self.assertEqual(archive.read('adapter_model.safetensors'), b'fixture-adapter-bytes')
                provenance = json.loads(archive.read('modelanvil-provenance.json'))
                self.assertEqual(provenance['source'], hf_runtime.SOURCE)
                self.assertEqual(provenance['included_files'], ['adapter_config.json', 'adapter_model.safetensors'])
            run.status = 'pending'; run.save(update_fields=['status'])
            self.assertEqual(self.client.get(path).data['export_options'], [])
            self.assertEqual(self.client.get(path + 'download/?export_format=adapter').status_code, 400)

    def test_synthetic_download_registration_requires_post_and_write_permission(self):
        from modelanvil.runners.models import TrainingRun
        imported = self.import_model()
        version = ModelVersion.all_objects.get(model_version_id=imported.data['candidate_id'])
        run = TrainingRun.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
            tokenizer_version=version.tokenizer, status='completed', hardware_config={'execution_mode': 'simulation'})
        path = f'/api/v1/training-runs/{run.run_id}/download/?export_format=json'
        bundle = {'fixture': True}
        with patch('modelanvil.api.views.training_views.TrainingEngine.export_candidate_model', return_value=(version, bundle)) as export, patch('modelanvil.runners.training.registry.verify_bundle'):
            self.assertEqual(self.client.get(path).status_code, 400); export.assert_not_called()
            response = self.client.post(path, {}, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(b''.join(response.streaming_content)), bundle); response.close()
            secret, hashed = generate_api_key()
            ApiKey.objects.create(tenant=self.tenant, project=self.project, name='viewer export key', role=Role.VIEWER, secret_hash=hashed)
            viewer = APIClient(); viewer.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
            export.reset_mock()
            self.assertEqual(viewer.post(path, {}, format='json').status_code, 403); export.assert_not_called()

    def test_failed_import_resumes_verified_files_and_preserves_worker_history(self):
        from modelanvil.runners.model_catalog import launch_import
        from modelanvil.jobs.models import JobAttempt
        pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='retry', queue_name='retry')
        worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=pool, name='local', slots=1, capabilities={'model_import': True})
        plan = {'repo_id': 'owner/model', 'revision': 'a'*40, 'license': 'apache-2.0', 'format': 'safetensors',
            'files': {n: {'byte_size': r['byte_size'], 'sha256': r['sha256']} for n, r in self.files.items()}}
        item = launch_import(plan, name='Resumable', tenant=self.tenant.pk, project=self.project, pool=pool,
            accepted_license='apache-2.0', idempotency_key='resume-1')
        calls = []
        def partial(item, name, pin, context):
            calls.append(name)
            if len(calls) == 2: raise ValueError('Interrupted transfer.')
            return self.files[name]
        with patch('modelanvil.runners.model_catalog.download_file', side_effect=partial):
            result = execute_claim(worker, claim_job(worker), model_import_executor)
        self.assertTrue(result['committed']); item.refresh_from_db(); self.assertEqual(item.status, 'failed')
        self.assertEqual(len(item.acquired_files), 1); self.assertIsNone(item.candidate_id)
        resumed = self.client.post(f'/api/v1/model-imports/{item.import_id}/resume/', {}, format='json')
        self.assertEqual(resumed.status_code, 200, resumed.data)
        self.assertEqual(self.client.post(f'/api/v1/model-imports/{item.import_id}/resume/', {}, format='json').status_code, 200)
        second_calls = []
        def download(item, name, pin, context): second_calls.append(name); return self.files[name]
        with patch('modelanvil.runners.model_catalog.download_file', side_effect=download):
            result = execute_claim(worker, claim_job(worker), model_import_executor)
        self.assertTrue(result['committed']); item.refresh_from_db(); self.assertEqual(item.status, 'completed')
        self.assertNotIn(calls[0], second_calls)
        self.assertEqual(JobAttempt.all_objects.filter(job=item.job).count(), 2)
        self.assertEqual(self.client.post(f'/api/v1/model-imports/{item.import_id}/resume/', {}, format='json').status_code, 400)

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

    def test_completed_adapter_candidate_chat_uses_verified_base_and_rejects_lineage_changes(self):
        import torch
        import shutil
        from safetensors.torch import save_file
        from modelanvil.runners.models import Model, TrainingRun, TrainingCheckpoint
        from modelanvil.runners.training import hf_runtime as hf
        from modelanvil.runners.training.runtime import digest
        imported = self.import_model()
        base = ModelVersion.all_objects.get(model_version_id=imported.data['candidate_id'])
        # A small real tensor fixture exercises candidate publication, not hardware qualification.
        ModelVersion.all_objects.filter(pk=base.pk).update(architecture_ref=hf.RUNTIME_ID)
        base.refresh_from_db()
        files = {n: self.files[n] for n in hf.FILE_HASHES}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in files:
                shutil.copyfile(Path(self.fixture.name) / name, directory / name)
            adapter = hf._recipe_model(directory, 'lora_adapter', training=True)
            optimizer = torch.optim.AdamW([p for p in adapter.parameters() if p.requires_grad], lr=0.001, foreach=False)
            ids = torch.tensor([[3, 4, 3, 4]])
            adapter(input_ids=ids, labels=ids).loss.backward(); optimizer.step()
            adapter.save_pretrained(temp, safe_serialization=True, save_embedding_layers=False)
            save_file(hf._optimizer_state(adapter, optimizer), str(directory / 'optimizer.safetensors'))
            for name in ('adapter_config.json', 'adapter_model.safetensors', 'optimizer.safetensors'):
                with (directory / name).open('rb') as source:
                    ref = _store(source, tenant=self.tenant.pk, project=self.project.pk, name=name)
                if name == 'optimizer.safetensors':
                    adam = ref
                else:
                    files[name] = ref
        pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name='candidate-fixture')
        job = Job.objects.create(tenant_id=self.tenant.pk, pool=pool, name='Completed tensor fixture', status='succeeded')
        pins = {'runtime': hf.RUNTIME_ID, 'recipe': 'lora_adapter', 'config': json.loads((Path(self.fixture.name) / 'config.json').read_text())}
        run = TrainingRun.all_objects.create(tenant_id=self.tenant.pk, project=self.project, job=job,
            tokenizer_version=base.tokenizer, base_model_version=base, status='completed', recipe_type='lora_adapter',
            current_step=1, total_steps=1, hardware_config={'execution_mode': 'worker', 'pins': pins})
        state = {'pins': pins, 'step': 1, 'run_id': str(run.run_id), 'files': files, 'adam': adam,
            'tokenizer': {}, 'optimizer': {**hf.OPTIMIZER, 'updates': 1}, 'metrics': {}}
        checkpoint = TrainingCheckpoint.all_objects.create(tenant_id=self.tenant.pk, training_run=run,
            step=1, weights_manifest=state, state_digest=digest(state))
        bundle = hf.checkpoint_bundle(run, checkpoint)
        manifest = _store(io.BytesIO(json.dumps(bundle).encode()), tenant=self.tenant.pk, project=self.project.pk, name='candidate.json')
        model = Model.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='Trained adapter')
        candidate = ModelVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project, model=model,
            tokenizer=base.tokenizer, architecture_ref=hf.RUNTIME_ID, artifact_manifest_id=manifest['artifact_id'],
            metadata={'source_run_id': str(run.run_id), 'checkpoint_digest': checkpoint.state_digest})
        run.output_model_version = candidate; run.save()
        catalog = self.client.get('/api/v1/inference/models/').data['data']
        entry = next(m for m in catalog if m['id'] == str(candidate.model_version_id))
        self.assertEqual(entry['base_model_id'], str(base.model_version_id))
        self.assertEqual(entry['training_run_id'], str(run.run_id))
        body = {'model': str(candidate.model_version_id), 'messages': [{'role': 'user', 'content': 'hello world'}], 'max_tokens': 2}
        with patch('socket.socket.connect', side_effect=AssertionError('Candidate chat must stay offline')) as network:
            response = self.client.post('/api/v1/inference/chat/completions', body, format='json')
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.data['usage']['prompt_tokens'], 2)
            network.assert_not_called()
        self.assertEqual(self.client.patch(f'/api/v1/model-versions/{candidate.model_version_id}/', {'metadata': {}}, format='json').status_code, 400)
        candidate.metadata = {}; self.assertRaises(ValidationError, candidate.save)
        TrainingCheckpoint.all_objects.filter(pk=checkpoint.pk).update(state_digest='0' * 64)
        self.assertEqual(self.client.post('/api/v1/inference/chat/completions', body, format='json').status_code, 400)

    def test_comparisons_preserve_verified_outputs_hide_identities_and_record_one_vote(self):
        from modelanvil.runners.models import ChatComparison
        first = self.import_model().data['candidate_id']
        second = self.import_model(name='Second snapshot', idempotency_key='second').data['candidate_id']
        messages = [{'role': 'user', 'content': 'hello world'}]
        body = {'messages': messages, 'max_tokens': 4}
        responses = []
        for model in (first, second):
            response = self.client.post('/api/v1/inference/chat/completions', {**body, 'model': model}, format='json')
            self.assertEqual(response.status_code, 200, response.content)
            responses.append({'request_id': response.data['id'].removeprefix('chatcmpl-'),
                'text': response.data['choices'][0]['message']['content']})
        conversation = self.client.post('/api/v1/chat-conversations/', {'title': 'Paired output',
            'messages': messages, 'configuration': {'model': first, 'compare_model': second, 'max_tokens': 4}}, format='json')
        payload = {'conversation_id': conversation.data['conversation_id'], 'messages': messages, 'responses': responses}
        saved = self.client.post('/api/v1/chat-comparisons/', payload, format='json')
        self.assertEqual(saved.status_code, 201, saved.content)
        self.assertEqual([side['label'] for side in saved.data['sides']], ['A', 'B'])
        self.assertTrue(all(set(side) == {'label', 'text'} for side in saved.data['sides']))
        repeated = self.client.post('/api/v1/chat-comparisons/', {**payload, 'responses': list(reversed(responses))}, format='json')
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(repeated.data['sides'], saved.data['sides'])
        self.assertEqual(ChatComparison.all_objects.count(), 1)
        path = f"/api/v1/chat-comparisons/{saved.data['comparison_id']}/"
        self.assertEqual(self.client.get(path).data['sides'], saved.data['sides'])
        self.assertTrue(all('role' not in side for side in self.client.get(path + '?view=base-trained').data['sides']))
        from modelanvil.runners.models import TrainingRun
        base = ModelVersion.all_objects.get(model_version_id=first)
        trained = ModelVersion.all_objects.get(model_version_id=second)
        pool = WorkerPool.all_objects.create(tenant_id=self.tenant.pk, name='comparison lineage')
        job = Job.all_objects.create(tenant_id=self.tenant.pk, project=self.project, pool=pool, name='Completed lineage fixture', status='succeeded')
        TrainingRun.all_objects.create(tenant_id=self.tenant.pk, project=self.project, job=job, status='completed',
            base_model_version=base, output_model_version=trained, tokenizer_version=base.tokenizer)
        named = self.client.get(path + '?view=base-trained')
        self.assertEqual({side['role']: side['model'] for side in named.data['sides']}, {'base': first, 'trained': second})
        self.assertTrue(all('name' in side for side in named.data['sides']))
        self.assertEqual(self.client.get(path).data['sides'], saved.data['sides'])
        voted = self.client.post(path + 'vote/', {'vote': 'A'}, format='json')
        self.assertEqual(voted.status_code, 200, voted.content)
        self.assertEqual({s['model'] for s in voted.data['sides']}, {first, second})
        self.assertTrue(all(s['usage']['total_tokens'] > 0 for s in voted.data['sides']))
        self.assertEqual(self.client.post(path + 'vote/', {'vote': 'A'}, format='json').status_code, 200)
        self.assertEqual(self.client.post(path + 'vote/', {'vote': 'B'}, format='json').status_code, 409)
        self.assertEqual(self.client.patch(path, {'vote': 'B'}, format='json').status_code, 405)
        bad = [{**responses[0], 'text': 'fabricated output'}, responses[1]]
        self.assertEqual(self.client.post('/api/v1/chat-comparisons/', {**payload, 'responses': bad}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/v1/chat-comparisons/', {**payload, 'messages': [{'role': 'user', 'content': 'different'}]}, format='json').status_code, 400)
        changed = self.client.post('/api/v1/inference/chat/completions', {**body, 'model': second, 'temperature': 0.5}, format='json')
        mismatch = [responses[0], {'request_id': changed.data['id'].removeprefix('chatcmpl-'), 'text': changed.data['choices'][0]['message']['content']}]
        self.assertEqual(self.client.post('/api/v1/chat-comparisons/', {**payload, 'responses': mismatch}, format='json').status_code, 400)
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=self.other, name='comparison other project', role=Role.ENGINEER, secret_hash=hashed)
        other = APIClient(); other.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(other.get('/api/v1/chat-comparisons/').data['results'], [])
        self.assertEqual(other.post('/api/v1/chat-comparisons/', payload, format='json').status_code, 400)
        self.assertEqual(other.post(path + 'vote/', {'vote': 'A'}, format='json').status_code, 404)
        # A saved comparison cannot retain access to a model after its grant is revoked.
        from modelanvil.identity.models import ProjectGrant
        ModelVersion.all_objects.filter(pk=trained.pk).update(project=self.other)
        grant = ProjectGrant.all_objects.create(tenant_id=self.tenant.pk, project=self.other,
            granted_to_project=self.project, resource_type='modelversion', resource_id=trained.model_version_id)
        self.assertEqual(self.client.get(path).status_code, 200)
        grant.delete()
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/chat-comparisons/').data['results'], [])
        self.assertEqual(self.client.post('/api/v1/chat-comparisons/', payload, format='json').status_code, 400)
