"""Minimal reverse-mode automatic differentiation for the pure-Python reference runtime.

This module exists so the reference CPU runtime can execute a *general* decoder-only
transformer (causal attention, layer norm, GELU, residual stream) with analytically
correct gradients, without depending on a tensor framework. It is intentionally small
and scalar-valued; it is a correctness-first reference, not a performance path.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence


class Value:
    """A scalar node in a reverse-mode automatic differentiation graph."""

    __slots__ = ("data", "grad", "_backward", "_prev")

    def __init__(self, data: float, _prev: tuple["Value", ...] = ()) -> None:
        self.data = float(data)
        self.grad = 0.0
        self._prev = _prev
        self._backward = lambda: None

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Value(data={self.data!r}, grad={self.grad!r})"

    # -- additive ops -------------------------------------------------------
    def __add__(self, other: "Value | float") -> "Value":
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data + other.data, (self, other))

        def _backward() -> None:
            self.grad += out.grad
            other.grad += out.grad

        out._backward = _backward
        return out

    def __radd__(self, other: "Value | float") -> "Value":
        return self + other

    def __neg__(self) -> "Value":
        return self * -1.0

    def __sub__(self, other: "Value | float") -> "Value":
        other = other if isinstance(other, Value) else Value(other)
        return self + (-other)

    def __rsub__(self, other: "Value | float") -> "Value":
        return (-self) + other

    # -- multiplicative ops -------------------------------------------------
    def __mul__(self, other: "Value | float") -> "Value":
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data * other.data, (self, other))

        def _backward() -> None:
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad

        out._backward = _backward
        return out

    def __rmul__(self, other: "Value | float") -> "Value":
        return self * other

    def __truediv__(self, other: "Value | float") -> "Value":
        other = other if isinstance(other, Value) else Value(other)
        return self * (other ** -1.0)

    def __rtruediv__(self, other: "Value | float") -> "Value":
        other = other if isinstance(other, Value) else Value(other)
        return other * (self ** -1.0)

    def __pow__(self, exponent: float) -> "Value":
        if not isinstance(exponent, (int, float)):
            raise TypeError("Only real powers are supported.")
        out = Value(self.data ** exponent, (self,))

        def _backward() -> None:
            self.grad += exponent * (self.data ** (exponent - 1)) * out.grad

        out._backward = _backward
        return out

    # -- elementary functions ----------------------------------------------
    def exp(self) -> "Value":
        out = Value(math.exp(self.data), (self,))

        def _backward() -> None:
            self.grad += out.data * out.grad

        out._backward = _backward
        return out

    def log(self) -> "Value":
        out = Value(math.log(self.data), (self,))

        def _backward() -> None:
            self.grad += (1.0 / self.data) * out.grad

        out._backward = _backward
        return out

    def tanh(self) -> "Value":
        t = math.tanh(self.data)
        out = Value(t, (self,))

        def _backward() -> None:
            self.grad += (1.0 - t * t) * out.grad

        out._backward = _backward
        return out

    def relu(self) -> "Value":
        out = Value(self.data if self.data > 0.0 else 0.0, (self,))

        def _backward() -> None:
            self.grad += (1.0 if self.data > 0.0 else 0.0) * out.grad

        out._backward = _backward
        return out

    def backward(self) -> None:
        """Accumulate gradients for the whole graph rooted at this node."""
        topo: list[Value] = []
        seen: set[int] = set()
        stack: list[tuple[Value, bool]] = [(self, False)]
        while stack:
            node, processed = stack.pop()
            if processed:
                topo.append(node)
                continue
            if id(node) in seen:
                continue
            seen.add(id(node))
            stack.append((node, True))
            for child in node._prev:
                if id(child) not in seen:
                    stack.append((child, False))
        self.grad = 1.0
        for node in reversed(topo):
            node._backward()


def sum_values(values: Sequence[Value]) -> Value:
    total = Value(0.0)
    for value in values:
        total = total + value
    return total


def mean(values: Sequence[Value]) -> Value:
    if not values:
        raise ValueError("mean of an empty sequence is undefined.")
    return sum_values(values) / float(len(values))


def dot(a: Sequence[Value], b: Sequence[Value]) -> Value:
    if len(a) != len(b):
        raise ValueError("dot product requires equal-length vectors.")
    total = Value(0.0)
    for x, y in zip(a, b):
        total = total + (x * y)
    return total


def matmul(a: Sequence[Sequence[Value]], b: Sequence[Sequence[Value]]) -> list[list[Value]]:
    """Multiply an (m, k) matrix by a (k, n) matrix."""
    if not a or not b:
        raise ValueError("matmul requires non-empty matrices.")
    k = len(b)
    if len(a[0]) != k:
        raise ValueError("matmul inner dimensions do not match.")
    n = len(b[0])
    out: list[list[Value]] = []
    for row in a:
        out_row: list[Value] = []
        for j in range(n):
            total = Value(0.0)
            for p in range(k):
                total = total + row[p] * b[p][j]
            out_row.append(total)
        out.append(out_row)
    return out


def softmax(values: Sequence[Value]) -> list[Value]:
    if not values:
        raise ValueError("softmax of an empty sequence is undefined.")
    peak = max(v.data for v in values)
    shifted = [v - peak for v in values]
    exps = [v.exp() for v in shifted]
    total = sum_values(exps)
    return [e / total for e in exps]


def softmax_cross_entropy(logits: Sequence[Value], target: int) -> Value:
    probs = softmax(logits)
    return -probs[target].log()


def layer_norm(
    x: Sequence[Value],
    gamma: Sequence[Value],
    beta: Sequence[Value],
    eps: float = 1e-5,
) -> list[Value]:
    if len(x) != len(gamma) or len(x) != len(beta):
        raise ValueError("layer_norm parameter dimensions do not match.")
    center = mean(x)
    variance = mean([(xi - center) ** 2 for xi in x])
    inv_std = (variance + eps) ** -0.5
    return [(xi - center) * inv_std * gamma[i] + beta[i] for i, xi in enumerate(x)]


def gelu(x: Value) -> Value:
    """GELU using the tanh approximation."""
    coeff = math.sqrt(2.0 / math.pi)
    return 0.5 * x * (1.0 + (coeff * (x + 0.044715 * (x ** 3))).tanh())


def iter_params(value: "Value | Iterable") -> Iterable[Value]:
    """Depth-first walk over nested lists/dicts of Value instances."""
    if isinstance(value, Value):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_params(item)
        return
    if isinstance(value, (str, bytes)):
        return
    for item in value:
        yield from iter_params(item)
