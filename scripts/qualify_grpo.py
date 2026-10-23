"""Actual bounded CPU GRPO API qualification in a new, isolated directory."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--interrupt-run', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.output.resolve()
    if not args.interrupt_run:
        root.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(root / 'qualification.sqlite'),
                     MODELANVIL_ARTIFACT_ROOT=str(root / 'artifacts'))
    import django
    django.setup()
    from django.core.management import call_command
    from django.test import override_settings
    from rest_framework.test import APIClient
    from modelanvil.artifacts.models import Artifact
    from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
    from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
    from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
    from modelanvil.runners.models import AlignmentRun, Model, ModelVersion, TokenizerVersion
    from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
    from modelanvil.runners.training.runtime import RUNTIME_ID
    from modelanvil.runners.alignment import numerical, verifier_runtime
    from modelanvil.runners.alignment.execution import execute_alignment, _live, ExecutionStopped

    if args.interrupt_run:
        # Real process death after the ordinary callback has committed checkpoint one.
        original = numerical.train_alignment
        def interrupted(*values, **kwargs):
            callback = kwargs['on_step']
            def stop(step, *state):
                callback(step, *state)
                if step == 1:
                    os._exit(93)
            kwargs['on_step'] = stop
            return original(*values, **kwargs)
        numerical.train_alignment = interrupted
        execute_alignment(AlignmentRun.all_objects.get(run_id=args.interrupt_run))
        raise AssertionError('Interruption did not occur.')

    call_command('migrate', verbosity=0)
    tenant = Tenant.objects.create(slug='grpo-qualification', name='Authored CPU GRPO qualification')
    team = Team.objects.create(tenant_id=tenant.pk, slug='local', name='Local')
    project = Project.objects.create(tenant_id=tenant.pk, team=team, slug='authored', name='Authored correctness probes')
    secret, hashed = generate_api_key()
    key = ApiKey.objects.create(tenant_id=tenant.pk, project=project, name='Isolated qualification', role=Role.ENGINEER, secret_hash=hashed)
    private = root / 'browser-private.json'
    with private.open('x') as target:
        os.chmod(private, 0o600)
        json.dump({'key': secret, 'project_id': str(project.pk)}, target)
    client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')

    def post(path, body, expected=200):
        response = client.post(path, body, format='json')
        assert response.status_code == expected, (path, response.status_code, response.content)
        return response.json()

    def artifact(value):
        raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
        record = Artifact.all_objects.create(tenant_id=tenant.pk, project=project, storage_location_id='local',
            object_key=f'authored/{uuid.uuid4()}.json', sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type='application/json')
        upload_staged_artifact(record, io.BytesIO(raw), backend=artifact_storage_backend())
        return record

    def read_bundle(run):
        record = Artifact.all_objects.get(artifact_id=run.output_model_version.artifact_manifest_id)
        with artifact_storage_backend().open(tenant.pk, record.object_key) as source:
            raw = source.read()
        assert hashlib.sha256(raw).hexdigest() == record.sha256
        return json.loads(raw)

    def receipt(run):
        run.refresh_from_db()
        reservation = BudgetReservation.all_objects.get(job_id=run.run_id)
        usage = list(UsageEvent.all_objects.filter(provider_event_key=f'alignment:{run.run_id}').values('quantity', 'unit'))
        return {'run_id': str(run.run_id), 'status': run.status, 'current_step': run.current_step,
            'checkpoint_steps': list(run.checkpoints.order_by('step').values_list('step', flat=True)),
            'candidate': str(run.output_model_version_id) if run.output_model_version_id else None,
            'reservation_state': reservation.state, 'settled_amount': str(reservation.settled_amount), 'usage': usage}

    tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef \n')]
    spec = {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}
    tokenizer = TokenizerVersion.objects.create(tenant_id=tenant.pk, project=project, name='Authored character',
        vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
    numerical_model = CausalTextModel(len(tokens), n_embd=4, lora_r=2, lora_alpha=4, seed=42)
    for _ in range(4):
        numerical_model.compute_loss_and_step([1, 4, 5, 2], .15)
    raw, manifest = pack_safetensors(numerical_model.export_tensors())
    base = {'config.json': {'runtime': RUNTIME_ID, 'vocab_size': len(tokens), 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
        'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(), 'tokenizer_config.json': spec}
    base_artifact = artifact(base)
    model = Model.objects.create(tenant_id=tenant.pk, project=project, name='Authored tiny character policy')
    version = ModelVersion.objects.create(tenant_id=tenant.pk, project=project, model=model, revision_no=1,
        tokenizer=tokenizer, architecture_ref=RUNTIME_ID, artifact_manifest_id=str(base_artifact.artifact_id),
        license_evidence={'license': 'MIT', 'source': 'Repository-authored numerical fixture; LICENSE'},
        metadata={'weights_sha256': manifest['weights_sha256']})
    policy = BudgetPolicy.objects.create(tenant_id=tenant.pk, name='Bounded GRPO steps', period='lifetime', unit='training_steps', limit_amount=100)
    rows = lambda chars, split: [{'prompt': char, 'chosen': 'a', 'rejected': 'b', 'source_group_id': f'{split}-{char}'} for char in chars]
    training, heldout, regression = rows('ab', 'train'), rows('cd', 'heldout'), rows('ef', 'regression')

    with override_settings(ALLOWED_HOSTS=['testserver', '127.0.0.1']):
        registered = [post('/api/v1/alignment-runs/register-preferences/', {'name': label, 'samples': samples}, 201)
                      for label, samples in [('Authored GRPO training', training), ('Protected GRPO heldout', heldout)]]
        body = {'algorithm': 'grpo', 'policy_model_version': version.pk, 'reference_model_version': version.pk,
            'train_dataset_artifact': registered[0]['artifact_id'], 'held_out_dataset_artifact': registered[1]['artifact_id'],
            'total_steps': 3, 'verifier_spec': {'type': 'exact_match'},
            'hyperparameters': {'group_size': 8, 'max_new_tokens': 1, 'budget_policy_id': str(policy.policy_id)}}
        def plan():
            value = post('/api/v1/alignment-runs/', body, 201)
            return AlignmentRun.all_objects.get(run_id=value['run_id'])
        baseline = plan()
        post(f'/api/v1/alignment-runs/{baseline.run_id}/execute/', {})
        baseline.refresh_from_db(); candidate = read_bundle(baseline)
        assert baseline.status == 'completed' and baseline.output_model_version.state == 'draft'
        assert any(m['weights_changed'] for m in baseline.metrics_history)
        post(f'/api/v1/alignment-runs/{baseline.run_id}/execute/', {})
        assert len(receipt(baseline)['usage']) == 1
        (root / 'base.bundle.json').write_text(json.dumps(base))
        (root / 'candidate.bundle.json').write_text(json.dumps(candidate))
        (root / 'protected-probes.json').write_text(json.dumps({'heldout': heldout, 'regression': regression, 'verifier': {'type': 'exact_match'}}))
        external = subprocess.run([sys.executable, '-I', str(repo / 'scripts/qualify_grpo_consumer.py'),
            '--base', str(root / 'base.bundle.json'), '--candidate', str(root / 'candidate.bundle.json'),
            '--samples', str(root / 'protected-probes.json')], capture_output=True, text=True, timeout=10, check=True)
        independent = json.loads(external.stdout)
        assert not independent['consumer_imported_modelanvil_or_django']

        recovered = plan()
        killed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--output', str(root),
                                '--interrupt-run', str(recovered.run_id)], capture_output=True, text=True, timeout=30)
        assert killed.returncode == 93, killed.stderr
        before = receipt(recovered); previous_token = recovered.execution_token
        assert before['current_step'] == 1 and before['reservation_state'] == 'reserved' and not before['usage']
        cp = recovered.checkpoints.get(step=1); original_digest = cp.state_digest
        cp.state_digest = '0' * 64; cp.save(update_fields=['state_digest'])
        refused = post(f'/api/v1/alignment-runs/{recovered.run_id}/resume/', {}, 400)
        assert receipt(recovered)['current_step'] == 1
        cp.state_digest = original_digest; cp.save(update_fields=['state_digest'])
        post(f'/api/v1/alignment-runs/{recovered.run_id}/resume/', {})
        recovered.refresh_from_db()
        assert recovered.execution_token != previous_token
        assert read_bundle(recovered)['model.safetensors.b64'] == candidate['model.safetensors.b64']
        try:
            _live(recovered, previous_token)
        except ExecutionStopped:
            pass
        else:
            raise AssertionError('Prior execution token accepted.')

        cancelled = plan(); original_train = numerical.train_alignment
        def cancelling(*values, **kwargs):
            callback = kwargs['on_step']
            def stop(step, *state):
                callback(step, *state)
                if step == 1:
                    post(f'/api/v1/alignment-runs/{cancelled.run_id}/cancel/', {})
            kwargs['on_step'] = stop
            return original_train(*values, **kwargs)
        numerical.train_alignment = cancelling
        try:
            post(f'/api/v1/alignment-runs/{cancelled.run_id}/execute/', {})
        finally:
            numerical.train_alignment = original_train
        cancellation = receipt(cancelled)
        assert cancellation['status'] == 'cancelled' and cancellation['current_step'] == 1 and not cancellation['candidate']
        assert cancellation['settled_amount'] == '1.000000'

    sources = ['modelanvil/runners/alignment/' + name for name in ('execution.py', 'numerical.py', 'grpo.py', 'verifier_runtime.py')]
    sources += ['scripts/alignment_verifier.py', 'scripts/qualify_grpo.py', 'scripts/qualify_grpo_consumer.py', 'scripts/cpu_character_infer.py']
    result = {'scope': 'Authored bounded CPU character GRPO correctness; no pretrained, GPU, FP8, customer-quality or production claim.',
        'python': sys.version, 'platform': sys.platform, 'tenant_id': str(tenant.pk), 'project_id': str(project.pk),
        'base_model_version': str(version.pk), 'base_weights_sha256': manifest['weights_sha256'],
        'candidate_weights_sha256': candidate['weights_manifest.json']['weights_sha256'], 'candidate_state': 'draft',
        'registered_inputs': registered, 'training': training, 'heldout': heldout, 'regression': regression,
        'verifier': verifier_runtime.contract(), 'baseline': receipt(baseline), 'metrics': baseline.metrics_history,
        'rollouts': baseline.rollouts_log, 'held_out_evaluation': baseline.latest_metrics['held_out_evaluation'],
        'independent': independent, 'process_death': {'exit_code': killed.returncode, 'before': before,
            'corrupt_checkpoint_refusal': refused, 'after': receipt(recovered), 'exact_weights_match': True, 'stale_token_refused': True},
        'cancellation': cancellation, 'source_sha256': {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in sources}}
    (root / 'actual-report.json').write_text(json.dumps(result, indent=2, default=str, allow_nan=False) + '\n')
    print(json.dumps({'report': str(root / 'actual-report.json'), 'weights_changed': True,
        'process_death_recovery_exact': True, 'independent_quality_improved': independent['quality_improved']}))


if __name__ == '__main__':
    main()
