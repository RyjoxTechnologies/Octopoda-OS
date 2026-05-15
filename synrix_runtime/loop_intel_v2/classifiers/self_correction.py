"""Self-correction loop classifier.

RULE:
  Flag a self-correction loop when ≥3 consecutive LLM responses from an agent
  start with a revision cue — phrases like "actually", "wait", "let me
  reconsider", "on second thought", "i was wrong". These cues indicate the
  model is second-guessing itself across calls, typically in CrewAI-style
  reflection mode or agents prompted with "be thorough."

CONFIDENCE:
  - high:   ≥3 consecutive LLM calls with revision cue, same prompt hash
  - medium: ≥3 consecutive LLM calls with revision cue, varying prompt hash
  - low:    (not emitted)

FALSE POSITIVES WE AVOID:
  - A single revision cue is legitimate reflection, not a loop.
  - Cues embedded mid-response (not at start) may be explanatory; we only
    match prefix.
  - Non-revision responses between cues break the chain.
"""

from __future__ import annotations

import re
from typing import List, Optional

from ..models import (
    LoopEvent,
    EventType,
    LLMCallEvent,
    LoopDetection,
    LoopType,
    Confidence,
)

RULE_VERSION = "self-correction-v1.0"


# Patterns must match at the very start of a response (case-insensitive).
# Grouped for easy auditability.
_CUE_PATTERNS = [
    r"actually,?\b",
    r"wait,?\b",
    r"let me (re-?consider|re-?think|revise)",
    r"on second thought",
    r"i was wrong",
    r"i made a mistake",
    r"correction:",
    r"hold on,?\b",
    r"hmm,?\s+(actually|on second|let me)",
]
_CUE_REGEX = re.compile(
    r"^\s*(?:" + r"|".join(_CUE_PATTERNS) + r")",
    flags=re.IGNORECASE,
)


def _has_revision_cue(response_text: str) -> bool:
    if not response_text:
        return False
    return bool(_CUE_REGEX.match(response_text))


def classify(events: List[LoopEvent], agent_id: str) -> Optional[LoopDetection]:
    llm_calls: List[LLMCallEvent] = [
        e for e in events
        if e.event_type == EventType.LLM_CALL and e.agent_id == agent_id
    ]
    if len(llm_calls) < 3:
        return None
    llm_calls.sort(key=lambda e: e.timestamp)

    # Walk back from the latest, collect consecutive revision-cued calls.
    tail: List[LLMCallEvent] = []
    for call in reversed(llm_calls):
        if _has_revision_cue(call.response_text):
            tail.append(call)
        else:
            break
    tail.reverse()

    if len(tail) < 3:
        return None

    prompt_hashes = {c.prompt_hash for c in tail if c.prompt_hash}
    same_prompt = len(prompt_hashes) == 1

    confidence = Confidence.HIGH if same_prompt else Confidence.MEDIUM

    # Extract the actual matched cues for audit.
    matched_cues = []
    for c in tail:
        m = _CUE_REGEX.match(c.response_text or "")
        matched_cues.append(m.group(0).strip() if m else "")

    total_cost = sum(c.cost_usd for c in tail)

    fix = (
        "Agent is self-correcting repeatedly — likely caused by a prompt "
        "instructing 'be thorough' or reflection mode enabled. Consider:\n"
        "  - Limit max revisions per task (e.g. reflection_rounds=2)\n"
        "  - Remove 'reconsider if unsure' from the system prompt\n"
        "  - Lower temperature if the model is uncertain"
    )

    return LoopDetection(
        loop_type=LoopType.SELF_CORRECTION,
        confidence=confidence,
        rule_version=RULE_VERSION,
        agent_id=agent_id,
        matched_event_timestamps=[c.timestamp for c in tail],
        evidence={
            "call_count": len(tail),
            "matched_cues": matched_cues,
            "same_prompt_hash": same_prompt,
            "prompt_hashes": sorted(prompt_hashes),
            "total_cost_usd": round(total_cost, 4),
            "window_start": tail[0].timestamp,
            "window_end": tail[-1].timestamp,
        },
        rule_description=(
            f"Self-correction loop ({RULE_VERSION}): {len(tail)} consecutive "
            f"LLM responses start with revision cues "
            f"({', '.join(repr(c) for c in matched_cues)}). Agent is "
            f"second-guessing itself; total cost ${total_cost:.4f}."
        ),
        suggested_fix=fix,
    )
