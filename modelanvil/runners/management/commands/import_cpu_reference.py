"""Import verified local reference tensors and optional explicit example data; never launch compute."""
import io
import json
import sys
import uuid
import hashlib
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from modelanvil.artifacts.models import Dataset
from modelanvil.runners.model_catalog import _store
from modelanvil.runners.models import Model,ModelVersion,TokenizerVersion,RunnerManifest
from modelanvil.runners.training import general_runtime as runtime
from modelanvil.identity.models import Project
from modelanvil.jobs.models import Worker
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.data.publication import publish_prepared_dataset


class Command(BaseCommand):
    help='Import a bounded CPU reference JSON bundle from stdin into one project; optionally prepare an explicit small example recipe. Does not download or run training.'

    def add_arguments(self,parser):
        parser.add_argument('--tenant-id',type=uuid.UUID,required=True)
        parser.add_argument('--project-id',type=uuid.UUID,required=True)
        parser.add_argument('--name',required=True)
        parser.add_argument('--license',required=True)
        parser.add_argument('--example-worker-id',type=int)

    @transaction.atomic
    def handle(self,*args,**options):
        tenant,project,name=options['tenant_id'],options['project_id'],options['name'].strip()
        if not 1<=len(name)<=80 or not 1<=len(options['license'])<=64:raise CommandError('Use a1–80 character name and an explicit license expression up to64characters.')
        if not Project.all_objects.filter(tenant_id=tenant,pk=project).exists():raise CommandError('Select a project belonging to this tenant.')
        if Model.all_objects.filter(tenant_id=tenant,name=name).exists():raise CommandError('Model name already exists; import a new named version.')
        raw=sys.stdin.buffer.read(runtime.LIMITS['input_bytes']+1)
        try:
            if not 0<len(raw)<=runtime.LIMITS['input_bytes']:raise ValueError()
            bundle=json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
            if not isinstance(bundle,dict) or set(bundle)!={'config.json','tokenizer_config.json','model.safetensors.b64','weights_manifest.json'}:raise ValueError()
            if any(not isinstance(bundle[n],dict) for n in ('config.json','tokenizer_config.json','weights_manifest.json')):raise ValueError()
            if bundle['config.json'].get('runtime')!=runtime.RUNTIME_ID or bundle['tokenizer_config.json']!={'kind':'byte-v1','vocab_size':260,'pad_id':0,'bos_id':1,'eos_id':2,'unk_id':3}:raise ValueError()
            runtime._load_general_export_model(bundle)
        except (ValueError,KeyError,TypeError,RecursionError):raise CommandError('Import requires a complete bounded finite CPU transformer reference bundle with valid tensor checksums.') from None
        ref=_store(io.BytesIO(raw),tenant=tenant,project=project,name='reference.json',media_type='application/json')
        tok=TokenizerVersion.all_objects.create(tenant_id=tenant,project_id=project,name=name+'-tokenizer',vocabulary_size=260,
            artifact_manifest_id=ref['artifact_id'],configuration_digest=runtime.digest(bundle['tokenizer_config.json']),
            compatibility={'byte_v1':{'vocab_size':260},'immutable_import':True})
        model=Model.all_objects.create(tenant_id=tenant,project_id=project,name=name,intended_tasks=['text_generation'])
        version=ModelVersion.all_objects.create(tenant_id=tenant,project_id=project,model=model,tokenizer=tok,architecture_ref=runtime.RUNTIME_ID,
            artifact_manifest_id=ref['artifact_id'],license_evidence=options['license'],metadata={'imported':True,'weights_sha256':bundle['weights_manifest.json']['weights_sha256'],
                'initialization':'Imported numerical reference tensors; pretrained language quality is not asserted.'})
        result={'model':str(version.model_version_id),'model_pk':version.pk,'bundle_sha256':ref['sha256'],'runtime':runtime.RUNTIME_ID,'production_qualified':False}
        worker_id=options.get('example_worker_id')
        if worker_id is not None:
            worker=Worker.all_objects.select_related('pool').filter(tenant_id=tenant,pk=worker_id).first()
            if worker is None or not runtime.capable_worker(worker) or worker.pool.status!='active' or worker.pool.result_egress!='envelope':
                raise CommandError('Select an available matching CPU reference worker in this tenant.')
            rows=[]
            for i,text in enumerate(('a tiny example.','another sample.','local data stays local.','learn this short text.')):
                rows.append({'schema_version':'1.0','sample_id':str(uuid.uuid4()),'source_group_id':str(i),'blocks':[{'block_id':'text','type':'text','text':text}],
                    'provenance':{'source_snapshot_ref':'explicit-selfhost-reference','source_record_key':str(i),'content_sha256':hashlib.sha256(text.encode()).hexdigest()}})
            payload=b''.join(json.dumps(row).encode()+b'\n' for row in rows)
            source_ref=_store(io.BytesIO(payload),tenant=tenant,project=project,name='example.jsonl',media_type='application/x-ndjson')
            from modelanvil.artifacts.models import Artifact
            source=Artifact.all_objects.get(artifact_id=source_ref['artifact_id'],tenant_id=tenant)
            dataset=Dataset.all_objects.create(tenant_id=tenant,project_id=project,name=name+'-explicit-example')
            revision=publish_prepared_dataset(dataset,source,validation_percent=0,test_percent=0)
            manifest=runtime.runner_manifest()
            runner=RunnerManifest.all_objects.create(tenant_id=tenant,name=name+'-runner',version='1',manifest=manifest,digest=runtime.digest(manifest),compatibility={'contract_digest':runtime.CONTRACT_DIGEST})
            quota=BudgetPolicy.all_objects.create(tenant_id=tenant,name=name+'-example-steps',period='lifetime',unit='training_steps',limit_amount=16)
            result['launch']={'project':str(project),'execution_mode':'worker','recipe_type':'full_sft','base_model_version':version.pk,'tokenizer_version':tok.pk,
                'dataset_revision':revision.pk,'runner_manifest':runner.pk,'pool':worker.pool_id,'budget_policy_id':str(quota.policy_id),'total_steps':4}
        self.stdout.write(json.dumps(result))
