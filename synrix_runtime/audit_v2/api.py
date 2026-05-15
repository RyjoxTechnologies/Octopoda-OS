"""audit_v2.api - FastAPI routes that the dashboard will eventually call.

These endpoints are NOT wired into the main cloud_server yet. They're
defined here in an isolated router so we can test them independently,
then mount them on the production app in a single-line change once
we're ready.

All routes require Bearer auth the same way the rest of the app does.
We reuse the existing TenantManager.verify_api_key for consistency.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional

try:
    from fastapi import APIRouter, Depends, HTTPException, Query, Header
    from fastapi.responses import StreamingResponse, JSONResponse
except ImportError:  # pragma: no cover
    APIRouter = None

from . import (
    list_events as _list,
    count_events as _count,
    get_event as _get,
    get_context as _get_ctx,
    verify_chain as _verify,
)


def _verify_auth(authorization: Optional[str] = Header(default=None)):
    """Re-uses TenantManager verification. Raises 401 if invalid."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    raw = authorization
    if raw.startswith("Bearer "):
        raw = raw[7:]
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        tenant = tm.verify_api_key(raw)
        if not tenant:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return tenant
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Auth error: {e}")


def build_router() -> "APIRouter":
    """Construct and return the audit-v2 router.

    Consumer wires it in with: app.include_router(router, prefix="/v1/audit_v2")
    """
    if APIRouter is None:
        raise RuntimeError("FastAPI not available")

    router = APIRouter(tags=["audit_v2"])

    @router.get("/events")
    def list_events_endpoint(
        agent_id: Optional[str] = Query(default=None),
        event_type: Optional[str] = Query(default=None),
        from_ts: Optional[float] = Query(default=None),
        to_ts: Optional[float] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        auth=Depends(_verify_auth),
    ):
        tid = auth["tenant_id"]
        events = _list(
            tid,
            agent_id=agent_id,
            event_type=event_type,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
            offset=offset,
        )
        total = _count(tid, agent_id=agent_id, event_type=event_type,
                        from_ts=from_ts, to_ts=to_ts)
        return {
            "events": events,
            "count": len(events),
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @router.get("/events/{row_id}")
    def get_event_endpoint(row_id: int, auth=Depends(_verify_auth)):
        tid = auth["tenant_id"]
        ev = _get(tid, row_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Event not found")
        return ev

    @router.get("/events/{row_id}/context")
    def get_context_endpoint(
        row_id: int,
        window: int = Query(default=5, ge=1, le=50),
        auth=Depends(_verify_auth),
    ):
        tid = auth["tenant_id"]
        return _get_ctx(tid, row_id, window=window)

    @router.get("/verify")
    def verify_chain_endpoint(
        agent_id: Optional[str] = Query(default=None),
        limit: int = Query(default=10000, ge=1, le=100000),
        auth=Depends(_verify_auth),
    ):
        tid = auth["tenant_id"]
        return _verify(tid, agent_id=agent_id, limit=limit)

    @router.get("/cost")
    def cost_rollup_endpoint(
        group_by: str = Query(default="agent",
                               pattern="^(agent|day|event_type)$"),
        from_ts: Optional[float] = Query(default=None),
        to_ts: Optional[float] = Query(default=None),
        auth=Depends(_verify_auth),
    ):
        """Aggregate cost_usd across events.

        Supports group_by = agent | day | event_type.
        """
        tid = auth["tenant_id"]
        events = _list(tid, from_ts=from_ts, to_ts=to_ts, limit=500)
        agg: Dict[str, Dict[str, Any]] = {}
        for e in events:
            if group_by == "agent":
                bucket = e.get("agent_id", "?")
            elif group_by == "event_type":
                bucket = e.get("event_type", "?")
            else:  # day
                import datetime as _dt
                ts = float(e.get("timestamp") or 0)
                bucket = _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
            entry = agg.setdefault(bucket, {"count": 0, "cost_usd": 0.0,
                                             "latency_ms_total": 0})
            entry["count"] += 1
            entry["cost_usd"] += float(e.get("cost_usd") or 0)
            entry["latency_ms_total"] += int(e.get("latency_ms") or 0)
        rows = [{"group": k, **v} for k, v in agg.items()]
        rows.sort(key=lambda r: r["cost_usd"], reverse=True)
        return {"group_by": group_by, "rows": rows}

    @router.get("/export")
    def export_csv_endpoint(
        agent_id: Optional[str] = Query(default=None),
        event_type: Optional[str] = Query(default=None),
        from_ts: Optional[float] = Query(default=None),
        to_ts: Optional[float] = Query(default=None),
        limit: int = Query(default=1000, ge=1, le=10000),
        auth=Depends(_verify_auth),
    ):
        """Stream a CSV of audit events matching the filter.

        Notes on safety:
          - Excel CSV injection: cells starting with = + @ - are evaluated as
            formulas. We prefix a single quote to neutralise them. That single
            quote is invisible in Excel but preserves the original content.
          - Tab/CR/LF at the start of a cell can also trigger Excel macros;
            we drop them.
        """
        tid = auth["tenant_id"]
        events = _list(tid, agent_id=agent_id, event_type=event_type,
                        from_ts=from_ts, to_ts=to_ts, limit=limit)

        def _safe_cell(val: Any) -> Any:
            if val is None:
                return ""
            if isinstance(val, (int, float, bool)):
                return val
            s = str(val)
            # Neutralise Excel formula-injection lead characters
            if s and s[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
                s = "'" + s
            return s

        # Build CSV in memory (simple and safe for limit <= 10_000)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "timestamp", "agent_id", "event_type", "source",
            "key", "value_preview", "tags", "cost_usd",
            "tokens_in", "tokens_out", "latency_ms",
            "outcome", "error_message",
        ])
        for e in events:
            writer.writerow([
                _safe_cell(e.get("timestamp", "")),
                _safe_cell(e.get("agent_id", "")),
                _safe_cell(e.get("event_type", "")),
                _safe_cell(e.get("source", "")),
                _safe_cell(e.get("key", "")),
                _safe_cell((e.get("value_preview") or "")[:240]),
                _safe_cell(",".join(e.get("tags", []) or [])),
                e.get("cost_usd", 0),
                e.get("tokens_in", 0),
                e.get("tokens_out", 0),
                e.get("latency_ms", 0),
                _safe_cell(e.get("outcome", "")),
                _safe_cell(e.get("error_message", "") or ""),
            ])
        buf.seek(0)
        headers = {
            "Content-Disposition": f'attachment; filename="audit-{tid[:8]}.csv"'
        }
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers=headers,
        )

    return router
