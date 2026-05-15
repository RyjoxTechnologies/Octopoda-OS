"""audit_v2.mcp_hooks - wrap FastMCP tool dispatch to log every tool call.

FastMCP exposes a single chokepoint for tool invocation:
    mcp._tool_manager.call_tool(name, args)

By wrapping that one method we capture every tool call through the MCP
server - no per-tool instrumentation needed. This means any new MCP tool
added to octopoda_mcp is automatically audited without touching this
module.

Event schema:
    tool.call   (pre-dispatch) -> only for slow tools where we want to
                                  see the intent before the outcome
    tool.result (post-dispatch, success)
    tool.error  (post-dispatch, failure)

We merge intent and outcome into a single event of type `tool.result` or
`tool.error` to keep the timeline tight (one row per call, not two).

Tenant resolution:
    MCP clients pass the OCTOPODA_API_KEY as an env var. We look up the
    tenant_id via the api_keys table on first call and cache it for the
    lifetime of the process.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import os
import time
from typing import Any, Optional

from . import log as _audit_log
from .cost import estimate_cost as _estimate_cost


# Map known tool names to their canonical event_type. If a tool isn't in
# here, we still audit it as "tool.call" (catch-all) so nothing is missed.
# This is informational - we keep it short because the tool name itself
# is already stored in the event's `key` field.
KNOWN_TOOLS = frozenset([
    "octopoda_remember", "octopoda_recall", "octopoda_search",
    "octopoda_recall_similar", "octopoda_recall_history", "octopoda_related",
    "octopoda_snapshot", "octopoda_restore",
    "octopoda_share", "octopoda_read_shared",
    "octopoda_list_agents", "octopoda_agent_stats",
    "octopoda_process_conversation", "octopoda_get_context",
    "octopoda_recall_similar",
    "octopoda_forget", "octopoda_forget_stale",
    "octopoda_consolidate", "octopoda_memory_health",
    "octopoda_loop_status", "octopoda_loop_history",
    "octopoda_send_message", "octopoda_read_messages",
    "octopoda_broadcast",
    "octopoda_set_goal", "octopoda_get_goal",
    "octopoda_update_progress",
    "octopoda_log_decision", "octopoda_search_filtered",
])


_cached_tenant_id: Optional[str] = None


def _lookup_tenant_id_from_api_key() -> Optional[str]:
    """One-time DB lookup: api_key -> tenant_id. Cached for process lifetime."""
    global _cached_tenant_id
    if _cached_tenant_id is not None:
        return _cached_tenant_id

    api_key = os.environ.get("OCTOPODA_API_KEY")
    dsn = os.environ.get("DATABASE_URL")
    if not api_key or not dsn:
        return None
    try:
        import psycopg2
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        conn = psycopg2.connect(dsn)
        try:
            cur = conn.cursor()
            cur.execute("SELECT tenant_id FROM api_keys WHERE key_hash = %s",
                        (key_hash,))
            row = cur.fetchone()
            if row:
                _cached_tenant_id = row[0]
                return _cached_tenant_id
        finally:
            conn.close()
    except Exception:
        pass
    return None


def _extract_agent_id(name: str, args: Any) -> str:
    """Best-effort agent_id extraction from MCP call arguments.

    FastMCP passes arguments as a dict keyed by parameter name. All our
    tools accept `agent_id` as a first parameter by convention. Fallback
    is a per-process default so events aren't silently dropped.
    """
    if isinstance(args, dict) and "agent_id" in args:
        return str(args["agent_id"])
    if isinstance(args, (list, tuple)) and args:
        first = args[0]
        if isinstance(first, str):
            return first
    return "mcp_default"


def _extract_key(name: str, args: Any) -> Optional[str]:
    """Pull a meaningful `key` field for the audit row based on tool name."""
    if not isinstance(args, dict):
        return None
    for candidate in ("key", "query", "prefix", "space", "entity",
                      "thread_id", "run_id", "label"):
        if candidate in args and args[candidate]:
            return str(args[candidate])
    return None


def instrument_mcp(mcp_instance: Any, *, tenant_id: Optional[str] = None) -> Any:
    """Patch mcp._tool_manager.call_tool so every tool call emits audit.

    Idempotent. Zero behaviour change if an audit write fails.
    """
    tm = getattr(mcp_instance, "_tool_manager", None)
    if tm is None:
        return mcp_instance

    if getattr(tm, "__audit_v2_instrumented__", False):
        return mcp_instance

    original_call_tool = tm.call_tool

    async def _audited_call_tool(name, args, *extra_args, **extra_kwargs):
        start = time.perf_counter()
        outcome = "success"
        error_message: Optional[str] = None
        result = None
        agent_id = _extract_agent_id(name, args)
        key = _extract_key(name, args)
        event_type = "tool.result"

        try:
            result = original_call_tool(name, args, *extra_args, **extra_kwargs)
            # Original may be coroutine
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            outcome = "fail"
            error_message = f"{type(e).__name__}: {e}"
            event_type = "tool.error"
            raise
        finally:
            try:
                latency_ms = int((time.perf_counter() - start) * 1000)
                tid = tenant_id or _lookup_tenant_id_from_api_key()
                if tid:
                    cost_usd = _estimate_cost(tid, event_type)
                    _audit_log(
                        tenant_id=tid,
                        event_type=event_type,
                        agent_id=agent_id,
                        source="mcp",
                        key=f"tool:{name}" + (f":{key}" if key else ""),
                        value=args if isinstance(args, dict) else None,
                        cost_usd=cost_usd,
                        latency_ms=latency_ms,
                        outcome=outcome,
                        error_message=error_message,
                        extra={
                            "tool": name,
                            "known_tool": name in KNOWN_TOOLS,
                        },
                    )
            except Exception:
                pass  # audit must not break caller

    # FastMCP's call_tool is async; we replace it with our async wrapper
    tm.call_tool = _audited_call_tool
    tm.__audit_v2_instrumented__ = True  # type: ignore[attr-defined]
    return mcp_instance


def uninstrument_mcp(mcp_instance: Any) -> Any:
    """Remove the wrapper. Best-effort."""
    tm = getattr(mcp_instance, "_tool_manager", None)
    if tm is None:
        return mcp_instance
    # We can't easily restore original without saving it; since this is
    # test-only, just reset the flag and rely on fresh process for cleanup.
    tm.__audit_v2_instrumented__ = False
    return mcp_instance
