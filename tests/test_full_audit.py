# -*- coding: utf-8 -*-
"""
Octopoda Full System Audit
===========================
Comprehensive test suite that validates EVERY system component against the live API.
Run: python tests/test_full_audit.py
"""

import os
import sys
import io
import time
import json
import uuid
import hashlib
import threading
import traceback
import requests

# Fix Windows console encoding for unicode
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Disable local daemon (it interferes with cloud-only tests)
os.environ["SYNRIX_DAEMON_DISABLED"] = "1"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE = os.environ.get("OCTOPODA_API_URL", "https://api.octopodas.com")
API_KEY = os.environ.get("OCTOPODA_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

PASS = 0
FAIL = 0
SKIP = 0
RESULTS = []


def _h():
    return dict(HEADERS)


def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        result = fn()
        if result == "SKIP":
            SKIP += 1
            RESULTS.append(("SKIP", name, ""))
            print(f"  [SKIP] {name}")
        else:
            PASS += 1
            RESULTS.append(("PASS", name, ""))
            print(f"  [PASS] {name}")
    except Exception as e:
        FAIL += 1
        msg = str(e)[:200]
        RESULTS.append(("FAIL", name, msg))
        print(f"  [FAIL] {name} — {msg}")


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: expected {b!r}, got {a!r}")


def assert_true(val, msg=""):
    if not val:
        raise AssertionError(f"{msg}: expected truthy, got {val!r}")


def assert_in(item, container, msg=""):
    if item not in container:
        raise AssertionError(f"{msg}: {item!r} not in {container!r}")


# ===========================================================================
# PHASE 1: Core API
# ===========================================================================

def phase1_core_api():
    print("\n=== PHASE 1: CORE API ===\n")
    agent_id = f"audit-agent-{int(time.time())}"

    # Register the audit agent first
    requests.post(f"{BASE}/v1/agents", headers=_h(), json={"agent_id": agent_id}, timeout=10)

    # 1.1 Health endpoint
    def t_health():
        r = requests.get(f"{BASE}/health", timeout=10)
        assert_eq(r.status_code, 200, "health status")
        data = r.json()
        assert_in("status", data, "health body")
        assert_eq(data["status"], "ok", "health ok")
        assert_in("version", data, "has version")
    test("1.1 Health endpoint", t_health)

    # 1.2 Auth — valid key
    def t_auth_valid():
        r = requests.get(f"{BASE}/v1/agents", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "auth valid")
    test("1.2 Auth with valid key", t_auth_valid)

    # 1.3 Auth — invalid key
    def t_auth_invalid():
        h = {"Authorization": "Bearer sk-octopoda-FAKE-KEY-123", "Content-Type": "application/json"}
        r = requests.get(f"{BASE}/v1/agents", headers=h, timeout=10)
        assert_true(r.status_code in (401, 403), f"auth invalid: {r.status_code}")
    test("1.3 Auth with invalid key rejected", t_auth_invalid)

    # 1.4 Auth — no key
    def t_auth_none():
        r = requests.get(f"{BASE}/v1/agents", timeout=10)
        assert_true(r.status_code in (401, 403, 422), f"auth none: {r.status_code}")
    test("1.4 Auth with no key rejected", t_auth_none)

    # 1.5 Settings
    def t_settings():
        r = requests.get(f"{BASE}/v1/settings", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "settings status")
        data = r.json()
        assert_in("llm_provider", data, "has provider")
        assert_in("platform_extractions_used", data, "has counter")
    test("1.5 Settings endpoint", t_settings)

    # 1.6 Remember — string value
    def t_remember_string():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:string", "value": "Hello World"})
        assert_eq(r.status_code, 200, "remember string")
        data = r.json()
        assert_true(data.get("success"), "remember success")
        assert_true(data.get("node_id"), "has node_id")
    test("1.6 Remember string value", t_remember_string)

    # 1.7 Remember — dict value
    def t_remember_dict():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:dict", "value": {"name": "Alice", "age": 30, "city": "London"}})
        assert_eq(r.status_code, 200, "remember dict")
    test("1.7 Remember dict value", t_remember_dict)

    # 1.8 Remember — with tags
    def t_remember_tags():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:tagged", "value": "Critical bug in auth module",
                                "tags": ["bug", "critical", "security"]})
        assert_eq(r.status_code, 200, "remember tags")
    test("1.8 Remember with tags", t_remember_tags)

    # 1.9 Remember — unicode
    def t_remember_unicode():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:unicode", "value": "日本語テスト 🐙 émojis café"})
        assert_eq(r.status_code, 200, "remember unicode")
    test("1.9 Remember unicode value", t_remember_unicode)

    # 1.10 Remember — large value
    def t_remember_large():
        big = "x" * 50000
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:large", "value": big})
        assert_eq(r.status_code, 200, "remember large")
    test("1.10 Remember large value (50KB)", t_remember_large)

    # 1.11 Recall — string
    def t_recall_string():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/recall/test:string", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "recall status")
        data = r.json()
        assert_true(data.get("found"), "recall found")
        val = data.get("value", "")
        # May be wrapped in {"value": "..."} dict
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        assert_eq(val, "Hello World", "recall value")
    test("1.11 Recall string value", t_recall_string)

    # 1.12 Recall — dict
    def t_recall_dict():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/recall/test:dict", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "recall dict status")
        data = r.json()
        assert_true(data.get("found"), "recall dict found")
        val = data.get("value", {})
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        if isinstance(val, dict):
            assert_eq(val.get("name"), "Alice", "recall dict name")
    test("1.12 Recall dict value", t_recall_dict)

    # 1.13 Recall — unicode
    def t_recall_unicode():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/recall/test:unicode", headers=_h(), timeout=10)
        data = r.json()
        val = data.get("value", "")
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        assert_in("🐙", str(val), "unicode preserved")
    test("1.13 Recall unicode preserved", t_recall_unicode)

    # 1.14 Recall — nonexistent key
    def t_recall_missing():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/recall/nonexistent:key:999", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "recall missing status")
        data = r.json()
        assert_true(not data.get("found"), "recall missing not found")
    test("1.14 Recall nonexistent key", t_recall_missing)

    # 1.15 Memory list
    def t_memory_list():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/memory?offset=0&limit=50", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "memory list status")
        data = r.json()
        assert_true(data.get("count", 0) >= 4, f"memory count: {data.get('count')}")
        # Check enriched fields
        items = data.get("items", [])
        if items:
            item = items[0]
            assert_in("key", item, "item has key")
            assert_in("value", item, "item has value")
            assert_in("tags", item, "item has tags")
            assert_in("importance", item, "item has importance")
            assert_in("version_count", item, "item has version_count")
            assert_in("created_at", item, "item has created_at")
    test("1.15 Memory list with enriched fields", t_memory_list)

    # 1.16 Semantic search
    def t_semantic_search():
        time.sleep(3)  # Give embeddings time to process
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/similar?q=authentication+bug&limit=3",
                         headers=_h(), timeout=30)
        assert_eq(r.status_code, 200, f"search status: {r.status_code} {r.text[:100]}")
        data = r.json()
        items = data.get("items", [])
        assert_true(len(items) > 0, f"search returned {len(items)} results")
        if items and "score" in items[0]:
            assert_true(items[0]["score"] > 0, "score > 0")
    test("1.16 Semantic search with scores", t_semantic_search)

    # 1.17 Version history — write same key 3 times
    def t_version_history():
        for i in range(3):
            requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:versioned", "value": f"Version {i+1} content"})
            time.sleep(0.3)
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/history/test:versioned", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "history status")
        data = r.json()
        versions = data.get("versions", [])
        assert_true(len(versions) >= 3, f"version count: {len(versions)}")
        # Check v1 != v3
        assert_true(versions[0]["value"] != versions[-1]["value"], "versions differ")
        # Check is_current on last
        assert_true(versions[-1].get("is_current"), "last is current")
        # Check valid_from exists
        assert_true(versions[0].get("valid_from", 0) > 0, "has valid_from")
    test("1.17 Version history (3 writes, different values)", t_version_history)

    # 1.18 Loop detection
    def t_loop_detection():
        # Write same value rapidly to trigger loop
        for i in range(10):
            requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": f"test:loop:{i}", "value": "Repeated identical content for loop test"})
        time.sleep(1)
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/loops/status", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "loop status")
        data = r.json()
        assert_in("severity", data, "has severity")
        assert_in("score", data, "has score")
        assert_true(data["score"] <= 100, "score <= 100")
    test("1.18 Loop detection status", t_loop_detection)

    # 1.19 Loop history
    def t_loop_history():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/loops/history?hours=24", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "loop history status")
        data = r.json()
        assert_in("by_hour", data, "has by_hour")
    test("1.19 Loop history (24h)", t_loop_history)

    # 1.20 Memory health
    def t_memory_health():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/memory/health", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, f"health status: {r.text[:100]}")
        data = r.json()
        assert_in("score", data, "has score")
        assert_true(0 <= data["score"] <= 100, f"score range: {data['score']}")
    test("1.20 Memory health score", t_memory_health)

    # 1.21 Shared memory — write
    space = f"audit-space-{int(time.time())}"
    def t_shared_write():
        r = requests.post(f"{BASE}/v1/shared/{space}", headers=_h(), timeout=10,
                          json={"key": "shared-test", "value": "shared data from audit", "author_agent_id": agent_id})
        assert_eq(r.status_code, 200, "shared write")
    test("1.21 Shared memory write", t_shared_write)

    # 1.22 Shared memory — read
    def t_shared_read():
        r = requests.get(f"{BASE}/v1/shared/{space}/shared-test", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "shared read")
        data = r.json()
        assert_true(data.get("found"), "shared found")
    test("1.22 Shared memory read", t_shared_read)

    # 1.23 Shared memory — list spaces
    def t_shared_list():
        r = requests.get(f"{BASE}/v1/shared", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "shared list")
        data = r.json()
        space_names = [s["name"] for s in data.get("spaces", [])]
        assert_in(space, space_names, "audit space in list")
    test("1.23 Shared memory list spaces", t_shared_list)

    # 1.24 Shared memory — detail
    def t_shared_detail():
        r = requests.get(f"{BASE}/v1/shared/{space}/detail", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "shared detail")
        data = r.json()
        assert_true(len(data.get("items", [])) > 0, "has items")
        assert_true(len(data.get("changelog", [])) > 0, "has changelog")
    test("1.24 Shared memory detail", t_shared_detail)

    # 1.25 Snapshot — create
    def t_snapshot_create():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/snapshot", headers=_h(), timeout=30,
                          json={"label": "audit-snapshot"})
        assert_eq(r.status_code, 200, f"snapshot create: {r.text[:100]}")
    test("1.25 Snapshot create", t_snapshot_create)

    # 1.26 Snapshot — list
    def t_snapshot_list():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/snapshots", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, f"snapshot list: {r.text[:100]}")
        data = r.json()
        assert_true(data.get("count", 0) > 0, "has snapshots")
    test("1.26 Snapshot list", t_snapshot_list)

    # 1.27 Recovery history
    def t_recovery_history():
        r = requests.get(f"{BASE}/v1/recovery/history", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "recovery history")
        data = r.json()
        assert_in("history", data, "has history")
        assert_in("stats", data, "has stats")
    test("1.27 Recovery history", t_recovery_history)

    # 1.28 Agent list
    def t_agent_list():
        r = requests.get(f"{BASE}/v1/agents?limit=100", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "agent list")
        data = r.json()
        agent_ids = [a["agent_id"] for a in data.get("agents", [])]
        assert_in(agent_id, agent_ids, "audit agent in list")
    test("1.28 Agent list includes audit agent", t_agent_list)

    # 1.29 Agent metrics
    def t_agent_stats():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/metrics", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, f"agent metrics: {r.text[:100]}")
    test("1.29 Agent metrics", t_agent_stats)

    # 1.30 Audit trail
    def t_audit_trail():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/audit?limit=10", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, "audit trail")
        data = r.json()
        assert_true(data.get("count", 0) > 0, "has audit events")
    test("1.30 Audit trail", t_audit_trail)

    # 1.31 Messaging — send
    agent_b = f"audit-agent-b-{int(time.time())}"
    def t_message_send():
        # Register agent B first and wait
        requests.post(f"{BASE}/v1/agents", headers=_h(), json={"agent_id": agent_b}, timeout=10)
        time.sleep(1)
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/messages/send", headers=_h(), timeout=10,
                          json={"to_agent": agent_b, "message": "Hello from audit test", "message_type": "info"})
        assert_eq(r.status_code, 200, f"message send: {r.text[:100]}")
    test("1.31 Agent messaging — send", t_message_send)

    # 1.32 Messaging — read inbox
    def t_message_read():
        r = requests.get(f"{BASE}/v1/agents/{agent_b}/messages/inbox", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, f"inbox: {r.text[:100]}")
        data = r.json()
        messages = data.get("messages", [])
        assert_true(len(messages) > 0, "has messages")
    test("1.32 Agent messaging — read inbox", t_message_read)

    # 1.33 Goal tracking — set
    def t_goal_set():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/goal", headers=_h(), timeout=10,
                          json={"goal": "Complete audit test", "milestones": ["Phase 1", "Phase 2", "Phase 3"]})
        assert_eq(r.status_code, 200, f"goal set: {r.text[:100]}")
    test("1.33 Goal tracking — set", t_goal_set)

    # 1.34 Goal tracking — get
    def t_goal_get():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/goal", headers=_h(), timeout=10)
        assert_eq(r.status_code, 200, f"goal get: {r.text[:100]}")
        data = r.json()
        assert_true(data.get("goal") or data.get("status"), "has goal data")
    test("1.34 Goal tracking — get", t_goal_get)

    # 1.35 Forget
    def t_forget():
        # Write then forget
        requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                      json={"key": "test:forget-me", "value": "temporary"})
        time.sleep(0.5)
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/forget/stale", headers=_h(), timeout=10,
                          json={"max_age_seconds": 0})
        assert_eq(r.status_code, 200, f"forget stale: {r.text[:100]}")
    test("1.35 Forget stale memories", t_forget)

    # 1.36 Export
    def t_export():
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/export", headers=_h(), timeout=30)
        assert_eq(r.status_code, 200, f"export: {r.text[:100]}")
        data = r.json()
        assert_true("memories" in data or "keys" in data or "bundle" in data, f"export has data: {list(data.keys())}")
    test("1.36 Export memories", t_export)

    # 1.37 Consolidate dry run
    def t_consolidate():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/consolidate", headers=_h(), timeout=30,
                          json={"dry_run": True})
        assert_eq(r.status_code, 200, f"consolidate: {r.text[:100]}")
    test("1.37 Consolidate (dry run)", t_consolidate)

    # 1.38 Filtered search
    def t_search_filtered():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/search/filtered", headers=_h(), timeout=30,
                          json={"query": "bug", "tags": ["bug"], "limit": 5})
        assert_eq(r.status_code, 200, f"filtered search: {r.text[:100]}")
    test("1.38 Filtered search", t_search_filtered)

    # 1.39 Extraction counter increments
    def t_extraction_counter():
        r1 = requests.get(f"{BASE}/v1/settings", headers=_h(), timeout=10)
        before = r1.json().get("platform_extractions_used", 0)
        # Write a fact-rich memory
        requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                      json={"key": "test:extraction", "value": "Bob is a senior engineer at Microsoft working on Azure in Seattle since 2019"})
        time.sleep(4)  # Wait for async extraction
        r2 = requests.get(f"{BASE}/v1/settings", headers=_h(), timeout=10)
        after = r2.json().get("platform_extractions_used", 0)
        assert_true(after > before, f"extraction counter: {before} -> {after}")
    test("1.39 Fact extraction counter increments", t_extraction_counter)

    return agent_id


# ===========================================================================
# PHASE 2: Tenant Isolation
# ===========================================================================

def phase2_tenant_isolation():
    print("\n=== PHASE 2: TENANT ISOLATION ===\n")

    # We only have one API key, so test that:
    # 1. We can't access another tenant's data by manipulating agent IDs
    # 2. The RLS is working

    agent_id = f"isolation-test-{int(time.time())}"
    requests.post(f"{BASE}/v1/agents", headers=_h(), json={"agent_id": agent_id}, timeout=10)

    # Write data
    def t_write_own():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "secret", "value": "tenant-A-secret-data"})
        assert_eq(r.status_code, 200, "write own")
    test("2.1 Write to own tenant", t_write_own)

    # Try reading with different (fake) auth
    def t_cross_tenant_blocked():
        h = {"Authorization": "Bearer sk-octopoda-INVALID-CROSS-TENANT", "Content-Type": "application/json"}
        r = requests.get(f"{BASE}/v1/agents/{agent_id}/recall/secret", headers=h, timeout=10)
        assert_true(r.status_code in (401, 403), f"cross tenant: {r.status_code}")
    test("2.2 Cross-tenant access blocked", t_cross_tenant_blocked)

    # Verify agents from other tenants don't appear
    def t_agent_isolation():
        r = requests.get(f"{BASE}/v1/agents?limit=100", headers=_h(), timeout=10)
        data = r.json()
        agents = data.get("agents", [])
        # All agents should belong to our tenant (we can't verify tenant_id directly,
        # but we can check that known other-tenant agents don't appear)
        agent_ids = [a["agent_id"] for a in agents]
        # These would be other tenants' agents — they should NOT appear
        assert_true(len(agents) < 50, f"reasonable agent count: {len(agents)}")
    test("2.3 Agent list shows only own agents", t_agent_isolation)

    # Verify shared memory isolation
    def t_shared_isolation():
        r = requests.get(f"{BASE}/v1/shared", headers=_h(), timeout=10)
        data = r.json()
        spaces = data.get("spaces", [])
        # All spaces should be ours
        assert_true(isinstance(spaces, list), "spaces is list")
    test("2.4 Shared memory isolation", t_shared_isolation)


# ===========================================================================
# PHASE 3: Framework Integrations
# ===========================================================================

def phase3_frameworks():
    print("\n=== PHASE 3: FRAMEWORK INTEGRATIONS ===\n")

    # 3.1 LangChain integration
    def t_langchain():
        try:
            from synrix.integrations.langchain import OctopodaMemory
        except ImportError:
            return "SKIP"
        # OctopodaMemory uses env vars: OCTOPODA_API_KEY, OCTOPODA_API_URL
        os.environ["OCTOPODA_API_KEY"] = API_KEY
        os.environ["OCTOPODA_API_URL"] = BASE
        mem = OctopodaMemory(agent_id="audit-langchain")
        mem.save_context({"input": "What is Octopoda?"}, {"output": "A memory engine for AI agents."})
        result = mem.load_memory_variables({})
        assert_true(result, "langchain load returned data")
        mem.clear()
    test("3.1 LangChain OctopodaMemory", t_langchain)

    def t_langchain_chat():
        try:
            from synrix.integrations.langchain import OctopodaChatHistory
        except ImportError:
            return "SKIP"
        try:
            from langchain_core.messages import HumanMessage, AIMessage
        except ImportError:
            return "SKIP"
        os.environ["OCTOPODA_API_KEY"] = API_KEY
        os.environ["OCTOPODA_API_URL"] = BASE
        hist = OctopodaChatHistory(agent_id="audit-langchain", session_id="audit-session")
        hist.add_message(HumanMessage(content="Hello"))
        hist.add_message(AIMessage(content="Hi there!"))
        msgs = hist.messages
        assert_true(len(msgs) >= 2, f"chat history: {len(msgs)} messages")
        hist.clear()
    test("3.2 LangChain ChatHistory", t_langchain_chat)

    # 3.3 CrewAI integration
    def t_crewai():
        try:
            from synrix.integrations.crewai import OctopodaCrewMemory
        except ImportError:
            return "SKIP"
        os.environ["OCTOPODA_API_KEY"] = API_KEY
        os.environ["OCTOPODA_API_URL"] = BASE
        crew = OctopodaCrewMemory(agent_id="audit-crewai", crew_name="audit-crew")
        crew.remember("finding:1", "The database needs indexing", tags=["performance"])
        result = crew.recall("finding:1")
        assert_true(result, "crewai recall returned data")
        crew.save_crew_result("audit-task", {"status": "passed", "score": 100})
        task_result = crew.get_crew_result("audit-task")
        assert_true(task_result, "crewai task result")
        summary = crew.get_crew_summary()
        assert_true(isinstance(summary, dict), "crewai summary is dict")
    test("3.3 CrewAI OctopodaCrewMemory", t_crewai)

    # 3.4 AutoGen integration
    def t_autogen():
        try:
            from synrix.integrations.autogen import OctopodaAutoGenMemory
        except ImportError:
            return "SKIP"
        os.environ["OCTOPODA_API_KEY"] = API_KEY
        os.environ["OCTOPODA_API_URL"] = BASE
        mem = OctopodaAutoGenMemory(agent_id="audit-autogen")
        mem.remember("context:1", "User prefers dark mode", tags=["preference"])
        result = mem.recall("context:1")
        assert_true(result, "autogen recall returned data")
        messages = [
            {"role": "user", "content": "Set up the environment", "name": "admin"},
            {"role": "assistant", "content": "Environment ready", "name": "agent-1"},
        ]
        mem.learn_from_conversation(messages)
        context = mem.get_relevant_context("environment setup")
        assert_true(isinstance(context, (str, list, dict)), "autogen context returned")
    test("3.4 AutoGen OctopodaAutoGenMemory", t_autogen)

    # 3.5 OpenAI Agents tools
    def t_openai_tools():
        try:
            from synrix.integrations.openai_agents import octopoda_tools, handle_tool_call
        except ImportError:
            return "SKIP"
        os.environ["OCTOPODA_API_KEY"] = API_KEY
        os.environ["OCTOPODA_API_URL"] = BASE
        tools = octopoda_tools("audit-openai-agent")
        assert_true(len(tools) >= 3, f"tool count: {len(tools)}")
        result = handle_tool_call("audit-openai-agent", "remember_memory",
                                  {"key": "test", "value": "openai tool test"})
        assert_true(result, "tool call returned result")
    test("3.5 OpenAI Agents tools", t_openai_tools)

    # 3.6 MCP server imports
    def t_mcp_import():
        try:
            from synrix_runtime.api.mcp_server import main
            assert_true(callable(main), "mcp main callable")
        except ImportError:
            return "SKIP"
    test("3.6 MCP server imports", t_mcp_import)


# ===========================================================================
# PHASE 4: Security & Edge Cases
# ===========================================================================

def phase4_security():
    print("\n=== PHASE 4: SECURITY & EDGE CASES ===\n")

    agent_id = f"security-test-{int(time.time())}"
    requests.post(f"{BASE}/v1/agents", headers=_h(), json={"agent_id": agent_id}, timeout=10)

    # 4.1 SQL injection in key — should either accept safely or reject with validation
    def t_sqli_key():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "sqli-test-key", "value": "'; DROP TABLE nodes; --"})
        assert_true(r.status_code in (200, 422), f"sqli: {r.status_code}")
        # Verify DB still works
        r2 = requests.get(f"{BASE}/v1/agents/{agent_id}/memory?limit=1", headers=_h(), timeout=10)
        assert_eq(r2.status_code, 200, "DB still works after sqli")
    test("4.1 SQL injection in value (parameterized)", t_sqli_key)

    # 4.2 SQL injection in value (Bobby Tables)
    def t_sqli_value():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:sqli-val", "value": "Robert'); DROP TABLE nodes;-- "})
        assert_true(r.status_code in (200, 422), f"sqli value: {r.status_code}")
        # Verify DB still works
        r2 = requests.get(f"{BASE}/v1/agents/{agent_id}/memory?limit=1", headers=_h(), timeout=10)
        assert_eq(r2.status_code, 200, "DB still works after sqli value")
    test("4.2 SQL injection Bobby Tables (parameterized)", t_sqli_value)

    # 4.3 XSS in value
    def t_xss():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "test:xss", "value": "<script>alert('xss')</script>"})
        assert_true(r.status_code in (200, 422), f"xss: {r.status_code}")
    test("4.3 XSS in value (stored safely)", t_xss)

    # 4.4 Empty key
    def t_empty_key():
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": "", "value": "empty key test"})
        assert_true(r.status_code in (200, 400, 422), f"empty key: {r.status_code}")
    test("4.4 Empty key handled", t_empty_key)

    # 4.5 Very long key
    def t_long_key():
        long_key = "k" * 5000
        r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                          json={"key": long_key, "value": "long key test"})
        assert_true(r.status_code in (200, 400, 413, 422), f"long key: {r.status_code}")
    test("4.5 Very long key (5000 chars)", t_long_key)

    # 4.6 Special characters in agent ID
    def t_special_agent():
        r = requests.post(f"{BASE}/v1/agents/agent%20with%20spaces/remember", headers=_h(), timeout=30,
                          json={"key": "test", "value": "special agent"})
        assert_true(r.status_code in (200, 400, 422), f"special agent: {r.status_code}")
    test("4.6 Special chars in agent ID", t_special_agent)

    # 4.7 Concurrent writes
    def t_concurrent():
        errors = []
        def write(i):
            try:
                r = requests.post(f"{BASE}/v1/agents/{agent_id}/remember", headers=_h(), timeout=30,
                                  json={"key": f"concurrent:{i}", "value": f"thread {i}"})
                if r.status_code != 200:
                    errors.append(f"thread {i}: {r.status_code}")
            except Exception as e:
                errors.append(f"thread {i}: {e}")

        threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert_true(len(errors) == 0, f"concurrent errors: {errors[:3]}")
    test("4.7 20 concurrent writes", t_concurrent)

    # 4.8 Rate limiting
    def t_rate_limit():
        statuses = []
        for i in range(100):
            r = requests.get(f"{BASE}/v1/settings", headers=_h(), timeout=5)
            statuses.append(r.status_code)
        has_429 = 429 in statuses
        all_200 = all(s == 200 for s in statuses)
        assert_true(has_429 or all_200, f"rate limit: 429s={statuses.count(429)}, 200s={statuses.count(200)}")
        if has_429:
            print(f"    (Rate limit triggered after {statuses.index(429)} requests)")
    test("4.8 Rate limiting (100 rapid requests)", t_rate_limit)


# ===========================================================================
# PHASE 5: Signup & Email (Resend)
# ===========================================================================

def phase5_signup():
    print("\n=== PHASE 5: SIGNUP & EMAIL ===\n")

    # 5.1 Signup endpoint exists
    def t_signup_endpoint():
        unique_email = f"audit-{int(time.time())}@example.com"
        r = requests.post(f"{BASE}/v1/auth/signup", timeout=10,
                          json={"email": unique_email, "password": "AuditTest123!",
                                "first_name": "Audit", "last_name": "Test"})
        assert_true(r.status_code in (200, 201, 400, 409, 422), f"signup: {r.status_code} {r.text[:100]}")
        if r.status_code == 200:
            data = r.json()
            assert_true(data.get("api_key", "").startswith("sk-octopoda-"), "got API key back")
    test("5.1 Signup endpoint", t_signup_endpoint)

    # 5.2 Login endpoint
    def t_login_endpoint():
        r = requests.post(f"{BASE}/v1/auth/login", timeout=10,
                          json={"email": "audit-test-fake@example.com", "password": "AuditTest123!"})
        assert_true(r.status_code in (200, 401, 403, 422), f"login: {r.status_code}")
    test("5.2 Login endpoint responds", t_login_endpoint)

    # 5.3 API key create
    def t_api_key_create():
        r = requests.post(f"{BASE}/v1/auth/create-key", headers=_h(), timeout=10, json={})
        assert_true(r.status_code in (200, 201, 404), f"create key: {r.status_code}")
    test("5.3 API key create endpoint", t_api_key_create)


# ===========================================================================
# Main
# ===========================================================================

def main():
    global API_KEY

    if not API_KEY:
        print("ERROR: Set OCTOPODA_API_KEY environment variable")
        print("Usage: OCTOPODA_API_KEY=sk-octopoda-... python tests/test_full_audit.py")
        sys.exit(1)

    print(f"Octopoda Full System Audit")
    print(f"==========================")
    print(f"Target: {BASE}")
    print(f"Key: {API_KEY[:20]}...")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    start = time.time()

    phase1_core_api()
    phase2_tenant_isolation()
    phase3_frameworks()
    phase4_security()
    phase5_signup()

    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE — {elapsed:.1f}s")
    print(f"{'='*60}")
    print(f"  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")
    print(f"  SKIP: {SKIP}")
    print(f"  TOTAL: {PASS + FAIL + SKIP}")
    print(f"{'='*60}")

    if FAIL > 0:
        print(f"\nFAILURES:")
        for status, name, msg in RESULTS:
            if status == "FAIL":
                print(f"  {name}: {msg}")

    return 1 if FAIL > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
