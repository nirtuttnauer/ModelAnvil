"""Actual alignment API journeys against committed inputs, weights and accounting."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import uuid
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.runners.models import AlignmentCheckpoint, AlignmentRun, Model, ModelVersion, TokenizerVersion
from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
from modelanvil.runners.training.runtime import RUNTIME_ID


# Separate stdlib-only process: no Django models, optimizer objects or project loader.
INDEPENDENT_LOADER = r'''
import base64, hashlib, json, math, struct, sys
bundle = json.load(open(sys.argv[1]))
raw = base64.b64decode(bundle['model.safetensors.b64'], validate=True)
size = struct.unpack('<Q', raw[:8])[0]
header = json.loads(raw[8:8+size]); data = raw[8+size:]; tensors = {}
for name, spec in header.items():
    if name == '__metadata__': continue
    assert spec['dtype'] == 'F32'
    start, end = spec['data_offsets']; count = math.prod(spec['shape'])
    assert 0 <= start <= end <= len(data) and end-start == 4*count
    values = struct.unpack('<'+'f'*count, data[start:end]); assert all(map(math.isfinite, values))
    tensors[name] = (spec['shape'], values)
cfg = bundle['config.json']; width = cfg['n_embd']; rank = cfg['lora_r']; vocab = cfg['vocab_size']
wte = tensors['transformer.wte.weight'][1]; a = tensors['transformer.layers.0.lora_A.weight'][1]
b = tensors['transformer.layers.0.lora_B.weight'][1]; head = tensors['lm_head.weight'][1]
x = wte[width:2*width]
ax = [sum(a[k*width+j]*x[j] for j in range(width)) for k in range(rank)]
h = [x[i]+cfg['lora_alpha']/rank*sum(b[i*rank+k]*ax[k] for k in range(rank)) for i in range(width)]
logits = [sum(head[v*width+i]*h[i] for i in range(width)) for v in range(vocab)]
assert len(logits) == vocab and all(map(math.isfinite, logits))
print(json.dumps({'weights_sha256': hashlib.sha256(raw).hexdigest(), 'tensor_count': len(tensors), 'logits': logits}))
'''


@override_settings(ALLOWED_HOSTS=['testserver'])
class ActualAlignmentExecutionTests(TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': self.root.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='actual-align', name='Actual alignment')
        self.team = Team.objects.create(tenant_id=self.tenant.pk, slug='alignment', name='Alignment')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=self.team, slug='visible', name='Visible')
        self.hidden = Project.objects.create(tenant_id=self.tenant.pk, team=self.team, slug='hidden', name='Hidden')
        self.client = APIClient(); self.authenticate()
        tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef \n')]
        self.spec = {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}
        self.tokenizer = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, project=self.project,
            name='Character', vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
        numerical = CausalTextModel(len(tokens), n_embd=4, lora_r=2, lora_alpha=4, seed=42)
        for _ in range(4): numerical.compute_loss_and_step([1, 4, 5, 2], .15)
        raw, manifest = pack_safetensors(numerical.export_tensors())
        self.base_bundle = {'config.json': {'runtime': RUNTIME_ID, 'vocab_size': len(tokens), 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
            'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(), 'tokenizer_config.json': self.spec}
        self.base_artifact = self.artifact(self.base_bundle)
        model = Model.objects.create(tenant_id=self.tenant.pk, project=self.project, name='Tiny numerical policy')
        self.base = ModelVersion.objects.create(tenant_id=self.tenant.pk, project=self.project, model=model,
            revision_no=1, tokenizer=self.tokenizer, architecture_ref=RUNTIME_ID,
            artifact_manifest_id=str(self.base_artifact.artifact_id), metadata={'weights_sha256': manifest['weights_sha256']})
        self.train = self.preference_artifact([{'prompt': 'a', 'chosen': 'ab', 'rejected': 'cd'}, {'prompt': 'b', 'chosen': 'ab', 'rejected': 'ef'}])
        self.held = self.preference_artifact([{'prompt': 'e', 'chosen': 'ab', 'rejected': 'cd'}, {'prompt': 'f', 'chosen': 'ab', 'rejected': 'ef'}])
        self.policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name='Alignment steps', period='lifetime', unit='training_steps', limit_amount=10000)

    def authenticate(self, tenant=None, project=None, role=Role.ENGINEER):
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=tenant or self.tenant, project=project or self.project, name=str(uuid.uuid4()), role=role, secret_hash=hashed)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')

    def artifact(self, value, *, tenant=None, project=None):
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        artifact = Artifact.objects.create(tenant_id=(tenant or self.tenant).pk, project=project or self.project,
            storage_location_id='local', object_key=f'alignment-input/{uuid.uuid4()}.json', sha256=hashlib.sha256(raw).hexdigest(),
            byte_size=len(raw), media_type='application/json')
        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
        return artifact

    def preference_artifact(self, pairs, **kwargs):
        return self.artifact({'schema_version': 'modelanvil.preference-pairs.v1', 'pairs': pairs}, **kwargs)

    def body(self, algorithm='dpo', **changes):
        body = {'algorithm': algorithm, 'policy_model_version': self.base.pk, 'reference_model_version': self.base.pk,
            'train_dataset_artifact': str(self.train.artifact_id), 'held_out_dataset_artifact': str(self.held.artifact_id),
            'total_steps': 4, 'hyperparameters': {'budget_policy_id': str(self.policy.policy_id)}, 'verifier_spec': {'type': 'substring'}}
        return {**body, **changes}

    def test_dpo_and_reward_inputs_refuse_shared_source_groups_even_with_different_prompts(self):
        train = self.preference_artifact([{'prompt': 'a', 'chosen': 'ab', 'rejected': 'cd',
            'metadata': {'source_group_id': 'one-source'}}])
        held = self.preference_artifact([{'prompt': 'f', 'chosen': 'ab', 'rejected': 'cd',
            'metadata': {'source_group_id': 'one-source'}}])
        for algorithm in ('dpo', 'reward_model'):
            response = self.client.post('/api/v1/alignment-runs/', self.body(algorithm,
                train_dataset_artifact=str(train.artifact_id), held_out_dataset_artifact=str(held.artifact_id)), format='json')
            self.assertEqual(response.status_code, 400, response.content)
            self.assertIn('source groups', response.content.decode())
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def create(self, algorithm='dpo', **changes):
        response = self.client.post('/api/v1/alignment-runs/', self.body(algorithm, **changes), format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return AlignmentRun.all_objects.get(run_id=response.json()['run_id'])

    def execute(self, run):
        response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        run.refresh_from_db(); self.assertEqual(run.status, 'completed')
        return response

    def output_bundle(self, run):
        version = run.output_model_version
        self.assertIsNotNone(version)
        response = self.client.get(f'/api/v1/model-versions/{version.model_version_id}/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['execution_evidence']['level'], 'integrated_execution')
        self.assertFalse(response.json()['execution_evidence']['production_qualified'])
        self.assertEqual(run.latest_metrics['held_out_evaluation']['held_out_sample_count'], 2)
        artifact = Artifact.all_objects.get(tenant_id=self.tenant.pk, artifact_id=version.artifact_manifest_id)
        self.assertEqual(artifact.state, Artifact.State.COMMITTED)
        with artifact_storage_backend().open(self.tenant.pk, artifact.object_key) as stream: raw = stream.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact.sha256)
        self.assertNotEqual(artifact.sha256, self.base_artifact.sha256)
        return json.loads(raw), artifact

    def independently_load(self, bundle):
        path = Path(self.root.name) / 'external.bundle.json'; path.write_text(json.dumps(bundle))
        result = subprocess.run([sys.executable, '-I', '-c', INDEPENDENT_LOADER, str(path)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed['weights_sha256'], bundle['weights_manifest.json']['weights_sha256'])
        self.assertEqual(observed['tensor_count'], 4)
        return observed

    def test_all_four_algorithms_commit_measured_state_and_loadable_weights(self):
        reward = self.create('reward_model'); self.execute(reward)
        reward_bundle, _ = self.output_bundle(reward)
        self.independently_load(reward_bundle)
        self.assertEqual(reward_bundle['model.safetensors.b64'], self.base_bundle['model.safetensors.b64'])
        head = reward_bundle['reward_head.json']
        self.assertTrue(any(value != 0 for value in head['weights']))
        self.assertEqual(head['format'], 'modelanvil.cpu-character-reward.v1')
        self.assertEqual(head['encoder_weights_sha256'], self.base_bundle['weights_manifest.json']['weights_sha256'])
        self.assertEqual(head['weights_sha256'], hashlib.sha256(struct.pack(f"<{len(head['weights'])}f", *head['weights'])).hexdigest())
        for algorithm in ['dpo', 'ppo_rlhf', 'verifier_rl']:
            with self.subTest(algorithm=algorithm):
                changes = {'reward_model_version': reward.output_model_version_id} if algorithm == 'ppo_rlhf' else {}
                run = self.create(algorithm, **changes); response = self.execute(run)
                bundle, _ = self.output_bundle(run); self.independently_load(bundle)
                self.assertNotEqual(bundle['model.safetensors.b64'], self.base_bundle['model.safetensors.b64'])
                self.assertEqual(run.current_step, run.total_steps)
                self.assertEqual(len(run.metrics_history), run.total_steps)
                self.assertFalse(response.json()['execution_evidence']['production_qualified'])
                self.assertEqual(BudgetReservation.all_objects.get(job_id=run.run_id).settled_amount, run.current_step)
                self.assertEqual(UsageEvent.all_objects.get(provider_event_key=f'alignment:{run.run_id}').quantity, run.current_step)

    def test_completed_execution_replay_does_not_retrain_or_charge_again(self):
        run = self.create(); self.execute(run)
        before = (run.output_model_version_id, run.checkpoints.count(), ModelVersion.all_objects.count(), Artifact.all_objects.count())
        self.execute(run)
        self.assertEqual(before, (run.output_model_version_id, run.checkpoints.count(), ModelVersion.all_objects.count(), Artifact.all_objects.count()))
        self.assertEqual(UsageEvent.all_objects.filter(provider_event_key=f'alignment:{run.run_id}').count(), 1)
        changed = self.client.patch(f'/api/v1/alignment-runs/{run.run_id}/', {'total_steps': 5}, format='json')
        self.assertEqual(changed.status_code, 400, changed.content)

    def test_corrupt_committed_input_cannot_publish_output_or_charge_training(self):
        run = self.create()
        (Path(self.root.name) / str(self.tenant.pk) / self.train.object_key).write_bytes(b'corrupted')
        response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertIn(response.status_code, (400, 409), response.content)
        run.refresh_from_db(); self.assertIsNone(run.output_model_version_id)
        self.assertEqual(run.current_step, 0)
        self.assertFalse(UsageEvent.all_objects.filter(provider_event_key=f'alignment:{run.run_id}').exists())

    def test_prompt_overlap_and_step_bounds_refuse_before_execution(self):
        overlap = self.preference_artifact([{'prompt': 'a', 'chosen': 'ef', 'rejected': 'ab'}])
        for changes in [{'held_out_dataset_artifact': str(overlap.artifact_id)}, {'total_steps': 101}, {'total_steps': 0}]:
            response = self.client.post('/api/v1/alignment-runs/', self.body(**changes), format='json')
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(AlignmentRun.all_objects.count(), 0)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_verifier_tolerance_bound_is_checked_before_budget_admission(self):
        response = self.client.post('/api/v1/alignment-runs/', self.body('verifier_rl',
            verifier_spec={'type': 'numeric_tolerance', 'tolerance': 1000001}), format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_budget_limit_refuses_before_any_committed_optimizer_step(self):
        self.policy.limit_amount = 1; self.policy.save()
        response = self.client.post('/api/v1/alignment-runs/', self.body(), format='json')
        if response.status_code == 201:
            run = AlignmentRun.all_objects.get(run_id=response.json()['run_id'])
            response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
            run.refresh_from_db(); self.assertEqual(run.current_step, 0); self.assertIsNone(run.output_model_version_id)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(UsageEvent.all_objects.count(), 0)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_nonfinite_boolean_unknown_and_out_of_bounds_hyperparameters_refuse(self):
        from modelanvil.runners.alignment.execution import validate_alignment_inputs
        run = self.create()
        for hp in [{'learning_rate': float('nan')}, {'learning_rate': float('inf')},
                   {'learning_rate': True}, {'learning_rate': 0}, {'learning_rate': .201},
                   {'beta': 0}, {'max_gradient_norm': 11}, {'unsupported_knob': 1}]:
            with self.subTest(hyperparameters=hp):
                run.hyperparameters = hp
                with self.assertRaises(ValueError):
                    validate_alignment_inputs(run)
                response = self.client.post('/api/v1/alignment-runs/',
                    json.dumps(self.body(hyperparameters=hp), allow_nan=True), content_type='application/json')
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(AlignmentRun.all_objects.count(), 1)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)

    def test_corrupt_registered_reward_head_refuses_ppo_without_budget_admission(self):
        reward = self.create('reward_model'); self.execute(reward)
        bundle, _ = self.output_bundle(reward)
        bundle['reward_head.json']['weights'][0] += .25
        corrupt = self.artifact(bundle)
        version = ModelVersion.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
            model=reward.output_model_version.model, revision_no=2, tokenizer=self.tokenizer,
            architecture_ref=RUNTIME_ID, artifact_manifest_id=str(corrupt.artifact_id),
            metadata={'model_role': 'reward_model'})
        before = BudgetReservation.all_objects.count()
        response = self.client.post('/api/v1/alignment-runs/', self.body('ppo_rlhf', reward_model_version=version.pk), format='json')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(BudgetReservation.all_objects.count(), before)
        self.assertEqual(AlignmentRun.all_objects.count(), 1)

    def test_cancel_pending_run_is_terminal_and_has_no_output_or_billable_usage(self):
        run = self.create()
        path = f'/api/v1/alignment-runs/{run.run_id}/cancel/'
        self.assertEqual(self.client.post(path, {}, format='json').status_code, 200)
        run.refresh_from_db(); self.assertEqual(run.status, 'cancelled'); self.assertIsNone(run.output_model_version_id)
        self.assertEqual(self.client.post(path, {}, format='json').status_code, 200)
        response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertIn(response.status_code, (400, 409), response.content)
        self.assertTrue(all(event.quantity == 0 for event in UsageEvent.all_objects.all()))

    def test_cancellation_after_one_checkpoint_fences_later_output_and_settles_one_step(self):
        from modelanvil.runners.alignment import numerical
        from modelanvil.runners.alignment.execution import cancel_alignment
        run = self.create()
        original_train = numerical.train_alignment

        def cancel_after_checkpoint(*args, **kwargs):
            original_callback = kwargs['on_step']

            def callback(step, bundle, metrics, rollouts):
                original_callback(step, bundle, metrics, rollouts)
                if step == 1:
                    cancel_alignment(AlignmentRun.all_objects.get(pk=run.pk))

            return original_train(*args, **{**kwargs, 'on_step': callback})

        with patch.object(numerical, 'train_alignment', cancel_after_checkpoint):
            response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        run.refresh_from_db()
        self.assertEqual(run.status, 'cancelled'); self.assertEqual(run.current_step, 1)
        self.assertIsNone(run.output_model_version_id); self.assertEqual(run.checkpoints.count(), 1)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.run_id).settled_amount, 1)
        self.assertEqual(UsageEvent.all_objects.get(provider_event_key=f'alignment:{run.run_id}').quantity, 1)

    def test_corrupted_final_checkpoint_cannot_publish_a_candidate(self):
        from modelanvil.runners.alignment import numerical
        run = self.create()
        original_train = numerical.train_alignment

        def corrupt_final_checkpoint(*args, **kwargs):
            original_callback = kwargs['on_step']

            def callback(step, bundle, metrics, rollouts):
                original_callback(step, bundle, metrics, rollouts)
                if step == run.total_steps:
                    checkpoint = AlignmentCheckpoint.all_objects.get(alignment_run=run, step=step)
                    checkpoint.policy_state['bundle']['weights_manifest.json']['weights_sha256'] = 'a' * 64
                    checkpoint.save(update_fields=['policy_state'])

            return original_train(*args, **{**kwargs, 'on_step': callback})

        with patch.object(numerical, 'train_alignment', corrupt_final_checkpoint):
            response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertEqual(response.status_code, 400, response.content)
        run.refresh_from_db(); self.assertEqual(run.status, 'failed')
        self.assertIsNone(run.output_model_version_id)
        self.assertEqual(BudgetReservation.all_objects.get(job_id=run.run_id).settled_amount, run.total_steps)

    def test_openapi_alignment_contract_describes_actual_inputs_and_bounds(self):
        from jsonschema import Draft202012Validator
        doc = json.loads((Path(__file__).resolve().parents[3] / 'contracts/schemas/openapi.json').read_text())
        for name in ('AlignmentRunInput', 'PreferenceArtifactContent', 'AlignmentHyperparameters'):
            Draft202012Validator.check_schema(doc['components']['schemas'][name])
        validator = Draft202012Validator({'$ref': '#/components/schemas/AlignmentRunInput', 'components': doc['components']})
        validator.validate(self.body())
        self.assertTrue(list(validator.iter_errors(self.body(total_steps=101))))
        self.assertTrue(list(validator.iter_errors(self.body(hyperparameters={'learning_rate': 1}))))
        self.assertIn('/alignment-runs/register-preferences/', doc['paths'])
        self.assertIn('/alignment-runs/{run_id}/cancel/', doc['paths'])

    def test_cross_project_tenant_and_viewer_cannot_execute_or_change_pins(self):
        run = self.create()
        other = Tenant.objects.create(slug='other-align', name='Other')
        team = Team.objects.create(tenant_id=other.pk, slug='other', name='Other')
        other_project = Project.objects.create(tenant_id=other.pk, team=team, slug='other', name='Other')
        foreign = self.preference_artifact([{'prompt': 'c', 'chosen': 'ab', 'rejected': 'cd'}], tenant=other, project=other_project)
        hidden = self.preference_artifact([{'prompt': 'c', 'chosen': 'ab', 'rejected': 'cd'}], project=self.hidden)
        for artifact in (foreign, hidden):
            response = self.client.post('/api/v1/alignment-runs/', self.body(train_dataset_artifact=str(artifact.artifact_id)), format='json')
            self.assertIn(response.status_code, (400, 404), response.content)
        for tenant, project in [(self.tenant, self.hidden), (other, other_project)]:
            self.authenticate(tenant=tenant, project=project)
            self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json').status_code, 404)
        self.authenticate(role=Role.VIEWER)
        self.assertEqual(self.client.get(f'/api/v1/alignment-runs/{run.run_id}/').status_code, 200)
        self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{run.run_id}/cancel/', {}, format='json').status_code, 403)
        run.refresh_from_db(); self.assertEqual(run.current_step, 0)

    def test_preference_registration_commits_exact_bytes_and_rejects_bad_pairs(self):
        path = '/api/v1/alignment-runs/register-preferences/'
        pair = {'prompt': 'c', 'chosen': 'ab', 'rejected': 'cd'}
        response = self.client.post(path, {'name': 'Preferences', 'samples': [pair]}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        artifact = Artifact.all_objects.get(artifact_id=response.json()['artifact_id'])
        self.assertEqual(artifact.project_id, self.project.pk); self.assertEqual(artifact.state, Artifact.State.COMMITTED)
        with artifact_storage_backend().open(self.tenant.pk, artifact.object_key) as stream: raw = stream.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), response.json()['sha256'])
        self.assertEqual(json.loads(raw)['pairs'], [pair])
        for pairs in [[], [{**pair, 'rejected': 'ab'}], [pair]*33, [{**pair, 'prompt': 'a'*63}]]:
            rejected = self.client.post(path, {'name': 'Bad', 'samples': pairs}, format='json')
            self.assertEqual(rejected.status_code, 400, rejected.content)

    def grpo_plan(self):
        self.train = self.preference_artifact([{'prompt': 'a', 'chosen': 'a', 'rejected': 'b', 'source_group_id': 'train-a'},
            {'prompt': 'b', 'chosen': 'a', 'rejected': 'b', 'source_group_id': 'train-b'}])
        self.held = self.preference_artifact([{'prompt': 'e', 'chosen': 'a', 'rejected': 'b', 'source_group_id': 'held-e'},
            {'prompt': 'f', 'chosen': 'a', 'rejected': 'b', 'source_group_id': 'held-f'}])
        return self.create('grpo', total_steps=3, verifier_spec={'type': 'exact_match'},
            hyperparameters={'group_size': 8, 'max_new_tokens': 1, 'budget_policy_id': str(self.policy.policy_id)})

    def test_grpo_actual_api_updates_export_and_replay_settles_once(self):
        run = self.grpo_plan()
        response = self.execute(run)
        self.assertEqual(run.checkpoints.count(), 3)
        self.assertTrue(any(m['weights_changed'] for m in run.metrics_history))
        bundle, _ = self.output_bundle(run)
        self.assertNotIn('value_head.json', bundle)
        self.assertEqual(bundle['alignment_state.json']['optimizer'], 'stateless_sgd_global_norm_clip')
        repeated = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(UsageEvent.all_objects.filter(provider_event_key=f'alignment:{run.run_id}').count(), 1)
        self.assertEqual(BudgetReservation.all_objects.get(reservation_id=run.resource_reservation_id).settled_amount, 3)

    def test_grpo_interruption_resume_restores_exact_weights_and_fences_prior_token(self):
        from . import numerical
        from .execution import _live, ExecutionStopped
        baseline = self.grpo_plan(); self.execute(baseline)
        expected = self.output_bundle(baseline)[0]['weights_manifest.json']['weights_sha256']
        run = self.grpo_plan()
        original = numerical.train_alignment
        def interrupted(*args, **kwargs):
            callback = kwargs['on_step']
            def stop(step, *values):
                callback(step, *values)
                if step == 1:
                    raise SystemExit('controlled process interruption after committed step')
            kwargs['on_step'] = stop
            return original(*args, **kwargs)
        with patch.object(numerical, 'train_alignment', side_effect=interrupted), self.assertRaises(SystemExit):
            self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        run.refresh_from_db(); previous = run.execution_token
        self.assertEqual((run.status, run.current_step), ('running', 1))
        reservation = BudgetReservation.all_objects.get(reservation_id=run.resource_reservation_id)
        self.assertEqual(reservation.state, 'reserved')
        def resumed(*args, **kwargs):
            with self.assertRaises(ExecutionStopped):
                _live(run, previous)
            return original(*args, **kwargs)
        with patch.object(numerical, 'train_alignment', side_effect=resumed):
            response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/resume/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        run.refresh_from_db(); self.assertNotEqual(run.execution_token, previous)
        self.assertEqual(self.output_bundle(run)[0]['weights_manifest.json']['weights_sha256'], expected)
        self.assertEqual(list(run.checkpoints.order_by('step').values_list('step', flat=True)), [1, 2, 3])
        with self.assertRaises(ExecutionStopped):
            _live(run, previous)
        reservation.refresh_from_db(); self.assertEqual(reservation.settled_amount, 3)
        self.assertEqual(UsageEvent.all_objects.filter(provider_event_key=f'alignment:{run.run_id}').count(), 1)

    def test_grpo_invalid_verifier_result_cannot_publish_or_charge_uncommitted_steps(self):
        from . import verifier_runtime
        run = self.grpo_plan()
        with patch.object(verifier_runtime, 'score', side_effect=ValueError('Verifier timed out; no rewards accepted.')):
            response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        run.refresh_from_db()
        self.assertEqual((run.status, run.current_step, run.output_model_version_id), ('failed', 0, None))
        self.assertEqual(BudgetReservation.all_objects.get(reservation_id=run.resource_reservation_id).settled_amount, 0)
        self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{run.run_id}/resume/', {}, format='json').status_code, 400)

    def test_grpo_budget_revocation_prevents_the_next_step_and_preserves_committed_accounting(self):
        from . import numerical
        run = self.grpo_plan(); original = numerical.train_alignment
        def revoked(*args, **kwargs):
            callback = kwargs['on_step']
            def stop(step, *values):
                callback(step, *values)
                if step == 1:
                    BudgetPolicy.all_objects.filter(pk=self.policy.pk).update(enabled=False)
            kwargs['on_step'] = stop
            return original(*args, **kwargs)
        with patch.object(numerical, 'train_alignment', side_effect=revoked):
            response = self.client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        run.refresh_from_db()
        self.assertEqual((run.status, run.current_step, run.output_model_version_id), ('failed', 1, None))
        self.assertEqual(run.checkpoints.count(), 1)
        self.assertEqual(BudgetReservation.all_objects.get(reservation_id=run.resource_reservation_id).settled_amount, 1)

    def test_grpo_registration_preserves_groups_and_unsupported_options_refuse_before_allocation(self):
        row = {'prompt': 'a', 'chosen': 'a', 'rejected': 'b', 'source_group_id': 'authored-group'}
        response = self.client.post('/api/v1/alignment-runs/register-preferences/',
            {'name': 'Grouped reference', 'samples': [row]}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        artifact = Artifact.all_objects.get(artifact_id=response.json()['artifact_id'])
        with artifact_storage_backend().open(self.tenant.pk, artifact.object_key) as stream:
            self.assertEqual(json.load(stream)['pairs'], [row])
        run = self.grpo_plan(); count = AlignmentRun.all_objects.count()
        body = self.body('grpo', verifier_spec={'type': 'exact_match'},
            hyperparameters={'group_size': 8, 'max_new_tokens': 1, 'budget_policy_id': str(self.policy.policy_id)})
        for changes in ({'precision': 'fp8'}, {'hyperparameters': {'group_size': 1}}, {'verifier_spec': {'type': 'substring'}}):
            rejected = self.client.post('/api/v1/alignment-runs/', {**body, **changes}, format='json')
            self.assertEqual(rejected.status_code, 400, rejected.content)
        self.assertEqual(AlignmentRun.all_objects.count(), count)
        self.assertEqual(BudgetReservation.all_objects.count(), 0)
        self.authenticate(project=self.hidden)
        self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{run.run_id}/resume/', {}, format='json').status_code, 404)
        self.authenticate(role=Role.VIEWER)
        self.assertEqual(self.client.post(f'/api/v1/alignment-runs/{run.run_id}/resume/', {}, format='json').status_code, 403)
