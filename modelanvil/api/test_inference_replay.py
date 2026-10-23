"""Actual completion retries, measured cancellation and current authority checks."""
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from unittest import skipUnless

from django.conf import settings
from django.db import connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.core.models import IdempotencyKey
from modelanvil.core.tenancy import reset_context
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.runners.models import InferenceRequest, Model, ModelVersion, TokenizerVersion
from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
from modelanvil.runners.training.runtime import RUNTIME_ID


@override_settings(ALLOWED_HOSTS=['testserver'])
class InferenceReplayTests(TransactionTestCase):
    path = '/api/v1/inference/chat/completions'

    def test_unopened_stream_accounts_before_native_resources_unload(self):
        from contextlib import ExitStack
        from modelanvil.api.views.model_workspace import CompletionStream
        events = []
        stack = ExitStack(); stack.callback(lambda: events.append('unloaded'))
        def native_parts():
            try:
                yield 'prefetched'
            finally:
                self.assertNotIn('unloaded', events)
                events.append('accounted')
        parts = native_parts(); next(parts)
        unopened = (value for value in ())
        stream = CompletionStream(unopened, stack, parts.close)
        stream.close(); stream.close()
        self.assertEqual(events, ['accounted', 'unloaded'])

    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': self.root.name})
        override.enable(); self.addCleanup(override.disable); self.addCleanup(reset_context)
        self.tenant = Tenant.objects.create(slug='replay', name='Replay')
        team = Team.objects.create(tenant_id=self.tenant.pk, slug='team', name='Team')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=team, slug='one', name='One')
        self.other = Project.objects.create(tenant_id=self.tenant.pk, team=team, slug='other', name='Other')
        self.secret, hashed = generate_api_key()
        self.key = ApiKey.objects.create(tenant=self.tenant, project=self.project, name='caller', role=Role.ENGINEER, secret_hash=hashed)
        self.client = self.authenticated(self.secret)
        tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef \n')]
        model = CausalTextModel(len(tokens), n_embd=4, lora_r=2, lora_alpha=4, seed=42)
        raw, manifest = pack_safetensors(model.export_tensors())
        bundle = {'config.json': {'runtime': RUNTIME_ID, 'vocab_size': len(tokens), 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
            'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(),
            'tokenizer_config.json': {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}}
        payload = json.dumps(bundle).encode()
        artifact = Artifact.all_objects.create(tenant_id=self.tenant.pk, project=self.project, storage_location_id='local',
            object_key='replay/base.json', sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
        upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
        tokenizer = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Character',
            vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
        parent = Model.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Actual replay policy')
        self.version = ModelVersion.objects.create(tenant_id=self.tenant.pk, project=self.project, model=parent, revision_no=1,
            tokenizer=tokenizer, architecture_ref=RUNTIME_ID, artifact_manifest_id=str(artifact.artifact_id), metadata={'weights_sha256': manifest['weights_sha256']})
        self.body = {'model': str(self.version.model_version_id), 'messages': [{'role': 'user', 'content': 'a'}],
            'max_tokens': 8, 'stream_options': {'include_usage': True}}

    def authenticated(self, secret):
        client = APIClient(); client.credentials(HTTP_AUTHORIZATION='Bearer ' + secret)
        return client

    def post(self, *, client=None, key='stable', **changes):
        return (client or self.client).post(self.path, {**self.body, **changes}, format='json', HTTP_IDEMPOTENCY_KEY=key)

    def test_completed_buffered_replay_keeps_identity_usage_and_never_loads_again(self):
        first = self.post(); self.assertEqual(first.status_code, 200, first.content)
        with patch('modelanvil.api.views.model_workspace.local_session', side_effect=AssertionError('Replay loaded a model')):
            replay = self.post()
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(replay['Idempotency-Replayed'], 'true'); self.assertEqual(first['Idempotency-Replayed'], 'false')
        self.assertEqual(replay['Idempotency-Retention'], '604800')
        self.assertEqual(InferenceRequest.all_objects.count(), 1)
        self.assertEqual(InferenceRequest.all_objects.get().usage, first.json()['usage'])
        self.assertEqual(IdempotencyKey.all_objects.count(), 1)

    def test_completed_stream_replays_actual_text_and_usage_without_generation(self):
        first = self.post(stream=True); self.assertEqual(first.status_code, 200)
        raw = b''.join(first.streaming_content); first.close()
        with patch('modelanvil.api.views.model_workspace.generate', side_effect=AssertionError('Replay generated again')):
            replay = self.post(stream=True)
            repeated = b''.join(replay.streaming_content); replay.close()
        parse = lambda value: [json.loads(line[6:]) for line in value.splitlines() if line.startswith(b'data: ') and line != b'data: [DONE]']
        a, b = parse(raw), parse(repeated)
        self.assertEqual({item['id'] for item in a}, {item['id'] for item in b})
        self.assertEqual(''.join(c.get('delta', {}).get('content', '') for item in a for c in item['choices']),
            ''.join(c.get('delta', {}).get('content', '') for item in b for c in item['choices']))
        self.assertEqual(a[-1]['usage'], b[-1]['usage'])
        self.assertEqual(InferenceRequest.all_objects.count(), 1)

    def test_changed_inputs_invalid_keys_and_nonfinite_options_cannot_reexecute(self):
        self.assertEqual(self.post().status_code, 200)
        for changes in ({'max_tokens': 7}, {'stream': True}, {'messages': [{'role': 'user', 'content': 'b'}]}):
            self.assertEqual(self.post(**changes).status_code, 409)
        for key in (' ', 'x' * 129):
            self.assertEqual(self.post(key=key).status_code, 400)
        self.assertEqual(self.client.post(self.path, json.dumps({**self.body, 'temperature': float('nan')}),
            content_type='application/json', HTTP_IDEMPOTENCY_KEY='nonfinite').status_code, 400)
        self.assertEqual(InferenceRequest.all_objects.count(), 1)

    def test_pending_and_cancelled_keys_refuse_retry_and_preserve_measured_prefetch(self):
        first = self.post(stream=True); self.assertEqual(first.status_code, 200)
        self.assertEqual(self.post(stream=True).status_code, 409)
        first.close()
        record = InferenceRequest.all_objects.get()
        self.assertEqual(record.status, 'cancelled')
        self.assertGreater(record.usage['completion_tokens'], 0)
        self.assertLessEqual(record.usage['completion_tokens'], 8)
        self.assertEqual(self.post(stream=True).status_code, 409)
        self.assertEqual(InferenceRequest.all_objects.count(), 1)
        self.assertEqual(self.post(key='explicit-new-generation').status_code, 200)
        self.assertEqual(InferenceRequest.all_objects.count(), 2)

    def test_cached_replay_checks_current_model_pins_and_live_stream_authority(self):
        first = self.post(stream=True); b''.join(first.streaming_content); first.close()
        replay = self.post(stream=True); iterator = iter(replay.streaming_content); next(iterator)
        ApiKey.objects.filter(pk=self.key.pk).update(role=Role.VIEWER)
        remaining = b''.join(iterator); replay.close()
        self.assertIn(b'inference_error', remaining); self.assertNotIn(b'"content":', remaining)
        self.assertEqual(InferenceRequest.all_objects.get().status, 'completed')
        ApiKey.objects.filter(pk=self.key.pk).update(role=Role.ENGINEER)
        ModelVersion.all_objects.filter(pk=self.version.pk).update(metadata={'changed': True})
        self.assertEqual(self.post(stream=True).status_code, 409)
        self.assertEqual(InferenceRequest.all_objects.count(), 1)

    def test_keys_are_scoped_to_principal_project_and_current_permissions(self):
        self.assertEqual(self.post().status_code, 200)
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=self.project, name='another', role=Role.ENGINEER, secret_hash=hashed)
        self.assertEqual(self.post(client=self.authenticated(secret)).status_code, 200)
        self.assertEqual(InferenceRequest.all_objects.count(), 2)
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=self.other, name='hidden', role=Role.ENGINEER, secret_hash=hashed)
        self.assertEqual(self.post(client=self.authenticated(secret)).status_code, 404)
        ApiKey.objects.filter(pk=self.key.pk).update(is_active=False)
        self.assertEqual(self.post().status_code, 401)

    def test_an_inflight_request_is_not_executed_by_a_second_client(self):
        from modelanvil.api.views import model_workspace
        entered, proceed, results = threading.Event(), threading.Event(), {}
        original = model_workspace.local_session
        @contextmanager
        def held(*args, **kwargs):
            with original(*args, **kwargs) as session:
                entered.set()
                if not proceed.wait(10): raise AssertionError('Test request did not release its gate')
                yield session
        def worker():
            try:
                results['response'] = self.post(client=self.authenticated(self.secret))
            except BaseException as exc:
                results['error'] = exc
            finally:
                connections.close_all()
        with patch.object(model_workspace, 'local_session', held):
            thread = threading.Thread(target=worker); thread.start()
            try:
                self.assertTrue(entered.wait(10))
                self.assertEqual(self.post(client=self.authenticated(self.secret)).status_code, 409)
            finally:
                proceed.set(); thread.join(10)
        self.assertFalse(thread.is_alive()); self.assertNotIn('error', results, results)
        self.assertEqual(results['response'].status_code, 200, results['response'].content)
        self.assertEqual(InferenceRequest.all_objects.count(), 1)

    def test_sse_accept_header_is_supported_and_incompatible_json_request_refused(self):
        response = self.client.post(self.path, {**self.body, 'stream': True}, format='json', HTTP_ACCEPT='text/event-stream')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'[DONE]', b''.join(response.streaming_content)); response.close()
        refused = self.client.post(self.path, self.body, format='json', HTTP_ACCEPT='text/event-stream')
        self.assertEqual(refused.status_code, 400)

    def test_replay_retention_cleanup_preserves_pending_keys_and_measured_history(self):
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        self.assertEqual(self.post().status_code, 200)
        record = IdempotencyKey.all_objects.get()
        IdempotencyKey.all_objects.filter(pk=record.pk).update(completed_at=timezone.now() - timedelta(days=8))
        pending = IdempotencyKey.all_objects.create(tenant_id=self.tenant.pk, principal=record.principal,
            key='pending', path=self.path, http_method='POST', request_hash='0' * 64)
        call_command('purge_expired_inference_replays', stdout=io.StringIO())
        self.assertTrue(IdempotencyKey.all_objects.filter(pk=record.pk).exists())
        call_command('purge_expired_inference_replays', apply=True, stdout=io.StringIO())
        self.assertFalse(IdempotencyKey.all_objects.filter(pk=record.pk).exists())
        self.assertTrue(IdempotencyKey.all_objects.filter(pk=pending.pk).exists())
        self.assertEqual(InferenceRequest.all_objects.count(), 1)

    @skipUnless(os.name == 'posix', 'Qualified local POSIX admission')
    def test_another_process_holding_cpu_admission_blocks_actual_api_allocation(self):
        root = str(Path(self.root.name) / 'device-locks')
        code = "from modelanvil.device_admission import device_lease\nwith device_lease('cpu'):\n print('held',flush=True)\n input()\n"
        with override_settings(MODELANVIL_DEVICE_LOCK_ROOT=root):
            child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'modelanvil.settings', 'MODELANVIL_DEVICE_LOCK_ROOT': root})
            try:
                self.assertEqual(child.stdout.readline().strip(), 'held')
                blocked = self.post(key='busy-device')
                self.assertEqual(blocked.status_code, 400, blocked.content)
                self.assertIn('busy', blocked.content.decode())
                self.assertIsNone(InferenceRequest.all_objects.get().usage)
            finally:
                child.terminate(); child.communicate(timeout=5)
            self.assertEqual(self.post(key='busy-device').status_code, 409)
            self.assertEqual(self.post(key='released-device').status_code, 200)
            self.assertEqual(InferenceRequest.all_objects.filter(status='completed').count(), 1)
