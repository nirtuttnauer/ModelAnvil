"""Import a provisioned exact tool model and register its single local CPU worker."""
import hashlib
import io
import json
from pathlib import Path
import uuid
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend,upload_staged_artifact,LocalArtifactStorage
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.identity.models import Project
from modelanvil.jobs.models import Worker,WorkerPool
from modelanvil.runners.models import Model,ModelVersion,TokenizerVersion
from modelanvil.runners.training.hf_runtime import file_ref
from modelanvil.runners import tool_runtime as runtime


class Command(BaseCommand):
    help='Import the exact local Qwen3 tool snapshot and register one CPU worker. No download, grants or automatic execution.'

    def add_arguments(self,parser):
        parser.add_argument('--tenant-id',type=uuid.UUID,required=True)
        parser.add_argument('--project-id',type=uuid.UUID,required=True)
        parser.add_argument('--name',required=True)
        parser.add_argument('--model-dir',type=Path,required=True)
        parser.add_argument('--token-limit',type=int,default=1152)

    @transaction.atomic
    def handle(self,*args,**options):
        tenant,project,name=options['tenant_id'],options['project_id'],options['name'].strip()
        if not 1<=len(name)<=80 or not 1152<=options['token_limit']<=100000:raise CommandError('Use a1–80 character name and a1152–100000 generated-token quota.')
        if not Project.all_objects.filter(tenant_id=tenant,pk=project).exists():raise CommandError('Select a project belonging to this tenant.')
        if Model.all_objects.filter(tenant_id=tenant,name=name).exists():raise CommandError('Model name already exists; use a new name.')
        runtime.require_packages();observed=runtime.observed_device();directory=options['model_dir'];backend=artifact_storage_backend()
        if not isinstance(backend,LocalArtifactStorage):raise CommandError('The CPU tools worker requires shared local filesystem storage.')
        for filename,pin in runtime.FILES.items():
            path=directory/filename
            if not path.is_file() or path.is_symlink() or path.stat().st_size!=pin['byte_size']:raise CommandError(f'{filename}: exact source size differs.')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=pin['sha256']:raise CommandError(f'{filename}: exact source checksum differs.')
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False)
        if len(tokenizer)!=151669 or not tokenizer.chat_template:raise CommandError('Exact native tokenizer/template differs.')
        def store(name,stream,size,sha):
            artifact=Artifact.all_objects.create(tenant_id=tenant,project_id=project,storage_location_id='local',
                object_key=f'tool-input/{uuid.uuid4()}/{name}',sha256=sha,byte_size=size,media_type='application/octet-stream')
            upload_staged_artifact(artifact,stream,backend=backend);return artifact
        files={}
        for filename,pin in runtime.FILES.items():
            with (directory/filename).open('rb') as stream:files[filename]=file_ref(store(filename,stream,pin['byte_size'],pin['sha256']))
        raw=json.dumps({'source':runtime.SOURCE,'files':files},sort_keys=True).encode()
        manifest=store('snapshot.json',io.BytesIO(raw),len(raw),hashlib.sha256(raw).hexdigest())
        tok=TokenizerVersion.all_objects.create(tenant_id=tenant,project_id=project,name=f'{name}-tokenizer',vocabulary_size=151669,
            artifact_manifest_id=str(manifest.artifact_id),configuration_digest=runtime.digest(runtime.FILES),chat_template=tokenizer.chat_template,
            special_tokens={k:v for k,v in tokenizer.special_tokens_map.items() if isinstance(v,str)},compatibility={'hf_snapshot':runtime.SOURCE,'immutable_import':True})
        model=Model.all_objects.create(tenant_id=tenant,project_id=project,name=name,intended_tasks=['tool_chat'])
        version=ModelVersion.all_objects.create(tenant_id=tenant,project_id=project,model=model,tokenizer=tok,architecture_ref=runtime.RUNTIME_ID,
            artifact_manifest_id=str(manifest.artifact_id),parameters_count=596049920,metadata={'imported':True,'snapshot_manifest':file_ref(manifest),'source':runtime.SOURCE})
        pool=WorkerPool.all_objects.create(tenant_id=tenant,name=f'{name}-tools',status='active')
        worker=Worker.all_objects.create(tenant_id=tenant,pool=pool,name=f'{name}-tools',slots=1,capabilities={
            'tool_runtime':runtime.CONTRACT_DIGEST,'tool_packages':runtime.PACKAGES,'gpu_device':'cpu','memory_bytes':observed['device']['total_memory_bytes']})
        policy=BudgetPolicy.all_objects.create(tenant_id=tenant,name=f'{name}-tool-tokens',period='lifetime',unit='generated_tokens',limit_amount=options['token_limit'])
        self.stdout.write(json.dumps({'model':str(version.model_version_id),'worker_id':worker.pk,'pool':pool.pk,'budget_policy':str(policy.policy_id),
            'executor':'modelanvil.runners.tool_jobs.tool_executor','source':runtime.SOURCE,'accelerator':observed,'production_qualified':False},indent=2))
