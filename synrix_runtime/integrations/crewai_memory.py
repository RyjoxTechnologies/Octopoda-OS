"""
Octopoda × CrewAI Integration (Runtime)
=========================================
Shared persistent memory for CrewAI crews.
All memory is stored in the Octopoda Cloud API (api.octopodas.com).

Setup:
    pip install octopoda[client] crewai
    export OCTOPODA_API_KEY=sk-octopoda-...

Usage:
    from synrix_runtime.integrations.crewai_memory import SynrixCrewMemory
    crew_memory = SynrixCrewMemory(crew_id="research_crew")

For the full CrewAI integration, use:
    from synrix.integrations.crewai import OctopodaCrewMemory
"""

import time
import json
from typing import Dict, List, Any, Optional

from synrix.cloud import Octopoda

_client: Optional[Octopoda] = None


def _get_client() -> Octopoda:
    global _client
    if _client is None:
        _client = Octopoda()
    return _client


class SynrixCrewMemory:
    """
    Shared persistent memory for CrewAI crews, backed by Octopoda Cloud.
    All agents in the crew share knowledge through the cloud API.

    Requires OCTOPODA_API_KEY environment variable.
    Get your free key at https://octopodas.com

    Usage:
        crew_memory = SynrixCrewMemory(crew_id="research_crew")
        crew_memory.store_finding("researcher", "market_size", {"value": "$4.2B"})
        finding = crew_memory.get_finding("market_size")
    """

    def __init__(self, crew_id: str, backend=None, crew_name: Optional[str] = None, **kwargs):
        self.crew_id = crew_id
        self.crew_name = crew_name or crew_id

        if backend is not None:
            from synrix_runtime.integrations._local_adapter import _LocalAgentAdapter
            self._agent = _LocalAgentAdapter(backend, f"crewai_{crew_id}")
            self.backend = backend
        else:
            client = _get_client()
            self._agent = client.agent(f"crewai_{crew_id}", metadata={"type": "crewai", "crew": crew_id})
            self.backend = None

        self._agent.write(
            f"crewai:{crew_id}:meta",
            {"crew_id": crew_id, "created_at": time.time()},
        )

    def store_finding(self, agent_role: str, key: str, finding: Any):
        """Store a finding from a crew agent."""
        payload = finding if isinstance(finding, dict) else {"value": finding}
        payload["_agent_role"] = agent_role
        payload["_stored_at"] = time.time()

        t0 = time.perf_counter()
        self._agent.write(
            f"crewai:{self.crew_id}:findings:{key}",
            payload,
            tags=["crew_finding", agent_role],
        )
        latency_us = (time.perf_counter() - t0) * 1_000_000
        return {"key": key, "latency_us": round(latency_us, 1)}

    def get_finding(self, key: str) -> Optional[dict]:
        """Get a specific finding."""
        return self._agent.read(f"crewai:{self.crew_id}:findings:{key}")

    def get_all_findings(self) -> list:
        """Get all findings from the crew."""
        results = self._agent.keys(prefix=f"crewai:{self.crew_id}:findings:", limit=200)
        findings = []
        for r in results:
            key = r.get("key", "").replace(f"crewai:{self.crew_id}:findings:", "")
            val = r.get("value", r)
            findings.append({"key": key, "data": val})
        return findings

    def store_task_result(self, task_name: str, result: Any, agent_role: str):
        """Store a task result."""
        payload = result if isinstance(result, dict) else {"value": result}
        payload["_agent_role"] = agent_role
        payload["_completed_at"] = time.time()

        self._agent.write(
            f"crewai:{self.crew_id}:tasks:{task_name}",
            payload,
            tags=["crew_task_result", agent_role],
        )

    def get_crew_knowledge_base(self) -> dict:
        """Get the entire crew knowledge base."""
        findings = self.get_all_findings()
        tasks = self._agent.keys(prefix=f"crewai:{self.crew_id}:tasks:", limit=200)

        task_results = []
        for t in tasks:
            key = t.get("key", "").replace(f"crewai:{self.crew_id}:tasks:", "")
            val = t.get("value", t)
            task_results.append({"task": key, "result": val})

        return {
            "crew_id": self.crew_id,
            "findings": findings,
            "task_results": task_results,
            "total_items": len(findings) + len(task_results),
        }

    def crew_snapshot(self, label: str = None):
        """Snapshot entire crew state."""
        if label is None:
            label = f"crew_snap_{int(time.time()*1000000)}"

        kb = self.get_crew_knowledge_base()
        self._agent.write(
            f"crewai:{self.crew_id}:snapshots:{label}",
            {"label": label, "knowledge_base": kb, "created_at": time.time()},
        )
        return {"label": label, "items": kb["total_items"]}

    def crew_restore(self, label: str) -> dict:
        """Restore crew state from a snapshot."""
        val = self._agent.read(f"crewai:{self.crew_id}:snapshots:{label}")
        if val is None:
            return {"restored": False, "reason": "snapshot_not_found"}

        kb = val.get("knowledge_base", {}) if isinstance(val, dict) else {}

        restored = 0
        for finding in kb.get("findings", []):
            self.store_finding("restored", finding.get("key", ""), finding.get("data", {}))
            restored += 1

        return {"restored": True, "label": label, "items_restored": restored}
