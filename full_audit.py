"""
Octopoda Full Launch Audit
Tests every real user journey end-to-end.
"""
import requests, json, time, sys, os, subprocess

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
RESULTS = []

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(f"  PASS  {name}")
    else:
        FAIL += 1
        RESULTS.append(f"  FAIL  {name} -- {detail}")

def post(path, data=None, headers=None):
    return requests.post(f"{BASE}{path}", json=data, headers=headers or {}, timeout=15)

def get(path, headers=None, params=None):
    return requests.get(f"{BASE}{path}", headers=headers or {}, params=params or {}, timeout=15)

def read_code(email):
    with open("/var/lib/octopoda/verification_codes.json") as f:
        codes = json.load(f)
    return codes.get(email, {}).get("code", "")

print("=" * 60)
print("OCTOPODA LAUNCH AUDIT")
print("=" * 60)

# 1. HEALTH
print("\n[1] HEALTH")
r = get("/health")
test("Health endpoint", r.status_code == 200)
test("Version is 3.0.3", r.json().get("version") == "3.0.3")

# 2. SIGNUP
print("\n[2] SIGNUP FLOW")
ts = int(time.time())
USER_A = f"audit-a-{ts}@example.com"
USER_B = f"audit-b-{ts}@example.com"

r = post("/v1/auth/signup", {"email": USER_A, "password": "AuditPass123!", "first_name": "Alice", "last_name": "Tester"})
test("Signup returns 200", r.status_code == 200)
data_a = r.json()
KEY_A = data_a.get("api_key", "")
test("Signup returns API key", KEY_A.startswith("sk-octopoda-"))
test("Signup returns tenant_id", bool(data_a.get("tenant_id")))
test("Plan is free", data_a.get("plan") == "free")
test("Email not verified yet", data_a.get("email_verified") == False)

r = post("/v1/auth/signup", {"email": USER_B, "password": "AuditPass456!", "first_name": "Bob", "last_name": "Tester"})
KEY_B = r.json().get("api_key", "")
test("User B signup", r.status_code == 200 and KEY_B.startswith("sk-octopoda-"))

# 3. EMAIL VERIFICATION
print("\n[3] EMAIL VERIFICATION")
H_A = {"Authorization": f"Bearer {KEY_A}"}
H_B = {"Authorization": f"Bearer {KEY_B}"}

r = get("/v1/settings", headers=H_A)
test("Unverified user blocked", r.status_code == 403 or "not verified" in r.json().get("detail", "").lower())

CODE_A = read_code(USER_A)
test("Verification code saved to disk", len(CODE_A) == 6, f"got: '{CODE_A}'")

r = post("/v1/auth/verify", {"email": USER_A, "code": "000000"})
test("Wrong code rejected", r.status_code == 400)

r = post("/v1/auth/verify", {"email": USER_A, "code": CODE_A})
test("Correct code accepted", r.status_code == 200 and r.json().get("verified") == True)

CODE_B = read_code(USER_B)
r = post("/v1/auth/verify", {"email": USER_B, "code": CODE_B})
test("User B verified", r.status_code == 200)

r = get("/v1/settings", headers=H_A)
test("Verified user can access settings", r.status_code == 200)

# 4. AGENT OPERATIONS
print("\n[4] AGENT OPERATIONS")
r = post("/v1/agents", {"agent_id": "my-agent"}, headers=H_A)
test("Register agent", r.status_code == 200 and r.json().get("status") == "running")

# 5. MEMORY
print("\n[5] MEMORY OPERATIONS")
r = post("/v1/agents/my-agent/remember", {"key": "name", "value": "Alice likes coffee"}, headers=H_A)
test("Remember", r.status_code == 200 and r.json().get("success") == True)

r = post("/v1/agents/my-agent/remember", {"key": "work", "value": "Alice works at Google as a senior engineer"}, headers=H_A)
test("Remember #2", r.status_code == 200)

r = post("/v1/agents/my-agent/remember", {"key": "hobby", "value": "Alice plays piano on weekends", "tags": ["personal", "hobby"]}, headers=H_A)
test("Remember with tags", r.status_code == 200)

r = get("/v1/agents/my-agent/recall/name", headers=H_A)
test("Recall returns correct value", r.status_code == 200 and "coffee" in str(r.json().get("value", "")))

r = get("/v1/agents/my-agent/recall/nonexistent_key", headers=H_A)
test("Recall missing key returns found=false", r.json().get("found") == False)

# 6. SEARCH
print("\n[6] SEARCH")
r = get("/v1/agents/my-agent/search", headers=H_A, params={"q": "where does Alice work", "limit": 5})
test("Search returns results", r.status_code == 200 and r.json().get("count", 0) >= 1)

# 7. MEMORY LIST
print("\n[7] MEMORY LIST")
r = get("/v1/agents/my-agent/memory", headers=H_A, params={"offset": 0, "limit": 50})
data = r.json()
test("Memory list returns items", r.status_code == 200 and data.get("count", 0) >= 3)
if data.get("items"):
    item = data["items"][0]
    test("Memory has tags field", "tags" in item)
    test("Memory has importance field", "importance" in item)
    test("Memory has version_count", "version_count" in item)
    test("Memory has created_at", "created_at" in item)

# 8. VERSION HISTORY
print("\n[8] VERSION HISTORY")
r = post("/v1/agents/my-agent/remember", {"key": "name", "value": "Alice likes tea now"}, headers=H_A)
r = get("/v1/agents/my-agent/history/name", headers=H_A)
test("History endpoint works", r.status_code == 200)
hist = r.json()
test("History shows multiple versions", hist.get("total_versions", 0) >= 2, f"got {hist.get('total_versions', 0)}")

# 9. LOOP DETECTION
print("\n[9] LOOP DETECTION")
r = get("/v1/agents/my-agent/loops/status", headers=H_A)
test("Loop status returns", r.status_code == 200)
test("Loop has severity field", "severity" in r.json())

# 10. SNAPSHOTS
print("\n[10] SNAPSHOTS")
r = post("/v1/agents/my-agent/snapshot", {}, headers=H_A)
test("Create snapshot", r.status_code == 200, f"got {r.status_code}: {r.text[:150]}")

r = get("/v1/agents/my-agent/snapshots", headers=H_A)
test("List snapshots", r.status_code == 200 and r.json().get("count", 0) >= 1, f"got {r.status_code}: {r.text[:150]}")

# 11. TENANT ISOLATION
print("\n[11] TENANT ISOLATION")
r = post("/v1/agents", {"agent_id": "my-agent"}, headers=H_B)
test("User B can create same agent name", r.status_code == 200)

r = post("/v1/agents/my-agent/remember", {"key": "name", "value": "Bob is different"}, headers=H_B)
test("User B can write", r.status_code == 200)

r = get("/v1/agents/my-agent/recall/name", headers=H_B)
val_b = str(r.json().get("value", ""))
test("User B sees own data not A's", "Bob" in val_b and "Alice" not in val_b, f"got: {val_b[:60]}")

r = get("/v1/agents/my-agent/recall/name", headers=H_A)
val_a = str(r.json().get("value", ""))
test("User A still sees own data", "tea" in val_a or "Alice" in val_a, f"got: {val_a[:60]}")

r = get("/v1/agents/my-agent/recall/work", headers=H_B)
test("User B cannot see A's work key", r.json().get("found") == False)

# 12. AGENT LIMITS
print("\n[12] AGENT LIMITS (free = 5)")
for i in range(4):
    post("/v1/agents", {"agent_id": f"limit-test-{i}"}, headers=H_B)

r = post("/v1/agents", {"agent_id": "one-too-many"}, headers=H_B)
test("6th agent blocked on free plan", r.status_code == 403, f"got {r.status_code}: {r.text[:100]}")
test("Error is 403 not 500", r.status_code != 500, f"got {r.status_code}")

# 13. EXTRACTION COUNTER
print("\n[13] EXTRACTION COUNTER")
r = get("/v1/settings", headers=H_A)
settings = r.json()
test("Settings show platform provider", settings.get("llm_provider") == "platform")
test("Extractions limit is 100", settings.get("platform_extractions_limit") == 100)

# 14. DISPOSABLE EMAIL
print("\n[14] DISPOSABLE EMAIL BLOCKING")
time.sleep(2)  # Wait for auth rate limiter to cool down
r = post("/v1/auth/signup", {"email": "test@tempmail.com", "password": "Test123!", "first_name": "X", "last_name": "Y"})
test("Disposable email blocked", r.status_code in (400, 422) or "disposable" in r.text.lower(), f"got {r.status_code}: {r.text[:100]}")

# 15. UNAUTHENTICATED ACCESS
print("\n[15] UNAUTHENTICATED ACCESS")
r = get("/v1/settings")
test("Settings without auth blocked", r.status_code in (401, 403))

r = post("/v1/agents/my-agent/remember", {"key": "hack", "value": "bad"})
test("Remember without auth blocked", r.status_code in (401, 403))

# 16. RATE LIMITING
print("\n[16] RATE LIMITING")
blocked = False
for i in range(25):
    r = post("/v1/auth/login", {"email": "spam@test.com", "password": "wrong"})
    if r.status_code == 429:
        blocked = True
        break
test("Auth rate limiting works", blocked, "never got 429")

# 17. SHARED MEMORY
print("\n[16] SHARED MEMORY")
r = post("/v1/shared/team-space", {"key": "shared-item", "value": "shared data", "author_agent_id": "my-agent"}, headers=H_A)
test("Shared memory write", r.status_code == 200, f"got {r.status_code}: {r.text[:100]}")

r = get("/v1/shared/team-space/shared-item", headers=H_A)
test("Shared memory read", r.status_code == 200 and r.json().get("found") == True, f"got {r.status_code}: {r.text[:100]}")

r = get("/v1/shared/team-space/shared-item", headers=H_B)
test("Shared memory isolated between tenants", r.json().get("found") == False, f"got: {r.text[:100]}")

# 18. SETTINGS ISOLATION
print("\n[18] SETTINGS ISOLATION")
r = requests.put(f"{BASE}/v1/settings", json={"llm_provider": "openai", "openai_api_key": "sk-fake-key"}, headers=H_A, timeout=15)
test("Can update settings", r.status_code == 200, f"got {r.status_code}: {r.text[:100]}")

r = get("/v1/settings", headers=H_B)
test("User B cannot see A's API key", "sk-fake" not in str(r.json()))

# RESULTS
print("\n" + "=" * 60)
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL}")
print("=" * 60)
for r in RESULTS:
    print(r)
print("=" * 60)
if FAIL > 0:
    print(f"\n!!! {FAIL} FAILURES -- FIX BEFORE LAUNCH !!!")
    sys.exit(1)
else:
    print("\nALL TESTS PASSED -- READY TO LAUNCH")
    sys.exit(0)
