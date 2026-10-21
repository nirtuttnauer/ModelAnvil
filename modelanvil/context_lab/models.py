"""Context Lab durable models: Recipes, Blocks, Memory Snapshots, Tool Fixtures, and Experiments (WP-13 / TECH-026-027)."""
from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from modelanvil.core.ids import uuid7
from modelanvil.core.models import TenantContextModel


class ContextRecipe(TenantContextModel):
    """Logical context composition recipe."""

    recipe_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name"), name="context_recipe_tenant_name_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"


class ContextRecipeVersion(TenantContextModel):
    """Pinned, immutable context recipe revision with token budget and output reserve (TECH-026)."""

    class BudgetPolicy(models.TextChoices):
        FAIL_ON_OVERFLOW = "fail_on_overflow", "Fail on Overflow"
        TRIM_LOWEST_PRIORITY = "trim_lowest_priority", "Trim Lowest Priority Blocks"
        SUMMARIZE = "summarize", "Summarize History"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PROMOTED = "promoted", "Promoted"
        ARCHIVED = "archived", "Archived"

    recipe_version_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    recipe = models.ForeignKey(ContextRecipe, on_delete=models.CASCADE, related_name="versions")
    revision_no = models.PositiveIntegerField(default=1)
    model_limit_tokens = models.PositiveIntegerField(default=4096)
    output_reserve_tokens = models.PositiveIntegerField(default=512)
    budget_policy = models.CharField(
        max_length=32, choices=BudgetPolicy.choices, default=BudgetPolicy.TRIM_LOWEST_PRIORITY
    )
    tokenizer_ref = models.CharField(max_length=128, default="llama-3-8b")
    chat_template = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("recipe", "revision_no"), name="recipe_version_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.recipe.name} r{self.revision_no} [{self.status}]"


class ContextBlockRevision(TenantContextModel):
    """Ordered context block definition with role, trust level, and priority (TECH-026)."""

    class BlockType(models.TextChoices):
        INSTRUCTION = "instruction", "Instruction"
        USER_QUERY = "user_query", "User Query"
        EXAMPLES = "examples", "Few-Shot Examples"
        EVIDENCE = "evidence", "Retrieved Evidence"
        HISTORY = "history", "Conversation History"
        MEMORY = "memory", "User Memory / Fact"
        TOOL_RESULT = "tool_result", "Tool Execution Result"

    class Role(models.TextChoices):
        SYSTEM = "system", "System"
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        TOOL = "tool", "Tool"

    block_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    recipe_version = models.ForeignKey(ContextRecipeVersion, on_delete=models.CASCADE, related_name="blocks")
    block_key = models.CharField(max_length=64)
    block_type = models.CharField(max_length=32, choices=BlockType.choices)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.SYSTEM)
    order = models.PositiveIntegerField(default=0)  # Ascending position in serialized prompt
    priority = models.PositiveIntegerField(default=1)  # 1 is highest priority, 10 is lowest
    max_tokens = models.PositiveIntegerField(null=True, blank=True)
    content_template = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("recipe_version", "block_key"), name="recipe_block_key_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.block_key} ({self.role}) [P{self.priority}]"


class SessionMemorySnapshot(TenantContextModel):
    """Multi-turn memory snapshot isolating conversation sessions with expiry support (TECH-027)."""

    session_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    session_key = models.CharField(max_length=128)
    revision_no = models.PositiveIntegerField(default=1)
    entries = models.JSONField(default=list)  # [{"role": ..., "content": ..., "timestamp": ..., "expired": bool}]

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "session_key", "revision_no"), name="session_key_rev_uniq")
        ]

    def __str__(self) -> str:
        return f"Session {self.session_key} r{self.revision_no} ({len(self.entries)} entries)"


class ToolFixtureVersion(TenantContextModel):
    """Frozen tool execution schemas, responses, and permissions for offline reproducible replay (TECH-027)."""

    fixture_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=128)
    revision_no = models.PositiveIntegerField(default=1)
    tool_schemas = models.JSONField(default=list)
    frozen_results = models.JSONField(default=dict)
    is_live_allowed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant_id", "name", "revision_no"), name="tool_fixture_uniq")
        ]

    def __str__(self) -> str:
        return f"ToolFixture {self.name} r{self.revision_no}"


class ContextExperiment(TenantContextModel):
    """Paired stress suite or ablation experiment execution (TECH-027 / PRD Scenario 16)."""

    experiment_id = models.UUIDField(default=uuid7, unique=True, editable=False)
    name = models.CharField(max_length=200)
    recipe_version = models.ForeignKey(ContextRecipeVersion, on_delete=models.PROTECT, related_name="experiments")
    stress_type = models.CharField(max_length=64)  # position_sweep, overflow, injection, stale_memory, history_comparison
    metrics = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, default="completed")
    details = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"Experiment {self.name} [{self.stress_type}]"
