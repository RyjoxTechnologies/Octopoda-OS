"""
Octopoda Test Fixtures
=======================
Shared fixtures for all test modules.
"""

import os
import pytest
import tempfile


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that's cleaned up after the test."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        yield d


@pytest.fixture
def sqlite_client(tmp_dir):
    """Provide a fresh SynrixSQLiteClient backed by a temp database."""
    from synrix.sqlite_client import SynrixSQLiteClient
    client = SynrixSQLiteClient(db_path=os.path.join(tmp_dir, "test.db"))
    yield client
    client.close()


@pytest.fixture
def agent_backend(tmp_dir):
    """Provide a SynrixAgentBackend using SQLite in a temp dir."""
    from synrix.agent_backend import get_synrix_backend
    backend = get_synrix_backend(
        backend="sqlite",
        sqlite_path=os.path.join(tmp_dir, "test_backend.db"),
    )
    yield backend
    backend.close()


@pytest.fixture
def memory(tmp_dir):
    """Provide a Memory instance using a fresh SQLite in a temp dir."""
    from synrix.memory import Memory
    from synrix.agent_backend import get_synrix_backend

    mem = Memory.__new__(Memory)
    mem._backend = get_synrix_backend(
        backend="sqlite",
        sqlite_path=os.path.join(tmp_dir, "test_memory.db"),
    )
    mem._agent_id = "test_agent"
    mem._prefix = "agents:test_agent:"
    yield mem


@pytest.fixture
def agent_ledger(tmp_dir):
    """Provide a fresh AgentLedger backed by a temp database."""
    from synrix.licensing import AgentLedger
    ledger = AgentLedger(db_path=os.path.join(tmp_dir, "test_ledger.db"))
    yield ledger
    ledger.close()
    AgentLedger.reset_instance()


@pytest.fixture(autouse=True)
def _unlimited_license(monkeypatch):
    """Generate and set an unlimited license key for all tests."""
    from synrix.licensing import _generate_license_key, AgentLedger
    monkeypatch.setenv("SYNRIX_HMAC_SECRET", "test-hmac-secret-do-not-ship")
    key = _generate_license_key("unlimited", "test@octopoda.dev")
    monkeypatch.setenv("SYNRIX_LICENSE_KEY", key)
    yield
    AgentLedger.reset_instance()


@pytest.fixture
def agent_runtime(tmp_dir, monkeypatch):
    """Provide an AgentRuntime backed by a temp SQLite database.

    Sets env vars so the runtime uses a temp dir instead of ~/.synrix/data.
    Resets the daemon singleton after the test.
    """
    monkeypatch.setenv("SYNRIX_BACKEND", "sqlite")
    monkeypatch.setenv("SYNRIX_DATA_DIR", tmp_dir)

    from synrix_runtime.core.daemon import RuntimeDaemon
    from synrix_runtime.api.tenant import TenantManager
    from synrix_runtime.monitoring.metrics import MetricsCollector
    RuntimeDaemon.reset_instance()
    try:
        TenantManager.reset_instance()
    except Exception:
        pass
    MetricsCollector._instance = None

    from synrix_runtime.api.runtime import AgentRuntime
    rt = AgentRuntime("test_agent", agent_type="test")
    yield rt
    rt.shutdown()
    RuntimeDaemon.reset_instance()
    try:
        TenantManager.reset_instance()
    except Exception:
        pass
    MetricsCollector._instance = None


@pytest.fixture
def api_client(tmp_dir, monkeypatch):
    """Provide a FastAPI TestClient with auth disabled and temp backend."""
    monkeypatch.setenv("SYNRIX_BACKEND", "sqlite")
    monkeypatch.setenv("SYNRIX_DATA_DIR", tmp_dir)
    monkeypatch.setenv("SYNRIX_AUTH_DISABLED", "1")
    # Auth bypass now requires the real bind (config.api_host) to be loopback.
    monkeypatch.setenv("SYNRIX_API_HOST", "127.0.0.1")

    from synrix_runtime.core.daemon import RuntimeDaemon
    from synrix_runtime.api.tenant import TenantManager
    from synrix_runtime.monitoring.metrics import MetricsCollector
    RuntimeDaemon.reset_instance()
    try:
        TenantManager.reset_instance()
    except Exception:
        pass
    MetricsCollector._instance = None

    daemon = RuntimeDaemon.get_instance()
    daemon.start()

    from synrix_runtime.config import SynrixConfig
    config = SynrixConfig.from_env()

    from synrix_runtime.api.cloud_server import app, init_cloud_server, _agent_runtimes
    _agent_runtimes.clear()
    init_cloud_server(daemon, config)

    from fastapi.testclient import TestClient
    client = TestClient(app)
    yield client

    daemon.shutdown()
    RuntimeDaemon.reset_instance()
    try:
        TenantManager.reset_instance()
    except Exception:
        pass
    MetricsCollector._instance = None


@pytest.fixture
def daemon(tmp_dir, monkeypatch):
    """Provide a RuntimeDaemon backed by a temp SQLite database."""
    monkeypatch.setenv("SYNRIX_BACKEND", "sqlite")
    monkeypatch.setenv("SYNRIX_DATA_DIR", tmp_dir)

    from synrix_runtime.core.daemon import RuntimeDaemon
    from synrix_runtime.api.tenant import TenantManager
    from synrix_runtime.monitoring.metrics import MetricsCollector
    RuntimeDaemon.reset_instance()
    try:
        TenantManager.reset_instance()
    except Exception:
        pass
    MetricsCollector._instance = None

    d = RuntimeDaemon.get_instance()
    d.start()
    yield d
    d.shutdown()
    RuntimeDaemon.reset_instance()
    try:
        TenantManager.reset_instance()
    except Exception:
        pass
    MetricsCollector._instance = None
