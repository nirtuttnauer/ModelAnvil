#!/usr/bin/env python3
"""Independent inference process for ModelAnvil general transformer SFT exports.

No Django and no ModelAnvil imports: this file reproduces the published
``modelanvil.general-transformer-sft.v1`` tensor layout and forward pass from the
export bundle alone, so a candidate checkpoint is proved loadable and decodable
outside the server that produced it.

Run:

    .venv/bin/python -I modelanvil/runners/training/independent_infer.py \
        candidate.json --prompt 'ab' --max-new-tokens 8

This is a reference consumer for one bounded CPU runtime. It is not a serving
engine, not Hugging Face ``transformers``, and not hardware qualification.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

RUNTIME_ID = "modelanvil.general-transformer-sft.v1"
SPECIAL_TOKENS = ("<pad>", "<bos>", "<eos>", "<unk>")
BOS_ID, EOS_ID = 1, 2
MAX_WEIGHTS_BYTES = 64 * 1024 * 1024
LAYER_NORM_EPSILON = 1e-5


def encode(text: str) -> list[int]:
    return [BOS_ID, *(len(SPECIAL_TOKENS) + byte for byte in text.encode("utf-8")), EOS_ID]


def decode(ids: list[int]) -> str:
    return bytes(token - len(SPECIAL_TOKENS) for token in ids if token >= len(SPECIAL_TOKENS)).decode(
        "utf-8", errors="replace")


def _parse_config(bundle: dict[str, Any]) -> dict[str, int]:
    config = bundle.get("config.json", {})
    dimensions = [config.get(name) for name in ("vocab_size", "n_layer", "n_head", "n_embd", "context_window")]
    if any(type(value) is not int or value <= 0 for value in dimensions):
        raise ValueError("Missing or invalid transformer dimensions in the export.")
    vocab, layers, heads, width, context = dimensions
    if width % heads:
        raise ValueError("n_embd must be divisible by n_head.")
    if config.get("runtime") != RUNTIME_ID:
        raise ValueError("Export is not a general transformer runtime bundle.")
    if bundle.get("tokenizer_config.json", {}).get("kind") != "byte-v1":
        raise ValueError("Export does not pin the byte-v1 tokenizer.")
    return {"vocab_size": vocab, "n_layer": layers, "n_head": heads,
            "n_embd": width, "context_window": context}


def _expected_tensor_names(config: dict[str, int]) -> set[str]:
    names = {"transformer.wte.weight", "transformer.wpe.weight",
             "transformer.ln_f.weight", "transformer.ln_f.bias", "lm_head.weight"}
    for layer in range(config["n_layer"]):
        prefix = f"transformer.layers.{layer}"
        names.update({f"{prefix}.attn_ln.weight", f"{prefix}.attn_ln.bias", f"{prefix}.mlp_ln.weight",
                      f"{prefix}.mlp_ln.bias", f"{prefix}.attn.q.weight", f"{prefix}.attn.k.weight",
                      f"{prefix}.attn.v.weight", f"{prefix}.attn.o.weight", f"{prefix}.mlp.fc1.weight",
                      f"{prefix}.mlp.fc2.weight"})
    return names


def _unpack(raw: bytes) -> tuple[dict[str, list[list[float]]], str]:
    if len(raw) < 8:
        raise ValueError("Safetensors buffer is smaller than its header length.")
    header_length = struct.unpack("<Q", raw[:8])[0]
    if header_length > len(raw) - 8 or header_length > 1024 * 1024:
        raise ValueError("Invalid Safetensors header length.")
    header = json.loads(raw[8:8 + header_length].decode("utf-8"))
    data_start = 8 + header_length
    tensors: dict[str, list[list[float]]] = {}
    intervals = []
    for name, descriptor in header.items():
        if name == "__metadata__":
            continue
        shape = descriptor.get("shape")
        start, end = descriptor.get("data_offsets", [None, None])
        if (descriptor.get("dtype") != "F32" or not isinstance(shape, list) or len(shape) != 2
                or any(type(size) is not int or size <= 0 for size in shape)
                or type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= len(raw) - data_start
                or end - start != shape[0] * shape[1] * 4):
            raise ValueError(f"Invalid Safetensors descriptor: {name}.")
        values = struct.unpack(f"<{shape[0] * shape[1]}f", raw[data_start + start:data_start + end])
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Non-finite tensor values: {name}.")
        tensors[name] = [list(values[row * shape[1]:(row + 1) * shape[1]]) for row in range(shape[0])]
        intervals.append((start, end))
    offset = 0
    for start, end in sorted(intervals):
        if start != offset:
            raise ValueError("Safetensors data has overlapping or missing ranges.")
        offset = end
    if offset != len(raw) - data_start:
        raise ValueError("Safetensors data has unreferenced trailing bytes.")
    return tensors, hashlib.sha256(raw).hexdigest()


def _matrix(tensors: dict[str, list[list[float]]], name: str, rows: int, cols: int) -> list[list[float]]:
    matrix = tensors.get(name)
    if matrix is None or len(matrix) != rows or any(len(row) != cols for row in matrix):
        raise ValueError(f"Missing or mis-shaped tensor: {name}.")
    return matrix


def _linear(vector: list[float], weight: list[list[float]]) -> list[float]:
    """``vector @ weight`` where weight is stored as (in_dim, out_dim)."""
    out_dim = len(weight[0])
    out = [0.0] * out_dim
    for i, component in enumerate(vector):
        row = weight[i]
        for j in range(out_dim):
            out[j] += component * row[j]
    return out


def _layer_norm(row: list[float], gamma: list[float], beta: list[float]) -> list[float]:
    total = 0.0
    for value in row:
        total += value
    center = total / len(row)
    squared = 0.0
    for value in row:
        squared += (value - center) ** 2
    inverse = (squared / len(row) + LAYER_NORM_EPSILON) ** -0.5
    return [(row[i] - center) * inverse * gamma[i] + beta[i] for i in range(len(row))]


def _gelu(value: float) -> float:
    coefficient = math.sqrt(2.0 / math.pi)
    return 0.5 * value * (1.0 + math.tanh(coefficient * (value + 0.044715 * value ** 3)))


def _softmax(values: list[float]) -> list[float]:
    peak = max(values)
    exponentials = [math.exp(value - peak) for value in values]
    total = 0.0
    for value in exponentials:
        total += value
    return [value / total for value in exponentials]


def _logits(tensors: dict[str, list[list[float]]], config: dict[str, int], tokens: list[int]) -> list[list[float]]:
    width, heads, layers, vocab = config["n_embd"], config["n_head"], config["n_layer"], config["vocab_size"]
    head_size = width // heads
    embedding = _matrix(tensors, "transformer.wte.weight", vocab, width)
    position = _matrix(tensors, "transformer.wpe.weight", config["context_window"], width)
    hidden = [[embedding[tokens[t]][c] + position[t][c] for c in range(width)] for t in range(len(tokens))]
    for layer in range(layers):
        prefix = f"transformer.layers.{layer}"
        gamma = [row[0] for row in _matrix(tensors, f"{prefix}.attn_ln.weight", width, 1)]
        beta = [row[0] for row in _matrix(tensors, f"{prefix}.attn_ln.bias", width, 1)]
        normalized = [_layer_norm(row, gamma, beta) for row in hidden]
        queries = [_linear(row, _matrix(tensors, f"{prefix}.attn.q.weight", width, width)) for row in normalized]
        keys = [_linear(row, _matrix(tensors, f"{prefix}.attn.k.weight", width, width)) for row in normalized]
        values = [_linear(row, _matrix(tensors, f"{prefix}.attn.v.weight", width, width)) for row in normalized]
        scale = 1.0 / math.sqrt(head_size)
        attended = []
        for index in range(len(tokens)):
            row = [0.0] * width
            for head in range(heads):
                low, high = head * head_size, (head + 1) * head_size
                scores = []
                for j in range(index + 1):
                    total = 0.0
                    for channel in range(low, high):
                        total += queries[index][channel] * keys[j][channel]
                    scores.append(total * scale)
                weights = _softmax(scores)
                for channel in range(low, high):
                    total = 0.0
                    for j in range(index + 1):
                        total += weights[j] * values[j][channel]
                    row[channel] = total
            attended.append(row)
        output = _matrix(tensors, f"{prefix}.attn.o.weight", width, width)
        projected = [_linear(row, output) for row in attended]
        hidden = [[hidden[t][c] + projected[t][c] for c in range(width)] for t in range(len(tokens))]
        gamma = [row[0] for row in _matrix(tensors, f"{prefix}.mlp_ln.weight", width, 1)]
        beta = [row[0] for row in _matrix(tensors, f"{prefix}.mlp_ln.bias", width, 1)]
        normalized = [_layer_norm(row, gamma, beta) for row in hidden]
        expanded = [[_gelu(component) for component in _linear(row,
                   _matrix(tensors, f"{prefix}.mlp.fc1.weight", width, 4 * width))] for row in normalized]
        down = [_linear(row, _matrix(tensors, f"{prefix}.mlp.fc2.weight", 4 * width, width)) for row in expanded]
        hidden = [[hidden[t][c] + down[t][c] for c in range(width)] for t in range(len(tokens))]
    gamma = [row[0] for row in _matrix(tensors, "transformer.ln_f.weight", width, 1)]
    beta = [row[0] for row in _matrix(tensors, "transformer.ln_f.bias", width, 1)]
    head = _matrix(tensors, "lm_head.weight", width, vocab)
    return [_linear(_layer_norm(row, gamma, beta), head) for row in hidden]


def infer(bundle: dict[str, Any], prompt: str, max_new_tokens: int) -> dict[str, Any]:
    if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 32:
        raise ValueError("max_new_tokens must be between 1 and 32.")
    if not isinstance(prompt, str) or len(prompt) > 4096:
        raise ValueError("Prompt must be text up to 4096 characters.")
    encoded = bundle.get("model.safetensors.b64")
    if not isinstance(encoded, str) or len(encoded) > MAX_WEIGHTS_BYTES * 2:
        raise ValueError("Export requires bounded model.safetensors.b64 weights.")
    raw = base64.b64decode(encoded, validate=True)
    computed = hashlib.sha256(raw).hexdigest()
    if bundle.get("weights_manifest.json", {}).get("weights_sha256") != computed:
        raise ValueError("Safetensors SHA-256 verification failed or is missing from the manifest.")
    config = _parse_config(bundle)
    tensors, _ = _unpack(raw)
    if set(tensors) != _expected_tensor_names(config):
        raise ValueError("Export is missing required transformer tensors or has unsupported tensors.")
    context = list(encode(prompt))[-config["context_window"]:]
    generated: list[int] = []
    for _ in range(max_new_tokens):
        logits = _logits(tensors, config, context)[-1]
        if not all(math.isfinite(value) for value in logits):
            raise ValueError("Non-finite inference logits.")
        # Control tokens other than EOS are never emitted.
        following = max([EOS_ID, *range(4, config["vocab_size"])], key=lambda index: logits[index])
        generated.append(following)
        context = [*context, following][-config["context_window"]:]
        if following == EOS_ID:
            break
    return {
        "is_loadable": True,
        "runtime": RUNTIME_ID,
        "weights_sha256": computed,
        "prompt": prompt,
        "generated_token_ids": generated,
        "completion": decode(generated),
        "decoded_text": True,
        "verification_scope": "independent_process_stdlib_only",
        "independent_runtime_verified": True,
        "production_qualified": False,
    }


def _read_bundle(path: str) -> dict[str, Any]:
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(bundle, dict):
        raise ValueError("Export bundle must be a JSON object.")
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent consumer for ModelAnvil transformer exports.")
    parser.add_argument("bundle", help="Path to an exported candidate bundle JSON file.")
    parser.add_argument("--prompt", default="", help="Prompt text to condition decoding on.")
    parser.add_argument("--max-new-tokens", type=int, default=8, help="Bounded greedy decode length.")
    arguments = parser.parse_args(argv)
    try:
        result = infer(_read_bundle(arguments.bundle), arguments.prompt, arguments.max_new_tokens)
    except Exception as error:  # noqa: BLE001 - a failed load is the reported result
        print(json.dumps({"is_loadable": False, "error": f"{type(error).__name__}: {error}"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())