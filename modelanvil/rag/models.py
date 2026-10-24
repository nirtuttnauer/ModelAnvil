"""Durable models for Knowledge Bases, Chunks, Embeddings, Indices, Retrieval Metrics, Projections, and Traces (WP-12 / TECH-022-025)."""
from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from pgvector.django import VectorField

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel


class KnowledgeBase(TenantContextModel):
    """Logical knowledge base corpus belonging to a tenant."""

    kb_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name"), name="kb_tenant_name_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class ResearchSession(TenantContextModel):
    session_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    knowledge_base = models.OneToOneField(KnowledgeBase, on_delete=models.PROTECT)
    index = models.ForeignKey('IndexVersion', on_delete=models.PROTECT, null=True)
    model_version = models.ForeignKey('runners.ModelVersion', on_delete=models.PROTECT)
    turns = models.JSONField(default=list)
    memory = models.JSONField(default=dict)
    research_steps = models.JSONField(default=list)
    revision_no = models.PositiveIntegerField(default=1)


class SourceDocument(TenantContextModel):
    """Source document with versioned revisions, hashes, and access revocation (TECH-024)."""

    doc_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=255)
    source_uri = models.CharField(max_length=512)
    revision_no = models.PositiveIntegerField(default=1)
    content = models.TextField()
    content_hash = models.CharField(max_length=64)
    is_revoked = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    access_scope = models.CharField(max_length=64, default="public")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("knowledge_base", "source_uri", "revision_no"), name="doc_kb_uri_rev_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.title} r{self.revision_no} [{'REVOKED' if self.is_revoked else 'ACTIVE'}]"


class DocumentChunk(TenantContextModel):
    """Source-linked chunk with text, span positions, token count, and embedding (TECH-022)."""

    chunk_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    recipe_digest = models.CharField(max_length=64, default="", blank=True)
    text = models.TextField()
    content_hash = models.CharField(max_length=64)
    span_start = models.PositiveIntegerField(default=0)
    span_end = models.PositiveIntegerField(default=0)
    token_count = models.PositiveIntegerField(default=0)
    embedding = models.JSONField(default=list, blank=True)  # vector representation
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("document", "recipe_digest", "chunk_index"), name="chunk_doc_recipe_index_uniq")
        ]

    def __str__(self) -> str:
        return f"Chunk {self.chunk_index} of {self.document.title}"


class EmbeddingSpace(TenantContextModel):
    """Declared embedding space with model, dimension, and distance function (TECH-022)."""

    space_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, null=True, blank=True)
    model_revision = models.CharField(max_length=128, default='', blank=True)
    license_expression = models.CharField(max_length=64, default='', blank=True)
    name = models.CharField(max_length=200)
    model_name = models.CharField(max_length=200)
    dimension = models.PositiveIntegerField(default=384)
    distance_metric = models.CharField(max_length=32, default="cosine")  # cosine, l2, ip
    normalized = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name"), name="embedding_space_tenant_name_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.model_name}:{self.dimension}d]"


class ChunkEmbedding(TenantContextModel):
    """Actual vectors scoped by immutable chunk and declared embedding space."""
    chunk = models.ForeignKey(DocumentChunk,on_delete=models.CASCADE,related_name='space_embeddings')
    space = models.ForeignKey(EmbeddingSpace,on_delete=models.PROTECT,related_name='chunk_vectors')
    vector = VectorField()
    content_hash = models.CharField(max_length=64)
    vector_digest = models.CharField(max_length=64)
    runtime_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('chunk','space'),name='embedding_chunk_space_uniq')]


class IndexVersion(TenantContextModel):
    """Pinned, immutable knowledge index version over chunk manifests and embedding space."""

    class Status(models.TextChoices):
        BUILDING = "building", "Building"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        REVOKED = "revoked", "Revoked"

    class AdapterType(models.TextChoices):
        LEXICAL = "lexical", "Lexical (BM25 / Full-Text)"
        DENSE = "dense", "Dense (pgvector / Cosine)"
        HYBRID = "hybrid", "Hybrid (RRF Fusion)"

    project = models.ForeignKey('identity.Project',on_delete=models.PROTECT,null=True,blank=True)
    index_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    knowledge_base = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="indexes")
    embedding_space = models.ForeignKey(EmbeddingSpace, on_delete=models.PROTECT, related_name="indexes")
    revision_no = models.PositiveIntegerField(default=1)
    adapter_type = models.CharField(max_length=32, choices=AdapterType.choices, default=AdapterType.HYBRID)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    chunks_count = models.PositiveIntegerField(default=0)
    manifest_digest = models.CharField(max_length=64, blank=True)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("knowledge_base", "revision_no"), name="index_kb_rev_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.knowledge_base.name} Index r{self.revision_no} ({self.status})"


class RetrievalCase(TenantContextModel):
    """Evaluation test case for retrieval benchmark suites (TECH-023)."""

    case_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    query = models.TextField()
    expected_chunk_ids = models.JSONField(default=list)  # Ground-truth relevant chunk IDs
    graded_relevance = models.JSONField(default=dict, blank=True)  # {chunk_id: grade}
    reference_answer = models.TextField(blank=True)
    is_unanswerable = models.BooleanField(default=False)
    task_tag = models.CharField(max_length=64, default="general")

    def __str__(self) -> str:
        return f"Case: {self.query[:40]}"


class RetrievalRun(TenantContextModel):
    """Execution of retrieval evaluation over an index version."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    run_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    index_version = models.ForeignKey(IndexVersion, on_delete=models.PROTECT, related_name="eval_runs")
    mode = models.CharField(max_length=32, default="hybrid")
    top_k = models.PositiveIntegerField(default=5)
    reranker = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETED)
    qrels_version = models.CharField(max_length=128, blank=True)
    qrels_digest = models.CharField(max_length=64, blank=True)
    protocol_ref = models.JSONField(default=dict, blank=True)
    metrics_summary = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"RetrievalRun {self.run_id} [{self.mode} @ {self.top_k}]"


class RetrievalMetric(TenantContextModel):
    """Fine-grained retrieval score (Recall, Precision, Hit, MRR, nDCG) with N/A support (TECH-023)."""

    metric_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    run = models.ForeignKey(RetrievalRun, on_delete=models.CASCADE, related_name="metrics")
    key = models.CharField(max_length=64)  # recall@k, precision@k, hit@k, mrr@k, ndcg@k
    k = models.PositiveIntegerField(default=5)
    value = models.FloatField(null=True, blank=True)
    is_na = models.BooleanField(default=False)
    sample_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("run", "key", "k"), name="retrieval_metric_run_key_k_uniq")
        ]


class ProjectionArtifact(TenantContextModel):
    """Saved 2D UMAP/PCA projection, cluster labels, and original embedding neighbors (TECH-025)."""

    artifact_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    index_version = models.ForeignKey(IndexVersion, on_delete=models.CASCADE, related_name="projections")
    method = models.CharField(max_length=16, default="pca")  # Other methods require separate qualified implementations.
    coordinates = models.JSONField(default=list)  # [{"chunk_id": ..., "x": ..., "y": ..., "cluster_id": ...}]
    clusters = models.JSONField(default=dict, blank=True)  # cluster metadata / summary
    settings = models.JSONField(default=dict, blank=True)
    total_points = models.PositiveIntegerField(default=0)
    displayed_points = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"Projection {self.artifact_id} [{self.method}] ({self.total_points} pts)"


class QueryTrace(TenantContextModel):
    """End-to-end query trace with candidates, reranking, citations, and redaction (TECH-022, TECH-024)."""

    trace_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    index_version = models.ForeignKey(IndexVersion, on_delete=models.CASCADE, related_name="traces")
    query = models.TextField()
    mode = models.CharField(max_length=32, default="hybrid")
    retrieval_config = models.JSONField(default=dict, blank=True)
    retrieved_chunk_ids = models.JSONField(default=list)
    reranked_chunk_ids = models.JSONField(default=list)
    supplied_context = models.TextField(blank=True)
    answer = models.TextField(blank=True)
    citations = models.JSONField(default=list)
    abstained = models.BooleanField(default=False)
    latency_ms = models.FloatField(default=0.0)
    redacted = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Trace {self.trace_id} [{self.mode}] - Abstained={self.abstained}"


class EmbeddingBuild(TenantContextModel):
    build_id = models.UUIDField(default=uuid7,unique=True,editable=False)
    project = models.ForeignKey('identity.Project',on_delete=models.PROTECT)
    job = models.OneToOneField('jobs.Job',on_delete=models.PROTECT,related_name='embedding_build')
    source_index = models.ForeignKey(IndexVersion,on_delete=models.PROTECT,related_name='embedding_builds')
    index = models.OneToOneField(IndexVersion,on_delete=models.PROTECT,related_name='build_request')
    principal = models.CharField(max_length=128)
    frozen = models.JSONField(default=dict)
    input_digest = models.CharField(max_length=64)
    completed_chunks = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300,blank=True)


class EmbeddingCandidate(TenantContextModel):
    """Published CPU fine-tuning result; weights and protocol are artifact-pinned."""
    candidate_id = models.UUIDField(default=uuid7,unique=True,editable=False)
    project = models.ForeignKey('identity.Project',on_delete=models.PROTECT)
    source = models.ForeignKey('artifacts.Artifact',on_delete=models.PROTECT,related_name='embedding_training_inputs')
    export = models.ForeignKey('artifacts.Artifact',on_delete=models.PROTECT,related_name='embedding_candidate_exports')
    space = models.OneToOneField(EmbeddingSpace,on_delete=models.PROTECT,related_name='candidate')
    source_digest = models.CharField(max_length=64)
    export_digest = models.CharField(max_length=64)
    files = models.JSONField(default=dict)
    protocol = models.JSONField(default=dict)
    report = models.JSONField(default=dict)


class EmbeddingTrainingExposure(TenantContextModel):
    """Minimal persistent group/text receipts prevent later clean-split relabeling."""
    project = models.ForeignKey('identity.Project',on_delete=models.PROTECT)
    source_group_digest = models.CharField(max_length=64,db_index=True)
    prompt_digest = models.CharField(max_length=64,db_index=True)
    role = models.CharField(max_length=16,choices=[('training','Training inspected'),('held_out','Protected held out')])

    class Meta:
        constraints = [models.UniqueConstraint(fields=('project','source_group_digest','prompt_digest','role'),name='embedding_exposure_uniq')]


class RAGGeneration(TenantContextModel):
    """Actual local model output with source, decoding and budget receipts."""
    run_id = models.UUIDField(default=uuid7,unique=True,editable=False)
    project = models.ForeignKey('identity.Project',on_delete=models.PROTECT)
    index = models.ForeignKey(IndexVersion,on_delete=models.PROTECT,related_name='generations')
    model_version = models.ForeignKey('runners.ModelVersion',on_delete=models.PROTECT)
    condition = models.CharField(max_length=16,choices=[('none','No retrieval'),('retrieved','Retrieved evidence'),('human','Human-supplied evidence')])
    query = models.TextField()
    status = models.CharField(max_length=32)
    answer = models.TextField(blank=True)
    raw_output = models.TextField(blank=True)
    citations = models.JSONField(default=list)
    receipt = models.JSONField(default=dict)
