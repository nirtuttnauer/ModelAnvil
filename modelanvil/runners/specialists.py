"""Curated, immutable OCR and typed-decision snapshots and isolated inference."""
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import os
import subprocess
import tempfile
import time

from django.conf import settings
from modelanvil.device_admission import device_lease
from modelanvil.runners.inference import copy_verified, staged_snapshot, verified_artifact
from modelanvil.runners.training.runtime import digest

PINS = json.loads(Path(__file__).with_name('specialist_pins.json').read_text())
RUNTIME = Path(__file__).resolve().parents[2] / 'scripts' / 'specialist_runtime.py'


def import_plan(kind):
    if kind not in PINS:
        raise ValueError('Select ocr or laya.')
    pin = PINS[kind]
    return {**pin, 'format': kind, 'byte_size': sum(f['byte_size'] for f in pin['files'].values()),
            'gated': False, 'training_supported': False}


def check_files(files, kind):
    expected = PINS[kind]['files']
    if not isinstance(files, dict) or set(files) != set(expected):
        raise ValueError('Use the complete pinned specialist snapshot.')
    if any(not isinstance(ref, dict) or {k: ref.get(k) for k in ('sha256', 'byte_size')} != expected[n]
           for n, ref in files.items()):
        raise ValueError('Specialist bytes differ from the qualified snapshot pins.')


def publish_specialist(files, *, tenant, project, name, kind, license_expression):
    from modelanvil.runners.model_catalog import _store
    from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion
    pin = PINS[kind]
    if license_expression != pin['license']:
        raise ValueError('Confirm the pinned model license.')
    check_files(files, kind)
    with staged_snapshot(files, tenant, project) as directory:
        tokenizer = json.loads((directory / ('tokenizer/tokenizer.json' if kind == 'laya' else 'tokenizer.json')).read_text())
        vocab = max([*tokenizer['model']['vocab'].values(), *(t['id'] for t in tokenizer.get('added_tokens', []))]) + 1
    source = {k: pin[k] for k in ('repo_id', 'revision', 'license')}
    manifest = {'source': source, 'files': files, 'format': kind}
    ref = _store(io.BytesIO(json.dumps(manifest, sort_keys=True).encode()), tenant=tenant, project=project, name='snapshot.json')
    tok = TokenizerVersion.all_objects.create(tenant_id=tenant, project_id=project,
        name=f'{name} tokenizer', vocabulary_size=vocab, artifact_manifest_id=ref['artifact_id'],
        configuration_digest=digest(files), compatibility={'model_snapshot': source, 'immutable_import': True})
    logical = Model.all_objects.create(tenant_id=tenant, project_id=project, name=name, intended_tasks=[pin['task']])
    return ModelVersion.all_objects.create(tenant_id=tenant, project_id=project, model=logical, tokenizer=tok,
        architecture_ref=f'modelanvil.{kind}.v1', artifact_manifest_id=ref['artifact_id'],
        parameters_count=pin['parameters_count'], license_evidence=license_expression,
        metadata={'source': source, 'snapshot_manifest': ref, 'format': kind, 'imported': True,
                  'configuration': {'model_type': kind}, 'license_expression': license_expression})


def snapshot(version, tenant, project, kind):
    from modelanvil.identity.models import check_resource_access
    if (version.architecture_ref != f'modelanvil.{kind}.v1'
            or version.state in {'archived', 'rejected'}
            or not check_resource_access(version, project, tenant)
            or not check_resource_access(version.tokenizer, project, tenant)):
        raise ValueError('Select an accessible specialist model of the requested kind.')
    ref = version.metadata.get('snapshot_manifest')
    if not ref or str(ref.get('artifact_id')) != version.artifact_manifest_id:
        raise ValueError('Specialist snapshot manifest is unavailable.')
    if verified_artifact(ref, tenant, project).byte_size > 1024 * 1024:
        raise ValueError('Specialist manifest exceeds its size limit.')
    out = io.BytesIO(); copy_verified(ref, tenant, project, out)
    value = json.loads(out.getvalue())
    if value.get('source') != {k: PINS[kind][k] for k in ('repo_id', 'revision', 'license')} or value.get('format') != kind:
        raise ValueError('Specialist manifest identity changed.')
    check_files(value.get('files'), kind)
    return value


def execute(version, *, tenant, project, kind, device, inputs, image=None):
    from scripts.specialist_runtime import validate_decision, validate_ocr
    if kind == 'laya':
        validate_decision(inputs)
    else:
        validate_ocr(inputs)
    if device not in (['cpu', 'mps:0'] if kind == 'laya' else ['mlx:0']):
        raise ValueError('Choose an explicitly supported specialist device.')
    python = getattr(settings, 'MODELANVIL_SPECIALIST_PYTHON', None) or os.environ.get('MODELANVIL_SPECIALIST_PYTHON')
    if not python or not Path(python).is_absolute() or not Path(python).is_file():
        raise ValueError('Install the isolated specialist runtime and configure MODELANVIL_SPECIALIST_PYTHON.')
    plan = snapshot(version, tenant, project, kind)
    started = time.monotonic()
    with ExitStack() as stack:
        stack.enter_context(device_lease(device))
        directory = stack.enter_context(staged_snapshot(plan['files'], tenant, project))
        work = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='modelanvil-specialist-')))
        if kind == 'ocr':
            if image is None or image.byte_size > 8 * 1024**2:
                raise ValueError('Select an accessible PNG or JPEG of at most 8 MiB.')
            from modelanvil.runners.training.hf_runtime import file_ref
            with (work / 'image').open('wb') as target:
                copy_verified(file_ref(image), tenant, project, target)
        request = {'kind': kind, 'device': device, 'directory': str(directory), 'inputs': inputs,
                   'image': str(work / 'image') if image else None}
        env = {'PATH': os.defpath, 'HOME': str(work), 'TMPDIR': str(work), 'HF_HOME': str(work / 'hf'),
               'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
               'USE_TF': '0', 'PYTORCH_ENABLE_MPS_FALLBACK': '0', 'TOKENIZERS_PARALLELISM': 'false'}
        with (work / 'out').open('w+b') as stdout, (work / 'err').open('w+b') as stderr:
            try:
                result = subprocess.run([python, '-I', str(RUNTIME)], input=json.dumps(request, allow_nan=False).encode(),
                    cwd=work, env=env, stdout=stdout, stderr=stderr, timeout=120)
            except subprocess.TimeoutExpired:
                raise ValueError('Specialist request exceeded 120 seconds; the runtime was terminated.') from None
            stdout.seek(0)
            raw = stdout.read(2 * 1024**2 + 1)
            if len(raw) > 2 * 1024**2:
                raise ValueError('Specialist output exceeds its byte limit.')
            try:
                output = json.loads(raw)
            except ValueError:
                raise ValueError('Specialist runtime failed; check the pinned dependencies and device capacity.') from None
            if result.returncode or output.get('error'):
                raise ValueError(output.get('error', 'Specialist runtime failed.'))
    output.update(elapsed_seconds=round(time.monotonic() - started, 4),
                  provenance={'source': plan['source'], 'snapshot_sha256': version.metadata['snapshot_manifest']['sha256'],
                              'files': {n: {k: r[k] for k in ('sha256', 'byte_size')} for n, r in plan['files'].items()}})
    return output
