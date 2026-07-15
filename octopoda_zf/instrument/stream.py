"""Stream tee for the message-based SDK hooks (OpenAI, Anthropic).

A streamed `create(stream=True)` returns an iterator (sync `Stream`) or async
iterator (`AsyncStream`) of chunks instead of a full response object. The capture
pipeline can't read a stream, so without tee-ing, the assistant's streamed text
is never captured — the most common agent pattern writes no memory (recall still
works; only the WRITE side has the gap). Bug check #2 confirmed this.

We TEE the stream: yield every chunk to the user UNCHANGED and in real time while
accumulating the assistant's text on the side; once the stream is exhausted, the
assembled text is handed to `on_complete` (which routes it into the normal capture
path). The tee is LAZY — it only pulls a chunk from the underlying stream when the
user asks for the next one, so we never buffer ahead or alter delivery timing.

Fail-soft contract (same as the wrappers): accumulating or capturing must NEVER
interrupt or alter the user's stream. Per-chunk extraction errors are swallowed,
and the terminal `on_complete` is guarded too.

Generators alone can't preserve the SDK `Stream`'s context-manager / `.close()` /
attribute surface, so each generator is wrapped in a thin proxy that delegates
those to the real stream while iteration flows through the tee. This keeps
`with client...create(stream=True) as s:` and `s.close()` working exactly as before.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

logger = logging.getLogger("octopoda.instrument.stream")

# chunk -> text delta for this chunk ('' if the chunk carries no text)
ChunkTextFn = Callable[[Any], str]
# called once with the full assembled assistant text after the stream ends
OnCompleteFn = Callable[[str], None]


def tee_sync_stream(
    stream: Iterator,
    chunk_text: ChunkTextFn,
    on_complete: OnCompleteFn,
) -> Iterator:
    """Yield every chunk from a sync stream unchanged; accumulate text; call
    `on_complete(full_text)` exactly once when iteration ends (normally or via
    early close)."""
    parts: list[str] = []
    try:
        for chunk in stream:
            try:
                piece = chunk_text(chunk)
                if piece:
                    parts.append(piece)
            except Exception:  # capture must never disrupt the stream
                pass
            yield chunk
    finally:
        # Fire even when no assistant text was streamed: the user's message still
        # carries durable facts and must be captured (parity with the non-stream
        # path, which always captures). Guarded so capture can't break the stream.
        try:
            on_complete("".join(parts))
        except Exception as e:
            logger.warning("stream capture failed (memory not written): %s", e)


async def tee_async_stream(
    stream: AsyncIterator,
    chunk_text: ChunkTextFn,
    on_complete: OnCompleteFn,
) -> AsyncIterator:
    """Async counterpart of :func:`tee_sync_stream`."""
    parts: list[str] = []
    try:
        async for chunk in stream:
            try:
                piece = chunk_text(chunk)
                if piece:
                    parts.append(piece)
            except Exception:  # capture must never disrupt the stream
                pass
            yield chunk
    finally:
        # Fire even when no assistant text was streamed (parity with non-stream).
        try:
            on_complete("".join(parts))
        except Exception as e:
            logger.warning("stream capture failed (memory not written): %s", e)


class SyncStreamProxy:
    """Wraps a sync SDK `Stream`. Iteration flows through the tee (capturing the
    assistant text); context-manager use, `.close()`, and any other attribute
    (`.response`, ...) delegate to the real stream — so user code that does
    `with ... as s:` / `s.close()` / `for c in s:` behaves exactly as unwrapped."""

    def __init__(
        self, stream: Any, chunk_text: ChunkTextFn, on_complete: OnCompleteFn
    ) -> None:
        self._stream = stream
        self._tee = tee_sync_stream(stream, chunk_text, on_complete)

    def __iter__(self) -> Iterator:
        return self._tee

    def __next__(self) -> Any:
        return next(self._tee)

    def __enter__(self) -> SyncStreamProxy:
        enter = getattr(self._stream, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, *exc: Any) -> Any:
        # Close the tee first so a partial (early-exit) stream still captures what
        # was streamed, then hand off to the real stream's __exit__.
        self.close()
        exit_ = getattr(self._stream, "__exit__", None)
        if exit_ is not None:
            return exit_(*exc)
        return False

    def close(self) -> None:
        # Closing the tee runs its `finally` -> on_complete fires (once); then
        # release the underlying stream's resources.
        try:
            self._tee.close()
        finally:
            closer = getattr(self._stream, "close", None)
            if closer is not None:
                closer()

    def __getattr__(self, name: str) -> Any:
        # Only reached for attrs not defined on the proxy -> delegate to the stream.
        return getattr(self._stream, name)


class AsyncStreamProxy:
    """Async counterpart of :class:`SyncStreamProxy` (preserves `async with`,
    `aclose()`, `async for`)."""

    def __init__(
        self, stream: Any, chunk_text: ChunkTextFn, on_complete: OnCompleteFn
    ) -> None:
        self._stream = stream
        self._tee = tee_async_stream(stream, chunk_text, on_complete)

    def __aiter__(self) -> AsyncIterator:
        return self._tee

    async def __anext__(self) -> Any:
        return await self._tee.__anext__()

    async def __aenter__(self) -> AsyncStreamProxy:
        enter = getattr(self._stream, "__aenter__", None)
        if enter is not None:
            await enter()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        await self.aclose()
        exit_ = getattr(self._stream, "__aexit__", None)
        if exit_ is not None:
            return await exit_(*exc)
        return False

    async def aclose(self) -> None:
        try:
            await self._tee.aclose()
        finally:
            closer = getattr(self._stream, "close", None)
            if closer is not None:
                result = closer()
                if hasattr(result, "__await__"):
                    await result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)
