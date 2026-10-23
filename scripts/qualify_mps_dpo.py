"""Opt-in, isolated Apple GPU DPO correctness proof using authored fixture labels.

Creates a new database/artifact directory. No customer data, downloads, human
quality claims or production approval. All fixture credentials/workers are
disabled on exit, including failure. Run numerical qualifications serially.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model-dir', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=False)
repo = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(repo))
os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(args.output / 'qualification.sqlite'),
    MODELANVIL_ARTIFACT_ROOT=str(args.output / 'artifacts'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
    TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
    VECLIB_MAXIMUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
import django
django.setup()
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from modelanvil.identity.models import Tenant, Team, Project, ApiKey, Role, generate_api_key
from modelanvil.jobs.models import Job, Worker, JobAttempt, claim_job, commit_result, reconcile_expired_leases
from modelanvil.jobs.executor import execute_claim, ExecutionContext
from modelanvil.runners.models import AlignmentRun, ModelVersion
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.runners.alignment import mps_dpo
from modelanvil.runners.inference import snapshot
from modelanvil.device_admission import device_lease

call_command('migrate', verbosity=0)
report = {'scope': 'Authored correctness fixture labels with explicit test-owner attestation; no human/customer quality qualification.',
          'production_qualified': False, 'runtime': mps_dpo.RUNTIME_ID, 'build_digest': mps_dpo.build_digest()}
try:
    tenant = Tenant.objects.create(slug='dpo-proof', name='Isolated DPO correctness fixture')
    team = Team.objects.create(tenant_id=tenant.pk, slug='fixture', name='Fixture')
    project = Project.objects.create(tenant_id=tenant.pk, team=team, slug='fixture', name='Fixture')
    samples = repo / 'docs/engineering/verification/task77-gpu-recipes-2026-10-23/authored-mechanics-corpus.jsonl'
    # Reuse the operator importer and pinned base, then disable its unrelated SFT worker.
    output = io.StringIO()
    call_command('setup_gpu_training', tenant_id=tenant.pk, project_id=project.pk, name='fixture-base',
        model_dir=args.model_dir.resolve(), samples=samples, device='mps:0', recipe='lora_adapter', steps=3, stdout=output)
    installed = json.loads(output.getvalue()); Worker.all_objects.filter(pk=installed['worker_id']).update(status='offline', slots=0)
    output = io.StringIO(); call_command('setup_mps_dpo_worker', tenant_id=tenant.pk, name='fixture-dpo', stdout=output)
    worker_data = json.loads(output.getvalue()); worker = Worker.all_objects.get(pk=worker_data['worker_id'])
    report['accelerator'] = worker_data['accelerator']
    budget = BudgetPolicy.all_objects.create(tenant_id=tenant.pk, name='DPO fixture updates', period='lifetime',
        unit='training_steps', limit_amount=100)
    secret, hashed = generate_api_key()
    ApiKey.objects.create(tenant=tenant, project=project, role=Role.ENGINEER, name='DPO fixture only', secret_hash=hashed)
    client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
    datasets = {
        'train': [('Sky color:', ' blue', ' green'), ('Two plus two:', ' four', ' five'), ('Frozen water:', ' ice', ' fire')],
        'heldout': [('Grass color:', ' green', ' purple'), ('Three plus one:', ' four', ' seven')],
        'regression': [('Sunrise direction:', ' east', ' west'), ('Water formula:', ' H2O', ' CO2')]}
    artifacts = {}
    for name, rows in datasets.items():
        pairs = [{'prompt': p, 'chosen': c, 'rejected': r, 'source_group_id': f'authored-fixture-{name}-{i}'}
                 for i, (p, c, r) in enumerate(rows)]
        response = client.post('/api/v1/alignment-runs/register-preferences/',
            {'name': name + ' authored correctness fixtures', 'samples': pairs, 'labels_reviewed': True}, format='json')
        assert response.status_code == 201, response.data
        artifacts[name] = response.data
    report['fixture_inputs'] = artifacts
    body = {'algorithm': 'dpo', 'policy_model_version': installed['launch']['base_model_version'],
        'reference_model_version': installed['launch']['base_model_version'], 'worker_pool': worker.pool_id,
        'train_dataset_artifact': artifacts['train']['artifact_id'], 'held_out_dataset_artifact': artifacts['heldout']['artifact_id'],
        'regression_dataset_artifact': artifacts['regression']['artifact_id'], 'total_steps': 3,
        'hyperparameters': {'beta': .1, 'learning_rate': .00002, 'max_gradient_norm': 1., 'budget_policy_id': str(budget.policy_id)}}

    def create(**changes):
        response = client.post('/api/v1/alignment-runs/', {**body, **changes}, format='json')
        assert response.status_code == 201, response.data
        return AlignmentRun.all_objects.get(run_id=response.data['run_id'])

    def launch(run):
        response = client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        assert response.status_code == 200, response.data
        run.refresh_from_db(); return run

    def execute(run):
        worker.refresh_from_db()
        descriptor = claim_job(worker, run.job)
        assert descriptor is not None, 'DPO worker could not claim its job'
        result = execute_claim(worker, descriptor, mps_dpo.worker_executor)
        run.refresh_from_db()
        if result.get('status') != 'succeeded':
            attempt = JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
            raise AssertionError({'result': result, 'run_status': run.status, 'reason': run.stop_reason, 'error': attempt.error})
        assert run.status == 'completed' and run.current_step == 3 and run.output_model_version_id
        assert snapshot(run.output_model_version, tenant.pk, project.pk)['trained']
        return result

    baseline = create()
    for changes in ({'regression_dataset_artifact': artifacts['train']['artifact_id']},
                    {'hyperparameters': {**body['hyperparameters'], 'learning_rate': .05}}, {'algorithm': 'orpo'}):
        response = client.post('/api/v1/alignment-runs/', {**body, **changes}, format='json')
        assert response.status_code == 400, response.data
    with device_lease('mps:0'):
        refused = client.post(f'/api/v1/alignment-runs/{baseline.run_id}/execute/', {}, format='json')
        assert refused.status_code == 400 and Job.all_objects.count() == BudgetReservation.all_objects.count() == 0, refused.data
    launch(baseline); report['baseline_result'] = execute(baseline)
    checkpoint = baseline.checkpoints.get(step=3)
    report['baseline'] = {'run_id': str(baseline.run_id), 'metrics': baseline.metrics_history,
        'weights_sha256': checkpoint.policy_state['files']['adapter_model.safetensors']['sha256'],
        'optimizer_sha256': checkpoint.policy_state['adam']['sha256'], 'evaluation': baseline.latest_metrics['independent_evaluation']}
    download = client.get(f'/api/v1/alignment-runs/{baseline.run_id}/download/')
    assert download.status_code == 200, getattr(download, 'data', None)
    archive = args.output / 'adapter.zip'
    with archive.open('wb') as target:
        for block in download.streaming_content: target.write(block)
    download.close()
    import zipfile
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {'adapter_model.safetensors', 'adapter_config.json', 'LICENSE.txt', 'provenance.json'}
        assert hashlib.sha256(bundle.read('adapter_model.safetensors')).hexdigest() == report['baseline']['weights_sha256']
    report['adapter_archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (args.output / 'baseline-report.json').write_text(json.dumps(report, indent=2))
    print('Real MPS DPO completed three updates, independent scoring and adapter download.', flush=True)

    # Expire after a genuinely committed first update; resume through a new fenced worker attempt.
    recovery = launch(create())
    descriptor = claim_job(worker, recovery.job); assert descriptor
    attempt = JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
    class ExpireAfterCommit(ExecutionContext):
        def heartbeat(self, progress=None):
            if AlignmentRun.all_objects.get(pk=recovery.pk).current_step == 1:
                JobAttempt.all_objects.filter(pk=self.attempt.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
                self.lease_lost = True; return False
            return super().heartbeat(progress)
    context = ExpireAfterCommit(attempt, descriptor['fencing_token'])
    mps_dpo.worker_executor(descriptor, context)
    assert reconcile_expired_leases(job_ids=[recovery.job.job_id]) == 1
    assert not commit_result(attempt, descriptor['fencing_token'], JobAttempt.Status.SUCCEEDED)
    response = client.post(f'/api/v1/alignment-runs/{recovery.run_id}/resume/', {}, format='json'); assert response.status_code == 200, response.data
    recovery.refresh_from_db(); execute(recovery)
    cp = recovery.checkpoints.get(step=3)
    assert cp.policy_state['files']['adapter_model.safetensors']['sha256'] == report['baseline']['weights_sha256']
    assert cp.policy_state['adam']['sha256'] == report['baseline']['optimizer_sha256']
    report['recovery'] = {'exact_adapter_and_optimizer': True, 'stale_result_refused': True, 'committed_steps': recovery.current_step,
        'checkpoints': recovery.checkpoints.count(), 'attempts': recovery.job.attempt_count}

    cancelled = launch(create())
    def cancel_after_commit(descriptor, context):
        original = context.heartbeat
        def heartbeat(progress=None):
            if AlignmentRun.all_objects.get(pk=cancelled.pk).current_step == 1:
                mps_dpo.cancel(AlignmentRun.all_objects.get(pk=cancelled.pk))
            return original(progress)
        context.heartbeat = heartbeat
        return mps_dpo.worker_executor(descriptor, context)
    worker.refresh_from_db(); result = execute_claim(worker, claim_job(worker, cancelled.job), cancel_after_commit)
    cancelled.refresh_from_db()
    assert result['committed'] and cancelled.status == 'cancelled' and cancelled.current_step == 1 and not cancelled.output_model_version_id
    assert UsageEvent.all_objects.get(provider_event_key=f'alignment:{cancelled.run_id}').quantity == 1
    report['cancellation'] = {'committed_steps': 1, 'candidate_published': False, 'settled_steps': 1}

    # Deliberately reversed held-out labels exercise a real failed quality gate.
    reversed_rows = [{'prompt': p, 'chosen': r, 'rejected': c, 'source_group_id': f'authored-fixture-heldout-{i}'}
                     for i, (p, c, r) in enumerate(datasets['heldout'])]
    response = client.post('/api/v1/alignment-runs/register-preferences/',
        {'name': 'Reversed labels: quality-gate failure fixture', 'samples': reversed_rows, 'labels_reviewed': True}, format='json')
    assert response.status_code == 201, response.data
    failed_quality = launch(create(held_out_dataset_artifact=response.data['artifact_id']))
    execute(failed_quality)
    failed_evaluation = failed_quality.latest_metrics['independent_evaluation']
    assert failed_evaluation['status'] == 'completed' and failed_evaluation['passed'] is False
    assert failed_quality.output_model_version.state == 'draft'
    assert failed_quality.output_model_version.metadata['independent_evaluation_passed'] is False
    report['failed_quality_gate'] = failed_evaluation

    # Actual updates with an injected unavailable child binary must produce an explicit blocked gate.
    from unittest.mock import patch
    unavailable = launch(create())
    with patch('modelanvil.runners.alignment.mps_dpo.subprocess.Popen', side_effect=FileNotFoundError('qualification fault injection')):
        execute(unavailable)
    unavailable_evaluation = unavailable.latest_metrics['independent_evaluation']
    assert unavailable_evaluation['status'] == 'unavailable' and unavailable_evaluation['passed'] is False
    assert unavailable.output_model_version.state == 'draft'
    report['unavailable_quality_gate'] = {**unavailable_evaluation, 'fault_injection': 'Missing scoring child executable after genuine MPS updates.'}
    import torch
    assert torch.mps.current_allocated_memory() == 0
    report['mps_allocated_after_unload'] = 0
    print('Exact adapter/Adam recovery and one-update cancellation passed.', flush=True)
finally:
    revoked = ApiKey.objects.filter(is_active=True).update(is_active=False)
    offline = Worker.all_objects.update(status='offline', slots=0)
    Tenant.objects.update(status='suspended')
    report['cleanup'] = {'fixture_keys_revoked': revoked, 'workers_offline': offline, 'fixture_tenants_suspended': True}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
