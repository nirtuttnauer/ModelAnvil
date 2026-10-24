"""Opt-in isolated CPU reward/RLOO correctness proof; authored labels are not customer quality evidence."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model-dir', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=False)
repo = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(repo))
os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(args.output / 'qualification.sqlite'),
    MODELANVIL_ARTIFACT_ROOT=str(args.output / 'artifacts'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
    TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
import django; django.setup()
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from modelanvil.identity.models import Tenant, Team, Project, ApiKey, Role, generate_api_key
from modelanvil.jobs.models import Worker, Job, JobAttempt, claim_job, commit_result, reconcile_expired_leases
from modelanvil.jobs.executor import execute_claim, ExecutionContext
from modelanvil.runners.models import AlignmentRun
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.runners.alignment import hf_rlhf as runtime
from modelanvil.runners.inference import snapshot
from modelanvil.device_admission import device_lease

call_command('migrate', verbosity=0)
report = {'scope': 'Authored correctness preferences, explicit fixture-owner attestation; not independent human/customer quality.',
    'runtime': runtime.RUNTIME_ID, 'build_digest': runtime.build_digest(), 'production_qualified': False}
try:
    tenant = Tenant.objects.create(slug='cpu-rlhf-proof', name='CPU RLHF correctness fixture')
    team = Team.objects.create(tenant_id=tenant.pk, slug='fixture', name='Fixture')
    project = Project.objects.create(tenant_id=tenant.pk, team=team, slug='fixture', name='Fixture')
    output = io.StringIO()
    call_command('setup_gpu_training', tenant_id=tenant.pk, project_id=project.pk, name='fixture-base',
        model_dir=args.model_dir.resolve(), samples=repo / 'docs/engineering/verification/task77-gpu-recipes-2026-10-23/authored-mechanics-corpus.jsonl',
        device='cpu', recipe='lora_adapter', steps=3, stdout=output)
    installed = json.loads(output.getvalue()); Worker.all_objects.filter(pk=installed['worker_id']).update(status='offline', slots=0)
    output = io.StringIO(); call_command('setup_cpu_rlhf_worker', tenant_id=tenant.pk, name='fixture-rlhf', stdout=output)
    data = json.loads(output.getvalue()); worker = Worker.all_objects.get(pk=data['worker_id'])
    report['environment'] = data['accelerator']
    policies = {u: BudgetPolicy.all_objects.create(tenant_id=tenant.pk, name='Fixture ' + u,
        period='lifetime', unit=u, limit_amount=10000) for u in runtime.UNITS}
    secret, hashed = generate_api_key()
    ApiKey.objects.create(tenant_id=tenant.pk, project=project, role=Role.ENGINEER, name='Fixture only', secret_hash=hashed)
    client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
    artifacts = {}
    for name, words in {'train': ['helpful', 'truthful'], 'heldout': ['kind'], 'regression': ['careful'],
                        'policy_heldout': ['honest'], 'policy_regression': ['polite']}.items():
        pairs = [{'prompt': f'Q: Be {word}? A:', 'chosen': ' yes', 'rejected': ' no',
            'source_group_id': f'authored-{name}-{index}'} for index, word in enumerate(words)]
        response = client.post('/api/v1/alignment-runs/register-preferences/',
            {'name': name + ' authored fixtures', 'samples': pairs, 'labels_reviewed': True}, format='json')
        assert response.status_code == 201, response.data
        artifacts[name] = response.data
    report['fixture_inputs'] = artifacts
    body = {'algorithm': 'reward_model', 'policy_model_version': installed['launch']['base_model_version'],
        'reference_model_version': installed['launch']['base_model_version'], 'worker_pool': worker.pool_id,
        'train_dataset_artifact': artifacts['train']['artifact_id'], 'held_out_dataset_artifact': artifacts['heldout']['artifact_id'],
        'regression_dataset_artifact': artifacts['regression']['artifact_id'], 'total_steps': 2,
        'hyperparameters': {'learning_rate': .001, 'max_gradient_norm': 1.,
            'budget_policy_id': str(policies['training_steps'].policy_id),
            'scoring_budget_policy_id': str(policies['alignment_scores'].policy_id)}}
    def create(**changes):
        response = client.post('/api/v1/alignment-runs/', {**body, **changes}, format='json')
        assert response.status_code == 201, response.data
        return AlignmentRun.all_objects.get(run_id=response.data['run_id'])
    def launch(run):
        response = client.post(f'/api/v1/alignment-runs/{run.run_id}/execute/', {}, format='json')
        assert response.status_code == 200, response.data
        run.refresh_from_db(); return run
    def execute(run):
        worker.refresh_from_db(); descriptor = claim_job(worker, run.job)
        assert descriptor, 'CPU worker could not claim its job'
        result = execute_claim(worker, descriptor, runtime.worker_executor); run.refresh_from_db()
        assert result.get('status') == 'succeeded' and run.status == 'completed', {'result': result, 'status': run.status,
            'stop_reason': run.stop_reason, 'stages': list(run.stage_attempts.values('sequence', 'phase', 'status'))}
        return result
    # Preserve private tracebacks only in this opt-in fixture, never as worker/API result egress.
    import traceback
    original_stage = runtime._numerical_stage
    def traced(*a, **k):
        try: return original_stage(*a, **k)
        except Exception:
            traceback.print_exc(); raise
    runtime._numerical_stage = traced
    reward = create()
    with device_lease('cpu'):
        refused = client.post(f'/api/v1/alignment-runs/{reward.run_id}/execute/', {}, format='json')
        assert refused.status_code == 400 and Job.all_objects.count() == BudgetReservation.all_objects.count() == 0
    launch(reward); execute(reward)
    reward_bundle = runtime.candidate_bundle(reward.output_model_version, tenant.pk, project.pk, role='reward')
    report['reward'] = {'run_id': str(reward.run_id), 'metrics': reward.metrics_history,
        'evaluation': reward.latest_metrics['independent_evaluation'], 'bundle': reward_bundle}
    (args.output / 'reward-report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    assert reward.latest_metrics['independent_evaluation']['passed'], report['reward']['evaluation']
    body.update(algorithm='rloo', reward_model_version=reward.output_model_version_id,
        held_out_dataset_artifact=artifacts['policy_heldout']['artifact_id'], regression_dataset_artifact=artifacts['policy_regression']['artifact_id'],
        hyperparameters={**body['hyperparameters'], 'learning_rate': .00002, 'rollout_group_size': 2, 'max_new_tokens': 3,
            'beta': .1, 'max_kl_divergence': .5, 'rollout_budget_policy_id': str(policies['generated_tokens'].policy_id)})
    baseline = launch(create()); execute(baseline)
    final = baseline.checkpoints.order_by('-step').first().policy_state
    report['policy'] = {'run_id': str(baseline.run_id), 'metrics': baseline.metrics_history,
        'weights_sha256': final['files']['adapter_model.safetensors']['sha256'], 'adam_sha256': final['adam']['sha256'],
        'evaluation': baseline.latest_metrics['independent_evaluation']}
    assert snapshot(baseline.output_model_version, tenant.pk, project.pk)['trained']
    print('Real CPU reward and RLOO stages completed; independent gates recorded.', flush=True)
    report['recovery'] = []
    for stop_sequence in (1, 2, 3):
        recovery = launch(create()); worker.refresh_from_db(); descriptor = claim_job(worker, recovery.job); assert descriptor
        attempt = JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
        class ExpireAfterStage(ExecutionContext):
            def heartbeat(self, progress=None):
                if recovery.checkpoints.filter(step=stop_sequence).exists():
                    JobAttempt.all_objects.filter(pk=self.attempt.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
                    self.lease_lost = True; return False
                return super().heartbeat(progress)
        runtime.worker_executor(descriptor, ExpireAfterStage(attempt, descriptor['fencing_token']))
        assert not commit_result(attempt, descriptor['fencing_token'], 'succeeded')
        assert reconcile_expired_leases(job_ids=[recovery.job.job_id]) == 1
        response = client.post(f'/api/v1/alignment-runs/{recovery.run_id}/resume/', {}, format='json'); assert response.status_code == 200, response.data
        recovery.refresh_from_db(); execute(recovery)
        restored = recovery.checkpoints.order_by('-step').first().policy_state
        assert restored['files']['adapter_model.safetensors']['sha256'] == final['files']['adapter_model.safetensors']['sha256']
        assert restored['adam']['sha256'] == final['adam']['sha256']
        assert restored['rng'] == final['rng'] and restored['rollouts'] == final['rollouts']
        report['recovery'].append({'after_sequence': stop_sequence, 'adapter_and_adam_exact': True, 'rng_and_rollouts_exact': True,
            'attempts': recovery.job.attempt_count, 'stage_usage': recovery.latest_metrics['stage_usage']})
    # Interrupt during an uncommitted rollout, then recover from the last durable RNG state.
    uncertain = launch(create()); worker.refresh_from_db(); descriptor = claim_job(worker, uncertain.job); assert descriptor
    attempt = JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
    class LoseDuringRollout(ExecutionContext):
        seen = 0
        def heartbeat(self, progress=None):
            if uncertain.stage_attempts.filter(phase='rollout', status='started').exists():
                self.seen += 1
                if self.seen == 3:
                    JobAttempt.all_objects.filter(pk=self.attempt.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
                    self.lease_lost = True; return False
            return super().heartbeat(progress)
    runtime.worker_executor(descriptor, LoseDuringRollout(attempt, descriptor['fencing_token']))
    assert reconcile_expired_leases(job_ids=[uncertain.job.job_id]) == 1
    uncertain.refresh_from_db()
    assert uncertain.stage_attempts.get(sequence=1).status == 'uncertain'
    response = client.post(f'/api/v1/alignment-runs/{uncertain.run_id}/resume/', {}, format='json'); assert response.status_code == 200
    uncertain.refresh_from_db(); execute(uncertain)
    assert uncertain.checkpoints.order_by('-step').first().policy_state['files']['adapter_model.safetensors']['sha256'] == final['files']['adapter_model.safetensors']['sha256']
    report['uncertain_stage'] = uncertain.latest_metrics['stage_usage']
    assert report['uncertain_stage']['uncertain_upper_units']['generated_tokens'] == 6
    assert report['uncertain_stage']['measured_units']['generated_tokens'] == 12

    cancelled = launch(create()); worker.refresh_from_db(); descriptor = claim_job(worker, cancelled.job); assert descriptor
    class CancelAfterRollout(ExecutionContext):
        def heartbeat(self, progress=None):
            if cancelled.checkpoints.filter(step=1).exists():
                response = client.post(f'/api/v1/alignment-runs/{cancelled.run_id}/cancel/', {}, format='json')
                assert response.status_code == 200
            return super().heartbeat(progress)
    attempt = JobAttempt.all_objects.get(attempt_id=descriptor['attempt_id'])
    context = CancelAfterRollout(attempt, descriptor['fencing_token'])
    runtime.worker_executor(descriptor, context)
    assert commit_result(attempt, descriptor['fencing_token'], 'interrupted')
    cancelled.refresh_from_db()
    assert cancelled.status == 'cancelled' and not cancelled.output_model_version_id and cancelled.current_step == 0
    report['cancellation'] = cancelled.latest_metrics['stage_usage']
    assert report['cancellation']['measured_units']['generated_tokens'] == 6

    stopped = launch(create(hyperparameters={**body['hyperparameters'], 'max_kl_divergence': 0.}))
    worker.refresh_from_db(); descriptor = claim_job(worker, stopped.job); assert descriptor
    result = execute_claim(worker, descriptor, runtime.worker_executor); stopped.refresh_from_db()
    assert result['status'] == 'failed' and not stopped.output_model_version_id and stopped.current_step == 0
    assert stopped.stop_reason == 'categorical_kl_stop'
    receipt = stopped.stage_attempts.get(phase='policy_update')
    assert receipt.status == 'measured_aborted' and receipt.actual_units['training_steps'] == 1
    report['divergence_stop'] = {'reason': stopped.stop_reason, 'usage': stopped.latest_metrics['stage_usage']}

    from unittest.mock import patch
    unavailable = launch(create())
    original_evaluation = runtime._evaluation
    def missing_scorer(*a, **k):
        with patch.object(runtime.subprocess, 'Popen', side_effect=FileNotFoundError('Injected missing scorer executable')):
            return original_evaluation(*a, **k)
    with patch.object(runtime, '_evaluation', side_effect=missing_scorer):
        execute(unavailable)
    assert unavailable.latest_metrics['independent_evaluation']['status'] == 'unavailable'
    assert not unavailable.latest_metrics['independent_evaluation']['passed'] and unavailable.output_model_version.state == 'draft'
    report['unavailable_gate'] = unavailable.latest_metrics['independent_evaluation']

    response = client.post('/api/v1/alignment-runs/register-preferences/', {'name': 'Reversed fixture labels', 'labels_reviewed': True,
        'samples': [{'prompt': 'Q: Be kind? A:', 'chosen': ' no', 'rejected': ' yes', 'source_group_id': 'authored-reversed-held'}]}, format='json')
    assert response.status_code == 201
    failed = launch(create(algorithm='reward_model', reward_model_version=None,
        held_out_dataset_artifact=response.data['artifact_id'], regression_dataset_artifact=artifacts['regression']['artifact_id'],
        hyperparameters={'learning_rate': .001, 'max_gradient_norm': 1., 'budget_policy_id': str(policies['training_steps'].policy_id),
            'scoring_budget_policy_id': str(policies['alignment_scores'].policy_id)}))
    execute(failed)
    assert not failed.latest_metrics['independent_evaluation']['passed'] and failed.output_model_version.state == 'draft'
    rejected = client.post('/api/v1/alignment-runs/', {**body, 'reward_model_version': failed.output_model_version_id}, format='json')
    assert rejected.status_code == 400
    report['failed_gate'] = {'evaluation': failed.latest_metrics['independent_evaluation'], 'rloo_admission_status': rejected.status_code}

    for run, name in ((reward, 'reward'), (baseline, 'rloo')):
        download = client.get(f'/api/v1/alignment-runs/{run.run_id}/download/'); assert download.status_code == 200
        with (args.output / (name + '.zip')).open('wb') as stream:
            for block in download.streaming_content: stream.write(block)
        download.close()
    report['accounting'] = list(UsageEvent.all_objects.values('unit', 'quantity', 'detail'))
finally:
    ApiKey.objects.filter(is_active=True).update(is_active=False)
    Worker.all_objects.update(status='offline', slots=0); Tenant.objects.update(status='suspended')
    for run in AlignmentRun.all_objects.filter(status__in=['pending', 'running', 'interrupted'], job__isnull=False):
        runtime.cancel(run)
        run.job.refresh_from_db()
        if run.job.status == 'running':
            attempt = run.job.attempts.filter(status='running').first()
            if attempt: commit_result(attempt, attempt.fencing_token, 'interrupted')
    report['cleanup'] = {'active_keys': ApiKey.objects.filter(is_active=True).count(),
        'online_workers': Worker.all_objects.exclude(status='offline').count(),
        'reserved_budgets': BudgetReservation.all_objects.filter(state='reserved').count()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2, default=str, allow_nan=False))
    print('Fixture credentials revoked, workers offline and tenants suspended.', flush=True)
