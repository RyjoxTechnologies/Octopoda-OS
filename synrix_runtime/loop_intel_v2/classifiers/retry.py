"""Retry loop classifier.

RULE:
  Flag a retry loop when the last N consecutive tool calls (same tool_name
  + same args) include at least 2 failures (HTTP 4xx/5xx or success=False),
  AND the most recent call is itself a failure.

  The "most recent is a failure" gate means we don't falsely flag
  "struggled then recovered" — if the latest call succeeded, the retry
  resolved.

CONFIDENCE:
  - high:   ≥3 consecutive identical calls AND ≥2 failures AND latest call failed
  - medium: ≥2 consecutive identical calls AND ≥1 failure AND latest call failed
  - low:    (we do not emit low for retry; uncertain is better than noise)

FALSE POSITIVES WE AVOID:
  - "Called 3 times, last one succeeded" — not a loop, the retry worked.
  - "3 calls, all different args" — different semantics per call; not a retry.
  - "3 calls interleaved with successful other tools" — the intervening work
    implies progress; not a tight retry.

DATA REQUIRED: ToolCallEvent with status_code OR success fields populated.
"""

from __future__ import annotations

import hashlib
import json
from typing import List, Optional

from ..models import (
    LoopEvent,
    EventType,
    ToolCallEvent,
    LoopDetection,
    LoopType,
    Confidence,
)

RULE_VERSION = "retry-v1.0"


def _canonical_args_hash(args: dict) -> str:
    """Deterministic hash of args for identity comparison."""
    try:
        canonical = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        canonical = repr(args)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _is_failure(event: ToolCallEvent) -> bool:
    """A call is a failure iff status_code ∈ [400, 599] OR success is False."""
    if event.success is False:
        return True
    if event.status_code is not None and 400 <= event.status_code <= 599:
        return True
    return False


def classify(events: List[LoopEvent], agent_id: str) -> Optional[LoopDetection]:
    """Return a LoopDetection if a retry loop is present, else None."""
    # Keep only tool calls for this agent, ordered by timestamp ascending.
    tool_calls: List[ToolCallEvent] = [
        e for e in events
        if e.event_type == EventType.TOOL_CALL and e.agent_id == agent_id
    ]
    if len(tool_calls) < 2:
        return None
    tool_calls.sort(key=lambda e: e.timestamp)

    latest = tool_calls[-1]
    if not _is_failure(latest):
        # Latest call succeeded — retry resolved (or not a retry).
        return None

    latest_key = (latest.tool_name, _canonical_args_hash(latest.args))

    # Walk backwards, count consecutive identical calls.
    consecutive: List[ToolCallEvent] = [latest]
    for prior in reversed(tool_calls[:-1]):
        key = (prior.tool_name, _canonical_args_hash(prior.args))
        if key == latest_key:
            consecutive.append(prior)
        else:
            break  # chain broken by a different call
    consecutive.reverse()

    failures = sum(1 for e in consecutive if _is_failure(e))
    total = len(consecutive)

    confidence: Optional[Confidence] = None
    if total >= 3 and failures >= 2:
        confidence = Confidence.HIGH
    elif total >= 2 and failures >= 1:
        confidence = Confidence.MEDIUM
    else:
        return None

    status_codes = [e.status_code for e in consecutive if e.status_code is not None]
    fix = None
    if confidence == Confidence.HIGH:
        fix = (
            "Tool is failing repeatedly. Add a circuit breaker:\n"
            "  from functools import wraps\n"
            "  def circuit_breaker(max_failures=3):\n"
            "      ...\n"
            f"  @circuit_breaker()\n  def {latest.tool_name}(...): ..."
        )

    return LoopDetection(
        loop_type=LoopType.RETRY,
        confidence=confidence,
        rule_version=RULE_VERSION,
        agent_id=agent_id,
        matched_event_timestamps=[e.timestamp for e in consecutive],
        evidence={
            "tool_name": latest.tool_name,
            "args_hash": _canonical_args_hash(latest.args),
            "consecutive_count": total,
            "failure_count": failures,
            "status_codes": status_codes,
            "window_start": consecutive[0].timestamp,
            "window_end": consecutive[-1].timestamp,
        },
        rule_description=(
            f"Retry loop ({RULE_VERSION}): {total} consecutive calls to "
            f"{latest.tool_name!r} with identical args; {failures} failed, "
            f"latest failed. Agent is retrying without success."
        ),
        suggested_fix=fix,
    )
