"""Exact typed context compiler, token budgeting, and omission/truncation tracking (TECH-026)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from modelanvil.context_lab.models import ContextBlockRevision, ContextRecipeVersion, SessionMemorySnapshot


class ContextOverflowError(Exception):
    """Raised when context compilation exceeds token budget under strict overflow policies."""
    pass


@dataclass
class CompiledBlock:
    block_key: str
    block_type: str
    role: str
    priority: int
    raw_content: str
    rendered_content: str
    token_count: int
    truncated: bool = False
    original_token_count: int = 0


@dataclass
class ContextCompilationResult:
    serialized_prompt: str
    total_input_tokens: int
    output_reserve_tokens: int
    model_limit_tokens: int
    included_blocks: list[CompiledBlock] = field(default_factory=list)
    omitted_blocks: list[dict[str, Any]] = field(default_factory=list)
    truncated_blocks: list[dict[str, Any]] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """Deterministic token estimation (approx 4 chars per token, matching BPE heuristics)."""
    if not text:
        return 0
    words = re.findall(r"\w+|[^\w\s]", text)
    return max(1, len(words) + (len(text) // 16))


class ContextCompiler:
    """Compiles typed context blocks into exact serialized model input with token limits and omission records."""

    def __init__(self, recipe_version: ContextRecipeVersion) -> None:
        self.recipe_version = recipe_version

    def compile(
        self,
        runtime_inputs: Mapping[str, Any],
        memory_snapshot: Optional[SessionMemorySnapshot] = None,
    ) -> ContextCompilationResult:
        """Compile blocks into serialized input, enforcing token limits and output reserve."""
        max_budget = self.recipe_version.model_limit_tokens - self.recipe_version.output_reserve_tokens
        if max_budget <= 0:
            raise ContextOverflowError(
                f"Model limit ({self.recipe_version.model_limit_tokens}) is less than or equal to output reserve ({self.recipe_version.output_reserve_tokens})."
            )

        if self.recipe_version.budget_policy == ContextRecipeVersion.BudgetPolicy.SUMMARIZE:
            raise ContextOverflowError("Automatic summarization requires a configured model executor.")
        blocks = list(self.recipe_version.blocks.all().order_by("order", "priority", "block_key"))
        block_order = {block.block_key: position for position, block in enumerate(blocks)}
        truncated: list[dict[str, Any]] = []
        candidate_blocks: list[CompiledBlock] = []

        # Step 1: Render each defined block
        for b in blocks:
            raw = runtime_inputs.get(b.block_key, b.content_template)
            if b.block_type == ContextBlockRevision.BlockType.MEMORY and memory_snapshot:
                # Active non-expired memory items
                active_mem = [
                    entry["content"]
                    for entry in memory_snapshot.entries
                    if not entry.get("expired", False)
                ]
                raw = "\n".join(active_mem) if active_mem else ""

            if not raw:
                continue

            rendered = str(raw).strip()
            original_tokens = estimate_tokens(rendered)
            was_truncated = False
            if b.max_tokens is not None and original_tokens > b.max_tokens:
                low, high = 0, len(rendered)
                while low < high:
                    middle = (low + high + 1) // 2
                    if estimate_tokens(rendered[:middle]) <= b.max_tokens:
                        low = middle
                    else:
                        high = middle - 1
                rendered = rendered[:low].rstrip()
                was_truncated = True
                truncated.append({"block_key": b.block_key, "reason": "block_token_limit", "original_tokens": original_tokens, "tokens_retained": estimate_tokens(rendered)})
            tok_count = estimate_tokens(f"<|im_start|>{b.role}\n{rendered}<|im_end|>")

            candidate_blocks.append(
                CompiledBlock(
                    block_key=b.block_key,
                    block_type=b.block_type,
                    role=b.role,
                    priority=b.priority,
                    raw_content=str(raw),
                    rendered_content=rendered,
                    token_count=tok_count,
                    original_token_count=original_tokens,
                    truncated=was_truncated,
                )
            )

        def serialized(blocks):
            return "\n".join(f"<|im_start|>{block.role}\n{block.rendered_content}<|im_end|>" for block in blocks)

        total_tokens = estimate_tokens(serialized(candidate_blocks))
        included: list[CompiledBlock] = []
        omitted: list[dict[str, Any]] = []

        # Step 2: Handle overflow if total_tokens exceeds max_budget
        if total_tokens > max_budget:
            if self.recipe_version.budget_policy == ContextRecipeVersion.BudgetPolicy.FAIL_ON_OVERFLOW:
                raise ContextOverflowError(
                    f"Context overflow: Total required tokens {total_tokens} exceeds available budget {max_budget}."
                )

            # Sort by priority descending (priority 10 is trimmed first; priority 1 is kept)
            # Retain order when trimming
            active_list = list(candidate_blocks)
            while estimate_tokens(serialized(active_list)) > max_budget and active_list:
                # Find lowest priority (max priority number)
                lowest = max(active_list, key=lambda x: x.priority)
                if lowest.priority == 1:
                    # Critical system instructions cannot fit!
                    raise ContextOverflowError(
                        "Cannot trim further: Essential priority-1 instructions exceed token budget!"
                    )

                active_list.remove(lowest)
                omitted.append({
                    "block_key": lowest.block_key,
                    "reason": "token_budget_overflow",
                    "priority": lowest.priority,
                    "tokens_omitted": lowest.token_count,
                })

            included = active_list
        else:
            included = candidate_blocks

        # Step 3: Serialize prompt in strict block order
        included.sort(key=lambda x: block_order[x.block_key])

        prompt_lines = []
        for ib in included:
            prompt_lines.append(f"<|im_start|>{ib.role}\n{ib.rendered_content}<|im_end|>")

        serialized = "\n".join(prompt_lines)
        final_input_tokens = estimate_tokens(serialized)
        # Attribute separator and wrapper estimates so the chart allocations sum to the prompt estimate.
        prior = 0
        for position, block in enumerate(included):
            prefix = "\n".join(prompt_lines[:position + 1])
            prefix_tokens = estimate_tokens(prefix)
            block.token_count = prefix_tokens - prior
            prior = prefix_tokens

        return ContextCompilationResult(
            serialized_prompt=serialized,
            total_input_tokens=final_input_tokens,
            output_reserve_tokens=self.recipe_version.output_reserve_tokens,
            model_limit_tokens=self.recipe_version.model_limit_tokens,
            included_blocks=included,
            omitted_blocks=omitted,
            truncated_blocks=truncated,
        )
