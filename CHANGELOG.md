# Changelog

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
