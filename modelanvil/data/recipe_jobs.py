"""Versioned recipes with frozen bindings, resumable rows and fenced publication."""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import time

from django.db import transaction
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.artifacts.models import Artifact, Dataset, LineageEdge
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.data.models import RecipeRun
from modelanvil.data import recipes
from modelanvil.data.preparation import prepare_envelopes
from modelanvil.data.publication import _documents, publish_prepared_dataset
from modelanvil.data.source_import import extract_source, MEDIA_TYPES
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Job, JobAttempt, OutboxEvent, Worker, dispatch_topic
from modelanvil.runners import inference
from modelanvil.runners.model_catalog import _store
from modelanvil.runners.training.hf_runtime import file_ref
from modelanvil.runners.training.runtime import digest

TYPE='recipe_execution'
UNIT='recipe_attempts'
MAX_ATTEMPTS=3
ROOT=Path(__file__).resolve().parents[2]


def runtime_digest():
    files=[__file__,recipes.__file__,inference.__file__,ROOT/'modelanvil/device_admission.py',
        ROOT/'modelanvil/data/source_import.py',ROOT/'modelanvil/data/preparation.py',
        ROOT/'modelanvil/data/publication.py',ROOT/'modelanvil/data/detection.py',
        ROOT/'modelanvil/runners/training/hf_runtime.py']
    return digest([hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files])


def read_json(ref, tenant, project, limit=16*1024**2):
    if ref['byte_size']>limit:raise ValueError('Recipe artifact exceeds its byte limit.')
    stream=io.BytesIO();inference.copy_verified(ref,tenant,project,stream)
    return json.loads(stream.getvalue())


def source_rows(ref, step, tenant, project):
    artifact=inference.verified_artifact(ref,tenant,project)
    if artifact.media_type != {'jsonl':'application/x-ndjson',**MEDIA_TYPES}[step['format']]:
        raise ValueError('Recipe source format differs from the committed media type.')
    if artifact.byte_size>16*1024**2:raise ValueError('Recipe source exceeds 16 MiB.')
    stream=io.BytesIO();inference.copy_verified(ref,tenant,project,stream)
    rows=list(_documents(stream.getvalue())) if step['format']=='jsonl' else extract_source(stream.getvalue(),
        source_format=step['format'],text_field=step.get('text_field','text'),group_field=step.get('group_field'))
    if not 1<=len(rows)<=256:raise ValueError('Bounded recipes accept 1–256 source records per input.')
    return rows


def protected_rows(run):
    from contracts import validate_envelope
    rows=[]
    for ref in run.frozen['protected']:
        artifact=inference.verified_artifact(ref,run.tenant_id,run.project_id)
        if artifact.media_type=='application/x-ndjson':
            rows.extend(source_rows(ref,{'format':'jsonl'},run.tenant_id,run.project_id))
        else:
            prepared=read_json(ref,run.tenant_id,run.project_id)
            held=set(prepared['split_manifest']['validation']) | set(prepared['split_manifest']['test'])
            rows.extend(r for r in prepared['rows'] if r['sample_id'] in held)
    for row in rows:validate_envelope(row)
    return rows


@transaction.atomic
def save_version(definition, tenant, project):
    recipes.validate_recipe(definition)
    payload=json.dumps(definition,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
    sha=hashlib.sha256(payload).hexdigest()
    prior=Artifact.all_objects.filter(tenant_id=tenant,project_id=project,sha256=sha,state='committed',metadata__kind='recipe_version').first()
    if prior:return file_ref(prior)
    return _store(io.BytesIO(payload),tenant=tenant,project=project,name='recipe.json',media_type='application/json',
        metadata={'kind':'recipe_version','schema':recipes.SCHEMA,'name':definition['name']})


@transaction.atomic
def queue(*, tenant, project, principal, recipe, sources, model, device, pool, policy, key, preview, dataset=None, preview_run=None, protected=()):
    if not check_resource_access(recipe,project.pk,tenant) or recipe.metadata.get('kind')!='recipe_version':
        raise ValueError('Select an accessible immutable recipe version.')
    definition=read_json(file_ref(recipe),tenant,project.pk,64000);recipes.validate_recipe(definition)
    source_steps={s['id']:s for s in definition['steps'] if s['type']=='source'}
    if set(sources)!=set(source_steps):raise ValueError('Bind every source step exactly once.')
    for key_name, artifact in sources.items():
        if not check_resource_access(artifact,project.pk,tenant) or artifact.state!='committed' or artifact.byte_size>16*1024**2:
            raise ValueError('Select accessible bounded committed recipe sources.')
        if artifact.media_type!={'jsonl':'application/x-ndjson',**MEDIA_TYPES}[source_steps[key_name]['format']]:
            raise ValueError('Recipe source format differs from the committed media type.')
    needs_model=any(s['type']=='generate' for s in definition['steps'])
    if needs_model != bool(model) or device not in ({'cpu','mps:0','mlx:0'} if needs_model else {'cpu'}):
        raise ValueError('Generation requires an accessible model and supported explicit device; deterministic recipes use CPU.')
    model_plan=inference.snapshot(model,tenant,project.pk) if model else None
    for artifact in protected:
        if not check_resource_access(artifact,project.pk,tenant) or not (artifact.media_type=='application/x-ndjson'
                or artifact.media_type=='application/json' and artifact.metadata.get('kind')=='prepared_dataset'):
            raise ValueError('Select accessible canonical sources or prepared held-out split manifests.')
    basis={'recipe':file_ref(recipe),'sources':{k:file_ref(a) for k,a in sources.items()},
        'model_snapshot':model_plan,'device':device,'runtime':runtime_digest(),'protected':[file_ref(a) for a in protected]}
    frozen={**basis,'preview':preview,'dataset':str(dataset.dataset_id) if dataset else None,'preview_run':str(preview_run.run_id) if preview_run else None,
        'pool':pool.pk,'budget_policy':str(policy.policy_id)}
    fingerprint=digest(frozen)
    prior=RecipeRun.all_objects.select_for_update().filter(tenant_id=tenant,project=project,principal_id=str(principal),idempotency_key=key).first()
    if prior:
        if prior.input_digest!=fingerprint:raise ValueError('This idempotency key belongs to different recipe bindings.')
        return prior
    if not preview:
        if (dataset is None or not check_resource_access(dataset,project.pk,tenant) or preview_run is None
                or not check_resource_access(preview_run,project.pk,tenant) or preview_run.status!='completed'
                or not preview_run.frozen.get('preview') or not preview_run.result.get('row_count')
                or digest({k:preview_run.frozen[k] for k in basis})!=digest(basis)):
            raise ValueError('Review a successful preview of the same recipe/model/sources before choosing an accessible output dataset.')
    elif dataset or preview_run:
        raise ValueError('Preview runs cannot publish a dataset.')
    requirements={'recipe_runtime':basis['runtime'],'recipe_device':device}
    if needs_model:requirements['recipe_generation']=True
    from modelanvil.jobs.setup import local_capacity_available
    workers=Worker.all_objects.filter(tenant_id=tenant,pool=pool,status__in=['available','busy'])
    if (str(pool.tenant_id)!=str(tenant) or pool.status!='active' or pool.result_egress!='envelope'
            or not any(local_capacity_available(w) and all(w.capabilities.get(k)==v for k,v in requirements.items()) for w in workers)):
        raise ValueError('Select an active envelope pool with a matching recipe worker.')
    if str(policy.tenant_id)!=str(tenant) or policy.unit!=UNIT or policy.currency or not policy.enabled:
        raise ValueError('Select an enabled currency-free recipe_attempts quota.')
    identifier=uuid7();job_id=uuid7()
    BudgetReservation.reserve(tenant_id=tenant,policy=policy,job_id=job_id,estimated_amount=MAX_ATTEMPTS)
    job=Job.all_objects.create(tenant_id=tenant,job_id=job_id,pool=pool,name=f'Recipe: {definition["name"]}',max_attempts=MAX_ATTEMPTS,
        payload={'type':TYPE,'run_id':str(identifier)},requirements={**requirements,'slots':1})
    return RecipeRun.all_objects.create(tenant_id=tenant,project=project,job=job,run_id=identifier,recipe=recipe,model_version=model,
        dataset=dataset,principal_id=str(principal),idempotency_key=key,input_digest=fingerprint,frozen=frozen)


def live_run(context):
    attempt=JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job=Job.all_objects.select_for_update().get(pk=attempt.job_id)
    if (attempt.status!='running' or job.status!='running' or job.desired_action=='cancel'
            or attempt.fencing_token!=context.fencing_token or job.fencing_token!=context.fencing_token
            or job.claimed_by_id!=attempt.worker_id or not attempt.lease_expires_at or attempt.lease_expires_at<=timezone.now()
            or job.pool.result_egress!='envelope'):
        raise ValueError('Recipe execution cancelled, fenced out or forbidden by egress policy.')
    return RecipeRun.all_objects.select_for_update().select_related('project','model_version__tokenizer','recipe','dataset').get(job=job,tenant_id=job.tenant_id)


@transaction.atomic
def checkpoint(context, key, value):
    run=live_run(context)
    payload=json.dumps({'input_digest':run.input_digest,'value':value},allow_nan=False).encode()
    if len(payload)>16*1024**2:raise ValueError('Recipe checkpoint exceeds 16 MiB.')
    if key in run.checkpoints:
        if run.checkpoints[key]['sha256']!=hashlib.sha256(payload).hexdigest():raise ValueError('Recipe checkpoint replacement refused.')
        return run.checkpoints[key]
    ref=_store(io.BytesIO(payload),tenant=run.tenant_id,project=run.project_id,name='recipe-checkpoint.json',
        media_type='application/json',metadata={'kind':'recipe_checkpoint','run_id':str(run.run_id),'step':key})
    run.checkpoints={**run.checkpoints,key:ref};run.status='running';run.save(update_fields=['checkpoints','status','updated_at'])
    return ref


def restored(run,key):
    value=read_json(run.checkpoints[key],run.tenant_id,run.project_id)
    if value['input_digest']!=run.input_digest:raise ValueError('Recipe checkpoint belongs to different bindings.')
    return value['value']


def local_generate(session, cell, step, context):
    deadline=time.monotonic()+120;text='';last=None
    def cancelled():
        if time.monotonic()>deadline:raise RuntimeError('Recipe generation exceeded its row deadline.')
        return not context.heartbeat()
    for part in inference.generate(session,[{'role':'user','content':cell['value']}],max_tokens=step['max_tokens'],
            temperature=0,seed=step['seed'],prompt_format=step.get('prompt_format','model'),cancelled=cancelled):
        text+=part.get('text','')
        if 'usage' in part:last=part
    if last is None or last['finish_reason']=='cancelled':raise ValueError('Recipe generation cancelled or incomplete.')
    return {'text':text,**last}


def recipe_executor(descriptor,context):
    if descriptor.get('payload',{}).get('type')!=TYPE:raise ValueError('This executor accepts recipe jobs only.')
    if not context.heartbeat():return None
    with transaction.atomic():
        run=live_run(context)
        if digest(run.frozen)!=run.input_digest or run.frozen['runtime']!=runtime_digest():raise ValueError('Recipe bindings or runtime changed.')
        if '$result' in run.checkpoints:restored(run,'$result');return None
        reservation=BudgetReservation.all_objects.get(job_id=run.job.job_id,tenant_id=run.tenant_id)
        if reservation.state!='reserved':raise ValueError('Recipe attempt quota is unavailable.')
        UsageEvent.record(tenant_id=run.tenant_id,provider_event_key=f'recipe:{context.attempt.attempt_id}',quantity=1,unit=UNIT,
            reservation=reservation,detail={'run_id':str(run.run_id),'attempt_id':str(context.attempt.attempt_id)})
    definition=read_json(run.frozen['recipe'],run.tenant_id,run.project_id,64000);recipes.validate_recipe(definition)
    if run.model_version and inference.snapshot(run.model_version,run.tenant_id,run.project_id)!=run.frozen['model_snapshot']:
        raise ValueError('Recipe model snapshot changed.')
    protected=protected_rows(run);states={};session=None;calls=0
    with ExitStack() as stack:
        for index, step in enumerate(definition['steps']):
            if not context.heartbeat(progress=index/len(definition['steps'])):return None
            key=step['id']
            if key in run.checkpoints:
                states[key]=restored(run,key);continue
            rejected=[]
            if step['type']=='source':
                raw=source_rows(run.frozen['sources'][key],step,run.tenant_id,run.project_id)
                held_groups={r['source_group_id'] for r in protected}
                excluded=[{'sample_id':r['sample_id'],'reasons':['protected.source_group']} for r in raw if r['source_group_id'] in held_groups]
                allowed=[r for r in raw if r['source_group_id'] not in held_groups]
                prepared=prepare_envelopes(allowed,detect=True,dedup=True,protected=protected) if allowed else {'rows':[],'dropped':[]}
                cells=recipes.source_cells(prepared['rows'],key);rejected=[*excluded,*prepared['dropped']]
            elif step['type']=='merge':
                cells=[c for n in step['inputs'] for c in states[n]['cells']]
                rejected=[r for n in step['inputs'] for r in states[n]['rejected']]
                if len(cells)>128:raise ValueError('Merged recipe output exceeds 128 rows.')
            else:
                previous=states[step['input']];cells=previous['cells'];rejected=list(previous['rejected'])
                if step['type']=='sample':
                    cells=sorted(cells,key=lambda c:digest([step['seed'],c['key']]))[:step['limit']]
                elif step['type'] in {'generate','expression','template','validate'}:
                    if step['type']=='generate' and len(cells)>recipes.MAX_ROWS:raise ValueError('Sample at most 32 rows before generation.')
                    if run.frozen['preview']:cells=cells[:3]
                    output=[]
                    for cell in cells:
                        if not context.heartbeat():return None
                        cell_key=f"{key}/{cell['key']}"
                        if cell_key in run.checkpoints:
                            saved=restored(run,cell_key)
                        else:
                            result=None
                            if step['type']=='generate' and session is None:
                                session=stack.enter_context(inference.local_session(run.model_version,tenant=run.tenant_id,project=run.project_id,device=run.frozen['device']))
                            try:
                                if step['type']=='generate':
                                    calls+=1
                                    if calls>64:raise ValueError('Recipe generation exceeds 64 calls per attempt.')
                                    result=local_generate(session,cell,step,context)
                                    transformed=recipes.generated_cell(cell,step,result)
                                else:transformed=recipes.transform(cell,step)
                                saved={'cell':transformed,'rejection':None}
                            except ValueError as exc:
                                if context.cancel_requested or context.lease_lost:raise
                                saved={'cell':None,'rejection':{'source_sample_id':cell['source']['sample_id'],'step':key,
                                    'reason':str(exc),'output':result['text'] if result else None,'usage':result['usage'] if result else None,
                                    'generation_calls':{**cell['usage'],**({digest([key,cell['key']]):{'usage':result['usage'],'finish_reason':result['finish_reason']}} if result else {})}}}
                            ref=checkpoint(context,cell_key,saved);run.checkpoints[cell_key]=ref
                        if saved['cell']:output.append(saved['cell'])
                        else:rejected.append(saved['rejection'])
                    cells=output
            value={'cells':cells,'rejected':rejected};states[key]=value
            ref=checkpoint(context,key,value);run.checkpoints[key]=ref
        final=states[definition['steps'][-1]['id']]
        rows=recipes.envelopes(final['cells'],recipe_sha=run.frozen['recipe']['sha256'],
            model_sha=digest(run.frozen['model_snapshot']) if run.model_version else None,runtime=run.frozen['runtime'])
        prepared=prepare_envelopes(rows,detect=True,dedup=True,protected=protected) if rows else {'rows':[],'dropped':[]}
        if not run.frozen['preview'] and not prepared['rows']:
            raise ValueError('No accepted recipe rows; dataset publication refused.')
        calls={k:v for cell in final['cells'] for k,v in cell['usage'].items()}
        calls.update({k:v for rejection in final['rejected'] for k,v in rejection.get('generation_calls',{}).items()})
        usage={key:sum(call['usage'][key] for call in calls.values()) for key in ('prompt_tokens','completion_tokens','total_tokens')}
        usage['completed_generation_calls']=len(calls)
        checkpoint(context,'$result',{'rows':prepared['rows'],'rejected':[*final['rejected'],*prepared['dropped']],
            'preview':run.frozen['preview'],'usage':usage})
    return None


def finalize_job(job,status):
    run=RecipeRun.all_objects.select_for_update().select_related('dataset').get(job=job,tenant_id=job.tenant_id)
    if status=='succeeded':
        if job.pool.result_egress!='envelope':raise ValueError('Recipe publication is forbidden by egress policy.')
        output=restored(run,'$result')
        report=_store(io.BytesIO(json.dumps(output,allow_nan=False).encode()),tenant=run.tenant_id,project=run.project_id,
            name='recipe-report.json',media_type='application/json',metadata={'kind':'recipe_result','run_id':str(run.run_id)})
        result={'report':report,'row_count':len(output['rows']),'rejected_count':len(output['rejected']),'preview':run.frozen['preview'],'usage':output['usage']}
        if not run.frozen['preview']:
            if not output['rows']:raise ValueError('No accepted recipe rows; dataset publication refused.')
            payload=''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in output['rows']).encode()
            ref=_store(io.BytesIO(payload),tenant=run.tenant_id,project=run.project_id,name='recipe-output.jsonl',
                media_type='application/x-ndjson',metadata={'kind':'recipe_dataset_input','run_id':str(run.run_id)})
            artifact=Artifact.all_objects.get(artifact_id=ref['artifact_id'],tenant_id=run.tenant_id)
            parents=[run.frozen['recipe'],*run.frozen['sources'].values(),*run.frozen['protected']]
            if run.frozen['model_snapshot']:
                parents += list(run.frozen['model_snapshot']['files'].values())
            for parent in {p['artifact_id']:p for p in parents}.values():
                LineageEdge.all_objects.create(tenant_id=run.tenant_id,parent_artifact_id=Artifact.all_objects.get(artifact_id=parent['artifact_id']).pk,
                    child_artifact=artifact,relation='recipe_input',detail={'run_id':str(run.run_id),'input_digest':run.input_digest})
            revision=publish_prepared_dataset(run.dataset,artifact,detect=True,dedup=True,protected=protected_rows(run))
            result.update(output_artifact=ref,revision_id=str(revision.revision_id),row_count=revision.row_count)
        run.result=result
    run.status='completed' if status=='succeeded' else status;run.completed_at=timezone.now();run.save()
    reservation=BudgetReservation.all_objects.get(job_id=job.job_id,tenant_id=job.tenant_id)
    if reservation.state=='reserved':reservation.settle(sum(reservation.usage_events.values_list('quantity',flat=True)))


@transaction.atomic
def cancel(run):
    job=Job.all_objects.select_for_update().get(pk=run.job_id,tenant_id=run.tenant_id)
    if job.status in {'succeeded','failed'}:raise ValueError('The recipe job is already terminal.')
    job.desired_action='cancel'
    if job.status in {'queued','interrupted'}:job.status='cancelled';finalize_job(job,'cancelled')
    job.save(update_fields=['desired_action','status','updated_at']);return job


@transaction.atomic
def retry(run):
    job=Job.all_objects.select_for_update().get(pk=run.job_id,tenant_id=run.tenant_id)
    if job.status not in {'failed','interrupted'} or job.desired_action=='cancel' or job.attempt_count>=MAX_ATTEMPTS:
        raise ValueError('Retry requires a failed/interrupted job with remaining claims.')
    reservation=BudgetReservation.all_objects.select_for_update().get(job_id=job.job_id,tenant_id=job.tenant_id)
    policy=BudgetPolicy.all_objects.select_for_update().get(pk=reservation.policy_id)
    period,committed=BudgetReservation.current_commitment(policy)
    if not policy.enabled or period!=reservation.period_start or committed+MAX_ATTEMPTS-(reservation.settled_amount or 0)>policy.limit_amount:
        raise ValueError('The original recipe quota cannot admit a retry.')
    reservation.state='reserved';reservation.settled_amount=None;reservation.settled_at=None;reservation.save()
    job.status='queued';job.save(update_fields=['status','updated_at'])
    run.status='queued';run.completed_at=None;run.save(update_fields=['status','completed_at','updated_at'])
    OutboxEvent.objects.create(tenant_id=job.tenant_id,topic=dispatch_topic(job.tenant_id,job.pool.queue_name,job.pool.name),
        payload={'event_type':'job.queued','job_id':str(job.job_id)})
    return job
