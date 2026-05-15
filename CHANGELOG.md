# Changelog

## 3.1.9 (2026-05-15)

Follow-up to 3.1.8 — addresses the cloud-side findings from the May 2026 audit.

### `DELETE /v1/agents/{agent_id}?purge=true` — real hard delete

Previously the DELETE endpoint only soft-deleted (set state to `deregistered`, data preserved). Auditor flagged that as a GDPR Article 17 / CCPA delete-on-request blocker. Now accepts `?purge=true` query param. When set, physically removes every row the agent ever produced across five namespaces:

- `runtime:agents:{agent_id}`
- `agents:{agent_id}`
- `metrics:{agent_id}`
- `auditv2:{tenant_short}:{agent_id}`
- `audit:{agent_id}`

Response includes `rows_deleted` total + `by_namespace` breakdown so callers can verify what got removed.

### `POST /v1/agents/{agent_id}/decision` now mirrors to audit-v2 hash chain

Previously the SDK `log_decision()` call wrote a row in the legacy `audit:*` namespace without a hash chain. Auditor pointed out that the README's "tamper-evident hash chain" claim wasn't true on the default decision-logging path. Now every `log_decision()` call ALSO writes a hash-chained row via `auditv2.log(event_type="decision", ...)`, returning the new `audit_v2_row_id` in the response so callers can verify the chain. The legacy `audit:` row continues to be written for backwards compat with any consumer reading it.

This means: every decision logged via the SDK is now provably part of the per-agent hash chain, queryable via `GET /v1/auditv2/events?agent_id=X` and verifiable via `GET /v1/auditv2/verify-chain`. The marketing claim is now true on the default code path.

### Regressions

- `tests/test_mcp_local_adapter.py`: 13/13 pass
- `tests/test_gc.py`: 10/10 pass
- `tests/test_runtime_version_cap.py`: 6/6 pass
- `tests/ci_smoke.py`: 6/6 pass

## 3.1.8 (2026-05-15)

### Local-mode audit response — MCP server gets parity with HTTP API

A detailed third-party audit (May 10, 2026) of Octopoda local-mode found that of 16 MCP tools probed, **6 threw `AttributeError`**, **1 returned silently-wrong results** (`recall_similar` → empty), and **1 reported inconsistent state**. Root cause: `synrix_runtime/api/mcp_server.py` shipped a parallel `_LocalAgentAdapter` that wrapped `AgentRuntime` but never exposed the methods (`get_loop_status`, `get_loop_history`, `memory_health`, `set_goal`, `get_goal`, `update_progress`, `send_message`, `read_messages`, `broadcast`, `forget`, `consolidate`, `related`, `get_context`, `process_conversation`) that `AgentRuntime` itself implements. This release fixes that.

- **`_LocalAgentAdapter` now exposes every method the MCP tools call.** All 6 previously-broken tools (`octopoda_loop_status`, `octopoda_loop_history`, `octopoda_memory_health`, `octopoda_set_goal`, `octopoda_send_message`, `octopoda_read_messages`) return real results.
- **`recall_similar` now actually does semantic search.** Adapter's `search()` was routing through `rt.search()` (keyword/prefix); now routes through `rt.recall_similar()` (embedding-based). Falls back to keyword search cleanly if the `[ai]` extra isn't installed.
- **`consolidate()` defaults to `dry_run=False`** in the MCP adapter. The loop-detector signal recommends `consolidate()` as remediation; with `dry_run=True` as the default it was a no-op. Now actually consolidates.
- **`log_decision.context` accepts `dict | str | None`.** Previously typed as `str | None` but the MCP framework auto-parses JSON-shaped strings into dicts before validation, so the docs literally told you to pass JSON and pydantic rejected it.
- Added regression suite (`tests/test_mcp_local_adapter.py`, 13 tests) covering every previously-broken tool plus the local sentinel logic.

### Local-mode sentinels — stop hanging on cloud auth for non-keys

Previously the only honored local sentinel was `YOUR_KEY_HERE`. Anything else — including the natural `local`, `offline`, `dev`, `none`, or even empty string when surrounded by whitespace — was passed to the cloud as a real API key and hung for 10s on auth before failing. The audit reported ~30 minutes of debugging caused by this single ambiguity.

- All of `local`, `offline`, `dev`, `none`, `""`, and `YOUR_KEY_HERE` (case-insensitive) are now local-mode sentinels.
- Honors `OCTOPODA_LOCAL_MODE=1` to force local mode regardless of `OCTOPODA_API_KEY`.
- Anything that doesn't start with `sk-octopoda-` and isn't a known sentinel falls back to local mode with a clear stderr warning, rather than hanging on cloud auth.

### README — scope claims to what's actually shipped

The audit flagged several README claims as unsubstantiated by the code shipped on the default path. This release scopes them honestly:

- **"Tamper-evident hash chain"** is now scoped explicitly to the audit-v2 endpoints (`POST /v1/auditv2/log`, `GET /v1/auditv2/events`, `GET /v1/auditv2/verify-chain`). The legacy `log_decision()` SDK call writes a simpler audit row without the chain — documented as such.
- **"Drift tracking / Goal alignment with deviation alerts"** removed. The drift sampler does not currently run; only goal storage is supported. Will be reinstated when the sampler ships.
- **"5-signal loop engine"** still accurate (retry, oscillation, ping-pong, reflection, recall-write); the cost signal is documented as requiring agent model registration to populate.
- **"Catches before it burns through the budget overnight"** softened — detection is automatic, intervention is opt-in via the v2 circuit-breaker config.
- Storage path documented at `~/.synrix/data/synrix.db` (previously the README mentioned `~/.octopoda/`).
- Added Claude Code MCP env-cache restart caveat.

### Configuration env vars added to README

- `OCTOPODA_LOCAL_MODE` (force local)
- `SYNRIX_HEARTBEAT_INTERVAL_SEC` (daemon polling cadence)
- `SYNRIX_MAX_VERSIONS_PER_RUNTIME_KEY` (schema-level version cap)

### Credits

Most of the fixes in this release come from a detailed third-party audit. The auditor methodically exercised every MCP tool, every HTTP endpoint, the local SQLite layer, the dashboard, the v2 circuit-breaker, the drift sampler, and the cloud — including head-to-head comparisons. The result was a 1,400-line report that pinpointed exactly which line in `mcp_server.py` needed to change and why. Thank you for the rigour.

## 3.1.7 (2026-05-08)

### Schema-level version cap for runtime/metrics keys
Issue #6 follow-up. The 3.1.6 GC fix prunes `runtime:agents:*` every 6 hours but each heartbeat still creates a new row between cycles, so the table can gain ~70K rows during the gap before the next GC catches up. This release adds an `AFTER INSERT` trigger directly to the SQLite schema that caps each `runtime:*` and `metrics:*` key to its 10 most-recent versions on every write. The cap fires inline so the table never grows past steady state. Configurable via `SYNRIX_MAX_VERSIONS_PER_RUNTIME_KEY`. User memory keys (`agents:*`) are explicitly excluded — their full version history is preserved for `recall_history()`. Credit to @Dvalin21 in issue #6 for the trigger pattern and end-to-end validation.

### Daemon thread intervals now configurable
Hardcoded 3s / 5s / 10s polling on heartbeat / anomaly / metrics / recovery loops was too aggressive for low-resource boxes and contributed to the SQLite contention reported in issue #6. All four are now env-configurable, defaults unchanged for backward compatibility:
- `SYNRIX_HEARTBEAT_INTERVAL_SEC` (default 3)
- `SYNRIX_ANOMALY_INTERVAL_SEC` (default 5)
- `SYNRIX_METRICS_INTERVAL_SEC` (default 10)
- `SYNRIX_RECOVERY_INTERVAL_SEC` (default 5)

For long-running local deployments the recommended values are 15 / 30 / 60 / 30 seconds — that's the configuration validated to drop CPU from 184% to 7-8% in the issue thread.

### FTS5 cleanup trigger
Companion `AFTER DELETE` trigger now removes corresponding `nodes_fts` rows when nodes are pruned, fixing the stale-FTS-content issue (4.2M FTS rows for 133K live nodes in the original report).

### Test coverage
New `tests/test_runtime_version_cap.py` verifies: runtime/metrics caps, user-memory bypass, per-key independence, env-var override, FTS cleanup. 6/6 passing.

## 3.1.6 (2026-05-08)

### Critical bugfix — local SQLite unbounded growth
- `runtime:agents:*` heartbeat and state writes were never being garbage-collected. Each agent writes ~3 rows/sec to this prefix; without GC the SQLite `nodes` table grew unboundedly, eventually causing background-thread queries to spin CPU and freeze the daemon. One reported case had this single prefix at 2.2M of 4.1M total rows. Now pruned by default (`runtime_agents_days=1`, configurable via `SYNRIX_GC_RUNTIME_AGENTS_DAYS`). Fixes #6.
- Existing local DBs that already grew past a few hundred thousand rows will see significant cleanup on the first GC cycle after upgrade. Plan for that cycle to take a few extra seconds; subsequent cycles return to normal.

### Audit chain integrity
- `verify_chain` now tracks expected `prev_hash` per agent rather than globally, fixing a long-standing false negative when the global view crossed agent boundaries. Returns a `by_agent` breakdown alongside the overall result. The historical chain was always intact; only the verifier was wrong.

### Misc
- All package `__version__` constants now match `pyproject.toml`. They had drifted across `octopoda`, `synrix`, `synrix_runtime` historically (3.1.4 / 3.1.0 / 3.1.0).
- README updated with the full MCP tool reference (the actual exposed names after `claude mcp add octopoda`), the Python version note for the `[mcp]` extra, and the local dashboard hero screenshot refreshed.
- CI smoke matrix dropped Python 3.9 because `mcp>=1.0.0` requires Python 3.10+. Core `octopoda` still installs on 3.9 — only the optional `[mcp]` extra needs 3.10+.
- CI test assertions updated for the rebrand (`SYNRIX_LICENSE_KEY` → `OCTOPODA_LICENSE_KEY`, `synrix.io/pricing` → `octopodas.com/pricing`, version-pinning removed from `test_health`).

## 3.1.1 (2026-04-17)

### Critical bugfix — fixes silent activation failures
Two production bugs were silently blocking ~67% of new users from writing their first memory. Audit found 11 silent-failure sites total. This release:

- **Null-byte write corruption fixed.** `add_node` silently failed whenever user data contained `\u0000` (common in LLM output, byte-level tokenizer artifacts, binary-ish data). Postgres JSONB rejects `\u0000` even though it's legal JSON; the old error handler caught it, logged to a channel nobody watched, and returned None — the write *appeared* to succeed but nothing was stored. Fixed two ways:
  1. `_sanitize_for_pg_json()` strips `\u0000` before INSERT.
  2. A psycopg2 string-adapter registered at pool init strips NUL bytes from *every* string en route to Postgres. Belt-and-braces defense that prevents any future call site from regressing.
- **Timeline 500 error fixed.** `GET /v1/agents/{id}/timeline` and `/checkpoints` crashed with `TypeError: '<' not supported between 'str' and 'int'` when events had mixed timestamp types. Sort keys now coerce to float with 0.0 fallback.
- **Stripe webhook hardening.** Signature parser now rejects missing/malformed `Stripe-Signature` headers cleanly instead of crashing into the error path.

### Knowledge-graph reliability
- `_store_extraction` previously silently dropped relationships whenever entity writes failed (returned 0). Now every failed entity/relationship logs with context (name, type, source_node_id), and a summary line is emitted for any batch where failures occurred. KG pipeline is no longer invisible.

### Observability
- Added `_report_to_sentry()` helper used by every caught-and-swallowed DB-write exception in `postgres_client.py` (add_fact_embeddings, update_node_embedding, upsert_entity, add_relationship). Failures now surface in Sentry with `db_op` + `tenant_id` tags.
- Added `_capture_silent()` helper for the server-side non-blocking paths (licensing tracking, auto-snapshot, brain monitoring, TTL cleanup). These still don't block the user request but now surface in Sentry.
- Richer SDK-layer logging in `agent_backend.py` (3 sites previously had `except Exception: return 0` with zero logging).

### New admin endpoints
- `GET /v1/admin/activation` — cohort activation report (signups vs verified vs api-used vs actually-wrote-memory, per 24h/7d/30d/all-time window). Health flagged as `critical` when <10% activation, `degraded` <20%, `healthy` >=20%. Built on a new `admin_cohort_activation()` SECURITY DEFINER function so it bypasses RLS cleanly.
- `GET /v1/admin/health` — end-to-end smoke test that exercises register → write-with-null-byte → recall → shared → log_decision → snapshot → cleanup. Regression canary for the null-byte bug and every critical write path. Run manually or from a cron.
- `GET /v1/admin/billing/overview` — paid tenants, MRR/ARR, recent Stripe events (shipped in 3.1.0, documented here).

### Billing emails (shipped mid-3.1.0, documented here)
- Customer emails on: upgrade (welcome), cancellation (confirmation), payment failure (warning).
- Owner notifications to `OWNER_NOTIFICATION_EMAIL` env (default `joe@octopodas.com`) on: upgrade, plan change, cancellation, payment failure.
- All sends are best-effort (wrapped in try/except, never break the webhook response).

### Schema additions
- `tenants.stripe_customer_id`, `tenants.stripe_subscription_id` — added via `ALTER TABLE IF NOT EXISTS` and in `init.sql`. Without these, `_upgrade_tenant()` would crash on the SQL UPDATE after a real payment and silently leave the customer on `free` tier.

---

## 3.1.0 (2026-04-16)

### Highlights since 3.0.9

**Neural Brain — 3D Agent Visualization** (new hero feature)

Real-time 3D view of agent activity powered by react-force-graph-3d with Three.js bloom post-processing. Every memory write, decision, loop alert, and cross-agent write becomes a node. Click any node to see the full event with its memory snapshot. Time scrubber replays any 24h window. Mobile fallback to 2D force graph. Backed by 9 `/v1/brain/*` endpoints.

**Integration kwargs now work** — three documented parameters that were silently accepted via `**kwargs` and ignored:
- `LangChainMemory(session_id=...)` — each session_id now gets isolated message storage. `RunnableWithMessageHistory` multi-session patterns work correctly.
- `LangChainMemory(return_messages=True)` — returns `list[HumanMessage | AIMessage]` instead of a concatenated string. Required for chat models.
- `CrewAIMemory(crew_name=...)` — was raising `TypeError`. Now accepted as an optional identifier.

**MCP client fixes** (affects every Claude Desktop / Cursor / Windsurf user):
- Fixed base URL typo `api.octapodas.com` → `api.octopodas.com` (previously worked by DNS accident)
- Non-2xx API responses now raise descriptive errors. Silent swallow was hiding 403 "agent limit reached" — users hit the free-tier 5-agent cap, every `remember` call reported success, but nothing was stored. That path is now loud.
- Install: `pip install octopoda[mcp]` (bare install didn't include the `mcp` Python package).

**Bundled dashboard updated** — the `synrix_runtime/dashboard/static/` shipped with the wheel now matches octopodas.com: Neural Brain, Audit Trail, Shared Memory tabs. Previous wheels shipped an April 8 build.

**Documentation** — README redesigned with Neural Brain screenshot, dedicated Audit Trail and Shared Memory sections, collapsed framework integrations. 8 stale pre-Octopoda-era docs removed. Every README code block verified end-to-end against the live SDK with real LangChain/CrewAI/AutoGen/OpenAI Agents calls.

### New Features

**Agent-to-Agent Messaging** — Agents can send messages, read inboxes, broadcast to all agents. Enables real multi-agent coordination without shared databases.
- `agent.send_message(to_agent, message)`, `agent.read_messages()`, `agent.broadcast(message)`
- API: `POST /v1/agents/{id}/messages/send`, `GET /inbox`, `POST /broadcast`
- MCP: `octopoda_send_message`, `octopoda_read_messages`, `octopoda_broadcast`

**Memory Forgetting** — Targeted memory deletion for agents that accumulate too much data.
- `agent.forget(key)`, `agent.forget_by_tag(tag)`, `agent.forget_stale(days)`
- API: `POST /v1/agents/{id}/forget`, `POST /forget/stale`
- MCP: `octopoda_forget`

**Memory Consolidation** — Find and merge semantically duplicate memories.
- `agent.consolidate(dry_run=True)` — preview before committing
- API: `POST /v1/agents/{id}/consolidate`
- MCP: `octopoda_consolidate`

**Memory Summarization** — Compress old detailed memories into daily summaries. Originals preserved.
- `agent.summarize_old_memories(older_than_days=7)`
- API: `POST /v1/agents/{id}/summarize`
- MCP: `octopoda_summarize`

**Goal Tracking** — Set goals with milestones, track progress, integrates with drift detection.
- `agent.set_goal(goal, milestones)`, `agent.update_progress()`, `agent.get_goal()`
- API: `POST/GET /v1/agents/{id}/goal`, `POST /goal/progress`
- MCP: `octopoda_set_goal`, `octopoda_get_goal`, `octopoda_update_progress`

**Memory Export/Import** — Portable JSON bundles for migration, backup, and agent cloning.
- `agent.export_memories()`, `agent.import_memories(bundle)`
- API: `GET /v1/agents/{id}/export`, `POST /import`

**Auto-Tagging** — Automatically categorize memories using semantic similarity.
- `agent.auto_tag(categories=["preference", "fact", "task"])`
- API: `POST /v1/agents/{id}/auto-tag`

**Filtered Search** — Combine semantic query with tags, importance, and time range filters.
- `agent.search_filtered(query="...", tags=["..."], importance="critical", max_age_seconds=86400)`
- API: `POST /v1/agents/{id}/search/filtered`
- MCP: `octopoda_search_filtered`

**Memory Health Scoring** — Automated diagnostics with 0-100 score and actionable recommendations.
- `agent.memory_health()`
- API: `GET /v1/agents/{id}/health`
- MCP: `octopoda_memory_health`

**Confidence Decay** — Recall with time-based relevance. Newer and frequently accessed memories rank higher.
- `agent.recall_with_confidence(key)`
- API: `GET /v1/agents/{id}/recall/confident`

**Shared Memory Conflict Detection** — Detect when agents overwrite each other in shared spaces.
- `agent.share_safe(key, value, space)` — write with conflict check
- API: `POST /v1/agents/{id}/shared/safe`, `GET /shared/conflicts`

### Loop Detection v2 (Major Upgrade)

Complete rewrite from single-check to multi-signal intelligence engine:
- **5 detection signals**: write similarity, key overwrites, velocity spikes, alert frequency, goal drift
- **Escalating severity**: green (healthy) → yellow (minor) → orange (significant) → red (critical)
- **Actionable recovery**: every signal includes what's happening, why, and exactly what to do
- **Pattern detection**: hourly breakdown, recurring patterns, spike identification
- `agent.get_loop_status()`, `agent.get_loop_history(hours=24)`
- API: `GET /v1/agents/{id}/loops/status`, `GET /loops/history`
- MCP: `octopoda_loop_status`, `octopoda_loop_history`

### Infrastructure

- **Dependency split**: `pip install octopoda` now pulls only requests + pydantic (~5 deps). Use `octopoda[server]` for cloud API, `octopoda[mcp]` for MCP, `octopoda[all]` for everything.
- **Governance files**: CODE_OF_CONDUCT.md, SECURITY.md, CONTRIBUTING.md, GitHub issue/PR templates
- **Version unification**: All packages now report 3.0.3 consistently
- **File cleanup**: Internal test scripts moved to archive/

### Bug Fixes

- Fixed `count_agents()` counting deleted/deregistered agents toward tenant limits

## 3.0.3 (2026-03-31)

### Bug Fixes

- Fixed DB bloat from heartbeat rows (SQLite INSERT OR REPLACE)
- Fixed cleanup_expired() reading wrong field for expiry timestamp
- Fixed snapshot add_node metadata kwarg
- Fixed TTL end-to-end flow
- Fixed SearchResult not being iterable (added __iter__, __getitem__, __len__)
- Fixed log_decision returning None (now returns full decision_data dict)
- Fixed LangChain 0.3+ import compatibility (4-level fallback chain)
- Fixed restore() not purging post-snapshot keys
- Fixed MCP server being cloud-only (added local fallback with _LocalAgentAdapter)
- Fixed CI synrix_runtime module not installed (added pip install -e .)
- Fixed delete_node → delete in 3 places (TTL expiry and restore purge)
- Fixed recall() double-unwrap returning nested dicts instead of values
- Fixed concurrent agent startup being slow (20-38s → parallel)
- Fixed OctopodaAgent constructor signature
- Fixed remember_safe() returning raw dict instead of SafeWriteResult
- Fixed MCP advertising 13 tools but shipping 15

### Infrastructure

- CI/CD auto-deploy to VPS via SSH (GitHub Actions)
- 156 tests passing in CI
- Version bump to 3.0.3

## 3.0.0 (2026-03-26)

### Major Release

- **PostgreSQL + pgvector** backend for production (replaced SQLite for cloud)
- **Brain Intelligence System** — Loop Breaker, Drift Radar, Contradiction Shield, Memory Health
- **Cloud API** (FastAPI) — multi-tenant auth, rate-limited, email verification
- **MCP Server** bundled into pip package (no git clone needed)
- **Docker Compose + Nginx + CI/CD pipeline**
- **Dashboard** — React+TS frontend (Lovable)
- **77 API endpoints** across auth, agents, memory, shared memory, audit, metrics, recovery, webhooks, streaming
- **Framework integrations**: LangChain, CrewAI, AutoGen, OpenAI Agents

## 2.0.0 (2025-03-12)

### New Features

- Semantic Search with local embeddings (BAAI/bge-small-en-v1.5)
- Fact Extraction (Ollama + llama3.2)
- Knowledge Graph (SQLite + spaCy NER)
- Temporal Versioning (full history with recall_history)
- MCP Server (15 tools)
- Real-time Dashboard (8 tabs, SSE streaming)
- Garbage Collection

## 1.0.0

Initial release. Persistent key-value memory for AI agents with crash recovery, shared memory bus, audit trail, and framework integrations.
