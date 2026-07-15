"""Extraction orchestrator.

Ties the pipeline together:

    transcript
       -> sanitize (strip secrets/PII)
       -> chunk (if long)
       -> extractor LLM (per chunk)
       -> parse (defensive JSON)
       -> build Facts
       -> within-batch dedup
       -> importance filter
       -> [returns surviving Facts]

Write-time dedup against EXISTING stored memories happens later, at write time
(deduper.decide), because it needs the agent's current memory set.

Everything here is pure given an injected LLMClient + Embedder, so the whole
pipeline is unit-testable with mocks (no network, no API key).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import prompts
from .deduper import dedupe_within_batch
from .embeddings import Embedder, LexicalEmbedder
from .importance import FilterConfig, filter_facts
from .llm import LLMClient, safe_parse_facts
from .sanitizer import sanitize
from .types import Fact, FactType

logger = logging.getLogger("octopoda.extraction")

# Rough token->char ratio for chunking without a tokenizer dependency.
_CHARS_PER_TOKEN = 4
_DEFAULT_CHUNK_TOKENS = 2000
_MAX_OUTPUT_TOKENS = 800


@dataclass
class ExtractionConfig:
    chunk_tokens: int = _DEFAULT_CHUNK_TOKENS
    max_output_tokens: int = _MAX_OUTPUT_TOKENS
    min_confidence: float = 0.6
    min_length: int = 10
    max_facts: int = 20            # hard cap per transcript (cost + pollution guard)
    llm_retries: int = 1           # retry once on unparseable output


@dataclass
class ExtractionResult:
    facts: list[Fact]
    dropped: list[tuple[Fact, str]] = field(default_factory=list)
    redactions: dict[str, int] = field(default_factory=dict)
    chunks_processed: int = 0
    llm_calls: int = 0
    parse_failures: int = 0

    @property
    def kept_count(self) -> int:
        return len(self.facts)


def _chunk(text: str, chunk_tokens: int) -> list[str]:
    """Split a transcript into chunks at line boundaries, keeping each under
    the char budget. Avoids splitting mid-line where possible."""
    max_chars = chunk_tokens * _CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > max_chars and current:
            chunks.append("".join(current))
            current = [line]
            size = len(line)
        else:
            current.append(line)
            size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _facts_from_dicts(raw_facts: list[dict]) -> list[Fact]:
    out: list[Fact] = []
    for d in raw_facts:
        try:
            fact = Fact(
                type=FactType.from_str(str(d.get("type", "memory"))),
                subject=str(d.get("subject", "")),
                predicate=str(d.get("predicate", "")),
                value=str(d.get("value", "")),
                confidence=d.get("confidence", 0.0),
                tags=list(d.get("tags", [])) if isinstance(d.get("tags"), list) else [],
            )
            if not fact.is_empty():
                out.append(fact)
        except Exception as e:  # malformed individual fact — skip, don't crash
            logger.debug("skipping malformed fact dict: %s", e)
    return out


def extract(
    transcript: str,
    llm: LLMClient,
    embedder: Embedder | None = None,
    config: ExtractionConfig | None = None,
    system_prompts: tuple[str, ...] = (),
) -> ExtractionResult:
    """Run the full extraction pipeline on one transcript.

    `system_prompts` (optional) are the agent's own system prompts, used by the
    importance filter to drop facts that merely restate instructions.
    """
    cfg = config or ExtractionConfig()
    emb = embedder or LexicalEmbedder()

    result = ExtractionResult(facts=[])

    if not transcript or not transcript.strip():
        return result

    # 1. Sanitize FIRST — secrets never reach the LLM.
    sanitized = sanitize(transcript)
    result.redactions = sanitized.redactions

    # 2. Chunk.
    chunks = _chunk(sanitized.text, cfg.chunk_tokens)

    # 3. Per-chunk extraction.
    all_facts: list[Fact] = []
    for chunk in chunks:
        result.chunks_processed += 1
        system, user = prompts.build_messages(chunk)

        parsed: list[dict] | None = None
        attempts = cfg.llm_retries + 1
        for attempt in range(attempts):
            result.llm_calls += 1
            raw = llm.complete(system=system, user=user, max_tokens=cfg.max_output_tokens)
            parsed = safe_parse_facts(raw)
            if parsed is not None:
                break
            result.parse_failures += 1
            logger.warning(
                "extractor returned unparseable output (attempt %d/%d)", attempt + 1, attempts
            )

        if parsed is None:
            # Fail-soft: this chunk yields nothing rather than crashing the run.
            continue

        all_facts.extend(_facts_from_dicts(parsed))

    # 4. Within-batch dedup (overlapping chunks may repeat facts).
    deduped = dedupe_within_batch(all_facts, emb)

    # 5. Importance filter.
    kept, dropped = filter_facts(
        deduped,
        FilterConfig(min_confidence=cfg.min_confidence, min_length=cfg.min_length),
        system_prompts=system_prompts,
    )
    result.dropped = dropped

    # 6. Hard cap (cost + pollution). Keep highest-confidence first.
    kept.sort(key=lambda f: f.confidence, reverse=True)
    if len(kept) > cfg.max_facts:
        for overflow in kept[cfg.max_facts :]:
            result.dropped.append((overflow, f"exceeded max_facts cap ({cfg.max_facts})"))
        kept = kept[: cfg.max_facts]

    result.facts = kept
    return result
