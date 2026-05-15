"""Live smoke test for Issue #7 (Yeraze): local cloud_server.py with no
DATABASE_URL. Verifies the server boots and serves endpoints against SQLite.
"""
import os
import sys
import time
import subprocess
import urllib.request
import urllib.error
import json
import shutil

# Clean test data dir
DATA_DIR = "/tmp/test-local-3118-data"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.makedirs(DATA_DIR, exist_ok=True)

# Start the cloud_server.py with NO DATABASE_URL.
env = os.environ.copy()
env.pop("DATABASE_URL", None)
env["OCTOPODA_LOCAL_MODE"] = "1"
env["OCTOPODA_DATA_DIR"] = DATA_DIR
env["OCTOPODA_API_KEY"] = "local"

PORT = "8742"
print(f"Starting local server on port {PORT} with NO DATABASE_URL...")
proc = subprocess.Popen(
    [
        "C:/Users/user/AppData/Local/Temp/test-local-3118/Scripts/python.exe",
        "-m", "uvicorn", "synrix_runtime.api.cloud_server:app",
        "--host", "127.0.0.1", "--port", PORT,
        "--log-level", "warning",
    ],
    env=env,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True,
)

# Wait for it to come up
print("Waiting for /health to be ready...")
for i in range(30):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as r:
            if r.status == 200:
                body = json.loads(r.read())
                print(f"  ready after {i+1}s -> {body}")
                break
    except Exception:
        time.sleep(1)
else:
    proc.kill()
    out, _ = proc.communicate(timeout=2)
    print("SERVER NEVER STARTED. Output:")
    print(out[-2000:])
    sys.exit(1)


def req(method, path, body=None, key="local"):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": str(e)}
    except Exception as e:
        return None, {"err": str(e)}


print()
print("=" * 60)
print("LOCAL-MODE LIVE TEST")
print("=" * 60)

# 1. /health (was already working — sanity)
c, b = req("GET", "/health")
print(f"[{ 'PASS' if c == 200 else 'FAIL'}] /health -> {c} {b}")

# 2. THE ORIGINAL FAILURE — /v1/auth/me. Pre-fix this raised
# ValueError: DATABASE_URL not set. Now should succeed with local tenant.
c, b = req("GET", "/v1/auth/me")
ok = c == 200 and b.get("tenant_id") == "_local"
print(f"[{ 'PASS' if ok else 'FAIL'}] /v1/auth/me -> {c} {str(b)[:120]}")

# 3. Write a memory in local mode
c, b = req("POST", "/v1/agents/local-test/remember",
           {"key": "favorite_food", "value": "octopus"})
ok = c == 200 and b.get("success") is True
print(f"[{ 'PASS' if ok else 'FAIL'}] /remember -> {c} success={b.get('success')}")

# 4. Read it back via the actual /recall endpoint
c, b = req("GET", "/v1/agents/local-test/recall/favorite_food")
ok = c == 200 and ("octopus" in str(b))
print(f"[{ 'PASS' if ok else 'FAIL'}] /recall -> {c} body has 'octopus'={('octopus' in str(b))}")

# 5. List agents
c, b = req("GET", "/v1/agents")
agents = b.get("agents", [])
ok = c == 200 and len(agents) >= 1
print(f"[{ 'PASS' if ok else 'FAIL'}] /v1/agents -> {c} agents={len(agents)}")

# 6. Cleanup endpoint (audit fix #7a)
c, b = req("POST", "/v1/agents/local-test/cleanup")
ok = c == 200
print(f"[{ 'PASS' if ok else 'FAIL'}] /cleanup -> {c} {b}")

# 7. Bad key should still be rejected
c, b = req("GET", "/v1/auth/me", key="sk-octopoda-fake-key")
ok = c in (401, 403)
print(f"[{ 'PASS' if ok else 'FAIL'}] /v1/auth/me with bogus cloud key -> {c} (should reject)")

# Teardown
proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    proc.kill()
print()
print("done")
