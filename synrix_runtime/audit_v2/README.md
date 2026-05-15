# audit_v2

Octopoda's "black box recorder" for AI agents. Parallel-built, isolated from production. Not yet wired into the main app.

## What it does

Every time an agent does something — writes memory, reads memory, calls a tool, handles an OpenAI thread, gets a CrewAI finding — we record an audit event. Each event carries:

- `event_type` (e.g. `memory.write`, `tool.call`, `crew.finding`) — 19 canonical types
- `agent_id`, `source` (sdk/langchain/crewai/autogen/openai/mcp)
- `key`, `value_preview` (PII-redacted, 240-char cap)
- `cost_usd` (from `cost_models.MODEL_COSTS` + tenant's `llm_model`)
- `tokens_in`, `tokens_out`, `latency_ms`
- `outcome` (success/fail/timeout)
- `tags`, `session_id`, `user_id`, `extra`
- `prev_hash` (SHA-256 tamper-evident chain per tenant)
- `timestamp` (unix, microsecond precision)

## What's in this module

| File | What |
|---|---|
| `models.py` | `AuditEvent` dataclass + event-type enum + PII redaction + storage-key format |
| `storage.py` | Postgres read/write via existing `nodes` table (RLS-isolated) |
| `sdk_hooks.py` | `instrument(runtime)` — wraps `remember/recall/share/forget/etc` on an `AgentRuntime` |
| `framework_hooks.py` | `instrument_memory(mem)` — wraps `CrewAIMemory/AutoGenMemory/OpenAIAgentsMemory/LangChain` |
| `mcp_hooks.py` | `instrument_mcp(mcp)` — patches `FastMCP._tool_manager.call_tool` |
| `cost.py` | `estimate_cost(tenant, event_type)` via `cost_models.py` |
| `api.py` | FastAPI router: `/events`, `/events/{id}`, `/context`, `/verify`, `/cost`, `/export` |
| `__init__.py` | Public entry points: `log()`, `list_events()`, `count_events()`, etc. |

## Storage model

We reuse the existing `nodes` table (no schema migration needed):

- `name`: `auditv2:<tenant_prefix>:<agent_id>:<timestamp_us>:<event_type>`
- `data`: full event payload as JSONB (includes `prev_hash` and `_this_hash`)
- `metadata`: `{"source_module": "audit_v2", "event_type": ..., "source": ...}`
- `tenant_id`: standard RLS-enforced column
- `valid_from`: event timestamp (seconds since epoch)
- `valid_until`: 0 (audit events are immutable)

## Test results

| Test file | Cases | Status |
|---|---|---|
| `tests/audit_v2/test_unit.py` | 22 | all pass |
| `tests/audit_v2/test_integration.py` | 10 | all pass |
| `tests/audit_v2/test_sdk_hooks_e2e.py` | 1 | pass (10 events, 7 types, chain OK) |
| `tests/audit_v2/test_framework_e2e.py` | 4 | all pass (CrewAI, AutoGen, OpenAI, chain) |
| `tests/audit_v2/test_mcp_e2e.py` | 2 | all pass (3 tool calls: 2 success, 1 fail) |
| `tests/audit_v2/test_api_e2e.py` | 6 | all pass (list, get, context, verify, cost, CSV, auth) |

## Integration checklist (when ready)

Each of these is one line in the production codebase. None have been applied yet.

### 1. SDK auto-instrument — `synrix_runtime/api/runtime.py`

Add to `AgentRuntime.__init__` (after all other setup):

```python
if os.environ.get("OCTOPODA_AUDIT_V2", "").lower() in ("1", "true"):
    try:
        from synrix_runtime.audit_v2.sdk_hooks import instrument
        instrument(self)
    except Exception:
        pass
```

### 2. Framework auto-instrument — `octopoda/__init__.py`

Wrap the `__new__` methods:

```python
class CrewAIMemory:
    def __new__(cls, crew_id="default_crew", **kwargs):
        from synrix_runtime.integrations.crewai_memory import SynrixCrewMemory
        if "backend" not in kwargs:
            kwargs["backend"] = _get_backend_auto()
        instance = SynrixCrewMemory(crew_id=crew_id, **kwargs)
        if os.environ.get("OCTOPODA_AUDIT_V2", "").lower() in ("1", "true"):
            from synrix_runtime.audit_v2.framework_hooks import instrument_memory
            instance = instrument_memory(instance)
        return instance
```

Same pattern for `LangChainMemory`, `AutoGenMemory`, `OpenAIAgentsMemory`.

### 3. MCP auto-instrument — `synrix_runtime/api/mcp_server.py`

Add after the `mcp = FastMCP("Octopoda Memory")` line:

```python
if os.environ.get("OCTOPODA_AUDIT_V2", "").lower() in ("1", "true"):
    try:
        from synrix_runtime.audit_v2.mcp_hooks import instrument_mcp
        instrument_mcp(mcp)
    except Exception:
        pass
```

### 4. Mount the API router — `synrix_runtime/api/cloud_server.py`

Near the top of the file, after FastAPI app is created:

```python
if os.environ.get("OCTOPODA_AUDIT_V2", "").lower() in ("1", "true"):
    try:
        from synrix_runtime.audit_v2.api import build_router
        app.include_router(build_router(), prefix="/v1/audit_v2")
    except Exception as e:
        logger.warning(f"audit_v2 router not mounted: {e}")
```

### 5. Feature flag

Set `OCTOPODA_AUDIT_V2=1` on the VPS env to enable. Unset / set to `0` to disable.

```bash
# Enable for the ryjoxtechnologies tenant only (requires tenant-aware flag)
# ... or just globally once validated:
echo 'OCTOPODA_AUDIT_V2=1' >> /root/octopoda/.env
systemctl restart octopoda
```

## Rollback

If anything misbehaves:

1. `unset OCTOPODA_AUDIT_V2` in `.env`
2. `systemctl restart octopoda`
3. All audit-v2 code paths are now inert; prod behaviour restored.
4. Data in the `nodes` table keyed `auditv2:*` remains (read-only; cleanup is optional).

## Future work (not yet built)

- **LangChain adapter e2e test** — wrapper code exists, but running it requires live langchain_core imports. Pattern identical to the other frameworks.
- **Token counting** — `tokens_in` / `tokens_out` currently always 0. Needs hook into the LLM client. Phase 5a on the roadmap.
- **Real-time streaming** — the dashboard could subscribe via SSE. Not needed for v1.
- **Decision synthesis** — heuristic that groups recall+write+LLM within a 5s window into a synthetic `decision` event. Phase 6 on the roadmap.
- **Policies + alerts** — YAML rules like "alert if cost_usd > X". Phase 8 on the roadmap.

## How to run the full test suite

From the audit-v2 worktree root:

```bash
cd /root/octopoda-audit-v2
set -a; . /root/octopoda/.env; set +a
export OCTOPODA_API_KEY='sk-octopoda-...'

venv/bin/python3 tests/audit_v2/test_unit.py              # 22 tests, no DB
venv/bin/python3 tests/audit_v2/test_integration.py       # 10 tests, real DB
venv/bin/python3 tests/audit_v2/test_sdk_hooks_e2e.py     # cloud SDK round-trip
venv/bin/python3 tests/audit_v2/test_framework_e2e.py     # CrewAI/AutoGen/OpenAI
venv/bin/python3 tests/audit_v2/test_mcp_e2e.py           # FastMCP middleware
venv/bin/python3 tests/audit_v2/test_api_e2e.py           # FastAPI TestClient
```

All 45 test cases currently pass.
