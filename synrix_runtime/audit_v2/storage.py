"""audit_v2.storage - read/write audit events to Postgres nodes table.

We deliberately piggyback on the existing `nodes` table (instead of a
dedicated `audit_events_v2` table) because the app-level DB role doesn't
have CREATE TABLE rights on the managed Postgres instance. This keeps the
v1 deployment free of any admin-level schema changes.

Layout inside `nodes`:
  - name:     auditv2:<tenant_prefix>:<agent>:<ts_us>:<event_type>
  - data:     the full AuditEvent payload as JSON
  - metadata: {"source": "audit_v2", "event_type": "..."}  (lets future
              migrations find audit rows without a LIKE scan)
  - tenant_id: standard tenant_id column, RLS-isolated
  - valid_from: event timestamp
  - valid_until: 0 (audit events are immutable)

Every write computes sha256 over (prev_hash + canonical event) to form a
tamper-evident chain per-tenant. We cache the "last_prev_hash" per-tenant
in memory for performance; on first use we read the most recent event to
warm the cache.

RLS: caller is expected to have already set `app.tenant_id` for their
connection. Every function here asserts the connection's effective tenant
matches the tenant argument.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - module requires psycopg2
    psycopg2 = None

from .models import AuditEvent, safe_preview

# ----------------------------------------------------------------------
# Connection management
# ----------------------------------------------------------------------

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    """Return a lazy-initialised Postgres connection pool."""
    global _pool
    if _pool is not None:
        return _pool
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for audit_v2 storage")
    with _pool_lock:
        if _pool is None:
            dsn = os.environ.get("DATABASE_URL")
            if not dsn:
                raise RuntimeError("DATABASE_URL env var not set")
            from psycopg2 import pool
            # Pool size tuned for the audit hot path: reads + writes from
            # all instrumented hooks share this pool. The per-agent write
            # lock means at most one connection per agent in-flight at a
            # time. 64 is enough for dozens of concurrent agents without
            # falling into the retry backoff (which would make latency
            # spikes under load). Override with AUDIT_V2_POOL_MAX if needed.
            _maxconn = int(os.environ.get("AUDIT_V2_POOL_MAX", "64"))
            _pool = pool.ThreadedConnectionPool(minconn=2, maxconn=_maxconn, dsn=dsn)
    return _pool


@contextmanager
def _tenant_conn(tenant_id: str) -> Iterator[Any]:
    """Check out a connection and set its app.tenant_id for RLS.

    psycopg2 ThreadedConnectionPool.getconn() raises PoolError when
    maxconn is exhausted rather than blocking. For audit we retry with
    backoff so we never drop an event under burst load.
    """
    if not tenant_id:
        raise ValueError("tenant_id required for audit_v2 storage")
    pool = _get_pool()

    # Retry getconn with SHORT backoff to smooth over momentary bursts.
    # Long retry tails caused latency spikes so we keep the total wait
    # tight (~300ms) and bail out quickly if the pool is truly saturated.
    conn = None
    last_err = None
    for attempt in range(4):  # total wait at most ~310ms
        try:
            conn = pool.getconn()
            break
        except Exception as e:
            last_err = e
            time.sleep(0.01 * (2 ** attempt))  # 10ms, 20ms, 40ms, 80ms, ...
    if conn is None:
        raise RuntimeError(f"connection pool exhausted after retries: {last_err}")

    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SET LOCAL app.tenant_id = %s", (tenant_id,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ----------------------------------------------------------------------
# Hash chain (tamper-evidence)
# ----------------------------------------------------------------------

_last_hash_cache: Dict[tuple, str] = {}  # (tenant_id, agent_id) -> hash
_cache_lock = threading.Lock()

# Per-(tenant, agent) write lock. Serialises read-prev -> compute -> write so
# concurrent writes to the SAME agent produce a correctly-sequenced chain.
# Writes to DIFFERENT agents still proceed in parallel.
_per_agent_write_locks: Dict[tuple, threading.Lock] = {}
_locks_registry_lock = threading.Lock()


def _get_agent_write_lock(tenant_id: str, agent_id: str) -> threading.Lock:
    key = (tenant_id, agent_id)
    with _locks_registry_lock:
        lk = _per_agent_write_locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _per_agent_write_locks[key] = lk
        return lk


def _canonical_bytes(event: AuditEvent) -> bytes:
    """Deterministic byte representation for hashing. Excludes prev_hash
    so the event can be hashed independently of its position in the chain.
    """
    payload = event.to_dict()
    payload.pop("prev_hash", None)
    # Sort keys for deterministic output
    return json.dumps(payload, sort_keys=True, default=str).encode("utf-8")


def _compute_hash(event: AuditEvent, prev_hash: Optional[str]) -> str:
    h = hashlib.sha256()
    if prev_hash:
        h.update(prev_hash.encode("utf-8"))
        h.update(b"|")
    h.update(_canonical_bytes(event))
    return h.hexdigest()


def _get_prev_hash(tenant_id: str, agent_id: str, conn) -> Optional[str]:
    """Read the most recent prev_hash for this (tenant, agent). Warms cache.

    The hash chain is scoped per-agent so verify_chain can walk and check
    any single agent's history without seeing foreign hashes.
    """
    key = (tenant_id, agent_id)
    with _cache_lock:
        cached = _last_hash_cache.get(key)
        if cached is not None:
            return cached
    # Warm from DB
    prefix = f"auditv2:{tenant_id[:8]}:{agent_id}:%"
    cur = conn.cursor()
    cur.execute(
        "SELECT data FROM nodes "
        "WHERE tenant_id = %s AND name LIKE %s AND valid_until = 0 "
        "ORDER BY valid_from DESC, id DESC LIMIT 1",
        (tenant_id, prefix),
    )
    row = cur.fetchone()
    prev = None
    if row and row[0]:
        data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        # The chain is built from the prior event's _this_hash
        prev = data.get("_this_hash")
    with _cache_lock:
        _last_hash_cache[key] = prev or ""
    return prev


# ----------------------------------------------------------------------
# Write path
# ----------------------------------------------------------------------

def write_event(tenant_id: str, event: AuditEvent) -> int:
    """Persist one audit event. Returns the storage row id.

    - Sets prev_hash to form a tamper-evident chain per-tenant.
    - Writes to `nodes` using the agreed layout.
    - Validates the event before writing.
    """
    event.validate()
    # Timestamp is assigned INSIDE the write_lock (below) so its monotonic
    # ordering matches the order events hit the DB. Otherwise a thread
    # could set a timestamp, lose the CPU, and get scheduled in after a
    # thread with a LATER timestamp — breaking the chain order.
    _explicit_ts = event.timestamp is not None
    if event.value_preview is not None:
        event.value_preview = safe_preview(event.value_preview)
    # Final defence: strip any NUL byte that somehow survived, from ANY string field
    _NUL = chr(0)
    for attr in ("key", "value_preview", "error_message", "session_id", "user_id"):
        v = getattr(event, attr, None)
        if isinstance(v, str) and _NUL in v:
            setattr(event, attr, v.replace(_NUL, "\\x00"))

    # Serialise writes to the same agent so the hash chain is well-ordered.
    # Different agents proceed in parallel (one lock per (tenant, agent)).
    # IMPORTANT: cache update must happen INSIDE the write_lock so the next
    # waiter sees the current hash, not a stale value.
    write_lock = _get_agent_write_lock(tenant_id, event.agent_id)
    with write_lock:
        # Assign timestamp inside lock so it's strictly monotonic per agent.
        # If caller provided an explicit one (tests, back-filling) we respect it.
        if not _explicit_ts:
            event.timestamp = time.time()
        with _tenant_conn(tenant_id) as conn:
            # Chain: read most recent hash for THIS agent, then set ours
            prev_hash = _get_prev_hash(tenant_id, event.agent_id, conn) or None
            event.prev_hash = prev_hash
            this_hash = _compute_hash(event, prev_hash)

            name = event.storage_key(tenant_id)
            data = event.to_dict()
            data["_this_hash"] = this_hash  # stored so verify_chain can check
            metadata = {
                "source_module": "audit_v2",
                "event_type": event.event_type,
                "source": event.source,
            }
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO nodes (tenant_id, name, data, metadata, valid_from, valid_until) "
                "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, 0) RETURNING id",
                (tenant_id, name, json.dumps(data), json.dumps(metadata), event.timestamp),
            )
            new_id = cur.fetchone()[0]
        # Cache update MUST be inside write_lock, after commit has landed.
        with _cache_lock:
            _last_hash_cache[(tenant_id, event.agent_id)] = this_hash
    return new_id


# ----------------------------------------------------------------------
# Read path
# ----------------------------------------------------------------------

def _row_to_event(row) -> Dict[str, Any]:
    """Convert a nodes row into an audit event dict (without raising)."""
    _id, name, data = row[0], row[1], row[2]
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}
    data = dict(data or {})
    data["_row_id"] = _id
    data["_storage_key"] = name
    return data


def list_events(
    tenant_id: str,
    *,
    agent_id: Optional[str] = None,
    event_type: Optional[str] = None,
    from_ts: Optional[float] = None,
    to_ts: Optional[float] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return recent audit events for a tenant, newest first.

    All filters are optional. We use parameterised SQL to stay RLS-safe.
    """
    limit = max(1, min(limit, 1000))
    clauses = ["tenant_id = %s", "name LIKE 'auditv2:%%'", "valid_until = 0"]
    args: List[Any] = [tenant_id]
    if agent_id:
        clauses.append("name LIKE %s")
        args.append(f"auditv2:{tenant_id[:8]}:{agent_id}:%")
    if event_type:
        clauses.append("data->>'event_type' = %s")
        args.append(event_type)
    if from_ts is not None:
        clauses.append("valid_from >= %s")
        args.append(float(from_ts))
    if to_ts is not None:
        clauses.append("valid_from <= %s")
        args.append(float(to_ts))

    sql = (
        "SELECT id, name, data FROM nodes "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY valid_from DESC, id DESC LIMIT %s OFFSET %s"
    )
    args.extend([limit, offset])

    with _tenant_conn(tenant_id) as conn:
        cur = conn.cursor()
        cur.execute(sql, tuple(args))
        rows = cur.fetchall()
    return [_row_to_event(r) for r in rows]


def count_events(
    tenant_id: str,
    *,
    agent_id: Optional[str] = None,
    event_type: Optional[str] = None,
    from_ts: Optional[float] = None,
    to_ts: Optional[float] = None,
) -> int:
    """Count audit events matching the filter."""
    clauses = ["tenant_id = %s", "name LIKE 'auditv2:%%'", "valid_until = 0"]
    args: List[Any] = [tenant_id]
    if agent_id:
        clauses.append("name LIKE %s")
        args.append(f"auditv2:{tenant_id[:8]}:{agent_id}:%")
    if event_type:
        clauses.append("data->>'event_type' = %s")
        args.append(event_type)
    if from_ts is not None:
        clauses.append("valid_from >= %s")
        args.append(float(from_ts))
    if to_ts is not None:
        clauses.append("valid_from <= %s")
        args.append(float(to_ts))

    sql = f"SELECT COUNT(*) FROM nodes WHERE {' AND '.join(clauses)}"
    with _tenant_conn(tenant_id) as conn:
        cur = conn.cursor()
        cur.execute(sql, tuple(args))
        return int(cur.fetchone()[0])


def get_event(tenant_id: str, row_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single event by row id."""
    with _tenant_conn(tenant_id) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, data FROM nodes WHERE tenant_id = %s AND id = %s "
            "AND name LIKE 'auditv2:%%'",
            (tenant_id, row_id),
        )
        row = cur.fetchone()
    return _row_to_event(row) if row else None


def get_context(tenant_id: str, row_id: int, *, window: int = 5) -> Dict[str, Any]:
    """Return the event at row_id plus `window` events before and after it
    for the same agent. This is the dashboard's "story around this event".
    """
    target = get_event(tenant_id, row_id)
    if not target:
        return {"event": None, "before": [], "after": []}

    # Parse agent_id out of the storage key
    storage_key = target.get("_storage_key", "")
    parts = storage_key.split(":")
    agent_id = parts[2] if len(parts) > 3 else None
    ts = float(target.get("timestamp", 0))

    with _tenant_conn(tenant_id) as conn:
        cur = conn.cursor()
        # Events before
        cur.execute(
            "SELECT id, name, data FROM nodes "
            "WHERE tenant_id = %s AND name LIKE %s "
            "AND valid_from < %s AND valid_until = 0 "
            "ORDER BY valid_from DESC, id DESC LIMIT %s",
            (tenant_id, f"auditv2:{tenant_id[:8]}:{agent_id}:%" if agent_id else "auditv2:%%",
             ts, window),
        )
        before = [_row_to_event(r) for r in cur.fetchall()]
        before.reverse()
        # Events after
        cur.execute(
            "SELECT id, name, data FROM nodes "
            "WHERE tenant_id = %s AND name LIKE %s "
            "AND valid_from > %s AND valid_until = 0 "
            "ORDER BY valid_from ASC, id ASC LIMIT %s",
            (tenant_id, f"auditv2:{tenant_id[:8]}:{agent_id}:%" if agent_id else "auditv2:%%",
             ts, window),
        )
        after = [_row_to_event(r) for r in cur.fetchall()]
    return {"event": target, "before": before, "after": after}


# ----------------------------------------------------------------------
# Tamper-evidence verification
# ----------------------------------------------------------------------

def verify_chain(
    tenant_id: str,
    *,
    agent_id: Optional[str] = None,
    limit: int = 10000,
) -> Dict[str, Any]:
    """Walk the chain for this tenant (optionally scoped to an agent)
    and confirm every prev_hash matches the hash of the prior event.

    The hash chain is per-agent (each agent's first event has prev_hash=None
    and chains forward from there). This function verifies all agents'
    chains in a single pass and returns both an overall result and a
    per-agent breakdown.

    Returns {
      "ok": bool,
      "checked": int,
      "first_broken_row_id": Optional[int],
      "by_agent": {agent_id: {"ok": bool, "checked": int, "first_broken_row_id": Optional[int]}},
    }.
    """
    clauses = ["tenant_id = %s", "name LIKE 'auditv2:%%'", "valid_until = 0"]
    args: List[Any] = [tenant_id]
    if agent_id:
        clauses.append("name LIKE %s")
        args.append(f"auditv2:{tenant_id[:8]}:{agent_id}:%")
    sql = (
        "SELECT id, name, data FROM nodes "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY valid_from ASC, id ASC LIMIT %s"
    )
    args.append(limit)

    with _tenant_conn(tenant_id) as conn:
        cur = conn.cursor()
        cur.execute(sql, tuple(args))
        rows = cur.fetchall()

    expected_prev_by_agent: Dict[str, Optional[str]] = {}
    by_agent: Dict[str, Dict[str, Any]] = {}
    total_checked = 0
    overall_ok = True
    overall_first_broken: Optional[int] = None

    for row in rows:
        data = _row_to_event(row)
        # Skip synthesised derived events - they aren't part of the chain
        if (data.get("extra") or {}).get("synthesised"):
            continue
        a_id = data.get("agent_id")
        if not a_id:
            continue
        agent_state = by_agent.setdefault(a_id, {"ok": True, "checked": 0, "first_broken_row_id": None})
        stored_prev = data.get("prev_hash")
        expected = expected_prev_by_agent.get(a_id)  # None for first event of each agent

        if stored_prev != expected:
            if agent_state["ok"]:
                agent_state["ok"] = False
                agent_state["first_broken_row_id"] = data.get("_row_id")
            if overall_ok:
                overall_ok = False
                overall_first_broken = data.get("_row_id")
            # Do not advance this agent's expected_prev — chain is broken here
            continue

        # Reconstruct the hash of THIS event to use as next expected_prev for this agent
        ev = AuditEvent(
            agent_id=data["agent_id"],
            event_type=data["event_type"],
            source=data.get("source", "sdk"),
            key=data.get("key"),
            value_preview=data.get("value_preview"),
            tags=data.get("tags", []),
            cost_usd=data.get("cost_usd", 0.0),
            tokens_in=data.get("tokens_in", 0),
            tokens_out=data.get("tokens_out", 0),
            latency_ms=data.get("latency_ms", 0),
            outcome=data.get("outcome", "success"),
            error_message=data.get("error_message"),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            extra=data.get("extra", {}),
            prev_hash=stored_prev,
            timestamp=data.get("timestamp", 0.0),
        )
        expected_prev_by_agent[a_id] = _compute_hash(ev, stored_prev)
        agent_state["checked"] += 1
        total_checked += 1

    return {
        "ok": overall_ok,
        "checked": total_checked,
        "first_broken_row_id": overall_first_broken,
        "by_agent": by_agent,
    }
# ----------------------------------------------------------------------
# Convenience: delete events for a specific agent (used by tests/cleanup)
# ----------------------------------------------------------------------

def delete_agent_events(tenant_id: str, agent_id: str) -> int:
    """Hard-delete all audit events for an agent. Returns rows deleted.

    Uses the partial index idx_nodes_name_prefix which requires
    valid_until = 0 in the WHERE clause.
    """
    with _tenant_conn(tenant_id) as conn:
        cur = conn.cursor()
        # Find ids first (fast with partial index) then bulk delete by id
        cur.execute(
            "SELECT id FROM nodes "
            "WHERE tenant_id = %s AND name LIKE %s AND valid_until = 0",
            (tenant_id, f"auditv2:{tenant_id[:8]}:{agent_id}:%"),
        )
        ids = [r[0] for r in cur.fetchall()]
        n = 0
        # Delete in batches of 500 to avoid oversized statements
        for i in range(0, len(ids), 500):
            batch = ids[i:i+500]
            cur.execute("DELETE FROM nodes WHERE id = ANY(%s)", (batch,))
            n += cur.rowcount
    # Invalidate hash cache for this (tenant, agent)
    with _cache_lock:
        _last_hash_cache.pop((tenant_id, agent_id), None)
    return n
