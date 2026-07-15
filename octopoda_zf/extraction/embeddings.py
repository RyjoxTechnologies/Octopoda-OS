"""Embedding + similarity abstraction for dedup.

Production uses BGE-small (already pooled in the runtime). For unit tests and
offline use we provide a deterministic lexical embedder so dedup logic can be
tested with zero network and zero model load.

The `Embedder` protocol is the seam: production wires the BGE-backed
implementation; tests wire `LexicalEmbedder`.
"""

from __future__ import annotations

import math
import re
from typing import Protocol, runtime_checkable

_TOKEN = re.compile(r"\b\w+\b")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


@runtime_checkable
class Embedder(Protocol):
    """Anything that can score semantic similarity between two strings."""

    def similarity(self, a: str, b: str) -> float:
        """Return cosine-like similarity in [0, 1]."""
        ...


class LexicalEmbedder:
    """Token-overlap cosine similarity. Deterministic, no dependencies.

    Not as good as BGE semantically, but:
    - perfect for testing dedup logic (we control the inputs),
    - a safe offline fallback if the embedding service is unavailable.

    Uses term-frequency cosine over a simple tokenization.
    """

    def _vector(self, text: str) -> dict[str, float]:
        vec: dict[str, float] = {}
        for tok in _tokens(text):
            vec[tok] = vec.get(tok, 0.0) + 1.0
        return vec

    def similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        va = self._vector(a)
        vb = self._vector(b)
        if not va or not vb:
            return 0.0
        # cosine of the two TF vectors
        common = set(va) & set(vb)
        dot = sum(va[t] * vb[t] for t in common)
        na = math.sqrt(sum(v * v for v in va.values()))
        nb = math.sqrt(sum(v * v for v in vb.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


class CachedEmbedder:
    """Wraps any Embedder with a small LRU-ish cache on similarity pairs.

    Recall/dedup query the same pairs repeatedly within a batch; caching keeps
    us inside the latency budget (PERFORMANCE_BUDGET.md: dedup p95 <= 30ms).
    """

    def __init__(self, inner: Embedder, max_entries: int = 4096) -> None:
        self._inner = inner
        self._cache: dict[tuple[str, str], float] = {}
        self._max = max_entries

    def similarity(self, a: str, b: str) -> float:
        key = (a, b) if a <= b else (b, a)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        val = self._inner.similarity(a, b)
        if len(self._cache) >= self._max:
            # cheap eviction: clear half when full (avoids per-call ordering cost)
            for k in list(self._cache.keys())[: self._max // 2]:
                del self._cache[k]
        self._cache[key] = val
        return val
