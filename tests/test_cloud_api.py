"""
Tests for the Cloud API (FastAPI on port 8741).

Uses FastAPI TestClient — no real server needed.
Auth is disabled via SYNRIX_AUTH_DISABLED=1 env var in the fixture.
"""

import pytest


class TestHealthAndSystem:

    def test_health(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "3.0.3"
        assert data["uptime_seconds"] >= 0

    def test_system_status(self, api_client):
        resp = api_client.get("/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"


class TestAgentManagement:

    def test_register_agent(self, api_client):
        resp = api_client.post("/v1/agents", json={"agent_id": "bot_1", "agent_type": "chat"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "bot_1"
        assert data["status"] == "running"

    def test_list_agents(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "bot_list"})
        resp = api_client.get("/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    def test_get_agent(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "bot_get"})
        resp = api_client.get("/v1/agents/bot_get")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "bot_get"

    def test_get_agent_not_found(self, api_client):
        resp = api_client.get("/v1/agents/nonexistent_agent")
        assert resp.status_code == 404

    def test_deregister_agent(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "bot_dereg"})
        resp = api_client.delete("/v1/agents/bot_dereg")
        assert resp.status_code == 200
        assert resp.json()["deregistered"]


class TestMemoryOperations:

    def test_remember_and_recall(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "mem_agent"})
        resp = api_client.post("/v1/agents/mem_agent/remember", json={
            "key": "favorite_color",
            "value": {"color": "green"},
        })
        assert resp.status_code == 200
        assert resp.json()["success"]

        resp = api_client.get("/v1/agents/mem_agent/recall/favorite_color")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"]
        assert data["value"]["color"] == "green"

    def test_recall_missing_key(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "mem_miss"})
        resp = api_client.get("/v1/agents/mem_miss/recall/does_not_exist")
        assert resp.status_code == 200
        assert not resp.json()["found"]

    def test_search(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "mem_search"})
        api_client.post("/v1/agents/mem_search/remember", json={"key": "config:theme", "value": "dark"})
        api_client.post("/v1/agents/mem_search/remember", json={"key": "config:lang", "value": "en"})

        resp = api_client.get("/v1/agents/mem_search/search?prefix=config:")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_batch_remember(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "mem_batch"})
        resp = api_client.post("/v1/agents/mem_batch/remember/batch", json={
            "items": [
                {"key": "a", "value": 1},
                {"key": "b", "value": 2},
                {"key": "c", "value": 3},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3

    def test_list_memory(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "mem_list"})
        api_client.post("/v1/agents/mem_list/remember", json={"key": "x", "value": 1})
        resp = api_client.get("/v1/agents/mem_list/memory")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1


class TestSnapshots:

    def test_snapshot_and_restore(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "snap_agent"})
        api_client.post("/v1/agents/snap_agent/remember", json={"key": "data", "value": "important"})

        resp = api_client.post("/v1/agents/snap_agent/snapshot", json={"label": "v1"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "v1"
        assert resp.json()["keys_captured"] >= 1

        resp = api_client.post("/v1/agents/snap_agent/restore", json={"label": "v1"})
        assert resp.status_code == 200
        assert resp.json()["label"] == "v1"
        assert resp.json()["keys_restored"] >= 1


class TestSharedMemory:

    def test_shared_write_and_read(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "sharer"})

        resp = api_client.post("/v1/shared/global", json={
            "key": "project_name",
            "value": "Octopoda",
            "author_agent_id": "sharer",
        })
        assert resp.status_code == 200
        assert resp.json()["success"]

        resp = api_client.get("/v1/shared/global/project_name")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"]

    def test_shared_list(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "sharer2"})
        api_client.post("/v1/shared/team", json={
            "key": "goal",
            "value": "ship v1",
            "author_agent_id": "sharer2",
        })

        resp = api_client.get("/v1/shared/team")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

    def test_shared_spaces(self, api_client):
        resp = api_client.get("/v1/shared")
        assert resp.status_code == 200
        assert "spaces" in resp.json()


class TestAuditAndDecisions:

    def test_log_decision(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "decide_agent"})
        resp = api_client.post("/v1/agents/decide_agent/decision", json={
            "decision": "Use RAG",
            "reasoning": "Better accuracy for domain-specific queries",
        })
        assert resp.status_code == 200
        assert resp.json()["logged"]

    def test_audit_trail(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "audit_agent"})
        resp = api_client.get("/v1/agents/audit_agent/audit")
        assert resp.status_code == 200
        assert "events" in resp.json()


class TestMetrics:

    def test_agent_metrics(self, api_client):
        api_client.post("/v1/agents", json={"agent_id": "metric_agent"})
        api_client.post("/v1/agents/metric_agent/remember", json={"key": "x", "value": 1})

        resp = api_client.get("/v1/agents/metric_agent/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "metric_agent"

    def test_system_metrics(self, api_client):
        resp = api_client.get("/v1/metrics/system")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_operations" in data


class TestRecovery:

    def test_recovery_history(self, api_client):
        resp = api_client.get("/v1/recovery/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data
        assert "stats" in data


class TestRawOperations:

    def test_raw_write_and_read(self, api_client):
        resp = api_client.post("/v1/raw/write", json={"key": "test:raw", "value": {"data": 42}})
        assert resp.status_code == 200
        assert resp.json()["key"] == "test:raw"

        resp = api_client.get("/v1/raw/read/test:raw")
        assert resp.status_code == 200
        assert resp.json()["found"]

    def test_raw_query(self, api_client):
        api_client.post("/v1/raw/write", json={"key": "ns:a", "value": 1})
        api_client.post("/v1/raw/write", json={"key": "ns:b", "value": 2})

        resp = api_client.get("/v1/raw/query?prefix=ns:")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 2
