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

    def __init__(self, recipe_version: ContextRecipeVersion, *, token_counter=estimate_tokens, serializer=None, runtime_limit_tokens=None) -> None:
        if getattr(recipe_version,'model_version_id',None) and token_counter is estimate_tokens:
            raise ValueError('A pinned recipe must use pinned_compiler and its verified runtime tokenizer.')
        self.runtime_limit_tokens = runtime_limit_tokens
        self.recipe_version = recipe_version
        self.count = token_counter
        self.serialize = serializer or (lambda blocks: "\n".join(f"<|im_start|>{b.role}\n{b.rendered_content}<|im_end|>" for b in blocks))

    def compile(
        self,
        runtime_inputs: Mapping[str, Any],
        memory_snapshot: Optional[SessionMemorySnapshot] = None,
    ) -> ContextCompilationResult:
        """Compile blocks into serialized input, enforcing token limits and output reserve."""
        if (self.runtime_limit_tokens is not None
                and self.recipe_version.model_limit_tokens > self.runtime_limit_tokens):
            raise ContextOverflowError('The configured input/output limit exceeds the pinned runtime context.')
        allowed = set(ContextRecipeVersion.BudgetPolicy.values)
        if self.recipe_version.budget_policy not in allowed:
            raise ContextOverflowError('Unknown overflow policy. Save a revision with an explicit supported policy.')
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

            rendered = str(raw)
            original_tokens = self.count(rendered)
            was_truncated = False
            if b.max_tokens is not None and original_tokens > b.max_tokens:
                if b.priority <= 1:
                    raise ContextOverflowError(f'Required block {b.block_key} exceeds its declared block cap; required content is never truncated.')
                low, high = 0, len(rendered)
                while low < high:
                    middle = (low + high + 1) // 2
                    if self.count(rendered[:middle]) <= b.max_tokens:
                        low = middle
                    else:
                        high = middle - 1
                rendered = rendered[:low]
                if self.count(rendered)>b.max_tokens:
                    raise ContextOverflowError(f'Block {b.block_key} cannot fit its declared token cap, including tokenizer overhead.')
                was_truncated = True
                truncated.append({"block_key": b.block_key, "reason": "block_token_limit", "original_tokens": original_tokens, "tokens_retained": self.count(rendered), "block_type":b.block_type, "required":False})
            tok_count = self.count(rendered)

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
            return self.serialize(blocks)

        total_tokens = self.count(serialized(candidate_blocks))
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
            while self.count(serialized(active_list)) > max_budget and active_list:
                optional = [block for block in active_list if block.priority>1]
                if self.recipe_version.budget_policy == ContextRecipeVersion.BudgetPolicy.TRIM_OPTIONAL_EVIDENCE:
                    optional = [block for block in optional if block.block_type==ContextBlockRevision.BlockType.EVIDENCE]
                if not optional:
                    raise ContextOverflowError('Required context, unselected categories or template overhead exceed the budget; no declared optional blocks can be omitted.')
                lowest = max(optional,key=lambda block:block.priority)

                tokens_before = self.count(serialized(active_list))
                active_list.remove(lowest)
                omitted.append({
                    "block_key": lowest.block_key,
                    "reason": "token_budget_overflow",
                    "priority": lowest.priority,
                    "block_type": lowest.block_type,
                    "required":False,
                    "tokens_omitted": tokens_before - self.count(serialized(active_list)),
                })

            included = active_list
        else:
            included = candidate_blocks

        included_keys={block.block_key for block in included}
        for row in truncated:row['included_in_final']=row['block_key'] in included_keys

        # Step 3: Serialize prompt in strict block order
        included.sort(key=lambda x: block_order[x.block_key])

        serialized = self.serialize(included)
        final_input_tokens = self.count(serialized)
        if final_input_tokens>max_budget:
            raise ContextOverflowError('The serialized template exceeds the input budget after optional omissions. Increase the limit or reduce the output reserve.')
        # Prefix differences attribute wrappers and special tokens without inventing per-block counts.
        prior = 0
        for position, block in enumerate(included):
            prefix_tokens = self.count(self.serialize(included[:position + 1]))
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
