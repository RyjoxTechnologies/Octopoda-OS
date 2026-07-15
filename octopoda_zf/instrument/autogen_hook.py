"""AutoGen hook (capture-only, async-stream).

AutoGen group chats expose `BaseGroupChat.run_stream(...)`, an async generator
of events. We tee that stream: yield every event unchanged to the user while
capturing the text of message events. After the stream ends, the captured
transcript is written.

This is the trickiest hook because it wraps an async generator. The wrapper must
preserve streaming semantics exactly (same events, same order, real-time) while
observing them.

Fail-soft: capture errors never interrupt the user's stream.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .base import apply_patch

logger = logging.getLogger("octopoda.instrument.autogen")

SubmitTranscriptFn = Callable[[str, str], None]
AgentIdFn = Callable[[], str]


def autogen_event_text(event: Any) -> str:
    """Extract 'source: content' from a message event, or '' for non-message
    events (TaskResult, ToolCallEvent, etc.). Mirrors the hasattr filtering the
    existing AutoGen docs recommend."""
    source = getattr(event, "source", None)
    content = getattr(event, "content", None)
    if source and isinstance(content, str) and content.strip():
        return f"{source}: {content.strip()}"
    return ""


async def _tee_stream(stream, submit_transcript: SubmitTranscriptFn, agent_id_fn: AgentIdFn):
    """Yield every event from `stream` unchanged; capture message text; on
    completion, submit the assembled transcript."""
    buffer: list[str] = []
    try:
        async for event in stream:
            try:
                text = autogen_event_text(event)
                if text:
                    buffer.append(text)
            except Exception:  # capture must never disrupt the stream
                pass
            yield event
    finally:
        if buffer:
            try:
                submit_transcript(agent_id_fn(), "\n".join(buffer))
            except Exception as e:
                logger.warning("autogen capture failed: %s", e)


def make_run_stream_wrapper(
    original: Callable,
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> Callable:
    """Wrap run_stream. The wrapper is a plain function returning a tee'd async
    generator (preserves `async for` semantics)."""

    def wrapper(self, *args: Any, **kwargs: Any):
        stream = original(self, *args, **kwargs)
        return _tee_stream(stream, submit_transcript, agent_id_fn)

    return wrapper


def install_capture(
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> list:
    """Resolve AutoGen's BaseGroupChat and wrap run_stream. Import-guarded."""
    handles = []
    base_group_chat = None
    for path in (
        "autogen_agentchat.teams",
        "autogen_agentchat.teams._base_group_chat",
    ):
        try:
            mod = __import__(path, fromlist=["BaseGroupChat"])
            base_group_chat = getattr(mod, "BaseGroupChat", None)
            if base_group_chat is not None:
                break
        except ImportError:
            continue
    if base_group_chat is None:
        logger.debug("autogen_agentchat BaseGroupChat not found; skipping AutoGen hook")
        return handles

    h = apply_patch(
        base_group_chat,
        "run_stream",
        lambda original: make_run_stream_wrapper(original, submit_transcript, agent_id_fn),
        label="autogen.BaseGroupChat.run_stream",
    )
    if h:
        handles.append(h)
    return handles
