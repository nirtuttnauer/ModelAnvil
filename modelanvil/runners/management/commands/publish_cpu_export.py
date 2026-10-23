"""Explicit trusted-operator publication of one immutable archive to one private Hub target."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from modelanvil.core.tenancy import reset_context, set_active_tenant, set_active_project
from modelanvil.core.privacy import project_policy
from modelanvil.core.models import record_audit
from modelanvil.identity.models import Project
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training.cpu_exports import open_export, FORMATS


class Command(BaseCommand):
    help = 'Publish an exact CPU archive only to the installed project-specific private Hub repository. Requires explicit SHA authorization.'

    def add_arguments(self, parser):
        for name in ('project', 'run', 'repo', 'authorize-sha256'):
            parser.add_argument('--' + name, required=True)
        parser.add_argument('--format', choices=sorted(FORMATS), required=True)

    def handle(self, *args, **options):
        reset_context()
        try:
            project = Project.all_objects.get(pk=options['project'])
            set_active_tenant(project.tenant_id); set_active_project(project.pk)
            policy = project_policy(project.tenant_id, project.pk)
            target = getattr(settings, 'MODELANVIL_HUB_EXPORT_TARGETS', {}).get(f'{project.tenant_id}:{project.pk}', {})
            if (policy['offline'] or options['repo'] != target.get('repo_id') or not target.get('token')
                    or 'https://huggingface.co' not in policy['acquisition_origins']):
                raise ValueError('Explicit project publication target, dedicated credential and online Hub permission are required.')
            run = TrainingRun.all_objects.get(tenant_id=project.tenant_id, project_id=project.pk, run_id=options['run'])
            record, stream = open_export(run, options['format'])
            with stream:
                if options['authorize_sha256'] != record.sha256:
                    raise ValueError('Authorize the exact current archive SHA-256 before uploading.')
                with tempfile.TemporaryDirectory(prefix='modelanvil-publish-') as directory:
                    path = Path(directory) / 'export.zip'
                    with path.open('wb') as output: shutil.copyfileobj(stream, output, 1024 * 1024)
                    request = {'path': str(path), 'repo_id': options['repo'], 'sha256': record.sha256,
                               'authorize_sha256': options['authorize_sha256'], 'token': target['token'],
                               'origins': target.get('origins', ['https://huggingface.co'])}
                    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT'}}
                    env.update(HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_XET='1')
                    worker = Path(__file__).resolve().parents[2] / 'training' / 'hub_export_worker.py'
                    result = subprocess.run([sys.executable, str(worker)], input=json.dumps(request), env=env,
                                            capture_output=True, text=True, timeout=600, check=False)
                    if result.returncode or len(result.stdout) > 16384:
                        raise ValueError('Private Hub publication returned no verified receipt; retry the identical archive to reconcile an unknown outcome.')
                    receipt = json.loads(result.stdout)
            record_audit('training.hub_export', 'artifact', record.artifact_id, actor_id='local-operator',
                         actor_kind='system', input_snapshot=receipt)
            self.stdout.write(json.dumps(receipt, sort_keys=True))
        except (ValueError, OSError, subprocess.TimeoutExpired, Project.DoesNotExist, TrainingRun.DoesNotExist) as exc:
            raise CommandError('Private Hub publication refused or unconfirmed. Verify the installed target and exact archive authorization; retry the same identity after a transport interruption.') from None
        finally:
            reset_context()
