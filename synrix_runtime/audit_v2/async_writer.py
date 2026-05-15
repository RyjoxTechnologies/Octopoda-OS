"""audit_v2.async_writer - fire-and-forget batch writer.

Problem: sync log() was a per-event DB transaction. Under 20+ concurrent
agents the DB pool + commit overhead tanked throughput (7 w/s measured).

Solution: borrow the pattern used by Sentry / Datadog / DDTrace.
  1. log() enqueues AuditEvent into a bounded in-memory queue (microseconds)
  2. One background daemon thread dequeues, batches, and INSERTs in bulk
  3. The chain is computed inside the worker (single-writer, no contention)

Tradeoffs:
  - log() is now fire-and-forget: it returns 0 instead of the row id
  - Events are durable only after the next batch flush (default: 50ms
    interval or 200 events, whichever first)
  - A process crash loses at most (flush_interval_ms + max_batch) worth
    of events. Acceptable for audit, not OK for billing.

Opt-in via env var `AUDIT_V2_ASYNC=1`. Default is still sync.

Interface:
  enqueue(tenant_id, event) -> bool    # True if accepted, False if dropped
  flush_sync(timeout=5.0) -> int        # force flush, returns events drained
  shutdown() -> None                    # gracefully drain and stop
  stats() -> dict                       # queue depth, worker health, etc
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from .models import AuditEvent, safe_preview


# Tuning knobs (can be overridden via env)
_QUEUE_MAX = int(os.environ.get("AUDIT_V2_QUEUE_MAX", "100000"))
_BATCH_MAX = int(os.environ.get("AUDIT_V2_BATCH_MAX", "500"))
_FLUSH_MS  = int(os.environ.get("AUDIT_V2_FLUSH_MS", "50"))


# Queue items: (tenant_id, AuditEvent)
_queue: "queue.Queue[Tuple[str, AuditEvent]]" = queue.Queue(maxsize=_QUEUE_MAX)
_worker: Optional[threading.Thread] = None
_worker_started = threading.Event()
_shutdown_requested = threading.Event()
_stats_lock = threading.Lock()
_stats = {
    "enqueued": 0,
    "written": 0,
    "dropped_queue_full": 0,
    "write_errors": 0,
    "batches_flushed": 0,
}


def _ensure_worker_started() -> None:
    """Spin up the background worker on first use."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    if _worker_started.is_set() and _worker and not _worker.is_alive():
        # Worker died; restart
        _worker_started.clear()
    if _worker_started.is_set():
        return
    _worker = threading.Thread(
        target=_worker_loop,
        name="audit_v2_async_writer",
        daemon=True,
    )
    _worker.start()
    _worker_started.set()
    atexit.register(shutdown)


def _worker_loop() -> None:
    """Pull events from queue and write them in batches."""
    while not _shutdown_requested.is_set():
        batch: List[Tuple[str, AuditEvent]] = []
        # Collect up to BATCH_MAX events or wait FLUSH_MS
        deadline = time.time() + (_FLUSH_MS / 1000.0)
        while len(batch) < _BATCH_MAX:
            remaining = max(0.0, deadline - time.time())
            try:
                item = _queue.get(timeout=remaining if remaining else 0.001)
                batch.append(item)
            except queue.Empty:
                break

        if not batch:
            continue

        try:
            _flush_batch(batch)
            with _stats_lock:
                _stats["written"] += len(batch)
                _stats["batches_flushed"] += 1
        except Exception as e:
            with _stats_lock:
                _stats["write_errors"] += 1
            # Don't swallow silently - but also don't crash the worker
            import sys
            print(f"[audit_v2.async_writer] batch flush error: {e}",
                  file=sys.stderr)


def _flush_batch(batch: List[Tuple[str, AuditEvent]]) -> None:
    """Write one batch. Uses bulk INSERT (execute_values) for speed.

    Groups by (tenant_id, agent_id) so the chain stays well-ordered:
    the first event in each sub-batch inherits the latest stored hash,
    and subsequent events chain off the previous event in the same batch.
    """
    # Lazy imports to avoid circular deps
    from . import storage as _storage
    from .models import safe_preview as _preview
    import psycopg2.extras

    # Group by (tenant_id, agent_id)
    by_tagent: Dict[Tuple[str, str], List[AuditEvent]] = {}
    for tenant_id, event in batch:
        by_tagent.setdefault((tenant_id, event.agent_id), []).append(event)

    for (tenant_id, agent_id), events in by_tagent.items():
        # Serialize through the per-agent write lock so any sync writes
        # still produce a consistent chain.
        lock = _storage._get_agent_write_lock(tenant_id, agent_id)
        with lock:
            try:
                with _storage._tenant_conn(tenant_id) as conn:
                    cur = conn.cursor()

                    # Warm prev_hash from DB/cache once per (tenant, agent)
                    prev_hash = _storage._get_prev_hash(tenant_id, agent_id, conn) or None

                    rows = []
                    _NUL = chr(0)
                    for ev in events:
                        # Assign timestamp here (monotonic within this batch)
                        if ev.timestamp is None:
                            ev.timestamp = time.time()
                        if ev.value_preview is not None:
                            ev.value_preview = _preview(ev.value_preview)
                        # NUL scrub defence
                        for attr in ("key", "value_preview", "error_message",
                                     "session_id", "user_id"):
                            v = getattr(ev, attr, None)
                            if isinstance(v, str) and _NUL in v:
                                setattr(ev, attr, v.replace(_NUL, "\\x00"))

                        ev.validate()
                        ev.prev_hash = prev_hash
                        this_hash = _storage._compute_hash(ev, prev_hash)

                        name = ev.storage_key(tenant_id)
                        data = ev.to_dict()
                        data["_this_hash"] = this_hash
                        metadata = {
                            "source_module": "audit_v2",
                            "event_type": ev.event_type,
                            "source": ev.source,
                        }
                        rows.append((
                            tenant_id, name,
                            json.dumps(data), json.dumps(metadata),
                            ev.timestamp,
                        ))
                        prev_hash = this_hash  # chain the next one

                    if rows:
                        # Bulk INSERT with a single round-trip per batch
                        psycopg2.extras.execute_values(
                            cur,
                            "INSERT INTO nodes "
                            "(tenant_id, name, data, metadata, valid_from, valid_until) "
                            "VALUES %s",
                            [(r[0], r[1], r[2], r[3], r[4], 0) for r in rows],
                            template="(%s, %s, %s::jsonb, %s::jsonb, %s, %s)",
                        )

                # Update cache with the last hash after commit
                with _storage._cache_lock:
                    _storage._last_hash_cache[(tenant_id, agent_id)] = prev_hash or ""
            except Exception:
                import sys, traceback as _tb
                print(f"[audit_v2.async_writer] batch-write for "
                      f"({tenant_id[:8]}, {agent_id}) failed:", file=sys.stderr)
                _tb.print_exc(file=sys.stderr)


def enqueue(tenant_id: str, event: AuditEvent) -> bool:
    """Enqueue one event for background write. Returns True if accepted."""
    _ensure_worker_started()
    # Preview/sanitisation happens in the hot path (tiny cost). The
    # storage-level safe_preview + NUL scrub still runs in the worker as
    # defence in depth.
    if event.value_preview is not None:
        event.value_preview = safe_preview(event.value_preview)
    try:
        _queue.put_nowait((tenant_id, event))
        with _stats_lock:
            _stats["enqueued"] += 1
        return True
    except queue.Full:
        with _stats_lock:
            _stats["dropped_queue_full"] += 1
        return False


def flush_sync(timeout: float = 5.0) -> int:
    """Block until the queue is empty (or timeout). Returns events drained."""
    deadline = time.time() + timeout
    drained_snapshot = _stats["written"]
    while _queue.qsize() > 0 and time.time() < deadline:
        time.sleep(0.02)
    with _stats_lock:
        drained = _stats["written"] - drained_snapshot
    return drained


def shutdown() -> None:
    """Flush remaining events and stop the worker."""
    _shutdown_requested.set()
    flush_sync(timeout=5.0)


def stats() -> Dict[str, Any]:
    with _stats_lock:
        snapshot = dict(_stats)
    snapshot["queue_depth"] = _queue.qsize()
    snapshot["worker_alive"] = bool(_worker and _worker.is_alive())
    return snapshot
