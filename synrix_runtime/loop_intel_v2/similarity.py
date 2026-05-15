"""Deterministic similarity functions.

Shared across classifiers that need to compare values without calling an
embedding service. When real embeddings are available (via the main
runtime), higher-layer code can replace these — but classifiers must
remain deterministic for unit tests, so the default uses only stdlib.
"""

from __future__ import annotations

import difflib
import json
from typing import Any


def _stringify(value: Any) -> str:
    """Stable string form of any value."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def text_similarity(a: Any, b: Any) -> float:
    """Return similarity ratio in [0.0, 1.0].

    Uses stdlib difflib.SequenceMatcher — deterministic, no external deps.
    For strings, measures shared subsequences. For non-string objects,
    compares their canonical JSON form.

    Not a replacement for semantic embeddings; it's a useful proxy when
    the two objects overlap substantially in their serialized content.
    """
    s1 = _stringify(a)
    s2 = _stringify(b)
    if not s1 and not s2:
        return 1.0
    if s1 == s2:
        return 1.0
    return difflib.SequenceMatcher(None, s1, s2).ratio()


def pairwise_min_similarity(values: list) -> float:
    """Return the minimum pairwise similarity across the list."""
    n = len(values)
    if n < 2:
        return 1.0
    min_sim = 1.0
    for i in range(n):
        for j in range(i + 1, n):
            sim = text_similarity(values[i], values[j])
            if sim < min_sim:
                min_sim = sim
    return min_sim


def pairwise_mean_similarity(values: list) -> float:
    """Return the mean pairwise similarity."""
    n = len(values)
    if n < 2:
        return 1.0
    total = 0.0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += text_similarity(values[i], values[j])
            pairs += 1
    return total / pairs if pairs else 1.0
