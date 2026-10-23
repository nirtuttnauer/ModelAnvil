import json
from django.core.management.base import BaseCommand,CommandError
from modelanvil.identity.models import Project
from modelanvil.rag.decoder import register


class Command(BaseCommand):
    help='Register a verified cached Apache-2.0 CPU RAG decoder in one project; no request downloads.'

    def add_arguments(self,parser):
        parser.add_argument('--project',required=True)
        parser.add_argument('--accepted-license',choices=['apache-2.0'],required=True)

    def handle(self,*args,**options):
        try:
            project=Project.all_objects.get(pk=options['project']);model=register(project)
        except (Project.DoesNotExist,ValueError) as exc:raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({'model_version_id':str(model.model_version_id),'architecture':model.architecture_ref,
            'source':model.metadata['source'],'load_tested':False}))
