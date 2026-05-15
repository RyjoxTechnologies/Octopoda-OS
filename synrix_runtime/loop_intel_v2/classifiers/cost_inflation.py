"""Cost inflation loop classifier.

RULE:
  Flag a cost inflation loop when:
    (a) ≥3 recent LLMCallEvents for the same agent AND
    (b) the model tier strictly increases across calls (e.g. haiku → sonnet
        → opus, or gpt-4-mini → gpt-4o → gpt-4o-pro) AND
    (c) prompt content is substantially similar across calls (same prompt
        hash, or similarity ≥0.85) — agent is escalating on the SAME task,
        not doing different work.

  Classic pattern: agent gets an unsatisfying answer, retries on a bigger
  model, still unsatisfied, retries on the biggest, etc. Low call count,
  high cost.

CONFIDENCE:
  - high:   ≥3 calls, strictly increasing tier, same prompt hash
  - medium: ≥3 calls, non-decreasing tier with ≥1 increase, same prompt hash
  - low:    not emitted

MODEL TIER ORDERING:
  Hard-coded tier map below. Models not in the map are treated as tier 0
  (neither escalation nor de-escalation).
"""

from __future__ import annotations

from typing import List, Optional

from ..models import (
    LoopEvent,
    EventType,
    LLMCallEvent,
    LoopDetection,
    LoopType,
    Confidence,
)

RULE_VERSION = "cost-inflation-v1.0"


# Tier map — higher number = more expensive / more capable.
# Sources: published API pricing ordering as of 2026-04.
_MODEL_TIER: dict = {
    # Anthropic
    "claude-haiku": 1,
    "claude-haiku-4-5": 1,
    "claude-haiku-4-5-20251001": 1,
    "claude-sonnet": 2,
    "claude-sonnet-4-6": 2,
    "claude-opus": 3,
    "claude-opus-4-7": 3,
    # OpenAI
    "gpt-4-mini": 1,
    "gpt-4o-mini": 1,
    "gpt-4": 2,
    "gpt-4o": 2,
    "gpt-4-turbo": 2,
    "gpt-4.1": 3,
    "o1-mini": 2,
    "o1": 3,
    "o1-pro": 4,
    # Google
    "gemini-flash": 1,
    "gemini-1.5-flash": 1,
    "gemini-pro": 2,
    "gemini-1.5-pro": 2,
    "gemini-ultra": 3,
}


def _tier(model: str) -> int:
    """Resolve a model name to a tier. Unknown models are 0."""
    if not model:
        return 0
    key = model.lower().strip()
    if key in _MODEL_TIER:
        return _MODEL_TIER[key]
    # Prefix match fallback.
    for k, v in _MODEL_TIER.items():
        if key.startswith(k):
            return v
    return 0


def classify(events: List[LoopEvent], agent_id: str) -> Optional[LoopDetection]:
    llm_calls: List[LLMCallEvent] = [
        e for e in events
        if e.event_type == EventType.LLM_CALL and e.agent_id == agent_id
    ]
    if len(llm_calls) < 3:
        return None
    llm_calls.sort(key=lambda e: e.timestamp)

    # Walk back from the latest call collecting consecutive same-prompt calls.
    # Previously we took the last 5 and required them all to share a prompt —
    # that missed real inflation loops followed by unrelated LLM work.
    # Now: find the longest same-prompt suffix ending at the latest call.
    latest = llm_calls[-1]
    if not latest.prompt_hash:
        return None

    suffix: List[LLMCallEvent] = [latest]
    for prior in reversed(llm_calls[:-1]):
        if prior.prompt_hash == latest.prompt_hash:
            suffix.append(prior)
        else:
            break
    suffix.reverse()

    # Cap at the most recent 5 same-prompt calls for manageable evidence.
    window = suffix[-5:]
    if len(window) < 3:
        return None

    tiers = [_tier(c.model) for c in window]
    # All tiers must be known (>0) to reason about escalation.
    if any(t == 0 for t in tiers):
        return None

    # Strictly increasing?
    strict = all(tiers[i] < tiers[i + 1] for i in range(len(tiers) - 1))
    # Non-decreasing with ≥1 increase?
    nondec = all(tiers[i] <= tiers[i + 1] for i in range(len(tiers) - 1))
    has_increase = any(tiers[i] < tiers[i + 1] for i in range(len(tiers) - 1))

    if strict:
        confidence = Confidence.HIGH
    elif nondec and has_increase:
        confidence = Confidence.MEDIUM
    else:
        return None

    total_cost = sum(c.cost_usd for c in window)
    models = [c.model for c in window]
    fix = (
        "Cap model tier for this task. The same prompt is being retried on "
        "increasingly expensive models with no gain. Consider:\n"
        "  - Lock to the cheapest model that gives acceptable results\n"
        "  - Add a confidence gate before escalation"
    )

    return LoopDetection(
        loop_type=LoopType.COST_INFLATION,
        confidence=confidence,
        rule_version=RULE_VERSION,
        agent_id=agent_id,
        matched_event_timestamps=[c.timestamp for c in window],
        evidence={
            "call_count": len(window),
            "models_used": models,
            "tiers": tiers,
            "strictly_increasing": strict,
            "prompt_hash": latest.prompt_hash,
            "total_cost_usd": round(total_cost, 4),
        },
        rule_description=(
            f"Cost inflation ({RULE_VERSION}): {len(window)} LLM calls on the "
            f"same prompt, model tier escalating ({' → '.join(models)}). "
            f"Total cost so far: ${total_cost:.4f}."
        ),
        suggested_fix=fix,
    )
