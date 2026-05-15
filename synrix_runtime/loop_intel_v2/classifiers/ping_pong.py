"""Ping-pong (cross-agent) loop classifier.

RULE:
  Flag a ping-pong loop when two distinct agents alternate writes to the
  same shared-memory key. Signature: A → B → A → B (same key).

  Multiple ping-pong patterns can exist simultaneously (across different
  shared keys). This classifier returns every qualifying key as a
  separate detection.

CONFIDENCE:
  - high:   ≥4 alternating writes (A/B/A/B)
  - medium: 3 alternating writes (A/B/A)
  - low:    not emitted

UNLIKE single-agent classifiers, `agent_id` is ignored — ping-pong
spans agents by definition.

FALSE POSITIVES WE AVOID:
  - Same agent writing twice in a row → not alternation.
  - 3+ distinct agents → not ping-pong (that's a merge / race).
  - Different keys → each evaluated independently.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from ..models import (
    LoopEvent,
    EventType,
    MemoryWriteEvent,
    LoopDetection,
    LoopType,
    Confidence,
)

RULE_VERSION = "ping-pong-v1.1"


def classify(events: List[LoopEvent], agent_id: str = "") -> List[LoopDetection]:
    """Return list of ping-pong detections — one per qualifying shared key."""
    writes: List[MemoryWriteEvent] = [
        e for e in events if e.event_type == EventType.MEMORY_WRITE
    ]
    if len(writes) < 3:
        return []
    writes.sort(key=lambda e: e.timestamp)

    by_key: Dict[str, List[MemoryWriteEvent]] = defaultdict(list)
    for w in writes:
        by_key[w.key].append(w)

    detections: List[LoopDetection] = []

    for key, key_writes in by_key.items():
        if len(key_writes) < 3:
            continue
        agents = [w.agent_id for w in key_writes]
        distinct = list(dict.fromkeys(agents))
        if len(distinct) != 2:
            continue
        a, b = distinct
        expected_a = [a if i % 2 == 0 else b for i in range(len(agents))]
        expected_b = [b if i % 2 == 0 else a for i in range(len(agents))]
        if not (agents == expected_a or agents == expected_b):
            continue

        count = len(key_writes)
        involved = [a, b]
        confidence = Confidence.HIGH if count >= 4 else Confidence.MEDIUM

        fix = (
            f"Agents {involved[0]!r} and {involved[1]!r} are "
            f"alternating writes on shared key {key!r}. Consider:\n"
            "  - Rate-limit cross-agent triggers on shared keys\n"
            "  - Add a consensus deadline (stop after N rounds)\n"
            "  - Assign ownership of the key to one agent"
        )

        detections.append(LoopDetection(
            loop_type=LoopType.PING_PONG,
            confidence=confidence,
            agent_id=involved[0],
            rule_version=RULE_VERSION,
            matched_event_timestamps=[w.timestamp for w in key_writes],
            evidence={
                "shared_key": key,
                "involved_agents": involved,
                "write_count": count,
                "write_sequence": [w.agent_id for w in key_writes],
                "window_start": key_writes[0].timestamp,
                "window_end": key_writes[-1].timestamp,
            },
            rule_description=(
                f"Ping-pong loop ({RULE_VERSION}): agents "
                f"{involved[0]!r} and {involved[1]!r} are "
                f"alternating {count} writes on shared key {key!r}."
            ),
            suggested_fix=fix,
        ))

    return detections
