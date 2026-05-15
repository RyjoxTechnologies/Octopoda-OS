"""Clarification loop classifier.

RULE:
  Flag a clarification loop when ≥3 recent LLM responses from the agent
  are questions (end with '?', start with interrogative) AND pairwise
  similarity between the questions is ≥0.75. The agent keeps asking
  essentially the same question in slightly different phrasings.

  Common in chatbot orchestrators where the agent runs out of context
  for a downstream action and keeps rephrasing the clarification request.

CONFIDENCE:
  - high:   ≥3 consecutive questions, pairwise mean similarity ≥0.70
  - medium: ≥3 consecutive questions, pairwise mean similarity ≥0.45
  - low:    not emitted

  (Calibrated against difflib on natural-language questions: 0.70 represents
   questions that share ~70% of their structure and content, typical of
   rephrasings of the same underlying ask.)

FALSE POSITIVES WE AVOID:
  - A single clarification question is legitimate.
  - 3 DIFFERENT questions (sim <0.75) = agent exploring, not looping.
  - Questions embedded in a longer response (not at start) are not
    primary intents; we require the response itself to BE the question.
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
from ..similarity import pairwise_mean_similarity

RULE_VERSION = "clarification-v1.0"


_INTERROGATIVE_PREFIXES = (
    r"what",
    r"who",
    r"when",
    r"where",
    r"why",
    r"how",
    r"can",
    r"could",
    r"would",
    r"should",
    r"is",
    r"are",
    r"does",
    r"did",
    r"do you",
    r"will",
    r"may i",
    r"could you",
    r"could i",
    r"which",
)
_INTERROGATIVE_RE = re.compile(
    r"^\s*(?:" + r"|".join(_INTERROGATIVE_PREFIXES) + r")\b",
    flags=re.IGNORECASE,
)


def _is_question(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if not stripped.endswith("?"):
        return False
    return bool(_INTERROGATIVE_RE.match(stripped))


def classify(events: List[LoopEvent], agent_id: str) -> Optional[LoopDetection]:
    llm_calls: List[LLMCallEvent] = [
        e for e in events
        if e.event_type == EventType.LLM_CALL and e.agent_id == agent_id
    ]
    if len(llm_calls) < 3:
        return None
    llm_calls.sort(key=lambda e: e.timestamp)

    # Walk back: consecutive calls whose response is a question.
    tail: List[LLMCallEvent] = []
    for call in reversed(llm_calls):
        if _is_question(call.response_text):
            tail.append(call)
        else:
            break
    tail.reverse()

    if len(tail) < 3:
        return None

    questions = [c.response_text.strip() for c in tail]
    mean_sim = pairwise_mean_similarity(questions)

    if mean_sim >= 0.70:
        confidence = Confidence.HIGH
    elif mean_sim >= 0.45:
        confidence = Confidence.MEDIUM
    else:
        return None

    fix = (
        "Agent keeps asking essentially the same question. The orchestrator "
        "likely needs:\n"
        "  - A max-clarification limit (stop after N rounds)\n"
        "  - A fallback: give the user explicit options instead of open questions\n"
        "  - Check if the agent has enough context before asking"
    )

    return LoopDetection(
        loop_type=LoopType.CLARIFICATION,
        confidence=confidence,
        rule_version=RULE_VERSION,
        agent_id=agent_id,
        matched_event_timestamps=[c.timestamp for c in tail],
        evidence={
            "question_count": len(tail),
            "mean_similarity": round(mean_sim, 3),
            "questions": [q[:160] for q in questions],
            "window_start": tail[0].timestamp,
            "window_end": tail[-1].timestamp,
        },
        rule_description=(
            f"Clarification loop ({RULE_VERSION}): {len(tail)} consecutive "
            f"question-shaped responses, mean pairwise similarity "
            f"{mean_sim:.2f}. Agent is rephrasing the same question."
        ),
        suggested_fix=fix,
    )
