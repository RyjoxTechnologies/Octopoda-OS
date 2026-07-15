"""Importance filter.

After the extractor LLM produces candidate facts, this drops the weak ones
before they ever reach a memory write. This is the second line of defense
against memory pollution (R4) and sensitive data (R14).

Filters applied, in order (first failure wins, so we can report a reason):
1. empty value
2. confidence below threshold
3. value too short to be useful
4. looks like a restatement of a system prompt
5. still contains a redaction marker or obvious secret remnant
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .types import Fact

# Tokens that strongly suggest the "fact" is really echoing instructions.
_SYSTEM_PROMPT_MARKERS = (
    "you are a",
    "your task is",
    "as an ai",
    "i am an ai",
    "return only",
    "json array",
    "do not include",
)

_REDACTION_MARKER = re.compile(r"\[REDACTED_[A-Z_]+\]")
# Leftover secret-looking remnants the sanitizer might have missed.
_RESIDUAL_SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{16,}|AKIA[0-9A-Z]{12,}")


@dataclass
class FilterConfig:
    min_confidence: float = 0.6
    min_length: int = 10
    drop_redacted: bool = True


@dataclass
class FilterResult:
    keep: bool
    reason: str  # "" when kept


def passes(
    fact: Fact,
    config: FilterConfig | None = None,
    system_prompts: tuple[str, ...] = (),
) -> FilterResult:
    """Decide whether a single fact survives. Returns keep + reason."""
    cfg = config or FilterConfig()

    text = fact.to_text()
    if not text:
        return FilterResult(False, "empty value")

    if fact.confidence < cfg.min_confidence:
        return FilterResult(False, f"confidence {fact.confidence:.2f} < {cfg.min_confidence}")

    if len(text) < cfg.min_length:
        return FilterResult(False, f"too short ({len(text)} < {cfg.min_length} chars)")

    lowered = text.lower()
    for marker in _SYSTEM_PROMPT_MARKERS:
        if marker in lowered:
            return FilterResult(False, f"looks like system-prompt restatement ('{marker}')")

    # If the caller passed the actual system prompts used, check direct overlap.
    for sp in system_prompts:
        if sp and (sp.lower() in lowered or lowered in sp.lower()):
            return FilterResult(False, "matches a known system prompt")

    if cfg.drop_redacted and _REDACTION_MARKER.search(text):
        return FilterResult(False, "contains redaction marker (sensitive)")

    if _RESIDUAL_SECRET.search(text):
        return FilterResult(False, "contains residual secret-like token")

    return FilterResult(True, "")


def filter_facts(
    facts: list[Fact],
    config: FilterConfig | None = None,
    system_prompts: tuple[str, ...] = (),
) -> tuple[list[Fact], list[tuple[Fact, str]]]:
    """Split facts into (kept, dropped_with_reason)."""
    kept: list[Fact] = []
    dropped: list[tuple[Fact, str]] = []
    for f in facts:
        result = passes(f, config, system_prompts)
        if result.keep:
            kept.append(f)
        else:
            dropped.append((f, result.reason))
    return kept, dropped
