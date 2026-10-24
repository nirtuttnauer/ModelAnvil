"""Create one private self-hosted workspace without development credentials or example evidence."""
import json
import sys
from django.core.management.base import BaseCommand,CommandError
from django.core.validators import validate_email
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from modelanvil.identity.models import Tenant,User,Membership,Team,Project,Role
from modelanvil.core.models import ProjectPrivacyPolicy
from modelanvil.jobs.models import WorkerPool,Worker
from modelanvil.runners.models import RunnerManifest
from modelanvil.runners.training import general_runtime as runtime


class Command(BaseCommand):
    help='Initialize a fresh self-hosted database from private stdin JSON (email,password,name). No default password, API key or model is created.'

    @transaction.atomic
    def handle(self,*args,**options):
        raw=sys.stdin.buffer.read(8193)
        try:
            value=json.loads(raw)
            if len(raw)>8192 or not isinstance(value,dict) or set(value)!={'email','password','name'} or any(not isinstance(v,str) for v in value.values()):raise ValueError()
            validate_email(value['email'])
            if len(value['email'])>254 or not 1<=len(value['name'].strip())<=80 or not 12<=len(value['password'])<=256:raise ValueError()
            validate_password(value['password'])
        except (ValueError,TypeError,ValidationError):raise CommandError('Use a valid email,1–80 character name and a strong12–256 character password on private stdin.') from None
        if Tenant.objects.exists() or User.objects.exists():raise CommandError('Initialization requires a fresh database; existing accounts and data are retained.')
        tenant=Tenant.objects.create(slug='selfhost',name=value['name'].strip())
        user=User(email=value['email'].lower(),name='Workspace owner');user.set_password(value['password']);user.save()
        Membership.objects.create(tenant=tenant,user=user,role=Role.OWNER)
        team=Team.objects.create(tenant_id=tenant.pk,name='Local models',slug='local')
        project=Project.objects.create(tenant_id=tenant.pk,team=team,name='Local workspace',slug='workspace')
        ProjectPrivacyPolicy.all_objects.create(tenant_id=tenant.pk,project=project,offline=True,acquisition_origins=[])
        pool=WorkerPool.all_objects.create(tenant_id=tenant.pk,name='Local CPU reference',status='active')
        worker=Worker.all_objects.create(tenant_id=tenant.pk,pool=pool,name='Local CPU reference',slots=1,
            capabilities={'training_runtime':runtime.CONTRACT_DIGEST,'memory_bytes':runtime.LIMITS['memory_bytes']})
        manifest=runtime.runner_manifest()
        runner=RunnerManifest.all_objects.create(tenant_id=tenant.pk,name='Local CPU transformer full SFT',version='1',
            manifest=manifest,digest=runtime.digest(manifest),compatibility={'contract_digest':runtime.CONTRACT_DIGEST})
        self.stdout.write(json.dumps({'tenant':str(tenant.pk),'project':str(project.pk),'worker_id':worker.pk,'pool':pool.pk,
            'runner_manifest':runner.pk,'runtime':runtime.RUNTIME_ID,'offline':True,'models_created':0,'api_keys_created':0,'production_qualified':False}))
