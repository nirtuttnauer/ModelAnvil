"""Recoverable trusted-operator CPU exports; HTTP only serves committed archives."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from django.conf import settings
from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.identity.models import check_resource_access
from modelanvil.device_admission import device_lease
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training import cpu_hf_runtime, hf_runtime
from modelanvil.runners.training.registry import runtime_for_run
from modelanvil.runners.training.runtime import digest

PROFILE = 'modelanvil.cpu-export.v1'
LLAMA_COMMIT = 'f5027fb21307eb264aed483242603d68c87b0fe3'
FORMATS = {'merged': 'Merged Safetensors (ZIP)', 'gguf-q8': 'CPU GGUF Q8_0 (ZIP)'}
MAX_ARCHIVE_BYTES = 2 * 1024**3


def pin(path):
    sha, size = hashlib.sha256(), 0
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > MAX_ARCHIVE_BYTES:
                raise ValueError('CPU export exceeds the 2 GiB bound.')
            sha.update(block)
    return {'sha256': sha.hexdigest(), 'byte_size': size}


def source_bundle(run):
    run.refresh_from_db()
    if (runtime_for_run(run) is not cpu_hf_runtime or run.status != 'completed' or not run.job_id
            or run.job.status != 'succeeded' or not run.output_model_version_id):
        raise ValueError('Select a completed actual pretrained CPU worker run.')
    for resource in (run, run.output_model_version, run.base_model_version, run.tokenizer_version, run.dataset_revision):
        if not check_resource_access(resource, run.project_id, run.tenant_id):
            raise ValueError('Export inputs are no longer accessible in this project.')
    if run.output_model_version.state in ('archived', 'rejected') or run.base_model_version.state in ('archived', 'rejected'):
        raise ValueError('Export model or base is no longer available.')
    from modelanvil.runners.inference import snapshot_guard
    guards = [snapshot_guard(model, run.tenant_id, run.project_id) for model in (run.base_model_version, run.output_model_version)]
    if (run.dataset_revision.state != 'published' or run.dataset_revision.manifest_digest != run.dataset_manifest_digest):
        raise ValueError('The pinned training dataset is no longer current.')
    step = run.output_model_version.metadata.get('selected_checkpoint_step', run.total_steps)
    bundle = cpu_hf_runtime.checkpoint_bundle(run, run.checkpoints.get(step=step))
    if bundle['source'] != hf_runtime.SOURCE:
        raise ValueError('CPU exports require the exact pinned SmolLM2-135M source.')
    bundle['input_identities'] = [guard.identity for guard in guards]
    return bundle


def export_records(run):
    if not getattr(run, 'pk', None):
        return Artifact.all_objects.none()
    return Artifact.all_objects.filter(tenant_id=run.tenant_id, project_id=run.project_id,
        state='committed', metadata__cpu_export__profile=PROFILE,
        metadata__cpu_export__run_id=str(run.run_id)).order_by('created_at')


def open_export(run, selected_format, *, artifact_id=None):
    bundle = source_bundle(run)
    records = export_records(run).filter(metadata__cpu_export__format=selected_format, metadata__cpu_export__source_digest=digest(bundle))
    record = (records.filter(artifact_id=artifact_id) if artifact_id else records.order_by('-created_at')).first()
    if not record or DeletionTombstone.all_objects.filter(tenant_id=run.tenant_id, resource_id=str(record.artifact_id)).exists():
        raise ValueError('Prepare a current verified CPU export before downloading.')
    backend = artifact_storage_backend()
    # Check bytes before returning a stream; corrupt or partial storage is never a download.
    result = tempfile.TemporaryFile()
    sha, size = hashlib.sha256(), 0
    try:
        with backend.open(run.tenant_id, record.object_key) as source:
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > min(record.byte_size, MAX_ARCHIVE_BYTES):
                    raise ValueError('Export bytes exceed their committed size.')
                sha.update(block); result.write(block)
        if size != record.byte_size or sha.hexdigest() != record.sha256:
            raise ValueError('Export bytes no longer match their immutable identity.')
        result.seek(0)
        return record, result
    except BaseException:
        result.close()
        raise


def _run(args, *, cwd=None, timeout=300, descriptor=None):
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'SYSTEMROOT', 'TMPDIR', 'LANG', 'LC_ALL'}}
    env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', TOKENIZERS_PARALLELISM='false')
    command = [sys.executable, str(Path(__file__).with_name('cpu_export_process.py')), str(timeout), *map(str, args)]
    result = subprocess.run(command, cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=timeout + 5, check=False,
                            pass_fds=() if descriptor is None else (descriptor,))
    if result.returncode or len(result.stdout) > 1024**2 or len(result.stderr) > 4 * 1024**2:
        raise ValueError('Offline CPU export subprocess failed; no archive was published.')
    return result.stdout


def tools():
    config = getattr(settings, 'MODELANVIL_CPU_EXPORT_TOOLS', {})
    try:
        source = Path(config['source']).resolve()
        if _run(['git', '-C', source, 'rev-parse', 'HEAD']).strip() != LLAMA_COMMIT:
            raise ValueError('CPU export converter revision changed.')
        _run(['git', '-C', source, 'diff', '--quiet', 'HEAD', '--'])
        values = {'source': source}
        for key in ('quantize', 'cli'):
            path = Path(config[key]['path']).resolve()
            if pin(path)['sha256'] != config[key]['sha256'] or not os.access(path, os.X_OK):
                raise ValueError('CPU export binary checksum changed.')
            values[key] = path
        return values
    except (KeyError, TypeError, OSError):
        raise ValueError('Install and checksum the pinned CPU-only llama.cpp export tools first.') from None


def _save(path, value):
    temp = path.with_suffix('.pending')
    with temp.open('w') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


@contextmanager
def _work(run, request_digest):
    import fcntl
    backend = artifact_storage_backend()
    if not hasattr(backend, 'root'):
        raise ValueError('CPU export recovery requires local artifact storage.')
    root = backend.root / '.cpu-export-work'
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError('CPU export work directory must be private and owned by this account.')
    directory = root / str(run.tenant_id) / request_digest
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor = os.open(directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('This export is already being prepared.') from None
        if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError('Export work directory escapes its private root.')
        yield directory
    finally:
        os.close(descriptor)


def prepare(run, selected_format):
    if selected_format not in FORMATS:
        raise ValueError('Select merged or gguf-q8.')
    bundle = source_bundle(run)
    cpu_hf_runtime.require_packages()
    installed = tools() if selected_format == 'gguf-q8' else None
    request = {'profile': PROFILE, 'run_id': str(run.run_id), 'format': selected_format,
               'source_digest': digest(bundle), 'worker_sha256': pin(Path(__file__).with_name('cpu_export_worker.py'))['sha256'],
               'process_sha256': pin(Path(__file__).with_name('cpu_export_process.py'))['sha256'],
               'implementation_sha256': pin(__file__)['sha256'], 'llama_commit': LLAMA_COMMIT if selected_format == 'gguf-q8' else None,
               'tool_sha256': {name: pin(installed[name])['sha256'] for name in ('quantize', 'cli')} if installed else {}}
    key = digest(request)
    with _work(run, key) as directory, device_lease('cpu', pass_descriptor=True) as descriptor:
        existing = export_records(run).filter(metadata__cpu_export__request_digest=key).first()
        if existing:
            record, stream = open_export(run, selected_format, artifact_id=existing.artifact_id); stream.close()
            return record
        receipt_path = directory / 'receipt.json'
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {'request': request, 'phases': {}}
        if receipt['request'] != request:
            raise ValueError('Export recovery request changed.')
        def phase(name, build):
            target = directory / name
            saved = receipt['phases'].get(name)
            if saved:
                if any(pin(target / file) != value for file, value in saved['files'].items()):
                    raise ValueError('A completed export phase changed; restore its verified bytes.')
                return target, saved['verification']
            # Incomplete phase files are private, unpublished and safe to rebuild.
            if target.exists(): shutil.rmtree(target)
            target.mkdir()
            verification = build(target)
            files = {p.name: pin(p) for p in sorted(target.iterdir()) if p.is_file()}
            if not files or len(files) > 16:
                raise ValueError('Incomplete or oversized export phase.')
            receipt['phases'][name] = {'files': files, 'verification': verification}
            _save(receipt_path, receipt)
            return target, verification
        def merge(target):
            with cpu_hf_runtime.staged_files(bundle['files'], run.tenant_id, run.project_id) as source:
                result = json.loads(_run([sys.executable, Path(__file__).with_name('cpu_export_worker.py'), source, target], descriptor=descriptor))
                shutil.copyfile(Path(__file__).parent / 'assets' / 'Apache-2.0.txt', target / 'LICENSE.txt')
                (target / 'NOTICE.txt').write_text('Source: https://huggingface.co/' + bundle['source']['repo_id'] + '\nRevision: ' + bundle['source']['revision'] + '\nLicense: Apache-2.0. Derived weights from the recorded ModelAnvil training run.\n')
                return result
        merged, verification = phase('merged', merge)
        selected = merged
        if selected_format == 'gguf-q8':
            def convert(target):
                f16 = target / 'baseline-f16.gguf'
                _run([sys.executable, installed['source'] / 'convert_hf_to_gguf.py', merged,
                      '--outfile', f16, '--outtype', 'f16'], descriptor=descriptor)
                output = target / 'model-q8_0.gguf'
                _run([installed['quantize'], f16, output, 'Q8_0', '1'], descriptor=descriptor)
                from modelanvil.runners.gguf_validation import validate_gguf
                structural = validate_gguf(output)
                import gguf
                reader = gguf.GGUFReader(output)
                if reader.fields['general.file_type'].contents() != int(gguf.LlamaFileType.MOSTLY_Q8_0) or not any(t.tensor_type == gguf.GGMLQuantizationType.Q8_0 for t in reader.tensors):
                    raise ValueError('Converter did not produce the qualified Q8_0 tensor format.')
                structural['tensor_types'] = sorted({str(t.tensor_type.name) for t in reader.tensors})
                del reader
                text = _run([installed['cli'], '-m', output, '-ngl', '0', '-t', '1', '-c', '128',
                             '-n', '8', '--seed', '42', '--temp', '0', '--no-warmup', '--no-conversation',
                             '--no-display-prompt', '-p', 'A telescope collects'], descriptor=descriptor)
                if not text.strip(): raise ValueError('The exported GGUF produced no decoded output.')
                shutil.copyfile(Path(__file__).parent / 'assets' / 'Apache-2.0.txt', target / 'LICENSE.txt')
                f16.unlink()
                return {'structure': structural, 'runtime': 'independent llama.cpp completion CLI', 'decoded_output': text,
                        'converter_revision': LLAMA_COMMIT, 'quantization': 'Q8_0', 'device': 'cpu'}
            selected, verification = phase('gguf', convert)
        if digest(source_bundle(run)) != request['source_digest']:
            raise ValueError('Export source changed during conversion; publication refused.')
        metadata = {**request, 'request_digest': key, 'files': dict(receipt['phases']['gguf' if selected_format == 'gguf-q8' else 'merged']['files']),
                    'verification': verification, 'source': bundle['source'], 'production_qualified': False,
                    'quality_gate': {'state': 'not_evaluated', 'reason': 'Format loadability is separate from held-out quality and release qualification.'}}
        if selected_format == 'gguf-q8':
            for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'NOTICE.txt'):
                if (merged / name).exists(): metadata['files'][name] = pin(merged / name)
        output = directory / 'export.zip'
        if not receipt.get('archive'):
            temporary = directory / 'export.pending'
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                files = dict(metadata['files'])
                if selected_format == 'gguf-q8':
                    for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'NOTICE.txt'):
                        if (merged / name).exists(): files[name] = pin(merged / name)
                for name in sorted(files):
                    path = selected / name if (selected / name).exists() else merged / name
                    with path.open('rb') as source, archive.open(zipfile.ZipInfo(name, (1980,1,1,0,0,0)), 'w', force_zip64=True) as target:
                        shutil.copyfileobj(source, target, 1024 * 1024)
                archive.writestr(zipfile.ZipInfo('modelanvil-provenance.json', (1980,1,1,0,0,0)),
                    json.dumps({'export': metadata, 'training': bundle}, sort_keys=True, allow_nan=False))
            os.replace(temporary, output)
            receipt['archive'] = pin(output); _save(receipt_path, receipt)
        if pin(output) != receipt['archive']:
            raise ValueError('Recovered archive checksum changed.')
        # Storage commit is atomic. A killed upload leaves a staging record, reused on retry.
        record = Artifact.all_objects.filter(tenant_id=run.tenant_id, project_id=run.project_id,
                    metadata__cpu_export__request_digest=key).first()
        if not record:
            record = Artifact.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id,
                storage_location_id='local', object_key=f'cpu-exports/{key}/export.zip',
                **receipt['archive'], media_type='application/zip', metadata={'cpu_export': metadata})
        if record.state != 'committed':
            try:
                with output.open('rb') as stream: upload_staged_artifact(record, stream)
            except FileExistsError:
                # A process may die after atomic object storage but before the DB commit.
                with artifact_storage_backend().open(run.tenant_id, record.object_key) as stored, tempfile.NamedTemporaryFile() as recovered:
                    shutil.copyfileobj(stored, recovered, 1024 * 1024); recovered.flush()
                    if pin(recovered.name) != receipt['archive']:
                        raise ValueError('Staged upload bytes differ from the immutable archive.')
                record.mark_verified(verified_sha256=record.sha256, verified_size=record.byte_size)
        return record
