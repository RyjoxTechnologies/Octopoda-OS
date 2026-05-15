"""Integration smoke test for 3.1.7 fixes.

Spins up a real AgentRuntime in local SQLite mode, simulates heavy heartbeat
traffic, then asserts the nodes table stays bounded by the trigger.
"""
import os
import sys
import tempfile
import shutil
import time
import sqlite3

# Force local mode (no cloud key)
os.environ.pop("OCTOPODA_API_KEY", None)
tmpdir = tempfile.mkdtemp(prefix="octopoda_v317_smoke_")
os.environ["SYNRIX_DATA_DIR"] = tmpdir

from octopoda import AgentRuntime
import octopoda

print(f"=" * 70)
print(f"  Integration smoke test for octopoda {octopoda.__version__}")
print(f"  Data dir: {tmpdir}")
print(f"=" * 70)
print()

# Step 1: create agent
agent = AgentRuntime("smoke_v317")
print(f"[1] AgentRuntime created — daemon spinning up heartbeats...")

# Step 2: write to user-memory key 30 times — should NOT be capped
USER_KEY = "user:preferences"
for i in range(30):
    agent.remember(USER_KEY, f"value v{i} at {time.time():.1f}")

# Step 3: hammer a runtime: key 50 times via direct backend writes (simulates heartbeat behavior)
HEARTBEAT_KEY = "runtime:agents:smoke_v317:test_heartbeat"
backend = agent.backend
for i in range(50):
    backend.write(HEARTBEAT_KEY, {"hb": i, "ts": time.time()})

# Step 4: hammer a metrics: key
METRICS_KEY = "metrics:system:test_counter"
for i in range(40):
    backend.write(METRICS_KEY, {"count": i})

# Step 5: count rows for each via direct SQLite query
db_path = os.path.join(tmpdir, "data", "synrix.db")
if not os.path.exists(db_path):
    # Try other common paths
    for cand in [os.path.join(tmpdir, "synrix.db"), os.path.expanduser("~/.synrix/data/synrix.db")]:
        if os.path.exists(cand):
            db_path = cand
            break

print(f"[2] Inspecting nodes table at {db_path}")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

user_count = cur.execute("SELECT COUNT(*) FROM nodes WHERE name LIKE ?", (f"%{USER_KEY}",)).fetchone()[0]
hb_count = cur.execute("SELECT COUNT(*) FROM nodes WHERE name = ?", (HEARTBEAT_KEY,)).fetchone()[0]
m_count = cur.execute("SELECT COUNT(*) FROM nodes WHERE name = ?", (METRICS_KEY,)).fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

print(f"     user-memory key {USER_KEY!r}: {user_count} rows (wrote 30x — should retain all/most)")
print(f"     runtime: heartbeat key:        {hb_count} rows (wrote 50x — should be capped at 10)")
print(f"     metrics: counter key:          {m_count} rows (wrote 40x — should be capped at 10)")
print(f"     total nodes table size:        {total} rows")
print()

# Step 6: verify the trigger exists
trigger_rows = cur.execute("""
    SELECT name, sql FROM sqlite_master
    WHERE type='trigger' AND name LIKE 'trg_nodes_%'
""").fetchall()
print(f"[3] Triggers installed: {len(trigger_rows)}")
for name, _sql in trigger_rows:
    print(f"     - {name}")

conn.close()
print()

# Step 7: assertions
print(f"[4] Assertions:")
ok = True
if user_count < 15:
    print(f"     FAIL: user-memory key was capped to {user_count} (should keep most of 30)")
    ok = False
else:
    print(f"     PASS: user-memory NOT capped ({user_count} rows preserved)")

if hb_count > 10:
    print(f"     FAIL: heartbeat key has {hb_count} rows (should be capped at 10)")
    ok = False
else:
    print(f"     PASS: heartbeat capped to {hb_count} rows")

if m_count > 10:
    print(f"     FAIL: metrics key has {m_count} rows (should be capped at 10)")
    ok = False
else:
    print(f"     PASS: metrics capped to {m_count} rows")

if len(trigger_rows) < 2:
    print(f"     FAIL: only {len(trigger_rows)} triggers, expected 2")
    ok = False
else:
    print(f"     PASS: {len(trigger_rows)} triggers installed")

print()
print("=" * 70)
print(f"  RESULT: {'ALL PASS' if ok else 'FAILED'}")
print("=" * 70)

# Cleanup
try:
    agent.shutdown()
except Exception:
    pass
time.sleep(1)
try:
    shutil.rmtree(tmpdir, ignore_errors=True)
except Exception:
    pass

sys.exit(0 if ok else 1)
