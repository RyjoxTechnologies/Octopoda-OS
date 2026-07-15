"""
Quick load test — run directly with: python tests/run_load_test.py
Uses sequential batches of concurrent users to avoid segfaults from
threading + native extensions on Windows.
"""

import os
import sys
import time
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup
tmp = tempfile.mkdtemp(prefix="octopoda_load_")
os.environ["SYNRIX_BACKEND"] = "sqlite"
os.environ["SYNRIX_DATA_DIR"] = tmp
os.environ["SYNRIX_AUTH_DISABLED"] = "1"
os.environ["SYNRIX_API_HOST"] = "127.0.0.1"
os.environ["SYNRIX_RATE_LIMIT_RPM"] = "999999"

os.environ["SYNRIX_HMAC_SECRET"] = "load-test-hmac-secret"
from synrix.licensing import _generate_license_key
os.environ["SYNRIX_LICENSE_KEY"] = _generate_license_key("unlimited", "load@test.dev")

from synrix_runtime.core.daemon import RuntimeDaemon
from synrix_runtime.monitoring.metrics import MetricsCollector
RuntimeDaemon.reset_instance()
MetricsCollector._instance = None
daemon = RuntimeDaemon.get_instance()
daemon.start()

from synrix_runtime.config import SynrixConfig
from synrix_runtime.api.cloud_server import app, init_cloud_server, _agent_runtimes, _rate_limiter
_agent_runtimes.clear()
_rate_limiter._rpm = 999999
init_cloud_server(daemon, SynrixConfig.from_env())

from fastapi.testclient import TestClient
client = TestClient(app)

print("\n  Server up. Starting load test...\n")

# ----------- CONFIG -----------
NUM_USERS = 100
BATCH_SIZE = 10  # run 10 users at a time to avoid native extension segfaults
WRITES_PER = 5
READS_PER = 3

# ----------- STORAGE -----------
timings = {op: [] for op in [
    "register", "write", "read", "search",
    "metrics", "performance", "anomalies", "audit", "timeseries"
]}
errors = []
users_done = 0


def run_user(uid):
    aid = f"agent_{uid}"
    local_errors = []

    def timed(op, method, url, **kwargs):
        t = time.perf_counter()
        if method == "GET":
            r = client.get(url, **kwargs)
        else:
            r = client.post(url, **kwargs)
        ms = (time.perf_counter() - t) * 1000
        timings[op].append(ms)
        if r.status_code >= 400:
            local_errors.append(f"{op}:{r.status_code}")
        return r

    try:
        timed("register", "POST", "/v1/agents", json={"agent_id": aid, "agent_type": "test"})
        for i in range(WRITES_PER):
            timed("write", "POST", f"/v1/agents/{aid}/remember",
                  json={"key": f"k{i}", "value": f"v{i}"})
        for i in range(READS_PER):
            timed("read", "GET", f"/v1/agents/{aid}/recall/k{i}")
        timed("search", "GET", f"/v1/agents/{aid}/search?prefix=k")
        timed("metrics", "GET", f"/v1/agents/{aid}/metrics")
        timed("performance", "GET", f"/v1/agents/{aid}/performance")
        timed("anomalies", "GET", "/v1/anomalies")
        timed("audit", "GET", "/v1/audit/timeline?limit=20")
        timed("timeseries", "GET", f"/v1/agents/{aid}/metrics/timeseries?minutes=60&type=write")
    except Exception as e:
        local_errors.append(f"CRASH:{e}")

    return local_errors


def pct(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    k = int(len(s) * p / 100)
    return s[min(k, len(s) - 1)]


# ----------- RUN IN BATCHES -----------
total_start = time.perf_counter()

for batch_start in range(0, NUM_USERS, BATCH_SIZE):
    batch_end = min(batch_start + BATCH_SIZE, NUM_USERS)
    batch_ids = list(range(batch_start, batch_end))

    with ThreadPoolExecutor(max_workers=BATCH_SIZE) as pool:
        futures = {pool.submit(run_user, uid): uid for uid in batch_ids}
        for f in as_completed(futures):
            errs = f.result(timeout=60)
            errors.extend(errs)
            users_done += 1

    pct_done = users_done / NUM_USERS * 100
    sys.stdout.write(f"\r  Progress: {users_done}/{NUM_USERS} users ({pct_done:.0f}%)")
    sys.stdout.flush()

total_time = time.perf_counter() - total_start
total_reqs = sum(len(v) for v in timings.values())
error_count = len(errors)

# ----------- RESULTS -----------
print("\n")
print("=" * 65)
print(f"  LOAD TEST: {NUM_USERS} users ({BATCH_SIZE} concurrent)")
print("=" * 65)
print(f"  Users completed:  {users_done}/{NUM_USERS}")
print(f"  Total requests:   {total_reqs}")
print(f"  Errors:           {error_count} ({error_count / max(total_reqs, 1) * 100:.1f}%)")
print(f"  Total time:       {total_time:.1f}s")
print(f"  Throughput:       {total_reqs / total_time:.0f} req/s")
print()
print(f"  {'Op':<16} {'Count':>6} {'p50ms':>8} {'p95ms':>8} {'p99ms':>8} {'Max ms':>8}")
print(f"  {'-' * 16} {'-' * 6} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 8}")
for op in ["register", "write", "read", "search", "metrics",
           "performance", "anomalies", "audit", "timeseries"]:
    d = timings[op]
    if d:
        print(f"  {op:<16} {len(d):>6} {pct(d, 50):>8.1f} {pct(d, 95):>8.1f} {pct(d, 99):>8.1f} {max(d):>8.1f}")

if errors:
    from collections import Counter
    c = Counter(errors)
    print(f"\n  Errors:")
    for e, cnt in c.most_common(5):
        print(f"    [{cnt}x] {e}")

print("=" * 65)

# ----------- SSE TEST -----------
print("\n  SSE Test: 20 concurrent streams...")
from synrix_runtime.api.cloud_server import _sse_event_generator

backend = daemon.backend
sse_results = {}
sse_errors = []


def sse_stream(sid):
    try:
        gen = _sse_event_generator(backend)
        for chunk in gen:
            sse_results[sid] = chunk
            if "system_heartbeat" in chunk:
                break
    except Exception as e:
        sse_errors.append(str(e))


threads = []
sse_start = time.perf_counter()
for i in range(20):
    t = threading.Thread(target=sse_stream, args=(i,), daemon=True)
    threads.append(t)
    t.start()
for t in threads:
    t.join(timeout=10)
sse_time = time.perf_counter() - sse_start
sse_ok = sum(1 for v in sse_results.values() if "heartbeat" in v)
print(f"  Result: {sse_ok}/20 streams OK in {sse_time:.1f}s")
if sse_errors:
    print(f"  SSE errors: {sse_errors[:3]}")

# ----------- VERDICT -----------
print()
if error_count == 0 and users_done == NUM_USERS and sse_ok == 20:
    print("  VERDICT: ALL CLEAR - 100 users + 20 SSE streams, zero errors")
elif error_count / max(total_reqs, 1) < 0.01:
    print(f"  VERDICT: PASS - {error_count} minor errors ({error_count / total_reqs * 100:.2f}%)")
else:
    print(f"  VERDICT: NEEDS WORK - {error_count} errors ({error_count / total_reqs * 100:.1f}%)")
print()

daemon.shutdown()
