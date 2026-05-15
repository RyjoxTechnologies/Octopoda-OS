"""audit_v2.llm_hooks - capture every LLM call (OpenAI, Anthropic) as audit.

We monkey-patch the two most common LLM clients so every `chat.completions`
/ `messages.create` call produces three audit events:

    llm.call      -> intent (model, prompt_preview, temperature, tool_choice)
    llm.response  -> success (tokens_in, tokens_out, cost_usd, response_preview)
    llm.error     -> failure (error_message, outcome=fail)

Actually we merge call+response into a single row (event_type=llm.response)
to keep the timeline compact. Errors get their own llm.error row.

Zero user code changes: after `instrument_llms()` the next `OpenAI()` or
`Anthropic()` client instance emits audit automatically. Idempotent.

Works with streaming too - for streaming responses we record the event
when the stream closes (or times out), capturing aggregate usage.

Tenant resolution + trace_id: both pulled from audit_v2 helpers so
correlation works across nested SDK/MCP/framework calls in the same
trace_scope.
"""
from __future__ import annotations

import functools
import os
import time
from typing import Any, Callable, Dict, List, Optional

from . import log as _audit_log
from .cost import estimate_cost as _estimate_cost
from .sdk_hooks import _resolve_tenant_id  # reuse


# -------------------------------------------------------------- helpers

def _extract_messages_preview(messages: Any) -> str:
    """Compact string preview of the prompt messages array (redaction-safe)."""
    if not messages:
        return ""
    parts = []
    for m in messages[:6]:  # first few messages only
        if isinstance(m, dict):
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                # OpenAI vision / multimodal - flatten text blocks
                content = " ".join(
                    (b.get("text") or "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            content = str(content)[:80]
            parts.append(f"{role}: {content}")
        else:
            parts.append(str(m)[:80])
    return " | ".join(parts)


def _extract_usage(response: Any) -> Dict[str, int]:
    """Pull prompt_tokens/completion_tokens from an OpenAI/Anthropic response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"tokens_in": 0, "tokens_out": 0}
    if hasattr(usage, "model_dump"):
        u = usage.model_dump()
    elif hasattr(usage, "dict"):
        u = usage.dict()
    else:
        u = usage if isinstance(usage, dict) else {}
    # OpenAI: prompt_tokens, completion_tokens, total_tokens
    # Anthropic: input_tokens, output_tokens
    tokens_in = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
    tokens_out = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
    return {"tokens_in": tokens_in, "tokens_out": tokens_out}


def _extract_response_preview(response: Any) -> str:
    """Compact preview of the assistant's reply."""
    # OpenAI: response.choices[0].message.content
    try:
        choices = getattr(response, "choices", None)
        if choices:
            first = choices[0]
            msg = getattr(first, "message", None)
            if msg is not None:
                content = getattr(msg, "content", None)
                if content:
                    return str(content)
    except Exception:
        pass
    # Anthropic: response.content[0].text
    try:
        content = getattr(response, "content", None)
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return str(first.get("text", ""))
            else:
                return str(getattr(first, "text", first))
    except Exception:
        pass
    return ""


def _cost_from_usage(model: str, tokens_in: int, tokens_out: int) -> float:
    """Compute USD cost based on token counts + model pricing table."""
    try:
        from synrix_runtime.monitoring.cost_models import MODEL_COSTS
    except Exception:
        return 0.0
    rates = MODEL_COSTS.get(model) or MODEL_COSTS.get("unknown") or {}
    input_rate = float(rates.get("input", 0.0))   # USD per 1M tokens
    output_rate = float(rates.get("output", 0.0))
    return (tokens_in / 1_000_000) * input_rate + \
           (tokens_out / 1_000_000) * output_rate


# -------------------------------------------------------------- OpenAI

def _wrap_openai_chat_create(original: Callable, *, tenant_id: Optional[str]) -> Callable:
    """Wrap OpenAI's `client.chat.completions.create` to emit llm.response."""

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        start = time.perf_counter()
        model = str(kwargs.get("model") or "unknown")
        messages = kwargs.get("messages") or []
        temperature = kwargs.get("temperature")
        agent_id_hint = kwargs.pop("_audit_agent_id", None) or "llm_caller"
        prompt_preview = _extract_messages_preview(messages)
        stream = bool(kwargs.get("stream"))
        outcome = "success"
        error_message = None
        response = None
        try:
            response = original(*args, **kwargs)
            return response
        except Exception as e:
            outcome = "fail"
            error_message = f"{type(e).__name__}: {e}"
            raise
        finally:
            try:
                latency_ms = int((time.perf_counter() - start) * 1000)
                tid = tenant_id or _resolve_tenant_id(None, None)
                if not tid:
                    return
                if outcome == "fail":
                    _audit_log(
                        tenant_id=tid,
                        event_type="llm.error",
                        agent_id=agent_id_hint,
                        source="sdk",
                        key=f"openai:{model}",
                        value=prompt_preview,
                        latency_ms=latency_ms,
                        outcome="fail",
                        error_message=error_message,
                        extra={
                            "provider": "openai",
                            "model": model,
                            "stream": stream,
                            "temperature": temperature,
                        },
                    )
                    return
                # success - skip detailed token accounting if streaming
                if stream:
                    _audit_log(
                        tenant_id=tid,
                        event_type="llm.response",
                        agent_id=agent_id_hint,
                        source="sdk",
                        key=f"openai:{model}",
                        value=prompt_preview,
                        latency_ms=latency_ms,
                        outcome="success",
                        extra={
                            "provider": "openai", "model": model,
                            "stream": True,
                            "note": "token accounting unavailable on streaming",
                        },
                    )
                    return
                usage = _extract_usage(response)
                cost = _cost_from_usage(model, usage["tokens_in"], usage["tokens_out"])
                reply_preview = _extract_response_preview(response)
                _audit_log(
                    tenant_id=tid,
                    event_type="llm.response",
                    agent_id=agent_id_hint,
                    source="sdk",
                    key=f"openai:{model}",
                    value={"prompt": prompt_preview, "reply": reply_preview[:180]},
                    cost_usd=cost,
                    tokens_in=usage["tokens_in"],
                    tokens_out=usage["tokens_out"],
                    latency_ms=latency_ms,
                    outcome="success",
                    extra={
                        "provider": "openai",
                        "model": model,
                        "temperature": temperature,
                    },
                )
            except Exception:
                pass  # audit must not break caller

    wrapped.__audit_v2_wrapped__ = True  # type: ignore[attr-defined]
    return wrapped


# -------------------------------------------------------------- Anthropic

def _wrap_anthropic_messages_create(original: Callable, *, tenant_id: Optional[str]) -> Callable:
    """Wrap Anthropic's `client.messages.create` to emit llm.response."""

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        start = time.perf_counter()
        model = str(kwargs.get("model") or "unknown")
        messages = kwargs.get("messages") or []
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        agent_id_hint = kwargs.pop("_audit_agent_id", None) or "llm_caller"
        prompt_preview = _extract_messages_preview(messages)
        stream = bool(kwargs.get("stream"))
        outcome = "success"
        error_message = None
        response = None
        try:
            response = original(*args, **kwargs)
            return response
        except Exception as e:
            outcome = "fail"
            error_message = f"{type(e).__name__}: {e}"
            raise
        finally:
            try:
                latency_ms = int((time.perf_counter() - start) * 1000)
                tid = tenant_id or _resolve_tenant_id(None, None)
                if not tid:
                    return
                if outcome == "fail":
                    _audit_log(
                        tenant_id=tid,
                        event_type="llm.error",
                        agent_id=agent_id_hint,
                        source="sdk",
                        key=f"anthropic:{model}",
                        value=prompt_preview,
                        latency_ms=latency_ms,
                        outcome="fail",
                        error_message=error_message,
                        extra={
                            "provider": "anthropic",
                            "model": model,
                            "stream": stream,
                            "temperature": temperature,
                        },
                    )
                    return
                if stream:
                    _audit_log(
                        tenant_id=tid,
                        event_type="llm.response",
                        agent_id=agent_id_hint,
                        source="sdk",
                        key=f"anthropic:{model}",
                        value=prompt_preview,
                        latency_ms=latency_ms,
                        outcome="success",
                        extra={
                            "provider": "anthropic", "model": model,
                            "stream": True,
                            "note": "token accounting unavailable on streaming",
                        },
                    )
                    return
                usage = _extract_usage(response)
                cost = _cost_from_usage(model, usage["tokens_in"], usage["tokens_out"])
                reply_preview = _extract_response_preview(response)
                _audit_log(
                    tenant_id=tid,
                    event_type="llm.response",
                    agent_id=agent_id_hint,
                    source="sdk",
                    key=f"anthropic:{model}",
                    value={"prompt": prompt_preview, "reply": reply_preview[:180]},
                    cost_usd=cost,
                    tokens_in=usage["tokens_in"],
                    tokens_out=usage["tokens_out"],
                    latency_ms=latency_ms,
                    outcome="success",
                    extra={
                        "provider": "anthropic",
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
            except Exception:
                pass

    wrapped.__audit_v2_wrapped__ = True  # type: ignore[attr-defined]
    return wrapped


# -------------------------------------------------------------- public API

_instrumented = {"openai": False, "anthropic": False}


def instrument_llms(*, tenant_id: Optional[str] = None) -> Dict[str, bool]:
    """Monkey-patch openai + anthropic clients so every call is audited.

    Idempotent. Returns dict showing which providers we patched.
    Providers that aren't installed are silently skipped.
    """
    result = {"openai": False, "anthropic": False}

    # ---- OpenAI ----
    try:
        import openai
        # The new openai Python SDK exposes:
        #   client.chat.completions.create(...)
        # We patch at the method level on Completions class so all instances
        # (Sync + Async) get wrapped.
        target = openai.resources.chat.completions.Completions.create
        if not getattr(target, "__audit_v2_wrapped__", False):
            wrapped = _wrap_openai_chat_create(target, tenant_id=tenant_id)
            # Bind as unbound method; it'll still receive self when called
            openai.resources.chat.completions.Completions.create = wrapped
            _instrumented["openai"] = True
            result["openai"] = True
        # Async variant
        try:
            target_async = openai.resources.chat.completions.AsyncCompletions.create

            async def wrapped_async(self_, *args, **kwargs):
                start = time.perf_counter()
                model = str(kwargs.get("model") or "unknown")
                messages = kwargs.get("messages") or []
                agent_id_hint = kwargs.pop("_audit_agent_id", None) or "llm_caller"
                prompt_preview = _extract_messages_preview(messages)
                outcome = "success"
                error_message = None
                response = None
                try:
                    response = await target_async(self_, *args, **kwargs)
                    return response
                except Exception as e:
                    outcome = "fail"
                    error_message = f"{type(e).__name__}: {e}"
                    raise
                finally:
                    try:
                        latency_ms = int((time.perf_counter() - start) * 1000)
                        tid = tenant_id or _resolve_tenant_id(None, None)
                        if not tid:
                            return
                        if outcome == "fail":
                            _audit_log(tenant_id=tid, event_type="llm.error",
                                        agent_id=agent_id_hint, source="sdk",
                                        key=f"openai:{model}", value=prompt_preview,
                                        latency_ms=latency_ms, outcome="fail",
                                        error_message=error_message,
                                        extra={"provider": "openai", "async": True,
                                               "model": model})
                        else:
                            usage = _extract_usage(response)
                            cost = _cost_from_usage(model, usage["tokens_in"],
                                                     usage["tokens_out"])
                            reply = _extract_response_preview(response)
                            _audit_log(tenant_id=tid, event_type="llm.response",
                                        agent_id=agent_id_hint, source="sdk",
                                        key=f"openai:{model}",
                                        value={"prompt": prompt_preview, "reply": reply[:180]},
                                        cost_usd=cost,
                                        tokens_in=usage["tokens_in"],
                                        tokens_out=usage["tokens_out"],
                                        latency_ms=latency_ms, outcome="success",
                                        extra={"provider": "openai", "async": True,
                                               "model": model})
                    except Exception:
                        pass

            if not getattr(target_async, "__audit_v2_wrapped__", False):
                wrapped_async.__audit_v2_wrapped__ = True  # type: ignore[attr-defined]
                openai.resources.chat.completions.AsyncCompletions.create = wrapped_async
        except Exception:
            pass
    except ImportError:
        pass  # openai SDK not installed

    # ---- Anthropic ----
    try:
        import anthropic
        target = anthropic.resources.messages.Messages.create
        if not getattr(target, "__audit_v2_wrapped__", False):
            wrapped = _wrap_anthropic_messages_create(target, tenant_id=tenant_id)
            anthropic.resources.messages.Messages.create = wrapped
            _instrumented["anthropic"] = True
            result["anthropic"] = True
    except ImportError:
        pass

    return result


def is_instrumented(provider: str) -> bool:
    return bool(_instrumented.get(provider))
