"""CrewAI hook (capture-only).

CrewAI orchestrates multiple agents internally, so recall injection into the
crew is out of scope for v1 (it would mean rewriting agent backstories / task
descriptions before kickoff). Instead we CAPTURE the crew's task outputs after
`Crew.kickoff()` returns and write them as memories — mirroring what the
existing explicit `CrewAIMemory` adapter does, but automatically.

Capture-only hook interface:
    install_capture(submit_transcript_fn, agent_id_fn) -> [handles]
where submit_transcript_fn(agent_id, text) enqueues a transcript turn.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .base import apply_patch

logger = logging.getLogger("octopoda.instrument.crewai")

SubmitTranscriptFn = Callable[[str, str], None]
AgentIdFn = Callable[[], str]


def crew_output_to_transcript(result: Any) -> str:
    """Render a CrewOutput's task results into transcript text."""
    lines: list[str] = []
    tasks = getattr(result, "tasks_output", None)
    if tasks is None and isinstance(result, dict):
        tasks = result.get("tasks_output")
    for t in tasks or []:
        raw = getattr(t, "raw", None)
        if raw is None and isinstance(t, dict):
            raw = t.get("raw")
        agent = getattr(t, "agent", None)
        if agent is None and isinstance(t, dict):
            agent = t.get("agent")
        text = str(raw) if raw is not None else str(t)
        role = str(agent) if agent else "crew"
        if text.strip():
            lines.append(f"{role}: {text.strip()}")
    return "\n".join(lines)


def _crew_id(crew: Any, agent_id_fn: AgentIdFn) -> str:
    """Prefer an explicit scope/env agent_id; else fall back to the crew's name."""
    from ..scope import current_scope

    if current_scope():
        return agent_id_fn()
    import os

    if os.environ.get("OCTOPODA_AGENT_ID"):
        return agent_id_fn()
    name = getattr(crew, "name", None)
    if name:
        from ..scope import sanitize_agent_id

        return sanitize_agent_id(str(name))
    return agent_id_fn()


def make_kickoff_wrapper(
    original: Callable,
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> Callable:
    def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        try:
            transcript = crew_output_to_transcript(result)
            if transcript:
                submit_transcript(_crew_id(self, agent_id_fn), transcript)
        except Exception as e:
            logger.warning("crewai capture failed: %s", e)
        return result

    return wrapper


def make_async_kickoff_wrapper(
    original: Callable,
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> Callable:
    async def wrapper(self, *args: Any, **kwargs: Any) -> Any:
        result = await original(self, *args, **kwargs)
        try:
            transcript = crew_output_to_transcript(result)
            if transcript:
                submit_transcript(_crew_id(self, agent_id_fn), transcript)
        except Exception as e:
            logger.warning("crewai async capture failed: %s", e)
        return result

    return wrapper


def install_capture(
    submit_transcript: SubmitTranscriptFn,
    agent_id_fn: AgentIdFn,
) -> list:
    """Resolve the real CrewAI Crew and wrap kickoff (+ kickoff_async)."""
    handles = []
    try:
        from crewai import Crew  # type: ignore
    except ImportError:
        logger.debug("crewai not importable; skipping CrewAI hook")
        return handles

    h1 = apply_patch(
        Crew,
        "kickoff",
        lambda original: make_kickoff_wrapper(original, submit_transcript, agent_id_fn),
        label="crewai.Crew.kickoff",
    )
    if h1:
        handles.append(h1)

    if hasattr(Crew, "kickoff_async"):
        h2 = apply_patch(
            Crew,
            "kickoff_async",
            lambda original: make_async_kickoff_wrapper(original, submit_transcript, agent_id_fn),
            label="crewai.Crew.kickoff_async",
        )
        if h2:
            handles.append(h2)
    return handles
