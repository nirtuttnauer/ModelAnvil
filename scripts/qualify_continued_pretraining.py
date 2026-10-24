"""Opt-in real CPU continued-pretraining qualification in a new isolated database/artifact directory.

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
parser.add_argument('--device', choices=['cpu'], required=True, help='Explicit bounded CPU profile')
parser.add_argument('--output', type=Path, required=True, help='New directory for isolated state and evidence')
parser.add_argument('--recipe', choices=['continued_pretraining'], default='continued_pretraining')
args = parser.parse_args()
args.model_dir = args.model_dir.resolve()
args.output = args.output.resolve()
os.umask(0o077)
args.output.mkdir(parents=True, exist_ok=False)
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings',
    DATABASE_NAME=str(args.output / 'qualification.sqlite'),
    MODELANVIL_ARTIFACT_ROOT=str(args.output / 'artifacts'),
    HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
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
from modelanvil.runners.training import hf_runtime, cpu_hf_runtime
runtime = cpu_hf_runtime
checkpoint_bundle, staged_files = runtime.checkpoint_bundle, runtime.staged_files
from modelanvil.runners.training.hardware import hardware_report
from modelanvil.budgets.models import UsageEvent,BudgetReservation
from rest_framework.test import APIClient
call_command('migrate',verbosity=0)
name='gpu-'+uuid.uuid4().hex[:8]
tenant=Tenant.objects.create(slug=name,name='Isolated GPU qualification')
set_active_tenant(tenant.pk)
# Exit cleanup also runs when a qualification assertion fails; unfinished jobs remain visible for diagnosis.
import atexit
def close_fixture():
 from modelanvil.jobs.models import WorkerPool,DeviceClaim
 from modelanvil.budgets.models import BudgetPolicy
 revoked=ApiKey.objects.filter(tenant=tenant,is_active=True).update(is_active=False)
 Worker.all_objects.filter(tenant_id=tenant.pk).update(status='offline',slots=0,drain_requested=True)
 WorkerPool.all_objects.filter(tenant_id=tenant.pk).update(status='draining')
 BudgetPolicy.all_objects.filter(tenant_id=tenant.pk).update(enabled=False)
 Tenant.objects.filter(pk=tenant.pk).update(status='suspended')
 closure={'revoked_active_keys':revoked,'active_keys':ApiKey.objects.filter(tenant=tenant,is_active=True).count(),
  'pending_jobs':Job.all_objects.filter(tenant_id=tenant.pk,status__in=['queued','running','interrupted']).count(),
  'running_attempts':JobAttempt.all_objects.filter(tenant_id=tenant.pk,status='running').count(),
  'reserved_budgets':BudgetReservation.all_objects.filter(tenant_id=tenant.pk,state='reserved').count(),
  'device_claims':DeviceClaim.objects.filter(attempt__job__tenant_id=tenant.pk).count(),'tenant_suspended':True,'workers_offline':True}
 (args.output/'exit-cleanup.json').write_text(json.dumps(closure,indent=2)+'\n')
atexit.register(close_fixture)
team=Team.objects.create(tenant_id=tenant.pk,slug=name,name=name)
project=Project.objects.create(tenant_id=tenant.pk,team=team,slug=name,name=name)
# The authored text fixtures below are dedicated under CC0-1.0.
domain=[
 'A telescope gathers faint starlight using a precisely shaped mirror.',
 'Astronomers measure stellar temperature from the spectrum of emitted light.',
 'An orbital period describes the time required to circle a central body.',
 'A nebula contains interstellar gas and dust illuminated by nearby stars.',
 'Parallax compares apparent stellar positions from different observing locations.',
 'Spectroscopy separates incoming radiation into individual wavelength bands.',
 'The aperture of an observatory instrument controls its light gathering area.',
 'A red giant expands after hydrogen burning changes inside its core.',
 'Gravitational attraction keeps natural satellites moving around their planets.',
 'An eclipse occurs when one celestial object blocks another from view.',
 'A galaxy contains stars, gas, dust and an extended gravitational halo.',
 'Astronomical distance estimates depend on calibrated observational measurements.',
 'A comet releases gas when sunlight warms its frozen surface.',
 'Planetary atmospheres absorb specific wavelengths during a stellar transit.',
 'A supernova ejects material after a catastrophic stellar explosion.',
 'The inclination of an orbit specifies its tilt relative to a reference plane.',
 'Radio observatories detect long wavelength emission from astronomical sources.',
 'Dark adaptation improves the sensitivity of human night vision.',
 'Adaptive optics corrects distortions caused by turbulent atmospheric layers.',
 'A lunar crater records the impact of a smaller rocky object.'
]
protected=[
 'A baker kneads dough before allowing the bread to rise.',
 'A bicycle chain transfers motion from the pedals to the rear wheel.',
 'Public libraries organize books and provide spaces for quiet reading.',
 'Rainwater moves through soil before entering streams and rivers.',
 'An orchestra combines string, wind and percussion instruments.',
 'Tree roots absorb dissolved nutrients and water from the ground.',
 'A compiler translates source code into executable machine instructions.',
 'A ceramic cup holds hot tea while its handle limits direct contact.',
 'The gardener removes weeds to give young vegetables room to grow.',
 'A thermometer measures temperature using a calibrated physical response.',
 'A map represents geographic features with symbols and a scale.',
 'Ocean tides reflect the gravitational influence of the moon and sun.',
 'A carpenter checks measurements before cutting a wooden board.',
 'Bees carry pollen between flowers while collecting nectar.',
 'A musician practices scales to improve accuracy and coordination.',
 'The train conductor checks passenger tickets before the next station.',
 'An insulated coat reduces heat transfer during cold weather.',
 'A dictionary describes the meanings and usage of individual words.',
 'A bridge distributes traffic loads through its structural supports.',
 'Fermentation converts sugars into other compounds through microbial activity.'
]
def envelopes(texts,label):
 return [{'schema_version':'1.0','sample_id':str(uuid.uuid5(uuid.NAMESPACE_URL,'modelanvil-cpt-v1:'+label+str(i))),
  'source_group_id':label+':'+str(i),'blocks':[{'block_id':'text','type':'text','text':text}],
  'provenance':{'source_snapshot_ref':'authored-CC0-cpt-pilot-v1:'+label,'source_record_key':str(i),
  'content_sha256':hashlib.sha256(text.encode()).hexdigest()}} for i,text in enumerate(texts)]
rows=envelopes(domain,'astronomy')
assert args.device=='cpu', 'This bounded qualification is CPU-only.'
import shutil
assert shutil.disk_usage(args.output).free > 24*1024**3, 'Qualification needs24GiB free disk.'
samples=args.output / 'samples.jsonl';samples.write_text(''.join(json.dumps(r)+'\n' for r in rows))
output=io.StringIO()
call_command('setup_gpu_training',tenant_id=tenant.pk,project_id=project.pk,name=name,model_dir=args.model_dir,samples=samples,device=args.device,recipe='full_sft',steps=3,stdout=output)
installed=json.loads(output.getvalue())
from modelanvil.device_admission import device_available, device_lease
from modelanvil.artifacts.models import DatasetRevision,Dataset,Artifact
from modelanvil.artifacts.storage import artifact_storage_backend,upload_staged_artifact
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.runners.training.runtime import read_artifact
raw=''.join(json.dumps(r)+'\n' for r in envelopes(protected,'general')).encode()
source=Artifact.all_objects.create(tenant_id=tenant.pk,project=project,storage_location_id='local',object_key='qualification/protected.jsonl',
 sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),media_type='application/x-ndjson')
upload_staged_artifact(source,io.BytesIO(raw),backend=artifact_storage_backend())
dataset=Dataset.all_objects.create(tenant_id=tenant.pk,project=project,name=name+'-protected')
protected_revision=publish_prepared_dataset(dataset,source,validation_percent=20,test_percent=20)
domain_revision=DatasetRevision.all_objects.get(pk=installed['launch']['dataset_revision'])
secret,hashed=generate_api_key()
key=ApiKey.objects.create(tenant=tenant,project=project,name='qualification',role=Role.ENGINEER,secret_hash=hashed)
client=APIClient();client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}',HTTP_X_PROJECT_ID=str(project.pk))
compiled=client.post('/api/v1/pretraining-corpora/',{'name':name+'-corpus','components':[
 {'revision_id':str(domain_revision.revision_id),'weight':'3'},{'revision_id':str(protected_revision.revision_id),'weight':'1'}],
 'train_samples':12,'seed':'cpu-continued-both-shards-v1'},format='json')
assert compiled.status_code==201,compiled.data
corpus_revision=DatasetRevision.all_objects.get(pk=compiled.data['id'])
installed['launch'].update(recipe_type='continued_pretraining',dataset_revision=corpus_revision.pk)
weight_name='model.safetensors'
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
assert {m['source_revision_id'] for m in run.metrics_log}=={str(domain_revision.revision_id),str(protected_revision.revision_id)}, 'The bounded pilot must consume both actual shards.'
bundle=checkpoint_bundle(run,hf_runtime.best_checkpoint(run))
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
        'scope':f'One local {args.device} SmolLM2 {runtime.CONTRACT['precision']} {args.recipe} pilot; authored CC0 original protected text shards; no cross-vendor or production claim.'}
(args.output / 'continued-pilot.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
print('saved real CPU continued-pretraining report',flush=True)

with device_lease('cpu'):
 inference = subprocess.run([sys.executable, str(root / ('scripts/mlx_candidate_infer.py' if args.recipe == 'qlora_adapter' else 'scripts/hf_candidate_infer.py')),
     str(destination), '--device', 'cpu'], capture_output=True, text=True, check=True, timeout=120)
independent = json.loads(inference.stdout)
assert independent['weights_sha256'] == bundle['files'][weight_name]['sha256']
assert independent['completion'] and not independent['consumer_imported_modelanvil_or_django']
(args.output / 'continued-independent-inference.json').write_text(json.dumps(independent, indent=2)+'\n')
print('independent inference passed', flush=True)
prepared=json.loads(read_artifact(corpus_revision.manifest_artifact,tenant.pk,project.pk))
quality_rows=[];forbidden=[];groups=[];expected=[]
for revision,label in [(domain_revision,'domain_test'),(protected_revision,'protected_test')]:
 original=json.loads(read_artifact(revision.manifest_artifact,tenant.pk,project.pk))
 for row in original['rows']:
  if row['sample_id'] in original['split_manifest']['test']:
   quality_rows.append({'sample_id':row['sample_id'],'source_group_id':row['source_group_id'],'split':label,'text':'\n'.join(b['text'] for b in row['blocks'])})
   expected.append(row['sample_id'])
  else:forbidden.append(row['sample_id']);groups.append(row['source_group_id'])
quality_path=args.output/'quality-samples.json'
quality_path.write_text(json.dumps({'dataset_digest':corpus_revision.manifest_digest,'corpus_recipe_digest':corpus_revision.recipe_digest,
 'expected_test_ids':expected,'training_and_validation_ids':forbidden,'training_and_validation_groups':groups,'samples':quality_rows}))
with device_lease('cpu'):
 measured=subprocess.run([sys.executable,str(root/'scripts/score_continued_pretraining.py'),'--base-dir',str(args.model_dir),
  '--candidate-dir',str(destination),'--samples',str(quality_path)],capture_output=True,text=True,check=True,timeout=240)
quality=json.loads(measured.stdout)
assert not quality['consumer_imported_modelanvil_or_django']
(args.output/'quality-verification.json').write_text(json.dumps(quality,indent=2)+'\n')
print('Independent original-test loss proxies:',quality['checks'],flush=True)
# Proxy failure is evidence and keeps the candidate unqualified; never cherry-pick another test split.
report['corpus']=dict(compiled.data);report['selected_candidate_step']=bundle['provenance.json']['step']
report['authored_corpus_license']='CC0-1.0';report['source_roles']={'domain':str(domain_revision.revision_id),'protected':str(protected_revision.revision_id)}
(args.output/'continued-pilot.json').write_text(json.dumps(report,indent=2,default=str)+'\n')

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
# A valid checksum cannot authorize an inconsistent logical corpus cursor.
import copy
from types import SimpleNamespace
pilot_run=TrainingRun.all_objects.get(run_id=pilot['run_id']);saved=pilot_run.checkpoints.get(step=1)
state=copy.deepcopy(saved.weights_manifest);state['data_cursor']['next_sample_offset']+=1
changed=SimpleNamespace(is_valid=True,step=1,weights_manifest=state,state_digest=hf_runtime.digest(state),metrics=saved.metrics)
try:checkpoint_bundle(pilot_run,changed)
except ValueError as exc:assert 'cursor' in str(exc)
else:raise AssertionError('Rehashed invalid data cursor was accepted')
results['cursor_tamper']={'rehashed_invalid_cursor_refused':True}
# Withdraw an original shard after the second optimizer update, before its checkpoint.
from modelanvil.artifacts.models import DeletionTombstone
run=launch('continued-source-withdraw-'+uuid.uuid4().hex)
def withdraw(descriptor):
 DeletionTombstone.all_objects.create(tenant_id=tenant.pk,resource_type='artifact',resource_id=str(domain_revision.manifest_artifact.artifact_id),reason='Isolated qualification source withdrawal')
_,out=execute(run,withdraw)
assert out['status']=='failed' and run.current_step==1 and not run.output_model_version_id,(out,run.current_step)
budget=BudgetReservation.all_objects.get(job_id=run.job.job_id);assert budget.settled_amount==1
refused=client.get(f'/api/v1/training-runs/{pilot_run.run_id}/download/')
assert refused.status_code==400,refused.status_code
assert client.get('/api/v1/pretraining-corpora/').data['results']==[]
results['source_withdrawal']={'stopped_at_committed_step':1,'settled':'1','candidate':None,'existing_candidate_download_refused':True,'corpus_hidden':True}
print('Source withdrawal stopped publication and revoked existing corpus candidate download',flush=True)
results['scope']=f'Real {args.device} SmolLM2 pretrained worker, isolated database, live fencing/cancellation/corruption/accounting. Does not qualify other vendors or production scheduling.'
(args.output / 'continued-recovery.json').write_text(json.dumps(results,indent=2)+'\n')
print('saved failure and recovery evidence',flush=True)

from modelanvil.jobs.models import DeviceClaim,WorkerPool
key.is_active=False;key.save(update_fields=['is_active'])
Worker.all_objects.filter(pk=worker.pk).update(status='offline',slots=0,drain_requested=True)
WorkerPool.all_objects.filter(pk=worker.pool_id).update(status='draining')
BudgetPolicy.all_objects.filter(tenant_id=tenant.pk).update(enabled=False)
tenant.status='suspended';tenant.save(update_fields=['status'])
cleanup={'revoked_keys':1,'nonterminal_jobs':Job.all_objects.filter(tenant_id=tenant.pk).exclude(status__in=['succeeded','failed','cancelled']).count(),
 'open_reservations':BudgetReservation.all_objects.filter(tenant_id=tenant.pk,state='reserved').count(),
 'device_claims':DeviceClaim.objects.filter(attempt__job__tenant_id=tenant.pk).count()}
assert cleanup['nonterminal_jobs']==cleanup['open_reservations']==cleanup['device_claims']==0,cleanup
(args.output/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n')
print('Private qualification fixtures revoked and suspended',flush=True)
