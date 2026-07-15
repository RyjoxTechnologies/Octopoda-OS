"""Build the memory-injection system message.

Given a list of MemoryHit from the cloud client, decide which to inject and
format them. Enforces:
- relevance floor (min_relevance, default 0.80): low-relevance memories add
  noise + tokens for no benefit (PERFORMANCE_BUDGET + R5 cost control).
- token cap (max_tokens, default 200, hard cap 300): injection never exceeds
  budget regardless of how many memories match.

Pure functions — no network, fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..client.api import MemoryHit

# Approximate, tokenizer-free. Matches the convention used in extraction.
_CHARS_PER_TOKEN = 4

_HEADER = "Relevant memories from previous sessions:"


@dataclass
class InjectionConfig:
    # Calibrated for BGE-small-en-v1.5 (the production embedding model): relevant
    # query/memory pairs score ~0.55-0.85, unrelated ~0.2-0.45. A 0.80 floor (the
    # original guess) discarded most genuinely-relevant memories — caught by the
    # behavioral-lift benchmark, where 5/7 correctly-retrieved facts were filtered
    # out before injection. 0.45 keeps relevant memories while rejecting noise.
    min_relevance: float = 0.45
    max_tokens: int = 200
    hard_cap_tokens: int = 300
    max_items: int = 5


def generous_injection_config() -> InjectionConfig:
    """Wider budget for DUAL STORAGE (facts + raw chunks). Lets ~4-5 verbatim
    chunks inject alongside facts within the ≤500-token guardrail.

    Measured (docs/MEMORY_QUALITY_PLAN.md §0.5): with chunks present this lifts
    facts-only 44% -> ~55% (+11pp, beats Mem0 49%).

    WARNING — only use this WHEN chunks are in the hit set. A wide budget + low
    floor on FACTS ALONE was a measured dead end (v1: 44% -> 42%): extra
    low-relevance facts are distractor noise the answerer sometimes follows. The
    win is the chunk REPRESENTATION, not a looser filter."""
    return InjectionConfig(
        min_relevance=0.0, max_items=10, max_tokens=450, hard_cap_tokens=500
    )


def estimate_tokens(text: str) -> int:
    """Rough token estimate without a tokenizer dependency."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def select_memories(
    hits: list[MemoryHit],
    config: InjectionConfig | None = None,
) -> list[MemoryHit]:
    """Filter + order memories for injection.

    - drop below relevance floor
    - drop empty values
    - sort by score desc
    - take top max_items
    - stop once adding the next would exceed the token budget
    """
    cfg = config or InjectionConfig()
    eligible = [
        h for h in hits if h.value.strip() and h.score >= cfg.min_relevance
    ]
    eligible.sort(key=lambda h: h.score, reverse=True)

    selected: list[MemoryHit] = []
    running_tokens = estimate_tokens(_HEADER)
    for h in eligible[: cfg.max_items]:
        line_tokens = estimate_tokens(f"- {h.value}")
        if running_tokens + line_tokens > cfg.hard_cap_tokens:
            break
        if running_tokens + line_tokens > cfg.max_tokens and selected:
            # soft cap: keep at least one, but stop adding once over soft budget
            break
        selected.append(h)
        running_tokens += line_tokens
    return selected


def build_injection(
    hits: list[MemoryHit],
    config: InjectionConfig | None = None,
) -> str | None:
    """Return the system-message text to inject, or None if nothing qualifies.

    Returning None (not an empty string) lets the caller skip injection
    entirely rather than prepend a pointless empty block.
    """
    selected = select_memories(hits, config)
    if not selected:
        return None
    lines = [_HEADER]
    for h in selected:
        lines.append(f"- {h.value}")
    return "\n".join(lines)


def injected_token_estimate(hits: list[MemoryHit], config: InjectionConfig | None = None) -> int:
    """How many tokens the injection would add (for telemetry/cost tracking)."""
    text = build_injection(hits, config)
    return estimate_tokens(text) if text else 0
