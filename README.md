<p align="center">
  <img src="docs/images/octopoda-hero.gif" alt="Octopoda" width="720" />
</p>

<h1 align="center">🐙 Octopoda</h1>

<p align="center">
  <strong>The open-source memory operating system for AI agents.</strong><br />
  Persistent memory, loop detection, audit trails, and live observability — automatic on <code>pip install</code>.
</p>

<p align="center">
  <a href="https://pypi.org/project/octopoda/"><img src="https://img.shields.io/pypi/v/octopoda?style=flat-square&label=pypi" alt="PyPI" /></a>
  <a href="https://pypi.org/project/octopoda/"><img src="https://img.shields.io/pypi/dm/octopoda?style=flat-square&color=blue&label=downloads" alt="Downloads" /></a>
  <a href="https://github.com/RyjoxTechnologies/Octopoda-OS/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/RyjoxTechnologies/Octopoda-OS/ci.yml?branch=main&style=flat-square&label=CI" alt="CI" /></a>
  <a href="https://github.com/RyjoxTechnologies/Octopoda-OS/actions/workflows/smoke.yml"><img src="https://img.shields.io/github/actions/workflow/status/RyjoxTechnologies/Octopoda-OS/smoke.yml?branch=main&style=flat-square&label=smoke" alt="Smoke" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue?style=flat-square" alt="Python 3.9+" /></a>
  <a href="https://github.com/RyjoxTechnologies/Octopoda-OS/stargazers"><img src="https://img.shields.io/github/stars/RyjoxTechnologies/Octopoda-OS?style=flat-square&color=gold" alt="Stars" /></a>
  <a href="https://oosmetrics.com/repo/RyjoxTechnologies/Octopoda-OS"><img src="https://api.oosmetrics.com/api/v1/badge/achievement/91ba942c-54bf-4c16-b359-f6a11d9d7aab.svg" alt="oosmetrics Top 3 in Observability" /></a>
</p>

<p align="center">
  <a href="https://octopodas.com"><b>Website</b></a> ·
  <a href="https://octopodas.com/docs"><b>Docs</b></a> ·
  <a href="https://octopodas.com/dashboard"><b>Dashboard</b></a> ·
  <a href="#quick-start"><b>Quick start</b></a> ·
  <a href="#mcp-server"><b>MCP</b></a>
</p>

<p align="center">
  <img src="docs/images/dashboard-overview.png" alt="Octopoda dashboard — 5 agents, 226 ops, 382 loops caught, $12.45 in wasted tokens detected" width="900" />
</p>

<p align="center"><sub><i>Live overview from a real fleet. Agent health, operations volume, anomaly stream, and dollars saved by catching loops before they ran the bill.</i></sub></p>

---

## What is Octopoda

Octopoda is the missing layer between your AI agents and a working production system. Think of it as the brain stem your agents always needed but never had.

You write your agent however you like. Pure Python, LangChain, CrewAI, AutoGen, OpenAI Agents SDK, MCP. Octopoda sits underneath and quietly handles the boring stuff that makes agents actually usable. Persistent memory that survives every restart. Loop detection that flags a stuck agent in seconds with structured signals you can wire into your runtime to pause or alert. A full audit trail of every decision, every memory write, every recovery, with a verifiable hash chain available via the audit-v2 API. A live dashboard that finally lets you see what your agents are doing.

It runs locally with one `pip install` and zero infrastructure. When you outgrow that, the same code syncs to the cloud with a single environment variable. No re-architecture, no migration, no lock-in. The whole thing is open source under MIT.

If you have ever shipped an AI agent and watched it forget who you are, loop on a failing API call for hours, or just disappear into a black box you cannot debug, this is the thing you wished existed.

---

## Why Octopoda

Three things go wrong when AI agents leave your laptop. Octopoda handles all three out of the box, with no config, so you can focus on the agent and not the plumbing.

**Agents forget, until they do not.** Every time your process restarts, your agent loses everything it ever knew about the user, the task, and the conversation. Octopoda gives every agent persistent memory that survives restarts, crashes, deployments, and process kills. Memory just works, the way you always assumed it would.

**Agents loop, and silently burn money.** A stuck agent retrying a failing tool call can quietly burn hundreds of dollars in tokens before anyone notices. Octopoda's loop detector catches retry, oscillation, ping pong, reflection, and recall write patterns in seconds, and surfaces exactly which calls caused it. Detection is automatic on every write; intervention (auto-pause, spend cap) is opt-in via the v2 circuit-breaker config so the right policy is yours to set, not ours.

**Agents are black boxes, and that is terrifying in production.** Why did it do that? You had no idea, until now. Octopoda logs every decision, every write, every recovery into a replayable audit trail you can diff over time. The dedicated audit-v2 endpoint additionally hash-chains its events (`prev_hash` → `_this_hash`) so you can verify integrity via `GET /v1/auditv2/verify-chain`. Pair it with the live dashboard and you can finally see what your agents are doing in real time.

---

## Quick Start

```bash
pip install octopoda
```

```python
from octopoda import AgentRuntime

agent = AgentRuntime("my_chatbot")
agent.remember("user_name", "Alice")

# kill the process. restart Python. then:
print(agent.recall("user_name").value)
# 'Alice' — still there. Survives every restart, deploy, and crash.
```

That is the entire setup. Your agent now has persistent memory, loop detection, crash recovery, and an audit trail. No config, no Docker, no Redis, no extra services.

### Want the local dashboard?

```bash
pip install octopoda[server]
octopoda
```

Open **http://localhost:7842** — the same dashboard as the cloud version, running against your local data. No account, no API key.

### Want cloud sync + a hosted dashboard?

One command after install:

```bash
octopoda-init
```

It walks you through: paste an API key (or sign up free at [octopodas.com](https://octopodas.com)), validates it, and saves it to `~/.octopoda/config.json`. No environment variables to set, no shell config to edit. The SDK auto-loads the key on next import.

After `octopoda-init`, the same Python code above writes to the cloud and shows up live at [octopodas.com/dashboard](https://octopodas.com/dashboard).

<details>
<summary>Prefer environment variables?</summary>

```bash
export OCTOPODA_API_KEY=sk-octopoda-...
```

Both methods work. The SDK checks the env var first, then the config file.

</details>

---

## Local vs Cloud — same code, your choice

|                        | Local                          | Cloud                          |
|------------------------|--------------------------------|--------------------------------|
| Setup                  | `pip install octopoda`         | Sign up at octopodas.com (free)|
| Storage                | SQLite on your machine         | PostgreSQL + pgvector          |
| Dashboard              | http://localhost:7842          | octopodas.com/dashboard        |
| Account                | Not needed                     | Free, then optional paid tiers |
| Multi-device sync      | No                             | Yes                            |
| Semantic search        | `octopoda[ai]` extra (33 MB)   | Built-in                       |
| Upgrade path           | Set `OCTOPODA_API_KEY`         | Already there                  |

Start local. Move to cloud when you need sync, team access, or the managed dashboard. Same Python API both ways.

---

## How it stacks up

|                        | Octopoda                                       | Mem0             | Zep              | LangChain Memory |
|------------------------|------------------------------------------------|------------------|------------------|------------------|
| Open source            | MIT                                            | Apache 2.0       | Partial (CE)     | MIT              |
| Local-first            | Yes (SQLite)                                   | Cloud-first      | Cloud-first      | In process       |
| Loop detection         | 5 signal engine                                | No               | No               | No               |
| Agent messaging        | Built in                                       | No               | No               | No               |
| Audit trail            | Hash chained (audit v2)                        | No               | No               | No               |
| Crash recovery         | Snapshots + restore                            | N/A              | No               | No               |
| Shared memory          | Built in                                       | No               | No               | No               |
| MCP server             | 29 tools                                       | No               | No               | No               |
| Semantic search        | Local embeddings                               | Cloud embeddings | Cloud embeddings | Needs vector DB  |
| Framework integrations | LangChain, CrewAI, AutoGen, OpenAI Agents SDK  | LangChain        | LangChain        | Own only         |

---

## What You Get Out of the Box

When you create an `AgentRuntime`, all of this runs in the background, automatically:

| Feature             | What it does                                                              |
|---------------------|---------------------------------------------------------------------------|
| Persistent memory   | Survives restarts, crashes, deployments. Versioned by default.            |
| Loop detection      | 5-signal engine catches retry, oscillation, ping-pong, reflection, recall.|
| Audit trail         | Every write hashed and chained. Replayable, verifiable.                   |
| Crash recovery      | Automatic snapshots and heartbeat-based restore.                          |
| Health scoring      | Continuous performance and memory quality monitoring per agent.           |
| Goal tracking       | Set goals and milestones per agent (`agent.set_goal()`).                  |

You don't configure any of it. It just works.

---

## See Inside Your Agents

Track latency, error rates, memory usage, and health scores for every agent — with the same dashboard locally and in cloud.

![Agent Performance](docs/images/dashboard-performance.png)

Browse every memory the agent ever wrote, inspect version history, and see exactly how its knowledge changed over time.

![Memory Explorer](docs/images/memory-explorer.png)

---

## Audit Trail

Every decision, crash, recovery, and anomaly your agents make is logged with full context — including a memory snapshot captured at the moment of decision. Replay any time window and see exactly what each agent knew, decided, and why.

![Audit Trail](docs/images/audit-trail.png)

```python
agent.log_decision(
    decision="Keep single VPS instead of Kubernetes",
    reasoning="Current traffic doesn't justify K8s complexity. VPS handles 100x this load.",
    context={"current_rps": 14000, "threshold_rps": 1000000},
)
```

Every `log_decision` automatically captures a memory snapshot at that instant. The audit timeline shows decisions alongside crashes and recoveries, filterable per agent. Built-in similarity check warns you if a decision repeats a recent one.

Events logged via the audit-v2 endpoints (`POST /v1/auditv2/log`, `GET /v1/auditv2/events`) are hashed and chained per agent (`prev_hash` → `_this_hash`). Run `GET /v1/auditv2/verify-chain` to confirm integrity — it returns `ok=true` plus a per-agent breakdown. The legacy `log_decision()` SDK call writes a simpler audit row without the chain; route through the audit-v2 endpoint if you need tamper-evident provenance.

---

## Shared Memory

Multiple agents working on the same problem can share knowledge through named memory spaces. Writes are atomic, reads are immediate, and every change is logged with its author — so you always know which agent contributed what.

![Shared Memory](docs/images/shared-memory.png)

```python
research_agent.share("market_size", "$2.1B AI memory market by 2027", space="team-knowledge")
result = coding_assistant.read_shared("market_size", space="team-knowledge")
print(result.value)  # "$2.1B AI memory market by 2027"
```

Spaces track authorship and timestamps for every write. Use `agent.shared_conflicts(space="team-knowledge")` to surface disagreements when multiple agents write to the same key.

---

## When You Need More Control

Everything below is optional. Use it when you need it.

### Semantic Search

Find memories by meaning, not just exact keys.

```python
agent.remember("bio", "Alice is a vegetarian living in London")
results = agent.recall_similar("what does the user eat?")
# Returns the right memory with a similarity score
```

> **Note:** In **cloud mode**, embeddings are computed server-side and this works out of the box. In **local mode**, install the AI extra (`pip install octopoda[ai]`) so the local embedding model (~33 MB) can run. Without it, `recall_similar` returns 0 results in local mode and logs a warning.

### Agent Messaging

Agents can talk to each other through shared inboxes.

```python
agent_a.send_message("agent_b", "Found a bug in auth", message_type="alert")
messages = agent_b.read_messages(unread_only=True)
```

### Goal Tracking

Set goals and track progress per agent.

```python
agent.set_goal("Migrate to PostgreSQL", milestones=["Backup", "Schema", "Migrate", "Validate"])
agent.update_progress(milestone_index=0, note="Backup done")
```

### Memory Management

```python
agent.forget("outdated_config")                   # Delete a specific memory
agent.forget_stale(max_age_seconds=30*86400)      # Clean up memories older than 30 days
agent.consolidate(dry_run=False)                  # Merge near-duplicates
agent.memory_health()                             # Get a health report
```

### Snapshots and Recovery

```python
agent.snapshot("before_migration")
# ... something goes wrong ...
agent.restore("before_migration")
```

### Export / Import

```python
bundle = agent.export_memories()
new_agent.import_memories(bundle)
```

---

## Framework Integrations

Drop into the framework you already use. One line, your agents get persistent memory.

<details>
<summary><b>LangChain — drop-in conversation memory</b></summary>

```python
from octopoda import LangChainMemory
memory = LangChainMemory("my-chain")
memory.save_context({"input": "I prefer dark mode"}, {"output": "Got it!"})
variables = memory.load_memory_variables({})
```
</details>

<details>
<summary><b>CrewAI — persistent crew findings and task results</b></summary>

```python
from octopoda import CrewAIMemory
crew = CrewAIMemory("research-crew")
crew.store_finding("researcher", "market_size", {"value": "$4.2B"})
finding = crew.get_finding("market_size")
```
</details>

<details>
<summary><b>AutoGen — multi-agent conversation memory</b></summary>

```python
from octopoda import AutoGenMemory
memory = AutoGenMemory("dev-team")
memory.store_message("user_proxy", "assistant", "Research quantum computing")
history = memory.get_conversation_history()
```
</details>

<details>
<summary><b>OpenAI Agents SDK — thread and run persistence</b></summary>

```python
from octopoda import OpenAIAgentsMemory
memory = OpenAIAgentsMemory()
memory.store_thread_state("thread_001", {"messages": [...]})
restored = memory.restore_thread("thread_001")
```
</details>

All integrations work locally (no API key) or with cloud sync (set `OCTOPODA_API_KEY`).

---

## MCP Server

Give Claude, Cursor, or any MCP-compatible AI persistent memory with zero code.

```bash
pip install octopoda[mcp]
```

**Claude Code:**

```bash
claude mcp add octopoda -s user -e OCTOPODA_API_KEY=sk-octopoda-YOUR_KEY -- python -m synrix_runtime.api.mcp_server
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "octopoda": {
      "command": "python",
      "args": ["-m", "synrix_runtime.api.mcp_server"],
      "env": { "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY" }
    }
  }
}
```

28 tools for memory, search, loop detection, goals, messaging, decisions, snapshots, and more.

<details>
<summary><b>Full MCP tool list (the names your agent will actually see)</b></summary>

When you register the server with `claude mcp add octopoda ...`, the MCP client prefixes each tool with the server name. So the tool that the function defines as `octopoda_remember` ends up exposed to your agent as `octopoda_octopoda_remember`. This is correct behaviour from the client; just be aware of it when you write skill files.

| Function name (server side) | Exposed name in client |
|---|---|
| `octopoda_remember` | `octopoda_octopoda_remember` |
| `octopoda_recall` | `octopoda_octopoda_recall` |
| `octopoda_search` | `octopoda_octopoda_search` |
| `octopoda_recall_similar` | `octopoda_octopoda_recall_similar` |
| `octopoda_recall_history` | `octopoda_octopoda_recall_history` |
| `octopoda_related` | `octopoda_octopoda_related` |
| `octopoda_snapshot` | `octopoda_octopoda_snapshot` |
| `octopoda_restore` | `octopoda_octopoda_restore` |
| `octopoda_share` | `octopoda_octopoda_share` |
| `octopoda_read_shared` | `octopoda_octopoda_read_shared` |
| `octopoda_list_agents` | `octopoda_octopoda_list_agents` |
| `octopoda_agent_stats` | `octopoda_octopoda_agent_stats` |
| `octopoda_process_conversation` | `octopoda_octopoda_process_conversation` |
| `octopoda_get_context` | `octopoda_octopoda_get_context` |
| `octopoda_log_decision` | `octopoda_octopoda_log_decision` |
| `octopoda_forget` | `octopoda_octopoda_forget` |
| `octopoda_forget_stale` | `octopoda_octopoda_forget_stale` |
| `octopoda_memory_health` | `octopoda_octopoda_memory_health` |
| `octopoda_consolidate` | `octopoda_octopoda_consolidate` |
| `octopoda_loop_status` | `octopoda_octopoda_loop_status` |
| `octopoda_loop_history` | `octopoda_octopoda_loop_history` |
| `octopoda_send_message` | `octopoda_octopoda_send_message` |
| `octopoda_read_messages` | `octopoda_octopoda_read_messages` |
| `octopoda_broadcast` | `octopoda_octopoda_broadcast` |
| `octopoda_set_goal` | `octopoda_octopoda_set_goal` |
| `octopoda_get_goal` | `octopoda_octopoda_get_goal` |
| `octopoda_update_progress` | `octopoda_octopoda_update_progress` |
| `octopoda_search_filtered` | `octopoda_octopoda_search_filtered` |

If you register the server with a different name (e.g. `claude mcp add memory ...`), the prefix changes to match. Use whichever name your client actually exposes when writing skill files; do not assume a single prefix.

</details>

---

## Cloud

Sign up free at [octopodas.com](https://octopodas.com) for the dashboard, managed hosting, and cloud API.

```python
from octopoda import Octopoda

client = Octopoda()              # Uses OCTOPODA_API_KEY env var
agent = client.agent("my_agent")
agent.write("preference", "dark mode")
results = agent.search("user preferences")
```

|                       | Free      | Pro ($19/mo)  | Business ($49/mo) | Scale ($99/mo)   |
|-----------------------|-----------|---------------|-------------------|------------------|
| Agents                | 5         | 25            | 75                | Unlimited        |
| Memories              | 5,000     | 250,000       | 1,000,000         | 5,000,000        |
| AI extractions        | 100       | 10,000        | 50,000            | Unlimited        |
| Rate limit            | 60 rpm    | 300 rpm       | 1,000 rpm         | 5,000 rpm        |
| Loop detection        | Basic     | Full v2       | Full v2           | Full v2          |
| Shared spaces         | 1         | 5             | Unlimited         | Unlimited        |
| Dashboard             | Yes       | Yes           | Yes               | Yes              |
| Support               | Community | Email (48h)   | Priority          | Dedicated        |

---

## Installation

```bash
pip install octopoda              # Core — everything to get started (Python 3.9+)
pip install octopoda[ai]          # + Local embeddings for semantic search
pip install octopoda[server]      # + Local dashboard server (Flask)
pip install octopoda[nlp]         # + spaCy for knowledge graph extraction
pip install octopoda[mcp]         # + MCP server for Claude/Cursor (Python 3.10+)
pip install octopoda[all]         # Everything (Python 3.10+)
```

> **Python version note:** the core package supports Python 3.9 and up. The `[mcp]` extra requires Python 3.10+ because the upstream `mcp` library does. If you're on 3.9 and want everything except MCP, use `pip install octopoda[ai,server,nlp]`.

> **Local-mode note:** running without an API key (`pip install octopoda` only) gives you a fully working local install with SQLite at `~/.synrix/data/synrix.db`. The `OCTOPODA_API_KEY` environment variable accepts the sentinels `local`, `offline`, `dev`, `none`, or `YOUR_KEY_HERE` to explicitly force local mode. Real cloud keys start with `sk-octopoda-`; anything else is treated as a local sentinel rather than hung on cloud auth.

> **Updating Claude Code MCP registration:** if you change the `claude mcp add octopoda ...` env vars (for example, swapping from local to cloud), restart the Claude Code window. `/mcp` reconnect alone won't pick up the new env because the child process inherits Claude Code's cached env at startup.

## Configuration

| Variable                   | Default                  | Description                                  |
|----------------------------|--------------------------|----------------------------------------------|
| `OCTOPODA_API_KEY`         |                          | Cloud API key (free at octopodas.com)        |
| `OCTOPODA_LICENSE_KEY`     |                          | License key for higher tiers (optional)      |
| `OCTOPODA_LLM_PROVIDER`    | `none`                   | `openai`, `anthropic`, `ollama`              |
| `OCTOPODA_OPENAI_API_KEY`  |                          | Your OpenAI key for local fact extraction    |
| `OCTOPODA_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model (33 MB, runs on CPU)   |
| `SYNRIX_DATA_DIR`          | `~/.synrix/data`         | Local data directory (where SQLite + embeddings live) |
| `OCTOPODA_LOCAL_MODE`      | unset                    | Set to `1` to force local mode regardless of `OCTOPODA_API_KEY` |
| `SYNRIX_HEARTBEAT_INTERVAL_SEC` | `3`                  | Daemon heartbeat polling interval (raise for low-resource boxes) |
| `SYNRIX_MAX_VERSIONS_PER_RUNTIME_KEY` | `10`           | Schema-level cap on `runtime:*` / `metrics:*` key versions |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and guidelines.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/ryjoxtechnologies-octopoda-os-badge.png)](https://mseep.ai/app/ryjoxtechnologies-octopoda-os)

## License

MIT, use it however you want. See [LICENSE](LICENSE).

## Verification harnesses

The repo ships four scripts under `scripts/integration/` that exercise the product end to end against both a fresh PyPI install and live `api.octopodas.com`:

* `audit_verify_3_1_13.py`: live HTTP probes against production. Currently 12 of 12 pass.
* `mcp_stdio_harness.py`: drives `octopoda-mcp` over JSON RPC the way Claude Code does. 7 of 7 pass.
* `user_simulation.py`: fresh venv, `pip install octopoda` from PyPI, exercises every SDK path.
* `local_dashboard_smoke.py`: proves the bundled dashboard serves byte identical assets to `octopodas.com/dashboard`.

Anyone can clone and rerun them.

---

<p align="center">
  Built by <a href="https://octopodas.com">RYJOX Technologies</a> ·
  <a href="https://pypi.org/project/octopoda/">PyPI</a> ·
  <a href="https://api.octopodas.com/docs">Cloud API</a> ·
  <a href="https://octopodas.com/dashboard">Dashboard</a>
</p>
