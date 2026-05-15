"""Regression tests for the three real bugs from the May 2026 third-party
audit closed in 3.1.12.

Each test isolates one bug:
  1. loop_warning was null in audit rows even during red v1 severity (§12.3)
  2. consolidate() returned clusters_found=0 for 21 same-key writes (§12.5)
  3. drift sampler's recent_samples stayed 0 forever (§9.3)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

import pytest


# ---------------------------------------------------------------------------
# Bug 1: loop_warning in audit rows during write-pattern loops
# ---------------------------------------------------------------------------

def test_log_decision_carries_live_loop_status_when_severity_red(monkeypatch):
    """When v1 severity is red due to write patterns (not decision repeats),
    the audit row's loop_warning must NOT be null. Before this fix, only
    duplicate decisions populated loop_warning, leaving forensic replay
    blind to the surrounding loop state.
    """
    from synrix_runtime.api.runtime import AgentRuntime

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("SYNRIX_DATA_DIR", tmp)
        agent = AgentRuntime("test-audit-bug1", require_account=False)
        try:
            fake_status = {
                "severity": "red",
                "score": 0,
                "loop_type": "retry_loop",
                "signals": [
                    {"name": "write_similarity", "detail": "190/190 pairs similar"},
                    {"name": "key_overwrite", "detail": "loop_probe overwritten 50x"},
                    {"name": "velocity_spike", "detail": "50 writes in 60s"},
                    {"name": "alert_frequency", "detail": "20 alerts/hour"},
                ],
            }
            monkeypatch.setattr(agent, "get_loop_status", lambda: fake_status)
            # Decision itself is unique — without the fix, decision_loop is
            # None and loop_warning would be None too.
            result = agent.log_decision(
                decision="reroute via redis",
                reasoning="primary backend timing out",
            )
            assert result["loop_warning"] is not None, \
                "audit row's loop_warning is null despite red severity (regression of §12.3)"
            lw = result["loop_warning"]
            assert "live_status" in lw, "missing live_status branch"
            live = lw["live_status"]
            assert live["severity"] == "red"
            assert live["loop_type"] == "retry_loop"
            assert live["signal_count"] == 4
            assert "write_similarity" in live["signal_names"]
        finally:
            try:
                agent.shutdown()
            except Exception:
                pass


def test_log_decision_loop_warning_stays_null_when_green(monkeypatch):
    """Sanity: a unique decision in a healthy agent should not falsely
    flag loop_warning. We don't want noise; only yellow/orange/red trips.
    """
    from synrix_runtime.api.runtime import AgentRuntime

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("SYNRIX_DATA_DIR", tmp)
        agent = AgentRuntime("test-audit-bug1-green", require_account=False)
        try:
            monkeypatch.setattr(
                agent, "get_loop_status",
                lambda: {"severity": "green", "score": 100, "signals": []},
            )
            result = agent.log_decision(
                decision="new unique decision",
                reasoning="first time seeing this",
            )
            # No decision repeat AND severity green → loop_warning stays None
            assert result["loop_warning"] is None, \
                "loop_warning should not trip on green severity + unique decision"
        finally:
            try:
                agent.shutdown()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Bug 2: consolidate() recognises same-key version churn
# ---------------------------------------------------------------------------

def test_consolidate_detects_same_key_version_churn(monkeypatch):
    """Auditor's exact scenario: 21 byte-identical writes to one key
    should be detected as a cluster (version_churn). Before the fix,
    clusters_found was 0 because query_prefix only returns the latest
    version per key.

    Tests the consolidate() logic in isolation by stubbing the backend
    so we don't need a real SQLite DB or the [ai] extra in CI.
    """
    import sys as _sys

    # Stub embeddings to avoid forcing [ai] extra in CI.
    class _StubM:
        def encode(self, _t):
            import numpy as np
            return np.ones(8, dtype=np.float32)

    class _StubEM:
        @staticmethod
        def get():
            return _StubM()

    stub = type(_sys)("synrix.embeddings")
    stub.EmbeddingModel = _StubEM
    _sys.modules["synrix.embeddings"] = stub

    # Build a minimal AgentRuntime-shaped object so we can call consolidate
    # without going through __init__ (which spins up daemons, embedding
    # models, etc).
    from synrix_runtime.api.runtime import AgentRuntime

    class _FakeBackend:
        def __init__(self):
            self._versions = [
                {"data": {"value": "same content forever"}, "version": v}
                for v in range(1, 22)  # 21 versions
            ]

        def query_prefix(self, prefix, limit=None):
            # consolidate() expects {"key": ..., "data": ...} per item.
            # We return one "latest" row for the same key.
            return [{
                "key": f"{prefix}loop_probe",
                "data": {"value": "same content forever",
                         "timestamp": time.time()},
            }]

        def get_history(self, key):
            assert "loop_probe" in key
            return self._versions

        def delete(self, key):
            pass

    rt = AgentRuntime.__new__(AgentRuntime)
    rt.agent_id = "test-audit-bug2"
    rt.backend = _FakeBackend()
    rt._value_to_text = lambda v: str(v)  # type: ignore[assignment]

    result = rt.consolidate(dry_run=True)

    assert "version_churn_clusters" in result, \
        f"response missing version_churn_clusters (regression of §12.5): {result}"
    assert result["version_churn_clusters"] >= 1, \
        f"expected ≥1 same-key churn cluster, got 0 (regression of §12.5). full result: {result}"
    details = result.get("version_churn_details", [])
    churn = next((d for d in details if d["key"] == "loop_probe"), None)
    assert churn is not None, f"loop_probe not flagged. details: {details}"
    assert churn["total_versions"] >= 21
    assert churn["identical_versions"] >= 21
    assert churn["pattern"] == "same_key_version_churn"


# ---------------------------------------------------------------------------
# Bug 3: BrainHub.process_write lazy-computes embedding so drift samples
# ---------------------------------------------------------------------------

def test_drift_sampler_populates_recent_samples_when_embedding_is_none():
    """BrainHub.process_write is called with embedding=None by the cloud
    /remember handler (p99 fix). Before this commit DriftRadar.track
    short-circuited on None and _recent_embeddings stayed empty forever —
    /v1/brain/drift returned recent_samples=0 regardless of activity.
    With the lazy-embedding fallback, the sampler now actually samples.
    """
    import sys as _sys

    # Stub embedding model BEFORE importing brain (so the lazy-import
    # inside process_write picks it up). Returns a deterministic vector
    # per text so we can also verify clustering math downstream.
    class _StubEmbeddingModel:
        @staticmethod
        def get():
            import numpy as np

            class _M:
                def encode(self, t):
                    # Two distinct "regions" based on first char so we can
                    # set a goal embedding and then write off-goal content.
                    seed = ord(t[0]) if t else 0
                    rng = np.random.default_rng(seed)
                    return rng.standard_normal(16).astype(np.float32)

            return _M()

    stub = type(_sys)("synrix.embeddings")
    stub.EmbeddingModel = _StubEmbeddingModel
    _sys.modules["synrix.embeddings"] = stub

    # Force-reimport brain so it picks up our stub at lazy-import time.
    if "synrix_runtime.monitoring.brain" in _sys.modules:
        del _sys.modules["synrix_runtime.monitoring.brain"]
    from synrix_runtime.monitoring.brain import BrainHub, DriftRadar

    tenant_id = "tenant-drift-fix"
    agent_id = "agent-drift-fix"

    # Pre-existing goal embedding so track() doesn't auto-set on first
    # write (which would skip drift measurement).
    import numpy as np
    goal_vec = np.ones(16, dtype=np.float32)
    DriftRadar.set_goal(tenant_id, agent_id, goal_vec, goal_text="catalog preferences")

    # Simulate 10 cloud writes — embedding intentionally None to mirror
    # the cloud_server's call.
    for i in range(10):
        BrainHub.process_write(
            tenant_id=tenant_id,
            agent_id=agent_id,
            key=f"yacht_part_{i}",  # deliberately off-goal content
            value=f"yacht hull maintenance log entry {i}",
            embedding=None,
            backend=None,
        )

    info = DriftRadar.get_agent_drift(tenant_id, agent_id)
    assert info["recent_samples"] >= 5, \
        f"drift sampler still inert — recent_samples={info['recent_samples']} (regression of §9.3)"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
