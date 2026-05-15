"""Production DB → LoopEvent adapter.

Pulls memory writes from the nodes table (current production schema) and
maps them into MemoryWriteEvent dataclasses that the classifiers consume.

Two-phase query for performance:
  1. Find candidate keys via the partial index on (tenant_id, name) where
     valid_until=0 — fast, returns current keys.
  2. For each key (or batch), pull all historical versions via name=ANY()
     equality lookup — also indexed.

This avoids the parallel seq-scan trap that hits when filtering only on
(tenant_id, valid_from) on a large nodes table — the previous query
would cost ~200k and time out.

SCHEMA NOTE:
  Current backend stores memory writes as nodes. Tool calls, LLM calls,
  and decisions are NOT stored separately — those need audit-v2 enabled.
  Only memory-based classifiers will produce results here.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from .models import (
    EventType, LoopEvent,
    MemoryWriteEvent, MemoryReadEvent,
    ToolCallEvent, LLMCallEvent, DecisionEvent,
)


# Hard ceiling on how many rows we'll actually read. Protects against
# pathological tenants with huge histories.
_MAX_ROWS = 5000

# Server-side query timeout to avoid hanging the API worker thread.
# 30s ceiling for /detect scans on real tenants. The earlier 5s value was
# tuned for the dashboard's 24h default; once the dashboard started calling
# /detect?hours=720 on page-load (30-day window) the larger scan exceeded
# 5s on tenants with 100k+ memory rows, returning 500s and breaking the
# Loop Intel v2 page. 30s is generous enough for 720h on every current
# tenant while still bounded so a runaway query can't hold a worker thread.
_STATEMENT_TIMEOUT = "30s"


def _setup_session(cursor, tenant_id: str) -> None:
    cursor.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
    cursor.execute(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT}'")


def _row_to_event(name: str, ts, data, tenant_id: str) -> Optional[MemoryWriteEvent]:
    parts = name.split(":", 2)
    if len(parts) < 3:
        return None
    _, agent_id, key = parts
    val = None
    if isinstance(data, dict):
        val = data.get("value", data)
    if isinstance(val, dict):
        try:
            val = json.dumps(val, sort_keys=True, default=str)[:500]
        except Exception:
            val = repr(val)[:500]
    return MemoryWriteEvent(
        event_type=EventType.MEMORY_WRITE,
        timestamp=float(ts) if ts is not None else 0.0,
        agent_id=agent_id,
        tenant_id=tenant_id,
        key=key,
        value=val,
        source="unknown",
    )


def fetch_events(
    connection,
    tenant_id: str,
    agent_id: Optional[str] = None,
    hours: int = 24,
    limit: int = 1000,
) -> List[LoopEvent]:
    """Fetch memory-write events for a tenant (optionally one agent).

    Returns events sorted by timestamp ascending.
    Includes write history per key via two-phase query.
    """
    cur = connection.cursor()
    _setup_session(cur, tenant_id)

    if agent_id:
        prefix = f"agents:{agent_id}:%"
    else:
        prefix = "agents:%"

    # Phase 1: get the distinct names with at least one current version.
    # This uses the partial index idx_nodes_name_prefix (tenant_id, name)
    # where valid_until=0 — fast.
    cur.execute(
        """
        SELECT DISTINCT name
        FROM nodes
        WHERE tenant_id = %s AND name LIKE %s AND valid_until = 0
        LIMIT %s
        """,
        (tenant_id, prefix, min(limit, _MAX_ROWS)),
    )
    names = [r[0] for r in cur.fetchall()]
    if not names:
        return []

    cutoff = time.time() - (hours * 3600) if hours > 0 else 0

    # Phase 2: pull all rows (history + current) for those names within the
    # time window. Uses name=ANY() equality which hits the index cleanly.
    cur.execute(
        """
        SELECT name, valid_from, data
        FROM nodes
        WHERE tenant_id = %s
          AND name = ANY(%s)
          AND valid_from >= %s
        ORDER BY valid_from
        LIMIT %s
        """,
        (tenant_id, names, cutoff, _MAX_ROWS),
    )

    events: List[LoopEvent] = []
    for name, ts, data in cur.fetchall():
        e = _row_to_event(name, ts, data, tenant_id)
        if e is not None:
            events.append(e)

    # Also pull audit-v2 events (tool calls, LLM calls, decisions, reads)
    # so the non-memory-only classifiers (retry, polling, cost_inflation,
    # tool_nondeterminism, decision_oscillation, recall_write, ...) see
    # their signal streams.
    try:
        events.extend(
            fetch_audit_events(connection, tenant_id, agent_id=agent_id,
                               hours=hours, limit=_MAX_ROWS)
        )
    except Exception:
        # Audit fetch failure should never break memory-based detection.
        pass

    # Re-sort the combined stream so classifiers see strictly chronological
    # order. Some classifiers (retry, polling) rely on adjacency.
    events.sort(key=lambda e: getattr(e, "timestamp", 0.0))
    return events


def _audit_event_to_loop_event(data: dict, tenant_id: str) -> Optional[LoopEvent]:
    """Convert an audit_v2-stored event row to the appropriate LoopEvent
    subclass that the loop-intel classifiers consume.

    The audit-v2 schema stores everything as flat fields plus an `extra`
    dict. This mapping pulls the right fields per event_type so:
      - retry / polling / tool_nondeterminism see ToolCallEvent
      - cost_inflation / self_correction / clarification see LLMCallEvent
      - decision_oscillation sees DecisionEvent
      - recall_write sees MemoryReadEvent + MemoryWriteEvent

    Returns None for event types the classifiers don't consume.
    """
    et = data.get("event_type")
    agent_id = data.get("agent_id") or ""
    ts = data.get("timestamp")
    if not agent_id or ts is None:
        return None
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}

    if et in ("memory.write", "memory.share"):
        # memory.share is treated as a MemoryWriteEvent so cross-agent
        # ping_pong on shared keys fires correctly. The shared key lives
        # under data.key (e.g. "engineering-team:review:PR142"); the
        # author agent is data.agent_id which matches what the classifier
        # expects.
        return MemoryWriteEvent(
            event_type=EventType.MEMORY_WRITE,
            timestamp=float(ts),
            agent_id=agent_id,
            tenant_id=tenant_id,
            key=data.get("key") or "",
            value=data.get("value_preview"),
            source=data.get("source") or "audit_v2",
        )

    if et == "memory.read":
        return MemoryReadEvent(
            event_type=EventType.MEMORY_READ,
            timestamp=float(ts),
            agent_id=agent_id,
            tenant_id=tenant_id,
            key=data.get("key") or "",
            value_returned=data.get("value_preview"),
        )

    if et == "tool.call":
        return ToolCallEvent(
            event_type=EventType.TOOL_CALL,
            timestamp=float(ts),
            agent_id=agent_id,
            tenant_id=tenant_id,
            tool_name=extra.get("tool") or data.get("key") or "",
            args=extra.get("args") or {},
            result=extra.get("result_hash") or extra.get("result_preview"),
            duration_ms=float(data.get("latency_ms") or 0),
            success=(data.get("outcome") == "success"),
        )

    if et == "llm.call":
        return LLMCallEvent(
            event_type=EventType.LLM_CALL,
            timestamp=float(ts),
            agent_id=agent_id,
            tenant_id=tenant_id,
            model=extra.get("model") or "",
            prompt_hash=extra.get("prompt_hash") or "",
            prompt_preview=extra.get("prompt_suffix") or "",
            response_text=extra.get("response_preview") or "",
            cost_usd=float(data.get("cost_usd") or 0.0),
            input_tokens=int(data.get("tokens_in") or 0),
            output_tokens=int(data.get("tokens_out") or 0),
        )

    if et == "decision":
        return DecisionEvent(
            event_type=EventType.DECISION,
            timestamp=float(ts),
            agent_id=agent_id,
            tenant_id=tenant_id,
            decision_key=extra.get("key") or data.get("key") or "decision",
            decision_value=extra.get("decision") or data.get("value_preview"),
            decision_type=extra.get("decision_type") or "",
        )

    return None  # Skip events the classifiers don't consume


def fetch_audit_events(
    connection,
    tenant_id: str,
    agent_id: Optional[str] = None,
    hours: int = 24,
    limit: int = _MAX_ROWS,
) -> List[LoopEvent]:
    """Fetch audit-v2 events and convert them to LoopEvent subclasses.

    Audit-v2 events live alongside memory writes in the `nodes` table
    under names beginning `auditv2:`. They carry tool calls, LLM calls,
    decisions, and read events — exactly the signals retry / polling /
    cost_inflation / tool_nondeterminism / decision_oscillation / etc
    need to fire on real data.
    """
    cur = connection.cursor()
    _setup_session(cur, tenant_id)

    cutoff = time.time() - (hours * 3600) if hours > 0 else 0
    name_filter = "auditv2:%"
    if agent_id:
        # Audit storage key: auditv2:{tenant_prefix}:{agent_id}:{ts}:{event_type}
        # We can't filter on agent_id efficiently in the LIKE without the
        # tenant_prefix, so we fetch broadly and filter in Python below.
        name_filter = f"auditv2:%:{agent_id}:%"

    cur.execute(
        """
        SELECT data, valid_from
        FROM nodes
        WHERE tenant_id = %s
          AND name LIKE %s
          AND valid_until = 0
          AND valid_from >= %s
        ORDER BY valid_from
        LIMIT %s
        """,
        (tenant_id, name_filter, cutoff, limit),
    )

    events: List[LoopEvent] = []
    for data, _ts in cur.fetchall():
        if not isinstance(data, dict):
            continue
        if agent_id and data.get("agent_id") != agent_id:
            continue
        ev = _audit_event_to_loop_event(data, tenant_id)
        if ev is not None:
            events.append(ev)
    return events


def fetch_events_per_agent(
    connection,
    tenant_id: str,
    hours: int = 24,
    limit: int = 5000,
) -> Dict[str, List[LoopEvent]]:
    """Fetch events grouped by agent_id."""
    events = fetch_events(connection, tenant_id, agent_id=None, hours=hours, limit=limit)
    per_agent: Dict[str, List[LoopEvent]] = {}
    for e in events:
        per_agent.setdefault(e.agent_id, []).append(e)
    return per_agent
