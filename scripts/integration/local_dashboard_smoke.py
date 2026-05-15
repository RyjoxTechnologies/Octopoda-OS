"""Local dashboard UI smoke test — the Flask app on :7842 that local users
see when they pip install octopoda and run the `octopoda` CLI.

Tests:
  1. Can we start the dashboard at all without DATABASE_URL?
  2. Does GET / return the index.html?
  3. Does it reference the same assets as the live cloud dashboard?
  4. Do those assets resolve from the local Flask server (no 404)?
"""
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

PYBIN = "C:/Users/user/AppData/Local/Temp/mcp-test/venv/Scripts/python.exe"
DATA_DIR = "/tmp/local-dash-data"
DASH_PORT = "7843"
API_PORT = "8747"


def fetch(url, timeout=8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), int(r.headers.get("Content-Length", "0"))
    except urllib.error.HTTPError as e:
        return e.code, "", 0
    except Exception as e:
        return None, str(e), 0


def head(url, timeout=6):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout) as r:
            return r.status, int(r.headers.get("Content-Length", "0"))
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception:
        # Some servers reject HEAD — fall back to range-GET
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, int(r.headers.get("Content-Length", "0"))
        except urllib.error.HTTPError as e:
            return e.code, 0
        except Exception as e:
            return None, 0


if not os.path.exists(PYBIN):
    print(f"ERROR: PyPI venv not found at {PYBIN}")
    print("Run mcp_stdio_harness.py first to set it up.")
    sys.exit(1)

shutil.rmtree(DATA_DIR, ignore_errors=True)
os.makedirs(DATA_DIR, exist_ok=True)

env = os.environ.copy()
env.pop("DATABASE_URL", None)
env["OCTOPODA_LOCAL_MODE"] = "1"
env["OCTOPODA_DATA_DIR"] = DATA_DIR
env["OCTOPODA_API_KEY"] = "local"

print("=" * 70)
print("LOCAL DASHBOARD UI SMOKE TEST")
print("=" * 70)
print(f"Spawning: {PYBIN} -m synrix_runtime.start --no-browser")
print(f"  Dashboard port: {DASH_PORT}")
print(f"  API port:       {API_PORT}")
print()

proc = subprocess.Popen(
    [PYBIN, "-m", "synrix_runtime.start",
     "--no-browser", "--port", DASH_PORT, "--api-port", API_PORT],
    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)

print("Waiting for dashboard...")
ready = False
for i in range(45):
    try:
        code, body, _ = fetch(f"http://127.0.0.1:{DASH_PORT}/")
        if code == 200:
            print(f"  ready after {i+1}s")
            ready = True
            break
    except Exception:
        pass
    time.sleep(1)

if not ready:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
    except Exception:
        proc.kill()
        out = ""
    print(f"  DASHBOARD NEVER STARTED. Last server output (tail):")
    print(out[-2000:])
    sys.exit(1)

results = []

# Test 1: index.html loads
code, html, _ = fetch(f"http://127.0.0.1:{DASH_PORT}/")
ok = code == 200 and len(html) > 100 and ("<div id=\"root\"" in html or "Octopoda" in html)
print(f"  [{'PASS' if ok else 'FAIL'}] GET / -> {code} ({len(html)} bytes)")
results.append(("GET /", ok))

# Test 2: find asset references in the HTML and compare to live cloud
asset_refs = re.findall(r'(?:src|href)=["\'](/assets/[^"\']+)["\']', html)
print(f"  [INFO] {len(asset_refs)} asset references found")
print(f"         examples: {asset_refs[:3]}")

# Test 3: compare against live cloud dashboard — should reference same files
try:
    _, cloud_html, _ = fetch("https://octopodas.com/dashboard")
    cloud_refs = set(re.findall(r'(?:src|href)=["\'](/assets/[^"\']+)["\']', cloud_html))
    local_refs = set(asset_refs)
    overlap = cloud_refs & local_refs
    same = cloud_refs == local_refs
    print(f"  [{'PASS' if same else 'FAIL'}] local asset refs match live cloud "
          f"(overlap={len(overlap)}, local-only={local_refs-cloud_refs}, cloud-only={cloud_refs-local_refs})")
    results.append(("asset refs match cloud", same))
except Exception as e:
    print(f"  [SKIP] cloud comparison failed: {e}")

# Test 4: every asset the local dashboard references actually resolves (no 404)
ok_count = 0
bad_count = 0
bad_details = []
for ref in asset_refs:
    url = f"http://127.0.0.1:{DASH_PORT}{ref}"
    code, size = head(url)
    if code == 200:
        ok_count += 1
    else:
        bad_count += 1
        bad_details.append((ref, code))
ok = bad_count == 0 and ok_count > 0
print(f"  [{'PASS' if ok else 'FAIL'}] all local assets resolve: {ok_count}/{ok_count+bad_count}")
for ref, code in bad_details[:5]:
    print(f"    BAD {code} {ref}")
results.append(("local assets resolve", ok))

# Test 5: a real-content asset spot check — fetch the JS bundle, verify it's >100KB
js_ref = next((r for r in asset_refs if r.endswith(".js")), None)
if js_ref:
    code, size = head(f"http://127.0.0.1:{DASH_PORT}{js_ref}")
    ok = code == 200 and size > 100_000
    print(f"  [{'PASS' if ok else 'FAIL'}] main JS bundle {js_ref} -> {code}, {size} bytes")
    results.append(("js bundle large", ok))

# Test 6: API health alongside dashboard
code, body, _ = fetch(f"http://127.0.0.1:{API_PORT}/health")
ok = code == 200 and "ok" in body.lower()
print(f"  [{'PASS' if ok else 'FAIL'}] sibling API on :{API_PORT}/health -> {code}")
results.append(("API healthy", ok))

# Teardown
proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    proc.kill()

print()
print("=" * 70)
passes = sum(1 for _, v in results if v)
print(f"LOCAL DASHBOARD SMOKE: {passes}/{len(results)} PASS")
print("=" * 70)
sys.exit(0 if passes == len(results) else 1)
