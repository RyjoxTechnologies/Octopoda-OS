"""Anthropic SDK hook.

Wraps `anthropic.resources.messages.Messages.create` (+ async variant).

Key difference from OpenAI: Anthropic takes the system prompt as a SEPARATE
`system` parameter, not as a message with role=system. So recall injection
appends to the `system` kwarg rather than inserting into `messages`.

Streaming + async are handled the same way as the OpenAI hook (bug-check #2):
streamed `create(stream=True)` returns a `Stream` of events that we TEE (forward
every event unchanged while accumulating the assistant text, capture at the end),
and `AsyncMessages` gets a dedicated async wrapper that awaits recall off the
event loop and tees the `AsyncStream`.

Same fail-soft contract: recall/injection/capture errors never break the call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .base import apply_patch, is_reentrant, run_in_thread
from .openai_sdk import last_user_text  # message text extraction is identical
from .stream import AsyncStreamProxy, SyncStreamProxy

logger = logging.getLogger("octopoda.instrument.anthropic")

RecallFn = Callable[[str], "str | None"]
CaptureFn = Callable[[list, Any], None]


def inject_into_system_param(kwargs: dict, injection: str) -> None:
    """Append the injection to Anthropic's `system` kwarg, in place.

    Anthropic's `system` may be:
    - absent
    - a string
    - a list of content blocks ([{"type":"text","text":...}, ...])
    We handle all three, always appending (never overwriting the user's prompt).
    """
    existing = kwargs.get("system")
    if existing is None:
        kwargs["system"] = injection
    elif isinstance(existing, str):
        kwargs["system"] = f"{existing}\n\n{injection}"
    elif isinstance(existing, list):
        # append a text block; copy to avoid mutating the caller's list
        new_blocks = list(existing)
        new_blocks.append({"type": "text", "text": injection})
        kwargs["system"] = new_blocks
    else:
        # unknown shape — be safe, don't touch it
        logger.debug("unexpected system param type %s; skipping injection", type(existing))


class _MaterializedText:
    """Minimal object shaped like an Anthropic Message so `anthropic_response_to_text`
    (which iterates `.content` text blocks) can read the text we accumulated from a
    stream — without special-casing capture for streaming."""

    def __init__(self, text: str) -> None:
        block = type("_Block", (), {"type": "text", "text": text})()
        self.content = [block]


def _attr(obj: Any, name: str) -> Any:
    """Attr-or-key access: Anthropic events are pydantic objects, but stay robust
    to dict-shaped events (some SDK paths / test fakes)."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _chunk_delta_text(event: Any) -> str:
    """Text delta carried by one streamed Anthropic event ('' for the message/
    block start+stop events, ping events, tool-input deltas, etc.). Only
    `content_block_delta` events with a `text_delta` carry assistant text."""
    try:
        if _attr(event, "type") != "content_block_delta":
            return ""
        delta = _attr(event, "delta")
        if _attr(delta, "type") != "text_delta":
            return ""
        return _attr(delta, "text") or ""
    except Exception:
        return ""


def _capture_streamed(cap_messages: list, capture_fn: CaptureFn) -> Callable[[str], None]:
    """Build the on-complete callback the tee fires with the assembled text."""
    return lambda text: capture_fn(cap_messages, _MaterializedText(text))


def make_messages_wrapper(
    original: Callable,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> Callable:
    """Build the wrapped SYNC `messages.create`. Pure factory — testable in isolation."""

    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        if is_reentrant():  # octopoda-internal call (extractor) — pass through
            return original(self, *args, **kwargs)
        messages = kwargs.get("messages")

        if messages and recall_fn:
            try:
                query = last_user_text(messages)
                if query:
                    injection = recall_fn(query)
                    if injection:
                        inject_into_system_param(kwargs, injection)
            except Exception as e:
                logger.warning("recall injection failed, proceeding without: %s", e)

        response = original(self, *args, **kwargs)

        if capture_fn:
            cap_messages = messages or []
            if kwargs.get("stream") and hasattr(response, "__iter__"):
                try:
                    return SyncStreamProxy(
                        response, _chunk_delta_text, _capture_streamed(cap_messages, capture_fn)
                    )
                except Exception as e:  # never break the user's stream
                    logger.warning("stream tee setup failed, returning raw stream: %s", e)
                    return response
            try:
                capture_fn(cap_messages, response)
            except Exception as e:
                logger.warning("capture failed (memory not written this turn): %s", e)

        return response

    return wrapper


def make_async_messages_wrapper(
    original: Callable,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> Callable:
    """Build the wrapped ASYNC `messages.create` (for `AsyncMessages`): awaits
    recall off the event loop and tees the `AsyncStream` when streaming."""

    async def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        if is_reentrant():
            return await original(self, *args, **kwargs)
        messages = kwargs.get("messages")

        if messages and recall_fn:
            try:
                query = last_user_text(messages)
                if query:
                    injection = await run_in_thread(recall_fn, query)
                    if injection:
                        inject_into_system_param(kwargs, injection)
            except Exception as e:
                logger.warning("recall injection failed, proceeding without: %s", e)

        response = await original(self, *args, **kwargs)

        if capture_fn:
            cap_messages = messages or []
            if kwargs.get("stream") and hasattr(response, "__aiter__"):
                try:
                    return AsyncStreamProxy(
                        response, _chunk_delta_text, _capture_streamed(cap_messages, capture_fn)
                    )
                except Exception as e:
                    logger.warning("stream tee setup failed, returning raw stream: %s", e)
                    return response
            try:
                capture_fn(cap_messages, response)
            except Exception as e:
                logger.warning("capture failed (memory not written this turn): %s", e)

        return response

    return wrapper


def patch_messages(
    messages_class: Any,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
    *,
    attr: str = "create",
    label: str = "anthropic.Messages.create",
    is_async: bool = False,
):
    """Apply the wrapper to a Messages class's `create`. Class passed in so tests
    can supply a fake. `is_async` selects the coroutine wrapper (`AsyncMessages`)."""
    factory = make_async_messages_wrapper if is_async else make_messages_wrapper
    return apply_patch(
        messages_class,
        attr,
        lambda original: factory(original, recall_fn, capture_fn),
        label=label,
    )


def resolve_and_patch(
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> list:
    """Resolve the real Anthropic SDK classes and patch them. Import-guarded."""
    handles = []
    try:
        from anthropic.resources.messages import (  # type: ignore
            AsyncMessages,
            Messages,
        )
    except ImportError:
        logger.debug("anthropic SDK not importable; skipping Anthropic hook")
        return handles

    h1 = patch_messages(Messages, recall_fn, capture_fn, label="anthropic.Messages.create")
    if h1:
        handles.append(h1)
    h2 = patch_messages(
        AsyncMessages, recall_fn, capture_fn,
        label="anthropic.AsyncMessages.create", is_async=True,
    )
    if h2:
        handles.append(h2)
    return handles
