"""Trusted bounded operator command; inputs and output remain in the chosen project."""
import json
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from modelanvil.core.tenancy import reset_context,set_active_project,set_active_tenant
from modelanvil.identity.models import Project
from modelanvil.rag.decoder import register
from modelanvil.context_lab.positions import run


class Command(BaseCommand):
    help='Run the fixed real CPU evidence-position protocol using the pinned public decoder; save a new measured report.'

    def add_arguments(self,parser):
        parser.add_argument('--project',required=True)
        parser.add_argument('--output',required=True)
        parser.add_argument('--accepted-license',choices=['apache-2.0'],required=True)

    def handle(self,*args,**options):
        output=Path(options['output'])
        if not output.is_absolute() or output.exists():raise CommandError('Choose a new absolute report path; existing evidence is never overwritten.')
        try:
            project=Project.all_objects.get(pk=options['project'])
            set_active_tenant(project.tenant_id);set_active_project(project.pk)
            model=register(project);report=run(model)
            with output.open('x') as stream:json.dump(report,stream,indent=2)
        except (ValueError,Project.DoesNotExist) as exc:raise CommandError(str(exc)) from exc
        finally:reset_context()
        self.stdout.write(json.dumps({'report':str(output),'summary':report['summary']}))
