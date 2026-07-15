"""Write-time dedup guard (ADR-005).

Before a fact is written via remember(), check it against recent existing
memories. If it's near-identical to one we already have, merge into the
existing memory (bump occurrences, refresh timestamp) instead of inserting a
duplicate.

This is the critical defense against memory pollution under auto-instrument
(R4): agents loop through similar prompts, so without write-time dedup the
free-tier memory cap blows out in days.

Two dedup passes use this module:
- within-batch: dedupe facts extracted from overlapping transcript chunks
- write-time: dedupe a new fact against existing stored memories

Both are pure functions over an injected `Embedder` so they're testable with
the lexical embedder (no model, no network).
"""

from __future__ import annotations

from dataclasses import dataclass

from .embeddings import Embedder, LexicalEmbedder
from .types import Fact

DEFAULT_WRITE_THRESHOLD = 0.92   # write-time: merge if >= this
DEFAULT_BATCH_THRESHOLD = 0.95   # within-batch: stricter (same extraction run)


@dataclass
class DedupDecision:
    action: str           # "insert" or "merge"
    target: Fact | None   # the existing fact to merge into (when action == merge)
    similarity: float


def merge_facts(existing: Fact, incoming: Fact) -> Fact:
    """Merge `incoming` into `existing`. Existing wins on identity; we bump
    occurrences and keep the higher confidence + union of tags."""
    existing.occurrences += incoming.occurrences
    existing.confidence = max(existing.confidence, incoming.confidence)
    for tag in incoming.tags:
        if tag not in existing.tags:
            existing.tags.append(tag)
    # Prefer the longer value (usually more informative) if types match.
    if incoming.type == existing.type and len(incoming.to_text()) > len(existing.to_text()):
        existing.subject = incoming.subject
        existing.predicate = incoming.predicate
        existing.value = incoming.value
    return existing


def decide(
    new_fact: Fact,
    existing: list[Fact],
    embedder: Embedder | None = None,
    threshold: float = DEFAULT_WRITE_THRESHOLD,
) -> DedupDecision:
    """Decide whether `new_fact` should be inserted or merged into an existing
    fact. Returns the best match above threshold, or an insert decision."""
    emb = embedder or LexicalEmbedder()
    new_text = new_fact.to_text()
    if not new_text or not existing:
        return DedupDecision("insert", None, 0.0)

    best: Fact | None = None
    best_sim = 0.0
    for candidate in existing:
        sim = emb.similarity(new_text, candidate.to_text())
        if sim > best_sim:
            best_sim = sim
            best = candidate

    if best is not None and best_sim >= threshold:
        return DedupDecision("merge", best, best_sim)
    return DedupDecision("insert", None, best_sim)


def dedupe_within_batch(
    facts: list[Fact],
    embedder: Embedder | None = None,
    threshold: float = DEFAULT_BATCH_THRESHOLD,
) -> list[Fact]:
    """Collapse near-identical facts produced in a single extraction run
    (e.g. from overlapping transcript chunks)."""
    emb = embedder or LexicalEmbedder()
    kept: list[Fact] = []
    for f in facts:
        if f.is_empty():
            continue
        decision = decide(f, kept, emb, threshold)
        if decision.action == "merge" and decision.target is not None:
            merge_facts(decision.target, f)
        else:
            kept.append(f)
    return kept
