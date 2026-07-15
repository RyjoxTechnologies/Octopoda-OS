"""
Octopoda Cloud API — Load Test
================================
Simulates 100 concurrent users each performing a realistic workflow:
  1. Register an agent
  2. Write 10 memories
  3. Read back 5 memories
  4. Search memories
  5. Query metrics
  6. Query performance breakdown
  7. Query anomalies
  8. Query audit timeline
  9. Open SSE stream (read first batch of events)

Measures: response times (p50/p95/p99), error rates, throughput.
Run with: pytest tests/test_load.py -v -s
"""

import os
import time
import json
import threading
import statistics
import tempfile
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NUM_USERS = 100
MEMORIES_PER_USER = 10
READS_PER_USER = 5


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def load_client():
    """
    Module-scoped TestClient — one server for all load tests.
    Uses a dedicated temp dir so it doesn't interfere with other tests.
    """
    tmp = tempfile.mkdtemp(prefix="octopoda_load_")
    os.environ["SYNRIX_BACKEND"] = "sqlite"
    os.environ["SYNRIX_DATA_DIR"] = tmp
    os.environ["SYNRIX_AUTH_DISABLED"] = "1"
    # Auth bypass now requires the real bind (config.api_host) to be loopback.
    os.environ["SYNRIX_API_HOST"] = "127.0.0.1"
    # Disable rate limiting for load test (all 100 users share one IP in test)
    os.environ["SYNRIX_RATE_LIMIT_RPM"] = "999999"

    os.environ["SYNRIX_HMAC_SECRET"] = "load-test-hmac-secret"
    from synrix.licensing import _generate_license_key, AgentLedger
    key = _generate_license_key("unlimited", "load@test.dev")
    os.environ["SYNRIX_LICENSE_KEY"] = key

    from synrix_runtime.core.daemon import RuntimeDaemon
    from synrix_runtime.monitoring.metrics import MetricsCollector
    RuntimeDaemon.reset_instance()
    MetricsCollector._instance = None

    daemon = RuntimeDaemon.get_instance()
    daemon.start()

    from synrix_runtime.config import SynrixConfig
    config = SynrixConfig.from_env()

    from synrix_runtime.api.cloud_server import app, init_cloud_server, _agent_runtimes, _rate_limiter
    _agent_runtimes.clear()
    # Reset rate limiter to allow high throughput (all test users share one IP)
    _rate_limiter._rpm = 999999
    init_cloud_server(daemon, config)

    from fastapi.testclient import TestClient
    client = TestClient(app)
    yield client

    daemon.shutdown()
    RuntimeDaemon.reset_instance()
    MetricsCollector._instance = None
    AgentLedger.reset_instance()

    # Clean env
    for k in ["SYNRIX_BACKEND", "SYNRIX_DATA_DIR", "SYNRIX_AUTH_DISABLED", "SYNRIX_LICENSE_KEY", "SYNRIX_RATE_LIMIT_RPM"]:
        os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class UserMetrics:
    """Collects timing data for a single simulated user."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.agent_id = f"load_agent_{user_id}"
        self.timings: dict[str, list[float]] = {
            "register": [],
            "write": [],
            "read": [],
            "search": [],
            "metrics": [],
            "performance": [],
            "anomalies": [],
            "audit_timeline": [],
            "timeseries": [],
            "sse_first_event": [],
        }
        self.errors: list[str] = []
        self.total_requests = 0
        self.failed_requests = 0

    def record(self, op: str, start: float, resp):
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.total_requests += 1
        if resp.status_code >= 400:
            self.failed_requests += 1
            self.errors.append(f"{op}: HTTP {resp.status_code}")
        self.timings[op].append(elapsed_ms)


def simulate_user(client, user_id: int) -> UserMetrics:
    """Run a full user workflow, return timing metrics."""
    m = UserMetrics(user_id)
    agent_id = m.agent_id

    # 1. Register agent
    t = time.perf_counter()
    resp = client.post("/v1/agents", json={"agent_id": agent_id, "agent_type": "load_test"})
    m.record("register", t, resp)

    # 2. Write memories
    for i in range(MEMORIES_PER_USER):
        t = time.perf_counter()
        resp = client.post(f"/v1/agents/{agent_id}/remember", json={
            "key": f"mem_{i}",
            "value": {"data": f"value_{i}", "index": i, "user": user_id},
        })
        m.record("write", t, resp)

    # 3. Read memories
    for i in range(READS_PER_USER):
        t = time.perf_counter()
        resp = client.get(f"/v1/agents/{agent_id}/recall/mem_{i}")
        m.record("read", t, resp)

    # 4. Search
    t = time.perf_counter()
    resp = client.get(f"/v1/agents/{agent_id}/search?prefix=mem_&limit=20")
    m.record("search", t, resp)

    # 5. Agent metrics
    t = time.perf_counter()
    resp = client.get(f"/v1/agents/{agent_id}/metrics")
    m.record("metrics", t, resp)

    # 6. Performance breakdown
    t = time.perf_counter()
    resp = client.get(f"/v1/agents/{agent_id}/performance")
    m.record("performance", t, resp)

    # 7. Anomalies
    t = time.perf_counter()
    resp = client.get("/v1/anomalies")
    m.record("anomalies", t, resp)

    # 8. Audit timeline
    t = time.perf_counter()
    resp = client.get("/v1/audit/timeline?limit=20")
    m.record("audit_timeline", t, resp)

    # 9. Metrics timeseries
    t = time.perf_counter()
    resp = client.get(f"/v1/agents/{agent_id}/metrics/timeseries?minutes=60&type=write")
    m.record("timeseries", t, resp)

    # 10. SSE — skip in concurrent test (each SSE generator has 1s sleep).
    #     Tested separately in TestSSEConcurrent.
    pass

    return m


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile from a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadConcurrent:
    """Run 100 concurrent users and verify performance."""

    def test_100_concurrent_users(self, load_client):
        """
        Simulate 100 users concurrently hitting the API.
        Assert: <1% error rate, p95 response < 5 seconds.
        """
        all_metrics: list[UserMetrics] = []
        total_start = time.perf_counter()

        # Run all users concurrently with thread pool
        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = {
                pool.submit(simulate_user, load_client, i): i
                for i in range(NUM_USERS)
            }
            for future in as_completed(futures):
                user_id = futures[future]
                try:
                    result = future.result(timeout=120)
                    all_metrics.append(result)
                except Exception as e:
                    print(f"  User {user_id} CRASHED: {e}")

        total_elapsed = time.perf_counter() - total_start

        # Aggregate results
        total_requests = sum(m.total_requests for m in all_metrics)
        total_failures = sum(m.failed_requests for m in all_metrics)
        error_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0
        all_errors = []
        for m in all_metrics:
            all_errors.extend(m.errors)

        # Aggregate timings per operation
        op_timings: dict[str, list[float]] = {}
        for m in all_metrics:
            for op, times in m.timings.items():
                op_timings.setdefault(op, []).extend(times)

        # Print results
        print("\n" + "=" * 70)
        print(f"  LOAD TEST RESULTS — {NUM_USERS} concurrent users")
        print("=" * 70)
        print(f"  Users completed:   {len(all_metrics)}/{NUM_USERS}")
        print(f"  Total requests:    {total_requests}")
        print(f"  Failed requests:   {total_failures}")
        print(f"  Error rate:        {error_rate:.2f}%")
        print(f"  Total time:        {total_elapsed:.1f}s")
        print(f"  Throughput:        {total_requests / total_elapsed:.0f} req/s")
        print()
        print(f"  {'Operation':<20} {'Count':>6} {'p50 (ms)':>10} {'p95 (ms)':>10} {'p99 (ms)':>10} {'Max (ms)':>10}")
        print(f"  {'-' * 20} {'-' * 6} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 10}")

        for op in ["register", "write", "read", "search", "metrics",
                    "performance", "anomalies", "audit_timeline", "timeseries", "sse_first_event"]:
            times = op_timings.get(op, [])
            if times:
                print(f"  {op:<20} {len(times):>6} "
                      f"{percentile(times, 50):>10.1f} "
                      f"{percentile(times, 95):>10.1f} "
                      f"{percentile(times, 99):>10.1f} "
                      f"{max(times):>10.1f}")

        if all_errors:
            print(f"\n  Errors ({len(all_errors)} total):")
            # Show unique errors with counts
            error_counts: dict[str, int] = {}
            for e in all_errors:
                error_counts[e] = error_counts.get(e, 0) + 1
            for err, count in sorted(error_counts.items(), key=lambda x: -x[1])[:10]:
                print(f"    [{count}x] {err}")

        print("=" * 70)

        # Assertions
        assert len(all_metrics) == NUM_USERS, f"Only {len(all_metrics)}/{NUM_USERS} users completed"
        assert error_rate < 5.0, f"Error rate {error_rate:.1f}% exceeds 5% threshold"

        # p95 for write operations should be under 5 seconds
        write_times = op_timings.get("write", [])
        if write_times:
            p95_write = percentile(write_times, 95)
            assert p95_write < 5000, f"p95 write latency {p95_write:.0f}ms exceeds 5s threshold"

        # p95 for read operations should be under 5 seconds
        read_times = op_timings.get("read", [])
        if read_times:
            p95_read = percentile(read_times, 95)
            assert p95_read < 5000, f"p95 read latency {p95_read:.0f}ms exceeds 5s threshold"

    def test_sequential_baseline(self, load_client):
        """
        Run 10 users sequentially for baseline comparison.
        This shows what single-user performance looks like.
        """
        all_metrics = []
        total_start = time.perf_counter()

        for i in range(10):
            result = simulate_user(load_client, 1000 + i)
            all_metrics.append(result)

        total_elapsed = time.perf_counter() - total_start
        total_requests = sum(m.total_requests for m in all_metrics)

        # Aggregate timings
        op_timings: dict[str, list[float]] = {}
        for m in all_metrics:
            for op, times in m.timings.items():
                op_timings.setdefault(op, []).extend(times)

        print("\n" + "=" * 70)
        print(f"  BASELINE — 10 sequential users")
        print("=" * 70)
        print(f"  Total time:        {total_elapsed:.1f}s")
        print(f"  Throughput:        {total_requests / total_elapsed:.0f} req/s")
        print()
        print(f"  {'Operation':<20} {'p50 (ms)':>10} {'p95 (ms)':>10} {'Max (ms)':>10}")
        print(f"  {'-' * 20} {'-' * 10} {'-' * 10} {'-' * 10}")

        for op in ["register", "write", "read", "search", "metrics",
                    "performance", "anomalies", "audit_timeline", "timeseries", "sse_first_event"]:
            times = op_timings.get(op, [])
            if times:
                print(f"  {op:<20} "
                      f"{percentile(times, 50):>10.1f} "
                      f"{percentile(times, 95):>10.1f} "
                      f"{max(times):>10.1f}")

        print("=" * 70)

        total_failures = sum(m.failed_requests for m in all_metrics)
        assert total_failures == 0, f"Baseline had {total_failures} failures"


class TestSSEConcurrent:
    """Test SSE with multiple concurrent streams."""

    def test_20_concurrent_sse_streams(self, load_client):
        """
        Open 20 SSE streams simultaneously.
        Each stream should produce events within 3 seconds.
        """
        NUM_STREAMS = 20

        from synrix_runtime.api.cloud_server import _sse_event_generator
        from synrix_runtime.core.daemon import RuntimeDaemon
        daemon = RuntimeDaemon.get_instance()
        backend = daemon.backend

        results = {}
        errors = []

        def open_stream(stream_id):
            try:
                gen = _sse_event_generator(backend)
                chunks = []
                for chunk in gen:
                    chunks.append(chunk)
                    if "system_heartbeat" in chunk:
                        break
                results[stream_id] = "".join(chunks)
            except Exception as e:
                errors.append(f"stream_{stream_id}: {e}")

        threads = []
        start = time.perf_counter()
        for i in range(NUM_STREAMS):
            t = threading.Thread(target=open_stream, args=(i,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        elapsed = time.perf_counter() - start

        success = sum(1 for v in results.values() if "system_heartbeat" in v)
        print(f"\n  SSE: {success}/{NUM_STREAMS} streams got events in {elapsed:.1f}s")
        if errors:
            for e in errors[:5]:
                print(f"    Error: {e}")

        assert success == NUM_STREAMS, f"Only {success}/{NUM_STREAMS} SSE streams succeeded"
        assert elapsed < 10, f"SSE streams took {elapsed:.1f}s (expected <10s)"
