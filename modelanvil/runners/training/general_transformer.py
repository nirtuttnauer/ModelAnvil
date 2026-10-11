"""General decoder-only transformer SFT reference runtime (pure Python).

This is a real, framework-free transformer: token + positional embeddings, pre-norm
causal multi-head self-attention, GELU feed-forward blocks and a language-model head.
It trains with analytic gradients (see :mod:`modelanvil.runners.training.autograd`) and
updates parameters with AdamW. Checkpoints reuse the repository's Safetensors codec.

Support envelope (honest, by construction):
- Runs on CPU only, single process. No GPU, distributed, remote-worker or provider support.
- This is a correctness reference for small models, not a performance or production path.
"""
from __future__ import annotations

import math
import random
from typing import Any, Optional, Sequence

from modelanvil.runners.training.autograd import (
    Value,
    gelu,
    iter_params,
    layer_norm,
    mean,
    softmax,
    softmax_cross_entropy,
)

GENERAL_RUNTIME_ID = "modelanvil.general-transformer-sft.v1"

SPECIAL_TOKENS = ("<pad>", "<bos>", "<eos>", "<unk>")
PAD_ID, BOS_ID, EOS_ID, UNK_ID = 0, 1, 2, 3


def format_chat_messages(messages: Sequence[dict[str, Any]]) -> str:
    """Render OpenAI-style chat messages with an explicit, inspectable template."""
    if not messages:
        raise ValueError("Chat templating requires at least one message.")
    rendered: list[str] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = str(message.get("content", ""))
        rendered.append(f"<|{role}|>\n{content}\n")
    return "".join(rendered)


class ByteTokenizer:
    """Byte-level tokenizer: general text, no vocabulary preprocessing required."""

    def __init__(self) -> None:
        self.vocabulary_size = len(SPECIAL_TOKENS) + 256
        self.special_tokens = {
            "pad_token": PAD_ID,
            "bos_token": BOS_ID,
            "eos_token": EOS_ID,
            "unk_token": UNK_ID,
        }

    def encode(self, text: str, *, add_special_tokens: bool = True) -> list[int]:
        body = [len(SPECIAL_TOKENS) + b for b in text.encode("utf-8")]
        if add_special_tokens:
            return [BOS_ID, *body, EOS_ID]
        return body

    def decode(self, ids: Sequence[int]) -> str:
        body = bytes(i - len(SPECIAL_TOKENS) for i in ids if i >= len(SPECIAL_TOKENS))
        return body.decode("utf-8", errors="replace")


def _rand_matrix(rows: int, cols: int, rng: random.Random, scale: float) -> list[list[Value]]:
    return [[Value(rng.gauss(0.0, scale)) for _ in range(cols)] for _ in range(rows)]


def _filled_matrix(rows: int, cols: int, value: float) -> list[list[Value]]:
    return [[Value(value) for _ in range(cols)] for _ in range(rows)]


def linear(x: Sequence[Value], weight: Sequence[Sequence[Value]]) -> list[Value]:
    """Compute ``x @ weight`` where weight is stored as (in_dim, out_dim)."""
    in_dim = len(weight)
    if len(x) != in_dim:
        raise ValueError("linear input dimension does not match the weight matrix.")
    out_dim = len(weight[0])
    out: list[Value] = []
    for j in range(out_dim):
        total = Value(0.0)
        for i in range(in_dim):
            total = total + x[i] * weight[i][j]
        out.append(total)
    return out


def _dot(a: Sequence[Value], b: Sequence[Value]) -> Value:
    total = Value(0.0)
    for x, y in zip(a, b):
        total = total + x * y
    return total


class GeneralTransformer:
    """A small decoder-only transformer with causal multi-head attention."""

    def __init__(
        self,
        *,
        vocab_size: int,
        n_layer: int = 2,
        n_head: int = 2,
        n_embd: int = 16,
        context_window: int = 32,
        seed: int = 1234,
    ) -> None:
        if vocab_size < 4:
            raise ValueError("vocab_size must be at least 4 for special tokens.")
        if n_embd % n_head != 0:
            raise ValueError("n_embd must be divisible by n_head.")
        if n_layer < 1 or n_head < 1 or context_window < 2:
            raise ValueError("Invalid transformer configuration.")
        self.vocab_size = vocab_size
        self.n_layer = n_layer
        self.n_head = n_head
        self.n_embd = n_embd
        self.context_window = context_window
        rng = random.Random(seed)
        scale = 0.02

        tensors: dict[str, list[list[Value]]] = {}
        tensors["transformer.wte.weight"] = _rand_matrix(vocab_size, n_embd, rng, scale)
        tensors["transformer.wpe.weight"] = _rand_matrix(context_window, n_embd, rng, scale)
        for layer in range(n_layer):
            prefix = f"transformer.layers.{layer}"
            tensors[f"{prefix}.attn_ln.weight"] = _filled_matrix(n_embd, 1, 1.0)
            tensors[f"{prefix}.attn_ln.bias"] = _filled_matrix(n_embd, 1, 0.0)
            for proj in ("q", "k", "v", "o"):
                tensors[f"{prefix}.attn.{proj}.weight"] = _rand_matrix(n_embd, n_embd, rng, scale)
            tensors[f"{prefix}.mlp_ln.weight"] = _filled_matrix(n_embd, 1, 1.0)
            tensors[f"{prefix}.mlp_ln.bias"] = _filled_matrix(n_embd, 1, 0.0)
            tensors[f"{prefix}.mlp.fc1.weight"] = _rand_matrix(n_embd, 4 * n_embd, rng, scale)
            tensors[f"{prefix}.mlp.fc2.weight"] = _rand_matrix(4 * n_embd, n_embd, rng, scale)
        tensors["transformer.ln_f.weight"] = _filled_matrix(n_embd, 1, 1.0)
        tensors["transformer.ln_f.bias"] = _filled_matrix(n_embd, 1, 0.0)
        tensors["lm_head.weight"] = _rand_matrix(n_embd, vocab_size, rng, scale)
        self.tensors = tensors

    # -- parameter access ---------------------------------------------------
    def parameters(self) -> list[Value]:
        return list(iter_params(self.tensors))

    def zero_grad(self) -> None:
        for param in self.parameters():
            param.grad = 0.0

    def _norm_params(self, prefix: str) -> tuple[list[Value], list[Value]]:
        gamma = [row[0] for row in self.tensors[f"{prefix}.weight"]]
        beta = [row[0] for row in self.tensors[f"{prefix}.bias"]]
        return gamma, beta

    # -- forward pass -------------------------------------------------------
    def _attention(
        self,
        x: list[list[Value]],
        prefix: str,
    ) -> list[list[Value]]:
        token_count = len(x)
        head_size = self.n_embd // self.n_head
        wq = self.tensors[f"{prefix}.attn.q.weight"]
        wk = self.tensors[f"{prefix}.attn.k.weight"]
        wv = self.tensors[f"{prefix}.attn.v.weight"]
        wo = self.tensors[f"{prefix}.attn.o.weight"]
        queries = [linear(x[t], wq) for t in range(token_count)]
        keys = [linear(x[t], wk) for t in range(token_count)]
        values = [linear(x[t], wv) for t in range(token_count)]
        concatenated: list[list[Optional[Value]]] = [[None] * self.n_embd for _ in range(token_count)]
        scale = 1.0 / math.sqrt(head_size)
        for head in range(self.n_head):
            lo = head * head_size
            hi = lo + head_size
            for position in range(token_count):
                query = queries[position][lo:hi]
                scores = [_dot(query, keys[j][lo:hi]) * scale for j in range(position + 1)]
                weights = softmax(scores)
                for channel in range(head_size):
                    total = Value(0.0)
                    for j in range(position + 1):
                        total = total + weights[j] * values[j][lo + channel]
                    concatenated[position][lo + channel] = total
        dense = [[value for value in row] for row in concatenated]
        return [linear(row, wo) for row in dense]  # type: ignore[arg-type]

    def _block(self, x: list[list[Value]], layer: int) -> list[list[Value]]:
        prefix = f"transformer.layers.{layer}"
        attn_gamma, attn_beta = self._norm_params(f"{prefix}.attn_ln")
        normed = [layer_norm(row, attn_gamma, attn_beta) for row in x]
        attended = self._attention(normed, prefix)
        x = [[x[t][c] + attended[t][c] for c in range(self.n_embd)] for t in range(len(x))]
        mlp_gamma, mlp_beta = self._norm_params(f"{prefix}.mlp_ln")
        normed2 = [layer_norm(row, mlp_gamma, mlp_beta) for row in x]
        fc1 = self.tensors[f"{prefix}.mlp.fc1.weight"]
        fc2 = self.tensors[f"{prefix}.mlp.fc2.weight"]
        hidden = [[gelu(v) for v in linear(row, fc1)] for row in normed2]
        projected = [linear(row, fc2) for row in hidden]
        return [[x[t][c] + projected[t][c] for c in range(self.n_embd)] for t in range(len(x))]

    def forward_logits(self, tokens: Sequence[int]) -> list[list[Value]]:
        if not tokens or len(tokens) > self.context_window:
            raise ValueError(f"Sequence length must be within 1 and {self.context_window} tokens.")
        wte = self.tensors["transformer.wte.weight"]
        wpe = self.tensors["transformer.wpe.weight"]
        x = [
            [wte[tokens[t]][c] + wpe[t][c] for c in range(self.n_embd)]
            for t in range(len(tokens))
        ]
        for layer in range(self.n_layer):
            x = self._block(x, layer)
        gamma, beta = self._norm_params("transformer.ln_f")
        x = [layer_norm(row, gamma, beta) for row in x]
        head = self.tensors["lm_head.weight"]
        return [linear(row, head) for row in x]

    def loss(self, tokens: Sequence[int]) -> Value:
        if len(tokens) < 2:
            raise ValueError("Training loss requires at least two tokens.")
        logits = self.forward_logits(tokens)
        return mean([
            softmax_cross_entropy(logits[t], tokens[t + 1])
            for t in range(len(tokens) - 1)
        ])

    # -- checkpoint codec ---------------------------------------------------
    def export_tensors(self) -> dict[str, tuple[list[int], list[float]]]:
        exported: dict[str, tuple[list[int], list[float]]] = {}
        for name, matrix in self.tensors.items():
            rows = len(matrix)
            cols = len(matrix[0])
            exported[name] = ([rows, cols], [value.data for row in matrix for value in row])
        return exported

    def import_tensors(self, exported: dict[str, tuple[list[int], list[float]]]) -> None:
        missing = set(self.tensors) - set(exported)
        if missing:
            raise ValueError(f"Checkpoint is missing tensors: {sorted(missing)[:3]}.")
        for name, (shape, flat) in exported.items():
            if name not in self.tensors:
                raise ValueError(f"Checkpoint contains an unexpected tensor {name!r}.")
            matrix = self.tensors[name]
            rows, cols = len(matrix), len(matrix[0])
            if list(shape) != [rows, cols] or len(flat) != rows * cols:
                raise ValueError(f"Checkpoint shape mismatch for {name!r}.")
            index = 0
            for r in range(rows):
                for c in range(cols):
                    matrix[r][c].data = float(flat[index])
                    index += 1


class AdamW:
    """Adam with decoupled weight decay."""

    def __init__(
        self,
        params: Sequence[Value],
        *,
        learning_rate: float = 1e-2,
        beta1: float = 0.9,
        beta2: float = 0.999,
        epsilon: float = 1e-8,
        weight_decay: float = 0.0,
    ) -> None:
        self.params = list(params)
        self.learning_rate = learning_rate
        self.beta1 = beta1
        self.beta2 = beta2
        self.epsilon = epsilon
        self.weight_decay = weight_decay
        self._m = [0.0] * len(self.params)
        self._v = [0.0] * len(self.params)
        self._t = 0

    def zero_grad(self) -> None:
        for param in self.params:
            param.grad = 0.0

    def step(self) -> None:
        self._t += 1
        correction1 = 1.0 - self.beta1 ** self._t
        correction2 = 1.0 - self.beta2 ** self._t
        for i, param in enumerate(self.params):
            gradient = param.grad
            self._m[i] = self.beta1 * self._m[i] + (1.0 - self.beta1) * gradient
            self._v[i] = self.beta2 * self._v[i] + (1.0 - self.beta2) * gradient * gradient
            m_hat = self._m[i] / correction1
            v_hat = self._v[i] / correction2
            update = m_hat / (math.sqrt(v_hat) + self.epsilon)
            if self.weight_decay:
                update += self.weight_decay * param.data
            param.data -= self.learning_rate * update


def prune_context(tokens: Sequence[int], context_window: int) -> list[int]:
    """Right-align a training window; raise if the sample cannot fit an input/target pair."""
    if len(tokens) < 2:
        raise ValueError("Training samples need at least two tokens.")
    return list(tokens[-context_window:])


def runtime_manifest() -> dict[str, Any]:
    """Server-owned manifest describing this reference general-transformer runtime."""
    return {
        "schema_version": "1.0",
        "adapter_id": GENERAL_RUNTIME_ID,
        "version": "1",
        "platform_api": "v1",
        "image": "local-python-contract:general-transformer-sft",
        "license": "local reference; license not asserted",
        "capabilities": [{
            "kind": "train",
            "architectures": [GENERAL_RUNTIME_ID],
            "formats": ["text", "chat"],
            "recovery": "verified_checkpoint",
        }],
        "resources": {
            "cpu_cores": 1,
            "gpu_count": 0,
            "distributed": False,
            "memory_bytes": 512 * 1024 * 1024,
        },
        "limitations": [
            "Pure-Python CPU reference; no GPU, distributed or remote-worker support.",
            "Intended for small models and tests, not production throughput.",
        ],
    }
