"""CPU pretrained admission boundaries; actual model qualification is opt-in."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from modelanvil.runners.training import cpu_hf_runtime as cpu, hf_runtime as gpu
from modelanvil.runners.training.registry import runtime_for_architecture


class PretrainedCPUGuards(SimpleTestCase):
    def test_missing_or_small_host_memory_never_admits(self):
        for value in (None, 0, 8 * 1024**3):
            with self.subTest(memory=value), patch('modelanvil.runners.training.hardware.total_memory_bytes', return_value=value):
                with self.assertRaisesRegex(ValueError, '16 GiB'):
                    cpu.observed_device('cpu')
        with self.assertRaisesRegex(ValueError, 'explicit cpu'):
            cpu.observed_device('mps:0')

    def test_cpu_contract_does_not_mutate_or_select_gpu_profile(self):
        self.assertIs(runtime_for_architecture(cpu.RUNTIME_ID), cpu)
        self.assertEqual(cpu.runner_manifest()['resources']['gpu_count'], 0)
        self.assertEqual(gpu.runner_manifest()['resources']['gpu_count'], 1)
        self.assertNotEqual(cpu.CONTRACT_DIGEST, gpu.CONTRACT_DIGEST)
        self.assertEqual(cpu.LIMITS['steps'], 20)
        self.assertNotIn('qlora_adapter', cpu.CONTRACT['recipes'])
        self.assertIn('continued_pretraining', cpu.CONTRACT['recipes'])

    def test_wrong_worker_runtime_device_packages_memory_or_slots_refused(self):
        caps = {'training_runtime': cpu.CONTRACT_DIGEST, 'gpu_backend': 'cpu', 'gpu_device': 'cpu',
                'gpu_packages': cpu.PACKAGES, 'memory_bytes': 16 * 1024**3}
        self.assertTrue(cpu.capable_worker(SimpleNamespace(capabilities=caps, slots=1)))
        for change in ({'training_runtime': gpu.CONTRACT_DIGEST}, {'gpu_backend': 'mps'},
                       {'gpu_device': 'mps:0'}, {'gpu_packages': {}}, {'memory_bytes': 8 * 1024**3}):
            with self.subTest(change=change):
                self.assertFalse(cpu.capable_worker(SimpleNamespace(capabilities={**caps, **change}, slots=1)))
        self.assertFalse(cpu.capable_worker(SimpleNamespace(capabilities=caps, slots=2)))

    def test_cpu_rejects_large_and_instruction_sources_before_resolving(self):
        for source in (gpu.GUIDED_SOURCE, gpu.LARGE_GUIDED_SOURCE):
            with self.assertRaisesRegex(ValueError, 'exact pinned 135M base'):
                cpu.resolve_inputs(base=SimpleNamespace(metadata={'source': source}))

    def test_pretrained_cpu_export_formats_include_native_and_adapter(self):
        from modelanvil.api.views.training_views import training_export_options
        run = SimpleNamespace(status='completed', recipe_type='lora_adapter',
            hardware_config={'execution_mode': 'worker', 'pins': {'runtime': cpu.RUNTIME_ID}})
        self.assertEqual([option['format'] for option in training_export_options(run)], ['native', 'adapter', 'json'])

    def test_cpu_memory_report_never_invents_free_memory(self):
        with patch('modelanvil.runners.training.hardware.total_memory_bytes', return_value=32 * 1024**3):
            report = cpu.memory_observation('cpu')
        self.assertEqual(report['required_bytes'], 16 * 1024**3)
        self.assertNotIn('free_bytes', report)
