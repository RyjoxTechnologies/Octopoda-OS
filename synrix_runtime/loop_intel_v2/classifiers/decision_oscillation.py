"""Decision oscillation classifier.

RULE:
  Flag a decision oscillation loop when:
    (a) ≥3 DecisionEvents in the recent window with the same decision_key AND
    (b) the decision_values alternate between exactly 2 distinct values
        (i.e. A, B, A, B, ...) AND
    (c) the decision_values are not monotonically converging toward a new
        value (third-value appearance breaks the pattern).

  This is the classic "can't make up its mind" failure, typically caused by
  conflicting memory or a flaky source of truth.

CONFIDENCE:
  - high:   ≥4 decisions, perfect A/B/A/B alternation on the same key
  - medium: 3 decisions alternating (A/B/A) — possible early oscillation
  - low:    (we don't emit low for decision oscillation)

FALSE POSITIVES WE AVOID:
  - Different keys → separate decisions, not an oscillation.
  - 3 values seen (A, B, C) → agent is exploring, not oscillating.
  - Same value repeated → agent is consistent, not oscillating.
"""

from __future__ import annotations

import json
from typing import List, Optional

from ..models import (
    LoopEvent,
    EventType,
    DecisionEvent,
    LoopDetection,
    LoopType,
    Confidence,
)

RULE_VERSION = "decision-oscillation-v1.0"


def _value_fingerprint(value) -> str:
    """Stable fingerprint for decision value comparison."""
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return repr(value)


def classify(events: List[LoopEvent], agent_id: str) -> Optional[LoopDetection]:
    decisions: List[DecisionEvent] = [
        e for e in events
        if e.event_type == EventType.DECISION and e.agent_id == agent_id
    ]
    if len(decisions) < 3:
        return None
    decisions.sort(key=lambda e: e.timestamp)

    # Find the most recent 3+ decisions sharing the same decision_key.
    latest_key = decisions[-1].decision_key
    same_key: List[DecisionEvent] = [
        d for d in decisions if d.decision_key == latest_key
    ]
    if len(same_key) < 3:
        return None

    # Take the consecutive tail (all the same_key decisions, ordered).
    # We don't require them to be consecutive in the full event stream —
    # oscillation happens across time, often with other events between.
    tail = same_key[-6:]  # cap window at 6 for noise resistance
    fingerprints = [_value_fingerprint(d.decision_value) for d in tail]
    distinct = list(dict.fromkeys(fingerprints))  # preserves order

    if len(distinct) != 2:
        # Either 1 value (no oscillation) or 3+ values (exploration, not oscillation)
        return None

    # Check alternation: fingerprints must alternate A/B/A/B (any starting value).
    a, b = distinct
    expected = [a if i % 2 == 0 else b for i in range(len(tail))]
    alt_a = fingerprints == expected
    expected2 = [b if i % 2 == 0 else a for i in range(len(tail))]
    alt_b = fingerprints == expected2
    if not (alt_a or alt_b):
        return None

    confidence = Confidence.HIGH if len(tail) >= 4 else Confidence.MEDIUM

    fix = (
        f"Memory likely contains conflicting values for key pattern "
        f"{latest_key!r}. Resolve with:\n"
        f"  agent.consolidate(key={latest_key!r}, strategy='latest_wins')"
    )

    return LoopDetection(
        loop_type=LoopType.DECISION_OSCILLATION,
        confidence=confidence,
        rule_version=RULE_VERSION,
        agent_id=agent_id,
        matched_event_timestamps=[d.timestamp for d in tail],
        evidence={
            "decision_key": latest_key,
            "decision_count": len(tail),
            "distinct_values": distinct,
            "alternation_pattern": fingerprints,
            "window_start": tail[0].timestamp,
            "window_end": tail[-1].timestamp,
        },
        rule_description=(
            f"Decision oscillation ({RULE_VERSION}): {len(tail)} consecutive "
            f"decisions on key {latest_key!r} alternating between 2 values. "
            f"Agent is flip-flopping — likely caused by conflicting memory."
        ),
        suggested_fix=fix,
    )
