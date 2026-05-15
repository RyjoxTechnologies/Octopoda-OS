"""Tool non-determinism classifier.

RULE:
  Flag a tool non-determinism loop when ≥3 successful calls to the same
  tool with identical args return MEANINGFULLY DIFFERENT results, and
  the agent kept re-querying. The "agent kept re-querying" is implicit
  in the observation of 3+ such calls.

  This differs from polling (same input, same output) and retry (failures).
  Here: same input, different outputs, all successful, agent confused.

CONFIDENCE:
  - high:   ≥3 calls, all successful, mean pairwise result similarity ≤0.65
  - medium: ≥3 calls, all successful, mean pairwise result similarity ≤0.80
  - low:    not emitted

  (Thresholds calibrated against difflib.SequenceMatcher on JSON-serialized
   dicts, which share a lot of structural characters even for unrelated
   content. Values ≤0.65 empirically mean "content meaningfully differs.")

FALSE POSITIVES WE AVOID:
  - Polling where results drift legitimately (market data, time-series).
    Handle: pair with retry/polling rules — tool-nondet only fires if
    result variance is HIGH. Drift is usually low variance.
  - Result differences from different args (not this rule's scope).
"""

from __future__ import annotations

from typing import List, Optional

from ..models import (
    LoopEvent,
    EventType,
    ToolCallEvent,
    LoopDetection,
    LoopType,
    Confidence,
)
from ..similarity import pairwise_mean_similarity

RULE_VERSION = "tool-nondeterminism-v1.0"


def _args_hash_obj(args: dict):
    return tuple(sorted(((k, str(v)) for k, v in (args or {}).items())))


def _is_success(e: ToolCallEvent) -> bool:
    if e.success is False:
        return False
    if e.status_code is not None and not (200 <= e.status_code < 300):
        return False
    return True


def classify(events: List[LoopEvent], agent_id: str) -> Optional[LoopDetection]:
    tool_calls: List[ToolCallEvent] = [
        e for e in events
        if e.event_type == EventType.TOOL_CALL and e.agent_id == agent_id
    ]
    if len(tool_calls) < 3:
        return None
    tool_calls.sort(key=lambda e: e.timestamp)

    latest = tool_calls[-1]
    latest_key = (latest.tool_name, _args_hash_obj(latest.args))

    # Consecutive calls with same tool+args.
    group: List[ToolCallEvent] = [latest]
    for prior in reversed(tool_calls[:-1]):
        if (prior.tool_name, _args_hash_obj(prior.args)) == latest_key:
            group.append(prior)
        else:
            break
    group.reverse()

    if len(group) < 3:
        return None

    if not all(_is_success(e) for e in group):
        return None  # failures belong to retry classifier

    results = [e.result for e in group]
    mean_sim = pairwise_mean_similarity(results)

    # Tool non-det requires LOW similarity (results vary).
    if mean_sim <= 0.65:
        confidence = Confidence.HIGH
    elif mean_sim <= 0.80:
        confidence = Confidence.MEDIUM
    else:
        return None  # results too similar — this is polling, not nondet

    fix = (
        f"Tool {latest.tool_name!r} returns different results on identical "
        "input. Agent keeps re-querying, hoping for stable output. Consider:\n"
        "  - Add a caching layer on the first response\n"
        "  - Accept the non-determinism with an explicit assert\n"
        "  - Use a fixed seed or idempotency key if the tool supports it"
    )

    return LoopDetection(
        loop_type=LoopType.TOOL_NONDETERMINISM,
        confidence=confidence,
        rule_version=RULE_VERSION,
        agent_id=agent_id,
        matched_event_timestamps=[e.timestamp for e in group],
        evidence={
            "tool_name": latest.tool_name,
            "call_count": len(group),
            "mean_result_similarity": round(mean_sim, 3),
            "sample_results": [str(r)[:120] for r in results[:3]],
            "window_start": group[0].timestamp,
            "window_end": group[-1].timestamp,
        },
        rule_description=(
            f"Tool non-determinism ({RULE_VERSION}): {len(group)} successful "
            f"calls to {latest.tool_name!r} with identical args but varying "
            f"results (mean similarity {mean_sim:.2f}). Agent is re-querying "
            f"a non-deterministic tool."
        ),
        suggested_fix=fix,
    )
