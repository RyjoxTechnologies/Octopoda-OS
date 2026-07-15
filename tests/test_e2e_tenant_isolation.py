"""
End-to-End Tenant Isolation & Auth Tests
==========================================
Tests the FULL flow: signup → verify → login → use API → verify isolation.
Uses FastAPI TestClient with REAL multi-tenant auth (NOT auth-disabled mode).

These tests prove:
1. Two tenants cannot see each other's agents or memories
2. Auth flow works correctly (signup, verify, login, API key)
3. Invalid/missing auth is rejected
4. Cross-tenant access is impossible at every endpoint
"""

import os
import secrets
import pytest
import tempfile

# These E2E tests exercise the real multi-tenant cloud server, which needs the
# [server] extra (FastAPI) and a live PostgreSQL. Skip cleanly when either is
# missing rather than erroring during collection — the multi-tenant registry has
# no SQLite fallback, so run them with: pip install -e .[server] and DATABASE_URL set.
pytest.importorskip("fastapi", reason="tenant-isolation E2E tests need the [server] extra")
if not os.environ.get("DATABASE_URL"):
    pytest.skip(
        "Tenant-isolation E2E tests require a live PostgreSQL (set DATABASE_URL).",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient

# Unique suffix per test run to avoid stale account collisions
_RUN_ID = secrets.token_hex(4)


# ---------------------------------------------------------------------------
# Fixtures — fresh server with REAL auth (no auth-disabled bypass)
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_env(tmp_dir, monkeypatch):
    """
    Boot the cloud server with real multi-tenant auth enabled.
    Uses Postgres if DATABASE_URL is set, otherwise falls back to SQLite.
    """
    backend = os.environ.get("SYNRIX_BACKEND", "sqlite")
    monkeypatch.setenv("SYNRIX_BACKEND", backend)
    if backend == "sqlite":
        monkeypatch.setenv("SYNRIX_DATA_DIR", tmp_dir)
    monkeypatch.delenv("SYNRIX_AUTH_DISABLED", raising=False)

    from synrix_runtime.core.daemon import RuntimeDaemon
    from synrix_runtime.monitoring.metrics import MetricsCollector
    RuntimeDaemon.reset_instance()
    MetricsCollector._instance = None
    MetricsCollector._instances = {}

    from synrix_runtime.api.tenant import TenantManager
    TenantManager._instance = None
    if backend == "postgres":
        TenantManager.get_instance(dsn=os.environ.get("DATABASE_URL"))
    else:
        TenantManager.get_instance(data_dir=tmp_dir)

    daemon = RuntimeDaemon.get_instance()
    daemon.start()

    from synrix_runtime.config import SynrixConfig
    config = SynrixConfig.from_env()

    from synrix_runtime.api import cloud_server
    from synrix_runtime.api.cloud_server import app, init_cloud_server, _agent_runtimes

    cloud_server._rate_limiter = cloud_server._RateLimiter()
    cloud_server._auth_rate_limiter = cloud_server._RateLimiter()
    _agent_runtimes.clear()
    init_cloud_server(daemon, config)

    client = TestClient(app)

    yield client

    daemon.shutdown()
    RuntimeDaemon.reset_instance()
    MetricsCollector._instance = None
    MetricsCollector._instances = {}
    TenantManager._instance = None
    cloud_server._rate_limiter = cloud_server._RateLimiter()
    cloud_server._auth_rate_limiter = cloud_server._RateLimiter()


def _unique_email(email):
    """Make email unique per test run to avoid collisions in Postgres."""
    name, domain = email.split("@")
    return f"{name}_{_RUN_ID}@{domain}"


def _signup(client, email, password="TestPass123!", first_name="Test", last_name="User"):
    """Helper: sign up a new account."""
    email = _unique_email(email)
    resp = client.post("/v1/auth/signup", json={
        "email": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
    })
    return resp


def _verify_email(email):
    """Helper: force-verify an email (bypass code since no email server in tests)."""
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    tm.set_verified(_unique_email(email), True)


def _login(client, email, password="TestPass123!"):
    """Helper: login and return the API key."""
    resp = client.post("/v1/auth/login", json={
        "email": _unique_email(email),
        "password": password,
    })
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    return resp.json()["api_key"]


def _auth(api_key):
    """Helper: return auth header dict."""
    return {"Authorization": f"Bearer {api_key}"}


def _signup_verify_login(client, email, password="TestPass123!"):
    """Helper: full signup → verify → login flow. Returns API key."""
    resp = _signup(client, email, password)
    assert resp.status_code == 200, f"Signup failed: {resp.json()}"
    _verify_email(email)
    return _login(client, email, password)


# ---------------------------------------------------------------------------
# Auth Flow Tests
# ---------------------------------------------------------------------------

class TestAuthFlow:

    def test_signup_returns_tenant_id_and_key(self, tenant_env):
        resp = _signup(tenant_env, "alice@test.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "tenant_id" in data
        assert data["api_key"].startswith("sk-octopoda-")
        assert "alice" in data["email"]

    def test_duplicate_signup_fails(self, tenant_env):
        _signup(tenant_env, "dupe@test.com")
        resp = _signup(tenant_env, "dupe@test.com")
        data = resp.json()
        assert data.get("success") is False or resp.status_code >= 400

    def test_login_returns_working_key(self, tenant_env):
        api_key = _signup_verify_login(tenant_env, "login@test.com")
        assert api_key.startswith("sk-octopoda-")

        # Key should work for authenticated endpoints
        resp = tenant_env.get("/v1/agents", headers=_auth(api_key))
        assert resp.status_code == 200

    def test_unverified_email_blocked(self, tenant_env):
        resp = _signup(tenant_env, "unverified@test.com")
        api_key = resp.json()["api_key"]

        # Don't verify — should be blocked
        resp = tenant_env.get("/v1/agents", headers=_auth(api_key))
        assert resp.status_code == 403

    def test_wrong_password_rejected(self, tenant_env):
        _signup(tenant_env, "wrongpw@test.com", password="CorrectPass123!")
        _verify_email("wrongpw@test.com")

        resp = tenant_env.post("/v1/auth/login", json={
            "email": "wrongpw@test.com",
            "password": "WrongPassword!",
        })
        assert resp.status_code == 401

    def test_invalid_api_key_rejected(self, tenant_env):
        resp = tenant_env.get("/v1/agents", headers=_auth("sk-octopoda-fake-key"))
        assert resp.status_code == 401

    def test_missing_auth_header_rejected(self, tenant_env):
        resp = tenant_env.get("/v1/agents")
        assert resp.status_code == 401

    def test_me_endpoint(self, tenant_env):
        api_key = _signup_verify_login(tenant_env, "me@test.com")
        resp = tenant_env.get("/v1/auth/me", headers=_auth(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "me" in data["email"]


# ---------------------------------------------------------------------------
# Tenant Isolation — Agents
# ---------------------------------------------------------------------------

class TestTenantIsolationAgents:

    def test_agents_isolated_between_tenants(self, tenant_env):
        """Tenant A's agents must NOT be visible to Tenant B."""
        key_a = _signup_verify_login(tenant_env, "tenant_a@test.com")
        key_b = _signup_verify_login(tenant_env, "tenant_b@test.com")

        # Tenant A registers 3 agents
        for name in ["alpha", "beta", "gamma"]:
            resp = tenant_env.post("/v1/agents", json={"agent_id": name}, headers=_auth(key_a))
            assert resp.status_code == 200

        # Tenant A sees 3 agents
        resp = tenant_env.get("/v1/agents", headers=_auth(key_a))
        assert resp.json()["total"] == 3

        # Tenant B sees 0 agents
        resp = tenant_env.get("/v1/agents", headers=_auth(key_b))
        assert resp.json()["total"] == 0

    def test_cannot_access_other_tenants_agent(self, tenant_env):
        """Tenant B cannot GET details of Tenant A's agent."""
        key_a = _signup_verify_login(tenant_env, "owner@test.com")
        key_b = _signup_verify_login(tenant_env, "intruder@test.com")

        tenant_env.post("/v1/agents", json={"agent_id": "secret-bot"}, headers=_auth(key_a))

        # Tenant B tries to access Tenant A's agent
        resp = tenant_env.get("/v1/agents/secret-bot", headers=_auth(key_b))
        assert resp.status_code == 404

    def test_cannot_delete_other_tenants_agent(self, tenant_env):
        """Tenant B's delete does NOT affect Tenant A's agent.
        Note: DELETE currently returns 200 even for non-existent agents
        (it writes 'deregistered' to the caller's own DB). This is harmless
        but could be tightened to return 404. The key check is that Tenant A's
        agent is unaffected.
        """
        key_a = _signup_verify_login(tenant_env, "deleteowner@test.com")
        key_b = _signup_verify_login(tenant_env, "deleteattacker@test.com")

        tenant_env.post("/v1/agents", json={"agent_id": "protected-bot"}, headers=_auth(key_a))

        # Tenant B tries to delete — writes to B's own DB, not A's
        tenant_env.delete("/v1/agents/protected-bot", headers=_auth(key_b))

        # Verify agent still exists for Tenant A
        resp = tenant_env.get("/v1/agents/protected-bot", headers=_auth(key_a))
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == "protected-bot"

    def test_same_agent_id_different_tenants(self, tenant_env):
        """Two tenants can have agents with the same ID — fully isolated."""
        key_a = _signup_verify_login(tenant_env, "same_id_a@test.com")
        key_b = _signup_verify_login(tenant_env, "same_id_b@test.com")

        # Both register "my-agent"
        resp = tenant_env.post("/v1/agents", json={"agent_id": "my-agent"}, headers=_auth(key_a))
        assert resp.status_code == 200
        resp = tenant_env.post("/v1/agents", json={"agent_id": "my-agent"}, headers=_auth(key_b))
        assert resp.status_code == 200

        # Each sees exactly 1 agent
        resp = tenant_env.get("/v1/agents", headers=_auth(key_a))
        assert resp.json()["total"] == 1
        resp = tenant_env.get("/v1/agents", headers=_auth(key_b))
        assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# Tenant Isolation — Memory
# ---------------------------------------------------------------------------

class TestTenantIsolationMemory:

    def test_memories_isolated(self, tenant_env):
        """Tenant A's memories are invisible to Tenant B."""
        key_a = _signup_verify_login(tenant_env, "mem_a@test.com")
        key_b = _signup_verify_login(tenant_env, "mem_b@test.com")

        # Tenant A writes memory
        tenant_env.post("/v1/agents", json={"agent_id": "bot"}, headers=_auth(key_a))
        tenant_env.post("/v1/agents/bot/remember", json={
            "key": "secret", "value": "tenant_a_private_data"
        }, headers=_auth(key_a))

        # Verify Tenant A can recall
        # Note: string values are stored as {"value": "..."} by runtime.remember()
        resp = tenant_env.get("/v1/agents/bot/recall/secret", headers=_auth(key_a))
        assert resp.status_code == 200
        assert resp.json()["found"] is True
        assert resp.json()["value"]["value"] == "tenant_a_private_data"

        # Tenant B registers same agent name, tries to recall
        tenant_env.post("/v1/agents", json={"agent_id": "bot"}, headers=_auth(key_b))
        resp = tenant_env.get("/v1/agents/bot/recall/secret", headers=_auth(key_b))
        assert resp.status_code == 200
        assert resp.json()["found"] is False  # Not found — isolated

    def test_search_isolated(self, tenant_env):
        """Prefix search only returns current tenant's data."""
        key_a = _signup_verify_login(tenant_env, "search_a@test.com")
        key_b = _signup_verify_login(tenant_env, "search_b@test.com")

        # Tenant A writes data
        tenant_env.post("/v1/agents", json={"agent_id": "searcher"}, headers=_auth(key_a))
        tenant_env.post("/v1/agents/searcher/remember", json={
            "key": "config:api_key", "value": "sk-secret-123"
        }, headers=_auth(key_a))
        tenant_env.post("/v1/agents/searcher/remember", json={
            "key": "config:model", "value": "gpt-4"
        }, headers=_auth(key_a))

        # Tenant A search finds 2
        resp = tenant_env.get("/v1/agents/searcher/search?prefix=config:", headers=_auth(key_a))
        assert resp.json()["count"] == 2

        # Tenant B same agent name, search finds 0
        tenant_env.post("/v1/agents", json={"agent_id": "searcher"}, headers=_auth(key_b))
        resp = tenant_env.get("/v1/agents/searcher/search?prefix=config:", headers=_auth(key_b))
        assert resp.json()["count"] == 0

    def test_batch_remember_isolated(self, tenant_env):
        """Batch writes are tenant-isolated."""
        key_a = _signup_verify_login(tenant_env, "batch_a@test.com")
        key_b = _signup_verify_login(tenant_env, "batch_b@test.com")

        tenant_env.post("/v1/agents", json={"agent_id": "batcher"}, headers=_auth(key_a))
        tenant_env.post("/v1/agents/batcher/remember/batch", json={
            "items": [
                {"key": "a", "value": 1},
                {"key": "b", "value": 2},
                {"key": "c", "value": 3},
            ]
        }, headers=_auth(key_a))

        # Tenant A: 3 memories
        resp = tenant_env.get("/v1/agents/batcher/memory", headers=_auth(key_a))
        assert resp.json()["count"] == 3

        # Tenant B: 0
        tenant_env.post("/v1/agents", json={"agent_id": "batcher"}, headers=_auth(key_b))
        resp = tenant_env.get("/v1/agents/batcher/memory", headers=_auth(key_b))
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Tenant Isolation — Shared Memory
# ---------------------------------------------------------------------------

class TestTenantIsolationSharedMemory:

    def test_shared_memory_isolated(self, tenant_env):
        """Shared memory spaces are per-tenant, not global."""
        key_a = _signup_verify_login(tenant_env, "shared_a@test.com")
        key_b = _signup_verify_login(tenant_env, "shared_b@test.com")

        # Tenant A writes to shared space
        tenant_env.post("/v1/agents", json={"agent_id": "writer"}, headers=_auth(key_a))
        tenant_env.post("/v1/shared/team", json={
            "key": "project", "value": "secret-project", "author_agent_id": "writer"
        }, headers=_auth(key_a))

        # Tenant A can read it
        resp = tenant_env.get("/v1/shared/team/project", headers=_auth(key_a))
        assert resp.json()["found"] is True

        # Tenant B cannot
        resp = tenant_env.get("/v1/shared/team/project", headers=_auth(key_b))
        assert resp.json()["found"] is False

    def test_shared_spaces_list_isolated(self, tenant_env):
        """Listing shared spaces only shows current tenant's spaces."""
        key_a = _signup_verify_login(tenant_env, "spaces_a@test.com")
        key_b = _signup_verify_login(tenant_env, "spaces_b@test.com")

        tenant_env.post("/v1/agents", json={"agent_id": "a1"}, headers=_auth(key_a))
        tenant_env.post("/v1/shared/private-space", json={
            "key": "data", "value": "x", "author_agent_id": "a1"
        }, headers=_auth(key_a))

        # Tenant A sees the space (spaces is a list of dicts with "name" key)
        resp = tenant_env.get("/v1/shared", headers=_auth(key_a))
        spaces = resp.json()["spaces"]
        space_names = [s["name"] if isinstance(s, dict) else s for s in spaces]
        assert "private-space" in space_names

        # Tenant B does not
        resp = tenant_env.get("/v1/shared", headers=_auth(key_b))
        spaces = resp.json()["spaces"]
        space_names = [s["name"] if isinstance(s, dict) else s for s in spaces]
        assert "private-space" not in space_names


# ---------------------------------------------------------------------------
# Tenant Isolation — Audit & Decisions
# ---------------------------------------------------------------------------

class TestTenantIsolationAudit:

    def test_audit_trail_isolated(self, tenant_env):
        """Tenant B cannot see Tenant A's audit trail."""
        key_a = _signup_verify_login(tenant_env, "audit_a@test.com")
        key_b = _signup_verify_login(tenant_env, "audit_b@test.com")

        # Tenant A logs a decision
        tenant_env.post("/v1/agents", json={"agent_id": "decider"}, headers=_auth(key_a))
        tenant_env.post("/v1/agents/decider/decision", json={
            "decision": "Use RAG", "reasoning": "Better accuracy"
        }, headers=_auth(key_a))

        # Tenant A sees it
        resp = tenant_env.get("/v1/agents/decider/audit", headers=_auth(key_a))
        assert resp.status_code == 200

        # Tenant B — agent doesn't exist in B's DB, returns empty events
        resp = tenant_env.get("/v1/agents/decider/audit", headers=_auth(key_b))
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_global_timeline_isolated(self, tenant_env):
        """Global audit timeline is per-tenant."""
        key_a = _signup_verify_login(tenant_env, "timeline_a@test.com")
        key_b = _signup_verify_login(tenant_env, "timeline_b@test.com")

        tenant_env.post("/v1/agents", json={"agent_id": "bot"}, headers=_auth(key_a))
        tenant_env.post("/v1/agents/bot/remember", json={
            "key": "x", "value": 1
        }, headers=_auth(key_a))

        # Tenant A timeline has events
        resp = tenant_env.get("/v1/audit/timeline", headers=_auth(key_a))
        assert resp.status_code == 200

        # Tenant B timeline is empty (no agents)
        resp = tenant_env.get("/v1/audit/timeline", headers=_auth(key_b))
        assert resp.status_code == 200
        assert len(resp.json().get("events", [])) == 0


# ---------------------------------------------------------------------------
# Tenant Isolation — Metrics
# ---------------------------------------------------------------------------

class TestTenantIsolationMetrics:

    def test_system_metrics_isolated(self, tenant_env):
        """System metrics reflect only the current tenant's data."""
        key_a = _signup_verify_login(tenant_env, "metrics_a@test.com")
        key_b = _signup_verify_login(tenant_env, "metrics_b@test.com")

        # Tenant A creates agent + writes
        tenant_env.post("/v1/agents", json={"agent_id": "counter"}, headers=_auth(key_a))
        for i in range(5):
            tenant_env.post("/v1/agents/counter/remember", json={
                "key": f"k{i}", "value": i
            }, headers=_auth(key_a))

        # Tenant B — no agents, metrics should reflect 0
        resp = tenant_env.get("/v1/metrics/system", headers=_auth(key_b))
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("active_agents", 0) == 0


# ---------------------------------------------------------------------------
# Tenant Isolation — Snapshots
# ---------------------------------------------------------------------------

class TestTenantIsolationSnapshots:

    def test_snapshots_isolated(self, tenant_env):
        """Tenant B cannot restore Tenant A's snapshot."""
        key_a = _signup_verify_login(tenant_env, "snap_a@test.com")
        key_b = _signup_verify_login(tenant_env, "snap_b@test.com")

        # Tenant A creates agent, writes data, snapshots
        tenant_env.post("/v1/agents", json={"agent_id": "snapper"}, headers=_auth(key_a))
        tenant_env.post("/v1/agents/snapper/remember", json={
            "key": "important", "value": "secret_data"
        }, headers=_auth(key_a))
        resp = tenant_env.post("/v1/agents/snapper/snapshot", json={
            "label": "backup_v1"
        }, headers=_auth(key_a))
        assert resp.status_code == 200

        # Tenant B tries to restore it
        tenant_env.post("/v1/agents", json={"agent_id": "snapper"}, headers=_auth(key_b))
        resp = tenant_env.post("/v1/agents/snapper/restore", json={
            "label": "backup_v1"
        }, headers=_auth(key_b))
        # Should either fail or restore 0 keys (no snapshot exists in B's DB)
        if resp.status_code == 200:
            assert resp.json().get("keys_restored", 0) == 0


# ---------------------------------------------------------------------------
# Tenant Isolation — Raw Operations
# ---------------------------------------------------------------------------

class TestTenantIsolationRaw:

    def test_raw_operations_isolated(self, tenant_env):
        """Raw read/write/query is tenant-isolated."""
        key_a = _signup_verify_login(tenant_env, "raw_a@test.com")
        key_b = _signup_verify_login(tenant_env, "raw_b@test.com")

        # Tenant A writes raw data
        tenant_env.post("/v1/raw/write", json={
            "key": "internal:config", "value": {"db_password": "hunter2"}
        }, headers=_auth(key_a))

        # Tenant A reads it
        resp = tenant_env.get("/v1/raw/read/internal:config", headers=_auth(key_a))
        assert resp.json()["found"] is True

        # Tenant B cannot
        resp = tenant_env.get("/v1/raw/read/internal:config", headers=_auth(key_b))
        assert resp.json()["found"] is False

    def test_raw_query_isolated(self, tenant_env):
        """Raw prefix query only returns current tenant's data."""
        key_a = _signup_verify_login(tenant_env, "rawq_a@test.com")
        key_b = _signup_verify_login(tenant_env, "rawq_b@test.com")

        tenant_env.post("/v1/raw/write", json={"key": "ns:x", "value": 1}, headers=_auth(key_a))
        tenant_env.post("/v1/raw/write", json={"key": "ns:y", "value": 2}, headers=_auth(key_a))

        resp = tenant_env.get("/v1/raw/query?prefix=ns:", headers=_auth(key_a))
        assert resp.json()["count"] == 2

        resp = tenant_env.get("/v1/raw/query?prefix=ns:", headers=_auth(key_b))
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Full E2E Flow — Complete User Journey
# ---------------------------------------------------------------------------

class TestFullE2EFlow:

    def test_complete_user_journey(self, tenant_env):
        """
        Full journey: signup → verify → login → register agent → write memories
        → recall → search → snapshot → list agents → metrics → audit.
        """
        # 1. Signup
        resp = _signup(tenant_env, "journey@test.com", password="Journey123!")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        tenant_id = data["tenant_id"]

        # 2. Verify email
        _verify_email("journey@test.com")

        # 3. Login
        api_key = _login(tenant_env, "journey@test.com", "Journey123!")
        h = _auth(api_key)

        # 4. Check account info
        resp = tenant_env.get("/v1/auth/me", headers=h)
        assert resp.status_code == 200
        assert "journey" in resp.json()["email"]

        # 5. Register agent
        resp = tenant_env.post("/v1/agents", json={
            "agent_id": "my-assistant", "agent_type": "chat"
        }, headers=h)
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == "my-assistant"

        # 6. Write memories
        for key, value in [("user:name", "Alice"), ("user:pref", "dark_mode"), ("context:topic", "AI")]:
            resp = tenant_env.post("/v1/agents/my-assistant/remember", json={
                "key": key, "value": value
            }, headers=h)
            assert resp.json()["success"] is True

        # 7. Recall (string values stored as {"value": "..."})
        resp = tenant_env.get("/v1/agents/my-assistant/recall/user:name", headers=h)
        assert resp.json()["found"] is True
        assert resp.json()["value"]["value"] == "Alice"

        # 8. Search
        resp = tenant_env.get("/v1/agents/my-assistant/search?prefix=user:", headers=h)
        assert resp.json()["count"] == 2

        # 9. List memories
        resp = tenant_env.get("/v1/agents/my-assistant/memory", headers=h)
        assert resp.json()["count"] == 3

        # 10. Snapshot
        resp = tenant_env.post("/v1/agents/my-assistant/snapshot", json={
            "label": "checkpoint_1"
        }, headers=h)
        assert resp.status_code == 200
        assert resp.json()["keys_captured"] >= 3

        # 11. Log decision
        resp = tenant_env.post("/v1/agents/my-assistant/decision", json={
            "decision": "Switch to RAG",
            "reasoning": "User asked complex domain question",
        }, headers=h)
        assert resp.json()["logged"] is True

        # 12. Audit trail
        resp = tenant_env.get("/v1/agents/my-assistant/audit", headers=h)
        assert resp.status_code == 200

        # 13. List agents
        resp = tenant_env.get("/v1/agents", headers=h)
        assert resp.json()["total"] == 1
        assert resp.json()["agents"][0]["agent_id"] == "my-assistant"

        # 14. Agent metrics
        resp = tenant_env.get("/v1/agents/my-assistant/metrics", headers=h)
        assert resp.status_code == 200

        # 15. System metrics
        resp = tenant_env.get("/v1/metrics/system", headers=h)
        assert resp.status_code == 200

        # 16. Usage
        resp = tenant_env.get("/v1/usage", headers=h)
        assert resp.status_code == 200

    def test_two_tenants_full_isolation(self, tenant_env):
        """
        Two tenants do everything — register agents, write memories,
        shared memory, raw ops — then verify ZERO data leakage.
        """
        key_a = _signup_verify_login(tenant_env, "full_a@test.com")
        key_b = _signup_verify_login(tenant_env, "full_b@test.com")
        h_a = _auth(key_a)
        h_b = _auth(key_b)

        # --- Tenant A: set up everything ---
        tenant_env.post("/v1/agents", json={"agent_id": "agent-1"}, headers=h_a)
        tenant_env.post("/v1/agents", json={"agent_id": "agent-2"}, headers=h_a)
        tenant_env.post("/v1/agents/agent-1/remember", json={"key": "secret", "value": "A_data"}, headers=h_a)
        tenant_env.post("/v1/agents/agent-1/remember/batch", json={
            "items": [{"key": f"batch:{i}", "value": f"val_{i}"} for i in range(5)]
        }, headers=h_a)
        tenant_env.post("/v1/shared/workspace", json={
            "key": "plan", "value": "launch_v2", "author_agent_id": "agent-1"
        }, headers=h_a)
        tenant_env.post("/v1/raw/write", json={"key": "internal:key", "value": "sensitive"}, headers=h_a)
        tenant_env.post("/v1/agents/agent-1/decision", json={
            "decision": "test", "reasoning": "test"
        }, headers=h_a)

        # --- Tenant B: set up their own stuff ---
        tenant_env.post("/v1/agents", json={"agent_id": "b-bot"}, headers=h_b)
        tenant_env.post("/v1/agents/b-bot/remember", json={"key": "own_data", "value": "B_data"}, headers=h_b)

        # --- Verify isolation from Tenant B's perspective ---

        # B sees only 1 agent
        resp = tenant_env.get("/v1/agents", headers=h_b)
        assert resp.json()["total"] == 1
        assert resp.json()["agents"][0]["agent_id"] == "b-bot"

        # B cannot see A's agent details
        resp = tenant_env.get("/v1/agents/agent-1", headers=h_b)
        assert resp.status_code == 404

        # B cannot recall A's memories (even with same agent name)
        tenant_env.post("/v1/agents", json={"agent_id": "agent-1"}, headers=h_b)
        resp = tenant_env.get("/v1/agents/agent-1/recall/secret", headers=h_b)
        assert resp.json()["found"] is False

        # B's search doesn't find A's batch data
        resp = tenant_env.get("/v1/agents/agent-1/search?prefix=batch:", headers=h_b)
        assert resp.json()["count"] == 0

        # B cannot read A's shared memory
        resp = tenant_env.get("/v1/shared/workspace/plan", headers=h_b)
        assert resp.json()["found"] is False

        # B cannot read A's raw data
        resp = tenant_env.get("/v1/raw/read/internal:key", headers=h_b)
        assert resp.json()["found"] is False

        # --- Verify Tenant A still has everything ---
        resp = tenant_env.get("/v1/agents", headers=h_a)
        assert resp.json()["total"] == 2

        resp = tenant_env.get("/v1/agents/agent-1/recall/secret", headers=h_a)
        assert resp.json()["value"]["value"] == "A_data"

        resp = tenant_env.get("/v1/agents/agent-1/search?prefix=batch:", headers=h_a)
        assert resp.json()["count"] == 5
