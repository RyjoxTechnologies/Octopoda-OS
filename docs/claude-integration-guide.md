# Using Octopoda with Claude Code & Claude Desktop

Give Claude persistent memory that survives across conversations. Claude remembers your preferences, your project context, past decisions, and anything you tell it to store.

## What You Get

- Claude remembers things across conversations (not just within one chat)
- Semantic search finds memories by meaning, not just exact words
- Version history tracks how memories change over time
- Shared memory lets multiple Claude sessions share knowledge
- Loop detection catches repetitive patterns
- Full audit trail of every memory operation

## Setup (2 minutes)

### Step 1: Install Octopoda

```bash
pip install octopoda
```

### Step 2: Get Your Free API Key

Sign up at [octopodas.com](https://octopodas.com) and copy your API key from the dashboard.

### Step 3: Add to Claude Code

```bash
claude mcp add octopoda -s user -e OCTOPODA_API_KEY=sk-octopoda-YOUR_KEY -- python -m synrix_runtime.api.mcp_server
```

That's it. Restart Claude Code and you have 13 memory tools available.

### Step 3 (Alternative): Add to Claude Desktop

Add this to your Claude Desktop config file:

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "octopoda": {
      "command": "python",
      "args": ["-m", "synrix_runtime.api.mcp_server"],
      "env": {
        "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY"
      }
    }
  }
}
```

Restart Claude Desktop.

### Step 3 (Alternative): Add to Cursor

Go to Settings > MCP Servers and add:

```json
{
  "octopoda": {
    "command": "python",
    "args": ["-m", "synrix_runtime.api.mcp_server"],
    "env": {
      "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY"
    }
  }
}
```

## How to Use It

Just talk to Claude naturally. No special syntax needed.

### Remember something

> "Remember that this project uses PostgreSQL with pgvector"

> "Remember that the deploy process requires running migrations first"

> "Remember that Alice prefers email over Slack and works in UTC+1"

### Recall something

> "What database do we use?"

> "What's the deploy process?"

> "What do you know about Alice?"

Claude searches memory by meaning, so you don't need to use the exact same words you stored.

### Check what's stored

> "What do you remember about this project?"

> "Show me everything you remember about the deployment setup"

### Forget something

> "Forget the old API endpoint, we migrated to the new one"

### Snapshot before risky work

> "Take a snapshot called before-refactor"

Then if things go wrong:

> "Restore from the before-refactor snapshot"

## Verify It Works

1. In one Claude conversation, say: "Remember that my favourite language is Python and I prefer dark mode"
2. Close that conversation completely
3. Open a brand new conversation
4. Ask: "What's my favourite language?"
5. Claude should answer "Python" from Octopoda memory

If it works, memory is persisting across sessions. If it doesn't, check that the MCP server shows as connected (type `/mcp` in Claude Code).

## 13 Tools Available

| Tool | What it does |
|---|---|
| octopoda_remember | Store a memory |
| octopoda_recall | Get a memory by key |
| octopoda_recall_similar | Find memories by meaning |
| octopoda_search | Search by key prefix |
| octopoda_recall_history | See how a memory changed over time |
| octopoda_snapshot | Save a checkpoint |
| octopoda_restore | Rollback to a checkpoint |
| octopoda_share | Share data between agents/sessions |
| octopoda_read_shared | Read shared data |
| octopoda_list_agents | List all agents |
| octopoda_agent_stats | Performance stats |
| octopoda_log_decision | Log a decision with reasoning |
| octopoda_loop_status | Check for loops |

## Tips

- You don't need to say "use octopoda" — Claude uses the tools automatically when you ask it to remember or recall
- Memories persist forever until you delete them
- Each agent_id gets isolated memory, so different projects don't mix
- The free tier gives you 5 agents and 5,000 memories
- All data goes through your Octopoda cloud account, viewable at octopodas.com/dashboard

## Troubleshooting

**Claude doesn't use the memory tools:**
Type `/mcp` in Claude Code. If octopoda isn't listed, the MCP server didn't connect. Try restarting Claude Code.

**"OCTOPODA_API_KEY not set" error:**
Make sure you included the `-e OCTOPODA_API_KEY=your-key` part when adding the MCP server.

**Memory not persisting across sessions:**
Check that you're using the same agent_id. By default the MCP tools ask which agent to use. Use the same name consistently.

## Links

- [GitHub](https://github.com/RyjoxTechnologies/Octopoda-OS)
- [Dashboard](https://octopodas.com/dashboard)
- [Website](https://octopodas.com)
- [Full Documentation](https://octopodas.com/docs)
