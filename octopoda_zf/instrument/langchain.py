"""LangChain hook.

Wraps `langchain_core.language_models.chat_models.BaseChatModel.invoke`
(and `ainvoke`). Because most LangChain chat models implement `_generate` and
inherit `invoke` from the base, patching the base intercepts ChatOpenAI,
ChatAnthropic, ChatOllama, etc. in one shot.

LangChain's `invoke` input is polymorphic: a string, a list of message objects /
(role, content) tuples / dicts, or a PromptValue. We handle all of them without
importing LangChain types (decoupled): recall injection uses a `("system", ...)`
tuple, which LangChain's message coercion accepts.

Fail-soft contract identical to the other hooks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .base import apply_patch, is_reentrant

logger = logging.getLogger("octopoda.instrument.langchain")

RecallFn = Callable[[str], "str | None"]
CaptureFn = Callable[[Any, Any], None]

_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _normalize_role(role: str) -> str:
    return _ROLE_MAP.get(role, role)


def _msg_role(m: Any) -> str:
    if isinstance(m, dict):
        return _normalize_role(m.get("role") or m.get("type") or "user")
    if isinstance(m, (tuple, list)) and len(m) == 2:
        return _normalize_role(str(m[0]))
    t = getattr(m, "type", None)  # LangChain BaseMessage.type
    return _normalize_role(t) if t else "user"


def _msg_content(m: Any) -> str:
    if isinstance(m, dict):
        content = m.get("content", "")
    elif isinstance(m, (tuple, list)) and len(m) == 2:
        content = m[1]
    else:
        content = getattr(m, "content", "") or ""
    if isinstance(content, list):
        # multimodal content blocks
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return " ".join(p for p in parts if p)
    return content if isinstance(content, str) else str(content)


def langchain_input_to_dicts(input_: Any) -> list[dict]:
    """Normalize any LangChain invoke input into [{role, content}, ...]."""
    if isinstance(input_, str):
        return [{"role": "user", "content": input_}]
    if isinstance(input_, (list, tuple)):
        out = []
        for m in input_:
            out.append({"role": _msg_role(m), "content": _msg_content(m)})
        return out
    # PromptValue
    if hasattr(input_, "to_messages"):
        try:
            return langchain_input_to_dicts(list(input_.to_messages()))
        except Exception:
            pass
    if hasattr(input_, "to_string"):
        try:
            return [{"role": "user", "content": input_.to_string()}]
        except Exception:
            pass
    return []


def langchain_response_to_text(response: Any) -> str:
    """Extract text from an invoke() result (an AIMessage or string)."""
    if isinstance(response, str):
        return response
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return " ".join(p for p in parts if p)
    return str(content) if content else ""


def extract_query(input_: Any) -> str:
    """Last user message text from any input shape."""
    for m in reversed(langchain_input_to_dicts(input_)):
        if m["role"] == "user":
            return m["content"]
    return ""


def inject_into_input(input_: Any, injection: str) -> Any:
    """Return a new input with the injection added.

    - str  -> prepend injection as context
    - list -> insert ("system", injection) after leading system messages
    - other (PromptValue) -> unchanged (cannot safely inject)
    """
    if isinstance(input_, str):
        return f"{injection}\n\n{input_}"
    if isinstance(input_, (list, tuple)):
        new = list(input_)
        insert_at = 0
        for i, m in enumerate(new):
            if _msg_role(m) == "system":
                insert_at = i + 1
            else:
                break
        new.insert(insert_at, ("system", injection))
        return new
    return input_


def make_invoke_wrapper(
    original: Callable,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> Callable:
    """Build the wrapped `invoke`. Pure factory — testable with a fake model."""

    def wrapper(self, input_, *args: Any, **kwargs: Any) -> Any:
        if is_reentrant():  # octopoda-internal call (extractor) — pass through
            return original(self, input_, *args, **kwargs)
        call_input = input_
        if recall_fn:
            try:
                query = extract_query(input_)
                if query:
                    injection = recall_fn(query)
                    if injection:
                        call_input = inject_into_input(input_, injection)
            except Exception as e:
                logger.warning("recall injection failed, proceeding without: %s", e)

        response = original(self, call_input, *args, **kwargs)

        if capture_fn:
            try:
                # capture the ORIGINAL input (not the injected one) + response
                capture_fn(input_, response)
            except Exception as e:
                logger.warning("capture failed (memory not written this turn): %s", e)

        return response

    return wrapper


def patch_chat_model(
    base_chat_model_class: Any,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
    *,
    attr: str = "invoke",
    label: str = "langchain.BaseChatModel.invoke",
):
    return apply_patch(
        base_chat_model_class,
        attr,
        lambda original: make_invoke_wrapper(original, recall_fn, capture_fn),
        label=label,
    )


def resolve_and_patch(
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> list:
    """Resolve the real LangChain BaseChatModel and patch invoke. Import-guarded."""
    handles = []
    try:
        from langchain_core.language_models.chat_models import (  # type: ignore
            BaseChatModel,
        )
    except ImportError:
        logger.debug("langchain_core not importable; skipping LangChain hook")
        return handles

    h = patch_chat_model(BaseChatModel, recall_fn, capture_fn, attr="invoke")
    if h:
        handles.append(h)
    return handles
