"""Recall-write loop classifier.

RULE:
  Flag a recall-write loop when the agent repeatedly reads a memory key
  and writes back a substantially-similar value. Pattern:
    read(X) → ... → write(X, similar_value) → read(X) → ... → write(X, ...)

  One agent can have multiple recall-write loops on different keys
  simultaneously. This classifier returns every qualifying key as a
  separate detection.

CONFIDENCE:
  - high:   ≥3 cycles on key, all writes ≥0.85 similar to prior read
  - medium: ≥2 cycles, similarity ≥0.75
  - low:    not emitted

FALSE POSITIVES WE AVOID:
  - Read then write a completely different value — legitimate update.
  - Writes without reads — that's reflection, not recall-write.
"""

from __future__ import annotations

from collections import defaultdict
from typing import List

from ..models import (
    LoopEvent,
    EventType,
    LoopDetection,
    LoopType,
    Confidence,
)
from ..similarity import text_similarity

RULE_VERSION = "recall-write-v1.1"


def classify(events: List[LoopEvent], agent_id: str) -> List[LoopDetection]:
    """Return a list of recall-write detections — one per qualifying key."""
    mem_events = [
        e for e in events
        if e.agent_id == agent_id and e.event_type in (EventType.MEMORY_READ, EventType.MEMORY_WRITE)
    ]
    if len(mem_events) < 4:
        return []
    mem_events.sort(key=lambda e: e.timestamp)

    by_key: dict = defaultdict(list)
    for e in mem_events:
        key = getattr(e, "key", None)
        if key:
            by_key[key].append(e)

    detections: List[LoopDetection] = []

    for key, chain in by_key.items():
        if len(chain) < 4:
            continue
        cycles = []
        last_read = None
        for e in chain:
            if e.event_type == EventType.MEMORY_READ:
                last_read = e
            elif e.event_type == EventType.MEMORY_WRITE and last_read is not None:
                sim = text_similarity(
                    getattr(last_read, "value_returned", None),
                    getattr(e, "value", None),
                )
                cycles.append((last_read, e, sim))
                last_read = None
        high_sim_cycles = [c for c in cycles if c[2] >= 0.75]
        if len(high_sim_cycles) < 2:
            continue

        sims = [c[2] for c in high_sim_cycles]
        min_sim = min(sims)

        if len(high_sim_cycles) >= 3 and min_sim >= 0.85:
            confidence = Confidence.HIGH
        elif len(high_sim_cycles) >= 2 and min_sim >= 0.75:
            confidence = Confidence.MEDIUM
        else:
            continue

        matched_ts = []
        for r, w, _ in high_sim_cycles:
            matched_ts.extend([r.timestamp, w.timestamp])

        fix = (
            f"Agent is reading {key!r} and writing back a near-identical "
            "value repeatedly — non-idempotent update pattern. Consider:\n"
            "  - Add a dedup check: if new_value == old_value, skip write\n"
            "  - Use a merge strategy that short-circuits on no-op\n"
            "  - If intentional, add an epoch/version field so equality fails"
        )

        detections.append(LoopDetection(
            loop_type=LoopType.RECALL_WRITE,
            confidence=confidence,
            rule_version=RULE_VERSION,
            agent_id=agent_id,
            matched_event_timestamps=matched_ts,
            evidence={
                "key": key,
                "cycle_count": len(high_sim_cycles),
                "min_similarity": round(min_sim, 3),
                "similarities": [round(s, 3) for s in sims],
                "window_start": matched_ts[0] if matched_ts else None,
                "window_end": matched_ts[-1] if matched_ts else None,
            },
            rule_description=(
                f"Recall-write loop ({RULE_VERSION}): {len(high_sim_cycles)} read→write "
                f"cycles on key {key!r} where each write is ≥{min_sim:.0%} "
                f"similar to the prior read. Agent is re-saving near-identical data."
            ),
            suggested_fix=fix,
        ))

    return detections
