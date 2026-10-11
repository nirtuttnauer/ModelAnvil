"""Tokenized and sharded dataset packaging (WP-05)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from modelanvil.data.detection import sample_text


@dataclass
class ShardDescriptor:
    """One immutable shard of tokenized/packaged records."""

    shard_id: str
    shard_index: int
    row_count: int
    token_count: int
    byte_size: int
    sha256: str
    data_bytes: bytes


@dataclass
class TokenizedShardsResult:
    """Complete sharded output with overall manifest digest."""

    manifest_digest: str
    total_rows: int
    total_tokens: int
    total_bytes: int
    shards: list[ShardDescriptor]
    shard_count: int
    metadata: dict[str, Any]


def default_tokenizer(text: str) -> list[int]:
    """Fallback deterministic UTF-8 byte tokenizer."""
    return list(text.encode("utf-8"))


def build_tokenized_shards(
    rows: list[dict[str, Any]],
    *,
    tokenizer_fn: Optional[Callable[[str], list[int]]] = None,
    shard_size_rows: int = 1000,
    vocab_size: int = 256,
) -> TokenizedShardsResult:
    """Tokenize rows and partition into bounded, hashed shards."""
    if not rows:
        raise ValueError("Cannot shard empty rows.")
    if shard_size_rows <= 0:
        raise ValueError("shard_size_rows must be positive.")

    tokenize = tokenizer_fn or default_tokenizer

    shards: list[ShardDescriptor] = []
    total_tokens = 0
    total_bytes = 0

    chunked_rows = [rows[i : i + shard_size_rows] for i in range(0, len(rows), shard_size_rows)]

    for shard_idx, chunk in enumerate(chunked_rows):
        tokenized_items: list[dict[str, Any]] = []
        shard_token_count = 0

        for row in chunk:
            text = sample_text(row)
            tokens = tokenize(text)
            shard_token_count += len(tokens)
            tokenized_items.append({
                "sample_id": row["sample_id"],
                "tokens": tokens,
                "length": len(tokens),
            })

        serialized_shard = json.dumps(tokenized_items, separators=(",", ":")).encode("utf-8")
        shard_sha256 = hashlib.sha256(serialized_shard).hexdigest()
        shard_id = f"shard-{shard_idx:05d}-{shard_sha256[:8]}"

        desc = ShardDescriptor(
            shard_id=shard_id,
            shard_index=shard_idx,
            row_count=len(chunk),
            token_count=shard_token_count,
            byte_size=len(serialized_shard),
            sha256=shard_sha256,
            data_bytes=serialized_shard,
        )
        shards.append(desc)
        total_tokens += shard_token_count
        total_bytes += len(serialized_shard)

    manifest_hasher = hashlib.sha256()
    for s in shards:
        manifest_hasher.update(s.sha256.encode("ascii"))
    manifest_digest = manifest_hasher.hexdigest()

    metadata = {
        "format": "tokenized_shards_v1",
        "vocab_size": vocab_size,
        "shard_size_rows": shard_size_rows,
        "shard_count": len(shards),
        "total_rows": len(rows),
        "total_tokens": total_tokens,
        "total_bytes": total_bytes,
        "manifest_digest": manifest_digest,
    }

    return TokenizedShardsResult(
        manifest_digest=manifest_digest,
        total_rows=len(rows),
        total_tokens=total_tokens,
        total_bytes=total_bytes,
        shards=shards,
        shard_count=len(shards),
        metadata=metadata,
    )
