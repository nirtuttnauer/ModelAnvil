"""Versioned runner, adapter, model, tokenizer, and evaluation registry (WP-07, WP-08, WP-11)."""
from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel


class RunnerManifest(TenantContextModel):
    manifest_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    manifest = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    compatibility = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name", "version"), name="runner_manifest_version_uniq")]

    def clean(self) -> None:
        if len(self.digest) != 64 or any(c not in "0123456789abcdef" for c in self.digest):
            raise ValidationError({"digest": "Must be lowercase SHA-256 hex."})
        from contracts.validate import validate_adapter_manifest
        try:
            validate_adapter_manifest(self.manifest)
        except Exception as exc:
            raise ValidationError({"manifest": str(exc)}) from exc

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class AdapterRegistryEntry(TenantContextModel):
    entry_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=64)
    manifest_digest = models.CharField(max_length=64)
    manifest = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    compatibility = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name", "version"), name="adapter_registry_version_uniq")]

    def clean(self) -> None:
        if len(self.manifest_digest) != 64 or any(c not in "0123456789abcdef" for c in self.manifest_digest):
            raise ValidationError({"manifest_digest": "Must be lowercase SHA-256 hex."})
        from contracts.validate import validate_adapter_manifest
        try:
            validate_adapter_manifest(self.manifest)
        except Exception as exc:
            raise ValidationError({"manifest": str(exc)}) from exc

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


def compatible(entry: RunnerManifest | AdapterRegistryEntry, requirements: dict[str, Any]) -> bool:
    """Fail closed unless each requested compatibility key matches."""
    declared = entry.compatibility
    return all(declared.get(key) == value for key, value in requirements.items())


# ---------------------------------------------------------------------------
# Model & Tokenizer Registry (WP-07 / TECH-015)
# ---------------------------------------------------------------------------

class Model(TenantContextModel):
    """Logical registered model."""

    model_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="models"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    intended_tasks = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name"), name="model_tenant_name_uniq")]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class TokenizerVersion(TenantContextModel):
    """Exact tokenizer artifact with vocabulary and special token constraints."""

    tokenizer_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="tokenizer_versions"
    )
    name = models.CharField(max_length=200)
    revision_no = models.PositiveIntegerField(default=1)
    artifact_manifest_id = models.CharField(max_length=128, blank=True)
    configuration_digest = models.CharField(max_length=64, blank=True)
    vocabulary_size = models.PositiveIntegerField(default=32000)
    special_tokens = models.JSONField(default=dict, blank=True)
    chat_template = models.TextField(blank=True)
    compatibility = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name", "revision_no"), name="tokenizer_version_uniq")]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            previous = type(self).all_objects.filter(pk=self.pk).first()
            if previous and previous.compatibility.get('immutable_import'):
                fields = ('tenant_id', 'project_id', 'configuration_digest', 'vocabulary_size',
                          'chat_template', 'special_tokens', 'compatibility', 'artifact_manifest_id')
                if any(getattr(previous, f) != getattr(self, f) for f in fields):
                    raise ValidationError('Imported tokenizer snapshots are immutable; import a new version.')
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} r{self.revision_no}"


class ProcessorVersion(TenantContextModel):
    """Multimodal or specialized preprocessor."""

    processor_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=200)
    revision_no = models.PositiveIntegerField(default=1)
    processor_type = models.CharField(max_length=64, default="multimodal")
    configuration_digest = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name", "revision_no"), name="processor_version_uniq")]

    def __str__(self) -> str:
        return f"{self.name} r{self.revision_no} ({self.processor_type})"


class ModelVersion(TenantContextModel):
    """Immutable model weight/adapter version with pinned tokenizer."""

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUALIFIED = "qualified", "Qualified"
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    model_version_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="model_versions"
    )
    model = models.ForeignKey(Model, on_delete=models.CASCADE, related_name="versions")
    revision_no = models.PositiveIntegerField(default=1)
    architecture_ref = models.CharField(max_length=128)
    artifact_manifest_id = models.CharField(max_length=128, blank=True)
    tokenizer = models.ForeignKey(TokenizerVersion, on_delete=models.PROTECT, related_name="model_versions")
    processor = models.ForeignKey(ProcessorVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="model_versions")
    license_evidence = models.CharField(max_length=64, default="apache-2.0")
    parameters_count = models.PositiveBigIntegerField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    producing_job_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("model", "revision_no"), name="model_version_revision_uniq")]

    def clean(self) -> None:
        if self.model_id and str(self.model.tenant_id) != str(self.tenant_id):
            raise ValidationError("Model version and model must share a tenant.")
        if self.tokenizer_id and str(self.tokenizer.tenant_id) != str(self.tenant_id):
            raise ValidationError("Model version and tokenizer must share a tenant.")
        if self.model_id and self.project_id and self.model.project_id and str(self.model.project_id) != str(self.project_id):
            from modelanvil.identity.models import check_resource_access
            if not check_resource_access(self.model, self.project_id, self.tenant_id):
                raise ValidationError("Model version and model must share the same project.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.project_id and self.model_id and self.model.project_id:
            self.project = self.model.project
        if self.pk:
            previous = type(self).all_objects.filter(pk=self.pk).first()
            if previous and (previous.metadata.get('imported') or previous.source_training_run.exists()):
                fields = ('tenant_id', 'project_id', 'model_id', 'tokenizer_id', 'processor_id',
                          'revision_no', 'architecture_ref', 'artifact_manifest_id', 'metadata', 'license_evidence')
                if any(getattr(previous, f) != getattr(self, f) for f in fields):
                    raise ValidationError('Imported and trained model snapshots are immutable; create a new version.')
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.model.name} r{self.revision_no} [{self.state}]"


class InferenceRequest(TenantContextModel):
    request_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, related_name='inference_requests')
    model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT, related_name='inference_requests')
    principal_id = models.CharField(max_length=128)
    input_digest = models.CharField(max_length=64)
    configuration = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default='running')
    usage = models.JSONField(null=True)
    elapsed_seconds = models.FloatField(null=True)
    output_digest = models.CharField(max_length=64, blank=True)
    completed_at = models.DateTimeField(null=True)


class ChatConversation(TenantContextModel):
    conversation_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, related_name='chat_conversations')
    title = models.CharField(max_length=180)
    messages = models.JSONField(default=list)
    configuration = models.JSONField(default=dict)
    revision_no = models.PositiveIntegerField(default=1)


class ChatComparison(TenantContextModel):
    review_campaign = models.ForeignKey('annotation.LabelingCampaign', on_delete=models.PROTECT,
        null=True, blank=True, related_name='arena_comparisons')
    comparison_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey('identity.Project', on_delete=models.PROTECT, related_name='chat_comparisons')
    conversation = models.ForeignKey(ChatConversation, on_delete=models.SET_NULL, null=True, related_name='comparisons')
    first_request = models.ForeignKey(InferenceRequest, on_delete=models.PROTECT, related_name='first_comparisons')
    second_request = models.ForeignKey(InferenceRequest, on_delete=models.PROTECT, related_name='second_comparisons')
    first_text = models.TextField()
    second_text = models.TextField()
    first_is_a = models.BooleanField()
    messages = models.JSONField(default=list)
    vote = models.CharField(max_length=8, blank=True)
    voter_id = models.CharField(max_length=128, blank=True)
    voted_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('first_request', 'second_request'), name='chat_comparison_pair_unique')]
        ordering = ('-created_at',)


class ModelImport(TenantContextModel):
    """Pinned acquisition; only a live job fence may publish its candidate."""

    import_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey("identity.Project", on_delete=models.PROTECT, related_name="model_imports")
    name = models.CharField(max_length=180)
    repo_id = models.CharField(max_length=200)
    revision = models.CharField(max_length=40)
    format = models.CharField(max_length=20, default="safetensors")
    license_expression = models.CharField(max_length=200)
    files = models.JSONField(default=dict)
    acquired_files = models.JSONField(default=dict)
    job = models.OneToOneField("jobs.Job", on_delete=models.PROTECT, null=True, related_name="model_import")
    candidate = models.ForeignKey(ModelVersion, on_delete=models.PROTECT, null=True, related_name="imports")
    status = models.CharField(max_length=20, default="queued")
    input_digest = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "project", "idempotency_key"), name="model_import_idempotency")]


def validate_model_tokenizer_compatibility(model_version: ModelVersion, tokenizer_version: TokenizerVersion) -> None:
    """Validate compatibility between a ModelVersion and a TokenizerVersion."""
    model_vocab = (model_version.metadata or {}).get("vocab_size")
    if model_vocab and tokenizer_version.vocabulary_size and model_vocab != tokenizer_version.vocabulary_size:
        raise ValidationError({"tokenizer_version": f"Vocabulary size mismatch: model expects {model_vocab}, tokenizer has {tokenizer_version.vocabulary_size}."})


# ---------------------------------------------------------------------------
# Evaluation Registry & Executor (WP-07 / TECH-020)
# ---------------------------------------------------------------------------

class EvaluationSuite(TenantContextModel):
    """Logical suite of evaluation test cases."""

    suite_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="evaluation_suites"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant_id", "name"), name="eval_suite_tenant_name_uniq")]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class EvaluationSuiteVersion(TenantContextModel):
    """Pinned evaluation test cases, scorers, and judge configurations."""

    suite_version_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="evaluation_suite_versions"
    )
    suite = models.ForeignKey(EvaluationSuite, on_delete=models.CASCADE, related_name="versions")
    revision_no = models.PositiveIntegerField(default=1)
    cases = models.JSONField(default=list)
    cases_count = models.PositiveIntegerField(default=0)
    schema_id = models.CharField(max_length=64, default="eval_case_v1")
    scorer_type = models.CharField(max_length=64, default="exact_match")
    scorer_config = models.JSONField(default=dict, blank=True)
    judge_config = models.JSONField(default=dict, blank=True)
    protected_role = models.CharField(max_length=64, default="protected_eval")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("suite", "revision_no"), name="eval_suite_version_uniq")]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.project_id and self.suite_id and self.suite.project_id:
            self.project = self.suite.project
        if isinstance(self.cases, list):
            self.cases_count = len(self.cases)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.suite.name} r{self.revision_no}"


class EvaluationRun(TenantContextModel):
    """Execution of an evaluation suite on a candidate model version."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    run_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="evaluation_runs"
    )
    suite_version = models.ForeignKey(EvaluationSuiteVersion, on_delete=models.PROTECT, related_name="runs")
    candidate_model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT, related_name="evaluation_runs")
    baseline_model_version = models.ForeignKey(ModelVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="baseline_runs")
    protocol_ref = models.JSONField(default=dict, blank=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.PROTECT, null=True, blank=True, related_name='evaluation_runs')
    started_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"EvalRun {self.run_id} ({self.status})"


class EvaluationCaseResult(TenantContextModel):
    """Case-level execution result with prediction, score, and failure diagnostics."""

    result_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    run = models.ForeignKey(EvaluationRun, on_delete=models.CASCADE, related_name="case_results")
    case_id = models.CharField(max_length=128)
    input_prompt = models.TextField(blank=True)
    candidate_output = models.TextField(blank=True)
    expected_output = models.TextField(blank=True)
    score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(default=False)
    failure_reason = models.TextField(blank=True)
    slice_name = models.CharField(max_length=64, default="all")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("run", "case_id"), name="eval_case_run_case_uniq")]


class EvaluationMetric(TenantContextModel):
    """Aggregate metric per slice with uncertainty / confidence intervals."""

    metric_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    run = models.ForeignKey(EvaluationRun, on_delete=models.CASCADE, related_name="metrics")
    key = models.CharField(max_length=64)
    slice_name = models.CharField(max_length=64, default="all")
    value = models.FloatField(null=True, blank=True)
    sample_count = models.PositiveIntegerField(default=0)
    uncertainty_interval = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("run", "key", "slice_name"), name="eval_metric_run_key_slice_uniq")]


class JudgeCalibration(TenantContextModel):
    """Calibration record establishing judge agreement with verified human evaluations."""

    calibration_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    judge_model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT, related_name="calibrations")
    human_sample_ref = models.CharField(max_length=128)
    agreement_score = models.FloatField(default=0.0)
    status = models.CharField(max_length=16, default="qualified")
    metadata = models.JSONField(default=dict, blank=True)


# ---------------------------------------------------------------------------
# Training Run & Checkpoint Registry (WP-08 / TECH-016, TECH-017)
# ---------------------------------------------------------------------------

class TrainingRun(TenantContextModel):
    """Orchestrated training run across scratch pretraining, fine-tuning, or adapter recipes."""

    class RecipeType(models.TextChoices):
        SCRATCH_PRETRAINING = "scratch_pretraining", "Scratch Pretraining"
        CONTINUED_PRETRAINING = "continued_pretraining", "Continued Pretraining"
        FULL_SFT = "full_sft", "Full Parameter SFT"
        LORA_ADAPTER = "lora_adapter", "LoRA Adapter"
        QLORA_ADAPTER = "qlora_adapter", "Quantized LoRA Adapter"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    run_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    recovery_parent = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='recovery_execution')
    recovery_checkpoint = models.ForeignKey('TrainingCheckpoint', on_delete=models.PROTECT, null=True,
        blank=True, related_name='recovery_executions')
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="training_runs"
    )
    recipe_type = models.CharField(max_length=32, choices=RecipeType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    base_model_version = models.ForeignKey(
        ModelVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="downstream_training_runs"
    )
    tokenizer_version = models.ForeignKey(
        TokenizerVersion, on_delete=models.PROTECT, related_name="training_runs"
    )
    dataset_revision = models.ForeignKey(
        "artifacts.DatasetRevision", on_delete=models.SET_NULL, null=True, blank=True, related_name="training_runs"
    )
    dataset_manifest_digest = models.CharField(max_length=64, blank=True)
    pool = models.ForeignKey(
        "jobs.WorkerPool", on_delete=models.SET_NULL, null=True, blank=True, related_name="training_runs"
    )
    job = models.ForeignKey(
        "jobs.Job", on_delete=models.SET_NULL, null=True, blank=True, related_name="training_runs"
    )
    hyperparameters = models.JSONField(default=dict, blank=True)
    hardware_config = models.JSONField(default=dict, blank=True)
    resource_reservation_id = models.UUIDField(null=True, blank=True)
    initialization_seed = models.PositiveIntegerField(default=42)
    current_step = models.PositiveIntegerField(default=0)
    total_steps = models.PositiveIntegerField(default=100)
    latest_loss = models.FloatField(null=True, blank=True)
    metrics_log = models.JSONField(default=list, blank=True)
    output_model_version = models.ForeignKey(
        ModelVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="source_training_run"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def clean(self) -> None:
        if self.base_model_version_id and str(self.base_model_version.tenant_id) != str(self.tenant_id):
            raise ValidationError("Base model version and training run must share a tenant.")
        if self.tokenizer_version_id and str(self.tokenizer_version.tenant_id) != str(self.tenant_id):
            raise ValidationError("Tokenizer version and training run must share a tenant.")
        if self.dataset_revision_id and str(self.dataset_revision.tenant_id) != str(self.tenant_id):
            raise ValidationError("Dataset revision and training run must share a tenant.")
        if self.pool_id and str(self.pool.tenant_id) != str(self.tenant_id):
            raise ValidationError("Worker pool and training run must share a tenant.")
        if self.job_id and str(self.job.tenant_id) != str(self.tenant_id):
            raise ValidationError("Job and training run must share a tenant.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"TrainingRun {self.run_id} [{self.recipe_type}] ({self.status})"


class TrainingCheckpoint(TenantContextModel):
    """Deterministic, inspectable checkpoint of training weights and state."""

    checkpoint_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    training_run = models.ForeignKey(
        TrainingRun, on_delete=models.CASCADE, related_name="checkpoints"
    )
    step = models.PositiveIntegerField()
    state_digest = models.CharField(max_length=64)
    is_valid = models.BooleanField(default=True)
    metrics = models.JSONField(default=dict, blank=True)
    weights_manifest = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("training_run", "step"), name="training_checkpoint_run_step_uniq")
        ]

    def __str__(self) -> str:
        return f"Checkpoint {self.training_run_id} step {self.step}"


# ---------------------------------------------------------------------------
# Alignment Run & Checkpoint Registry (WP-11 / TECH-018, TECH-019)
# ---------------------------------------------------------------------------

class AlignmentRun(TenantContextModel):
    """Orchestrated preference, reward model, RLHF, and verifier RL runs (WP-11 / TECH-018-019)."""

    class Algorithm(models.TextChoices):
        DPO = "dpo", "Direct Preference Optimization"
        REWARD_MODEL = "reward_model", "Bradley-Terry Reward Model"
        PPO_RLHF = "ppo_rlhf", "Learned-Reward PPO RLHF"
        VERIFIER_RL = "verifier_rl", "Verifier Rule-Guided RL"
        GRPO = "grpo", "Group Relative Policy Optimization"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        INTERRUPTED = "interrupted", "Interrupted"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    run_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    project = models.ForeignKey(
        "identity.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="alignment_runs"
    )
    algorithm = models.CharField(max_length=32, choices=Algorithm.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    policy_model_version = models.ForeignKey(
        ModelVersion, on_delete=models.CASCADE, related_name="policy_alignment_runs"
    )
    reference_model_version = models.ForeignKey(
        ModelVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="reference_alignment_runs"
    )
    reward_model_version = models.ForeignKey(
        ModelVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="reward_alignment_runs"
    )
    verifier_spec = models.JSONField(default=dict, blank=True)
    dataset_manifest_digest = models.CharField(max_length=64, blank=True)
    held_out_validation_digest = models.CharField(max_length=64, blank=True)
    hyperparameters = models.JSONField(default=dict, blank=True)
    train_dataset_artifact = models.ForeignKey(
        "artifacts.Artifact", on_delete=models.PROTECT, null=True, blank=True,
        related_name="alignment_training_runs",
    )
    held_out_dataset_artifact = models.ForeignKey(
        "artifacts.Artifact", on_delete=models.PROTECT, null=True, blank=True,
        related_name="alignment_validation_runs",
    )
    execution_pins = models.JSONField(default=dict, blank=True)
    execution_token = models.UUIDField(null=True, blank=True, editable=False)
    resource_reservation_id = models.UUIDField(null=True, blank=True, editable=False)
    current_step = models.PositiveIntegerField(default=0)
    total_steps = models.PositiveIntegerField(default=100)
    latest_metrics = models.JSONField(default=dict, blank=True)
    metrics_history = models.JSONField(default=list, blank=True)
    rollouts_log = models.JSONField(default=list, blank=True)
    output_model_version = models.ForeignKey(
        ModelVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="source_alignment_run"
    )
    stop_reason = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"AlignmentRun {self.run_id} [{self.algorithm}] ({self.status})"


class AlignmentCheckpoint(TenantContextModel):
    """Deterministic, inspectable checkpoint of alignment policy/reward state."""

    checkpoint_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    alignment_run = models.ForeignKey(
        AlignmentRun, on_delete=models.CASCADE, related_name="checkpoints"
    )
    step = models.PositiveIntegerField()
    state_digest = models.CharField(max_length=64)
    policy_state = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    is_valid = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("alignment_run", "step"), name="alignment_checkpoint_run_step_uniq")
        ]

    def __str__(self) -> str:
        return f"AlignmentCheckpoint {self.alignment_run_id} step {self.step}"


class LocalTrainingHost(models.Model):
    """Observed managed service state; no tenant data or host credentials."""
    name = models.CharField(max_length=32, unique=True, default="local")
    status = models.CharField(max_length=20, default="starting")
    device = models.CharField(max_length=32, blank=True)
    memory_bytes = models.PositiveBigIntegerField(default=0)
    error = models.CharField(max_length=400, blank=True)
    build_digest = models.CharField(max_length=64, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True)
