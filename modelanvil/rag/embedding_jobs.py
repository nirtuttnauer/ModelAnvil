"""Fenced, resumable vector builds over an existing immutable token index."""
import hashlib
from pathlib import Path

from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.models import IdempotencyKey
from modelanvil.identity.models import check_resource_access
from modelanvil.jobs.models import Job, JobAttempt, Worker, OutboxEvent, dispatch_topic
from modelanvil.jobs.setup import local_capacity_available
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.rag import embedding_adapter as adapter
from modelanvil.rag.models import ChunkEmbedding, EmbeddingBuild, EmbeddingSpace, IndexVersion, KnowledgeBase
from modelanvil.rag.retrieval import RetrievalEngine
from modelanvil.runners.training.runtime import digest

TYPE = 'embedding_build'
UNIT = 'embedding_attempts'
MAX_ATTEMPTS = 3
MEMORY_BYTES = adapter.MEMORY_BYTES
# Captured once in each process: an old worker cannot advertise newly edited code.
BUILD_DIGEST = digest([hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,adapter.__file__,
    Path(adapter.__file__).with_name('embedding-pins.json'),Path(adapter.__file__).with_name('embedding_candidates.py'),Path(__file__).parents[2]/'requirements.embeddings.txt']])


def runtime_digest():
    return digest({'code':BUILD_DIGEST,'environment':adapter.environment(),'profile':adapter.PINS})


def space_pins(space,project_id=None):
    if space.metadata.get('candidate_artifact'):
        from modelanvil.rag.embedding_candidates import pins
        return pins(space,project_id)
    if (space.model_name != adapter.PINS['model'] or space.model_revision != adapter.PINS['revision']
            or space.license_expression != adapter.PINS['license'] or space.dimension != adapter.PINS['dimension']
            or not space.normalized or space.distance_metric != 'cosine'
            or space.metadata.get('profile_digest') != digest(adapter.PINS)):
        raise ValueError('Select the registered immutable local MiniLM embedding space.')
    return {'space':str(space.space_id),'model':space.model_name,'revision':space.model_revision,
        'license':space.license_expression,'dimension':space.dimension,'normalized':space.normalized,
        'profile_digest':space.metadata['profile_digest']}


def source_chunks(index, project):
    if index.status != 'ready' or not check_resource_access(index,project,index.tenant_id) or not check_resource_access(index.knowledge_base,project,index.tenant_id):
        raise ValueError('The frozen source index is unavailable.')
    chunks = RetrievalEngine(index).get_eligible_chunks()
    expected = set(index.configuration.get('chunk_ids', []))
    if not expected or len(expected)>adapter.MAX_CHUNKS or {str(c.chunk_id) for c in chunks} != expected:
        raise ValueError('Use 1–1000 currently accessible chunks from a complete frozen source index.')
    if index.configuration.get('tokenizer',{}).get('sha256') != adapter.PINS['files']['tokenizer.json']['sha256']:
        raise ValueError('Rebuild source chunks with the pinned MiniLM tokenizer first.')
    for chunk in chunks:
        if chunk.content_hash != hashlib.sha256(chunk.text.encode()).hexdigest():
            raise ValueError('Frozen source chunk bytes changed.')
    return chunks


@transaction.atomic
def queue(*, source, space, project, principal, pool, policy_id, key):
    if connection.vendor != 'postgresql':
        raise ValueError('Real vector index builds require PostgreSQL with pgvector.')
    if not check_resource_access(space,project.pk,source.tenant_id):
        raise ValueError('Embedding space is unavailable in the selected project.')
    pins = space_pins(space,project.pk); chunks=source_chunks(source,project.pk)
    if source.configuration.get('chunk_size',0)>254:
        raise ValueError('Rechunk with at most 254 content tokens before this 256-token model build.')
    runtime=runtime_digest()
    workers=Worker.all_objects.filter(tenant_id=source.tenant_id,pool=pool,status__in=['available','busy'],
        capabilities__embedding_runtime=runtime)
    if (pool.tenant_id!=source.tenant_id or pool.status!='active' or pool.result_egress!='envelope'
            or not any(local_capacity_available(w) for w in workers)):
        raise ValueError('Connect a matching CPU embedding worker in an active envelope pool first.')
    frozen={'source_index':str(source.index_id),'source_manifest':source.manifest_digest,'space':pins,'runtime':runtime,
        'chunks':[{'id':str(c.chunk_id),'hash':c.content_hash} for c in chunks]}
    fingerprint=digest({'frozen':frozen,'pool':pool.pk,'budget_policy':str(policy_id)})
    identity=dict(tenant_id=source.tenant_id,principal=str(principal),http_method='POST',path=f'/embeddings/{project.pk}/builds',key=key)
    admission,created=IdempotencyKey.all_objects.select_for_update().get_or_create(**identity,defaults={'request_hash':fingerprint})
    if not created:
        if admission.request_hash!=fingerprint:raise ValueError('Idempotency key belongs to different embedding inputs.')
        return EmbeddingBuild.all_objects.get(build_id=admission.response_body['build_id'],tenant_id=source.tenant_id,project=project)
    policy=BudgetPolicy.all_objects.filter(tenant_id=source.tenant_id,policy_id=policy_id,enabled=True,unit=UNIT,currency='').first()
    if not policy:raise ValueError('Select an enabled embedding_attempts quota without currency pricing.')
    base=KnowledgeBase.all_objects.select_for_update().get(pk=source.knowledge_base_id)
    revision=(IndexVersion.all_objects.filter(knowledge_base=base).aggregate(n=Max('revision_no'))['n'] or 0)+1
    job_id=uuid7();BudgetReservation.reserve(tenant_id=source.tenant_id,policy=policy,job_id=job_id,estimated_amount=MAX_ATTEMPTS)
    index=IndexVersion.all_objects.create(tenant_id=source.tenant_id,project=project,knowledge_base=base,embedding_space=space,
        revision_no=revision,adapter_type='dense',status='building',chunks_count=len(chunks),manifest_digest=source.manifest_digest,
        configuration={**source.configuration,'embedding_profile':pins,'embedding_build_runtime':runtime,'embeddings_generated':False,'retrieval':'pinned-local-minilm-pgvector-cosine-v1'})
    job=Job.all_objects.create(tenant_id=source.tenant_id,job_id=job_id,pool=pool,name='Build pinned local embedding index',
        max_attempts=MAX_ATTEMPTS,payload={'type':TYPE,'index_id':str(index.index_id)},requirements={'slots':1,'embedding_runtime':runtime})
    build=EmbeddingBuild.all_objects.create(tenant_id=source.tenant_id,project=project,job=job,source_index=source,index=index,
        principal=str(principal),frozen=frozen,input_digest=digest(frozen))
    admission.response_body={'build_id':str(build.build_id)};admission.response_status=202;admission.completed_at=timezone.now();admission.save()
    return build


def owning_build(job,lock=False):
    qs=EmbeddingBuild.all_objects.select_related('source_index__knowledge_base','index__embedding_space','project')
    if lock:qs=qs.select_for_update()
    build=qs.get(job_id=job.pk,tenant_id=job.tenant_id,index__index_id=job.payload['index_id'])
    if build.input_digest!=digest(build.frozen):raise ValueError('Embedding input identity changed.')
    return build


def live_build(context):
    attempt=JobAttempt.all_objects.select_for_update().get(pk=context.attempt.pk)
    job=Job.all_objects.select_for_update().get(pk=attempt.job_id)
    if (attempt.status!='running' or job.status!='running' or attempt.fencing_token!=context.fencing_token
            or job.fencing_token!=context.fencing_token or job.claimed_by_id!=attempt.worker_id
            or not attempt.lease_expires_at or attempt.lease_expires_at<=timezone.now() or job.desired_action=='cancel'):
        raise ValueError('Embedding build is cancelled or fenced out.')
    from modelanvil.jobs.models import WorkerPool
    pool=WorkerPool.all_objects.select_for_update().get(pk=job.pool_id)
    if pool.result_egress!='envelope':raise ValueError('Current pool policy forbids vector publication.')
    return owning_build(job,lock=True)


def checked_chunks(build):
    if not check_resource_access(build.index.embedding_space,build.project_id,build.tenant_id):
        raise ValueError('Embedding space access is no longer available.')
    if runtime_digest()!=build.frozen['runtime'] or space_pins(build.index.embedding_space,build.project_id)!=build.frozen['space']:
        raise ValueError('Embedding runtime or model-space pins changed.')
    if build.source_index.manifest_digest!=build.frozen['source_manifest']:
        raise ValueError('Source index manifest changed.')
    chunks=source_chunks(build.source_index,build.project_id)
    if [{'id':str(c.chunk_id),'hash':c.content_hash} for c in chunks]!=build.frozen['chunks']:
        raise ValueError('Source chunk membership or hashes changed.')
    return chunks


def checked_rows(build,chunks):
    rows={row.chunk_id:row for row in ChunkEmbedding.all_objects.filter(tenant_id=build.tenant_id,
        space=build.index.embedding_space,chunk_id__in=[c.pk for c in chunks])}
    for chunk in chunks:
        row=rows.get(chunk.pk)
        if row:
            adapter.validate_vectors([row.vector],1)
            if (row.content_hash!=chunk.content_hash or row.runtime_digest!=build.frozen['runtime']
                    or row.vector_digest!=adapter.vector_digest(row.vector)):
                raise ValueError('Cached chunk vector provenance or checksum changed.')
    return rows


def embedding_executor(descriptor,context):
    with transaction.atomic():
        build=live_build(context);chunks=checked_chunks(build)
        reservation=BudgetReservation.all_objects.get(tenant_id=build.tenant_id,job_id=build.job.job_id)
        if reservation.state!='reserved':raise ValueError('Embedding attempt quota is unavailable.')
        UsageEvent.record(tenant_id=build.tenant_id,provider_event_key=f'embedding:{context.attempt.attempt_id}',quantity=1,
            unit=UNIT,reservation=reservation,detail={'build_id':str(build.build_id),'attempt_id':str(context.attempt.attempt_id)})
        cached=checked_rows(build,chunks)
    pending=[c for c in chunks if c.pk not in cached]
    for start in range(0,len(pending),adapter.BATCH_SIZE):
        if not context.heartbeat(progress=len(cached)/len(chunks)):return None
        batch=pending[start:start+adapter.BATCH_SIZE]
        vectors=adapter.encode_space([c.text for c in batch],build.index.embedding_space,build.project_id)
        if not context.heartbeat():return None
        with transaction.atomic():
            current=live_build(context);checked_chunks(current)
            ChunkEmbedding.all_objects.bulk_create([ChunkEmbedding(tenant_id=build.tenant_id,chunk=c,space=build.index.embedding_space,
                vector=v,content_hash=c.content_hash,vector_digest=adapter.vector_digest(v),runtime_digest=build.frozen['runtime'])
                for c,v in zip(batch,vectors)],ignore_conflicts=True)
            cached=checked_rows(current,chunks)
            current.completed_chunks=len(cached);current.save(update_fields=['completed_chunks','updated_at'])
    context.heartbeat(progress=1)
    return None


def create_hnsw(space):
    if connection.vendor!='postgresql':raise ValueError('A real vector index requires PostgreSQL.')
    dimension=int(space.dimension);key=int(space.pk)
    if dimension!=adapter.PINS['dimension']:raise ValueError('Unsupported HNSW dimension.')
    quote=connection.ops.quote_name;name=f'embedding_space_{key}_hnsw'
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE INDEX IF NOT EXISTS {quote(name)} ON {quote(ChunkEmbedding._meta.db_table)} USING hnsw ((vector::vector({dimension})) vector_cosine_ops) WHERE space_id = {key}')
    return name


def finalize_job(job,status):
    """The caller holds the job fence transaction. Never publish partial READY."""
    build=owning_build(job,lock=True);index=IndexVersion.all_objects.select_for_update().get(pk=build.index_id)
    if status=='succeeded':
        try:
            if job.pool.result_egress!='envelope':raise ValueError('Pool policy forbids vector publication.')
            chunks=checked_chunks(build);rows=checked_rows(build,chunks)
            if len(rows)!=len(chunks):raise ValueError('Vector build is incomplete.')
            space=EmbeddingSpace.all_objects.select_for_update().get(pk=index.embedding_space_id)
            hnsw=create_hnsw(space)
            index.configuration={**index.configuration,'embeddings_generated':True,'hnsw_index':hnsw,
                'vector_manifest':digest([(str(c.chunk_id),rows[c.pk].vector_digest) for c in chunks])}
            index.status='ready';build.error=''
        except (ValueError,PermissionError):
            status='failed';index.status='failed';build.error='Publication refused: current source, space, runtime or policy checks failed.'
    else:
        index.status='failed';build.error='Build cancelled or failed. Verified vector checkpoints are retained for bounded retry.'
    index.save(update_fields=['status','configuration','updated_at']);build.save(update_fields=['error','updated_at'])
    reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id,job_id=job.job_id)
    if reservation.state=='reserved':reservation.settle(sum(reservation.usage_events.values_list('quantity',flat=True)))
    return status


@transaction.atomic
def cancel(build):
    job=Job.all_objects.select_for_update().get(pk=build.job_id,tenant_id=build.tenant_id)
    if job.status in {'succeeded','failed','cancelled'}:raise ValueError('This build is already terminal.')
    job.desired_action='cancel'
    if job.status in {'queued','interrupted'}:
        job.status='cancelled';finalize_job(job,'cancelled')
    job.save(update_fields=['desired_action','status','updated_at']);return job


@transaction.atomic
def retry(build):
    job=Job.all_objects.select_for_update().get(pk=build.job_id,tenant_id=build.tenant_id)
    if job.status not in {'failed','interrupted','cancelled'} or job.attempt_count>=MAX_ATTEMPTS:
        raise ValueError('Only stopped builds with remaining attempts can resume.')
    build=owning_build(job,lock=True);checked_chunks(build)
    reservation=BudgetReservation.all_objects.select_for_update().get(tenant_id=job.tenant_id,job_id=job.job_id)
    policy=BudgetPolicy.all_objects.select_for_update().get(pk=reservation.policy_id)
    period,commitment=BudgetReservation.current_commitment(policy)
    used=reservation.settled_amount or 0
    if not policy.enabled or period!=reservation.period_start or commitment+MAX_ATTEMPTS-used>policy.limit_amount:
        raise ValueError('Original-period retry quota is unavailable.')
    reservation.state='reserved';reservation.settled_amount=None;reservation.settled_at=None;reservation.save()
    job.status='queued';job.desired_action='run';job.save(update_fields=['status','desired_action','updated_at'])
    build.index.status='building';build.index.save(update_fields=['status','updated_at'])
    build.error='';build.save(update_fields=['error','updated_at'])
    OutboxEvent.all_objects.create(tenant_id=job.tenant_id,topic=dispatch_topic(job.tenant_id,job.pool.queue_name,job.pool.name),payload={'event_type':'job.queued','job_id':str(job.job_id)})
    return job
