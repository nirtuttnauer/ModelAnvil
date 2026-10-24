"""Media/split trust boundaries; fixtures do not qualify a vision model."""
import hashlib
import json
import uuid
from unittest.mock import patch

from django.test import TestCase
from modelanvil.runners.training import test_hf_runtime as fixtures
from modelanvil.runners.training import vlm_data as data, vlm_runtime as gpu, cpu_vlm_runtime as cpu
from modelanvil.artifacts.models import DatasetRevision


class VisionInputTests(TestCase):
    setUp = fixtures.GPUInputTests.setUp
    store = fixtures.GPUInputTests.store
    # Reuse the project's verified local-artifact fixture, without importing the large model.
    def row(self, group, image):
        return {'schema_version': '1.0', 'sample_id': str(uuid.uuid4()), 'source_group_id': group,
            'blocks': [{'block_id': 'image', 'type': 'image', 'role': 'user', 'asset_ref': f'artifact:{image.artifact_id}'},
                {'block_id': 'q', 'type': 'text', 'role': 'user', 'text': 'What color?'},
                {'block_id': 'a', 'type': 'text', 'role': 'assistant', 'text': 'Red.'}],
            'provenance': {'source_snapshot_ref': 'authored-test', 'source_record_key': group, 'content_sha256': image.sha256}}

    def test_cpu_and_mps_contracts_are_separate_and_bounded(self):
        self.assertNotEqual(cpu.CONTRACT_DIGEST, gpu.CONTRACT_DIGEST)
        self.assertEqual(cpu.runner_manifest()['resources']['gpu_count'], 0)
        self.assertEqual(gpu.runner_manifest()['resources']['gpu_count'], 1)
        self.assertEqual(cpu.CONTRACT['recipes'], ['lora_adapter'])
        self.assertEqual(cpu.LIMITS['steps'], 20)
        for name in ('../model.safetensors', '/config.json', 'model.bin'):
            with self.assertRaises(ValueError), gpu.staged_files({name: gpu.file_ref(self.artifact)}, self.tenant.pk, self.project.pk):
                self.fail('Untrusted path entered vision staging')

    def test_image_scope_is_checked_before_decode_and_staging(self):
        from modelanvil.runners.training.vlm_data import read_image
        with patch('modelanvil.runners.training.vlm_math.decode_image') as decode:
            with self.assertRaises(ValueError): read_image(self.artifact.artifact_id, self.tenant.pk, self.other.pk)
            decode.assert_not_called()
        with self.assertRaises(ValueError): read_image('https://example.com/a.png', self.tenant.pk, self.project.pk)

    def test_identical_asset_or_source_group_cannot_cross_protected_splits(self):
        from modelanvil.artifacts.models import Dataset
        dataset = Dataset.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='Vision')
        encoded = {'input_ids': [type('Tokens', (), {'tolist': lambda self: [1,2]})()]}
        for duplicate in ('asset', 'group'):
            with self.subTest(duplicate=duplicate):
                rows = [self.row('same-group' if duplicate == 'group' else str(i), self.artifact) for i in range(3)]
                value = {'rows': rows, 'split_manifest': {split: [row['sample_id']] for split,row in zip(('train','validation','test'),rows)}}
                raw = json.dumps(value).encode(); manifest = self.store(raw, 'application/json')
                revision = DatasetRevision.all_objects.create(tenant_id=self.tenant.pk, project=self.project, dataset=dataset,
                    revision_no=1 if duplicate == 'asset' else 2, state='published', manifest_artifact=manifest, manifest_digest=hashlib.sha256(raw).hexdigest())
                pins = [{'sha256': ('a' if duplicate == 'asset' else str(i)) * 64,
                    'media_type': 'image/png', 'artifact': gpu.file_ref(self.artifact)} for i in range(3)]
                # Exercise split semantics with pinned image metadata and a tiny tokenizer result.
                with patch.object(data, 'read_image', side_effect=[(object(), pin) for pin in pins]), \
                        patch.object(data.vlm_math, 'encode', return_value=(encoded, 1)):
                    with self.assertRaisesRegex(ValueError, 'cross protected splits'):
                        data.samples(revision, object(), self.tenant.pk, self.project.pk)

    def test_vision_estimate_counts_assistant_tokens_instead_of_image_prompt(self):
        from modelanvil.runners.training.preflight_report import estimate_from_pilot
        result = estimate_from_pilot({'pins': {'steps': 2, 'config': {'model_role': 'vision_language'}},
            'sequences': [[1] * 85], 'samples': [{'prompt_tokens': 81}]},
            tenant=self.tenant.pk, project=self.project.pk, pool=None)
        self.assertEqual(result['total_tokens'], 8)
        self.assertEqual(result['units']['tokens'], 'assistant response tokens')
        self.assertFalse(result['known'])

    def test_changed_shared_numerical_helper_invalidates_the_loaded_runtime(self):
        from pathlib import Path
        original = Path.read_bytes
        def changed(path):
            raw = original(path)
            return raw + b'\n# changed numerical implementation' if path.name == 'torch_rlhf.py' else raw
        with patch.object(Path, 'read_bytes', changed):
            with self.assertRaisesRegex(ValueError, 'restart API and worker'):
                gpu.build_digest()
