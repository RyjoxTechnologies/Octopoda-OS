"""Procedural memory (value-add #3): remember what WORKED, not just what was said.

A different axis from factual memory: it records the OUTCOME of an approach to a
task, so an agent can recall the approaches that SUCCEEDED for similar tasks next
time, and avoid the ones that failed.

Honest scope: this is an EXPLICIT API — the agent (or developer) records an outcome
when a task finishes. Auto-detecting "success" from a transcript is unreliable, so
we don't pretend to. Procedures are stored as a TYPED memory, so they ride the same
recall + audit + dedup + supersession infrastructure as facts.

    pm = octopoda.procedural()
    pm.record("deploy to prod", "run CI green, then flip the feature flag", success=True)
    for p in pm.recall("deploy to prod"):   # only the approaches that worked
        print(p.approach)
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from .client.api import CloudClient
from .scope import derive_agent_id


@dataclass(frozen=True)
class Procedure:
    task: str
    approach: str
    success: bool
    note: str = ""


class ProceduralMemory:
    """Record + recall task→approach→outcome procedures via the memory store."""

    def __init__(
        self, client: CloudClient, agent_id_fn: Callable[[], str] = derive_agent_id
    ) -> None:
        self._client = client
        self._agent_id_fn = agent_id_fn

    def record(self, task: str, approach: str, success: bool, note: str = "") -> bool:
        """Persist the outcome of an approach to a task. Returns False (no-op) for
        empty task/approach. Fail-soft via the client."""
        if not task.strip() or not approach.strip():
            return False
        agent = self._agent_id_fn()
        key = "proc:" + hashlib.sha1(f"{task}|{approach}".encode()).hexdigest()[:16]
        value = {
            "value": (f"For task '{task.strip()}': {approach.strip()}"
                      + (" [WORKED]" if success else " [did NOT work]")),
            "fact_type": "procedure",
            "task": task.strip(),
            "approach": approach.strip(),
            "success": bool(success),
            "note": note.strip(),
            "source": "procedural",
        }
        return self._client.remember(agent, key, value)

    def recall(self, task: str, limit: int = 5, include_failures: bool = False) -> list[Procedure]:
        """Return procedures for a similar task — by default only the ones that
        WORKED (set include_failures=True to also surface what to avoid)."""
        if not task.strip():
            return []
        agent = self._agent_id_fn()
        hits = self._client.recall_similar(agent, f"how to accomplish: {task}", limit=limit * 3)
        out: list[Procedure] = []
        for h in hits:
            data = h.raw.get("data") if isinstance(h.raw.get("data"), dict) else h.raw
            if not isinstance(data, dict) or data.get("fact_type") != "procedure":
                continue
            success = bool(data.get("success"))
            if not success and not include_failures:
                continue
            out.append(Procedure(
                task=str(data.get("task", "")),
                approach=str(data.get("approach", "")),
                success=success,
                note=str(data.get("note", "")),
            ))
            if len(out) >= limit:
                break
        return out
