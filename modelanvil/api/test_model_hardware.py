from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from modelanvil.runners.capabilities import model_capabilities, training_memory_requirements
from modelanvil.runners.model_catalog import inspect_model
from modelanvil.runners.training import general_runtime, hf_runtime, mlx_runtime
from modelanvil.runners.training import runtime as character


class ModelHardwareTests(SimpleTestCase):
    def test_training_requirements_match_existing_runtime_limits(self):
        for runtime in (character, general_runtime, hf_runtime, mlx_runtime):
            profile = training_memory_requirements(runtime.RUNTIME_ID)
            self.assertEqual(profile['host_memory_bytes'], runtime.LIMITS['memory_bytes'])
            self.assertEqual(profile['accelerator_memory_bytes'], runtime.LIMITS.get('gpu_memory_bytes', 0))
            self.assertEqual(profile['runtime_contract'], runtime.CONTRACT_DIGEST)
        large = training_memory_requirements(hf_runtime.RUNTIME_ID, hf_runtime.LARGE_GUIDED_SOURCE)
        self.assertEqual(large['host_memory_bytes'], 32 * 1024**3)
        self.assertEqual(large['accelerator_memory_bytes'], 12 * 1024**3)
        self.assertEqual(large['accelerator_backends'], ['mps'])
        self.assertIsNone(training_memory_requirements('unknown-architecture'))

    def test_archived_model_does_not_claim_hardware_fit(self):
        result = model_capabilities(SimpleNamespace(state='archived'))
        self.assertFalse(result['train']['eligible'])
        self.assertIsNone(result['memory_requirements']['training'])

    def test_snapshot_size_is_separate_from_memory_and_only_supported_profile_has_requirements(self):
        info = SimpleNamespace(sha=hf_runtime.SOURCE['revision'], gated=False, pipeline_tag='text-generation',
            config={'model_type': 'llama'}, card_data={'license': 'apache-2.0'}, safetensors=SimpleNamespace(total=135000000),
            siblings=[SimpleNamespace(rfilename='config.json', size=512, lfs=None),
                      SimpleNamespace(rfilename='model.safetensors', size=1024**3, lfs=None)])
        with patch('modelanvil.runners.model_catalog.hub_client') as hub:
            hub.return_value.model_info.return_value = info
            plan = inspect_model(hf_runtime.SOURCE['repo_id'], info.sha, 'tenant', 'project')
            self.assertEqual(plan['byte_size'], 1024**3 + 512)
            self.assertEqual(plan['memory_requirements']['weights_bytes'], 1024**3)
            self.assertEqual(plan['runtime_actions']['chat'],'load_validation_required')
            self.assertEqual(plan['runtime_actions']['training'],'pinned_recipe_supported')
            self.assertEqual(plan['memory_requirements']['training']['host_memory_bytes'], hf_runtime.LIMITS['memory_bytes'])
            other = inspect_model('other/model', info.sha, 'tenant', 'project')
            self.assertIsNone(other['memory_requirements']['training'])
            info.safetensors.total=300000001
            large=inspect_model('other/model',info.sha,'tenant','project')
            self.assertEqual(large['runtime_actions']['chat'],'unsupported_in_current_runtime')
