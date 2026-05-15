"""FastAPI router exposing Loop Intelligence v2 detections.

Mounted into cloud_server.py conditionally on OCTOPODA_LOOP_INTEL_V2=1.
Endpoints are gated by a tenant allowlist — tenants not in ALLOWED_TENANTS
receive {disabled: true} with an empty detections list.

Auth is delegated to cloud_server.verify_auth via lazy import (inside
handlers) to avoid circular-import issues at module load time.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from .adapter import fetch_events, fetch_events_per_agent
from .detection import detect
from .models import LoopDetection
from .registry import list_rules

logger = logging.getLogger(__name__)

# Loop Intel v2 is GA — no longer admin-gated. Every tenant gets it.
# The ALLOWED_TENANTS object below behaves like a set that contains every
# string, so all `tenant_id in ALLOWED_TENANTS` checks short-circuit to True
# without changing the rest of the codebase. To revert to allowlist-only,
# set OCTOPODA_LOOP_INTEL_V2_TENANTS to a comma-separated list.
class _AllowAllTenants:
    def __contains__(self, x: object) -> bool:
        return True
    def __iter__(self):
        return iter([])  # for compatibility with `for t in ALLOWED_TENANTS`
    def __bool__(self) -> bool:
        return True
    def __repr__(self) -> str:
        return "<AllowAllTenants: all tenants enabled>"


_raw = os.environ.get("OCTOPODA_LOOP_INTEL_V2_TENANTS", "").strip()
if _raw and _raw not in ("*", "ALL", "all"):
    # Explicit allowlist override (revert path)
    ALLOWED_TENANTS = {t.strip() for t in _raw.split(",") if t.strip()}
else:
    # Default: every tenant gets Loop Intel v2
    ALLOWED_TENANTS = _AllowAllTenants()

router = APIRouter(prefix="/v1/loops/v2", tags=["loop-intel-v2"])


def _detection_to_dict(d: LoopDetection) -> Dict[str, Any]:
    raw = asdict(d)
    raw["loop_type"] = d.loop_type.value
    raw["confidence"] = d.confidence.value
    return raw


async def _authenticate(authorization: Optional[str]) -> Dict[str, Any]:
    from synrix_runtime.api.cloud_server import verify_auth
    return await verify_auth(authorization)


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
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    return psycopg2.connect(url)


def _disabled_response(tenant_id: str, extra: Optional[dict] = None) -> Dict[str, Any]:
    out = {
        "disabled": True,
        "reason": "tenant_not_in_allowlist",
        "tenant_id": tenant_id,
        "detections": [],
    }
    if extra:
        out.update(extra)
    return out


@router.get("/status")
async def status_endpoint(authorization: Optional[str] = Header(None)):
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    return {
        "enabled": True,
        "tenant_id": tenant_id,
        "allowed_for_tenant": tenant_id in ALLOWED_TENANTS,
        "rules_live": [r.version for r in list_rules(status="live")],
        "rules_shadow": [r.version for r in list_rules(status="shadow")],
        "total_rules": len(list_rules()),
    }


@router.get("/rules")
async def list_rules_endpoint():
    return {
        "rules": [
            {
                "loop_type": r.loop_type.value,
                "version": r.version,
                "description": r.description_short,
                "status": r.status,
                "target_precision": r.target_precision,
                "target_recall": r.target_recall,
                "measured_precision": r.measured_precision,
                "measured_recall": r.measured_recall,
            }
            for r in list_rules()
        ]
    }


@router.get("/detect/{agent_id}")
async def detect_agent_endpoint(
    agent_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    authorization: Optional[str] = Header(None),
):
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id, {"agent_id": agent_id})
    conn = _get_connection()
    try:
        events = fetch_events(conn, tenant_id, agent_id=agent_id, hours=hours, limit=2000)
        detections = detect(events, agent_id=agent_id)
        return {
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "event_count": len(events),
            "detection_count": len(detections),
            "detections": [_detection_to_dict(d) for d in detections],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Apply-fix + Undo-fix
# ---------------------------------------------------------------------------

def _snapshot_then_delete(
    conn,
    tenant_id: str,
    agent_id: str,
    key: str,
    loop_type: str,
    window_start: Optional[float],
    window_end: Optional[float],
    keep_current: bool = True,
) -> Dict[str, Any]:
    """Snapshot rows to loop_intel_undo, then DELETE from nodes.

    Returns {fix_id, rows_count, deleted_history, deleted_current}.

    Snapshots include enough state to restore via /undo-fix:
      name, data, metadata, valid_from, valid_until, embedding (as text)
    """
    full_name = f"agents:{agent_id}:{key}"
    cur = conn.cursor()
    cur.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
    cur.execute("SET LOCAL statement_timeout = '10s'")

    where = "tenant_id = %s AND name = %s"
    params: List[Any] = [tenant_id, full_name]
    if window_start is not None:
        where += " AND valid_from >= %s"
        params.append(float(window_start))
    if window_end is not None:
        where += " AND valid_from <= %s"
        params.append(float(window_end))

    history_where = where + " AND valid_until != 0"
    current_where = where + " AND valid_until = 0"

    delete_where = history_where if keep_current else where

    # 1. Snapshot the rows that will be deleted.
    cur.execute(
        f"""SELECT name, data, metadata, valid_from, valid_until,
                   COALESCE(embedding::text, '') AS embedding_str
            FROM nodes WHERE {delete_where}""",
        tuple(params),
    )
    rows = cur.fetchall()
    rows_for_blob = [
        {
            "name": r[0],
            "data": r[1],
            "metadata": r[2],
            "valid_from": float(r[3]) if r[3] is not None else None,
            "valid_until": float(r[4]) if r[4] is not None else None,
            "embedding_str": r[5],
        }
        for r in rows
    ]

    fix_id = uuid.uuid4().hex
    if rows_for_blob:
        cur.execute(
            """INSERT INTO loop_intel_undo
                  (fix_id, tenant_id, agent_id, key, loop_type, rows_blob, rows_count)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)""",
            (fix_id, tenant_id, agent_id, key, loop_type,
             json.dumps(rows_for_blob, default=str), len(rows_for_blob)),
        )

    # 2. Delete from nodes.
    deleted_history = 0
    deleted_current = 0
    if keep_current:
        cur.execute(f"DELETE FROM nodes WHERE {history_where}", tuple(params))
        deleted_history = cur.rowcount
    else:
        cur.execute(f"DELETE FROM nodes WHERE {history_where}", tuple(params))
        deleted_history = cur.rowcount
        cur.execute(f"DELETE FROM nodes WHERE {current_where}", tuple(params))
        deleted_current = cur.rowcount

    conn.commit()
    return {
        "fix_id": fix_id if rows_for_blob else None,
        "rows_count": len(rows_for_blob),
        "deleted_history": deleted_history,
        "deleted_current": deleted_current,
    }


def _restore_from_undo(conn, tenant_id: str, fix_id: str) -> Dict[str, Any]:
    """Restore deleted rows from loop_intel_undo.

    Returns {restored, agent_id, key, loop_type} or raises 404.
    """
    cur = conn.cursor()
    cur.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
    cur.execute("SET LOCAL statement_timeout = '15s'")

    # Lazy cleanup of expired entries while we're here.
    cur.execute("DELETE FROM loop_intel_undo WHERE expires_at < now()")

    cur.execute(
        """SELECT rows_blob, agent_id, key, loop_type, rows_count
           FROM loop_intel_undo
           WHERE fix_id = %s AND tenant_id = %s AND expires_at > now()""",
        (fix_id, tenant_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Fix not found or already expired")
    rows_blob_raw, agent_id, key, loop_type, expected_count = row
    rows = (json.loads(rows_blob_raw) if isinstance(rows_blob_raw, str)
            else rows_blob_raw)

    restored = 0
    for r in rows:
        emb_str = r.get("embedding_str") or ""
        # data and metadata may be dicts (already parsed) or strings
        data = r["data"]
        metadata = r["metadata"]
        data_json = json.dumps(data) if not isinstance(data, str) else data
        meta_json = json.dumps(metadata) if not isinstance(metadata, str) else metadata
        if emb_str:
            try:
                cur.execute(
                    """INSERT INTO nodes
                          (tenant_id, name, data, metadata,
                           valid_from, valid_until, embedding)
                       VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::vector)""",
                    (tenant_id, r["name"], data_json, meta_json,
                     r["valid_from"], r["valid_until"], emb_str),
                )
            except Exception as e:
                # If embedding cast fails, restore without it.
                logger.warning("embedding restore failed (%s); inserting without", e)
                cur.execute(
                    """INSERT INTO nodes
                          (tenant_id, name, data, metadata,
                           valid_from, valid_until)
                       VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s)""",
                    (tenant_id, r["name"], data_json, meta_json,
                     r["valid_from"], r["valid_until"]),
                )
        else:
            cur.execute(
                """INSERT INTO nodes
                      (tenant_id, name, data, metadata,
                       valid_from, valid_until)
                   VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s)""",
                (tenant_id, r["name"], data_json, meta_json,
                 r["valid_from"], r["valid_until"]),
            )
        restored += 1

    cur.execute("DELETE FROM loop_intel_undo WHERE fix_id = %s", (fix_id,))
    conn.commit()
    return {
        "restored": restored,
        "expected": expected_count,
        "agent_id": agent_id,
        "key": key,
        "loop_type": loop_type,
    }


def _maybe_pause_agent(tenant_id: str, agent_id: str) -> Dict[str, Any]:
    """Best-effort agent pause; returns {paused: bool, error?}."""
    try:
        from synrix_runtime.monitoring.brain import LoopBreaker
        LoopBreaker.pause_agent(tenant_id, agent_id, reason="loop_intel_v2_apply_fix")
        return {"paused": True}
    except Exception as e:
        logger.warning("pause_agent failed: %s", e)
        return {"paused": False, "pause_error": str(e)}


# Per-loop-type apply-fix actions.

def _fix_reflection(conn, tenant_id: str, body: dict) -> Dict[str, Any]:
    agent_id = body.get("agent_id", "")
    evidence = body.get("evidence", {})
    key = evidence.get("artifact_key")
    if not agent_id or not key:
        raise HTTPException(status_code=400, detail="agent_id and evidence.artifact_key required")
    snap = _snapshot_then_delete(
        conn, tenant_id, agent_id, key, "reflection",
        window_start=evidence.get("window_start"),
        window_end=evidence.get("window_end"),
        keep_current=True,
    )
    return {
        "action": "deleted_redundant_revisions",
        "summary": f"Removed {snap['deleted_history']} redundant revisions of {key!r}; kept the current value.",
        "agent_id": agent_id,
        "key": key,
        **snap,
    }


def _fix_recall_write(conn, tenant_id: str, body: dict) -> Dict[str, Any]:
    agent_id = body.get("agent_id", "")
    evidence = body.get("evidence", {})
    key = evidence.get("key")
    if not agent_id or not key:
        raise HTTPException(status_code=400, detail="agent_id and evidence.key required")
    snap = _snapshot_then_delete(
        conn, tenant_id, agent_id, key, "recall_write",
        window_start=evidence.get("window_start"),
        window_end=evidence.get("window_end"),
        keep_current=True,
    )
    return {
        "action": "deleted_redundant_revisions",
        "summary": f"Removed {snap['deleted_history']} read-write cycle revisions of {key!r}.",
        "agent_id": agent_id,
        "key": key,
        **snap,
    }


def _fix_unsupported(conn, tenant_id: str, body: dict) -> Dict[str, Any]:
    return {
        "action": "manual",
        "summary": "Fix requires a code or config change. Copy the suggested_fix and apply manually.",
        "agent_id": body.get("agent_id", ""),
    }


_FIX_HANDLERS = {
    "reflection": _fix_reflection,
    "recall_write": _fix_recall_write,
    "retry": _fix_unsupported,
    "polling": _fix_unsupported,
    "decision_oscillation": _fix_unsupported,
    "cost_inflation": _fix_unsupported,
    "self_correction": _fix_unsupported,
    "ping_pong": _fix_unsupported,
    "tool_nondeterminism": _fix_unsupported,
    "clarification": _fix_unsupported,
}


@router.post("/apply-fix")
async def apply_fix_endpoint(
    body: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Apply the fix for a detection.

    Body:
        {
          "loop_type": "reflection" | ...,
          "agent_id": str,
          "evidence": {...},
          "pause_agent": bool   # optional, default false
        }

    For data-fix types (reflection, recall_write):
      - Snapshots the rows to loop_intel_undo (7-day TTL)
      - DELETEs them from nodes
      - Optionally pauses the agent
      - Returns {fix_id, action, summary, deleted_history, deleted_current,
                 paused, undo_url}

    For code-fix types (retry, polling, etc.): returns {action: "manual"}.
    """
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id, {"action": "disabled"})

    loop_type = body.get("loop_type", "")
    handler = _FIX_HANDLERS.get(loop_type)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unknown loop_type: {loop_type!r}")

    conn = _get_connection()
    try:
        result = handler(conn, tenant_id, body)
        result["tenant_id"] = tenant_id
        result["loop_type"] = loop_type

        # Pause-on-fix
        if body.get("pause_agent") and result.get("agent_id"):
            result.update(_maybe_pause_agent(tenant_id, result["agent_id"]))
        else:
            result["paused"] = False

        # Convenience: undo URL if we have a fix_id
        if result.get("fix_id"):
            result["undo_url"] = f"/v1/loops/v2/undo-fix/{result['fix_id']}"

        return result
    finally:
        conn.close()


@router.post("/undo-fix/{fix_id}")
async def undo_fix_endpoint(
    fix_id: str,
    authorization: Optional[str] = Header(None),
):
    """Restore the rows deleted by a prior apply-fix call.

    Returns 404 if fix_id is unknown or older than 7 days.
    """
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id, {"fix_id": fix_id})
    conn = _get_connection()
    try:
        result = _restore_from_undo(conn, tenant_id, fix_id)
        result["tenant_id"] = tenant_id
        return result
    finally:
        conn.close()


@router.get("/undo-fix")
async def list_undo_endpoint(
    authorization: Optional[str] = Header(None),
):
    """List recent fixes that are still undoable (within their 7-day window)."""
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
        cur.execute("DELETE FROM loop_intel_undo WHERE expires_at < now()")
        cur.execute(
            """SELECT fix_id, agent_id, key, loop_type, rows_count, created_at, expires_at
               FROM loop_intel_undo
               WHERE tenant_id = %s
               ORDER BY created_at DESC LIMIT 50""",
            (tenant_id,),
        )
        fixes = []
        for r in cur.fetchall():
            fixes.append({
                "fix_id": r[0],
                "agent_id": r[1],
                "key": r[2],
                "loop_type": r[3],
                "rows_count": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "expires_at": r[6].isoformat() if r[6] else None,
            })
        return {"tenant_id": tenant_id, "count": len(fixes), "fixes": fixes}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Circuit breaker — admin endpoints
# ---------------------------------------------------------------------------

@router.get("/circuit-breaker/config")
async def cb_get_config(authorization: Optional[str] = Header(None)):
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
        cur.execute(
            """SELECT id, agent_id, threshold_usd_per_min, enabled, notify_email,
                      pause_count, last_paused_at, created_at, updated_at
               FROM circuit_breaker_config
               WHERE tenant_id = %s
               ORDER BY agent_id NULLS FIRST""",
            (tenant_id,),
        )
        rows = []
        for r in cur.fetchall():
            rows.append({
                "id": r[0],
                "agent_id": r[1],  # null = tenant default
                "threshold_usd_per_min": float(r[2]) if r[2] is not None else None,
                "enabled": r[3],
                "notify_email": r[4],
                "pause_count": r[5],
                "last_paused_at": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat() if r[7] else None,
                "updated_at": r[8].isoformat() if r[8] else None,
            })
        return {"tenant_id": tenant_id, "configs": rows, "count": len(rows)}
    finally:
        conn.close()


@router.post("/circuit-breaker/config")
async def cb_set_config(
    body: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Insert or update a threshold.

    Body: {agent_id?: str, threshold_usd_per_min: float, enabled?: bool, notify_email?: str}
    agent_id null/omitted = tenant default.
    """
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    threshold = body.get("threshold_usd_per_min")
    if threshold is None:
        raise HTTPException(status_code=400, detail="threshold_usd_per_min required")
    agent_id = body.get("agent_id")  # None => tenant default
    enabled = body.get("enabled", True)
    notify_email = body.get("notify_email")
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO circuit_breaker_config
                  (tenant_id, agent_id, threshold_usd_per_min, enabled, notify_email)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (tenant_id, agent_id)
               DO UPDATE SET threshold_usd_per_min = EXCLUDED.threshold_usd_per_min,
                             enabled = EXCLUDED.enabled,
                             notify_email = EXCLUDED.notify_email,
                             updated_at = now()
               RETURNING id""",
            (tenant_id, agent_id, float(threshold), enabled, notify_email),
        )
        row = cur.fetchone()
        conn.commit()
        return {"id": row[0], "tenant_id": tenant_id, "agent_id": agent_id,
                "threshold_usd_per_min": float(threshold), "enabled": enabled,
                "notify_email": notify_email}
    finally:
        conn.close()


@router.delete("/circuit-breaker/config/{config_id}")
async def cb_delete_config(
    config_id: int,
    authorization: Optional[str] = Header(None),
):
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM circuit_breaker_config WHERE id = %s AND tenant_id = %s",
            (config_id, tenant_id),
        )
        deleted = cur.rowcount
        conn.commit()
        if not deleted:
            raise HTTPException(status_code=404, detail="config not found")
        return {"deleted": deleted, "id": config_id}
    finally:
        conn.close()


@router.post("/circuit-breaker/check")
async def cb_check_now(authorization: Optional[str] = Header(None)):
    """Trigger a circuit-breaker check immediately for the caller's tenant.

    Useful for testing + dashboard pull-to-refresh. Returns the actions taken.
    """
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    from .circuit_breaker import check_tenant
    conn = _get_connection()
    try:
        actions = check_tenant(conn, tenant_id)
        return {"tenant_id": tenant_id, "actions": actions, "count": len(actions)}
    finally:
        conn.close()


@router.get("/circuit-breaker/status")
async def cb_status(authorization: Optional[str] = Header(None)):
    """Current spend rate per agent over the last WINDOW_SEC seconds."""
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    from .circuit_breaker import compute_recent_spend, WINDOW_SEC
    conn = _get_connection()
    try:
        spend = compute_recent_spend(conn, tenant_id)
        return {
            "tenant_id": tenant_id,
            "window_sec": WINDOW_SEC,
            "spend_by_agent": [
                {"agent_id": a, "spend_usd": round(v, 6),
                 "rate_usd_per_min": round(v * 60.0 / WINDOW_SEC, 6)}
                for a, v in sorted(spend.items(), key=lambda kv: -kv[1])
            ],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dedup guards — admin endpoints
# ---------------------------------------------------------------------------

@router.get("/dedup-guard")
async def dg_list(authorization: Optional[str] = Header(None)):
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
        cur.execute(
            """SELECT id, agent_id, key_pattern, similarity_threshold,
                      blocks_count, created_at, expires_at
               FROM dedup_guards
               WHERE tenant_id = %s AND (expires_at IS NULL OR expires_at > now())
               ORDER BY created_at DESC""",
            (tenant_id,),
        )
        guards = []
        for r in cur.fetchall():
            guards.append({
                "id": r[0],
                "agent_id": r[1],
                "key_pattern": r[2],
                "similarity_threshold": float(r[3]),
                "blocks_count": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "expires_at": r[6].isoformat() if r[6] else None,
            })
        return {"tenant_id": tenant_id, "guards": guards, "count": len(guards)}
    finally:
        conn.close()


@router.post("/dedup-guard")
async def dg_install(
    body: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """Install a guard.

    Body: {agent_id, key_pattern, similarity_threshold?, expires_in_seconds?}

    key_pattern can be exact (`pipeline:health-check`) or wildcard
    (`pipeline:*` or `customer:*:status`).
    """
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    agent_id = body.get("agent_id")
    key_pattern = body.get("key_pattern")
    threshold = float(body.get("similarity_threshold", 0.95))
    expires_in = body.get("expires_in_seconds")
    if not agent_id or not key_pattern:
        raise HTTPException(status_code=400, detail="agent_id and key_pattern required")
    expires_clause = "expires_at = now() + (%s || ' seconds')::interval" if expires_in else "expires_at = NULL"
    conn = _get_connection()
    try:
        cur = conn.cursor()
        # ON CONFLICT updates threshold + extends expiry
        if expires_in:
            cur.execute(
                f"""INSERT INTO dedup_guards
                       (tenant_id, agent_id, key_pattern, similarity_threshold,
                        expires_at)
                    VALUES (%s, %s, %s, %s, now() + (%s || ' seconds')::interval)
                    ON CONFLICT (tenant_id, agent_id, key_pattern)
                    DO UPDATE SET similarity_threshold = EXCLUDED.similarity_threshold,
                                  {expires_clause}
                    RETURNING id""",
                (tenant_id, agent_id, key_pattern, threshold, str(expires_in), str(expires_in)),
            )
        else:
            cur.execute(
                """INSERT INTO dedup_guards
                       (tenant_id, agent_id, key_pattern, similarity_threshold)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (tenant_id, agent_id, key_pattern)
                    DO UPDATE SET similarity_threshold = EXCLUDED.similarity_threshold,
                                  expires_at = NULL
                    RETURNING id""",
                (tenant_id, agent_id, key_pattern, threshold),
            )
        row = cur.fetchone()
        conn.commit()
        return {"id": row[0], "tenant_id": tenant_id, "agent_id": agent_id,
                "key_pattern": key_pattern, "similarity_threshold": threshold,
                "expires_in_seconds": expires_in}
    finally:
        conn.close()


@router.delete("/dedup-guard/{guard_id}")
async def dg_delete(
    guard_id: int,
    authorization: Optional[str] = Header(None),
):
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM dedup_guards WHERE id = %s AND tenant_id = %s",
            (guard_id, tenant_id),
        )
        deleted = cur.rowcount
        conn.commit()
        if not deleted:
            raise HTTPException(status_code=404, detail="guard not found")
        return {"deleted": deleted, "id": guard_id}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auto-start side effects on import.
# ---------------------------------------------------------------------------

try:
    from .circuit_breaker import start_watcher_once
    start_watcher_once()
except Exception as _e:
    logger.warning("circuit-breaker watcher not started: %s", _e)

try:
    from .dedup_guard import install_patch_once
    install_patch_once()
except Exception as _e:
    logger.warning("dedup_guard not installed: %s", _e)


@router.get("/detect")
async def detect_all_endpoint(
    hours: int = Query(default=24, ge=1, le=720),
    authorization: Optional[str] = Header(None),
):
    auth = await _authenticate(authorization)
    tenant_id = auth.get("tenant_id", "")
    if tenant_id not in ALLOWED_TENANTS:
        return _disabled_response(tenant_id)
    conn = _get_connection()
    try:
        per_agent = fetch_events_per_agent(conn, tenant_id, hours=hours, limit=5000)
        all_detections: List[dict] = []
        total_events = 0
        for agent_id, events in per_agent.items():
            total_events += len(events)
            ds = detect(events, agent_id=agent_id)
            for d in ds:
                all_detections.append(_detection_to_dict(d))
        flat = [e for evs in per_agent.values() for e in evs]
        for d in detect(flat, agent_id=""):
            if d.loop_type.value == "ping_pong":
                all_detections.append(_detection_to_dict(d))
        conf_order = {"high": 0, "medium": 1, "low": 2}
        all_detections.sort(key=lambda d: (conf_order.get(d["confidence"], 3), d["loop_type"]))
        return {
            "tenant_id": tenant_id,
            "agent_count": len(per_agent),
            "event_count": total_events,
            "detection_count": len(all_detections),
            "detections": all_detections,
        }
    finally:
        conn.close()
