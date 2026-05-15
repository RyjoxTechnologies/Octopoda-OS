"""audit_v2 - Octopoda audit trail (isolated build, not yet wired to prod).

The short version:
  - Every SDK/framework/MCP call will eventually emit an AuditEvent via
    this module's `log()` function.
  - Events are persisted per-tenant in the existing `nodes` table under
    keys beginning `auditv2:` (no schema migration needed).
  - Each event joins a tamper-evident hash chain (prev_hash) so we can
    verify the log wasn't tampered with.
  - The module is completely self-contained: importing it has zero side
    effects on production code paths.

Public surface:
  log(tenant_id, event_type, agent_id, ...)  - emit one event
  list_events(tenant_id, ...)                - paginated read
  count_events(tenant_id, ...)               - count with filter
  get_event(tenant_id, row_id)               - fetch one
  get_context(tenant_id, row_id, window=5)   - story around an event
  verify_chain(tenant_id)                    - tamper-check
  delete_agent_events(tenant_id, agent_id)   - cleanup helper
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import AuditEvent, EVENT_TYPES, SOURCES, OUTCOMES, safe_preview
from . import storage as _storage
from .trace import current_trace_id as _current_trace_id


__all__ = [
    "AuditEvent",
    "EVENT_TYPES",
    "SOURCES",
    "OUTCOMES",
    "log",
    "list_events",
    "count_events",
    "get_event",
    "get_context",
    "verify_chain",
    "delete_agent_events",
    "safe_preview",
]


def log(
    tenant_id: str,
    event_type: str,
    agent_id: str,
    *,
    source: str = "sdk",
    key: Optional[str] = None,
    value: Any = None,
    tags: Optional[List[str]] = None,
    cost_usd: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    outcome: str = "success",
    error_message: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> int:
    """One-shot helper for callers. Constructs + writes an AuditEvent.

    Silent-failure is intentional: auditing MUST NOT break the main code
    path. If storage fails we return -1 and log the error internally.
    """
    # Auto-attach trace_id from the current scope (correlation tracking)
    _extra = dict(extra) if extra else {}
    _tid = _current_trace_id()
    if _tid and 'trace_id' not in _extra:
        _extra['trace_id'] = _tid
    try:
        ev = AuditEvent(
            agent_id=agent_id,
            event_type=event_type,
            source=source,
            key=key,
            value_preview=safe_preview(value) if value is not None else None,
            tags=tags or [],
            cost_usd=cost_usd,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            outcome=outcome,
            error_message=error_message,
            session_id=session_id,
            user_id=user_id,
            extra=_extra,
        )
        # Validate synchronously so invalid events are caught here and
        # never enter the queue. log() returns -1 for bad events so
        # callers get the same contract in sync and async modes.
        try:
            ev.validate()
        except ValueError as _ve:
            import sys
            print(f"[audit_v2] WARN: failed to log event {event_type!r}: {_ve}",
                  file=sys.stderr)
            return -1

        # Async path (default: enabled for high throughput; disable with
        # AUDIT_V2_ASYNC=0 to force each write to be durable before log()
        # returns).
        import os as _os
        if _os.environ.get("AUDIT_V2_ASYNC", "1") != "0":
            from . import async_writer as _aw
            if _aw.enqueue(tenant_id, ev):
                return 0  # pseudo-id: real id assigned at flush time
            # If the queue is full, fall through to sync write so we
            # never silently drop events.
        return _storage.write_event(tenant_id, ev)
    except Exception as e:
        # Never propagate audit failures to user code. Log and swallow.
        import sys
        print(f"[audit_v2] WARN: failed to log event {event_type!r}: {e}",
              file=sys.stderr)
        return -1


def list_events(tenant_id: str, **kwargs) -> List[Dict[str, Any]]:
    return _storage.list_events(tenant_id, **kwargs)


def count_events(tenant_id: str, **kwargs) -> int:
    return _storage.count_events(tenant_id, **kwargs)


def get_event(tenant_id: str, row_id: int) -> Optional[Dict[str, Any]]:
    return _storage.get_event(tenant_id, row_id)


def get_context(tenant_id: str, row_id: int, window: int = 5) -> Dict[str, Any]:
    return _storage.get_context(tenant_id, row_id, window=window)


def verify_chain(tenant_id: str, **kwargs) -> Dict[str, Any]:
    return _storage.verify_chain(tenant_id, **kwargs)


def delete_agent_events(tenant_id: str, agent_id: str) -> int:
    return _storage.delete_agent_events(tenant_id, agent_id)
