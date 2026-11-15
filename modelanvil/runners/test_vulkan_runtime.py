"""TASK-41 Vulkan inference-only backend: refusal, opt-in fallback labelling, recovery and isolation.

Fixture sessions stand in for llama.cpp here and never claim hardware results. The ``vulkan``-tagged
class runs the pinned build on the real Apple GPU through MoltenVK when it is configured.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings, tag
from rest_framework.test import APIClient

from modelanvil import accelerators
from modelanvil.core.tenancy import set_active_project, set_active_tenant
from modelanvil.device_admission import device_available, device_key, device_lease
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.runners import accelerator_support as support
from modelanvil.runners import vulkan_runtime
from modelanvil.runners.vulkan_runtime import VulkanUnavailable

HAS_GGUF = bool(importlib.util.find_spec('gguf') and importlib.util.find_spec('numpy'))
HOST = {'platform.system': 'Darwin', 'platform.machine': 'arm64'}

# Excerpt of the pinned server's own load report on the Apple M5 Pro (TASK-41 evidence).
LOAD_LOG = """
0.00.015.790 I llama_prepare_model_devices: using device Vulkan0 (Apple M5 Pro) (unknown id) - 38338 MiB free
0.00.031.822 I load_tensors: offloading output layer to GPU
0.00.031.823 I load_tensors: offloading 29 repeating layers to GPU
0.00.031.823 I load_tensors: offloaded 31/31 layers to GPU
0.00.031.824 I load_tensors:      Vulkan0 model buffer size =   256.63 MiB
0.00.031.824 I load_tensors:  Vulkan_Host model buffer size =    54.00 MiB
0.00.073.167 I llama_context: flash_attn            = auto
0.00.074.349 I llama_kv_cache:    Vulkan0 KV buffer size =    45.00 MiB
0.00.079.660 I resolve_fused_ops: Flash Attention enabled
0.00.106.577 I sched_reserve:    Vulkan0 compute buffer size =   102.52 MiB
0.00.106.577 I sched_reserve: Vulkan_Host compute buffer size =     6.52 MiB
main: server is listening on http://127.0.0.1:50123
"""


def tiny_gguf(path, file_type=1):
    import gguf
    import numpy as np
    writer = gguf.GGUFWriter(str(path), 'llama')
    writer.add_context_length(64)
    writer.add_file_type(file_type)
    writer.add_token_list(['<unk>', 'hello', 'world'])
    writer.add_tensor('token_embd.weight', np.zeros((3, 4), dtype=np.float16))
    writer.write_header_to_file(); writer.write_kv_data_to_file(); writer.write_tensors_to_file(); writer.close()
    return path


class FixtureSession:
    """Stands in for llama.cpp; records what admission looked like while it generated."""
    created = []

    def __init__(self, path, **kwargs):
        self.path, self.kwargs, self.closed, self.seen = path, kwargs, False, {}
        FixtureSession.created.append(self)

    def generate(self, messages, *, max_tokens, temperature, seed, prompt_format, cancelled, started, measurement=None):
        self.seen = {'gpu_free': device_available('mps:0'), 'cpu_free': device_available('cpu')}
        yield {'text': 'fixture'}
        if getattr(self, 'fail', False):
            raise ValueError('GGUF runtime is unavailable or exceeded its bounded response time.')
        usage = {'prompt_tokens': 2, 'completion_tokens': 1, 'total_tokens': 3}
        if measurement is not None:
            measurement.update(usage=usage, elapsed_seconds=0.01)
        yield {'finish_reason': 'length', 'elapsed_seconds': 0.01, 'usage': usage}

    def close(self):
        self.closed = True


class FixtureVulkan(FixtureSession):
    evidence = {'backend': vulkan_runtime.BACKEND, 'gpu_execution': True, 'selected_device': 'vulkan:0',
                'offloaded_layers': 31, 'model_layers': 31, 'fixture': True}


class InferenceOnlyRefusalTests(SimpleTestCase):
    def test_training_selection_on_vulkan_is_refused_before_any_probe_or_allocation(self):
        report = {'backends': {name: {'status': 'available', 'devices': [], 'reason': ''} for name in accelerators.BACKENDS}}
        for selector in ('vulkan:0', 'vulkan', 'vulkan:1'):
            with self.subTest(selector=selector), self.assertRaisesRegex(accelerators.AcceleratorError, 'inference-only'):
                accelerators.select_device(report, selector)
        with patch.object(support, 'inventory', side_effect=AssertionError('no backend probe')), \
                patch.object(vulkan_runtime, 'inspect', side_effect=AssertionError('no Vulkan probe')):
            for operation in support.TRAINING:
                row = support.inspect(operation, 'vulkan:0', quantization='int4' if operation == 'qlora_adapter' else 'none')
                self.assertFalse(row['installed_compatible'])
                self.assertIn('inference-only', row['reason'])
                self.assertFalse(row['training_supported'])
                self.assertFalse(row['model_loaded'] or row['tensors_created'])
            self.assertIn('GGUF only', support.inspect('text_inference', 'vulkan:0')['reason'])
            self.assertIn('Only vulkan:0', support.inspect('gguf_inference', 'vulkan:1', quantization='f16')['reason'])
            for options in ({'quantization': 'none'}, {'quantization': 'q5_k_m'}, {'quantization': 'f16', 'offload': True}):
                self.assertFalse(support.inspect('gguf_inference', 'vulkan:0', **options)['installed_compatible'])
            self.assertIn('explicit cpu', support.inspect('gguf_inference', 'mps:0', quantization='f16')['reason'])

    def test_vulkan_shares_the_physical_apple_device_lease(self):
        self.assertEqual(device_key('vulkan:0'), 'apple-0')
        for selector in ('vulkan:1', 'vulkan', 'Vulkan0'):
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                device_key(selector)
        with device_lease('mlx:0'):
            self.assertFalse(device_available('vulkan:0'))
        self.assertTrue(device_available('vulkan:0'))


class InstallationVerificationTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.server = root / 'llama-server'; self.server.write_bytes(b'server'); self.server.chmod(0o700)
        self.driver = root / 'lib' / 'libMoltenVK.dylib'; self.driver.parent.mkdir(); self.driver.write_bytes(b'driver')
        self.loader = root / 'libvulkan.1.dylib'; self.loader.write_bytes(b'loader')
        self.manifest = root / 'icd.d' / 'MoltenVK_icd.json'; self.manifest.parent.mkdir()
        self.manifest.write_text(json.dumps({'file_format_version': '1.0.0', 'ICD': {
            'library_path': '../lib/libMoltenVK.dylib', 'api_version': '1.4.0', 'is_portability_driver': True}}))
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.pins = {'icd_manifest': {**vulkan_runtime.QUALIFIED_RUNTIME['icd_manifest'], 'sha256': sha(self.manifest)},
                     'driver': {**vulkan_runtime.QUALIFIED_RUNTIME['driver'], 'sha256': sha(self.driver)},
                     'loader': {**vulkan_runtime.QUALIFIED_RUNTIME['loader'], 'sha256': sha(self.loader)}}
        self.config = {'server': {'path': str(self.server), 'sha256': sha(self.server)}, 'icd': str(self.manifest),
                       'loader': str(self.loader)}
        for target, value in HOST.items():
            patcher = patch(target, return_value=value); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch('platform.mac_ver', return_value=(vulkan_runtime.QUALIFIED_HOST['macos'], ('', '', ''), 'arm64'))
        self.mac = patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.dict(vulkan_runtime.QUALIFIED_RUNTIME, self.pins); patcher.start(); self.addCleanup(patcher.stop)
        for target in ('subprocess.Popen', 'subprocess.run'):
            patcher = patch(target, side_effect=AssertionError('no process before verification')); patcher.start(); self.addCleanup(patcher.stop)

    def test_exact_installed_bytes_and_host_are_required_without_starting_a_process(self):
        with override_settings(MODELANVIL_VULKAN_INFERENCE=self.config):
            identity = vulkan_runtime.verify_installation()
            self.assertEqual(identity['driver']['path'], str(self.driver.resolve()))
            self.assertTrue(identity['icd_manifest']['portability_driver'])
            self.assertTrue(vulkan_runtime.installed())
            self.assertEqual(set(vulkan_runtime.runtime_identity()), {'server', 'icd_manifest', 'driver', 'loader'})
        refusals = [({}, 'Install and checksum'),
                    ({**self.config, 'server': {**self.config['server'], 'sha256': '0' * 64}}, 'checksum changed'),
                    ({**self.config, 'icd': str(self.server)}, 'not the qualified MoltenVK manifest'),
                    ({**self.config, 'loader': str(self.driver)}, 'not the qualified 1.4.363.0')]
        for config, message in refusals:
            with self.subTest(message=message), override_settings(MODELANVIL_VULKAN_INFERENCE=config):
                with self.assertRaisesRegex(VulkanUnavailable, message):
                    vulkan_runtime.verify_installation()
                self.assertFalse(vulkan_runtime.installed())
                self.assertIsNone(vulkan_runtime.runtime_identity())
        self.driver.write_bytes(b'changed driver')
        with override_settings(MODELANVIL_VULKAN_INFERENCE=self.config), self.assertRaisesRegex(VulkanUnavailable, 'MoltenVK 1.4.2'):
            vulkan_runtime.verify_installation()
        self.mac.return_value = ('27.3', ('', '', ''), 'arm64')
        with override_settings(MODELANVIL_VULKAN_INFERENCE=self.config), self.assertRaisesRegex(VulkanUnavailable, 'qualified only'):
            vulkan_runtime.verify_installation()

    @skipUnless(HAS_GGUF, 'GGUF writer is not installed')
    def test_unqualified_quantization_and_oversize_weights_are_refused_before_launch(self):
        with override_settings(MODELANVIL_VULKAN_INFERENCE=self.config):
            for file_type in (2, 17, 18):  # Q4_0, Q5_K_M, Q6_K: not measured on this device
                path = tiny_gguf(Path(self.directory.name) / f'type-{file_type}.gguf', file_type)
                with self.subTest(file_type=file_type), self.assertRaisesRegex(VulkanUnavailable, 'F16, Q8_0 and Q4_K_M'):
                    vulkan_runtime.VulkanGGUFSession(path)
            with tempfile.NamedTemporaryFile(suffix='.gguf') as weights:
                weights.truncate(1024**3 + 1)
                with self.assertRaisesRegex(ValueError, '1 GiB'):
                    vulkan_runtime.VulkanGGUFSession(weights.name)

    def test_child_environment_pins_the_icd_and_drops_inherited_overrides(self):
        with patch.dict(os.environ, {'LLAMA_ARG_N_GPU_LAYERS': '0', 'VK_ICD_FILENAMES': '/mock_icd.json',
                                     'GGML_VK_ALLOW_SYSMEM_FALLBACK': '1'}):
            value = vulkan_runtime.environment({'icd_manifest': {'path': str(self.manifest)}}, '/private/session')
        self.assertEqual(value['VK_DRIVER_FILES'], str(self.manifest))
        self.assertEqual(value['VK_ICD_FILENAMES'], str(self.manifest))
        self.assertEqual(value['VK_LOADER_LAYERS_DISABLE'], '~all~')
        self.assertFalse({key for key in value if key.startswith(('LLAMA_ARG', 'GGML_VK_ALLOW'))})


class LoadEvidenceTests(SimpleTestCase):
    def test_full_offload_on_the_qualified_device_is_required(self):
        evidence = vulkan_runtime.require_full_offload(vulkan_runtime.load_evidence(LOAD_LOG))
        self.assertEqual((evidence['offloaded_layers'], evidence['model_layers']), (31, 31))
        self.assertEqual(evidence['devices_used'][0]['name'], 'Apple M5 Pro')
        self.assertEqual(evidence['model_buffer_bytes'], {'Vulkan0': round(256.63 * 1024**2), 'Vulkan_Host': 54 * 1024**2})
        self.assertEqual(evidence['compute_buffer_bytes']['Vulkan0'], round(102.52 * 1024**2))
        self.assertEqual(evidence['flash_attention'], 'enabled')
        for change in (('31/31 layers', '30/31 layers'), ('Vulkan0 KV', 'CPU KV'), ('(Apple M5 Pro)', '(AMD Radeon)'),
                       ('Vulkan0 model buffer', 'CPU model buffer'), ('using device Vulkan0', 'using device Vulkan1')):
            with self.subTest(change=change[1]), self.assertRaises(VulkanUnavailable):
                vulkan_runtime.require_full_offload(vulkan_runtime.load_evidence(LOAD_LOG.replace(*change)))
        with self.assertRaises(VulkanUnavailable):
            vulkan_runtime.require_full_offload(vulkan_runtime.load_evidence(''))


class GPUTrainingSetupRefusalTests(TestCase):
    def test_gpu_worker_setup_refuses_vulkan_before_creating_any_record(self):
        from modelanvil.jobs.models import Worker, WorkerPool
        from modelanvil.runners.models import Model
        from modelanvil.runners.training import hf_runtime
        tenant = Tenant.objects.create(slug='vulkan-train', name='Vulkan training refusal')
        team = Team.objects.create(tenant_id=tenant.pk, name='team', slug='team')
        project = Project.objects.create(tenant_id=tenant.pk, team=team, name='p', slug='p')
        with tempfile.TemporaryDirectory() as directory, patch.object(hf_runtime, 'require_packages'), \
                patch.object(hf_runtime, 'inventory', return_value={'backends': {}}), \
                self.assertRaisesRegex(ValueError, 'inference-only'):
            call_command('setup_gpu_training', '--tenant-id', str(tenant.pk), '--project-id', str(project.pk),
                         '--name', 'vulkan', '--model-dir', directory, '--samples', directory, '--device', 'vulkan:0')
        self.assertEqual((Model.all_objects.count(), Worker.all_objects.count(), WorkerPool.all_objects.count()), (0, 0, 0))


class ChatFixture:
    def weights(self, directory):
        return tiny_gguf(Path(directory) / 'tiny.gguf')

    def setUp(self):
        from modelanvil.runners.model_catalog import _store
        storage = tempfile.TemporaryDirectory(); self.addCleanup(storage.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': storage.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='vulkan-chat', name='Vulkan chat')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        team = Team.objects.create(tenant_id=self.tenant.pk, name='team', slug='team')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='one', slug='one')
        self.other = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='two', slug='two')
        set_active_project(self.project.pk); self.addCleanup(set_active_project, None)
        self.client, self.outsider = self.authenticated(self.project), self.authenticated(self.other)
        path = self.weights(storage.name)
        with path.open('rb') as stream:
            files = {path.name: _store(stream, tenant=self.tenant.pk, project=self.project.pk, name=path.name)}
        imported = self.client.post('/api/v1/model-imports/', {'files': files, 'name': 'Tiny GGUF', 'accepted_license': 'apache-2.0',
                                                               'idempotency_key': 'gguf-1'}, format='json')
        self.assertEqual(imported.status_code, 201, imported.content)
        self.model = imported.data['candidate_id']
        self.body = {'model': self.model, 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 4, 'device': 'vulkan:0'}
        FixtureSession.created = []

    def authenticated(self, project):
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, project=project, name='engineer', role=Role.ENGINEER, secret_hash=hashed)
        client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        return client

    def chat(self, client=None, **changes):
        return (client or self.client).post('/api/v1/inference/chat/completions', {**self.body, **changes}, format='json')

    def probed(self, project=None):
        from modelanvil.runners.inference import probed_devices
        from modelanvil.runners.models import ModelVersion
        version = ModelVersion.all_objects.get(model_version_id=self.model)
        return probed_devices(version, 'gguf', ['cpu', 'vulkan:0'], self.tenant.pk, (project or self.project).pk)


@skipUnless(HAS_GGUF, 'GGUF writer is not installed')
class VulkanChatAdmissionTests(ChatFixture, TransactionTestCase):
    def test_unavailable_vulkan_fails_closed_without_operator_opt_in(self):
        from modelanvil.runners.models import InferenceRequest
        unavailable = VulkanUnavailable('Exactly one qualified Vulkan device (Apple M5 Pro through MoltenVK) must be visible.')
        with patch.object(vulkan_runtime, 'VulkanGGUFSession', side_effect=unavailable), \
                patch('modelanvil.runners.gguf_runtime.GGUFSession', side_effect=AssertionError('no CPU run')):
            for opt_in in ({}, {'cpu_fallback': 'yes'}, {'cpu_fallback': 1}):
                with self.subTest(config=opt_in), override_settings(MODELANVIL_VULKAN_INFERENCE=opt_in):
                    response = self.chat()
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertIn(b'CPU fallback is disabled', response.content)
            # Callers that do not report fallback as CPU never get one, even with the operator opt-in.
            from modelanvil.runners.inference import local_session
            from modelanvil.runners.models import ModelVersion
            version = ModelVersion.all_objects.get(model_version_id=self.model)
            with override_settings(MODELANVIL_VULKAN_INFERENCE={'cpu_fallback': True}), \
                    self.assertRaisesRegex(ValueError, 'CPU fallback is disabled'):
                with local_session(version, tenant=self.tenant.pk, project=self.project.pk, device='vulkan:0'):
                    pass
        self.assertEqual(set(InferenceRequest.all_objects.values_list('status', flat=True)), {'failed'})
        self.assertTrue(device_available('vulkan:0') and device_available('cpu'))
        self.assertEqual(self.probed(), [])

    def test_opt_in_fallback_is_recorded_labelled_cpu_and_never_a_gpu_receipt(self):
        from modelanvil.budgets.models import UsageEvent
        from modelanvil.runners.models import InferenceRequest
        reason = 'The Vulkan driver is not the qualified MoltenVK 1.4.2 library; requalify it.'
        with override_settings(MODELANVIL_VULKAN_INFERENCE={'cpu_fallback': True}), \
                patch.object(vulkan_runtime, 'VulkanGGUFSession', side_effect=VulkanUnavailable(reason)), \
                patch('modelanvil.runners.gguf_runtime.GGUFSession', FixtureSession):
            response = self.chat()
            streamed = self.chat(stream=True)
            chunks = [json.loads(line[6:]) for line in b''.join(streamed.streaming_content).decode().split('\n\n')
                      if line.startswith('data: {')]
        self.assertEqual(response.status_code, 200, response.content)
        labels = response.data['modelanvil']
        self.assertEqual((labels['device'], labels['requested_device']), ('cpu', 'vulkan:0'))
        self.assertEqual(labels['fallback'], {'requested_device': 'vulkan:0', 'actual_device': 'cpu', 'reason': reason,
                                              'operator_opt_in': True, 'gpu_execution': False, 'billing_device': 'cpu'})
        runtime = labels['runtime']
        self.assertEqual((runtime['device'], runtime['requested_device']), ('cpu', 'vulkan:0'))
        observation = runtime['observation']
        self.assertEqual((observation['actual_device'], observation['backend'], observation['billing_device']),
                         ('cpu', 'llama.cpp-cpu', 'cpu'))
        self.assertFalse(observation['gpu_execution'])
        self.assertEqual(observation['gpu_layers'], 0)
        self.assertEqual(chunks[-1]['modelanvil']['device'], 'cpu')
        # The CPU session ran under the CPU lease with the Apple GPU lease already released.
        self.assertEqual([s.seen for s in FixtureSession.created], [{'gpu_free': True, 'cpu_free': False}] * 2)
        record = InferenceRequest.all_objects.filter(status='completed').first()
        self.assertEqual(record.configuration['_runtime']['observation']['fallback']['actual_device'], 'cpu')
        self.assertEqual(self.probed(), [])  # neither device is load-tested by a fallback receipt
        self.assertEqual(UsageEvent.all_objects.count(), 0)
        self.assertTrue(device_available('vulkan:0') and device_available('cpu'))

    def test_vulkan_receipt_lease_recovery_and_project_isolation(self):
        from modelanvil.runners.models import InferenceRequest
        with patch.object(vulkan_runtime, 'VulkanGGUFSession', FixtureVulkan), \
                patch.object(vulkan_runtime, 'runtime_identity', return_value={'server': 'pinned'}), \
                patch('modelanvil.runners.gguf_runtime.GGUFSession', side_effect=AssertionError('no CPU run')):
            self.assertEqual(self.chat(self.outsider).status_code, 404)
            response = self.chat()
            self.assertEqual(response.status_code, 200, response.content)
            observation = response.data['modelanvil']['runtime']['observation']
            self.assertEqual((response.data['modelanvil']['device'], observation['backend'], observation['billing_device']),
                             ('vulkan:0', 'llama.cpp-vulkan', 'vulkan:0'))
            self.assertTrue(observation['gpu_execution'])
            self.assertNotIn('fallback', response.data['modelanvil'])
            session = FixtureSession.created[-1]
            self.assertEqual(session.seen, {'gpu_free': False, 'cpu_free': True})
            self.assertIsInstance(session.kwargs['lease_descriptor'], int)
            self.assertTrue(session.closed and device_available('vulkan:0'))
            self.assertEqual(self.probed(), ['vulkan:0'])
            self.assertEqual(self.probed(self.other), [])
            # Shared physical lease: an MLX/MPS user blocks Vulkan without a CPU substitute.
            with override_settings(MODELANVIL_VULKAN_INFERENCE={'cpu_fallback': True}), device_lease('mps:0'):
                self.assertEqual(self.chat().status_code, 400)
            # A native failure mid-stream fails that request, releases admission and the next request recovers.
            FixtureVulkan.fail = True
            try:
                failed = self.chat(stream=True)
                text = b''.join(failed.streaming_content).decode()
            finally:
                FixtureVulkan.fail = False
            self.assertIn('inference_error', text)
            self.assertTrue(device_available('vulkan:0'))
            self.assertEqual(self.chat().status_code, 200)
        statuses = list(InferenceRequest.all_objects.filter(project=self.project).order_by('created_at').values_list('status', flat=True))
        self.assertEqual(statuses, ['completed', 'failed', 'failed', 'completed'])
        self.assertEqual(self.outsider.get('/api/v1/inference/models/').data['data'], [])


_NATIVE = os.environ.get('MODELANVIL_VULKAN_INFERENCE') and os.environ.get('MODELANVIL_GGUF_TEST_MODEL')


@tag('vulkan')
class VulkanNative(SimpleTestCase if _NATIVE else object):
    """Actual pinned llama.cpp Vulkan server on the configured Apple GPU through MoltenVK."""

    def models(self):
        quantized = os.environ.get('MODELANVIL_GGUF_TEST_QUANTIZED', '')
        return [os.environ['MODELANVIL_GGUF_TEST_MODEL'], *filter(None, quantized.split(os.pathsep))]

    def test_actual_offload_generation_cancellation_recovery_and_unload(self):
        import requests
        from modelanvil.runners.inference import generate
        messages = [{'role': 'user', 'content': 'What is 2 + 2?'}]
        for path in self.models():
            with self.subTest(model=Path(path).name):
                model = vulkan_runtime.VulkanGGUFSession(path)
                address, process = model.base_url, model.process
                session = {'format': 'gguf', 'model': model, 'device': 'vulkan:0'}
                try:
                    evidence = model.evidence
                    self.assertEqual(evidence['offloaded_layers'], evidence['model_layers'])
                    self.assertGreater(evidence['offloaded_layers'], 0)
                    self.assertEqual(evidence['device']['name'], 'Apple M5 Pro')
                    self.assertEqual(evidence['runtime']['driver']['name'], 'MoltenVK')
                    self.assertGreater(evidence['model_buffer_bytes']['Vulkan0'], 0)
                    first = list(generate(session, messages, max_tokens=8))
                    second = list(generate(session, messages, max_tokens=8))
                    text = ''.join(p.get('text', '') for p in first)
                    self.assertTrue(text)
                    self.assertEqual(text, ''.join(p.get('text', '') for p in second))
                    self.assertTrue(0 < first[-1]['usage']['completion_tokens'] <= 8)
                    stopped, parts = [False], []
                    for part in generate(session, messages, max_tokens=64, cancelled=lambda: stopped[0]):
                        parts.append(part)
                        stopped[0] = stopped[0] or 'text' in part
                    self.assertEqual(parts[-1]['finish_reason'], 'cancelled')
                    self.assertLess(parts[-1]['usage']['completion_tokens'], 64)
                    with self.assertRaisesRegex(ValueError, 'prompt and output'):
                        list(generate(session, [{'role': 'user', 'content': 'word ' * 2200}], max_tokens=8))
                    iterator = generate(session, messages, max_tokens=64)
                    next(iterator); iterator.close()
                    self.assertFalse(model._json('/slots')[0]['is_processing'])
                    self.assertEqual(requests.post(address + '/v1/completions', json={'prompt': 'hi', 'max_tokens': 2},
                                                   timeout=5).status_code, 401)
                finally:
                    model.close()
                self.assertIsNotNone(process.poll())
                with self.assertRaises(requests.ConnectionError):
                    requests.get(address + '/health', timeout=2)
        # Recovery: a native crash mid-stream fails that generation; a fresh session serves the next one.
        model = vulkan_runtime.VulkanGGUFSession(self.models()[0])
        try:
            iterator = generate({'format': 'gguf', 'model': model, 'device': 'vulkan:0'}, messages, max_tokens=64)
            next(iterator)
            os.killpg(model.process.pid, signal.SIGKILL)
            with self.assertRaises(ValueError):
                list(iterator)
        finally:
            model.close()
        model = vulkan_runtime.VulkanGGUFSession(self.models()[0])
        try:
            self.assertTrue(''.join(p.get('text', '') for p in generate({'format': 'gguf', 'model': model, 'device': 'vulkan:0'},
                                                                         messages, max_tokens=4)))
        finally:
            model.close()


@tag('vulkan')
class VulkanNativeChat(ChatFixture, TransactionTestCase if _NATIVE else object):
    """Actual chat API request on vulkan:0: device/driver evidence is persisted in the request record."""

    def weights(self, directory):
        target = Path(directory) / 'smollm2-135m-instruct-f16.gguf'
        with open(os.environ['MODELANVIL_GGUF_TEST_MODEL'], 'rb') as source, target.open('wb') as copy:
            while block := source.read(1024 * 1024):
                copy.write(block)
        return target

    def test_actual_vulkan_chat_receipt_is_device_bound_and_project_isolated(self):
        from modelanvil.runners.models import InferenceRequest
        self.assertEqual(self.chat(self.outsider).status_code, 404)
        response = self.chat(max_tokens=8, temperature=0, seed=42)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data['choices'][0]['message']['content'])
        labels = response.data['modelanvil']
        observation = labels['runtime']['observation']
        self.assertEqual((labels['device'], observation['backend'], observation['billing_device']),
                         ('vulkan:0', 'llama.cpp-vulkan', 'vulkan:0'))
        self.assertTrue(observation['gpu_execution'])
        self.assertEqual(observation['offloaded_layers'], observation['model_layers'])
        self.assertEqual((observation['device']['name'], observation['runtime']['driver']['name']), ('Apple M5 Pro', 'MoltenVK'))
        self.assertEqual(observation['gguf_file_type'], 'F16')
        record = InferenceRequest.all_objects.get(status='completed')
        self.assertEqual(record.configuration['_runtime']['observation'], observation)
        self.assertEqual(record.usage, response.data['usage'])
        self.assertEqual(self.probed(), ['vulkan:0'])
        self.assertEqual(self.probed(self.other), [])
        self.assertTrue(device_available('vulkan:0'))
