"""Import the selected local SmolLM2 snapshot and publish operator-supplied text."""
import hashlib
import io
import json
from pathlib import Path
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from modelanvil.artifacts.models import Artifact, Dataset
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import Project
from modelanvil.jobs.models import Worker, WorkerPool
from modelanvil.runners.models import Model, ModelVersion, RunnerManifest, TokenizerVersion
from modelanvil.runners.training import hf_runtime as runtime
from modelanvil.runners.training.hardware import total_memory_bytes


class Command(BaseCommand):
    help = 'Import verified local SmolLM2 files, publish canonical text JSONL and register one dedicated GPU worker. Does not launch training or download models.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=uuid.UUID, required=True)
        parser.add_argument('--project-id', type=uuid.UUID, required=True)
        parser.add_argument('--name', required=True)
        parser.add_argument('--model-dir', type=Path, required=True)
        parser.add_argument('--samples', type=Path, required=True, help='Canonical text sample-envelope JSONL')
        parser.add_argument('--device', required=True, help='Explicit cuda:N, rocm:N, xpu:N or mps:0')
        parser.add_argument('--steps', type=int, default=3)

    @transaction.atomic
    def handle(self, *args, **options):
        tenant, project, name = options['tenant_id'], options['project_id'], options['name'].strip()
        if not name or len(name) > 80 or not 1 <= options['steps'] <= runtime.LIMITS['steps']:
            raise CommandError('Use a unique 1–80 character name and 1–1000 steps.')
        if not Project.all_objects.filter(pk=project, tenant_id=tenant).exists():
            raise CommandError('Select a project belonging to the tenant.')
        if Model.all_objects.filter(tenant_id=tenant, name=f'{name}-base').exists():
            raise CommandError('Model name already exists; use a new name.')
        runtime.require_packages()
        observed = runtime.observed_device(options['device'])
        memory = total_memory_bytes()
        if memory is None or memory < runtime.LIMITS['memory_bytes']:
            raise CommandError('Host memory is unknown or below 8 GiB.')
        directory = options['model_dir']
        for filename, expected in runtime.FILE_HASHES.items():
            path = directory / filename
            try:
                maximum = runtime.LIMITS['weight_bytes'] if filename.endswith('.safetensors') else runtime.LIMITS['aux_bytes']
                if not 1 <= path.stat().st_size <= maximum:
                    raise CommandError(f'{filename}: exceeds the bounded snapshot size.')
                sha = hashlib.sha256()
                with path.open('rb') as stream:
                    while block := stream.read(1024 * 1024):
                        sha.update(block)
                if sha.hexdigest() != expected:
                    raise CommandError(f'{filename}: does not match the pinned SmolLM2 snapshot.')
            except OSError as exc:
                raise CommandError(f'{filename}: local snapshot file unavailable.') from exc
        with options['samples'].open('rb') as stream:
            samples = stream.read(1024**2 + 1)
        if not 1 <= len(samples) <= 1024**2:
            raise CommandError('Use 1 byte to 1 MiB of canonical sample-envelope JSONL.')
        backend = artifact_storage_backend()
        if not hasattr(backend, 'root'):
            raise CommandError('This GPU runtime requires shared local filesystem storage.')

        def store(path):
            sha = hashlib.sha256()
            with path.open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    sha.update(block)
            result = Artifact.all_objects.create(tenant_id=tenant, project_id=project,
                storage_location_id='local', object_key=f'gpu-input/{uuid.uuid4()}/{path.name}',
                sha256=sha.hexdigest(), byte_size=path.stat().st_size, media_type='application/octet-stream')
            with path.open('rb') as stream:
                upload_staged_artifact(result, stream, backend=backend)
            return result

        files = {filename: runtime.file_ref(store(directory / filename)) for filename in runtime.FILE_HASHES}
        payload = json.dumps({'source': runtime.SOURCE, 'files': files}, sort_keys=True).encode()
        manifest = Artifact.all_objects.create(tenant_id=tenant, project_id=project, storage_location_id='local',
            object_key=f'gpu-input/{uuid.uuid4()}/snapshot.json', sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload), media_type='application/json')
        upload_staged_artifact(manifest, io.BytesIO(payload), backend=backend)
        tokenizer = runtime._tokenizer(directory)
        tok = TokenizerVersion.all_objects.create(tenant_id=tenant, project_id=project, name=f'{name}-tokenizer',
            vocabulary_size=len(tokenizer), compatibility={'hf_snapshot': runtime.SOURCE},
            special_tokens={k: v for k, v in tokenizer.special_tokens_map.items() if isinstance(v, str)})
        model = Model.all_objects.create(tenant_id=tenant, project_id=project, name=f'{name}-base', intended_tasks=['text_generation'])
        base = ModelVersion.all_objects.create(tenant_id=tenant, project_id=project, model=model, revision_no=1,
            tokenizer=tok, architecture_ref=runtime.RUNTIME_ID, artifact_manifest_id=str(manifest.artifact_id),
            metadata={'snapshot_manifest': runtime.file_ref(manifest), 'vocab_size': len(tokenizer), 'source': runtime.SOURCE})
        dataset = Dataset.all_objects.create(tenant_id=tenant, project_id=project, name=f'{name}-data')
        source = Artifact.all_objects.create(tenant_id=tenant, project_id=project, storage_location_id='local',
            object_key=f'gpu-input/{uuid.uuid4()}/samples.jsonl', sha256=hashlib.sha256(samples).hexdigest(),
            byte_size=len(samples), media_type='application/x-ndjson')
        upload_staged_artifact(source, io.BytesIO(samples), backend=backend)
        revision = publish_prepared_dataset(dataset, source, validation_percent=20, test_percent=20)
        manifest_value = runtime.runner_manifest()
        runner = RunnerManifest.all_objects.create(tenant_id=tenant, name=f'{name}-runner', version='1',
            manifest=manifest_value, digest=runtime.digest(manifest_value), compatibility={'contract_digest': runtime.CONTRACT_DIGEST})
        pool = WorkerPool.all_objects.create(tenant_id=tenant, name=f'{name}-gpu', status='active')
        worker = Worker.all_objects.create(tenant_id=tenant, pool=pool, name=f'{name}-gpu', slots=1,
            capabilities={'training_runtime': runtime.CONTRACT_DIGEST, 'memory_bytes': memory,
                          'gpu_backend': observed['device']['backend'], 'gpu_device': observed['device']['id'],
                          'gpu_packages': runtime.PACKAGES})
        policy = BudgetPolicy.all_objects.create(tenant_id=tenant, name=f'{name}-steps', period='lifetime',
            unit='training_steps', limit_amount=options['steps'])
        runtime.resolve_inputs(dataset=revision, base=base, tokenizer=tok, runner=runner, pool=pool,
            tenant=tenant, project=project, steps=options['steps'])
        self.stdout.write(json.dumps({'worker_id': worker.pk, 'accelerator': observed, 'source': runtime.SOURCE,
            'launch': {'project': str(project), 'execution_mode': 'worker', 'recipe_type': 'full_sft',
                       'base_model_version': base.pk, 'tokenizer_version': tok.pk, 'dataset_revision': revision.pk,
                       'runner_manifest': runner.pk, 'pool': pool.pk, 'budget_policy_id': str(policy.policy_id),
                       'total_steps': options['steps']}}, indent=2))
