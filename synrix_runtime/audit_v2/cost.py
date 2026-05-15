"""audit_v2.cost - attach real USD cost to each audit event.

Reuses the existing synrix_runtime.monitoring.cost_models module. The
tenant's `llm_model` setting (stored in tenant_settings table) determines
per-token pricing. Lookups are cached in-process with a 5-minute TTL so
we don't hit the DB on every event.

Public API:
    estimate_cost(tenant_id, event_type) -> float   # USD per event
    reset_cache()                                    # for tests
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional, Tuple


# (tenant_id, refresh_deadline) -> model_name
_model_cache: Dict[str, Tuple[str, float]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_llm_model(tenant_id: str) -> str:
    """Return tenant's configured LLM model, defaulting to 'unknown'.

    Read via direct SQL (no ORM dependency). Cached for 5 minutes.
    """
    now = time.time()
    with _cache_lock:
        entry = _model_cache.get(tenant_id)
        if entry and entry[1] > now:
            return entry[0]

    model = "unknown"
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        with _cache_lock:
            _model_cache[tenant_id] = (model, now + _CACHE_TTL_SECONDS)
        return model

    try:
        import psycopg2
        conn = psycopg2.connect(dsn)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT llm_model FROM tenant_settings WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                model = str(row[0])
        finally:
            conn.close()
    except Exception:
        pass  # fall back to 'unknown'

    with _cache_lock:
        _model_cache[tenant_id] = (model, now + _CACHE_TTL_SECONDS)
    return model


def estimate_cost(tenant_id: str, event_type: str) -> float:
    """Return USD cost for a single event of this type.

    Matches the broader cost model used elsewhere:
      - writes / shares cost the "per write" rate (includes embedding)
      - reads / semantic searches cost the "per read" rate
      - non-memory events (decisions, tool.*, crashes) default to 0

    Unknown event types return 0.0 (no panic).
    """
    if not tenant_id or not event_type:
        return 0.0
    # Lazy import so this module has no hard dep on cost_models if it's
    # refactored in future.
    try:
        from synrix_runtime.monitoring.cost_models import (
            get_cost_per_write, get_cost_per_read,
        )
    except Exception:
        return 0.0

    model = _get_llm_model(tenant_id)

    WRITE_KINDS = {
        "memory.write", "memory.important", "memory.share",
        "conversation.message", "crew.task", "crew.finding",
        "autogen.turn", "thread.updated",
    }
    READ_KINDS = {
        "memory.read", "memory.semantic_search", "memory.prefix_search",
        "memory.shared_read",
    }

    try:
        if event_type in WRITE_KINDS:
            return float(get_cost_per_write(model))
        if event_type in READ_KINDS:
            return float(get_cost_per_read(model))
    except Exception:
        return 0.0
    return 0.0


def reset_cache() -> None:
    """Clear the per-tenant model cache. Tests only."""
    with _cache_lock:
        _model_cache.clear()
