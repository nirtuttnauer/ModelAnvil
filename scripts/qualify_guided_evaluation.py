"""Run the native classification journey in a new disposable local installation."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=3)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(output / 'pilot.sqlite3'),
        MODELANVIL_ARTIFACT_ROOT=str(output / 'artifacts'), MODELANVIL_LOCAL_MODEL_DIR=str(args.model_dir.resolve()),
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='4')
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import close_old_connections
    from modelanvil.identity.models import Tenant, Team, Project, ApiKey, Role, generate_api_key
    from modelanvil.core.tenancy import set_active_tenant, set_active_project
    from modelanvil.runners.training.managed import host_status
    from modelanvil.runners.models import TrainingRun, EvaluationRun
    from modelanvil.artifacts.models import Dataset, Artifact
    from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
    from modelanvil.data.publication import publish_prepared_dataset
    from modelanvil.jobs.models import JobAttempt, Worker
    from modelanvil.jobs.setup import connection_state
    from rest_framework.test import APIClient
    call_command('migrate', verbosity=0)
    tenant = Tenant.objects.create(name='Native classification qualification', slug='native-classification')
    set_active_tenant(tenant.pk)
    team = Team.objects.create(tenant_id=tenant.pk, name='Pilot', slug='pilot')
    project = Project.objects.create(tenant_id=tenant.pk, team=team, name='Classification', slug='classification')
    set_active_project(project.pk)
    secret, hashed = generate_api_key()
    ApiKey.objects.create(tenant=tenant, project=project, name='Pilot', role=Role.ADMIN, secret_hash=hashed)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}', HTTP_X_PROJECT_ID=str(project.pk))
    logfile = (output / 'managed-service.log').open('w')
    service = subprocess.Popen([sys.executable, str(root / 'manage.py'), 'run_managed_training'],
        cwd=root, env=os.environ.copy(), stdout=logfile, stderr=subprocess.STDOUT)
    def wait(check, description, seconds=600):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            close_old_connections()
            if service.poll() is not None:
                raise RuntimeError('Managed service exited; inspect its log.')
            result = check()
            if result:
                print(description, flush=True)
                return result
            time.sleep(2)
        raise TimeoutError(description)
    def post(path, body):
        response = client.post(path, body, format='json', HTTP_IDEMPOTENCY_KEY=hashlib.sha256((path + json.dumps(body, sort_keys=True)).encode()).hexdigest())
        data = response.data if hasattr(response, 'data') else response.json()
        assert response.status_code in (200, 201, 202), (path, response.status_code, data)
        return data
    try:
        wait(lambda: host_status()['available'], 'managed service ready')
        inputs = post('/api/v1/fine-tuning/setup/', {})['inputs']
        examples = []
        for index in range(30):
            for label, text in [('billing', 'I need a copy of my paid invoice'), ('access', 'I cannot sign in to my account'),
                                ('technical', 'The application crashes when I open a file')]:
                examples.append({'prompt': f'Classify this support request. Reply with exactly one label: billing, access, technical. Request {index}: {text}.',
                    'response': label, 'group_id': f'{label}-{index}'})
        raw = '\n'.join(json.dumps(row) for row in examples).encode()
        artifact = Artifact.objects.create(tenant_id=tenant.pk, project=project, storage_location_id='local',
            object_key='pilot/classification.jsonl', sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type='application/x-ndjson')
        upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
        dataset = Dataset.objects.create(tenant_id=tenant.pk, project=project, name='Synthetic routing correctness pilot')
        revision = publish_prepared_dataset(dataset, artifact, source_format='training', dedup={'exact': True, 'near': False})
        payload = {**inputs, 'dataset_revision': revision.pk, 'total_steps': args.steps}
        preflight = post('/api/v1/training-runs/preflight/', payload)
        assert preflight['status'] == 'approved', preflight
        training_data = post('/api/v1/training-runs/', {**payload, 'preflight_token': preflight['preflight_token']})
        run_id = training_data['run_id']
        def training_done():
            run = TrainingRun.all_objects.get(run_id=run_id)
            if run.status in ('failed', 'cancelled'):
                raise RuntimeError(str(list(JobAttempt.all_objects.filter(job=run.job).values('status', 'error'))))
            return run if run.status == 'completed' else None
        training = wait(training_done, 'real adapter training completed', 1200)
        prepared = post(f'/api/v1/training-runs/{run_id}/prepare-evaluation/', {})
        evaluation_id = prepared['evaluation']['run_id']
        wait(lambda: any(connection_state(worker) == 'connected' for worker in Worker.all_objects.filter(pool_id=prepared['launch']['pool'])),
             'managed native evaluator connected', 60)
        queued = post(f'/api/v1/evaluation-runs/{evaluation_id}/execute/', prepared['launch'])
        duplicate = post(f'/api/v1/evaluation-runs/{evaluation_id}/execute/', prepared['launch'])
        assert queued['job'] == duplicate['job']
        def evaluation_done():
            run = EvaluationRun.all_objects.get(run_id=evaluation_id)
            if run.status in ('failed', 'cancelled'):
                raise RuntimeError(str(list(JobAttempt.all_objects.filter(job=run.job).values('status', 'error'))))
            return run if run.status == 'completed' else None
        evaluation = wait(evaluation_done, 'exact adapter/base native comparison completed', 1200)
        recorded = client.get(f'/api/v1/evaluation-runs/{evaluation_id}/').data
        decision = post(f'/api/v1/evaluation-runs/{evaluation_id}/record-decision/', {'outcome': 'reject'})
        response = client.get(f'/api/v1/training-runs/{run_id}/download/?export_format=native&evaluation_run={evaluation_id}')
        assert response.status_code == 200, response.data if hasattr(response, 'data') else response.status_code
        archive_path = output / 'reviewed-candidate.zip'
        with archive_path.open('wb') as target:
            for block in response.streaming_content:
                target.write(block)
        response.close()
        destination = output / 'independent-candidate'
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(destination)
        case = evaluation.suite_version.cases[0]
        independent = subprocess.run([sys.executable, '-I', str(destination / 'infer.py'), str(destination),
            '--device', 'mps:0', '--max-tokens', '32', '--prompt', case['input_prompt']],
            cwd=destination, env=os.environ.copy(), capture_output=True, text=True, timeout=300)
        assert independent.returncode == 0, independent.stderr[-4000:]
        actual = json.loads(independent.stdout)
        expected = evaluation.case_results.get(case_id=case['case_id']).candidate_output
        assert actual['text'] == expected, {'actual': actual['text'], 'expected': expected}
        checksum = hashlib.sha256()
        with archive_path.open('rb') as source:
            while block := source.read(1024 * 1024):
                checksum.update(block)
        report = {'scope': 'Synthetic classification correctness pilot on one Apple GPU. This is not a model-quality or production qualification.',
            'training_run': str(run_id), 'steps': args.steps, 'candidate': str(training.output_model_version.model_version_id),
            'selected_checkpoint_step': training.output_model_version.metadata['selected_checkpoint_step'],
            'evaluation': recorded, 'decision': decision, 'warnings': prepared['warnings'], 'labels': prepared['labels'],
            'export_sha256': checksum.hexdigest(), 'export_bytes': archive_path.stat().st_size,
            'independent_loading_matches': True, 'independent': actual, 'production_qualified': False}
        (output / 'report.json').write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps({'report': str(output / 'report.json'), 'candidate_accuracy': recorded['decision_report']['candidate']['accuracy'],
            'baseline_accuracy': recorded['decision_report']['baseline']['accuracy'], 'independent_loading_matches': True}), flush=True)
    finally:
        service.terminate()
        try:
            service.wait(timeout=30)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait(timeout=10)
        logfile.close()


if __name__ == '__main__':
    main()
