"""
Synrix Cloud Client SDK
========================
Python client for connecting to a remote Synrix Cloud API server.

Usage:
    from synrix_runtime.api.cloud_client import SynrixCloudClient

    client = SynrixCloudClient("http://localhost:8741", api_key="sk-synrix-...")

    # Register agent
    client.register_agent("my_agent", agent_type="researcher")

    # Memory operations
    client.remember("my_agent", "finding_01", {"market_size": "$4.2B"})
    result = client.recall("my_agent", "finding_01")

    # Shared memory
    client.share("research_team", "key", {"data": "value"}, author="my_agent")
"""

import time
import requests
from typing import Any, Optional, Dict, List


class SynrixCloudClient:
    """Remote client for Synrix Agent Runtime API."""

    def __init__(self, base_url: str = "http://localhost:8741", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        self.session.headers["Content-Type"] = "application/json"

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        return self._get("/health")

    def status(self) -> dict:
        return self._get("/v1/status")

    # ------------------------------------------------------------------
    # Agent Management
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str, agent_type: str = "generic", metadata: dict = None) -> dict:
        return self._post("/v1/agents", {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "metadata": metadata or {},
        })

    def list_agents(self) -> dict:
        return self._get("/v1/agents")

    def get_agent(self, agent_id: str) -> dict:
        return self._get(f"/v1/agents/{agent_id}")

    def deregister_agent(self, agent_id: str) -> dict:
        return self._delete(f"/v1/agents/{agent_id}")

    # ------------------------------------------------------------------
    # Memory Operations
    # ------------------------------------------------------------------

    def remember(self, agent_id: str, key: str, value: Any, tags: list = None) -> dict:
        return self._post(f"/v1/agents/{agent_id}/remember", {
            "key": key,
            "value": value,
            "tags": tags,
        })

    def recall(self, agent_id: str, key: str) -> dict:
        return self._get(f"/v1/agents/{agent_id}/recall/{key}")

    def search(self, agent_id: str, q: str = "", prefix: str = "", limit: int = 50) -> dict:
        params = {"limit": limit}
        if q:
            params["q"] = q
        if prefix:
            params["prefix"] = prefix
        return self._get(f"/v1/agents/{agent_id}/search", params=params)

    def similar(self, agent_id: str, query: str, limit: int = 10) -> dict:
        return self._get(f"/v1/agents/{agent_id}/similar", params={"q": query, "limit": limit})

    def history(self, agent_id: str, key: str) -> dict:
        return self._get(f"/v1/agents/{agent_id}/history/{key}")

    def list_memory(self, agent_id: str, limit: int = 200) -> dict:
        return self._get(f"/v1/agents/{agent_id}/memory", params={"limit": limit})

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def snapshot(self, agent_id: str, label: str = None) -> dict:
        return self._post(f"/v1/agents/{agent_id}/snapshot", {"label": label})

    def restore(self, agent_id: str, label: str = None) -> dict:
        return self._post(f"/v1/agents/{agent_id}/restore", {"label": label})

    # ------------------------------------------------------------------
    # Shared Memory
    # ------------------------------------------------------------------

    def share(self, space: str, key: str, value: Any, author: str) -> dict:
        return self._post(f"/v1/shared/{space}", {
            "key": key,
            "value": value,
            "author_agent_id": author,
        })

    def read_shared(self, space: str, key: str) -> dict:
        return self._get(f"/v1/shared/{space}/{key}")

    def list_shared(self, space: str) -> dict:
        return self._get(f"/v1/shared/{space}")

    def list_spaces(self) -> dict:
        return self._get("/v1/shared")

    # ------------------------------------------------------------------
    # Audit & Metrics
    # ------------------------------------------------------------------

    def audit(self, agent_id: str, limit: int = 50) -> dict:
        return self._get(f"/v1/agents/{agent_id}/audit", params={"limit": limit})

    def log_decision(self, agent_id: str, decision: str, reasoning: str, context: dict = None) -> dict:
        return self._post(f"/v1/agents/{agent_id}/decision", {
            "decision": decision,
            "reasoning": reasoning,
            "context": context,
        })

    def metrics(self, agent_id: str) -> dict:
        return self._get(f"/v1/agents/{agent_id}/metrics")

    def system_metrics(self) -> dict:
        return self._get("/v1/metrics/system")

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover(self, agent_id: str) -> dict:
        return self._post(f"/v1/agents/{agent_id}/recover", {})

    def recovery_history(self) -> dict:
        return self._get("/v1/recovery/history")

    # ------------------------------------------------------------------
    # Raw operations
    # ------------------------------------------------------------------

    def raw_write(self, key: str, value: Any, metadata: dict = None) -> dict:
        return self._post("/v1/raw/write", {"key": key, "value": value, "metadata": metadata})

    def raw_read(self, key: str) -> dict:
        return self._get(f"/v1/raw/read/{key}")

    def raw_query(self, prefix: str = "", limit: int = 100) -> dict:
        return self._get("/v1/raw/query", params={"prefix": prefix, "limit": limit})

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict = None) -> dict:
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=(3, 30))
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict) -> dict:
        resp = self.session.post(f"{self.base_url}{path}", json=data, timeout=(3, 30))
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        resp = self.session.delete(f"{self.base_url}{path}", timeout=(3, 30))
        resp.raise_for_status()
        return resp.json()

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
