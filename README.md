# Octopoda

### The open-source memory operating system for AI agents.

Persistent memory, semantic search, loop detection, agent messaging, crash recovery, and real-time observability. Local-first. Works offline. Optionally sync to cloud.

[![PyPI](https://img.shields.io/pypi/v/octopoda)](https://pypi.org/project/octopoda/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-208%20passing-brightgreen)]()
[![GitHub release](https://img.shields.io/github/v/release/RyjoxTechnologies/Octopoda-OS)](https://github.com/RyjoxTechnologies/Octopoda-OS/releases)

![Octopoda Dashboard](docs/images/dashboard-overview.png)

Track latency, error rates, memory usage, and health scores per agent. Catch performance regressions before they hit production.

![Agent Performance](docs/images/dashboard-performance.png)

Browse every memory an agent has stored, search by prefix, and inspect the full version history of any key. See exactly how a memory changed over time — useful for debugging agent behavior and understanding why an agent made a decision.

![Memory Explorer](docs/images/memory-explorer.png)

---

## Quick Start

```bash
pip install octopoda
```

```python
from octopoda import AgentRuntime

agent = AgentRuntime("my_agent")
agent.remember("user_pref", "Alice is vegetarian and lives in London")
result = agent.recall("user_pref")
```

That's it. Memory persists across restarts, crashes, and deployments. Works locally with SQLite — no account required.

Want cloud sync and the dashboard? Set an API key:

```bash
export OCTOPODA_API_KEY=sk-octopoda-...   # Get yours at octopodas.com
```

Same code, now backed by PostgreSQL with semantic search, real-time monitoring, and multi-agent observability.

---

## Why Octopoda

AI agents forget everything between sessions. Every framework treats memory as disposable. Octopoda gives agents:

1. **Persistent memory** that survives restarts and crashes
2. **Semantic search** to find memories by meaning, not just exact keys
3. **Loop detection** that catches agents stuck in repetitive patterns
4. **Agent-to-agent messaging** for multi-agent coordination
5. **Knowledge graphs** that map entities and relationships automatically
6. **Real-time observability** so you can see what your agents know

---

## Features

Everything works out of the box with `pip install octopoda`.

### Semantic Search

```python
agent.remember("bio", "Alice is a vegetarian living in London")
agent.remember("work", "Alice is a senior engineer at Google")

results = agent.recall_similar("where does the user work?")
# Returns: "Alice is a senior engineer at Google" (score: 0.82)
```

### Loop Detection

Five signals: write similarity, key overwrites, velocity spikes, alert frequency, goal drift.

```python
status = agent.get_loop_status()
# {"severity": "orange", "score": 45, "signals": [...]}
# Every signal tells you what's wrong and exactly what to do.
```

### Agent Messaging

```python
agent_a.send_message("agent_b", "Found a bug in auth", message_type="alert")
messages = agent_b.read_messages(unread_only=True)
agent_a.broadcast("Deploy starting in 5 minutes")
```

### Goal Tracking

```python
agent.set_goal("Migrate to PostgreSQL", milestones=["Backup", "Schema", "Migrate", "Validate"])
agent.update_progress(milestone_index=0, note="Backup done")
agent.get_goal()  # {"progress": 0.25, "milestones_completed": 1}
```

### Memory Management

```python
agent.forget("outdated_config")              # Delete specific memories
agent.forget_stale(days=30)                  # Remove old memories
agent.consolidate()                          # Merge duplicates
agent.memory_health()                        # {"score": 78, "issues": [...]}
```

### Crash Recovery

```python
agent.snapshot("before_migration")
# ... something goes wrong ...
agent.restore("before_migration")
```

### Shared Memory

```python
agent_a.share("research_pool", "analysis", {"findings": "..."})
data = agent_b.read_shared("research_pool", "analysis")
```

### Export / Import

```python
bundle = agent.export_memories()
new_agent.import_memories(bundle)
```

---

## Framework Integrations

Drop-in memory for the frameworks you already use.

```python
# LangChain
from synrix_runtime.integrations.langchain_memory import SynrixMemory
memory = SynrixMemory(agent_id="my_chain")

# CrewAI
from synrix_runtime.integrations.crewai_memory import SynrixCrewMemory
crew_memory = SynrixCrewMemory(crew_id="research_crew")

# AutoGen
from synrix_runtime.integrations.autogen_memory import SynrixAutoGenMemory
memory = SynrixAutoGenMemory(group_id="dev_team")

# OpenAI Agents SDK
from synrix.integrations.openai_agents import octopoda_tools
tools = octopoda_tools("my_agent")
```

---

## MCP Server

Give Claude, Cursor, or any MCP-compatible AI persistent memory with zero code.

```bash
pip install octopoda[mcp]
```

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "octopoda": {
      "command": "octopoda-mcp"
    }
  }
}
```

25 tools: memory operations, semantic search, loop detection, goal tracking, agent messaging, memory health, and more.

---

## Cloud

Sign up at [octopodas.com](https://octopodas.com) for the dashboard, managed hosting, and cloud API.

**Setup:**

```bash
export OCTOPODA_API_KEY=sk-octopoda-...
```

Or run `octopoda-login` to sign up interactively from your terminal.

```python
from octopoda import Octopoda

client = Octopoda()  # Reads API key from env
agent = client.agent("my_agent")
agent.write("preference", "dark mode")
results = agent.search("user preferences")
```

**Plans:**

| | Free | Pro ($19/mo) | Business ($79/mo) |
|---|---|---|---|
| Agents | 5 | 25 | 75 |
| Memories | 5,000 | 250,000 | 1,000,000 |
| AI extractions | 100 | 100 + own key | 100 + own key |
| Rate limit | 60 rpm | 300 rpm | 1,000 rpm |
| Dashboard | Yes | Yes | Yes |

---

## How It Compares

| | Octopoda | Mem0 | Zep | LangChain Memory |
|---|---|---|---|---|
| **Open source** | MIT | Apache 2.0 | Partial (CE) | MIT |
| **Local-first** | Yes (SQLite) | Cloud-first | Cloud-first | In-process |
| **Loop detection** | 5-signal engine | No | No | No |
| **Agent messaging** | Built-in | No | No | No |
| **Temporal versioning** | Full history | No | No | No |
| **Crash recovery** | Snapshots + restore | N/A | No | No |
| **Cross-agent sharing** | Shared memory bus | No | No | No |
| **MCP server** | 25 tools | No | No | No |
| **Knowledge graph** | spaCy NER | No | No | No |
| **Semantic search** | Local embeddings | Cloud embeddings | Cloud embeddings | Needs vector DB |
| **Framework integrations** | LangChain, CrewAI, AutoGen, OpenAI | LangChain | LangChain | Own only |

---

## Installation

```bash
pip install octopoda              # Core (local memory, ~5 dependencies)
pip install octopoda[ai]          # + Local embeddings for semantic search
pip install octopoda[nlp]         # + spaCy for knowledge graph extraction
pip install octopoda[mcp]         # + MCP server for Claude/Cursor
pip install octopoda[all]         # Everything
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OCTOPODA_API_KEY` | | Cloud API key (get at octopodas.com) |
| `OCTOPODA_LLM_PROVIDER` | `none` | LLM for fact extraction: `openai`, `anthropic`, `ollama` |
| `OCTOPODA_OPENAI_API_KEY` | | OpenAI API key (for local fact extraction) |
| `OCTOPODA_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model (33MB, CPU) |
| `SYNRIX_DATA_DIR` | `~/.synrix/data` | Local data directory |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

MIT — use it however you want. See [LICENSE](LICENSE).

---

Built by [RYJOX Technologies](https://octopodas.com) | [PyPI](https://pypi.org/project/octopoda/) | [Cloud API](https://api.octopodas.com) | [Dashboard](https://octopodas.com/dashboard)
