"""Simulate a real user installing Octopoda from PyPI and using it.
No local wheel, no cached install. Real pip, real PyPI, real SDK calls.
"""
import os
import sys
import time
import subprocess
import urllib.request
import urllib.error
import json
import shutil

TEST_ROOT = "/tmp/user-sim-3118"
VENV = f"{TEST_ROOT}/venv"
DATA_DIR = f"{TEST_ROOT}/data"
shutil.rmtree(TEST_ROOT, ignore_errors=True)
os.makedirs(DATA_DIR, exist_ok=True)

def run(cmd, env=None, capture=True):
    result = subprocess.run(cmd, env=env, capture_output=capture, text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr

def py(*args):
    return [f"{VENV}/Scripts/python.exe", *args]

def pip(*args):
    return py("-m", "pip", *args)

print("=" * 70)
print("REAL USER SIMULATION — fresh venv, install from PyPI")
print("=" * 70)
print()

# Step 1: Fresh venv (as if a user just made one)
print("[1] Creating fresh venv...")
rc, out, err = run([sys.executable, "-m", "venv", VENV])
if rc != 0:
    print(f"  venv create failed: {err}")
    sys.exit(1)
print("  ok")

# Step 2: pip install octopoda from PyPI (not my local wheel)
print("[2] pip install octopoda==3.1.18 --no-cache-dir (from PyPI)...")
rc, out, err = run(pip("install", "--quiet", "--no-cache-dir", "octopoda==3.1.18"))
if rc != 0:
    print(f"  install failed: {err[-500:]}")
    sys.exit(1)
print("  ok")

# Step 3: Verify version reported is what we just shipped
print("[3] What version does PyPI actually ship?")
rc, out, err = run(py("-c", "import octopoda; print(octopoda.__version__)"))
print(f"  {out.strip()}")
if "3.1.18" not in out:
    print(f"  FAIL: expected 3.1.18, got {out.strip()}")
    sys.exit(1)

# Step 4: A user writes a Python script. Test the simplest SDK path.
# This is what they'd see in the README quickstart.
print("[4] Real SDK use — AgentRuntime against fresh SQLite...")
env = os.environ.copy()
env.pop("DATABASE_URL", None)
env["OCTOPODA_DATA_DIR"] = DATA_DIR
script = """
import os
os.environ['OCTOPODA_DATA_DIR'] = r'{data}'
from octopoda import AgentRuntime

a = AgentRuntime('user-sim', require_account=False)
a.remember('favorite_food', {{'value': 'pizza'}})
a.remember('favorite_color', {{'value': 'orange'}})
a.remember('lang', {{'value': 'english'}})
got = a.recall('favorite_food')
assert got is not None, 'recall returned None for a key we just wrote'
print('roundtrip ok:', got)
# Try semantic recall (will fall back to lexical/prefix without [ai])
sr = a.recall_similar('what do they like to eat', limit=3)
print('recall_similar count:', getattr(sr, 'results', None) and len(sr.results) or 0)
# Loop status
status = a.get_loop_status()
print('loop_status severity:', status.get('severity'))
# Drift goal
a.set_goal('catalog preferences', milestones=['food', 'color', 'lang'])
goal = a.get_goal()
print('goal:', goal.get('goal'))
# Audit decision (verifies log_decision works with dict context)
a.log_decision('allow', 'all data is fine', context={{'who': 'sim', 'why': 'test'}})
print('decision logged ok')
# octopoda_status equivalent via SDK
stats = a.get_stats()
print('writes:', stats.total_writes, 'reads:', stats.total_reads)
a.shutdown()
print('SDK_OK')
""".format(data=DATA_DIR)
rc, out, err = run(py("-c", script), env=env)
print(out.replace("\\n", "\n").strip()[-800:])
if "SDK_OK" not in out:
    print(f"  STDERR:\n{err[-800:]}")
    sys.exit(1)
print("  [PASS] SDK round-trip works")

# Step 5: Real cloud_server.py with NO DATABASE_URL (this was Issue #7)
print()
print("[5] Real local cloud_server.py with no DATABASE_URL (Issue #7)...")
rc, out, err = run(pip("install", "--quiet", "fastapi", "uvicorn[standard]"))
print(f"  installed [server] deps: rc={rc}")

env2 = os.environ.copy()
env2.pop("DATABASE_URL", None)
env2["OCTOPODA_LOCAL_MODE"] = "1"
env2["OCTOPODA_DATA_DIR"] = f"{DATA_DIR}-server"
os.makedirs(f"{DATA_DIR}-server", exist_ok=True)

proc = subprocess.Popen(
    py("-m", "uvicorn", "synrix_runtime.api.cloud_server:app",
       "--host", "127.0.0.1", "--port", "8745", "--log-level", "warning"),
    env=env2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
for i in range(30):
    try:
        urllib.request.urlopen("http://127.0.0.1:8745/health", timeout=1).read()
        break
    except Exception:
        time.sleep(1)
else:
    proc.kill()
    out, _ = proc.communicate(timeout=2)
    print(f"  SERVER NEVER STARTED")
    print(out[-1500:])
    sys.exit(1)

def req(method, path, body=None, key="local"):
    url = f"http://127.0.0.1:8745{path}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": str(e)}

# The user's flow: hit /health, auth, write, read, list
checks = [
    ("/health", "GET", None, lambda c, b: c == 200 and b.get("version") == "3.1.18"),
    ("/v1/auth/me", "GET", None, lambda c, b: c == 200 and b.get("tenant_id") == "_local"),
    ("/v1/agents/usr/remember", "POST", {"key": "k1", "value": "hello world"},
     lambda c, b: c == 200 and b.get("success") is True),
    ("/v1/agents/usr/recall/k1", "GET", None,
     lambda c, b: c == 200 and "hello world" in str(b)),
    ("/v1/agents/usr/cleanup", "POST", None, lambda c, b: c == 200),
    ("/v1/agents", "GET", None, lambda c, b: c == 200),
]
results = []
for path, method, body, validator in checks:
    code, b = req(method, path, body)
    ok = validator(code, b)
    results.append((path, ok, code))
    print(f"  [{'PASS' if ok else 'FAIL'}] {method} {path} -> {code}")

proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    proc.kill()

# Step 6: Verify CLI binaries are wired up
print()
print("[6] CLI binaries installed?")
for binname in ["octopoda", "octopoda-mcp"]:
    binpath = f"{VENV}/Scripts/{binname}.exe"
    exists = os.path.exists(binpath)
    print(f"  [{'PASS' if exists else 'FAIL'}] {binname} -> {binpath}")

# Step 7: Verify wheel contents — audit_v2 module shipped, FTS5 fallback shipped
print()
print("[7] Wheel actually contains audit_v2 + new code?")
rc, out, err = run(py("-c",
    "import inspect; "
    "from synrix_runtime.audit_v2 import api, log, storage; "
    "from synrix_runtime.loop_intel_v2 import circuit_breaker as cb; "
    "from synrix_runtime.api.tenant import TenantManager; "
    "tm_src = inspect.getsource(TenantManager); "
    "print('audit_v2 importable: yes'); "
    "print('cb.trip_on_v1_severity:', hasattr(cb, 'trip_on_v1_severity')); "
    "print('TenantManager._local_mode wired:', '_local_mode' in tm_src); "
    "print('OCTOPODA_DATA_DIR honored:', 'OCTOPODA_DATA_DIR' in tm_src)"
))
print(out.strip())

print()
print("=" * 70)
all_pass = all(ok for _, ok, _ in results)
print(f"VERDICT: {'ALL PASS' if all_pass else 'SOMETHING FAILED'}")
print(f"  HTTP endpoint tests: {sum(1 for _, ok, _ in results if ok)}/{len(results)} pass")
