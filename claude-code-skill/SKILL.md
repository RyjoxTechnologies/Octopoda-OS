# Octopoda Memory

Give your Claude Code sessions persistent memory that survives across conversations.

## Setup

1. Install: `pip install octopoda`
2. Get a free API key at https://octopodas.com
3. Set your key: `export OCTOPODA_API_KEY=sk-octopoda-your-key`

## What This Skill Does

This skill gives Claude Code persistent memory powered by Octopoda. Your AI assistant remembers:
- Your coding preferences and conventions
- Project context and architecture decisions
- Past bugs and how they were fixed
- Team member names and roles
- Any fact you tell it to remember

Memory persists across conversations, restarts, and machines. Ask Claude to remember something today, recall it next week.

## Commands

### Remember something
Tell Claude: "Remember that we use PostgreSQL for the main database" or "Remember that the deploy process requires running migrations first"

Claude will store it using Octopoda and confirm.

### Recall something
Ask Claude: "What database do we use?" or "What's the deploy process?"

Claude will search its memory and find relevant facts even if you phrase the question differently from how you stored it.

### Check what's stored
Ask Claude: "What do you remember about this project?" or "Show me everything you remember"

## How It Works

Under the hood, this skill uses Octopoda's MCP server which provides 13 tools:
- `octopoda_remember` — store a memory
- `octopoda_recall` — get a specific memory by key
- `octopoda_recall_similar` — find memories by meaning (semantic search)
- `octopoda_search` — search by key prefix
- `octopoda_recall_history` — see how a memory changed over time
- `octopoda_snapshot` / `octopoda_restore` — save and restore memory state
- `octopoda_share` / `octopoda_read_shared` — share memories between agents
- `octopoda_list_agents` — see all your agents
- `octopoda_agent_stats` — get agent performance stats
- `octopoda_related` — explore knowledge graph connections
- `octopoda_log_decision` — log decisions with reasoning

All data stored locally (SQLite) or in the cloud if you set an API key. Your choice.

## Links

- GitHub: https://github.com/RyjoxTechnologies/Octopoda-OS
- Website: https://octopodas.com
- PyPI: https://pypi.org/project/octopoda/
