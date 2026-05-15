"""audit_v2.framework_hooks - attach auditing to the framework memory classes.

Covers the wrapper classes exposed as:
    octopoda.LangChainMemory        -> SynrixMemory (synrix_runtime.integrations.langchain_memory)
    octopoda.CrewAIMemory           -> SynrixCrewMemory (crewai_memory)
    octopoda.AutoGenMemory          -> SynrixAutoGenMemory (autogen_memory)
    octopoda.OpenAIAgentsMemory     -> SynrixOpenAIMemory (openai_agents)
    octopoda.OctopodaChatHistory    -> classes/langchain.py

The public entrypoint is `instrument_memory(memory_instance, **kwargs)`.
Pass it any of the above instances and every method call that touches
storage will emit a typed audit event. Never breaks caller code -
identical silent-failure semantics as sdk_hooks.
"""
from __future__ import annotations

import functools
import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

from . import log as _audit_log
from .cost import estimate_cost as _estimate_cost
from .sdk_hooks import _resolve_tenant_id, _make_wrapper  # reuse


# Per-class-name: map method-name -> (event_type, source, key_extractor, value_extractor)
# key_extractor / value_extractor are lambdas that take (args, kwargs) and
# return the appropriate values for the audit row.
#
# We match on class NAME so we don't need to import the framework classes
# at module load time (keeps this module dependency-free).
CLASS_METHOD_MAP: Dict[str, Dict[str, Dict[str, Any]]] = {
    # ================================================================
    # CrewAI (SynrixCrewMemory)
    # ================================================================
    "SynrixCrewMemory": {
        "store_finding": {
            "event_type": "crew.finding",
            "source": "crewai",
            "key": lambda a, k: f"finding:{a[1] if len(a) > 1 else k.get('key', '')}",
            "value": lambda a, k: a[2] if len(a) > 2 else k.get("finding"),
            "extra": lambda a, k: {"agent_role": a[0] if a else k.get("agent_role")},
        },
        "get_finding": {
            "event_type": "crew.finding",
            "source": "crewai",
            "key": lambda a, k: f"finding:{a[0] if a else k.get('key', '')}",
            "value": lambda a, k: None,
            "extra": lambda a, k: {"read_only": True},
        },
        "get_all_findings": {
            "event_type": "crew.finding",
            "source": "crewai",
            "key": lambda a, k: "findings:*",
            "value": lambda a, k: None,
            "extra": lambda a, k: {"read_only": True, "scope": "all"},
        },
        "store_task_result": {
            "event_type": "crew.task",
            "source": "crewai",
            "key": lambda a, k: f"task:{a[0] if a else k.get('task_name', '')}",
            "value": lambda a, k: a[1] if len(a) > 1 else k.get("result"),
            "extra": lambda a, k: {"agent_role": a[2] if len(a) > 2 else k.get("agent_role")},
        },
    },

    # ================================================================
    # AutoGen (SynrixAutoGenMemory)
    # ================================================================
    "SynrixAutoGenMemory": {
        "store_message": {
            "event_type": "autogen.turn",
            "source": "autogen",
            "key": lambda a, k: f"msg:{a[0] if a else k.get('sender', '')}->{a[1] if len(a) > 1 else k.get('recipient', '')}",
            "value": lambda a, k: a[2] if len(a) > 2 else k.get("content"),
            "extra": lambda a, k: {
                "sender": a[0] if a else k.get("sender"),
                "recipient": a[1] if len(a) > 1 else k.get("recipient"),
            },
        },
        "get_conversation_history": {
            "event_type": "autogen.turn",
            "source": "autogen",
            "key": lambda a, k: "history:*",
            "value": lambda a, k: None,
            "extra": lambda a, k: {"read_only": True},
        },
    },

    # ================================================================
    # OpenAI Assistants (SynrixOpenAIMemory)
    # ================================================================
    "SynrixOpenAIMemory": {
        "store_thread_state": {
            "event_type": "thread.updated",
            "source": "openai",
            "key": lambda a, k: f"thread:{a[0] if a else k.get('thread_id', '')}",
            "value": lambda a, k: a[1] if len(a) > 1 else k.get("state"),
            "extra": lambda a, k: {},
        },
        "restore_thread": {
            "event_type": "thread.updated",
            "source": "openai",
            "key": lambda a, k: f"thread:{a[0] if a else k.get('thread_id', '')}",
            "value": lambda a, k: None,
            "extra": lambda a, k: {"read_only": True},
        },
        "store_run_result": {
            "event_type": "thread.updated",
            "source": "openai",
            "key": lambda a, k: f"run:{a[0] if a else k.get('run_id', '')}",
            "value": lambda a, k: a[1] if len(a) > 1 else k.get("result"),
            "extra": lambda a, k: {"kind": "run_result"},
        },
    },

    # ================================================================
    # LangChain (SynrixMemory - the Memory class, for ConversationChain)
    # ================================================================
    "SynrixMemory": {
        "save_context": {
            "event_type": "conversation.message",
            "source": "langchain",
            "key": lambda a, k: "turn",
            "value": lambda a, k: {
                "inputs": a[0] if a else k.get("inputs"),
                "outputs": a[1] if len(a) > 1 else k.get("outputs"),
            },
            "extra": lambda a, k: {},
        },
        "load_memory_variables": {
            "event_type": "conversation.message",
            "source": "langchain",
            "key": lambda a, k: "history",
            "value": lambda a, k: None,
            "extra": lambda a, k: {"read_only": True},
        },
        "clear": {
            "event_type": "memory.delete",
            "source": "langchain",
            "key": lambda a, k: "*",
            "value": lambda a, k: None,
            "extra": lambda a, k: {"scope": "session"},
        },
    },

    # ================================================================
    # LangChain (OctopodaChatHistory - for RunnableWithMessageHistory)
    # ================================================================
    "OctopodaChatHistory": {
        "add_message": {
            "event_type": "conversation.message",
            "source": "langchain",
            "key": lambda a, k: "message",
            "value": lambda a, k: _safe_repr_message(a[0] if a else k.get("message")),
            "extra": lambda a, k: {"kind": _message_kind(a[0] if a else k.get("message"))},
        },
        "clear": {
            "event_type": "memory.delete",
            "source": "langchain",
            "key": lambda a, k: "chat_history",
            "value": lambda a, k: None,
            "extra": lambda a, k: {"scope": "session"},
        },
    },
}


def _safe_repr_message(msg: Any) -> Any:
    """Extract content from a LangChain BaseMessage without importing LC."""
    if msg is None:
        return None
    for attr in ("content", "text"):
        val = getattr(msg, attr, None)
        if val is not None:
            return val
    return repr(msg)


def _message_kind(msg: Any) -> str:
    if msg is None:
        return "unknown"
    cls = type(msg).__name__
    return cls


def _get_agent_id_from_memory(memory: Any, kind: str) -> str:
    """Best-effort agent/crew/group/thread id extraction."""
    for attr in ("crew_id", "group_id", "agent_id", "session_id",
                 "thread_id"):
        val = getattr(memory, attr, None)
        if val:
            return str(val)
    return f"{kind}_default"


def _make_framework_wrapper(
    original: Callable,
    *,
    event_type: str,
    source: str,
    agent_id: str,
    tenant_id: str,
    key_fn: Callable,
    value_fn: Callable,
    extra_fn: Callable,
) -> Callable:
    """Wrapper tuned for framework classes. Same safety semantics as sdk_hooks."""

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        start = time.perf_counter()
        outcome = "success"
        error_message = None
        try:
            result = original(*args, **kwargs)
            return result
        except Exception as e:
            outcome = "fail"
            error_message = f"{type(e).__name__}: {e}"
            raise
        finally:
            try:
                latency_ms = int((time.perf_counter() - start) * 1000)
                # For framework methods args[0] is sometimes `self`-shaped
                # but since we're wrapping bound methods, `self` is already
                # consumed. args here is the caller-visible args.
                key = None
                value = None
                extra: Dict[str, Any] = {}
                try:
                    key = key_fn(args, kwargs)
                except Exception:
                    pass
                try:
                    value = value_fn(args, kwargs)
                except Exception:
                    pass
                try:
                    extra = extra_fn(args, kwargs) or {}
                except Exception:
                    pass

                cost_usd = _estimate_cost(tenant_id, event_type)
                _audit_log(
                    tenant_id=tenant_id,
                    event_type=event_type,
                    agent_id=agent_id,
                    source=source,
                    key=key,
                    value=value,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    outcome=outcome,
                    error_message=error_message,
                    extra=extra,
                )
            except Exception:
                pass  # audit must not break caller

    wrapped.__audit_v2_wrapped__ = True  # type: ignore[attr-defined]
    return wrapped


def instrument_memory(memory: Any, *, tenant_id: Optional[str] = None,
                      agent_id: Optional[str] = None) -> Any:
    """Attach audit hooks to a framework memory instance.

    Detects the class automatically. Returns the same memory instance.
    Idempotent.
    """
    cls_name = type(memory).__name__
    rules = CLASS_METHOD_MAP.get(cls_name)
    if not rules:
        return memory  # not a class we know how to instrument

    resolved_tid = _resolve_tenant_id(memory, tenant_id)
    if not resolved_tid:
        return memory

    # Pick a reasonable agent id
    kind_for_default = {
        "SynrixCrewMemory": "crew",
        "SynrixAutoGenMemory": "group",
        "SynrixOpenAIMemory": "openai",
        "SynrixMemory": "langchain",
        "OctopodaChatHistory": "langchain",
    }.get(cls_name, "memory")
    resolved_aid = agent_id or _get_agent_id_from_memory(memory, kind_for_default)

    for method_name, rule in rules.items():
        original = getattr(memory, method_name, None)
        if original is None:
            continue
        if getattr(original, "__audit_v2_wrapped__", False):
            continue
        wrapped = _make_framework_wrapper(
            original,
            event_type=rule["event_type"],
            source=rule["source"],
            agent_id=resolved_aid,
            tenant_id=resolved_tid,
            key_fn=rule["key"],
            value_fn=rule["value"],
            extra_fn=rule["extra"],
        )
        setattr(memory, method_name, wrapped)

    memory._audit_v2_instrumented = True  # type: ignore[attr-defined]
    memory._audit_v2_tenant_id = resolved_tid  # type: ignore[attr-defined]
    memory._audit_v2_agent_id = resolved_aid  # type: ignore[attr-defined]
    return memory
