"""Durable general transformer SFT runtime (pure-Python CPU reference).

This is the second registered training runtime contract. It executes the real
decoder-only transformer in :mod:`modelanvil.runners.training.general_transformer`
through the same fenced worker path as the character runtime:

- published dataset rows are byte-encoded with the pinned byte tokenizer,
- the base bundle supplies the transformer configuration and initial tensors,
- gradients are analytic (:mod:`modelanvil.runners.training.autograd`) and applied
  with AdamW, with the optimizer moments persisted in every checkpoint so recovery
  from a committed checkpoint is exact,
- every checkpoint reuses the repository's Safetensors codec.

Support envelope (honest, by construction): CPU-only, single process, small models.
No GPU, distributed, remote-worker or provider support.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import time

from modelanvil.artifacts.models import Artifact
from modelanvil.runners.training.engine import pack_safetensors, unpack_safetensors
from modelanvil.runners.training.general_transformer import (
    GENERAL_RUNTIME_ID,
    AdamW,
    ByteTokenizer,
    GeneralTransformer,
)
from modelanvil.runners.training.runtime import _locked_live_run, read_artifact
from modelanvil.runners.training.runtime import digest as _digest

RUNTIME_ID = GENERAL_RUNTIME_ID
LIMITS = {
    'vocab_size': 260, 'n_layer': 4, 'n_head': 4, 'n_embd': 32, 'context_window': 64,
    'rows': 1000, 'steps': 1000, 'input_bytes': 2 * 1024 * 1024, 'memory_bytes': 512 * 1024 * 1024,
}
CONTRACT = {
    'runtime': RUNTIME_ID, 'recipe': 'full_sft', 'precision': 'fp32_state_float64_compute',
    'optimizer': 'adamw', 'tokenizer': 'byte-v1', 'limits': LIMITS,
}
CONTRACT_DIGEST = hashlib.sha256(json.dumps(CONTRACT, sort_keys=True).encode()).hexdigest()

OPTIMIZER = {'algorithm': 'adamw', 'learning_rate': 0.01, 'beta1': 0.9, 'beta2': 0.999, 'weight_decay': 0.0}


def digest(value):
    return _digest(value)


def runner_manifest():
    return {
        'schema_version': '1.0', 'adapter_id': RUNTIME_ID, 'version': '1', 'platform_api': 'v1',
        'image': f'local-python-contract@sha256:{CONTRACT_DIGEST}', 'license': 'local reference; license not asserted',
        'capabilities': [{
            'kind': 'train', 'input_schema_refs': ['urn:modelanvil:schema:sample-envelope:1.0'],
            'output_schema_refs': ['safetensors:F32'], 'formats': ['text'], 'architectures': [RUNTIME_ID],
            'recovery': 'verified_checkpoint',
        }],
        'resources': {'cpu_cores': 1, 'memory_bytes': LIMITS['memory_bytes'], 'gpu_count': 0,
                      'disk_bytes': 32 * 1024 * 1024, 'distributed': False},
        'permissions': {'network_hosts': [], 'artifact_access': ['read_job_inputs', 'write_attempt_staging'], 'secret_kinds': []},
        'dependencies': [], 'limitations': [
            'Pure-Python CPU reference; no GPU, distributed or remote-worker support.',
            'Intended for small models and tests, not production throughput.',
        ],
    }


def build_digest():
    from pathlib import Path
    root = Path(__file__).parent
    names = ['engine.py', 'runtime.py', 'general_runtime.py', 'options.py', 'general_transformer.py', 'autograd.py', 'executor.py']
    return hashlib.sha256(b''.join((root / name).read_bytes() for name in names)).hexdigest()


def capable_worker(worker):
    from modelanvil.jobs.setup import setup_worker_ready
    caps = worker.capabilities
    return (isinstance(caps, dict) and setup_worker_ready(worker) and caps.get('training_runtime') == CONTRACT_DIGEST
            and type(caps.get('memory_bytes')) is int and caps['memory_bytes'] >= LIMITS['memory_bytes'])


def tokenizer_spec(tokenizer):
    spec = (tokenizer.compatibility or {}).get('byte_v1')
    if not isinstance(spec, dict):
        raise ValueError('Register a byte-v1 tokenizer (compatibility.byte_v1).')
    if tokenizer.vocabulary_size != LIMITS['vocab_size']:
        raise ValueError('A byte-v1 tokenizer must declare a 260-token vocabulary.')
    if tokenizer.chat_template:
        raise ValueError('The byte-v1 reference tokenizer does not accept a chat template.')
    return {'kind': 'byte-v1', 'vocab_size': LIMITS['vocab_size'], 'pad_id': 0, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}


def encode(text, spec, *, enforce_limit=True):
    ids = ByteTokenizer().encode(text)
    if enforce_limit and len(ids) > LIMITS['context_window']:
        raise ValueError(
            f'A training sample exceeds {LIMITS["context_window"]} encoded byte tokens; prepare shorter text samples.')
    return ids


def _config_from_bundle(bundle):
    cfg = bundle.get('config.json', {})
    dimensions = [cfg.get('vocab_size'), cfg.get('n_layer'), cfg.get('n_head'), cfg.get('n_embd'), cfg.get('context_window')]
    if any(type(n) is not int or n <= 0 for n in dimensions):
        raise ValueError('Missing or invalid transformer dimensions in the base bundle.')
    vocab, layers, heads, width, context = dimensions
    if (vocab != LIMITS['vocab_size'] or layers > LIMITS['n_layer'] or heads > LIMITS['n_head']
            or width > LIMITS['n_embd'] or context > LIMITS['context_window'] or width % heads != 0):
        raise ValueError('Base transformer configuration exceeds the bounded CPU runtime envelope.')
    return cfg


def _load_general_export_model(bundle):
    """Load and fully verify a general transformer bundle from Safetensors tensors."""
    encoded = bundle.get('model.safetensors.b64')
    if not isinstance(encoded, str) or len(encoded) > 64 * 1024 * 1024:
        raise ValueError('Export requires bounded model.safetensors.b64 weights.')
    raw = base64.b64decode(encoded, validate=True)
    computed = hashlib.sha256(raw).hexdigest()
    if bundle.get('weights_manifest.json', {}).get('weights_sha256') != computed:
        raise ValueError('Safetensors SHA-256 verification failed or missing manifest digest.')
    cfg = _config_from_bundle(bundle)
    model = GeneralTransformer(
        vocab_size=cfg['vocab_size'], n_layer=cfg['n_layer'], n_head=cfg['n_head'],
        n_embd=cfg['n_embd'], context_window=cfg['context_window'], seed=1,
    )
    tensors = unpack_safetensors(raw)
    if set(tensors) != set(model.tensors):
        raise ValueError('Export is missing required transformer tensors or has unsupported tensors.')
    for name, (shape, values) in tensors.items():
        rows, cols = len(model.tensors[name]), len(model.tensors[name][0])
        if list(shape) != [rows, cols] or len(values) != rows * cols:
            raise ValueError(f'Invalid tensor shape or byte count: {name}.')
        if not all(math.isfinite(v) for v in values):
            raise ValueError(f'Non-finite tensor values: {name}.')
    model.import_tensors(tensors)
    return model, computed


def verify_external_loadable(bundle):
    """Instantiate the exported transformer and run one bounded inference (local smoke check)."""
    model, computed = _load_general_export_model(bundle)
    logits = model.forward_logits([1, 2])
    if len(logits[-1]) != model.vocab_size or not all(math.isfinite(v.data) for v in logits[-1]):
        raise ValueError('Exported model inference produced invalid logits.')
    return {
        'is_loadable': True, 'format': 'safetensors', 'num_tensors': len(model.tensors),
        'weights_sha256': computed, 'vocab_size': model.vocab_size, 'model_instantiated': True,
        'inference_steps': 1, 'predicted_token_id': max(range(model.vocab_size), key=lambda i: logits[-1][i].data),
        'verification_scope': 'local_modelanvil_general_transformer_runtime',
        'independent_runtime_verified': False, 'production_qualified': False,
    }


def generate_candidate_completion(bundle, prompt, max_new_tokens=8, heartbeat=None):
    """Bounded greedy byte-level decoding; the byte tokenizer decodes back to text."""
    if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 32:
        raise ValueError('max_new_tokens must be between 1 and 32.')
    if not isinstance(prompt, str) or len(prompt) > 4096:
        raise ValueError('Prompt must be text up to 4096 characters.')
    model, computed = _load_general_export_model(bundle)
    tokenizer = ByteTokenizer()
    context = list(tokenizer.encode(prompt))
    context = context[-model.context_window:]
    generated = []
    for _ in range(max_new_tokens):
        if heartbeat is not None and not heartbeat():
            raise ValueError('CPU transformer inference lost its lease or was cancelled.')
        logits = model.forward_logits(context)[-1]
        if not all(math.isfinite(v.data) for v in logits):
            raise ValueError('Non-finite inference logits.')
        next_id = max([2, *range(4, model.vocab_size)], key=lambda i: logits[i].data)
        generated.append(next_id)
        context = [*context, next_id][-model.context_window:]
        if next_id == 2:
            break
    return {
        'is_verified': True, 'prompt': prompt, 'generated_token_ids': generated,
        'generated_tokens': [f'byte:{t}' for t in generated], 'completion': tokenizer.decode(generated),
        'weights_sha256': computed, 'verification_scope': 'local_general_transformer_runtime',
        'decoded_text': True, 'production_qualified': False,
    }


def resolve_inputs(*, dataset, base, tokenizer, runner, pool, tenant, project, steps, require_capacity=True, hyperparameters=None):
    from modelanvil.artifacts.models import DatasetRevision
    from modelanvil.runners.training.options import cpu_options, validation_sequences
    from modelanvil.identity.models import check_resource_access
    from modelanvil.jobs.models import Worker
    if not all([dataset, base, tokenizer, runner, pool]):
        raise ValueError('Select a published dataset, base weights, tokenizer, qualified runner and worker pool.')
    for resource in [dataset, base, tokenizer, runner, pool]:
        if not check_resource_access(resource, project, tenant):
            raise ValueError('Referenced resource is unavailable in this project.')
    if type(steps) is not int or not 1 <= steps <= LIMITS['steps']:
        raise ValueError('The general transformer recipe supports 1–1000 optimizer steps.')
    if dataset.state != DatasetRevision.State.PUBLISHED or not dataset.manifest_artifact_id:
        raise ValueError('Publish the prepared text dataset with a committed manifest artifact.')
    raw = read_artifact(dataset.manifest_artifact, tenant, project)
    if hashlib.sha256(raw).hexdigest() != dataset.manifest_digest:
        raise ValueError('Dataset manifest digest changed; republish the dataset.')
    prepared = json.loads(raw)
    if not isinstance(prepared, dict):
        raise ValueError('Prepared manifest must be an object.')
    split_manifest = prepared.get('split_manifest', {})
    if not isinstance(split_manifest, dict):
        raise ValueError('Prepared manifest must declare an object split_manifest.')
    train_ids = split_manifest.get('train', [])
    rows = prepared.get('rows', [])
    if (not isinstance(rows, list) or not 1 <= len(rows) <= LIMITS['rows']
            or not isinstance(train_ids, list) or not train_ids):
        raise ValueError('Prepare 1–1000 text rows with a nonempty training split.')
    excluded = {name: ids for name, ids in sorted(split_manifest.items()) if name != 'train'}
    if any(not isinstance(ids, list) for ids in excluded.values()):
        raise ValueError('Every prepared split must be a list of sample identifiers.')
    held_out = [sample_id for ids in excluded.values() for sample_id in ids]
    overlap = sorted(set(train_ids) & set(held_out))
    if overlap:
        raise ValueError(
            f'Protected split contamination: {len(overlap)} sample(s) appear in both train and a '
            'held-out split; republish the dataset.')
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
        if not text:
            raise ValueError('Training text must be nonempty.')
        ids = encode(text, spec)
        encoded.append(ids)
        samples.append({'sample_id': row['sample_id'], 'text': text, 'token_ids': ids})
    if not encoded or set(train_ids) - seen or len(set(train_ids)) != len(train_ids):
        raise ValueError('No training samples resolve from the published split.')
    if set(held_out) - seen:
        raise ValueError(
            'Published held-out splits reference samples absent from the manifest; republish the dataset.')
    if str(base.tokenizer_id) != str(tokenizer.pk):
        raise ValueError('Select the tokenizer pinned by the base model.')
    try:
        artifact = Artifact.all_objects.get(tenant_id=tenant, artifact_id=base.artifact_manifest_id)
    except (Artifact.DoesNotExist, ValueError):
        raise ValueError('Base model requires a committed transformer export bundle artifact.') from None
    base_raw = read_artifact(artifact, tenant, project)
    bundle = json.loads(base_raw)
    cfg = _config_from_bundle(bundle)
    if base.architecture_ref != RUNTIME_ID or cfg.get('vocab_size') != tokenizer.vocabulary_size or bundle.get('tokenizer_config.json') != spec:
        raise ValueError('Base weights/config/tokenizer do not match the general transformer runtime.')
    if any(len(sequence) > cfg['context_window'] for sequence in encoded):
        raise ValueError(
            f'Training text exceeds the pinned model context of {cfg["context_window"]} encoded byte tokens '
            '(including BOS/EOS); prepare shorter text samples.')
    _load_general_export_model(bundle)
    if (not runner.enabled or runner.compatibility.get('contract_digest') != CONTRACT_DIGEST
            or runner.manifest != runner_manifest()
            or runner.digest != digest(runner.manifest)):
        raise ValueError('Select an enabled runner manifest for the verified general transformer contract.')
    if (pool.status != 'active' and (require_capacity or pool.status != 'draining')):
        raise ValueError('Activate the selected worker pool.')
    eligible = Worker.all_objects.filter(tenant_id=tenant, pool=pool, slots__gte=1,
        status__in=[Worker.Status.AVAILABLE, Worker.Status.BUSY])
    if require_capacity and not any(capable_worker(w) for w in eligible):
        raise ValueError('Register an available CPU worker with this runtime contract and at least 512 MiB RAM.')
    pinned_config = {**cfg, 'runtime': RUNTIME_ID}
    optimizer, validation_interval = cpu_options(hyperparameters, OPTIMIZER)
    validation = validation_sequences(prepared, encode, spec, samples, validation_interval, cfg['context_window'])
    pins = {
        'runtime': RUNTIME_ID, 'contract_digest': CONTRACT_DIGEST, 'dataset_id': str(dataset.revision_id),
        'build_digest': build_digest(), 'dataset_digest': dataset.manifest_digest,
        'base_id': str(base.model_version_id), 'base_artifact_id': str(artifact.artifact_id),
        'base_digest': hashlib.sha256(base_raw).hexdigest(), 'tokenizer_id': str(tokenizer.tokenizer_id),
        'tokenizer_digest': digest(spec), 'runner_id': str(runner.manifest_id), 'runner_digest': runner.digest,
        'pool_id': pool.pk, 'steps': steps, 'config': pinned_config, 'optimizer': optimizer,
        'sample_digest': digest(samples), 'validation': {'interval': validation_interval, 'digest': digest(validation)},
        'splits': {'consumed': 'train', 'train_rows': len(encoded),
                   'excluded_rows': {name: len(ids) for name, ids in excluded.items()},
                   'excluded_digest': digest(sorted(held_out))},
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
    _load_general_export_model(bundle)
    return bundle


def execute_training(run, context):
    """Numerical work outside locks; each publication rechecks the live fence."""
    from django.db import transaction
    from django.utils import timezone
    from modelanvil.runners.models import RunnerManifest, TrainingCheckpoint, TrainingRun
    pins = run.hardware_config['pins']
    runner = RunnerManifest.all_objects.get(manifest_id=pins['runner_id'], tenant_id=run.tenant_id)
    inputs = resolve_inputs(dataset=run.dataset_revision, base=run.base_model_version,
        tokenizer=run.tokenizer_version, runner=runner, pool=run.pool, tenant=run.tenant_id,
        project=run.project_id, steps=run.total_steps, require_capacity=False, hyperparameters=run.hyperparameters)
    if inputs['pins'] != pins or run.recipe_type != 'full_sft':
        raise ValueError('Pinned inputs changed since launch; create a new run.')
    if not capable_worker(context.attempt.worker):
        raise ValueError('Claimed worker does not meet the general transformer runtime requirements.')
    latest = run.checkpoints.order_by('-step').first()
    if latest and latest.step != run.current_step or run.current_step and latest is None:
        raise ValueError('Committed training cursor lacks a matching checkpoint.')
    bundle = checkpoint_bundle(run, latest) if latest else inputs['bundle']
    model, _ = _load_general_export_model(bundle)
    opt = pins['optimizer']
    optimizer = AdamW(model.parameters(), learning_rate=opt['learning_rate'], beta1=opt['beta1'],
                      beta2=opt['beta2'], weight_decay=opt['weight_decay'])
    if latest:
        moments = latest.weights_manifest.get('adam')
        if moments:
            optimizer._m = list(moments['m'])
            optimizer._v = list(moments['v'])
            optimizer._t = moments['t']
    start = latest.step if latest else 0
    for step in range(start + 1, run.total_steps + 1):
        if not context.heartbeat(progress=(step - 1) / run.total_steps):
            return
        sequence = inputs['sequences'][(step - 1) % len(inputs['sequences'])]
        started = time.process_time()
        wall_started = time.perf_counter()
        optimizer.zero_grad()
        loss_value = model.loss(sequence)
        loss = loss_value.data
        loss_value.backward()
        optimizer.step()
        raw, weights = pack_safetensors(model.export_tensors())
        # Canonical float32 state at every boundary gives exact recovery parity.
        model.import_tensors(unpack_safetensors(raw))
        post_loss = model.loss(sequence).data
        metrics = {'step': step, 'loss': loss, 'post_update_loss': post_loss,
                   'training_pairs': len(sequence) - 1, 'cpu_seconds': time.process_time() - started,
                   'engine_wall_seconds': time.perf_counter() - wall_started,
                   'sample_id': inputs['samples'][(step - 1) % len(inputs['samples'])]['sample_id']}
        from modelanvil.runners.training.options import validation_metrics
        metrics.update(validation_metrics(inputs['validation_sequences'], pins['validation']['interval'], step, run.total_steps, lambda sequence: model.loss(sequence).data))
        metrics['cpu_seconds'] = time.process_time() - started
        metrics['engine_wall_seconds'] = time.perf_counter() - wall_started
        state = {'run_id': str(run.run_id), 'step': step, 'pins': pins,
                 'optimizer': {**pins['optimizer'], 'updates': step}, 'tokenizer': inputs['tokenizer'],
                 'weights': weights, 'data_b64': base64.b64encode(raw).decode(), 'metrics': metrics,
                 'adam': {'m': optimizer._m, 'v': optimizer._v, 't': optimizer._t},
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


def finalize_job(job, status):
    """Called under the durable job fence transaction, including terminal recovery."""
    from modelanvil.runners.training.runtime import _finalize_worker_job
    return _finalize_worker_job(
        job, status, runtime_id=RUNTIME_ID, contract_digest=CONTRACT_DIGEST,
        model_name_prefix='general-sft', checkpoint_bundle=checkpoint_bundle, is_worker_run=is_worker_run,
    )
