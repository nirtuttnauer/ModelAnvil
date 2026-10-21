"""Bounded CPU character SFT runtime: verified published text and base tensors."""
from __future__ import annotations

import hashlib
import json
from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.data.publication import _read_verified_input
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.training.engine import TrainingEngine

RUNTIME_ID = 'modelanvil.cpu-character-sft.v1'
LIMITS = {'vocab_size': 256, 'n_embd': 16, 'lora_r': 4, 'rows': 1000, 'sequence_tokens': 64,
          'steps': 1000, 'input_bytes': 1024 * 1024, 'memory_bytes': 256 * 1024 * 1024}
# The runtime contract is server-owned; an arbitrary registry "qualified" label is insufficient.
CONTRACT = {'runtime': RUNTIME_ID, 'recipe': 'full_sft', 'precision': 'fp32_state_float64_compute', 'optimizer': 'sgd',
            'tokenizer': 'character-v1', 'limits': LIMITS}
CONTRACT_DIGEST = hashlib.sha256(json.dumps(CONTRACT, sort_keys=True).encode()).hexdigest()


def runner_manifest():
    return {'schema_version': '1.0', 'adapter_id': RUNTIME_ID, 'version': '1', 'platform_api': 'v1',
        'image': f'local-python-contract@sha256:{CONTRACT_DIGEST}', 'license': 'local reference; license not asserted',
        'capabilities': [{'kind': 'train', 'input_schema_refs': ['urn:modelanvil:schema:sample-envelope:1.0'],
            'output_schema_refs': ['safetensors:F32'], 'formats': ['text'], 'architectures': [RUNTIME_ID],
            'recovery': 'verified_checkpoint'}],
        'resources': {'cpu_cores': 1, 'memory_bytes': LIMITS['memory_bytes'], 'gpu_count': 0,
                      'disk_bytes': 16 * 1024 * 1024, 'distributed': False},
        'permissions': {'network_hosts': [], 'artifact_access': ['read_job_inputs', 'write_attempt_staging'], 'secret_kinds': []},
        'dependencies': [], 'limitations': ['Trusted local Python executor; image field identifies the contract, not a published container.',
            'Single CPU character bigram model; no transformer context, chat, GPU or distributed support.']}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def build_digest():
    from pathlib import Path
    root = Path(__file__).parent
    return hashlib.sha256(b''.join((root / name).read_bytes() for name in ['engine.py', 'runtime.py', 'executor.py', 'options.py'])).hexdigest()


def capable_worker(worker):
    from modelanvil.jobs.setup import setup_worker_ready
    caps = worker.capabilities
    return (isinstance(caps, dict) and setup_worker_ready(worker) and caps.get('training_runtime') == CONTRACT_DIGEST
            and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes'])


def read_artifact(artifact, tenant, project):
    if (artifact is None or artifact.tenant_id != tenant or not check_resource_access(artifact, project, tenant)
            or artifact.state != Artifact.State.COMMITTED or artifact.storage_location_id != 'local'
            or artifact.object_version is not None or artifact.byte_size > LIMITS['input_bytes']):
        raise ValueError('Use a committed, accessible local artifact within the 1 MiB runtime limit.')
    if DeletionTombstone.all_objects.filter(tenant_id=tenant, resource_id=str(artifact.artifact_id)).exists():
        raise ValueError('Referenced artifact has been deleted; select an available revision.')
    return _read_verified_input(artifact, artifact_storage_backend())


def tokenizer_spec(tokenizer):
    spec = (tokenizer.compatibility or {}).get('character_v1')
    if not isinstance(spec, dict) or tokenizer.chat_template:
        raise ValueError('Register a character-v1 text tokenizer without a chat template.')
    tokens = spec.get('tokens')
    if (not isinstance(tokens, list) or not 10 <= len(tokens) <= LIMITS['vocab_size']
            or any(not isinstance(t, str) for t in tokens)
            or len(tokens) != tokenizer.vocabulary_size or len(set(tokens)) != len(tokens)
            or tokens[:4] != ['<pad>', '<bos>', '<eos>', '<unk>']
            or any(not isinstance(t, str) or len(t) != 1 for t in tokens[4:])):
        raise ValueError('Tokenizer needs a unique character vocabulary with pad/bos/eos/unk at IDs 0/1/2/3.')
    return {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}


def encode(text, spec):
    table = {t: i for i, t in enumerate(spec['tokens'])}
    ids = [1] + [table.get(char, 3) for char in text] + [2]
    if len(ids) > LIMITS['sequence_tokens']:
        raise ValueError('A training sample exceeds 64 encoded tokens; prepare shorter text samples.')
    return ids


def resolve_inputs(*, dataset, base, tokenizer, runner, pool, tenant, project, steps, require_capacity=True, hyperparameters=None):
    from modelanvil.artifacts.models import DatasetRevision
    from modelanvil.runners.training.options import cpu_options, validation_sequences
    from modelanvil.jobs.models import Worker
    if not all([dataset, base, tokenizer, runner, pool]):
        raise ValueError('Select a published dataset, base weights, tokenizer, qualified runner and worker pool.')
    for resource in [dataset, base, tokenizer, runner, pool]:
        if not check_resource_access(resource, project, tenant):
            raise ValueError('Referenced resource is unavailable in this project.')
    if type(steps) is not int or not 1 <= steps <= LIMITS['steps']:
        raise ValueError('The CPU recipe supports 1–1000 optimizer steps.')
    if dataset.state != DatasetRevision.State.PUBLISHED or not dataset.manifest_artifact_id:
        raise ValueError('Publish the prepared text dataset with a committed manifest artifact.')
    raw = read_artifact(dataset.manifest_artifact, tenant, project)
    if hashlib.sha256(raw).hexdigest() != dataset.manifest_digest:
        raise ValueError('Dataset manifest digest changed; republish the dataset.')
    prepared = json.loads(raw)
    if not isinstance(prepared, dict):
        raise ValueError('Prepared manifest must be an object.')
    train_ids = prepared.get('split_manifest', {}).get('train', [])
    rows = prepared.get('rows', [])
    if (not isinstance(rows, list) or not 1 <= len(rows) <= LIMITS['rows']
            or not isinstance(train_ids, list) or not train_ids):
        raise ValueError('Prepare 1–1000 text rows with a nonempty training split.')
    spec = tokenizer_spec(tokenizer)
    encoded = []
    samples = []
    from contracts import validate_envelope
    seen = set()
    for row in rows:
        try:
            validate_envelope(row)
        except Exception as exc:
            raise ValueError('Prepared rows must conform to canonical sample envelopes; republish the dataset.') from exc
        if row['sample_id'] in seen:
            raise ValueError('Prepared samples must have unique IDs.')
        seen.add(row['sample_id'])
        if row.get('sample_id') not in train_ids:
            continue
        blocks = row['blocks']
        if any(b['type'] != 'text' or b.get('role') for b in blocks):
            raise ValueError('This recipe accepts canonical text samples only; prepare a text-only dataset.')
        text = '\n'.join(b['text'] for b in blocks)
        if not text or any(char not in spec['tokens'] for char in text):
            raise ValueError('Training text must be nonempty and fully covered by the character vocabulary.')
        ids = encode(text, spec)
        encoded.append(ids)
        samples.append({'sample_id': row['sample_id'], 'text': text, 'token_ids': ids})
    if not encoded or set(train_ids) - seen or len(set(train_ids)) != len(train_ids):
        raise ValueError('No training samples resolve from the published split.')
    if str(base.tokenizer_id) != str(tokenizer.pk):
        raise ValueError('Select the tokenizer pinned by the base model.')
    try:
        artifact = Artifact.all_objects.get(tenant_id=tenant, artifact_id=base.artifact_manifest_id)
    except (Artifact.DoesNotExist, ValueError):
        raise ValueError('Base model requires a committed CPU export bundle artifact.') from None
    base_raw = read_artifact(artifact, tenant, project)
    bundle = json.loads(base_raw)
    cfg = bundle.get('config.json', {})
    if (base.architecture_ref != RUNTIME_ID or cfg.get('vocab_size') != tokenizer.vocabulary_size
            or not 1 <= cfg.get('n_embd', 0) <= LIMITS['n_embd']
            or not 1 <= cfg.get('lora_r', 0) <= LIMITS['lora_r']
            or bundle.get('tokenizer_config.json') != spec):
        raise ValueError('Base weights/config/tokenizer do not match the bounded CPU runtime.')
    TrainingEngine.verify_external_loadable(bundle)
    if (not runner.enabled or runner.compatibility.get('contract_digest') != CONTRACT_DIGEST
            or runner.manifest != runner_manifest()
            or runner.digest != digest(runner.manifest)):
        raise ValueError('Select an enabled runner manifest for the verified CPU contract.')
    if (pool.status != 'active' and (require_capacity or pool.status != 'draining')):
        raise ValueError('Activate the selected worker pool.')
    eligible = Worker.all_objects.filter(tenant_id=tenant, pool=pool, slots__gte=1,
        status__in=[Worker.Status.AVAILABLE, Worker.Status.BUSY])
    if require_capacity and not any(capable_worker(w) for w in eligible):
        raise ValueError('Register an available CPU worker with this runtime contract and at least 256 MiB RAM.')
    optimizer, validation_interval = cpu_options(hyperparameters, {'algorithm': 'sgd', 'learning_rate': 0.05, 'momentum': 0})
    validation = validation_sequences(prepared, encode, spec, samples, validation_interval, LIMITS['sequence_tokens'])
    pins = {
        'runtime': RUNTIME_ID, 'contract_digest': CONTRACT_DIGEST, 'dataset_id': str(dataset.revision_id),
        'build_digest': build_digest(),
        'dataset_digest': dataset.manifest_digest, 'base_id': str(base.model_version_id),
        'base_artifact_id': str(artifact.artifact_id), 'base_digest': hashlib.sha256(base_raw).hexdigest(),
        'tokenizer_id': str(tokenizer.tokenizer_id), 'tokenizer_digest': digest(spec),
        'runner_id': str(runner.manifest_id), 'runner_digest': runner.digest,
        'pool_id': pool.pk, 'steps': steps, 'config': cfg, 'optimizer': optimizer,
        'sample_digest': digest(samples), 'validation': {'interval': validation_interval, 'digest': digest(validation)},
    }
    return {'pins': pins, 'bundle': bundle, 'tokenizer': spec, 'samples': samples, 'sequences': encoded, 'validation_sequences': validation}


def is_worker_run(run):
    return run.hardware_config.get('execution_mode') == 'worker'


def checkpoint_bundle(run, checkpoint):
    """Verify the complete recovery state before loading any tensors."""
    state = checkpoint.weights_manifest
    if (not checkpoint.is_valid or digest(state) != checkpoint.state_digest
            or state.get('pins') != run.hardware_config['pins']
            or state.get('step') != checkpoint.step or state.get('run_id') != str(run.run_id)
            or state.get('optimizer') != {**state['pins']['optimizer'], 'updates': checkpoint.step}
            or state.get('metrics') != checkpoint.metrics):
        raise ValueError('Checkpoint state checksum or pinned optimizer provenance changed.')
    bundle = {'config.json': state['pins']['config'], 'weights_manifest.json': state['weights'],
              'model.safetensors.b64': state['data_b64'], 'tokenizer_config.json': state['tokenizer'],
              'provenance.json': {'run_id': str(run.run_id), 'pins': state['pins'],
                                  'step': checkpoint.step, 'state_digest': checkpoint.state_digest}}
    TrainingEngine.verify_external_loadable(bundle)
    return bundle


def _locked_live_run(context, run_id):
    from django.utils import timezone
    from modelanvil.jobs.models import Job, JobAttempt
    from modelanvil.runners.models import TrainingRun
    attempt = JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job = Job.all_objects.select_for_update().get(pk=attempt.job_id)
    if (attempt.status != JobAttempt.Status.RUNNING or attempt.fencing_token != context.fencing_token
            or not attempt.lease_expires_at or attempt.lease_expires_at <= timezone.now()
            or job.fencing_token != context.fencing_token or job.status != Job.Status.RUNNING
            or job.claimed_by_id != attempt.worker_id):
        context.lease_lost = True
        raise ValueError('Worker lease is stale; checkpoint publication refused.')
    if job.desired_action == Job.DesiredAction.CANCEL:
        context.cancel_requested = True
        raise ValueError('Cancellation requested; checkpoint publication refused.')
    run = TrainingRun.all_objects.select_for_update().get(run_id=run_id, tenant_id=job.tenant_id, job=job)
    if run.status not in (TrainingRun.Status.PENDING, TrainingRun.Status.RUNNING):
        raise ValueError('Run is no longer executable.')
    return run


def execute_training(run, context):
    """Numerical work outside locks; each publication rechecks the live fence."""
    import base64
    import time
    from django.db import transaction
    from django.utils import timezone
    from modelanvil.runners.models import RunnerManifest, TrainingCheckpoint, TrainingRun
    from modelanvil.runners.training.engine import pack_safetensors, unpack_safetensors
    pins = run.hardware_config['pins']
    runner = RunnerManifest.all_objects.get(manifest_id=pins['runner_id'], tenant_id=run.tenant_id)
    inputs = resolve_inputs(dataset=run.dataset_revision, base=run.base_model_version,
        tokenizer=run.tokenizer_version, runner=runner, pool=run.pool, tenant=run.tenant_id,
        project=run.project_id, steps=run.total_steps, require_capacity=False, hyperparameters=run.hyperparameters)
    if inputs['pins'] != pins or run.recipe_type != 'full_sft':
        raise ValueError('Pinned inputs changed since launch; create a new run.')
    if not capable_worker(context.attempt.worker):
        raise ValueError('Claimed worker does not meet the CPU runtime requirements.')
    latest = run.checkpoints.order_by('-step').first()
    if latest and latest.step != run.current_step or run.current_step and latest is None:
        raise ValueError('Committed training cursor lacks a matching checkpoint.')
    bundle = checkpoint_bundle(run, latest) if latest else inputs['bundle']
    model, _ = TrainingEngine._load_export_model(bundle)
    start = latest.step if latest else 0
    for step in range(start + 1, run.total_steps + 1):
        if not context.heartbeat(progress=(step - 1) / run.total_steps):
            return
        sequence = inputs['sequences'][(step - 1) % len(inputs['sequences'])]
        started = time.process_time()
        wall_started = time.perf_counter()
        loss = model.compute_loss_and_step(sequence, pins['optimizer']['learning_rate'])
        raw, weights = pack_safetensors(model.export_tensors())
        # Canonical float32 state at every boundary gives exact recovery parity.
        model.import_tensors(unpack_safetensors(raw))
        post_loss = model.compute_loss(sequence)
        metrics = {'step': step, 'loss': loss, 'post_update_loss': post_loss,
                   'training_pairs': len(sequence) - 1, 'cpu_seconds': time.process_time() - started,
                   'engine_wall_seconds': time.perf_counter() - wall_started,
                   'sample_id': inputs['samples'][(step - 1) % len(inputs['samples'])]['sample_id']}
        from modelanvil.runners.training.options import validation_metrics
        metrics.update(validation_metrics(inputs['validation_sequences'], pins['validation']['interval'], step, run.total_steps, model.compute_loss))
        metrics['cpu_seconds'] = time.process_time() - started
        metrics['engine_wall_seconds'] = time.perf_counter() - wall_started
        state = {'run_id': str(run.run_id), 'step': step, 'pins': pins,
                 'optimizer': {**pins['optimizer'], 'updates': step}, 'tokenizer': inputs['tokenizer'],
                 'weights': weights, 'data_b64': base64.b64encode(raw).decode(), 'metrics': metrics,
                 'attempt_id': str(context.attempt.attempt_id), 'fencing_token': context.fencing_token}
        with transaction.atomic():
            locked = _locked_live_run(context, run.run_id)
            if locked.current_step != step - 1:
                raise ValueError('Training cursor changed; checkpoint publication refused.')
            TrainingCheckpoint.all_objects.create(tenant_id=run.tenant_id, training_run=locked,
                step=step, state_digest=digest(state), weights_manifest=state, metrics=metrics)
            locked.current_step, locked.latest_loss = step, loss
            locked.metrics_log = [*locked.metrics_log, metrics]
            locked.status = TrainingRun.Status.RUNNING
            locked.started_at = locked.started_at or timezone.now()
            locked.save(update_fields=['current_step', 'latest_loss', 'metrics_log', 'status', 'started_at', 'updated_at'])


def _finalize_worker_job(job, status, *, runtime_id, contract_digest, model_name_prefix,
                         checkpoint_bundle, is_worker_run, select_checkpoint=None):
    """Shared terminal accounting and candidate creation for any worker runtime."""
    import io
    from django.utils import timezone
    from modelanvil.artifacts.storage import upload_staged_artifact
    from modelanvil.budgets.models import BudgetReservation, UsageEvent
    from modelanvil.runners.models import Model, ModelVersion, TrainingRun
    from modelanvil.jobs.models import Job
    run = TrainingRun.all_objects.select_for_update().get(job=job, tenant_id=job.tenant_id)
    if not is_worker_run(run):
        return
    if status == Job.Status.SUCCEEDED:
        if run.current_step != run.total_steps:
            raise ValueError('Worker cannot declare success before all checkpointed steps complete.')
        checkpoint = select_checkpoint(run) if select_checkpoint else run.checkpoints.get(step=run.current_step)
        bundle = checkpoint_bundle(run, checkpoint)
        payload = json.dumps(bundle, sort_keys=True, allow_nan=False).encode()
        artifact = Artifact.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
            storage_location_id='local', object_key=f'training/{run.run_id}/candidate.json',
            sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
        upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
        model = Model.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
            name=f'{model_name_prefix}-{run.run_id}', intended_tasks=['text_generation'])
        run.output_model_version = ModelVersion.all_objects.create(tenant_id=run.tenant_id,
            project_id=run.project_id, model=model, revision_no=1, tokenizer=run.tokenizer_version,
            architecture_ref=runtime_id, artifact_manifest_id=str(artifact.artifact_id),
            state=ModelVersion.State.DRAFT, metadata={'source_run_id': str(run.run_id),
                'selected_checkpoint_step': checkpoint.step,
                'weights_sha256': bundle['weights_manifest.json']['weights_sha256'],
                'runtime_contract': contract_digest, 'checkpoint_digest': checkpoint.state_digest})
        run.status = TrainingRun.Status.COMPLETED
    else:
        run.status = TrainingRun.Status.CANCELLED if job.desired_action == Job.DesiredAction.CANCEL else TrainingRun.Status.FAILED
    reservation = BudgetReservation.all_objects.get(tenant_id=run.tenant_id,
        reservation_id=run.resource_reservation_id, job_id=job.job_id)
    committed_steps = run.current_step - run.hardware_config.get('recovery', {}).get('start_step', 0)
    reservation.settle(committed_steps)
    UsageEvent.record(tenant_id=run.tenant_id, provider_event_key=f'training:{run.run_id}',
        quantity=committed_steps, unit='training_steps', reservation=reservation,
        detail={'runtime': runtime_id, 'cpu_seconds': sum(m['cpu_seconds'] for m in run.metrics_log),
                'training_pairs': sum(m['training_pairs'] for m in run.metrics_log), 'status': run.status})
    run.completed_at = timezone.now()
    run.save(update_fields=['status', 'output_model_version', 'completed_at', 'updated_at'])


def finalize_job(job, status):
    """Called under the durable job fence transaction, including terminal recovery."""
    return _finalize_worker_job(
        job, status, runtime_id=RUNTIME_ID, contract_digest=CONTRACT_DIGEST,
        model_name_prefix='cpu-sft', checkpoint_bundle=checkpoint_bundle, is_worker_run=is_worker_run,
    )
