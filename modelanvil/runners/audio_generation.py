"""Typed, budgeted offline TTS jobs using the durable worker and physical CPU fence."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from django.db import transaction
from django.utils import timezone
from modelanvil.artifacts.models import Artifact
from modelanvil.budgets.models import BudgetPolicy,BudgetReservation,UsageEvent
from modelanvil.core.ids import uuid7
from modelanvil.core.models import IdempotencyKey
from modelanvil.identity.models import Tenant,check_resource_access
from modelanvil.jobs.models import Job,JobAttempt,Worker,WorkerPool
from modelanvil.runners.models import InferenceRequest,TrainingRun
from modelanvil.runners.inference import verified_artifact,copy_verified,runtime_input_identity
from modelanvil.runners.model_catalog import _store
from modelanvil.runners.training import audio_runtime as runtime
from modelanvil.runners.training.runtime import digest

TYPE='qualified_audio_generation'
UNIT='audio_samples'
MAX_ATTEMPTS=3


def candidate_bundle(version,tenant,project):
    processor=version.processor;tokenizer=version.tokenizer
    if (version.architecture_ref!=runtime.RUNTIME_ID or version.state in ('archived','rejected')
            or any(obj is None or not check_resource_access(obj,project,tenant) for obj in (version,processor,tokenizer))
            or not isinstance(version.metadata,dict) or not isinstance(processor.metadata,dict)
            or processor.metadata.get('audio_profile')!=runtime.PROCESSOR
            or processor.configuration_digest!=digest({'files':runtime.FILE_HASHES,'processor':runtime.PROCESSOR})
            or tokenizer.compatibility.get('hf_snapshot')!=runtime.SOURCE['tts'] or tokenizer.chat_template or tokenizer.vocabulary_size!=81):
        raise ValueError('Use the accessible exact CPU speech model, tokenizer and audio processor.')
    ref=version.metadata.get('snapshot_manifest');trained=False
    if ref:
        if ref.get('artifact_id')!=version.artifact_manifest_id or processor.metadata.get('artifact_manifest_id')!=version.artifact_manifest_id:
            raise ValueError('Speech base and processor manifest differ.')
        artifact=verified_artifact(ref,tenant,project)
        if artifact.byte_size>1024**2:raise ValueError('Speech manifest exceeds its bound.')
        raw=io.BytesIO();copy_verified(ref,tenant,project,raw);bundle=json.loads(raw.getvalue())
        if bundle.get('source')!=runtime.SOURCE or set(bundle.get('files',{}))!=set(runtime.FILE_HASHES)|set(runtime.EVALUATOR_FILE_HASHES):
            raise ValueError('Speech base snapshot is incomplete.')
        files={n:r for n,r in bundle['files'].items() if n in runtime.FILE_HASHES}
    else:
        run=TrainingRun.all_objects.filter(output_model_version=version,tenant_id=tenant,status='completed',job__status='succeeded',
            base_model_version__architecture_ref=runtime.RUNTIME_ID).first()
        if (run is None or not check_resource_access(run,project,tenant) or run.tokenizer_version_id!=tokenizer.pk
                or run.base_model_version.processor_id!=processor.pk):raise ValueError('Speech candidate needs successful actual training lineage.')
        checkpoint=run.checkpoints.filter(step=version.metadata.get('selected_checkpoint_step',run.total_steps)).first()
        if checkpoint is None or version.metadata.get('checkpoint_digest')!=checkpoint.state_digest:raise ValueError('Speech checkpoint lineage changed.')
        bundle=runtime.checkpoint_bundle(run,checkpoint);artifact=Artifact.all_objects.filter(artifact_id=version.artifact_manifest_id,tenant_id=tenant).first()
        if artifact is None or artifact.byte_size>1024**2:raise ValueError('Speech candidate manifest is unavailable.')
        raw=io.BytesIO();copy_verified(runtime.file_ref(artifact),tenant,project,raw)
        if digest(json.loads(raw.getvalue()))!=digest(bundle):raise ValueError('Speech candidate differs from its committed checkpoint.')
        files=bundle['files'];trained=True
    if set(files)!=set(runtime.FILE_HASHES)|({'audio_head.safetensors'} if trained else set()):raise ValueError('Speech snapshot contains incompatible files.')
    if any(files[n].get('sha256')!=sha for n,sha in runtime.FILE_HASHES.items()):raise ValueError('Speech source checksums differ.')
    for ref in files.values():verified_artifact(ref,tenant,project)
    return {'format':'audio','files':files,'source':runtime.SOURCE,'trained':trained,'recipe':'tts_output_head','production_qualified':False}


def controls(text,seed,max_seconds):
    if (not isinstance(text,str) or not text.strip() or len(text)>96 or type(seed) is not int or not 0<=seed<=2147483647
            or type(max_seconds) is not int or not 1<=max_seconds<=6):raise ValueError('Use1–96 text characters, an integer seed and1–6 seconds.')
    return {'text':text,'seed':seed,'max_seconds':max_seconds}


@transaction.atomic
def queue(*,tenant,project,principal,version,text,seed,max_seconds,pool,policy_id,key):
    settings=controls(text,seed,max_seconds);runtime.require_packages();plan=candidate_bundle(version,tenant,project.pk)
    with runtime.staged_files(plan['files'],tenant,project.pk) as directory:
        processor=runtime.math.processor(directory);encoded=processor(text=text,return_tensors='pt')['input_ids']
        if encoded.shape[-1]>128 or encoded.eq(processor.tokenizer.unk_token_id).any() or any(t in text for t in processor.tokenizer.all_special_tokens):
            raise ValueError('Text is outside the supported speech character vocabulary.')
    frozen={'settings':settings,'model_id':str(version.model_version_id),'model_identity':runtime_input_identity(version),
        'plan':plan,'build_digest':runtime.build_digest(),'accelerator':runtime.observed_device('cpu')}
    fingerprint=digest({'frozen':frozen,'pool':pool.pk,'policy_id':str(policy_id)})
    admission,created=IdempotencyKey.all_objects.select_for_update().get_or_create(tenant_id=tenant,principal=str(principal),
        http_method='POST',path=f'/audio/{project.pk}/jobs',key=key,defaults={'request_hash':fingerprint})
    if not created:
        if admission.request_hash!=fingerprint:raise ValueError('Idempotency key belongs to different speech inputs.')
        return InferenceRequest.all_objects.get(request_id=admission.response_body['request_id'],tenant_id=tenant,project=project)
    from modelanvil.jobs.setup import local_capacity_available
    workers=list(Worker.all_objects.filter(tenant_id=tenant,pool=pool,status__in=('available','busy')))
    if (str(pool.tenant_id)!=str(tenant) or pool.status!='active' or pool.result_egress!='envelope' or len(workers)!=1
            or not runtime.capable_worker(workers[0]) or not local_capacity_available(workers[0])):
        raise ValueError('Use an active envelope pool with one available exact CPU speech worker.')
    policy=BudgetPolicy.all_objects.filter(tenant_id=tenant,policy_id=policy_id,enabled=True,unit=UNIT,currency='').first()
    if policy is None:raise ValueError('Select an enabled audio_samples quota without currency pricing.')
    job_id=uuid7();BudgetReservation.reserve(tenant_id=tenant,policy=policy,job_id=job_id,estimated_amount=MAX_ATTEMPTS*max_seconds*16000)
    record=InferenceRequest.all_objects.create(tenant_id=tenant,project=project,principal_id=str(principal),model_version=version,
        input_digest=digest(frozen),status='queued',configuration={'kind':TYPE,'job_id':str(job_id),'frozen':frozen})
    Job.all_objects.create(tenant_id=tenant,project=project,job_id=job_id,pool=pool,name='Generate bounded CPU speech',max_attempts=MAX_ATTEMPTS,
        payload={'type':TYPE,'request_id':str(record.request_id),'input_digest':record.input_digest},
        requirements={'slots':1,'training_runtime':runtime.CONTRACT_DIGEST,'gpu_device':'cpu'})
    admission.response_body={'request_id':str(record.request_id)};admission.response_status=202;admission.completed_at=timezone.now();admission.save()
    return record


def owning_request(job,lock=False):
    qs=InferenceRequest.all_objects.select_related('model_version__processor','model_version__tokenizer','project')
    if lock:qs=qs.select_for_update()
    record=qs.get(request_id=job.payload['request_id'],tenant_id=job.tenant_id)
    if (record.configuration.get('kind')!=TYPE or record.configuration.get('job_id')!=str(job.job_id) or record.project_id!=job.project_id
            or record.input_digest!=job.payload.get('input_digest') or digest(record.configuration['frozen'])!=record.input_digest):
        raise ValueError('Audio job ownership or immutable input identity changed.')
    return record


def current_inputs(record,job):
    frozen=record.configuration['frozen']
    if (not Tenant.objects.filter(pk=record.tenant_id,status='active').exists() or job.pool.result_egress!='envelope'
            or frozen['build_digest']!=runtime.build_digest() or frozen['accelerator']!=runtime.observed_device('cpu')
            or frozen['model_identity']!=runtime_input_identity(record.model_version)
            or frozen['plan']!=candidate_bundle(record.model_version,record.tenant_id,record.project_id)):
        raise ValueError('Speech source, processor, code, device, project or egress changed.')
    reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id,job_id=job.job_id,state='reserved')
    policy=BudgetPolicy.all_objects.select_for_update().get(pk=reservation.policy_id,tenant_id=job.tenant_id)
    period,committed=BudgetReservation.current_commitment(policy)
    if (not policy.enabled or policy.unit!=UNIT or policy.currency or reservation.period_start!=period or committed>policy.limit_amount
            or reservation.estimated_amount!=MAX_ATTEMPTS*frozen['settings']['max_seconds']*16000):raise ValueError('Speech budget is no longer authorized.')
    return frozen,reservation


def live(context):
    attempt=JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job=Job.all_objects.select_for_update().select_related('pool').get(pk=attempt.job_id)
    if (attempt.status!='running' or job.status!='running' or attempt.fencing_token!=context.fencing_token
            or job.fencing_token!=context.fencing_token or job.claimed_by_id!=attempt.worker_id
            or not attempt.lease_expires_at or attempt.lease_expires_at<=timezone.now() or job.desired_action=='cancel'):
        raise ValueError('Speech job cancelled or fenced out.')
    record=owning_request(job,lock=True);current_inputs(record,job)
    return record,job


def gpu_claim_plan(job,worker):
    from modelanvil.device_admission import device_key,device_available
    record=owning_request(job,lock=True);frozen,_=current_inputs(record,job)
    if not runtime.capable_worker(worker) or not device_available('cpu'):raise ValueError('Exact physical CPU speech worker is unavailable.')
    return {'host_key':frozen['accelerator']['host_key'],'device_key':device_key('cpu')}


def validate_output(raw,report,frozen):
    if not isinstance(report,dict) or not 0<len(raw)<=200000:raise ValueError('Speech output/report exceeds its bound.')
    _,pin=runtime.math.decode_audio(raw,'audio/wav');settings=frozen['settings'];frames=report.get('frames')
    if (report.get('schema_version')!='modelanvil.independent-audio-generation.v1'
            or type(frames) is not int or not 4000<=frames<=settings['max_seconds']*16000
            or frames!=pin['frames'] or pin['sample_rate']!=16000 or pin['channels']!=1 or pin['normalized_rms']<1e-6
            or report.get('wave_sha256')!=pin['sha256'] or report.get('wave_bytes')!=len(raw)
            or report.get('duration_seconds')!=frames/16000 or report.get('sample_rate')!=16000
            or report.get('channels')!=1 or report.get('sample_format')!='PCM_S16_LE'
            or report.get('seed')!=settings['seed'] or report.get('maximum_seconds')!=settings['max_seconds']
            or report.get('file_sha256')!={n:r['sha256'] for n,r in frozen['plan']['files'].items()}
            or report.get('consumer_imported_modelanvil_or_django') is not False
            or type(report.get('prompt_tokens')) is not int or not 1<=report['prompt_tokens']<=128
            or report.get('finish_reason') not in ('stop','length')):
        raise ValueError('Speech consumer WAV, source, settings or output provenance differs.')
    for key,minimum,maximum in (('cpu_seconds',0,60),('wall_seconds',0,70),
            ('rms_before_quantization',1e-6,1),('clipped_fraction',0,.01),('last_stop_probability_sum',0,2)):
        value=report.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:
            raise ValueError('Speech consumer measurement is missing, non-finite or outside its bound.')
    if (report['finish_reason']=='stop')!=(report['last_stop_probability_sum']>=.5):
        raise ValueError('Speech stop evidence differs from the reported finish reason.')
    return pin


def read_result(record):
    if candidate_bundle(record.model_version,record.tenant_id,record.project_id)!=record.configuration['frozen']['plan']:
        raise ValueError('Speech source or processor access changed since generation.')
    result=record.configuration.get('checkpoint')
    if not isinstance(result,dict) or result.get('input_digest')!=record.input_digest:raise ValueError('Speech has no complete verified output.')
    artifact=verified_artifact(result['audio'],record.tenant_id,record.project_id)
    if artifact.media_type!='audio/wav' or artifact.byte_size>200000:raise ValueError('Speech output exceeds its media bound.')
    raw=io.BytesIO();copy_verified(result['audio'],record.tenant_id,record.project_id,raw)
    validate_output(raw.getvalue(),result['report'],record.configuration['frozen'])
    if result['report']['finish_reason']!='stop':raise ValueError('Length-limited speech is incomplete.')
    return result


def audio_executor(descriptor,context):
    if descriptor.get('payload',{}).get('type')=='qualified_training':
        from modelanvil.runners.training.executor import training_worker_executor
        return training_worker_executor(descriptor,context)
    if descriptor.get('payload',{}).get('type')!=TYPE:raise ValueError('This executor accepts fixed audio/training jobs only.')
    try:
        if not context.heartbeat(progress=0):return
        with transaction.atomic():
            record,job=live(context)
            if record.configuration.get('checkpoint'):read_result(record);return
            frozen,reservation=current_inputs(record,job);attempt_id=str(context.attempt.attempt_id)
            maximum=frozen['settings']['max_seconds']*16000
            # A lost in-flight attempt consumes its bounded ceiling, never a fabricated zero.
            charges=record.configuration.get('attempt_charges',{})
            if attempt_id not in charges:charges={**charges,attempt_id:{'samples':maximum,'basis':'unknown_inflight_upper_bound'}}
            record.configuration={**record.configuration,'attempt_charges':charges};record.status='running';record.save()
        from modelanvil.device_admission import device_lease
        with device_lease('cpu',pass_descriptor=True) as fd,tempfile.TemporaryDirectory(prefix='modelanvil-tts-') as temp:
            root=Path(temp);output=root/'speech.wav';settings=frozen['settings']
            with runtime.staged_files(frozen['plan']['files'],record.tenant_id,record.project_id) as directory:
                command=[sys.executable,'-I',str(Path(__file__).resolve().parents[2]/'scripts/audio_candidate_infer.py'),str(directory),
                    '--text',settings['text'],'--seed',str(settings['seed']),'--max-seconds',str(settings['max_seconds']),'--output',str(output)]
                env={'PATH':os.environ.get('PATH',''),'HOME':str(root),'HF_HOME':str(root/'hub'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                    'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1'}
                with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
                    child=subprocess.Popen(command,stdout=stdout,stderr=stderr,env=env,pass_fds=(fd,));deadline=time.monotonic()+70
                    try:
                        while child.poll() is None:
                            if not context.heartbeat(progress=.5):return
                            with transaction.atomic():live(context)
                            if time.monotonic()>deadline:raise ValueError('Speech consumer timed out.')
                            time.sleep(.25)
                        if child.returncode:raise ValueError('Speech consumer did not complete.')
                        stdout.seek(0);raw=stdout.read(65537)
                        if len(raw)>65536:raise ValueError('Speech report exceeds its bound.')
                        report=json.loads(raw)
                    finally:
                        if child.poll() is None:child.kill()
                        child.wait()
            if not output.is_file() or not 0<output.stat().st_size<=200000:raise ValueError('Speech consumer produced no bounded WAV.')
            raw=output.read_bytes();validate_output(raw,report,frozen)
            with transaction.atomic():
                record,job=live(context);charges=record.configuration['attempt_charges']
                charges[attempt_id]={'samples':report['frames'],'basis':'verified_generated_frames','cpu_seconds':report['cpu_seconds'],'wall_seconds':report['wall_seconds']}
                record.configuration={**record.configuration,'attempt_charges':charges}
                if report.get('finish_reason')=='stop':
                    ref=_store(io.BytesIO(raw),tenant=record.tenant_id,project=record.project_id,name='speech.wav',media_type='audio/wav',
                        metadata={'kind':'tts_output','request_id':str(record.request_id)})
                    record.configuration['checkpoint']={'input_digest':record.input_digest,'audio':ref,'report':report,
                        'source':runtime.SOURCE,'settings':settings,'model_identity':frozen['model_identity'],'production_qualified':False}
                record.save(update_fields=['configuration','updated_at'])
    except Exception:
        # Terminal validation provides a fixed error; private transcript/library diagnostics never leave the worker.
        return


def finalize_job(job,status):
    if status in ('queued','interrupted'):return status
    record=owning_request(job,lock=True)
    if job.desired_action=='cancel':status='cancelled'
    if status=='succeeded':
        try:current_inputs(record,job);result=read_result(record)
        except (ValueError,KeyError,TypeError,OSError):status='failed'
        else:
            record.output_digest=digest(result);record.elapsed_seconds=result['report']['wall_seconds']
            record.usage={'generated_samples':result['report']['frames'],'sample_rate':16000,'duration_seconds':result['report']['duration_seconds']}
    record.status='completed' if status=='succeeded' else status;record.completed_at=timezone.now();record.save()
    reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id,job_id=job.job_id)
    if reservation.state=='reserved':
        charges=record.configuration.get('attempt_charges',{});used=sum(c['samples'] for c in charges.values())
        for attempt,charge in charges.items():
            UsageEvent.record(tenant_id=job.tenant_id,provider_event_key=f'audio:{attempt}',quantity=charge['samples'],unit=UNIT,
                reservation=reservation,detail={'request_id':str(record.request_id),'attempt_id':attempt,**charge})
        reservation.settle(used)
    return status


@transaction.atomic
def cancel(record):
    job=Job.all_objects.select_for_update().get(job_id=record.configuration['job_id'],tenant_id=record.tenant_id)
    if job.status in ('succeeded','failed','cancelled'):raise ValueError('This speech job is already terminal.')
    job.desired_action='cancel'
    if job.status in ('queued','interrupted'):job.status=finalize_job(job,'cancelled')
    job.save(update_fields=['desired_action','status','updated_at']);return job
