#!/usr/bin/env python3
"""Restore an isolated local SQLite/filesystem copy and verify actual application state.

No source mutation, worker launch or external storage access. The destination must
not exist. Restored credentials remain private; no secrets appear in the report.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time


def verify():
    import django
    django.setup()
    from modelanvil.artifacts.models import Artifact
    from modelanvil.artifacts.storage import artifact_storage_backend
    from modelanvil.budgets.models import BudgetReservation, UsageEvent
    from modelanvil.core.tenancy import set_active_project, set_active_tenant
    from modelanvil.identity.models import ApiKey, Role, generate_api_key
    from modelanvil.jobs.models import Job, JobAttempt, commit_result
    from modelanvil.releases.models import ReleaseVersion, ServingEndpoint
    from modelanvil.releases.review import candidate_archive
    from modelanvil.releases.local_serving import serve_local
    from rest_framework.test import APIClient
    checked = 0
    for artifact in Artifact.all_objects.filter(state='committed'):
        sha, size = hashlib.sha256(), 0
        with artifact_storage_backend().open(artifact.tenant_id, artifact.object_key) as source:
            while block := source.read(1024*1024):
                sha.update(block); size += len(block)
        if sha.hexdigest() != artifact.sha256 or size != artifact.byte_size:
            raise ValueError('Restored artifact failed integrity checks.')
        checked += 1
    usage_before = list(UsageEvent.all_objects.order_by('pk').values('provider_event_key','quantity','unit','reservation_id'))
    reservations_before = list(BudgetReservation.all_objects.order_by('pk').values('job_id','state','estimated_amount','settled_amount'))
    duplicates = 0
    for attempt in JobAttempt.all_objects.filter(status='succeeded'):
        set_active_tenant(attempt.tenant_id)
        if commit_result(attempt, attempt.fencing_token, 'succeeded'):
            raise ValueError('Restored terminal attempt accepted duplicate completion.')
        duplicates += 1
    releases = 0
    for version in ReleaseVersion.all_objects.exclude(bundle_manifest__local_review__isnull=True):
        if not version.bundle_manifest.get('local_review'):
            continue
        set_active_tenant(version.tenant_id); set_active_project(version.project_id)
        candidate_archive(version)
        secret, hashed = generate_api_key()
        key = ApiKey.objects.create(tenant_id=version.tenant_id, project_id=version.project_id,
            name='Temporary isolated restore verification', role=Role.VIEWER, secret_hash=hashed)
        try:
            client = APIClient(); client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
            response = client.get(f'/api/v1/release-versions/{version.release_version_id}/')
            if response.status_code != 200:
                raise ValueError('Restored release is not accessible to its authorized scope.')
        finally:
            key.delete()
        releases += 1
    served = 0
    for endpoint in ServingEndpoint.all_objects.filter(active_deployment__serving_config__backend='modelanvil.local-on-demand-cpu.v1'):
        set_active_tenant(endpoint.tenant_id); set_active_project(endpoint.project_id)
        serve_local(endpoint, 'x', 2); served += 1
    set_active_tenant(None); set_active_project(None)
    if usage_before != list(UsageEvent.all_objects.order_by('pk').values('provider_event_key','quantity','unit','reservation_id')):
        raise ValueError('Restore verification duplicated or changed usage.')
    if reservations_before != list(BudgetReservation.all_objects.order_by('pk').values('job_id','state','estimated_amount','settled_amount')):
        raise ValueError('Restore verification changed accounting reservations.')
    return {'artifacts_verified': checked, 'accessible_reviewed_releases': releases, 'local_endpoints_reloaded': served,
        'duplicate_terminal_commits_refused': duplicates, 'usage_and_reservations_unchanged': True,
        'unresolved_job_ownership': list(Job.all_objects.filter(status='running').values_list('job_id',flat=True)),
        'queued_jobs_retained': Job.all_objects.filter(status='queued').count()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path); parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--destination', type=Path); parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(), default=str)); return
    if not all((args.database, args.artifacts, args.destination)):
        parser.error('Specify database, artifacts and a new destination directory.')
    database, artifacts, target = args.database.resolve(), args.artifacts.resolve(), args.destination.resolve()
    if target.exists() or not database.is_file() or not artifacts.is_dir():
        parser.error('Select existing local inputs and a new destination.')
    if target == artifacts or artifacts in target.parents or any(p.is_symlink() for p in artifacts.rglob('*')):
        parser.error('Use separate local directories with no artifact symlinks.')
    started = time.monotonic(); target.mkdir(parents=True, mode=0o700)
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as source, sqlite3.connect(target/'restored.db') as destination:
        source.backup(destination)
        if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Restored database failed integrity checks.')
    os.chmod(target/'restored.db', 0o600)
    shutil.copytree(artifacts, target/'artifacts')
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'DJANGO_SETTINGS_MODULE':'modelanvil.settings', 'DATABASE_ENGINE':'sqlite', 'MODELANVIL_ARTIFACT_BACKEND':'filesystem', 'DATABASE_NAME':str(target/'restored.db'),
           'MODELANVIL_ARTIFACT_ROOT':str(target/'artifacts'), 'PYTHONPATH':str(root)}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--verify'], cwd=root,
        env=env, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    report = {'scope':'local_sqlite_filesystem_restore', 'topology': 'One local application service, trusted DB-polling workers and filesystem artifacts; broker not used.',
        'database_integrity':'ok', 'elapsed_seconds':time.monotonic()-started,
        'production_qualified':False, **json.loads(result.stdout)}
    (target/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
