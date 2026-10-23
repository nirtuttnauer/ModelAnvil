"""Trusted operator CLI; training is local and never invoked by an HTTP request."""
import json
from django.core.management.base import BaseCommand, CommandError
from modelanvil.core.tenancy import reset_context, set_active_tenant, set_active_project
from modelanvil.identity.models import Project
from modelanvil.artifacts.models import Artifact
from modelanvil.rag.embedding_training import publish


class Command(BaseCommand):
    help='Fine-tune pinned MiniLM on a committed protected-triplet manifest and publish a private candidate.'

    def add_arguments(self,parser):
        parser.add_argument('--project',required=True)
        parser.add_argument('--manifest-artifact',required=True)
        parser.add_argument('--name',required=True)
        parser.add_argument('--steps',type=int,default=4)
        parser.add_argument('--learning-rate',type=float,default=.001)
        parser.add_argument('--seed',type=int,default=7)

    def handle(self,*args,**options):
        reset_context()
        try:
            project=Project.all_objects.get(pk=options['project']);set_active_tenant(project.tenant_id);set_active_project(project.pk)
            source=Artifact.all_objects.get(tenant_id=project.tenant_id,artifact_id=options['manifest_artifact'])
            result=publish(project=project,source=source,name=options['name'],steps=options['steps'],
                learning_rate=options['learning_rate'],seed=options['seed'])
            self.stdout.write(json.dumps({'candidate_id':str(result.candidate_id),'space_id':str(result.space.space_id),
                'export_artifact':str(result.export.artifact_id),'export_sha256':result.export_digest,
                'protocol':result.protocol,'report':result.report},sort_keys=True))
        except (ValueError,Project.DoesNotExist,Artifact.DoesNotExist) as exc:raise CommandError(str(exc)) from exc
        finally:reset_context()
