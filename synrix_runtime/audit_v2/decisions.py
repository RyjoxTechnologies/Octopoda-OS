"""audit_v2.decisions - heuristic decision synthesis.

Raw audit events are noisy. What the user actually wants to see in the
dashboard is "the agent made a decision at 3:42pm after reading these
memories and before writing these new ones."

This module provides a simple, deterministic heuristic that groups
causally-related events into synthetic `decision` rows:

  - Scope: one agent at a time (decisions are agent-local)
  - Window: 5 seconds by default (configurable)
  - Trigger: a cluster must contain at least one memory.read AND at
             least one memory.write within the window
  - Emit: a `decision` event whose `extra` field points to the
          contributing read / write row IDs
  - Idempotent: if you call this twice we don't duplicate decisions
                (we check for existing synthetic decisions covering the
                same source events)

This is intentionally a simple heuristic - no ML, no LLM classification,
no magic. It just says "if an agent read X then wrote Y within N seconds,
that's probably a decision based on X".

Later we can improve it by plugging in actual LLM-response context when
token counting is wired in.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .models import AuditEvent
from . import storage as _storage


DEFAULT_WINDOW_SEC = 5.0
_READ_KINDS = frozenset({
    "memory.read", "memory.semantic_search", "memory.prefix_search",
    "memory.shared_read",
})
_WRITE_KINDS = frozenset({
    "memory.write", "memory.important", "memory.share",
    "conversation.message", "crew.task", "crew.finding",
    "autogen.turn", "thread.updated",
})
_ALREADY_SYNTH = "decision"


def _is_already_synthesized(events: List[dict], start_ts: float,
                             end_ts: float, agent_id: str) -> bool:
    """Avoid duplicating decisions that were already synthesised."""
    for e in events:
        if e.get("event_type") == _ALREADY_SYNTH and \
                e.get("agent_id") == agent_id:
            ts = float(e.get("timestamp", 0))
            if start_ts <= ts <= end_ts:
                # Treat any existing decision within the window as coverage
                return True
    return False


def synthesize_decisions(
    tenant_id: str,
    *,
    agent_id: Optional[str] = None,
    from_ts: Optional[float] = None,
    to_ts: Optional[float] = None,
    window_sec: float = DEFAULT_WINDOW_SEC,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Walk events and emit synthetic `decision` events.

    Returns a summary dict: {
        "synthesized": int,
        "windows_considered": int,
        "events_scanned": int,
        "decisions": [{triggering_reads, outcome_writes, timestamp, agent_id}...]
    }
    """
    events = _storage.list_events(
        tenant_id,
        agent_id=agent_id,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=1000,
    )
    # Group by agent_id
    by_agent: Dict[str, List[dict]] = defaultdict(list)
    for e in events:
        aid = e.get("agent_id")
        if not aid:
            continue
        by_agent[aid].append(e)

    synthesised = 0
    windows_considered = 0
    details: List[dict] = []

    for aid, aid_events in by_agent.items():
        # oldest first so we can walk a rolling window
        aid_events_sorted = sorted(aid_events,
                                    key=lambda x: float(x.get("timestamp", 0)))
        i = 0
        n = len(aid_events_sorted)
        while i < n:
            e_anchor = aid_events_sorted[i]
            anchor_ts = float(e_anchor.get("timestamp", 0))
            window_end = anchor_ts + window_sec
            # Collect all events in this window
            bucket = []
            j = i
            while j < n:
                ej = aid_events_sorted[j]
                tj = float(ej.get("timestamp", 0))
                if tj > window_end:
                    break
                bucket.append(ej)
                j += 1
            windows_considered += 1

            reads = [x for x in bucket if x.get("event_type") in _READ_KINDS]
            writes = [x for x in bucket if x.get("event_type") in _WRITE_KINDS]

            if reads and writes and \
                    not _is_already_synthesized(bucket, anchor_ts, window_end, aid):
                # Build a synthetic decision
                synth_ts = max(
                    (float(r.get("timestamp", 0)) for r in reads),
                    default=anchor_ts,
                )
                # Place it just after the last read for natural ordering
                synth_ts = synth_ts + 0.001

                # Inherit trace_id from source events if they all share one
                src_traces = set()
                for src_ev in reads + writes:
                    t = (src_ev.get('extra') or {}).get('trace_id')
                    if t:
                        src_traces.add(t)
                inherited_trace = src_traces.pop() if len(src_traces) == 1 else None

                extra = {
                    "synthesised": True,
                    "window_sec": window_sec,
                    "triggering_reads": [r.get("_row_id") for r in reads
                                          if r.get("_row_id")],
                    "outcome_writes": [w.get("_row_id") for w in writes
                                        if w.get("_row_id")],
                    "read_count": len(reads),
                    "write_count": len(writes),
                }
                if inherited_trace:
                    extra["trace_id"] = inherited_trace
                decision_summary = _format_decision_summary(reads, writes)

                if not dry_run:
                    ev = AuditEvent(
                        agent_id=aid,
                        event_type=_ALREADY_SYNTH,
                        source="api",
                        key="decision:synthesised",
                        value_preview=decision_summary,
                        extra=extra,
                        timestamp=synth_ts,
                    )
                    try:
                        _storage.write_event(tenant_id, ev)
                        synthesised += 1
                    except Exception:
                        pass  # don't let a single failure kill the batch
                else:
                    synthesised += 1

                details.append({
                    "agent_id": aid,
                    "timestamp": synth_ts,
                    "reads": len(reads),
                    "writes": len(writes),
                    "summary": decision_summary,
                })
                # Skip past this window to avoid overlapping duplicates
                i = j
                continue
            i += 1

    return {
        "synthesised": synthesised,
        "windows_considered": windows_considered,
        "events_scanned": len(events),
        "decisions": details,
    }


def _format_decision_summary(reads: List[dict], writes: List[dict]) -> str:
    """Build a one-line human summary for the synthetic decision row."""
    read_keys = [r.get("key") for r in reads if r.get("key")][:2]
    write_keys = [w.get("key") for w in writes if w.get("key")][:2]
    read_bit = ", ".join(read_keys) if read_keys else "memory"
    write_bit = ", ".join(write_keys) if write_keys else "memory"
    return f"Read [{read_bit}] -> wrote [{write_bit}]"
