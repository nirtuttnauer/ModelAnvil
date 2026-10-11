#!/usr/bin/env python3
"""Isolated public Hub import/resume and real CPU/MPS chat API evidence."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True, help='New directory for the isolated DB, artifacts and report')
parser.add_argument('--resume-source', type=Path, help='Prime a 1 MiB partial weight file from the pinned snapshot')
parser.add_argument('--gguf', type=Path, help='Also import and execute an operator-converted local GGUF file')
parser.add_argument('--mlx', action='store_true', help='Also import and execute the same verified weights with MLX')
args = parser.parse_args()
args.output = args.output.resolve()
args.output.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(args.output / 'workspace.sqlite'))
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.core.tenancy import set_active_project, set_active_tenant
from modelanvil.jobs.models import JobAttempt, Worker, claim_job
from modelanvil.jobs.executor import execute_claim
from modelanvil.runners.model_catalog import model_import_executor
from modelanvil.runners.training.hf_runtime import SOURCE

override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': str(args.output / 'artifacts')})
override.enable()
call_command('migrate', verbosity=0)
tenant = Tenant.objects.create(slug='workspace-pilot', name='Workspace pilot')
set_active_tenant(tenant.pk)
team = Team.objects.create(tenant_id=tenant.pk, name='Pilot', slug='pilot')
project = Project.objects.create(tenant_id=tenant.pk, team=team, name='Pilot', slug='pilot')
set_active_project(project.pk)
secret, hashed = generate_api_key()
ApiKey.objects.create(tenant=tenant, project=project, name='Pilot', role=Role.ENGINEER, secret_hash=hashed)
client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
call_command('setup_model_import', tenant_id=str(tenant.pk))
worker = Worker.all_objects.get(tenant_id=tenant.pk, capabilities__model_import=True)

def checked(response, expected):
    if response.status_code != expected:
        raise RuntimeError(f'HTTP {response.status_code}: {response.content.decode()[:2000]}')
    return response.data

plan = checked(client.post('/api/v1/model-imports/inspect/', {**SOURCE, 'format': 'safetensors'}, format='json'), 200)
resume_bytes = 0
if args.resume_source:
    cache = args.output / 'artifacts' / '.model-cache' / str(tenant.pk) / str(project.pk) / SOURCE['revision']
    cache.mkdir(parents=True)
    with (args.resume_source / 'model.safetensors').open('rb') as source:
        partial = source.read(1024 * 1024)
    (cache / 'model.safetensors.partial').write_bytes(partial)
    resume_bytes = len(partial)
launched = checked(client.post('/api/v1/model-imports/', {'name': 'SmolLM2 pilot', 'repo_id': SOURCE['repo_id'], 'revision': SOURCE['revision'],
    'accepted_license': plan['license'], 'idempotency_key': 'public-pilot', 'pool': worker.pool_id}, format='json'), 201)
started = time.monotonic()
outcome = execute_claim(worker, claim_job(worker), model_import_executor)
attempt = JobAttempt.all_objects.get(job__job_id=launched['job_id'])
if outcome.get('status') != 'succeeded':
    raise RuntimeError(f'Import failed: {outcome}; {attempt.error}')
imported = checked(client.get(f"/api/v1/model-imports/{launched['import_id']}/"), 200)
outputs = {}
for device in ['cpu', 'mps:0']:
    body = {'model': imported['candidate_id'], 'messages': [{'role': 'user', 'content': 'Once upon a time'}],
            'max_tokens': 12, 'temperature': 0, 'seed': 42, 'device': device}
    completed = checked(client.post('/api/v1/inference/chat/completions', body, format='json'), 200)
    outputs[device] = completed
    print(f"{device}: {completed['choices'][0]['message']['content']}", flush=True)
if args.mlx:
    mlx = checked(client.post('/api/v1/model-imports/', {'name': 'SmolLM2 MLX pilot', 'format': 'mlx',
        'files': imported['acquired_files'], 'accepted_license': plan['license'], 'idempotency_key': 'mlx-pilot'}, format='json'), 201)
    outputs['mlx:0'] = checked(client.post('/api/v1/inference/chat/completions', {**body, 'model': mlx['candidate_id'], 'device': 'mlx:0'}, format='json'), 200)
    print('mlx:0: ' + outputs['mlx:0']['choices'][0]['message']['content'], flush=True)
if args.gguf:
    from modelanvil.runners.model_catalog import _store
    with args.gguf.open('rb') as source:
        ref = _store(source, tenant=tenant.pk, project=project.pk, name=args.gguf.name)
    gguf = checked(client.post('/api/v1/model-imports/', {'name': 'SmolLM2 GGUF pilot', 'files': {args.gguf.name: ref},
        'accepted_license': plan['license'], 'idempotency_key': 'gguf-pilot'}, format='json'), 201)
    outputs['gguf:cpu'] = checked(client.post('/api/v1/inference/chat/completions', {**body, 'model': gguf['candidate_id'], 'device': 'cpu'}, format='json'), 200)
    print('gguf:cpu: ' + outputs['gguf:cpu']['choices'][0]['message']['content'], flush=True)
report = {'source': SOURCE, 'plan': plan, 'import_id': imported['import_id'], 'candidate_id': imported['candidate_id'],
          'resume_primed_bytes': resume_bytes, 'job': outcome, 'wall_seconds': time.monotonic() - started, 'outputs': outputs,
          'cpu_mps_equal': outputs['cpu']['choices'] == outputs['mps:0']['choices'],
          'qualification': 'Public pinned import and bounded local inference on this Mac only; other runtimes/hardware pending.'}
(args.output / 'report.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
assert report['cpu_mps_equal'], 'CPU/MPS greedy completions differ; inspect tolerance before qualification.'
print('Saved ' + str(args.output / 'report.json'))
