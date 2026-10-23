"""Real HTTP provider transport, scoped opt-in, measured provenance and revocation."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import tempfile
import threading
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.core.models import ProjectPrivacyPolicy
from modelanvil.core.tenancy import reset_context
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.runners import external_inference
from modelanvil.runners.models import InferenceRequest, Model, ModelVersion, TokenizerVersion
from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
from modelanvil.runners.training.runtime import RUNTIME_ID


@override_settings(ALLOWED_HOSTS=['testserver'], DEBUG=True)
class ExternalChatTests(TransactionTestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.tenant = Tenant.objects.create(slug='external', name='External')
        team = Team.objects.create(tenant_id=self.tenant.pk, slug='team', name='Team')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=team, slug='one', name='One')
        self.other = Project.objects.create(tenant_id=self.tenant.pk, team=team, slug='other', name='Other')
        secret, hashed = generate_api_key()
        self.key = ApiKey.objects.create(tenant=self.tenant, project=self.project, name='local', role=Role.ADMIN, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + secret)
        self.addCleanup(reset_context)
        self.received = []; self.mode = 'normal'
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                owner.received.append({'path': self.path, 'authorization': self.headers.get('Authorization'),
                    'body': json.loads(self.rfile.read(int(self.headers['Content-Length'])))})
                if owner.mode == 'redirect':
                    self.send_response(307); self.send_header('Location', owner.endpoint.replace('/chat/completions', '/stolen')); self.end_headers(); return
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                usage = {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}
                if owner.mode == 'bad_usage': usage['total_tokens'] = 8
                chunks = [{'choices': [{'delta': {'content': 'hello'}, 'finish_reason': None}]},
                    {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
                if owner.mode != 'no_usage': chunks.append({'choices': [], 'usage': usage})
                if owner.mode == 'error': chunks = [{'error': {'message': 'secret-test-upstream-key'}}]
                for value in chunks:
                    value['model'] = 'explicit-upstream-revision'
                    self.wfile.write(('data: ' + json.dumps(value) + '\r\n\r\n').encode()); self.wfile.flush()
                self.wfile.write(b'data: [DONE]\r\n\r\n'); self.wfile.flush()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.endpoint = f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.config = {f'{self.tenant.pk}:{self.project.pk}': {'chosen': {'name': 'Selected compatible provider',
            'endpoint': self.endpoint, 'model': 'explicit-upstream-revision', 'credential_id': 'qualification-credential'}}}
        self.secrets = {f'{self.tenant.pk}:{self.project.pk}': {'qualification-credential': 'secret-test-upstream-key'}}
        override = override_settings(MODELANVIL_EXTERNAL_PROVIDERS=self.config,
            MODELANVIL_EXTERNAL_PROVIDER_KEYS=self.secrets,
            MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': self.root.name})
        override.enable(); self.addCleanup(override.disable)
        self.target = external_inference.installed_targets(self.tenant.pk, self.project.pk)[0]
        self.body = {'model': self.target['id'], 'messages': [{'role': 'user', 'content': 'a'}],
            'device': 'external', 'max_tokens': 2, 'prompt_format': 'model', 'stream': False,
            'stream_options': {'include_usage': True}}

    def enable(self):
        response = self.client.put('/api/v1/privacy/', {'offline': False, 'acquisition_origins': [],
            'measurement_retention_days': 30, 'external_generation_targets': [self.target['id']]}, format='json')
        self.assertEqual(response.status_code, 200, response.content)

    def complete(self, **changes):
        response = self.client.post('/api/v1/inference/chat/completions', {**self.body, **changes}, format='json')
        self.assertEqual(response.status_code, 200, response.content if not response.streaming else '')
        return response

    def test_default_opt_in_scope_and_real_transport_never_return_credentials(self):
        privacy = self.client.get('/api/v1/privacy/').json()
        self.assertFalse(privacy['external_generation']); self.assertEqual(privacy['installed_generation_targets'], [self.target])
        self.assertNotIn('secret-test-upstream-key', json.dumps(privacy))
        from django.views.debug import SafeExceptionReporterFilter
        self.assertEqual(SafeExceptionReporterFilter().get_safe_settings()['MODELANVIL_EXTERNAL_PROVIDER_KEYS'], '********************')
        self.assertEqual(self.client.get('/api/v1/inference/models/').json()['data'], [])
        with patch('socket.socket.connect') as connect:
            self.assertEqual(self.client.post('/api/v1/inference/chat/completions', self.body, format='json').status_code, 404)
            connect.assert_not_called()
        self.enable(); result = self.complete().json()
        self.assertEqual(result['choices'][0]['message']['content'], 'hello')
        self.assertEqual(result['usage'], {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7})
        self.assertEqual(self.received[0]['authorization'], 'Bearer secret-test-upstream-key')
        self.assertEqual(self.received[0]['body']['messages'], self.body['messages'])
        request = InferenceRequest.all_objects.get()
        self.assertIsNone(request.model_version_id); self.assertEqual(request.provider_snapshot, {**self.target, 'reported_model': 'explicit-upstream-revision'})
        self.assertEqual(request.status, 'completed'); self.assertGreater(request.elapsed_seconds, 0)
        self.assertNotIn('secret-test-upstream-key', json.dumps(request.configuration))
        other_secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=self.other, name='other', role=Role.ADMIN, secret_hash=hashed)
        other = APIClient(); other.credentials(HTTP_AUTHORIZATION='Bearer ' + other_secret)
        self.assertEqual(other.get('/api/v1/inference/models/').json()['data'], [])
        self.assertEqual(other.post('/api/v1/inference/chat/completions', self.body, format='json').status_code, 404)
        ApiKey.objects.filter(pk=self.key.pk).update(role=Role.ENGINEER)
        self.assertEqual(self.client.put('/api/v1/privacy/', {}, format='json').status_code, 403)

    def test_live_revocation_withholds_prefetched_output_and_offline_prevents_connection(self):
        self.enable()
        response = self.complete(stream=True)
        iterator = iter(response.streaming_content)
        self.assertIn(b'assistant', next(iterator))
        ProjectPrivacyPolicy.all_objects.filter(project=self.project).update(external_generation_targets=[])
        remaining = b''.join(iterator)
        self.assertNotIn(b'hello', remaining); self.assertIn(b'inference_error', remaining)
        self.assertEqual(InferenceRequest.all_objects.get().status, 'failed')
        self.enable()
        with override_settings(MODELANVIL_OFFLINE=True), patch('socket.socket.connect') as connect:
            self.assertEqual(self.client.post('/api/v1/inference/chat/completions', self.body, format='json').status_code, 404)
            connect.assert_not_called()

    def test_redirect_errors_and_invalid_usage_fail_without_secret_disclosure(self):
        self.enable()
        for mode in ('redirect', 'error', 'bad_usage'):
            self.mode = mode
            response = self.client.post('/api/v1/inference/chat/completions', self.body, format='json')
            self.assertEqual(response.status_code, 400, response.content)
            self.assertNotIn(b'secret-test-upstream-key', response.content)
            self.assertNotIn(b'/stolen', response.content)
        self.assertEqual(len(self.received), 3)
        self.assertEqual(InferenceRequest.all_objects.filter(status='completed').count(), 0)
        self.mode = 'normal'
        for fields in ({'endpoint': self.endpoint}, {'api_key': 'untrusted-key'}, {'prompt_format': 'plain'}):
            self.assertEqual(self.client.post('/api/v1/inference/chat/completions', {**self.body, **fields}, format='json').status_code, 400)
        self.assertEqual(len(self.received), 3)

    def test_missing_upstream_usage_remains_unavailable_and_stream_disconnect_cancels(self):
        self.enable(); self.mode = 'no_usage'
        result = self.complete().json()
        self.assertIsNone(result['usage']); self.assertIsNone(InferenceRequest.all_objects.get().usage)
        response = self.complete(stream=True); iterator = iter(response.streaming_content)
        next(iterator); response.close()
        self.assertEqual(InferenceRequest.all_objects.filter(status='cancelled').count(), 1)

    def test_credential_rotation_and_role_revocation_stop_existing_streams(self):
        self.enable()
        for change in ('credential', 'role'):
            with self.subTest(change=change):
                response = self.complete(stream=True); iterator = iter(response.streaming_content)
                next(iterator)
                if change == 'credential':
                    self.secrets[f'{self.tenant.pk}:{self.project.pk}']['qualification-credential'] = 'rotated-test-key'
                else:
                    ApiKey.objects.filter(pk=self.key.pk).update(role=Role.VIEWER)
                remaining = b''.join(iterator)
                self.assertNotIn(b'hello', remaining); self.assertIn(b'inference_error', remaining)

    def test_upstream_protocol_bounds_and_installed_urls_fail_closed(self):
        def wire(values, done=True):
            return io.BytesIO((''.join('data: ' + json.dumps(v) + '\n\n' for v in values) + ('data: [DONE]\n\n' if done else '')).encode())
        invalid = [wire([{'choices': [{'delta': {'tool_calls': []}}]}]),
            wire([{'model': 'one', 'choices': []}, {'model': 'two', 'choices': []}]),
            wire([{'choices': [{'delta': {'content': 'x' * 32001}}]}]),
            wire([{'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]}]),
            wire([{'choices': [{'delta': {'content': 'unfinished'}}]}], done=False)]
        for response in invalid:
            with self.assertRaises((ValueError, TypeError)):
                list(external_inference.parts(response))
        for endpoint in ('http://untrusted.invalid/v1/chat/completions', 'https://user:password@provider.invalid/v1/chat/completions',
                         'https://provider.invalid/v1/chat/completions?api_key=secret'):
            self.config[f'{self.tenant.pk}:{self.project.pk}']['chosen']['endpoint'] = endpoint
            with self.assertRaises(ValueError):
                external_inference.configured(self.tenant.pk, self.project.pk)

    def local_model(self):
        tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef \n')]
        model = CausalTextModel(len(tokens), n_embd=4, lora_r=2, lora_alpha=4, seed=42)
        raw, manifest = pack_safetensors(model.export_tensors())
        bundle = {'config.json': {'runtime': RUNTIME_ID, 'vocab_size': len(tokens), 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
            'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(),
            'tokenizer_config.json': {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}}
        payload = json.dumps(bundle).encode()
        artifact = Artifact.all_objects.create(tenant_id=self.tenant.pk, project=self.project, storage_location_id='local',
            object_key='test/base.json', sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
        upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
        tokenizer = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Character', vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
        parent = Model.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Local numerical policy')
        return ModelVersion.objects.create(tenant_id=self.tenant.pk, project=self.project, model=parent, revision_no=1,
            tokenizer=tokenizer, architecture_ref=RUNTIME_ID, artifact_manifest_id=str(artifact.artifact_id), metadata={'weights_sha256': manifest['weights_sha256']})

    def test_local_external_comparison_requires_actual_identical_requests_and_stays_informal(self):
        self.enable(); local = self.local_model()
        first = self.complete().json()
        second = self.complete(model=str(local.model_version_id), device='cpu').json()
        config = {key: value for key, value in self.body.items() if key != 'messages'}
        config.update(compare_model=str(local.model_version_id), compare_device='cpu')
        response = self.client.post('/api/v1/chat-conversations/', {'title': 'Exact pair', 'messages': self.body['messages'], 'configuration': config}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        body = {'conversation_id': response.json()['conversation_id'], 'messages': self.body['messages'],
            'responses': [{'request_id': item['id'][9:], 'text': item['choices'][0]['message']['content']} for item in (first, second)]}
        saved = self.client.post('/api/v1/chat-comparisons/', body, format='json')
        self.assertEqual(saved.status_code, 201, saved.content)
        self.assertFalse(saved.json()['review_eligible'])
        self.assertTrue(all('model' not in side for side in saved.json()['sides']))
        path = '/api/v1/chat-comparisons/' + saved.json()['comparison_id'] + '/'
        voted = self.client.post(path + 'vote/', {'vote': 'tie'}, format='json')
        self.assertEqual(voted.status_code, 200, voted.content)
        external = next(side for side in voted.json()['sides'] if side['model'] == self.target['id'])
        self.assertEqual(external['destination'], self.endpoint); self.assertEqual(external['usage'], first['usage'])
        self.assertNotIn('secret-test-upstream-key', json.dumps(voted.json()))
        self.assertEqual(self.client.post(path + 'review-batch/', {}, format='json').status_code, 400)
        body['responses'][0]['text'] = 'forged'
        self.assertEqual(self.client.post('/api/v1/chat-comparisons/', body, format='json').status_code, 400)
        ProjectPrivacyPolicy.all_objects.filter(project=self.project).update(external_generation_targets=[])
        self.assertEqual(self.client.get(path).status_code, 404)
