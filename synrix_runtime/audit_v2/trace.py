"""audit_v2.trace - correlation IDs for multi-agent / multi-call tracing.

A trace_id threads through every audit event that happens within its
scope. When agent A calls agent B, or agent A makes an LLM call which
internally writes memory, all those events share one trace_id and the
dashboard can stitch them together.

Implementation uses `contextvars.ContextVar` so propagation works across
threads and asyncio tasks without the caller doing anything.

Public API:
    generate_trace_id()               -> str        # new uuid4-based id
    current_trace_id()                -> Optional[str]
    set_trace_id(trace_id)            -> Token     # raw setter
    reset_trace_id(token)             -> None       # undo set_trace_id
    with trace_scope([trace_id]):     -> context-manager wrapper
        ...                           # any events in here share trace_id

Typical usage patterns:

    # 1. Incoming HTTP request - framework middleware sets it
    with trace_scope():
        process_request(...)

    # 2. Agent-to-agent handoff - outer agent passes trace_id explicitly
    def worker(task, trace_id=None):
        with trace_scope(trace_id):
            runtime.remember(...)   # inherits trace_id

    # 3. Background job - generate a fresh trace_id
    tid = generate_trace_id()
    with trace_scope(tid):
        ...                         # everything here tagged with tid

The audit_v2.log() function automatically reads current_trace_id() and
attaches it to the event's `extra` dict. So you never need to pass it
down manually to SDK / framework / MCP / LLM calls.
"""
from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional


# Context variable. Default None means no active trace.
_trace_id_var: contextvars.ContextVar[Optional[str]] = \
    contextvars.ContextVar("audit_v2_trace_id", default=None)


def generate_trace_id() -> str:
    """Return a fresh trace id. Prefixed `t-` so it's easy to spot in logs."""
    return "t-" + uuid.uuid4().hex[:16]


def current_trace_id() -> Optional[str]:
    """Return the active trace_id for this task/thread, or None."""
    return _trace_id_var.get()


def set_trace_id(trace_id: Optional[str]):
    """Raw setter. Returns a Token which can be passed to reset_trace_id.

    Prefer `trace_scope` for most use cases.
    """
    return _trace_id_var.set(trace_id)


def reset_trace_id(token) -> None:
    """Undo a previous set_trace_id. Must pass the Token it returned."""
    _trace_id_var.reset(token)


@contextmanager
def trace_scope(trace_id: Optional[str] = None) -> Iterator[str]:
    """Context manager that pins a trace_id to the current task/thread.

    If trace_id is None, a fresh one is generated. The active trace_id
    is restored to its previous value when the block exits - so nested
    scopes compose correctly.

    Yields the active trace_id so the caller can use it if needed.
    """
    tid = trace_id or generate_trace_id()
    token = _trace_id_var.set(tid)
    try:
        yield tid
    finally:
        _trace_id_var.reset(token)
