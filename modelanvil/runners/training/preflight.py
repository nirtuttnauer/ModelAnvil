"""Training configuration preflight validation, FLOP/cost estimation, and sample preview (WP-08 / TECH-016)."""
from __future__ import annotations

import math
from typing import Any, Optional

from django.core.exceptions import ValidationError

from modelanvil.runners.compatibility import validate_model_tokenizer_compatibility
from modelanvil.runners.models import ModelVersion, TokenizerVersion, TrainingRun


SUPPORTED_PRECISIONS = {"bf16", "fp16", "fp32"}
DEFAULT_TFLOPS_PER_SLOT = 150.0  # reference GPU/accelerator slot nominal throughput
DEFAULT_SLOT_HOURLY_RATE = 2.50  # dollars per slot-hour


def estimate_parameter_count(
    architecture: dict[str, Any],
    vocab_size: int,
) -> int:
    """Estimate transformer parameter count from architecture hyperparameters."""
    n_layer = int(architecture.get("n_layer", 12))
    n_embd = int(architecture.get("n_embd", 768))
    attn_and_mlp = 12 * n_layer * (n_embd ** 2)
    embeddings = 2 * vocab_size * n_embd
    norms = 4 * n_layer * n_embd
    return attn_and_mlp + embeddings + norms


def estimate_training_flops(
    params: int,
    total_tokens: int,
    *,
    is_lora: bool = False,
) -> float:
    """Estimate training FLOPs (Chinchilla rule: ~6 FLOPs per parameter per token for full backprop)."""
    factor = 2.0 if is_lora else 6.0
    return float(factor * params * total_tokens)


def validate_training_preflight(
    *,
    recipe_type: str,
    tokenizer_version: TokenizerVersion,
    base_model_version: Optional[ModelVersion] = None,
    hyperparameters: Optional[dict[str, Any]] = None,
    hardware_config: Optional[dict[str, Any]] = None,
    budget_limit_dollars: Optional[float] = None,
) -> dict[str, Any]:
    """Validate all training prerequisites before allocating compute or launching jobs (TECH-016).

    Guarantees:
    - Unsupported recipe and precision combinations fail preflight.
    - Scratch pretraining begins without base model and has verified architecture dimensions.
    - SFT and adapter recipes require valid base models and compatible tokenizers.
    - Estimates parameter count, FLOPs, execution time, and compute budget.
    """
    params = hyperparameters or {}
    hw = hardware_config or {}

    # 1. Validate recipe type
    if recipe_type not in TrainingRun.RecipeType.values:
        raise ValidationError(f"Unsupported recipe type {recipe_type!r}.")

    # 2. Validate hardware precision
    precision = hw.get("precision", "bf16").lower()
    if precision not in SUPPORTED_PRECISIONS:
        raise ValidationError(
            f"Precision {precision!r} is unsupported. Allowed precisions: {sorted(SUPPORTED_PRECISIONS)}."
        )

    slots_required = int(hw.get("slots_required", 1))
    if slots_required < 1:
        raise ValidationError("slots_required must be at least 1.")

    # 3. Recipe-specific constraints
    if recipe_type == TrainingRun.RecipeType.SCRATCH_PRETRAINING:
        if base_model_version is not None:
            raise ValidationError(
                "Scratch pretraining must begin from recorded random initialization; base_model_version must be None."
            )
        arch = params.get("architecture")
        if not arch or not isinstance(arch, dict):
            raise ValidationError(
                "Scratch pretraining requires an explicit architecture specification (n_layer, n_embd, n_head, vocab_size)."
            )
        expected_vocab = arch.get("vocab_size")
        if expected_vocab is not None and expected_vocab != tokenizer_version.vocabulary_size:
            raise ValidationError(
                f"Architecture vocab_size ({expected_vocab}) does not match tokenizer vocabulary size ({tokenizer_version.vocabulary_size})."
            )
        param_count = estimate_parameter_count(arch, tokenizer_version.vocabulary_size)

    else:
        # Fine-tuning or adapter recipes require base model
        if base_model_version is None:
            raise ValidationError(
                f"Recipe {recipe_type!r} requires a registered base_model_version."
            )

        validate_model_tokenizer_compatibility(base_model_version, tokenizer_version)

        base_meta = base_model_version.metadata or {}
        arch = base_meta.get("architecture") or {"n_layer": 12, "n_embd": 768}
        param_count = base_meta.get("parameter_count") or estimate_parameter_count(
            arch, tokenizer_version.vocabulary_size
        )

        if recipe_type == TrainingRun.RecipeType.LORA_ADAPTER:
            lora_cfg = params.get("lora_config") or {}
            r = lora_cfg.get("r", 8)
            alpha = lora_cfg.get("lora_alpha", 16)
            if r < 1 or alpha <= 0:
                raise ValidationError("Invalid LoRA configuration: rank r and lora_alpha must be positive.")

    # 4. Flop and cost estimation
    batch_size = int(params.get("batch_size", 4))
    seq_len = int(params.get("max_seq_len", 512))
    max_steps = int(params.get("max_steps", 100))
    total_tokens = batch_size * seq_len * max_steps

    is_lora = (recipe_type == TrainingRun.RecipeType.LORA_ADAPTER)
    total_flops = estimate_training_flops(param_count, total_tokens, is_lora=is_lora)

    tflops_slot = float(hw.get("tflops_per_slot", DEFAULT_TFLOPS_PER_SLOT))
    slot_rate = float(hw.get("slot_hourly_rate", DEFAULT_SLOT_HOURLY_RATE))

    # Effective throughput with 30% MFU assumption
    effective_flops_per_sec = slots_required * tflops_slot * 1e12 * 0.30
    est_seconds = total_flops / max(effective_flops_per_sec, 1e9)
    est_hours = est_seconds / 3600.0
    est_cost = est_hours * slots_required * slot_rate

    if budget_limit_dollars is not None and est_cost > budget_limit_dollars:
        raise ValidationError(
            f"Estimated training cost (${est_cost:.2f}) exceeds authorized project budget limit (${budget_limit_dollars:.2f})."
        )

    return {
        "status": "approved",
        "recipe_type": recipe_type,
        "precision": precision,
        "parameter_count": param_count,
        "total_tokens": total_tokens,
        "estimated_flops": total_flops,
        "estimated_duration_seconds": round(est_seconds, 4),
        "estimated_cost_dollars": est_cost,
        "slots_required": slots_required,
    }


def _format_sample_text(item: dict[str, Any], tokenizer: TokenizerVersion) -> str:
    if "messages" in item and tokenizer.chat_template:
        messages = item["messages"]
        formatted_text = ""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            formatted_text += f"<|{role}|>\n{content}\n"
        return formatted_text
    return str(
        item.get("text")
        or item.get("prompt", "") + " " + item.get("response", "")
        or item.get("input", "")
    ).strip()


def _pinned_character_encoder(tokenizer: TokenizerVersion):
    """Return a real character-v1 encoder only when the tokenizer pins one.

    Returns ``None`` when no honest encoding is available; callers must then report the
    token counts as unknown rather than inventing ids.
    """
    spec = (tokenizer.compatibility or {}).get("character_v1")
    if not isinstance(spec, dict):
        return None
    tokens = spec.get("tokens")
    if not isinstance(tokens, list) or len(tokens) != tokenizer.vocabulary_size or len(set(tokens)) != len(tokens):
        return None
    table = {token: index for index, token in enumerate(tokens)}
    unk_id = 3 if len(tokens) > 3 else 0

    def encode(text: str) -> list[int]:
        ids = [table.get(char, unk_id) for char in text]
        if tokenizer.special_tokens.get("bos_token"):
            ids.insert(0, 1)
        if tokenizer.special_tokens.get("eos_token"):
            ids.append(2)
        return ids

    return encode


def preview_encoded_samples(
    records: list[dict[str, Any]],
    tokenizer: TokenizerVersion,
    *,
    limit: int = 3,
    encoder: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Produce real tokenized previews of dataset samples before launching training runs.

    Only a pinned character-v1 tokenizer (or an explicit ``encoder``) can produce real
    ids. Without one, the sample is reported with ``token_count``/``sample_tokens`` set to
    ``None`` and an explicit reason, instead of invented hash-based tokens.
    """
    encode = encoder or _pinned_character_encoder(tokenizer)
    previews: list[dict[str, Any]] = []

    for item in records[:limit]:
        formatted_text = _format_sample_text(item, tokenizer)
        if encode is None:
            previews.append({
                "original_preview": formatted_text[:200],
                "token_count": None,
                "sample_tokens": None,
                "encoding": "unavailable",
                "reason": "No pinned tokenizer encoding is registered for this revision.",
            })
            continue
        tokens = list(encode(formatted_text))
        previews.append({
            "original_preview": formatted_text[:200],
            "token_count": len(tokens),
            "sample_tokens": tokens[:20],
            "encoding": "pinned",
        })

    return previews
