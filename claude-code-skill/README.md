# Octopoda Memory for Claude Code

Give your Claude Code sessions persistent memory. Your AI assistant remembers everything across conversations.

## Quick Setup

### 1. Install Octopoda

```bash
pip install octopoda
```

### 2. Get a free API key

Sign up at [octopodas.com](https://octopodas.com) (or skip this step to use local-only mode).

### 3. Add to Claude Code

Run this in your terminal:

```bash
claude mcp add octopoda -- octopoda-mcp
```

Or manually add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "octopoda": {
      "command": "octopoda-mcp",
      "env": {
        "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY"
      }
    }
  }
}
```

### 4. Use it

Just talk to Claude naturally:

- "Remember that this project uses React 18 with TypeScript"
- "What do you remember about the database schema?"
- "Remember that the CI pipeline takes 12 minutes on average"
- "What did I tell you about the deploy process?"

## For Claude Desktop

Same setup. Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "octopoda": {
      "command": "octopoda-mcp",
      "env": {
        "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY"
      }
    }
  }
}
```

## For Cursor

Add to Cursor's MCP settings (Settings > MCP Servers):

```json
{
  "octopoda": {
    "command": "octopoda-mcp",
    "env": {
      "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY"
    }
  }
}
```

## Local Only (No Account)

Skip the API key. Memory stores in SQLite on your machine:

```bash
claude mcp add octopoda -- octopoda-mcp
```

No cloud, no account, no data leaves your machine.

## What You Get

- **13 memory tools** available to Claude automatically
- **Persistent memory** across conversations and restarts
- **Semantic search** — find memories by meaning, not exact words
- **Version history** — see how memories changed over time
- **Snapshots** — save and restore memory state
- **Shared memory** — share context between different agents/sessions

## Links

- [GitHub](https://github.com/RyjoxTechnologies/Octopoda-OS)
- [Website](https://octopodas.com)
- [Dashboard](https://octopodas.com/dashboard)
- [Full Documentation](https://octopodas.com/docs)
