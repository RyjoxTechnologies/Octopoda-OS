"""Dashboard asset smoke test — verifies the dashboard HTML actually
loads and every JS/CSS/image asset it references resolves (no 404s).

Runs against both:
  - The live cloud dashboard at app.octopodas.com (what real users see)
  - The local cloud_server.py started on a fresh PyPI install (what
    self-hosters see when they pip install octopoda[server])

Catches the most common dashboard-broke-between-releases failure:
index.html references a JS bundle filename that no longer ships in the wheel
(or no longer exists on the VPS). My earlier test suite didn't catch this
because it tested API behaviour in isolation.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

TARGETS = [
    ("cloud (live)", "https://octopodas.com"),
]
LOCAL_PORT = 8746


def fetch(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, "", {}
    except Exception as e:
        return None, str(e), {}


def head(url, timeout=10):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        # HEAD blocked, try GET
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, {}
        except Exception as e:
            return None, {"err": str(e)}


def parse_assets(html, base_url):
    """Find every <script src=...>, <link href=...>, <img src=...> and
    resolve to absolute URLs."""
    assets = []
    # script src=
    for m in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I):
        assets.append(("script", urllib.parse.urljoin(base_url, m.group(1))))
    # link href= (filter to css + icons, skip prefetch/preload to other origins)
    for m in re.finditer(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*>', html, re.I):
        href = m.group(1)
        if href.startswith("data:") or "fonts.googleapis" in href:
            continue
        assets.append(("link", urllib.parse.urljoin(base_url, href)))
    # img src=
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
        src = m.group(1)
        if src.startswith("data:"):
            continue
        assets.append(("img", urllib.parse.urljoin(base_url, src)))
    return assets


def run_target(name, base_url):
    print(f"\n--- target: {name} ({base_url}) ---")
    # Cloud dashboards usually serve the SPA at the root, but some setups
    # also have /dashboard. Try /dashboard first, then root.
    candidates = ["/dashboard", "/"]
    html = None
    final_url = None
    for path in candidates:
        url = base_url.rstrip("/") + path
        code, body, _ = fetch(url)
        if code == 200 and "<script" in body.lower():
            html = body
            final_url = url
            print(f"  fetched {url} -> 200 ({len(body)} bytes)")
            break
        print(f"  {url} -> {code}")
    if not html:
        return ("no-html", 0, 0)

    # Look for the typical app shell signal: <div id="root"> or "Octopoda"
    has_root = '<div id="root"' in html or 'id="app"' in html
    has_brand = "octopoda" in html.lower()
    print(f"  has_root_div={has_root}  has_brand_text={has_brand}")

    assets = parse_assets(html, final_url)
    print(f"  {len(assets)} asset references found")

    # HEAD every asset, report 404s
    ok = 0
    bad = []
    for kind, url in assets:
        code, _ = head(url, timeout=8)
        if code == 200:
            ok += 1
        else:
            bad.append((kind, url, code))

    print(f"  assets reachable: {ok}/{len(assets)}")
    for kind, url, code in bad[:8]:
        print(f"    BAD {code} {kind:>6}  {url}")
    if len(bad) > 8:
        print(f"    ... and {len(bad) - 8} more")
    return (name, ok, len(assets))


# Run live cloud first
results = []
for name, url in TARGETS:
    results.append(run_target(name, url))

# Now spin up local cloud_server with no DATABASE_URL and test the bundled dashboard
print("\n--- spinning up local cloud_server.py (from PyPI install) ---")
PYBIN = "C:/Users/user/AppData/Local/Temp/mcp-test/venv/Scripts/python.exe"
if not os.path.exists(PYBIN):
    print("  skip (PyPI venv not found, run user_simulation.py or mcp_stdio_harness.py first)")
else:
    DATA_DIR = "/tmp/dash-smoke-data"
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["OCTOPODA_LOCAL_MODE"] = "1"
    env["OCTOPODA_DATA_DIR"] = DATA_DIR

    proc = subprocess.Popen(
        [PYBIN, "-m", "uvicorn", "synrix_runtime.api.cloud_server:app",
         "--host", "127.0.0.1", "--port", str(LOCAL_PORT), "--log-level", "warning"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{LOCAL_PORT}/health", timeout=1).read()
            break
        except Exception:
            time.sleep(1)
    try:
        results.append(run_target("local (pip install)", f"http://127.0.0.1:{LOCAL_PORT}"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

print()
print("=" * 70)
print("DASHBOARD ASSET SMOKE SUMMARY")
print("=" * 70)
for name, ok, total in results:
    print(f"  {name:<30}  {ok}/{total} assets reachable")
all_ok = all(ok == total and total > 0 for _, ok, total in results)
print()
print(f"VERDICT: {'ALL GOOD' if all_ok else 'SOMETHING IS BROKEN'}")
sys.exit(0 if all_ok else 1)
