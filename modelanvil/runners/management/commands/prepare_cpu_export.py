"""Trusted local operator conversion; never runs inside a web request."""
import json
import subprocess
from django.core.management.base import BaseCommand, CommandError
from modelanvil.core.tenancy import reset_context, set_active_tenant, set_active_project
from modelanvil.core.models import record_audit
from modelanvil.identity.models import Project
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training.cpu_exports import prepare, FORMATS


class Command(BaseCommand):
    help = 'Prepare a recoverable CPU Safetensors/LoRA-merge or Q8_0 GGUF archive for an actual completed run.'

    def add_arguments(self, parser):
        parser.add_argument('--project', required=True)
        parser.add_argument('--run', required=True)
        parser.add_argument('--format', choices=sorted(FORMATS), required=True)

    def handle(self, *args, **options):
        reset_context()
        try:
            project = Project.all_objects.get(pk=options['project'])
            set_active_tenant(project.tenant_id); set_active_project(project.pk)
            run = TrainingRun.all_objects.get(tenant_id=project.tenant_id, project_id=project.pk, run_id=options['run'])
            artifact = prepare(run, options['format'])
            record_audit('training.cpu_export', 'artifact', artifact.artifact_id,
                         actor_id='local-operator', actor_kind='system',
                         input_snapshot={'run_id': str(run.run_id), 'format': options['format'], 'sha256': artifact.sha256})
            self.stdout.write(json.dumps({'artifact_id': str(artifact.artifact_id), 'sha256': artifact.sha256,
                'byte_size': artifact.byte_size, 'export': artifact.metadata['cpu_export']}, sort_keys=True))
        except (ValueError, OSError, subprocess.TimeoutExpired, Project.DoesNotExist, TrainingRun.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        finally:
            reset_context()
