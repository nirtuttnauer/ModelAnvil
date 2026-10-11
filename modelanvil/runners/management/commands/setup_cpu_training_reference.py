"""Install explicit local CPU reference prerequisites without starting compute."""
import base64
import hashlib
import io
import json
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
from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
from modelanvil.runners.training.runtime import CONTRACT_DIGEST, LIMITS, RUNTIME_ID, digest, runner_manifest


class Command(BaseCommand):
    help = 'Create an explicit CPU character reference base, dataset, runner, pool, worker and step budget. Does not launch training.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=uuid.UUID, required=True)
        parser.add_argument('--project-id', type=uuid.UUID, required=True)
        parser.add_argument('--name', required=True, help='Unique prefix for new reference resources.')

    @transaction.atomic
    def handle(self, *args, **options):
        tenant, project, name = options['tenant_id'], options['project_id'], options['name'].strip()
        if not name or len(name) > 80:
            raise CommandError('Name must contain 1–80 characters.')
        if not Project.all_objects.filter(pk=project, tenant_id=tenant).exists():
            raise CommandError('Select a project belonging to the tenant.')
        if Model.all_objects.filter(tenant_id=tenant, name=f'{name}-base').exists():
            raise CommandError('Reference name already exists; choose a new name.')
        backend = artifact_storage_backend()
        if not hasattr(backend, 'root'):
            raise CommandError('CPU reference requires local filesystem artifact storage.')
        def artifact(raw, media):
            result = Artifact.all_objects.create(tenant_id=tenant, project_id=project, storage_location_id='local',
                object_key=f'cpu-reference/{uuid.uuid4()}', sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw), media_type=media)
            upload_staged_artifact(result, io.BytesIO(raw), backend=backend)
            return result
        tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdefghijklmnopqrstuvwxyz .\n')]
        spec = {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}
        tokenizer = TokenizerVersion.all_objects.create(tenant_id=tenant, project_id=project, name=f'{name}-tokenizer',
            vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
        initial = CausalTextModel(len(tokens), n_embd=8, lora_r=2, lora_alpha=4, seed=123)
        raw, weights = pack_safetensors(initial.export_tensors())
        bundle = {'config.json': {'vocab_size': len(tokens), 'n_embd': 8, 'lora_r': 2, 'lora_alpha': 4},
            'tokenizer_config.json': spec, 'model.safetensors.b64': base64.b64encode(raw).decode(), 'weights_manifest.json': weights}
        base_artifact = artifact(json.dumps(bundle).encode(), 'application/json')
        model = Model.all_objects.create(tenant_id=tenant, project_id=project, name=f'{name}-base', intended_tasks=['text_generation'])
        base = ModelVersion.all_objects.create(tenant_id=tenant, project_id=project, model=model, revision_no=1,
            tokenizer=tokenizer, architecture_ref=RUNTIME_ID, artifact_manifest_id=str(base_artifact.artifact_id),
            metadata={'initialization': 'random numerical base; not a pretrained language model', 'seed': 123})
        rows = []
        for index, text in enumerate(['a small training example.', 'another text sample.']):
            rows.append({'schema_version': '1.0', 'sample_id': str(uuid.uuid4()), 'source_group_id': str(index),
                'blocks': [{'block_id': 'text', 'type': 'text', 'text': text}],
                'provenance': {'source_snapshot_ref': 'cpu-reference', 'source_record_key': str(index),
                               'content_sha256': hashlib.sha256(text.encode()).hexdigest()}})
        source = artifact(b''.join(json.dumps(row).encode() + b'\n' for row in rows), 'application/x-ndjson')
        dataset = Dataset.all_objects.create(tenant_id=tenant, project_id=project, name=f'{name}-text')
        revision = publish_prepared_dataset(dataset, source, validation_percent=0, test_percent=0)
        manifest = runner_manifest()
        runner = RunnerManifest.all_objects.create(tenant_id=tenant, name=f'{name}-runner', version='1',
            manifest=manifest, digest=digest(manifest), compatibility={'contract_digest': CONTRACT_DIGEST})
        pool = WorkerPool.all_objects.create(tenant_id=tenant, name=f'{name}-pool', queue_name=f'{name}-cpu', status='active')
        worker = Worker.all_objects.create(tenant_id=tenant, pool=pool, name=f'{name}-worker', slots=1,
            capabilities={'training_runtime': CONTRACT_DIGEST, 'memory_bytes': LIMITS['memory_bytes']})
        policy = BudgetPolicy.all_objects.create(tenant_id=tenant, name=f'{name}-steps', period='lifetime', unit='training_steps', limit_amount=1000)
        self.stdout.write(json.dumps({'worker_id': worker.pk, 'launch': {'project': str(project), 'execution_mode': 'worker',
            'recipe_type': 'full_sft', 'base_model_version': base.pk, 'tokenizer_version': tokenizer.pk,
            'dataset_revision': revision.pk, 'runner_manifest': runner.pk, 'pool': pool.pk,
            'budget_policy_id': str(policy.policy_id), 'total_steps': 20}}, indent=2))
