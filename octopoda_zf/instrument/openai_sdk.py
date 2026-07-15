"""OpenAI SDK hook.

Wraps `openai.resources.chat.completions.Completions.create` (and the async
variant) so that, for every chat completion an agent makes:
  1. recall: relevant memories are injected as a system message BEFORE the call
  2. capture: the messages + response are handed to the extraction pipeline AFTER

The wrapper LOGIC is separated from the PATCHING so it can be unit-tested with a
fake SDK (no `openai` install, no network).

Two call shapes are handled distinctly (closing bug-check #2's gaps):
  - **streaming** (`stream=True`): the response is a `Stream` we can't read as a
    response object, so we TEE it (see `.stream`) — every chunk is forwarded to
    the user unchanged while we accumulate the assistant's text, captured once the
    stream ends. Without this, streamed responses recall fine but never WRITE.
  - **async** (`AsyncCompletions`): a dedicated `async` wrapper awaits recall off
    the event loop (in a thread) instead of blocking it ~110ms/call, and tees the
    `AsyncStream` for streamed async calls.

Fail-soft contract: if recall, injection, or capture raises, the user's original
LLM call still completes unchanged. We never worsen their request.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .base import apply_patch, is_reentrant, run_in_thread
from .stream import AsyncStreamProxy, SyncStreamProxy

logger = logging.getLogger("octopoda.instrument.openai")

# Callback types:
#   RecallFn(query: str) -> injection_text | None
#   CaptureFn(messages: list[dict], response: Any) -> None   (should be async/queued)
RecallFn = Callable[[str], "str | None"]
CaptureFn = Callable[[list, Any], None]


def _message_text(content: Any) -> str:
    """Extract plain text from an OpenAI message `content`, which may be a
    string or a list of content parts (multimodal). Images are skipped."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts)
    return ""


def last_user_text(messages: list[dict]) -> str:
    """Return the text of the most recent user message, or ''."""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return _message_text(msg.get("content"))
    return ""


def inject_system_message(messages: list[dict], injection: str) -> list[dict]:
    """Return a NEW messages list with the injection inserted as a system
    message, placed AFTER any leading system messages (so the user's primary
    system prompt keeps instruction priority). Never mutates the input."""
    new = list(messages)
    insert_at = 0
    for i, msg in enumerate(new):
        if isinstance(msg, dict) and msg.get("role") == "system":
            insert_at = i + 1
        else:
            break
    new.insert(insert_at, {"role": "system", "content": injection})
    return new


class _MaterializedText:
    """Minimal object shaped like a ChatCompletion so `openai_response_to_text`
    (which reads `.choices[0].message.content`) can read the text we accumulated
    from a stream — without us having to special-case capture for streaming."""

    def __init__(self, text: str) -> None:
        message = type("_Msg", (), {"content": text})()
        choice = type("_Choice", (), {"message": message})()
        self.choices = [choice]


def _chunk_delta_text(chunk: Any) -> str:
    """Text delta carried by one streamed ChatCompletionChunk ('' if none, e.g. a
    role-only first chunk, a tool-call chunk, or the usage-only final chunk)."""
    try:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        return getattr(delta, "content", None) or ""
    except Exception:
        return ""


def _capture_streamed(cap_messages: list, capture_fn: CaptureFn) -> Callable[[str], None]:
    """Build the on-complete callback the tee fires with the assembled text."""
    return lambda text: capture_fn(cap_messages, _MaterializedText(text))


def make_create_wrapper(
    original: Callable,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> Callable:
    """Build the wrapped SYNC `create`. Pure factory — testable in isolation."""

    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        # Re-entrancy: a call originating from octopoda's own machinery (the
        # extractor's LLM call) must NOT be recalled/captured, or we recurse
        # forever. Pass straight through to the real method.
        if is_reentrant():
            return original(self, *args, **kwargs)

        messages = kwargs.get("messages")

        # --- recall + inject (fail-soft) ---
        if messages and recall_fn:
            try:
                query = last_user_text(messages)
                if query:
                    injection = recall_fn(query)
                    if injection:
                        kwargs["messages"] = inject_system_message(messages, injection)
            except Exception as e:  # never break the user's call
                logger.warning("recall injection failed, proceeding without: %s", e)

        # --- the real call (always happens) ---
        response = original(self, *args, **kwargs)

        # --- capture for extraction (fail-soft, should be queued/async) ---
        if capture_fn:
            cap_messages = kwargs.get("messages", messages) or []
            # Streaming: tee so the ASSISTANT's streamed text is captured too (not
            # just the user message). Only when the response is actually iterable.
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


def make_async_create_wrapper(
    original: Callable,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> Callable:
    """Build the wrapped ASYNC `create` (for `AsyncCompletions`).

    Differs from the sync wrapper in two ways that matter on the event loop:
      - recall is awaited OFF the loop (thread executor) so the ~110ms cloud round
        trip doesn't stall the caller;
      - the awaited response is teed via `AsyncStreamProxy` when streaming.
    Capture stays a non-blocking enqueue (the worker drains it on its own thread)."""

    async def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        if is_reentrant():  # octopoda-internal call (extractor) — pass through
            return await original(self, *args, **kwargs)

        messages = kwargs.get("messages")

        if messages and recall_fn:
            try:
                query = last_user_text(messages)
                if query:
                    injection = await run_in_thread(recall_fn, query)
                    if injection:
                        kwargs["messages"] = inject_system_message(messages, injection)
            except Exception as e:
                logger.warning("recall injection failed, proceeding without: %s", e)

        response = await original(self, *args, **kwargs)

        if capture_fn:
            cap_messages = kwargs.get("messages", messages) or []
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


def patch_completions(
    completions_class: Any,
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
    *,
    attr: str = "create",
    label: str = "openai.Completions.create",
    is_async: bool = False,
):
    """Apply the wrapper to a Completions class's `create` method.

    `completions_class` is passed in (not imported) so tests can supply a fake.
    In production, `octopoda.init()` resolves
    `openai.resources.chat.completions.Completions`. `is_async` selects the
    coroutine wrapper (for `AsyncCompletions`)."""
    factory = make_async_create_wrapper if is_async else make_create_wrapper
    return apply_patch(
        completions_class,
        attr,
        lambda original: factory(original, recall_fn, capture_fn),
        label=label,
    )


def resolve_and_patch(
    recall_fn: RecallFn | None,
    capture_fn: CaptureFn | None,
) -> list:
    """Resolve the real OpenAI SDK classes and patch them. Returns the list of
    PatchHandles applied (empty if openai not importable).

    Patches both sync (`Completions`) and async (`AsyncCompletions`) `create`,
    each with the matching wrapper. Import-guarded so the package never
    hard-depends on `openai`.
    """
    handles = []
    try:
        from openai.resources.chat.completions import (  # type: ignore
            AsyncCompletions,
            Completions,
        )
    except ImportError:
        logger.debug("openai SDK not importable; skipping OpenAI hook")
        return handles

    h1 = patch_completions(Completions, recall_fn, capture_fn, label="openai.Completions.create")
    if h1:
        handles.append(h1)
    h2 = patch_completions(
        AsyncCompletions, recall_fn, capture_fn,
        label="openai.AsyncCompletions.create", is_async=True,
    )
    if h2:
        handles.append(h2)
    return handles
