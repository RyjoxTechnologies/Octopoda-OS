"""Memory-level dedup guard.

Stores per-agent, per-key-pattern guards that block server-side writes
of values too similar to the existing current value. Each guard:
  - Has a similarity threshold (default 0.95)
  - Is scoped to (tenant_id, agent_id, key_pattern)
  - Optional expiry — guards can be temporary

How blocking happens:
  - This module monkey-patches `AgentRuntime.remember` on first import
  - Before the original remember runs, we check guards matching the
    (tenant_id, agent_id, key) tuple
  - If a matching guard fires (similarity >= threshold), the write is
    suppressed and the call returns a synthetic MemoryResult with
    blocked_by_guard=True
  - On block, blocks_count on the guard row is incremented

The guard does NOT touch existing rows — only new writes after the guard
is installed are filtered.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

from .similarity import text_similarity

logger = logging.getLogger(__name__)

_patched = False
_patch_lock = threading.Lock()


def _get_connection():
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            for line in open("/root/octopoda/.env"):
                if line.startswith("DATABASE_URL="):
                    url = line.strip().split("=", 1)[1].strip('"').strip("'")
                    break
        except Exception:
            pass
    return psycopg2.connect(url, connect_timeout=5)


def _matching_guards(conn, tenant_id: str, agent_id: str, key: str):
    """Return list of (guard_id, threshold) for guards that match this write."""
    cur = conn.cursor()
    cur.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
    cur.execute("SET LOCAL statement_timeout = '2s'")
    cur.execute(
        """SELECT id, similarity_threshold, key_pattern
           FROM dedup_guards
           WHERE tenant_id = %s AND agent_id = %s
             AND (expires_at IS NULL OR expires_at > now())""",
        (tenant_id, agent_id),
    )
    matches = []
    for gid, thr, pat in cur.fetchall():
        # key_pattern can be exact match or '*' suffix wildcard.
        if pat == key or (pat.endswith("*") and key.startswith(pat[:-1])):
            matches.append((gid, float(thr), pat))
    return matches


def _read_current_value(conn, tenant_id: str, agent_id: str, key: str) -> Optional[Any]:
    """Read the current (valid_until=0) value for a key; return None if missing."""
    full_name = f"agents:{agent_id}:{key}"
    cur = conn.cursor()
    cur.execute(
        """SELECT data FROM nodes
           WHERE tenant_id = %s AND name = %s AND valid_until = 0
           LIMIT 1""",
        (tenant_id, full_name),
    )
    row = cur.fetchone()
    if not row:
        return None
    data = row[0]
    if isinstance(data, dict):
        return data.get("value", data)
    return data


def _record_block(conn, guard_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        """UPDATE dedup_guards
           SET blocks_count = blocks_count + 1
           WHERE id = %s""",
        (guard_id,),
    )
    conn.commit()


def check_and_block(tenant_id: str, agent_id: str, key: str, new_value: Any) -> Optional[dict]:
    """Return None if the write should proceed, or a dict if blocked.

    If blocked, increments the guard's blocks_count.
    """
    try:
        conn = _get_connection()
        try:
            matches = _matching_guards(conn, tenant_id, agent_id, key)
            if not matches:
                return None
            current = _read_current_value(conn, tenant_id, agent_id, key)
            if current is None:
                return None  # No existing value — nothing to compare against, allow.
            for guard_id, threshold, pattern in matches:
                sim = text_similarity(current, new_value)
                if sim >= threshold:
                    _record_block(conn, guard_id)
                    return {
                        "blocked_by_guard": True,
                        "guard_id": guard_id,
                        "guard_pattern": pattern,
                        "threshold": threshold,
                        "similarity": round(sim, 4),
                        "key": key,
                        "agent_id": agent_id,
                    }
            return None
        finally:
            conn.close()
    except Exception as e:
        # Best-effort — never break a write because the guard had a problem.
        logger.warning("dedup_guard check failed: %s", e)
        return None


def install_patch_once() -> bool:
    """Idempotent: monkey-patch AgentRuntime.remember to consult guards.

    The patched method short-circuits with a synthetic MemoryResult if a
    matching guard fires. Otherwise delegates to the original remember.
    """
    global _patched
    with _patch_lock:
        if _patched:
            return False
        try:
            from synrix_runtime.api.runtime import AgentRuntime, MemoryResult
        except Exception as e:
            logger.warning("dedup_guard could not patch runtime: %s", e)
            return False

        original_remember = AgentRuntime.remember

        def patched_remember(self, key, value, tags=None):
            logger.info("dedup_guard intercepting remember tenant=%s agent=%s key=%s",
                        getattr(self, 'tenant_id', '?'), getattr(self, 'agent_id', '?'), key)
            block = check_and_block(self.tenant_id, self.agent_id, key, value)
            if block is not None:
                # Build a synthetic MemoryResult shape so callers don't break.
                # MemoryResult is a dataclass; field set varies — we set best-effort.
                try:
                    return MemoryResult(
                        node_id=None,
                        key=key,
                        latency_us=0.0,
                        timestamp=time.time(),
                        success=True,
                        loop_warning=None,
                        warning=f"blocked_by_guard:{block['guard_pattern']}",
                    )
                except TypeError:
                    # Older MemoryResult without `warning` field — fall back.
                    return MemoryResult(
                        node_id=None,
                        key=key,
                        latency_us=0.0,
                        timestamp=time.time(),
                        success=True,
                    )
            return original_remember(self, key, value, tags)

        AgentRuntime.remember = patched_remember
        _patched = True
        logger.info("dedup_guard: AgentRuntime.remember patched successfully")
        return True
