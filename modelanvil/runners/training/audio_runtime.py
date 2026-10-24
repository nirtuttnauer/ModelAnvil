"""Pinned CPU speech output-head training; generation and qualification use bounded consumers."""
import hashlib
import importlib.metadata
import json
import math as scalar_math
from pathlib import Path
import tempfile
from contextlib import contextmanager

from django.db import transaction
from modelanvil.artifacts.storage import LocalArtifactStorage, artifact_storage_backend
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Worker
from modelanvil.runners.inference import verified_artifact, copy_verified, runtime_input_identity
from modelanvil.runners.training import hf_runtime as hf, cpu_hf_runtime as cpu
from modelanvil.runners.training.runtime import digest, read_artifact
from . import audio_math as math, audio_data

RUNTIME_ID = 'modelanvil.speecht5-cpu-output-head.v1'
DEVICE = 'cpu'
SOURCE, FILE_HASHES = math.SOURCE, math.FILE_HASHES
EVALUATOR_SOURCE = {'repo_id': 'openai/whisper-tiny.en', 'revision': '87c7102498dcde7456f24cfd30239ca606ed9063', 'license': 'Apache-2.0'}
EVALUATOR_FILE_HASHES = {'evaluator/added_tokens.json': '560be47bea388757f8d4cc185c5d82067426cbb6361e38016dd90ddc01ab203a', 'evaluator/config.json': 'b5366317df280f79e6cc366f259f379674f81a8721d458acf2e00680ccb10b1d', 'evaluator/generation_config.json': '38744c19d5cede6ff4dab5079c6d6ddc02ca726960bbef208fb602ad5a030eab', 'evaluator/merges.txt': '1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5', 'evaluator/model.safetensors': 'db59695928ded6043adaef491a53ef4e12da9611184d77c53baa691a60b958ad', 'evaluator/normalizer.json': 'bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd', 'evaluator/preprocessor_config.json': '9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666', 'evaluator/special_tokens_map.json': '014f8f802366ed818919550be0ad9e35907327cb9e142e8aaa102420f460bda8', 'evaluator/tokenizer.json': '5eb60cec1e77aeeb6869a2bb5a8e01a84c3fe5d072d75369343021fe6f5310d0', 'evaluator/tokenizer_config.json': '14f84bdf4b9ecdbd4738ddc81c17a1baedfc02bb93c6e049c951e15a1b40b70d', 'evaluator/vocab.json': '3ba3c3109ff33976c4bd966589c11ee14fcaa1f4c9e5e154c2ed7f99d80709e7'}
file_ref = hf.file_ref
PACKAGES = {**hf.PACKAGES, 'numpy':'2.3.3', 'scipy':'1.18.1', 'sentencepiece':'0.2.1',
    'soundfile':'0.14.0', 'cffi':'2.1.1', 'pycparser':'3.12'}
LIMITS = {'rows':32, 'steps':10, 'sequence_tokens':128, 'memory_bytes':16*1024**3,
    'gpu_memory_bytes':0, 'weight_bytes':700*1024**2, 'aux_bytes':8*1024**2, 'test_cases':4}
OPTIMIZER = {**hf.OPTIMIZER, 'learning_rate':.00001}
PROCESSOR = {'sample_rate':16000, 'max_seconds':6, 'channels':'mean_to_mono',
    'transform':'pcm16_mean_channels_scipy_resample_poly_kaiser5_clip_v1',
    'maximum_text_characters':96, 'maximum_text_tokens':128, 'maximum_mel_frames':376,
    'reduction_factor':2, 'odd_mel_padding':'one_masked_frame', 'speaker':'fixed_published_demo',
    'loss':'speecht5_composite_spectrogram_stop_attention_v1'}
CONTRACT = {'runtime':RUNTIME_ID, 'source':SOURCE, 'files':FILE_HASHES, 'evaluator_source':EVALUATOR_SOURCE,
    'evaluator_files':EVALUATOR_FILE_HASHES, 'packages':PACKAGES, 'precision':'fp32', 'cpu_threads':1,
    'recipe':'tts_output_head', 'recipes':['tts_output_head'], 'optimizer':OPTIMIZER,
    'head_parameters':sorted(math.HEAD_NAMES), 'trainable_parameters':124578, 'initialization_seed':42,
    'processor':PROCESSOR, 'limits':LIMITS, 'production_qualified':False}
CONTRACT_DIGEST = digest(CONTRACT)
LICENSE_ASSET = 'MIT-SpeechT5.txt'


def require_packages():
    for name,expected in PACKAGES.items():
        try: installed = importlib.metadata.version(name).split('+')[0]
        except importlib.metadata.PackageNotFoundError: installed = None
        if installed != expected: raise ValueError(f'Install {name}=={expected} for the pinned CPU audio profile.')


def observed_device(selector): return cpu.observed_device(selector)

def memory_observation(selector): return cpu.memory_observation(selector)


def runner_manifest():
    return {'schema_version':'1.0','adapter_id':RUNTIME_ID,'version':'1','platform_api':'v1',
        'image':f'local-python-contract@sha256:{CONTRACT_DIGEST}','license':'MIT TTS/vocoder/demo conditioning; Apache-2.0 evaluator; library licenses retained',
        'capabilities':[{'kind':'train','input_schema_refs':['urn:modelanvil:schema:sample-envelope:1.0'],
            'output_schema_refs':['huggingface:safetensors'],'formats':['audio','text'],'architectures':[RUNTIME_ID],'recovery':'verified_checkpoint'}],
        'resources':{'cpu_cores':1,'memory_bytes':LIMITS['memory_bytes'],'gpu_count':0,'disk_bytes':2*1024**3,'distributed':False},
        'permissions':{'network_hosts':[],'artifact_access':['read_job_inputs','write_attempt_staging'],'secret_kinds':[]},
        'dependencies':[],'limitations':['Exact English SpeechT5 TTS with fixed published demo conditioning and HiFi-GAN vocoder.',
            'FP32 CPU only;124578 mel/stop-head parameters,1–10updates; no full SFT, LoRA, quantization, voice cloning or product ASR.',
            'PCM16 WAV/FLAC0.25–6seconds, supported8–48kHz mono/stereo,4MiB;96 transcript characters,128 text tokens.',
            'Independent WhisperTiny WER is a proxy; human/customer/production quality and other hardware require separate qualification.']}


def _source_digest():
    root = Path(__file__).resolve().parents[3]
    names = ('modelanvil/runners/training/audio_runtime.py','modelanvil/runners/training/audio_math.py',
        'modelanvil/runners/training/audio_data.py','modelanvil/runners/training/registry.py',
        'modelanvil/runners/training/runtime.py','modelanvil/runners/training/hf_runtime.py',
        'modelanvil/runners/alignment/torch_rlhf.py','modelanvil/runners/training/admission.py',
        'modelanvil/runners/inference.py','modelanvil/runners/models.py','modelanvil/jobs/models.py',
        'modelanvil/device_admission.py','modelanvil/runners/audio_generation.py','modelanvil/api/views/audio.py',
        'modelanvil/runners/capabilities.py','modelanvil/jobs/access.py','modelanvil/api/views/jobs_artifacts.py',
        'modelanvil/api/views/training_views.py','modelanvil/runners/management/commands/setup_audio_training.py',
        'scripts/convert_speecht5.py','scripts/audio_candidate_infer.py','scripts/score_audio_candidate.py','requirements.audio.txt')
    return hashlib.sha256(b''.join((root/name).read_bytes() for name in names)).hexdigest()


_BUILD_DIGEST = _source_digest()


def build_digest():
    if _source_digest() != _BUILD_DIGEST:
        raise ValueError('Audio runtime changed on disk; restart API and worker before launch or recovery.')
    return _BUILD_DIGEST


def validate_options(*,precision='fp32',adapter=None,quantization=None,recipe_type='tts_output_head'):
    if precision!='fp32' or adapter not in (None,'none') or quantization not in (None,'none') or recipe_type!='tts_output_head':
        raise ValueError('Use the pinned FP32 CPU speech output-head recipe; other audio recipes require qualification.')


def capable_worker(worker):
    caps=worker.capabilities
    return (caps.get('training_runtime')==CONTRACT_DIGEST and caps.get('gpu_backend')=='cpu' and caps.get('gpu_device')=='cpu'
        and caps.get('gpu_packages')==PACKAGES and type(caps.get('memory_bytes')) is int and caps['memory_bytes']>=LIMITS['memory_bytes']
        and worker.slots in (0,1) and worker.status in ('available','busy','draining'))


@contextmanager
def staged_files(files,tenant,project):
    allowed=set(FILE_HASHES)|set(EVALUATOR_FILE_HASHES)|{'audio_head.safetensors','optimizer.safetensors','rng.safetensors'}
    if not isinstance(files,dict) or not files or set(files)-allowed: raise ValueError('Audio snapshot contains unsupported filenames.')
    total=0
    with tempfile.TemporaryDirectory(prefix='modelanvil-audio-') as temp:
        directory=Path(temp)
        for name,ref in files.items():
            artifact=verified_artifact(ref,tenant,project);total+=artifact.byte_size
            maximum=LIMITS['weight_bytes'] if name=='model.safetensors' else 200*1024**2 if name=='evaluator/model.safetensors' else 64*1024**2 if name=='vocoder/model.safetensors' else LIMITS['aux_bytes']
            if artifact.byte_size>maximum or total>2*1024**3:raise ValueError('Audio snapshot file or staging size exceeds its bound.')
            path=directory/name;path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('wb') as output:copy_verified(ref,tenant,project,output)
        yield directory


def resolve_inputs(*,dataset,base,tokenizer,runner,pool,tenant,project,steps,require_capacity=True,
                   recipe_type='tts_output_head',initialization_seed=42):
    from modelanvil.device_admission import device_available
    require_packages()
    if recipe_type!='tts_output_head' or type(initialization_seed) is not int or initialization_seed!=42 or type(steps) is not int or not 1<=steps<=10:
        raise ValueError('Use1–10 CPU speech output-head updates with training RNG seed42.')
    if (not all((dataset,base,tokenizer,runner,pool)) or not project or not isinstance(artifact_storage_backend(),LocalArtifactStorage)
            or any(not check_resource_access(obj,project,tenant) for obj in (dataset,base,tokenizer,runner,pool))):
        raise ValueError('Select accessible local speech data, base/processor, tokenizer, runner and dedicated worker pool.')
    if (not isinstance(base.metadata,dict) or not isinstance(tokenizer.compatibility,dict) or base.processor_id is None
            or not isinstance(base.processor.metadata,dict) or base.state in ('archived','rejected') or base.architecture_ref!=RUNTIME_ID
            or base.tokenizer_id!=tokenizer.pk or not check_resource_access(base.processor,project,tenant)
            or base.metadata.get('source')!=SOURCE or tokenizer.compatibility.get('hf_snapshot')!=SOURCE['tts']
            or base.processor.metadata.get('audio_profile')!=PROCESSOR
            or base.processor.configuration_digest!=digest({'files':FILE_HASHES,'processor':PROCESSOR})):
        raise ValueError('Use the exact pinned speech base, text/audio processor, tokenizer and conditioning profile.')
    if (not runner.enabled or runner.manifest!=runner_manifest() or runner.digest!=digest(runner_manifest())
            or runner.compatibility.get('contract_digest')!=CONTRACT_DIGEST or pool.status not in (('active',) if require_capacity else ('active','draining'))):
        raise ValueError('Enable the exact audio runner manifest and active dedicated worker pool.')
    ref=base.metadata.get('snapshot_manifest');artifact=verified_artifact(ref,tenant,project)
    if str(artifact.artifact_id)!=base.artifact_manifest_id or base.processor.metadata.get('artifact_manifest_id')!=base.artifact_manifest_id or artifact.byte_size>1024**2:
        raise ValueError('Audio base and processor must pin the same bounded immutable snapshot manifest.')
    raw=read_artifact(artifact,tenant,project)
    try:bundle=json.loads(raw)
    except (ValueError,UnicodeError,RecursionError):raise ValueError('Audio base manifest is malformed.') from None
    expected={**FILE_HASHES,**EVALUATOR_FILE_HASHES}
    if (not isinstance(bundle,dict) or bundle.get('source')!=SOURCE or not isinstance(bundle.get('files'),dict)
            or set(bundle['files'])!=set(expected) or any(not isinstance(bundle['files'][n],dict) or bundle['files'][n].get('sha256')!=sha for n,sha in expected.items())):
        raise ValueError('Audio source/processor/vocoder/conditioning/evaluator files differ from the pinned complete snapshot.')
    workers=list(Worker.all_objects.filter(tenant_id=tenant,pool=pool,status__in=('available','busy') if require_capacity else ('available','busy','draining')))
    if len(workers)!=1 or not capable_worker(workers[0]) or require_capacity and (workers[0].slots<1 or workers[0].drain_requested):
        raise ValueError('Use one matching single-slot local CPU audio worker with sufficient declared host memory.')
    observed=observed_device('cpu')
    if require_capacity and not device_available('cpu'):raise ValueError('The cooperating CPU device is busy.')
    with staged_files(bundle['files'],tenant,project) as directory:
        processor=math.processor(directory)
        if len(processor.tokenizer)!=tokenizer.vocabulary_size or tokenizer.chat_template:
            raise ValueError('Speech tokenizer vocabulary or incompatible chat template changed.')
        data=audio_data.samples(dataset,processor,tenant,project)
    if len(data['test'])>LIMITS['test_cases']:raise ValueError('This bounded audio profile supports1–4 protected test utterances.')
    config={'runtime':RUNTIME_ID,'source':SOURCE,'processor':PROCESSOR,'model_role':'text_to_speech','sequence_tokens':128}
    pins={'runtime':RUNTIME_ID,'contract_digest':CONTRACT_DIGEST,'build_digest':build_digest(),
        'dataset_id':str(dataset.revision_id),'dataset_digest':dataset.manifest_digest,
        'base_id':str(base.model_version_id),'base_artifact_id':str(artifact.artifact_id),'base_digest':hashlib.sha256(raw).hexdigest(),
        'base_input_identity':runtime_input_identity(base),'tokenizer_id':str(tokenizer.tokenizer_id),
        'tokenizer_digest':digest({n:r for n,r in bundle['files'].items() if not n.endswith('.safetensors')}),
        'processor_id':str(base.processor.processor_id),'processor_digest':base.processor.configuration_digest,
        'runner_id':str(runner.manifest_id),'runner_digest':runner.digest,'pool_id':pool.pk,'worker_id':workers[0].pk,
        'steps':steps,'config':config,'source':SOURCE,'optimizer':OPTIMIZER,'recipe':recipe_type,
        'initialization_seed':42,'sample_order':'seeded_epoch_shuffle_v1','accelerator':observed,'trainable_parameters':124578,
        'sample_digest':digest(data['train']),'validation_digest':digest(data['validation']),'protected_test_digest':digest(data['test']),
        'asset_pins':{name:[r['audio'] for r in rows] for name,rows in data.items()},
        'splits':{'consumed':'train','train_rows':len(data['train']),'excluded_rows':{n:len(v) for n,v in data.items() if n!='train'}},
        'evaluator_source':EVALUATOR_SOURCE,'evaluator_files':{n:r for n,r in bundle['files'].items() if n in EVALUATOR_FILE_HASHES},'production_qualified':False}
    return {'pins':pins,'bundle':bundle,'tokenizer':{'kind':'speecht5-char','source':SOURCE['tts']},
        'samples':data['train'],'validation_samples':data['validation'],'protected_test_samples':data['test'],
        'sequences':[r['token_ids'] for r in data['train']],'checkpoint_bytes':12*124578+1024**2,
        'checkpoint_count':steps,'staging_bytes':2*sum(r['byte_size'] for n,r in bundle['files'].items() if n in FILE_HASHES)+sum(r['byte_size'] for n,r in bundle['files'].items() if n in EVALUATOR_FILE_HASHES)}


def is_worker_run(run): return (run.hardware_config or {}).get('execution_mode')=='worker'


def checkpoint_bundle(run,checkpoint):
    state=checkpoint.weights_manifest
    if (not checkpoint.is_valid or digest(state)!=checkpoint.state_digest or state.get('pins')!=run.hardware_config['pins']
            or state.get('run_id')!=str(run.run_id) or state.get('step')!=checkpoint.step or state.get('metrics')!=checkpoint.metrics
            or set(state.get('files',{}))!=set(FILE_HASHES)|{'audio_head.safetensors'}):
        raise ValueError('Audio checkpoint, cursor, source or processor identity changed.')
    with staged_files({**state['files'],'optimizer.safetensors':state['adam'],'rng.safetensors':state['rng']},run.tenant_id,run.project_id):pass
    return {'config.json':state['pins']['config'],'source':SOURCE,'files':state['files'],
        'weights_manifest.json':{'weights_sha256':state['files']['audio_head.safetensors']['sha256'],
            'base_weights_sha256':state['files']['model.safetensors']['sha256']},
        'processor_config.json':{'source':SOURCE,'profile':PROCESSOR,'processor_id':state['pins']['processor_id']},
        'provenance.json':{'run_id':str(run.run_id),'tenant_id':str(run.tenant_id),'project_id':str(run.project_id),
            'step':checkpoint.step,'pins':state['pins']},'production_qualified':False}


def _authorized_budget(run):
    from modelanvil.budgets.models import BudgetReservation,BudgetPolicy
    reservation=BudgetReservation.all_objects.filter(tenant_id=run.tenant_id,job_id=run.job.job_id,
        reservation_id=run.resource_reservation_id,state='reserved').first()
    policy=BudgetPolicy.all_objects.select_for_update().filter(pk=reservation.policy_id,tenant_id=run.tenant_id).first() if reservation else None
    period,committed=BudgetReservation.current_commitment(policy) if policy else (None,None)
    if (policy is None or not policy.enabled or policy.unit!='training_steps' or policy.currency or reservation.period_start!=period
            or reservation.estimated_amount!=run.total_steps or committed>policy.limit_amount):
        raise ValueError('Audio training budget is no longer authorized.')


def _current_inputs(run):
    from modelanvil.identity.models import Tenant
    from modelanvil.runners.models import RunnerManifest
    if (run.job.project_id!=run.project_id or run.job.pool_id!=run.pool_id
            or run.job.payload!={'type':'qualified_training','run_id':str(run.run_id)}
            or not Tenant.objects.filter(pk=run.tenant_id,status='active').exists()):
        raise ValueError('Audio job, project, pool or current tenant differs from its pinned run.')
    runner=RunnerManifest.all_objects.filter(tenant_id=run.tenant_id,manifest_id=run.hardware_config['pins']['runner_id']).first()
    inputs=resolve_inputs(dataset=run.dataset_revision,base=run.base_model_version,tokenizer=run.tokenizer_version,
        runner=runner,pool=run.pool,tenant=run.tenant_id,project=run.project_id,steps=run.total_steps,
        recipe_type=run.recipe_type,initialization_seed=run.initialization_seed,require_capacity=False)
    if inputs['pins']!=run.hardware_config['pins']:raise ValueError('Audio source, dataset, code, processor or worker changed after launch.')
    _authorized_budget(run)
    return inputs


def _validation(model,processor,voice,rows,run):
    import torch
    total,frames=0.,0
    with torch.random.fork_rng(),torch.no_grad():
        torch.manual_seed(42)
        for sample in rows:
            encoded=audio_data.materialize(sample,processor,run.tenant_id,run.project_id)
            value=float(math.loss(model,encoded,voice))
            if not scalar_math.isfinite(value):raise ValueError('Audio validation loss is non-finite.')
            total+=value*sample['mel_frames'];frames+=sample['mel_frames']
    return {'loss':total/frames,'prediction_frames':frames,'samples':len(rows)}


def execute_training(run,context):
    import gc,time,torch
    from django.utils import timezone
    from safetensors.torch import load_file,save_file
    from modelanvil.device_admission import device_lease
    from modelanvil.runners.models import TrainingRun,TrainingCheckpoint
    from modelanvil.runners.training.runtime import _locked_live_run
    from modelanvil.runners.alignment.torch_rlhf import apply_update
    previous_threads=torch.get_num_threads();torch.set_num_threads(1)
    model=optimizer=loss=voice=None;trainable=[]
    try:
        with transaction.atomic():
            locked=_locked_live_run(context,run.run_id);inputs=_current_inputs(locked)
            if locked.started_at is None:
                locked.started_at,locked.status=timezone.now(),TrainingRun.Status.RUNNING
                locked.save(update_fields=['started_at','status','updated_at'])
        latest=run.checkpoints.filter(is_valid=True).order_by('-step').first()
        if latest:checkpoint_bundle(run,latest)
        if (latest.step if latest else 0)!=run.current_step:raise ValueError('Audio checkpoint and committed cursor disagree.')
        files=latest.weights_manifest['files'] if latest else {n:r for n,r in inputs['bundle']['files'].items() if n in FILE_HASHES}
        recovery={**files,**({'optimizer.safetensors':latest.weights_manifest['adam'],'rng.safetensors':latest.weights_manifest['rng']} if latest else {})}
        with device_lease('cpu'),hf.deterministic_updates():
            try:
                with staged_files(recovery,run.tenant_id,run.project_id) as directory:
                    processor=math.processor(directory);voice=math.speaker(directory);model=math.load_model(directory,training=True)
                    trainable=[p for p in model.parameters() if p.requires_grad]
                    optimizer=torch.optim.AdamW(trainable,lr=OPTIMIZER['learning_rate'],betas=(.9,.999),eps=1e-8,weight_decay=0.,foreach=False)
                    if latest:
                        hf._restore_optimizer(model,optimizer,directory,latest.step)
                        rng=load_file(str(directory/'rng.safetensors'),device='cpu')
                        if set(rng)!={'cpu_rng_state'} or rng['cpu_rng_state'].dtype!=torch.uint8 or rng['cpu_rng_state'].shape!=torch.get_rng_state().shape:
                            raise ValueError('Audio checkpoint lacks compatible CPU dropout RNG state.')
                        torch.set_rng_state(rng['cpu_rng_state'])
                    else:torch.manual_seed(42)
                    before=_validation(model,processor,voice,inputs['validation_samples'],run)
                    baseline=latest.metrics['validation_loss_before_training'] if latest else before['loss']
                    for step in range(run.current_step+1,run.total_steps+1):
                        if not context.heartbeat(progress=(step-1)/run.total_steps):return
                        with transaction.atomic():
                            locked=_locked_live_run(context,run.run_id);_current_inputs(locked)
                        sample=inputs['samples'][hf.training_sample_index(step,len(inputs['samples']),inputs['pins'])]
                        encoded=audio_data.materialize(sample,processor,run.tenant_id,run.project_id)
                        cpu_started,wall_started=time.process_time(),time.perf_counter()
                        loss=math.loss(model,encoded,voice);metrics=apply_update(loss,model,optimizer,1.)
                        if str(loss.device)!='cpu' or any(p.grad is not None for p in model.parameters() if not p.requires_grad):
                            raise ValueError('Audio gradients escaped the declared CPU output-head scope.')
                        after=_validation(model,processor,voice,inputs['validation_samples'],run)
                        metrics.update(step=step,measured_at=timezone.now().isoformat(),sample_id=sample['sample_id'],
                            audio_sha256=sample['audio']['sha256'],normalized_audio_sha256=sample['audio']['normalized_sha256'],
                            loss_kind=PROCESSOR['loss'],training_pairs=sample['mel_frames'],prediction_mel_frames=sample['mel_frames'],
                            padded_mel_frames=sample['padded_mel_frames'],cpu_seconds=time.process_time()-cpu_started,
                            engine_wall_seconds=time.perf_counter()-wall_started,total_parameters=sum(p.numel() for p in model.parameters()),
                            validation_loss_before_training=baseline,validation_loss=after['loss'],validation_samples=after['samples'],
                            validation_prediction_frames=after['prediction_frames'],gpu_backend='cpu',gpu_device='cpu',
                            device_residency_checked=True,peak_allocated_bytes=None,peak_reserved_bytes=None,production_qualified=False)
                        metrics['prediction_frames_per_second']=sample['mel_frames']/metrics['engine_wall_seconds']
                        save_file({n:p.detach().cpu().contiguous() for n,p in model.named_parameters() if p.requires_grad},str(directory/'audio_head.safetensors'))
                        save_file(hf._optimizer_state(model,optimizer),str(directory/'optimizer.safetensors'))
                        save_file({'cpu_rng_state':torch.get_rng_state()},str(directory/'rng.safetensors'))
                        with transaction.atomic():
                            locked=_locked_live_run(context,run.run_id);_current_inputs(locked)
                            state={'run_id':str(run.run_id),'step':step,'pins':inputs['pins'],'metrics':metrics,
                                'files':{**{n:r for n,r in inputs['bundle']['files'].items() if n in FILE_HASHES},
                                    'audio_head.safetensors':hf._store_file(directory/'audio_head.safetensors',run,context,step)},
                                'adam':hf._store_file(directory/'optimizer.safetensors',run,context,step),
                                'rng':hf._store_file(directory/'rng.safetensors',run,context,step)}
                            TrainingCheckpoint.all_objects.create(tenant_id=run.tenant_id,training_run=locked,step=step,
                                state_digest=digest(state),weights_manifest=state,metrics=metrics)
                            locked.current_step,locked.latest_loss=step,metrics['loss'];locked.metrics_log=[*locked.metrics_log,metrics]
                            locked.save(update_fields=['current_step','latest_loss','metrics_log','updated_at']);run.current_step=step
            finally:
                # Drop tensors before releasing the physical admission and starting the independent CPU consumer.
                model=optimizer=loss=voice=None;trainable=[];gc.collect()
        evaluation=_independent_evaluation(run,context,inputs)
        with transaction.atomic():
            locked=_locked_live_run(context,run.run_id);_current_inputs(locked)
            locked.hardware_config={**locked.hardware_config,'independent_evaluation':evaluation}
            locked.save(update_fields=['hardware_config','updated_at'])
    except Exception:
        # Trusted finalization refuses missing checkpoints/evaluation; private transcripts never enter error egress.
        return
    finally:
        model=optimizer=loss=voice=None;trainable=[];gc.collect();torch.set_num_threads(previous_threads)


def finalize_job(job,status):
    from modelanvil.jobs.models import Job
    from modelanvil.runners.models import TrainingRun,TrainingCheckpoint
    from modelanvil.runners.training.runtime import _finalize_worker_job
    run=TrainingRun.all_objects.select_for_update().get(job=job,tenant_id=job.tenant_id)
    if status in (Job.Status.QUEUED,Job.Status.INTERRUPTED):return status
    if job.desired_action=='cancel':status=Job.Status.CANCELLED
    if status==Job.Status.SUCCEEDED:
        try:
            _current_inputs(run);checkpoint=run.checkpoints.get(step=run.total_steps,is_valid=True);checkpoint_bundle(run,checkpoint)
            evaluation=run.hardware_config.get('independent_evaluation',{})
            if (run.current_step!=run.total_steps or evaluation.get('status') not in ('completed','unavailable')
                    or type(evaluation.get('passed')) is not bool or evaluation.get('checkpoint_digest')!=checkpoint.state_digest):
                raise ValueError('Audio training has no complete independently evaluated candidate.')
        except (ValueError,TypeError,KeyError,OSError,TrainingCheckpoint.DoesNotExist):status=Job.Status.FAILED
    _finalize_worker_job(job,status,runtime_id=RUNTIME_ID,contract_digest=CONTRACT_DIGEST,model_name_prefix='speecht5-head',
        checkpoint_bundle=checkpoint_bundle,is_worker_run=is_worker_run,candidate_metadata={'model_role':'text_to_speech',
            'trained':True,'independent_evaluation_passed':run.hardware_config.get('independent_evaluation',{}).get('passed',False),
            'production_qualified':False})
    return status


def _independent_evaluation(run,context,inputs):
    import hashlib,io,json,os,subprocess,sys,time
    from modelanvil.device_admission import device_lease
    from modelanvil.runners.training.runtime import _locked_live_run
    from modelanvil.runners.model_catalog import _store
    checkpoint=run.checkpoints.get(step=run.total_steps,is_valid=True)
    bundle=checkpoint_bundle(run,checkpoint);cases=inputs['protected_test_samples']
    base_files={n:r for n,r in inputs['bundle']['files'].items() if n in FILE_HASHES}
    evaluator=inputs['pins']['evaluator_files']
    manifest={'source':SOURCE,'base_files':{n:r['sha256'] for n,r in base_files.items()},
        'candidate_files':{n:r['sha256'] for n,r in bundle['files'].items()},
        'evaluator_files':{n:r['sha256'] for n,r in evaluator.items()},
        'training_groups':sorted({s['source_group_id'] for s in inputs['samples']}),
        'training_speakers':sorted({s['speaker_id'] for s in inputs['samples']}),
        'training_audio_hashes':sorted({s['audio']['sha256'] for s in inputs['samples']}),
        'training_normalized_hashes':sorted({s['audio']['normalized_sha256'] for s in inputs['samples']}),'cases':[]}
    try:
        with device_lease('cpu',pass_descriptor=True) as descriptor,tempfile.TemporaryDirectory(prefix='modelanvil-audio-score-') as temp:
            root=Path(temp)
            for i,sample in enumerate(cases):
                filename=f'case-{i}.'+('wav' if sample['audio']['media_type']=='audio/wav' else 'flac')
                with (root/filename).open('wb') as output:copy_verified(sample['audio']['artifact'],run.tenant_id,run.project_id,output)
                manifest['cases'].append({k:sample[k] for k in ('sample_id','source_group_id','speaker_id','text')})
                manifest['cases'][-1].update(audio_filename=filename,audio_sha256=sample['audio']['sha256'],
                    normalized_sha256=sample['audio']['normalized_sha256'],media_type=sample['audio']['media_type'])
            raw=json.dumps(manifest,sort_keys=True,allow_nan=False).encode();(root/'manifest.json').write_bytes(raw)
            with staged_files(base_files,run.tenant_id,run.project_id) as base,staged_files(bundle['files'],run.tenant_id,run.project_id) as candidate,staged_files(evaluator,run.tenant_id,run.project_id) as evaluator_dir:
                script=Path(__file__).resolve().parents[3]/'scripts/score_audio_candidate.py'
                command=[sys.executable,'-I',str(script),'--base',str(base),'--candidate',str(candidate),
                    '--evaluator',str(evaluator_dir/'evaluator'),'--manifest',str(root/'manifest.json')]
                env={'PATH':os.environ.get('PATH',''),'HOME':str(root),'HF_HOME':str(root/'hub'),'HF_HUB_OFFLINE':'1',
                    'TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
                    'VECLIB_MAXIMUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'}
                with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
                    child=subprocess.Popen(command,stdout=stdout,stderr=stderr,env=env,pass_fds=(descriptor,));deadline=time.monotonic()+150
                    try:
                        while child.poll() is None:
                            if not context.heartbeat(progress=1.):raise ValueError('Audio scoring lost its claim.')
                            with transaction.atomic():
                                locked=_locked_live_run(context,run.run_id);_authorized_budget(locked)
                                for ref in [*bundle['files'].values(),*evaluator.values(),*[s['audio']['artifact'] for s in cases]]:
                                    verified_artifact(ref,run.tenant_id,run.project_id)
                            if time.monotonic()>deadline:raise ValueError('Independent audio scoring timed out.')
                            time.sleep(.25)
                        if child.returncode:raise ValueError('Independent audio scoring did not complete.')
                        stdout.seek(0);output=stdout.read(256*1024+1)
                        if len(output)>256*1024:raise ValueError('Independent audio report exceeds its limit.')
                        report=json.loads(output)
                    finally:
                        if child.poll() is None:child.kill()
                        child.wait()
            if (report.get('schema_version')!='modelanvil.independent-audio-evaluation.v1'
                    or report.get('manifest_sha256')!=hashlib.sha256(raw).hexdigest()
                    or report.get('file_sha256')!={k:manifest[k+'_files'] for k in ('base','candidate','evaluator')}
                    or report.get('audio_sha256')!={s['sample_id']:s['audio']['sha256'] for s in cases}
                    or report.get('normalized_sha256')!={s['sample_id']:s['audio']['normalized_sha256'] for s in cases}
                    or report.get('consumer_imported_modelanvil_or_django') is not False
                    or set(report.get('checks',{}))!={'tts_natural_stop','tts_loss_within_ten_percent','asr_proxy_wer_at_most_half','asr_proxy_wer_not_regressed'}
                    or any(type(v) is not bool for v in report['checks'].values()) or type(report.get('passed')) is not bool
                    or report['passed']!=all(report['checks'].values())):
                raise ValueError('Independent audio report does not bind the exact head, processor, sources and evaluator.')
            with transaction.atomic():
                locked=_locked_live_run(context,run.run_id);_current_inputs(locked)
                for label in ('baseline','candidate'):
                    for i,row in enumerate(report[label]['cases']):
                        if row['wave_filename']!=f'{label}-{i}.wav':raise ValueError('Independent audio output filename changed.')
                        path=root/row['wave_filename']
                        if not 0<path.stat().st_size<=200000:raise ValueError('Independent audio example exceeds its limit.')
                        wave=path.read_bytes();math.decode_audio(wave,'audio/wav')
                        if hashlib.sha256(wave).hexdigest()!=row['wave_sha256']:raise ValueError('Independent audio example checksum changed.')
                        row['audio_artifact']=_store(io.BytesIO(wave),tenant=run.tenant_id,project=run.project_id,
                            name=f'{label}-{i}.wav',media_type='audio/wav',metadata={'kind':'audio_quality_example','run_id':str(run.run_id)})
            return {'status':'completed','passed':report['passed'],'report':report,'checkpoint_digest':checkpoint.state_digest,'production_qualified':False}
    except (ValueError,OSError):
        return {'status':'unavailable','passed':False,'checkpoint_digest':checkpoint.state_digest,
            'reason':'Independent CPU audio scoring unavailable; qualification blocked.','production_qualified':False}


def verify_external_loadable(bundle):
    import gc
    from modelanvil.device_admission import device_lease
    provenance=bundle['provenance.json'];model=None
    with device_lease('cpu'),staged_files(bundle['files'],provenance['tenant_id'],provenance['project_id']) as directory:
        try:
            model=math.load_model(directory);vocoder=math.load_vocoder(directory);processor=math.processor(directory);math.speaker(directory)
            count=sum(p.numel() for p in model.parameters())
        finally:model=vocoder=processor=None;gc.collect()
    return {'is_loadable':True,'format':'speecht5_head_safetensors','model_instantiated':True,'parameters':count,
        'weights_sha256':bundle['weights_manifest.json']['weights_sha256'],'verification_scope':'local_cpu_exact_speech_head_processor_vocoder_reload',
        'independent_runtime_verified':False,'production_qualified':False}
