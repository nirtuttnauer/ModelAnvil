"""Opt-in real GPU qualification in a new isolated database/artifact directory.

Creates synthetic text fixtures, trains three steps, independently loads the
candidate, and checks recovery, cancellation, corruption and step accounting.
No existing ModelAnvil database is used. This is not a quality benchmark.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model-dir', type=Path, required=True, help='Verified pinned local SmolLM2 snapshot')
parser.add_argument('--device', required=True, help='Explicit cpu, mps:0, cuda:N, rocm:N or xpu:N')
parser.add_argument('--output', type=Path, required=True, help='New directory for isolated state and evidence')
parser.add_argument('--recipe', choices=['full_sft', 'lora_adapter', 'qlora_adapter', 'continued_pretraining'], default='full_sft')
parser.add_argument('--samples', type=Path, help='Optional real versioned canonical text corpus; otherwise use synthetic correctness fixtures')
args = parser.parse_args()
args.model_dir = args.model_dir.resolve()
args.output = args.output.resolve()
args.output.mkdir(parents=True, exist_ok=False)
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings',
    DATABASE_NAME=str(args.output / 'qualification.sqlite'),
    MODELANVIL_ARTIFACT_ROOT=str(args.output / 'artifacts'),
    HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='4')
import django
django.setup()
import io,json,hashlib,uuid
import torch
from django.core.management import call_command
from modelanvil.identity.models import Tenant,Team,Project,ApiKey,Role,generate_api_key
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.runners.models import TrainingRun
from modelanvil.jobs.models import Worker,claim_job,JobAttempt,Job
from modelanvil.jobs.executor import execute_claim
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.runners.training import hf_runtime, mlx_runtime, cpu_hf_runtime
runtime = cpu_hf_runtime if args.device == 'cpu' else mlx_runtime if args.recipe == 'qlora_adapter' else hf_runtime
checkpoint_bundle, staged_files = runtime.checkpoint_bundle, runtime.staged_files
from modelanvil.runners.training.hardware import hardware_report
from modelanvil.budgets.models import UsageEvent,BudgetReservation
from rest_framework.test import APIClient
call_command('migrate',verbosity=0)
name='gpu-'+uuid.uuid4().hex[:8]
tenant=Tenant.objects.create(slug=name,name='Isolated GPU qualification')
set_active_tenant(tenant.pk)
team=Team.objects.create(tenant_id=tenant.pk,slug=name,name=name)
project=Project.objects.create(tenant_id=tenant.pk,team=team,slug=name,name=name)
text=['ModelAnvil verifies training inputs and saves durable checkpoints.',
      'A telescope collects light from distant stars to study the universe.',
      'Ocean waves move energy across water while tides follow gravitational forces.',
      'A recipe combines measured ingredients before the bread is baked.',
      'Trees absorb sunlight and grow leaves through photosynthesis.',
      'A compiler translates source code into instructions for a computer.',
      'Rainwater flows into streams and eventually reaches the sea.',
      'A bicycle uses two wheels and pedals to move along a road.',
      'An orchestra plays music with strings, wind instruments and percussion.',
      'A library organizes books so that readers can find useful information.']
rows=[{'schema_version':'1.0','sample_id':str(uuid.uuid4()),'source_group_id':str(i),
       'blocks':[{'block_id':'text','type':'text','text':s}],
       'provenance':{'source_snapshot_ref':'explicit-local-qualification-fixture','source_record_key':str(i),'content_sha256':hashlib.sha256(s.encode()).hexdigest()}} for i,s in enumerate(text)]
if args.samples:
 rows=[json.loads(line) for line in args.samples.read_text().splitlines() if line.strip()]
samples=args.output / 'samples.jsonl';samples.write_text(''.join(json.dumps(r)+'\n' for r in rows))
output=io.StringIO()
call_command('setup_gpu_training',tenant_id=tenant.pk,project_id=project.pk,name=name,model_dir=args.model_dir,samples=samples,device=args.device,recipe=args.recipe,steps=3,stdout=output)
installed=json.loads(output.getvalue())
from modelanvil.device_admission import device_available, device_lease
installed['launch']['recipe_type'] = args.recipe
weight_name = 'adapters.safetensors' if args.recipe == 'qlora_adapter' else ('adapter_model.safetensors' if args.recipe == 'lora_adapter' else 'model.safetensors')
secret,hashed=generate_api_key()
ApiKey.objects.create(tenant=tenant,name='qualification',role=Role.ENGINEER,secret_hash=hashed)
client=APIClient();client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
with device_lease(args.device):
 blocked = client.post('/api/v1/training-runs/preflight/', installed['launch'], format='json')
 assert blocked.status_code == 200 and 'device-admission' in blocked.data['blocking_checks'], blocked.data
 refused = client.post('/api/v1/training-runs/', installed['launch'], format='json', HTTP_IDEMPOTENCY_KEY='busy-device')
 assert refused.status_code == 400, refused.data
 assert TrainingRun.all_objects.count() == 0 and BudgetReservation.all_objects.count() == 0
print('busy device rejected before job and budget allocation', flush=True)
preview=client.post('/api/v1/training-runs/preflight/',installed['launch'],format='json')
assert preview.status_code==200 and preview.data['status']=='approved',preview.data
before_jobs = Job.all_objects.filter(tenant_id=tenant.pk).count()
before_reservations = BudgetReservation.all_objects.filter(tenant_id=tenant.pk).count()
for options in ({'precision':'bf16'}, {'precision':'fp16'}, {'adapter':'invalid'}, {'quantization':'int8' if args.recipe == 'qlora_adapter' else 'int4'}):
    for endpoint in ('/api/v1/training-runs/preflight/', '/api/v1/training-runs/'):
        rejected = client.post(endpoint, {**installed['launch'], **options}, format='json', HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
        assert rejected.status_code == 400, rejected.data
assert Job.all_objects.filter(tenant_id=tenant.pk).count() == before_jobs
assert BudgetReservation.all_objects.filter(tenant_id=tenant.pk).count() == before_reservations
print('unsupported precision/adapter/quantization rejected without jobs or budget', flush=True)
print('preflight approved' ,preview.data['requirements'],flush=True)
launch=client.post('/api/v1/training-runs/',{**installed['launch'],'preflight_token':preview.data['preflight_token']},format='json',HTTP_IDEMPOTENCY_KEY=name)
assert launch.status_code==201,launch.data
run=TrainingRun.all_objects.get(run_id=launch.data['run_id']);worker=Worker.all_objects.get(pk=installed['worker_id'])
print('launched',run.run_id,flush=True)
descriptor=claim_job(worker);assert descriptor
outcome=execute_claim(worker,descriptor,training_worker_executor)
run.refresh_from_db();print('outcome',outcome,'error',JobAttempt.all_objects.get(job=run.job).error,flush=True)
assert device_available(args.device), 'Training retained its device lease after exit'
assert outcome['committed'] and outcome['status']=='succeeded' and run.status=='completed'
bundle=checkpoint_bundle(run,run.checkpoints.get(step=run.total_steps))
download=client.get(f'/api/v1/training-runs/{run.run_id}/download/')
assert download.status_code == 200, download.content if not download.streaming else 'Expected model ZIP'
archive_path=args.output / 'modelanvil-candidate.zip'
with archive_path.open('wb') as target:
 for block in download.streaming_content: target.write(block)
download.close()
import zipfile
with zipfile.ZipFile(archive_path) as archive:
 assert set(archive.namelist()) == set(bundle['files']) | {'modelanvil-provenance.json', 'LICENSE.txt'}
 assert archive.read('LICENSE.txt') == (Path(runtime.__file__).parent / 'assets/Apache-2.0.txt').read_bytes()
 for filename,ref in bundle['files'].items():
  with archive.open(filename) as source:
   sha=hashlib.sha256()
   while block:=source.read(1024*1024): sha.update(block)
   assert sha.hexdigest()==ref['sha256']
with staged_files(bundle['files'],run.tenant_id,run.project_id) as directory:
 import shutil
 destination=args.output / 'candidate';destination.mkdir()
 for file in directory.iterdir():shutil.copyfile(file,destination/file.name)
report={'run_id':str(run.run_id),'tenant_id':str(tenant.pk),'project_id':str(project.pk),'installed':installed,
        'preflight':dict(preview.data),'metrics':run.metrics_log,'pins':run.hardware_config['pins'],
        'hardware': hardware_report(),
        'checkpoints':[{'step':c.step,'state_digest':c.state_digest,'weights_sha256':c.weights_manifest['files'][weight_name]['sha256']} for c in run.checkpoints.all()],
        'candidate':str(run.output_model_version.model_version_id),'bundle':bundle,
        'usage':[{'quantity':str(u.quantity),'unit':u.unit,'detail':u.detail} for u in UsageEvent.all_objects.filter(tenant_id=tenant.pk)],
        'budget':[{'reserved':str(b.estimated_amount),'settled':str(b.settled_amount)} for b in BudgetReservation.all_objects.filter(tenant_id=tenant.pk)],
        'scope':f'One local {args.device} SmolLM2 {runtime.CONTRACT['precision']} {args.recipe} pilot; {"operator-supplied versioned text" if args.samples else "synthetic correctness corpus"}; no cross-vendor or production claim.'}
(args.output / 'task13-gpu-pilot.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
print('saved real GPU report',flush=True)

with device_lease('cpu'):
 inference = subprocess.run([sys.executable, str(root / ('scripts/mlx_candidate_infer.py' if args.recipe == 'qlora_adapter' else 'scripts/hf_candidate_infer.py')),
     str(destination), '--device', 'cpu'], capture_output=True, text=True, check=True, timeout=120)
independent = json.loads(inference.stdout)
assert independent['weights_sha256'] == report['checkpoints'][-1]['weights_sha256']
assert independent['completion'] and not independent['consumer_imported_modelanvil_or_django']
(args.output / 'task13-gpu-independent-inference.json').write_text(json.dumps(independent, indent=2)+'\n')
print('independent inference passed', flush=True)
with device_lease(args.device):
 gpu_inference = subprocess.run([sys.executable, str(root / ('scripts/mlx_candidate_infer.py' if args.recipe == 'qlora_adapter' else 'scripts/hf_candidate_infer.py')),
     str(destination), '--device', args.device], capture_output=True, text=True, check=True, timeout=120)
gpu_result = json.loads(gpu_inference.stdout)
assert gpu_result['weights_sha256'] == independent['weights_sha256']
assert gpu_result['generated_token_ids'] == independent['generated_token_ids']
assert gpu_result['execution']['backend'] == args.device.split(':')[0]
assert gpu_result['execution']['device_residency_checked'] and not gpu_result['consumer_imported_modelanvil_or_django']
(args.output / 'gpu-independent-inference.json').write_text(json.dumps(gpu_result, indent=2)+'\n')
print('GPU inference matches CPU candidate reload', flush=True)

if args.samples:
 from modelanvil.runners.training.runtime import read_artifact
 prepared=json.loads(read_artifact(run.dataset_revision.manifest_artifact,run.tenant_id,run.project_id))
 consumed={m['sample_id'] for m in run.metrics_log}
 split_by_id={identifier:split for split,identifiers in prepared['split_manifest'].items() for identifier in identifiers}
 quality_samples=[]
 for row in prepared['rows']:
  split=split_by_id[row['sample_id']]
  if split=='train' and row['sample_id'] not in consumed:continue
  quality_samples.append({'sample_id':row['sample_id'],'source_group_id':row['source_group_id'],
   'split':'train_consumed' if split=='train' else split,'text':'\n'.join(b['text'] for b in row['blocks'])})
 quality_path=args.output/'quality-samples.json'
 quality_path.write_text(json.dumps({'dataset_digest':run.dataset_revision.manifest_digest,'samples':quality_samples}))
 with device_lease('mlx:0' if args.recipe == 'qlora_adapter' else 'cpu'):
  measured=subprocess.run([sys.executable,str(root/'scripts/hf_candidate_score.py'), '--runtime', ('mlx' if args.recipe == 'qlora_adapter' else 'torch'),'--base-dir',str(args.model_dir),
   '--candidate-dir',str(destination),'--samples',str(quality_path)],capture_output=True,text=True,check=True,timeout=240)
 quality=json.loads(measured.stdout)
 assert not quality['consumer_imported_modelanvil_or_django']
 (args.output/'quality-verification.json').write_text(json.dumps(quality,indent=2)+'\n')
 print('Independent protected-corpus quality checks:',quality['checks'],flush=True)
 if args.recipe == 'qlora_adapter':
  print('Overall quantized-vs-unquantized quality target:', quality['overall_quality_passed'], quality['quantization_checks_within_five_percent'], flush=True)
 assert quality['passed'], 'Independent protected-corpus quality target failed; inspect quality-verification.json'

from datetime import timedelta
from unittest.mock import patch
from django.utils import timezone
from modelanvil.jobs.models import reconcile_expired_leases
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.artifacts.models import Artifact
pilot=report
payload=pilot['installed']['launch'];worker=Worker.all_objects.get(pk=pilot['installed']['worker_id'])
policy=BudgetPolicy.all_objects.get(policy_id=payload['budget_policy_id']);policy.limit_amount=30;policy.save()
results={}
def launch(key):
 r=client.post('/api/v1/training-runs/',payload,format='json',HTTP_IDEMPOTENCY_KEY=key)
 assert r.status_code==201,r.data
 return TrainingRun.all_objects.get(run_id=r.data['run_id'])
def execute(run,hook=None):
 descriptor=claim_job(worker);assert descriptor
 if hook:
  if args.recipe == 'qlora_adapter':
   import mlx.optimizers as optim
   optimizer_class, method = optim.AdamW, 'update'
  else:
   optimizer_class, method = torch.optim.AdamW, 'step'
  original=getattr(optimizer_class, method);calls=0
  def wrapped(optimizer,*a,**kw):
   nonlocal calls
   out=original(optimizer,*a,**kw);calls+=1
   if calls==2:hook(descriptor)
   return out
  with patch.object(optimizer_class,method,wrapped):out=execute_claim(worker,descriptor,training_worker_executor)
 else:out=execute_claim(worker,descriptor,training_worker_executor)
 run.refresh_from_db();return descriptor,out
run=launch('gpu-recovery-'+uuid.uuid4().hex)
def expire(descriptor):
 JobAttempt.all_objects.filter(attempt_id=descriptor['attempt_id']).update(lease_expires_at=timezone.now()-timedelta(seconds=1))
descriptor,out=execute(run,expire)
assert not out['committed'] and run.current_step==1 and not run.output_model_version_id,(out,run.current_step)
print('expired lease stopped at committed step 1',flush=True)
reconcile_expired_leases();_,out=execute(run)
assert out['status']=='succeeded' and run.current_step==3,out
recovered=run.checkpoints.get(step=3).weights_manifest['files'][weight_name]['sha256']
assert recovered==pilot['checkpoints'][-1]['weights_sha256'],'Recovery changed final model weights'
assert UsageEvent.all_objects.filter(reservation__job_id=run.job.job_id).count()==1
assert not execute_claim(worker,descriptor,training_worker_executor)['committed']
results['recovery']={'run_id':str(run.run_id),'attempts':run.job.attempts.count(),'final_weights_sha256':recovered,'exactly_matches_uninterrupted':True,'steps':run.current_step}
print('recovered exact baseline weights',flush=True)
run=launch('gpu-cancel-'+uuid.uuid4().hex)
def cancel(descriptor):
 response=client.post(f'/api/v1/training-runs/{run.run_id}/cancel/');assert response.status_code==200,response.data
_,out=execute(run,cancel)
assert out['committed'] and run.status=='cancelled' and run.current_step==1 and not run.output_model_version_id,(out,run.status,run.current_step)
budget=BudgetReservation.all_objects.get(job_id=run.job.job_id);assert budget.settled_amount==1
results['cancel']={'run_id':str(run.run_id),'steps':run.current_step,'settled':str(budget.settled_amount),'candidate':None}
print('cancellation settled only one committed step',flush=True)
run=launch('gpu-corrupt-'+uuid.uuid4().hex)
base_ref=pilot['bundle']['files']['tokenizer.json'];artifact=Artifact.all_objects.get(artifact_id=base_ref['artifact_id'])
original=artifact.sha256
try:
 Artifact.all_objects.filter(pk=artifact.pk).update(sha256='0'*64)
 _,out=execute(run)
 assert out['status']=='failed' and not run.output_model_version_id and run.current_step==0,out
 budget=BudgetReservation.all_objects.get(job_id=run.job.job_id);assert budget.settled_amount==0
 results['corruption']={'run_id':str(run.run_id),'steps':0,'settled':'0','candidate':None}
finally:Artifact.all_objects.filter(pk=artifact.pk).update(sha256=original)
results['scope']=f'Real {args.device} SmolLM2 GPU worker, isolated database, live fencing/cancellation/corruption/accounting. Does not qualify other vendors or production scheduling.'
(args.output / 'task13-gpu-recovery.json').write_text(json.dumps(results,indent=2)+'\n')
print('saved failure and recovery evidence',flush=True)
