"""Polling loop classifier.

RULE:
  Flag a polling loop when:
    (a) ≥3 consecutive tool calls with the same tool_name + args AND
    (b) all returned success (status 2xx or success=True) AND
    (c) call intervals are within 20% of each other (suggests scheduled polling) AND
    (d) result payloads are highly similar (semantic similarity ≥0.90 via
        embeddings, or equality via result hash if no embeddings).

  This is the "useful-looking waste" — agent keeps calling the same endpoint
  on a cadence, storing near-identical results each time.

CONFIDENCE:
  - high:   all 4 conditions hold
  - medium: (a) + (b) + (d) hold, timing less strict (intervals within 50%)
  - low:    (we do not emit low for polling)

FALSE POSITIVES WE AVOID:
  - Ad-hoc manual calls at varying intervals → fails (c).
  - Calls that return different data → fails (d).
  - Calls to different endpoints → fails (a).

DATA REQUIRED: ToolCallEvent with success, result, and (optionally) an embedding
field on the result for semantic similarity.
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

RULE_VERSION = "polling-v1.0"


def _canonical_hash(obj) -> str:
    try:
        return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]
    except Exception:
        return hashlib.sha256(repr(obj).encode()).hexdigest()[:16]


def _args_hash(e: ToolCallEvent) -> str:
    return _canonical_hash(e.args)


def _result_hash(e: ToolCallEvent) -> str:
    return _canonical_hash(e.result)


def _is_success(e: ToolCallEvent) -> bool:
    if e.success is False:
        return False
    if e.status_code is not None and not (200 <= e.status_code < 300):
        return False
    return True


def _interval_spread(timestamps: List[float]) -> float:
    """Return max interval / min interval. 1.0 = perfectly periodic."""
    if len(timestamps) < 2:
        return 0.0
    intervals = [
        timestamps[i + 1] - timestamps[i]
        for i in range(len(timestamps) - 1)
    ]
    intervals = [x for x in intervals if x > 0]
    if not intervals:
        return 0.0
    return max(intervals) / max(min(intervals), 1e-9)


def classify(events: List[LoopEvent], agent_id: str) -> Optional[LoopDetection]:
    tool_calls: List[ToolCallEvent] = [
        e for e in events
        if e.event_type == EventType.TOOL_CALL and e.agent_id == agent_id
    ]
    if len(tool_calls) < 3:
        return None
    tool_calls.sort(key=lambda e: e.timestamp)

    latest = tool_calls[-1]
    latest_args_h = _args_hash(latest)
    latest_tool = latest.tool_name

    # Walk back for consecutive same-tool-same-args calls.
    group: List[ToolCallEvent] = [latest]
    for prior in reversed(tool_calls[:-1]):
        if prior.tool_name == latest_tool and _args_hash(prior) == latest_args_h:
            group.append(prior)
        else:
            break
    group.reverse()

    if len(group) < 3:
        return None

    # All must be success.
    if not all(_is_success(e) for e in group):
        return None

    # Results highly similar — use result hash equality as a floor (deterministic),
    # optionally tighten with embedding cosine if embeddings are available
    # (v1: skip embedding comparison since ToolCallEvent doesn't carry embeddings
    # directly; detection module can pass a similarity function in v2).
    result_hashes = {_result_hash(e) for e in group}
    if len(result_hashes) > 1:
        # Results vary — not a polling loop, could be legitimate updates.
        return None

    # Interval regularity.
    timestamps = [e.timestamp for e in group]
    spread = _interval_spread(timestamps)

    if spread <= 1.2:
        confidence = Confidence.HIGH
    elif spread <= 1.5:
        confidence = Confidence.MEDIUM
    else:
        # Intervals too irregular; not a scheduled poll.
        return None

    fix = (
        f"Cache {latest_tool!r} — it returns the same result on every call.\n"
        "  from functools import lru_cache\n"
        f"  @lru_cache(maxsize=128)\n  def {latest_tool}(...): ..."
    )

    return LoopDetection(
        loop_type=LoopType.POLLING,
        confidence=confidence,
        rule_version=RULE_VERSION,
        agent_id=agent_id,
        matched_event_timestamps=timestamps,
        evidence={
            "tool_name": latest_tool,
            "args_hash": latest_args_h,
            "count": len(group),
            "interval_spread": round(spread, 3),
            "result_hash": next(iter(result_hashes)),
            "window_start": timestamps[0],
            "window_end": timestamps[-1],
        },
        rule_description=(
            f"Polling loop ({RULE_VERSION}): {len(group)} successful calls to "
            f"{latest_tool!r} with identical args at near-regular intervals "
            f"(spread factor {spread:.2f}). All returned identical results — "
            f"wasted calls."
        ),
        suggested_fix=fix,
    )
