# audit_v2 — how to see it working

This is a demo artifact. The standalone viewer is a self-contained FastAPI
app + vanilla-JS dashboard that reads from the audit_v2 backend. It's
completely separate from the production Octopoda API and dashboard.

## Running the viewer

### On the VPS

```bash
# Once - audit-v2 is already at /root/octopoda-audit-v2
cd /root/octopoda-audit-v2
set -a; source /root/octopoda/.env; set +a
export OCTOPODA_API_KEY='sk-octopoda-...'
export PYTHONPATH=/root/octopoda-audit-v2
/root/octopoda/venv/bin/python3 -m synrix_runtime.audit_v2.standalone --port 8765
```

You'll see:

    audit_v2 standalone viewer starting on http://127.0.0.1:8765
      Open in browser: http://127.0.0.1:8765/

The viewer listens on **localhost only** (127.0.0.1) - it is not exposed
to the public internet. To reach it from your laptop, tunnel with SSH:

```bash
# on your laptop
ssh -i ~/.ssh/octopoda_deploy -L 8765:127.0.0.1:8765 root@104.238.184.255
# then, in your browser:  http://127.0.0.1:8765/
```

Paste your Octopoda API key into the top bar and hit **Connect**.

### On a dev laptop (no VPS needed)

```bash
git checkout audit-v2
pip install -e .
pip install fastapi uvicorn psycopg2-binary  # if not already installed
export DATABASE_URL='postgresql://...'         # point at the real DB
export OCTOPODA_API_KEY='sk-octopoda-...'
python -m synrix_runtime.audit_v2.standalone
```

## What you'll see

1. **Top bar**: API key input + connect button
2. **Sidebar**: filters (agent, event type, time range, search) + buttons
3. **Timeline**: colored pills for each event type, content line,
   cost in $, latency in ms, relative time
4. **Click any event**: detail panel opens on the right showing:
   - Summary (type, agent, source, timestamp, latency, cost, outcome)
   - Key, value preview
   - Tags
   - Integrity (prev_hash / this_hash)
   - Extra fields
   - **Story around this event**: the 5 events before and 5 after
5. **Verify integrity** button: walks the hash chain, green check if intact
6. **Export CSV** button: downloads matching events as CSV
7. **Top spenders** panel: live cost rollup per agent

## Producing some test data

If your tenant has no audit events yet, seed some with this script:

```python
import os, time
os.environ['OCTOPODA_API_KEY'] = 'sk-octopoda-...'
from octopoda import AgentRuntime
from synrix_runtime.audit_v2.sdk_hooks import instrument
from synrix_runtime.audit_v2 import cost as _c
_c._get_llm_model = lambda tid: 'gpt-4o-mini'   # pretend you've set a model

rt = AgentRuntime('demo-agent', agent_type='cloud')
instrument(rt, tenant_id='YOUR_TENANT_ID')
rt.remember('customer:alex:plan', 'pro_monthly')
rt.recall('customer:alex:plan')
rt.remember_important('policy:refund', '7-day window, prorated refund',
                       tags=['policy', 'critical'])
rt.recall_similar('refund policy', limit=3)
rt.share('team-note', {'note': 'audit is live'})
rt.forget('customer:alex:plan')
```

Each call emits an audit event. Refresh the viewer and you'll see them.

## Running the decision synthesiser

After seeding some events, produce synthetic `decision` rows:

```python
from synrix_runtime.audit_v2.decisions import synthesize_decisions
result = synthesize_decisions('YOUR_TENANT_ID', agent_id='demo-agent')
print(result)
# {'synthesised': N, 'windows_considered': M, 'events_scanned': K, ...}
```

Then refresh the viewer with event type filter = `decision` to see them.

## Cleanup

The test agents we created are scoped with names like `audit-e2e-*`,
`audit-mcp-*`, `audit-fw-*`. To remove:

```python
from synrix_runtime.audit_v2 import delete_agent_events
delete_agent_events('YOUR_TENANT_ID', 'demo-agent')
```

## Stopping the viewer

```bash
# find and kill
ps aux | grep 'audit_v2.standalone'
kill <pid>
```

## Things that are NOT this

- This is NOT the production Octopoda dashboard.
- This is NOT wired to `octopodas.com/dashboard`.
- This runs on port 8765 on `127.0.0.1` only.
- Nothing in your production setup changes when you start or stop it.

## Integration path (later)

When you're ready to move the audit v2 features into the main product:

1. Apply the 4 one-line changes from `audit_v2/README.md` § "Integration checklist"
2. Set `OCTOPODA_AUDIT_V2=1` in the VPS env
3. Restart `octopoda.service`
4. Build Lovable UI against `GET /v1/audit_v2/*` on the main API

At that point the standalone viewer can be retired - the main dashboard
will serve the same data on the same endpoints.
