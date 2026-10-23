"""Interruption and immutable download boundaries; numerical proofs are opt-in operator runs."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import uuid
import zipfile

from django.test import TestCase, SimpleTestCase, override_settings
from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import LocalArtifactStorage
from modelanvil.runners.training import cpu_exports as exports


class ExportRecoveryTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.backend = LocalArtifactStorage(self.directory.name)
        self.run = SimpleNamespace(pk=1, tenant_id=uuid.uuid4(), project_id=None, run_id=uuid.uuid4())
        self.bundle = {'files': {}, 'source': exports.hf_runtime.SOURCE, 'provenance.json': {'test': True}}
        self.settings = override_settings(MODELANVIL={'artifact_root': self.directory.name, 'artifact_backend': 'filesystem'})
        self.settings.enable(); self.addCleanup(self.settings.disable)
        for name, replacement in [('source_bundle', lambda run: self.bundle), ('device_lease', lambda *args, **kwargs: nullcontext(42)),
                                  ('_run', self.build)]:
            active = patch.object(exports, name, replacement); active.start(); self.addCleanup(active.stop)
        active = patch.object(exports.cpu_hf_runtime, 'staged_files', return_value=nullcontext(Path(self.directory.name))); active.start(); self.addCleanup(active.stop)
        active = patch.object(exports.cpu_hf_runtime, 'require_packages'); active.start(); self.addCleanup(active.stop)
        self.builds = 0

    def build(self, args, **kwargs):
        self.builds += 1
        target = Path(args[-1]); (target / 'model.safetensors').write_bytes(b'unit-test-not-a-real-model')
        (target / 'config.json').write_text('{}')
        return json.dumps({'runtime': 'unit-test-fixture', 'generated_token_ids': [1], 'completion': 'fixture'})

    def test_interrupted_atomic_upload_resumes_without_reconversion_and_never_exposes_staging(self):
        def die_after_object(artifact, stream):
            self.backend.put(artifact.tenant_id, artifact.object_key, stream, expected_sha256=artifact.sha256, expected_size=artifact.byte_size)
            raise SystemExit(93)
        with patch.object(exports, 'upload_staged_artifact', die_after_object):
            with self.assertRaises(SystemExit): exports.prepare(self.run, 'merged')
        self.assertEqual(exports.export_records(self.run).count(), 0)
        with self.assertRaisesRegex(ValueError, 'Prepare a current'): exports.open_export(self.run, 'merged')
        record = exports.prepare(self.run, 'merged')
        self.assertEqual(self.builds, 1)
        self.assertEqual(record.state, 'committed')
        repeated = exports.prepare(self.run, 'merged'); self.assertEqual(repeated.pk, record.pk)
        self.assertEqual(self.builds, 1)
        _, stream = exports.open_export(self.run, 'merged')
        with stream, zipfile.ZipFile(stream) as archive:
            names = archive.namelist(); self.assertEqual(len(names), len(set(names)))
            manifest = json.loads(archive.read('modelanvil-provenance.json'))
            self.assertFalse(manifest['export']['production_qualified'])
            self.assertEqual(manifest['export']['quality_gate']['state'], 'not_evaluated')
            self.assertIn('LICENSE.txt', names)
            self.assertTrue(all(info.date_time == (1980,1,1,0,0,0) for info in archive.infolist()))

    def test_completed_phase_corruption_cannot_be_reused(self):
        with patch.object(exports, 'upload_staged_artifact', side_effect=SystemExit(93)):
            with self.assertRaises(SystemExit): exports.prepare(self.run, 'merged')
        path = next((Path(self.directory.name) / '.cpu-export-work').glob('*/*/merged/model.safetensors'))
        path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'completed export phase changed'): exports.prepare(self.run, 'merged')
        self.assertEqual(exports.export_records(self.run).count(), 0)

    def test_download_rechecks_identity_scope_and_storage(self):
        record = exports.prepare(self.run, 'merged')
        other = SimpleNamespace(**{**vars(self.run), 'tenant_id': uuid.uuid4()})
        with self.assertRaisesRegex(ValueError, 'Prepare a current'): exports.open_export(other, 'merged')
        old = self.bundle; self.bundle = {**old, 'changed': True}
        with self.assertRaisesRegex(ValueError, 'Prepare a current'): exports.open_export(self.run, 'merged')
        self.bundle = old
        self.backend._path(record.tenant_id, record.object_key, create_parent=False).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'immutable identity'): exports.open_export(self.run, 'merged')

    def test_source_change_during_conversion_never_publishes(self):
        original = self.build
        def change(args, **kwargs):
            result = original(args, **kwargs); self.bundle = {**self.bundle, 'changed': True}; return result
        with patch.object(exports, '_run', change):
            with self.assertRaisesRegex(ValueError, 'source changed'): exports.prepare(self.run, 'merged')
        self.assertFalse(Artifact.all_objects.exists())

    def test_reserved_provenance_is_immutable_and_cannot_be_forged_by_api(self):
        from modelanvil.api.views.jobs_artifacts import ArtifactSerializer
        record = exports.prepare(self.run, 'merged')
        serializer = ArtifactSerializer(record, data={'metadata': {'cpu_export': {}}}, partial=True)
        self.assertFalse(serializer.is_valid())
        record.metadata = {'cpu_export': {'forged': True}}
        with self.assertRaisesRegex(ValueError, 'immutable'): record.save()
        serializer = ArtifactSerializer(data={'metadata': {'cpu_export': {}}, 'storage_location_id': 'local',
            'object_key': 'forged', 'sha256': 'a'*64, 'byte_size': 1, 'media_type': 'application/zip'})
        self.assertFalse(serializer.is_valid())

    def test_unrelated_legacy_json_metadata_can_still_commit_and_be_updated(self):
        from io import BytesIO
        from modelanvil.api.views.jobs_artifacts import ArtifactSerializer
        raw = b'legacy'
        record = Artifact.all_objects.create(tenant_id=self.run.tenant_id, storage_location_id='local',
            object_key='legacy', sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw),
            media_type='application/octet-stream', metadata=['legacy metadata'])
        exports.upload_staged_artifact(record, BytesIO(raw))
        self.assertEqual(record.state, 'committed')
        serializer = ArtifactSerializer(record, data={'metadata': {'description': 'updated legacy metadata'}}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()



class ExportAdmissionTests(SimpleTestCase):
    def test_tools_must_have_exact_revision_and_binary_checksums(self):
        with override_settings(MODELANVIL_CPU_EXPORT_TOOLS={}):
            with self.assertRaisesRegex(ValueError, 'Install and checksum'): exports.tools()
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'fake'; binary.write_bytes(b'not executable')
            config = {'source': directory, 'quantize': {'path': str(binary), 'sha256': 'a'*64},
                      'cli': {'path': str(binary), 'sha256': 'a'*64}}
            with override_settings(MODELANVIL_CPU_EXPORT_TOOLS=config), patch.object(exports, '_run', return_value=exports.LLAMA_COMMIT):
                with self.assertRaisesRegex(ValueError, 'checksum changed'): exports.tools()

    def test_failed_or_fixture_run_never_enters_conversion(self):
        run = SimpleNamespace(refresh_from_db=lambda: None, status='failed', hardware_config={})
        with self.assertRaisesRegex(ValueError, 'actual pretrained CPU'): exports.source_bundle(run)

    def test_fixture_and_nonfinite_quality_never_pass(self):
        from scripts.qualify_cpu_quantization import compare
        with self.assertRaisesRegex(ValueError, 'Fixture'): compare(10, 9, fixture=True)
        for value in (float('nan'), float('inf'), 0):
            with self.assertRaises(ValueError): compare(10, value, fixture=False)
        self.assertEqual(compare(10, 10.6, fixture=False)['state'], 'failed')
        self.assertFalse(compare(10, 10.1, fixture=False)['production_qualified'])
        from scripts.verify_cpu_export import validate_profile
        cfg = {'model_type': 'llama', 'hidden_size': 576, 'num_hidden_layers': 30, 'vocab_size': 49152,
               'intermediate_size': 1536, 'num_attention_heads': 9, 'num_key_value_heads': 3, 'max_position_embeddings': 8192}
        adapter = {'peft_type': 'LORA', 'task_type': 'CAUSAL_LM', 'r': 8, 'lora_alpha': 16, 'target_modules': ['q_proj', 'v_proj']}
        validate_profile(cfg, adapter)
        with self.assertRaisesRegex(ValueError, 'configuration'): validate_profile({**cfg, 'vocab_size': 2**40})
        with self.assertRaisesRegex(ValueError, 'rank-8'): validate_profile(cfg, {**adapter, 'r': 2**40})



class PrivateHubPublicationTests(SimpleTestCase):
    def test_private_publication_reconciles_unknown_commit_without_uploading_twice(self):
        from modelanvil.runners.training.hub_export_worker import publish
        import types
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'export.zip'; path.write_bytes(b'unit-test-archive')
            sha = hashlib.sha256(path.read_bytes()).hexdigest(); state = {'uploaded': False, 'count': 0}
            class API:
                def __init__(self, **kwargs): self.options = kwargs
                def whoami(self): return {'auth': {'accessToken': {'role': 'fineGrained'}}}
                def model_info(self, **kwargs): return SimpleNamespace(private=True, sha='a'*40)
                def get_paths_info(self, **kwargs):
                    return [SimpleNamespace(path=f'exports/{sha}.zip', size=path.stat().st_size, lfs=SimpleNamespace(sha256=sha))] if state['uploaded'] else []
                def upload_file(self, **kwargs):
                    self.assertions = kwargs
                    if kwargs['parent_commit'] != 'a'*40: raise AssertionError('Missing compare-and-swap parent')
                    state.update(uploaded=True, count=state['count']+1)
                    raise ConnectionError('Unknown outcome after commit')
            client = types.ModuleType('huggingface_hub'); client.HfApi = API
            hooks = []
            client.set_client_factory = lambda factory: hooks.append(factory)
            http = types.ModuleType('httpx'); http.Client = lambda **kwargs: kwargs
            request = {'path': str(path), 'repo_id': 'owner/private', 'sha256': sha, 'authorize_sha256': sha,
                       'token': 'dedicated-test-token', 'origins': ['https://huggingface.co']}
            with patch.dict('sys.modules', {'huggingface_hub': client, 'httpx': http}):
                with self.assertRaises(ConnectionError): publish(request)
                result = publish(request)
                self.assertTrue(result['recovered']); self.assertEqual(state['count'], 1)
                self.assertEqual(result['sha256'], sha); self.assertFalse(result['production_qualified'])
                guard = hooks[-1]() ['event_hooks']['request'][0]
                class Request:
                    method = 'POST'
                    headers = {'Authorization': 'Bearer dedicated-test-token'}
                    url = 'https://huggingface.co/api/models/other/repo/commit/main'
                with self.assertRaises(ValueError): guard(Request())
                Request.url = 'https://unapproved.invalid/upload'
                with self.assertRaises(ValueError): guard(Request())
                request['authorize_sha256'] = '0'*64
                with self.assertRaisesRegex(ValueError, 'authorization'): publish(request)

    def test_default_configuration_contains_no_publication_credentials(self):
        from django.conf import settings
        self.assertEqual(settings.MODELANVIL_HUB_EXPORT_TARGETS, {})


class ExportChildIsolationTests(SimpleTestCase):
    def test_child_inherits_device_lock_without_ambient_credentials(self):
        with patch.dict('os.environ', {'HF_TOKEN': 'must-not-pass', 'AWS_SECRET_ACCESS_KEY': 'must-not-pass'}), patch.object(exports.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}', stderr='')) as run:
            exports._run(['fixed-tool', 'fixed-input'], descriptor=123)
        self.assertEqual(run.call_args.kwargs['pass_fds'], (123,))
        self.assertNotIn('HF_TOKEN', run.call_args.kwargs['env'])
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['timeout'], 305)

    def test_deadline_survives_parent_lease_close_and_releases_after_child_exit(self):
        import os, signal, subprocess, sys
        from modelanvil.device_admission import device_lease, device_available
        with tempfile.TemporaryDirectory() as directory, override_settings(MODELANVIL_DEVICE_LOCK_ROOT=directory):
            Path(directory).chmod(0o700)
            with device_lease('cpu', pass_descriptor=True) as descriptor:
                child = subprocess.Popen([sys.executable, str(Path(exports.__file__).with_name('cpu_export_process.py')), '1', sys.executable, '-I', '-c', "import time;print('held',flush=True);time.sleep(10)"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, pass_fds=(descriptor,))
                self.assertEqual(child.stdout.readline().strip(), 'held')
            try:
                self.assertFalse(device_available('cpu'))
                self.assertEqual(child.wait(timeout=5), -signal.SIGALRM)
                self.assertTrue(device_available('cpu'))
            finally:
                if child.poll() is None: child.kill()
                child.communicate(timeout=5)


class QuantizationCorpusAdmissionTests(SimpleTestCase):
    def test_manifest_flag_cannot_turn_an_authored_fixture_into_a_qualified_corpus(self):
        from scripts.qualify_cpu_quantization import validate_corpus, QUALIFIED_CORPUS
        manifest = {**QUALIFIED_CORPUS, 'fixture': False, 'split': 'test', 'license': 'Publisher metadata'}
        actual = {k: QUALIFIED_CORPUS[k] for k in ('sha256', 'byte_size')}
        validate_corpus(manifest, actual)
        for changed in ({'sha256': 'a'*64}, {'source_revision': 'a'*40}, {'fixture': True}, {'source_path': 'train.parquet'}):
            with self.assertRaisesRegex(ValueError, 'fixture or unqualified'):
                validate_corpus({**manifest, **changed}, actual)
