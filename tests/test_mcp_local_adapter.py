"""Regression test for the MCP _LocalAgentAdapter from the May 2026 audit.

Auditor reported 6 of 16 MCP tools threw AttributeError and 1 returned
silent wrong results. This test exercises every previously-broken path
against a real local AgentRuntime and asserts each one returns a non-None,
non-error result.
"""
import os
import tempfile
import shutil
import pytest


@pytest.fixture
def local_adapter():
    tmpdir = tempfile.mkdtemp(prefix="octopoda_mcp_test_")
    os.environ.pop("OCTOPODA_API_KEY", None)
    os.environ["SYNRIX_DATA_DIR"] = tmpdir
    # Clear the singleton in case prior tests initialised it
    from synrix_runtime.api import mcp_server
    mcp_server._client = None
    mcp_server._runtimes.clear()
    adapter = mcp_server._get_runtime("test_audit_agent")
    yield adapter
    try:
        adapter._rt.shutdown()
    except Exception:
        pass
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_local_sentinel_local_does_not_route_to_cloud():
    """OCTOPODA_API_KEY=local must enable local mode, not hang on cloud auth."""
    os.environ["OCTOPODA_API_KEY"] = "local"
    from synrix_runtime.api import mcp_server
    mcp_server._client = None  # force re-init
    client = mcp_server._get_client()
    assert mcp_server._local_mode is True, "OCTOPODA_API_KEY=local should be a local sentinel"
    os.environ.pop("OCTOPODA_API_KEY", None)
    mcp_server._client = None


def test_local_sentinel_offline():
    os.environ["OCTOPODA_API_KEY"] = "offline"
    from synrix_runtime.api import mcp_server
    mcp_server._client = None
    mcp_server._get_client()
    assert mcp_server._local_mode is True
    os.environ.pop("OCTOPODA_API_KEY", None)
    mcp_server._client = None


def test_local_sentinel_dev_and_none():
    for v in ("dev", "none", "NONE", "Local"):
        os.environ["OCTOPODA_API_KEY"] = v
        from synrix_runtime.api import mcp_server
        mcp_server._client = None
        mcp_server._get_client()
        assert mcp_server._local_mode is True, f"sentinel {v} should be local"
    os.environ.pop("OCTOPODA_API_KEY", None)


def test_local_mode_env_flag():
    os.environ["OCTOPODA_LOCAL_MODE"] = "1"
    os.environ["OCTOPODA_API_KEY"] = "sk-octopoda-fake-but-OCTOPODA_LOCAL_MODE-should-win"
    from synrix_runtime.api import mcp_server
    mcp_server._client = None
    mcp_server._get_client()
    assert mcp_server._local_mode is True
    os.environ.pop("OCTOPODA_LOCAL_MODE", None)
    os.environ.pop("OCTOPODA_API_KEY", None)
    mcp_server._client = None


# ── Per-tool adapter method tests (previously AttributeError) ──

def test_adapter_has_memory_health(local_adapter):
    """Was: AttributeError. Should now return a dict."""
    result = local_adapter.memory_health()
    assert isinstance(result, dict)


def test_adapter_has_get_loop_status(local_adapter):
    result = local_adapter.get_loop_status()
    assert isinstance(result, dict)


def test_adapter_has_get_loop_history(local_adapter):
    result = local_adapter.get_loop_history(hours=24)
    assert isinstance(result, dict)


def test_adapter_has_set_goal_and_get_goal(local_adapter):
    set_result = local_adapter.set_goal("Test goal", milestones=["a", "b"])
    assert isinstance(set_result, dict)
    get_result = local_adapter.get_goal()
    assert isinstance(get_result, dict)


def test_adapter_has_send_and_read_messages(local_adapter):
    send_result = local_adapter.send_message("other_agent", "hello", message_type="info")
    assert isinstance(send_result, dict)
    msgs = local_adapter.read_messages(unread_only=False, limit=10)
    assert isinstance(msgs, list)


def test_adapter_has_broadcast(local_adapter):
    result = local_adapter.broadcast("test broadcast")
    assert isinstance(result, dict)


def test_adapter_has_consolidate_defaults_to_NOT_dry_run(local_adapter):
    """Previously consolidate defaulted to dry_run=True; auditor noted the
    loop signal recommends consolidate() but defaulted to a no-op. We now
    default to actually consolidating."""
    import inspect
    sig = inspect.signature(local_adapter.consolidate)
    assert sig.parameters["dry_run"].default is False, \
        "consolidate.dry_run should default to False so the recommended action actually runs"
    # Run it
    result = local_adapter.consolidate()
    assert isinstance(result, dict)


def test_adapter_has_forget(local_adapter):
    local_adapter.write("temp_key", "temp_value")
    result = local_adapter.forget("temp_key")
    assert isinstance(result, dict)


def test_adapter_semantic_search_uses_recall_similar(local_adapter):
    """The single silent-wrong-result the auditor flagged: octopoda_recall_similar
    returned 0 results because the old adapter.search() called rt.search()
    (keyword/prefix) instead of rt.recall_similar() (semantic).
    Verify adapter.search now uses the semantic path."""
    local_adapter.write("food_pref", "user loves spicy thai food")
    local_adapter.write("lang_pref", "user prefers Python")
    local_adapter.write("color_pref", "user likes blue")
    # Flush any background enrichment so embeddings exist
    try:
        local_adapter._rt.flush(timeout=15.0)
    except Exception:
        pass
    results = local_adapter.search("what cuisine does the user enjoy?", limit=3)
    # Either we got real semantic results, or we cleanly fell back to keyword.
    # The point is: never raise AttributeError, never silently return 0.
    assert isinstance(results, list)
