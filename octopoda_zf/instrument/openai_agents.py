"""OpenAI Agents SDK hook (capture-only, best-effort).

The OpenAI Agents SDK runs agents via `Runner.run(starting_agent, input, ...)`
(async) and returns a result with `.final_output` (and run items). We capture
the input + final output as a transcript after the run completes.

This SDK is newer and its surface is less stable than the OpenAI/Anthropic SDKs,
so this hook is deliberately tolerant and clearly best-effort. Fail-soft: any
capture error is swallowed; the user's run result is always returned unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .base import apply_patch

logger = logging.getLogger("octopoda.instrument.openai_agents")

SubmitTranscriptFn = Callable[[str, str], None]
AgentIdFn = Callable[[], str]


def _input_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        # list of message dicts
        parts = []
        for m in value:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                if isinstance(content, str) and content.strip():
                    parts.append(f"{role}: {content.strip()}")
        return "\n".join(parts)
    return ""


def agents_result_to_transcript(input_value: Any, result: Any) -> str:
    """Render (input, RunResult) into transcript text."""
    lines: list[str] = []
    in_text = _input_text(input_value)
    if in_text:
        lines.append(in_text if ":" in in_text else f"User: {in_text}")
    final = getattr(result, "final_output", None)
    if final is None and isinstance(result, dict):
        final = result.get("final_output")
    if final:
        lines.append(f"Assistant: {final}")
    return "\n".join(lines)


def _extract_input(args: tuple, kwargs: dict) -> Any:
    """Find the `input` argument across positional/keyword call styles.

    Runner.run(starting_agent, input, ...) — input is usually args[1] (after the
    agent) or the `input` kwarg."""
    if "input" in kwargs:
        return kwargs["input"]
    # args[0] is typically the starting agent; input is the next positional
    if len(args) >= 2:
        return args[1]
    return ""


def make_run_wrapper(
    original: Callable,
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> Callable:
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        try:
            input_value = _extract_input(args, kwargs)
            transcript = agents_result_to_transcript(input_value, result)
            if transcript:
                submit_transcript(agent_id_fn(), transcript)
        except Exception as e:
            logger.warning("openai-agents capture failed: %s", e)
        return result

    return wrapper


def make_sync_run_wrapper(
    original: Callable,
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> Callable:
    """Sync variant for Runner.run_sync (not a coroutine)."""
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        try:
            input_value = _extract_input(args, kwargs)
            transcript = agents_result_to_transcript(input_value, result)
            if transcript:
                submit_transcript(agent_id_fn(), transcript)
        except Exception as e:
            logger.warning("openai-agents sync capture failed: %s", e)
        return result

    return wrapper


async def _tee_capture(agen, result, input_value, submit_transcript, agent_id_fn):
    """Yield streamed events unchanged; capture the transcript once the
    stream is fully consumed (final_output is populated by then)."""
    async for ev in agen:
        yield ev
    try:
        transcript = agents_result_to_transcript(input_value, result)
        if transcript:
            submit_transcript(agent_id_fn(), transcript)
    except Exception as e:
        logger.warning("openai-agents streamed capture failed: %s", e)


def make_streamed_run_wrapper(
    original: Callable,
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> Callable:
    """Wrap Runner.run_streamed: tee the result's stream_events so the
    transcript is captured after the stream is fully consumed."""
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        try:
            input_value = _extract_input(args, kwargs)
            _orig_se = result.stream_events
            def _teed_stream_events():
                return _tee_capture(_orig_se(), result, input_value, submit_transcript, agent_id_fn)
            result.stream_events = _teed_stream_events
        except Exception as e:
            logger.warning("openai-agents streamed wrap failed: %s", e)
        return result

    return wrapper


def install_capture(
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> list:
    """Resolve the OpenAI Agents SDK Runner and wrap run. Import-guarded."""
    handles = []
    try:
        from agents import Runner  # type: ignore
    except ImportError:
        logger.debug("openai-agents SDK not importable; skipping hook")
        return handles

    if not hasattr(Runner, "run"):
        return handles

    h = apply_patch(
        Runner,
        "run",
        lambda original: make_run_wrapper(original, submit_transcript, agent_id_fn),
        label="openai_agents.Runner.run",
    )
    if h:
        handles.append(h)
    # run_sync is the common synchronous entry point in scripts; the
    # async-only `run` hook missed it entirely, so capture it too.
    if hasattr(Runner, "run_sync"):
        h2 = apply_patch(
            Runner,
            "run_sync",
            lambda original: make_sync_run_wrapper(original, submit_transcript, agent_id_fn),
            label="openai_agents.Runner.run_sync",
        )
        if h2:
            handles.append(h2)
    if hasattr(Runner, "run_streamed"):
        h3 = apply_patch(
            Runner,
            "run_streamed",
            lambda original: make_streamed_run_wrapper(original, submit_transcript, agent_id_fn),
            label="openai_agents.Runner.run_streamed",
        )
        if h3:
            handles.append(h3)
    return handles
