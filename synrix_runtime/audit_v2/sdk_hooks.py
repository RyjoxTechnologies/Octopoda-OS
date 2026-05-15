"""audit_v2.sdk_hooks - attach auditing to an AgentRuntime.

Does not modify any production code. The caller opts in by calling
`instrument(runtime)` on an existing runtime instance. Once instrumented,
every SDK call emits an audit event via audit_v2.log().

Design:
  - Wrap each method with a decorator that measures wall-clock latency
    and captures result/exception
  - Audit failures are swallowed (never break user code)
  - Tenant resolution priority:
      1. tenant_id argument to instrument()
      2. runtime.tenant_id attribute if set
      3. OCTOPODA_TENANT_ID env var
      4. Derived from OCTOPODA_API_KEY via a one-time TenantManager lookup

Method -> event_type mapping:
    remember(key, value)           -> memory.write
    remember_important(key, value) -> memory.important
    recall(key)                    -> memory.read
    recall_similar(query)          -> memory.semantic_search
    search(prefix)                 -> memory.prefix_search
    share(key, value)              -> memory.share
    read_shared(key)               -> memory.shared_read
    forget(key)                    -> memory.delete
"""
from __future__ import annotations

import functools
import os
import time
from typing import Any, Callable, Optional

from . import log as _audit_log
from .cost import estimate_cost as _estimate_cost


# Methods we wrap and the event type each one emits.
# Ordered from "most common" to "niche" purely for readability.
_SDK_METHODS = {
    "remember":           "memory.write",
    "remember_important": "memory.important",
    "recall":             "memory.read",
    "recall_similar":     "memory.semantic_search",
    "search":             "memory.prefix_search",
    "share":              "memory.share",
    "read_shared":        "memory.shared_read",
    "forget":             "memory.delete",
}


def _resolve_tenant_id(runtime: Any, explicit: Optional[str]) -> Optional[str]:
    """Figure out the tenant_id for this runtime without breaking things."""
    if explicit:
        return explicit
    # Runtime may already carry tenant_id (cloud-mode runtimes do)
    tid = getattr(runtime, "tenant_id", None)
    if tid:
        return tid
    # Env var override (useful for tests)
    env_tid = os.environ.get("OCTOPODA_TENANT_ID")
    if env_tid:
        return env_tid
    # Last-ditch: look up from API key
    api_key = os.environ.get("OCTOPODA_API_KEY")
    if api_key:
        try:
            import hashlib
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            # The TenantManager knows how to map. But we want to avoid
            # importing production code here, so we do a tiny direct query.
            import psycopg2
            dsn = os.environ.get("DATABASE_URL")
            if not dsn:
                return None
            conn = psycopg2.connect(dsn)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT tenant_id FROM api_keys WHERE key_hash = %s",
                    (key_hash,),
                )
                row = cur.fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        except Exception:
            return None
    return None


def _extract_key_value(method_name: str, args: tuple, kwargs: dict):
    """Best-effort extraction of key and value from call args."""
    key = None
    value = None

    if args:
        # Most methods: first positional = key
        if method_name in ("remember", "remember_important", "share",
                            "recall", "read_shared", "forget"):
            key = args[0] if args else kwargs.get("key")
            if method_name in ("remember", "remember_important", "share"):
                value = args[1] if len(args) > 1 else kwargs.get("value")
        elif method_name == "recall_similar":
            key = args[0] if args else kwargs.get("query")
        elif method_name == "search":
            key = args[0] if args else kwargs.get("prefix")

    if key is None:
        key = kwargs.get("key") or kwargs.get("query") or kwargs.get("prefix")
    if value is None:
        value = kwargs.get("value")

    return key, value


def _make_wrapper(
    original: Callable,
    *,
    event_type: str,
    method_name: str,
    agent_id: str,
    tenant_id: Optional[str],
    source: str = "sdk",
) -> Callable:
    """Build a drop-in wrapper that preserves signature + emits audit."""

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        start = time.perf_counter()
        outcome = "success"
        error_message = None
        result = None
        try:
            result = original(*args, **kwargs)
            return result
        except Exception as e:
            outcome = "fail"
            error_message = f"{type(e).__name__}: {e}"
            raise
        finally:
            if tenant_id:
                try:
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    key, value = _extract_key_value(method_name, args, kwargs)
                    # Tags: pull from kwargs if method supports it
                    tags = kwargs.get("tags") or []
                    cost_usd = _estimate_cost(tenant_id, event_type)
                    _audit_log(
                        tenant_id=tenant_id,
                        event_type=event_type,
                        cost_usd=cost_usd,
                        agent_id=agent_id,
                        source=source,
                        key=key,
                        value=value,
                        tags=tags if isinstance(tags, list) else [],
                        latency_ms=latency_ms,
                        outcome=outcome,
                        error_message=error_message,
                    )
                except Exception:
                    pass  # audit MUST NEVER break the runtime

    # Mark so we can detect double-instrumenting
    wrapped.__audit_v2_wrapped__ = True  # type: ignore[attr-defined]
    return wrapped


def instrument(runtime: Any, *, tenant_id: Optional[str] = None,
               source: str = "sdk") -> Any:
    """Attach audit hooks to a runtime instance.

    Idempotent - calling twice on the same runtime is a no-op.
    Returns the runtime for chaining.
    """
    agent_id = getattr(runtime, "agent_id", None)
    if not agent_id:
        return runtime  # cannot audit without agent id

    resolved_tid = _resolve_tenant_id(runtime, tenant_id)
    if not resolved_tid:
        return runtime  # cannot audit without tenant

    # Store on runtime for introspection
    runtime._audit_v2_tenant_id = resolved_tid

    for method_name, event_type in _SDK_METHODS.items():
        original = getattr(runtime, method_name, None)
        if original is None:
            continue
        # Already wrapped? Skip.
        if getattr(original, "__audit_v2_wrapped__", False):
            continue
        wrapped = _make_wrapper(
            original,
            event_type=event_type,
            method_name=method_name,
            agent_id=agent_id,
            tenant_id=resolved_tid,
            source=source,
        )
        setattr(runtime, method_name, wrapped)

    runtime._audit_v2_instrumented = True  # type: ignore[attr-defined]
    return runtime


def uninstrument(runtime: Any) -> Any:
    """Best-effort removal of hooks (restores bound methods from class).

    Useful in tests. Not required in normal use.
    """
    if not getattr(runtime, "_audit_v2_instrumented", False):
        return runtime
    cls = type(runtime)
    for method_name in _SDK_METHODS:
        if hasattr(runtime, method_name):
            try:
                delattr(runtime, method_name)
            except AttributeError:
                pass
            # Re-bind the class method
            class_method = getattr(cls, method_name, None)
            if class_method is not None:
                setattr(runtime, method_name, class_method.__get__(runtime, cls))
    runtime._audit_v2_instrumented = False  # type: ignore[attr-defined]
    return runtime
