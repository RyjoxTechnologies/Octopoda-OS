# Octopoda Memory for OpenClaw

Give your OpenClaw a brain that persists. Every conversation remembered, every preference tracked, across all platforms.

## What It Does

Without memory, your OpenClaw starts from zero every conversation. With Octopoda:

- **Remembers everything** — past conversations, preferences, decisions, task outcomes
- **Works across platforms** — WhatsApp, Discord, Telegram, CLI — same memory everywhere
- **Catches loops** — warns when your agent repeats the same failed action
- **Tracks changes** — full version history on every stored fact
- **Shares context** — multiple agents can share a memory space
- **Decision audit trail** — log and review every important choice your agent makes
- **Snapshot & restore** — save state before risky ops, roll back if needed

## Install (30 seconds)

### 1. Get your free API key

Go to [octopodas.com](https://octopodas.com) and sign up. Your key is available instantly after email verification.

### 2. Run the installer

```bash
python install.py --key sk-octopoda-YOUR_KEY_HERE
```

That's it. The installer:
- Copies the skill to `~/.openclaw/skills/`
- Saves your API key to OpenClaw config
- Validates everything works

### 3. Restart OpenClaw

```bash
openclaw gateway stop
openclaw gateway run
```

Start chatting. Your OpenClaw now remembers everything.

**No pip install needed** — the skill uses only Python standard library.

---

### Manual install (if you prefer)

<details>
<summary>Click to expand manual steps</summary>

**Copy the skill folder:**

Mac/Linux:
```bash
cp -r octopoda-memory ~/.openclaw/skills/
```

Windows (PowerShell):
```powershell
Copy-Item -Recurse octopoda-memory $env:USERPROFILE\.openclaw\skills\
```

**Set your API key** in `~/.openclaw/openclaw.json`:
```json
{
  "skills": {
    "entries": {
      "octopoda-memory": {
        "enabled": true,
        "env": {
          "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY_HERE"
        }
      }
    }
  }
}
```

**Verify:**
```bash
python ~/.openclaw/skills/octopoda-memory/scripts/memory.py setup
```

</details>

---

## How It Works

Every conversation turn:
1. **Before responding** — Octopoda retrieves relevant memories from past conversations
2. **You chat normally** — OpenClaw uses the context naturally (you won't even notice)
3. **After responding** — the conversation is stored with automatic fact extraction

You never see memory operations. OpenClaw just "knows things" from past conversations.

## Example

**Day 1:**
> You: "Set up my project with dark mode and use PostgreSQL"
> OpenClaw: *sets up project*

**Day 7 (new conversation):**
> You: "Add a new settings page to my project"
> OpenClaw: "I'll add a settings page with dark mode styling to match your existing setup, and connect it to your PostgreSQL database."

It remembered. No prompting needed.

## Full Feature Set

| Feature | What it does | When it's used |
|---------|-------------|----------------|
| **Memory recall** | Loads relevant past context | Automatically, every turn |
| **Memory storage** | Saves conversation facts | Automatically, after meaningful exchanges |
| **Semantic search** | Find memories by meaning | When you ask "what do you remember about X?" |
| **Shared memory** | Multiple agents read/write the same data | When collaborating across agents |
| **Decision audit trail** | Logs important choices with reasoning | When agent makes a recommendation or choice |
| **Version history** | See how a value changed over time | When you ask "what was the old value?" |
| **Snapshots** | Save full memory state | Before risky operations |
| **Restore** | Roll back to a snapshot | When something goes wrong |

## Natural Language Commands

Just ask naturally:

- **"What do you remember about me?"** — triggers memory search
- **"What was the old value of X?"** — triggers version history
- **"Save a snapshot before we start"** — triggers snapshot
- **"Share this with my other agents"** — triggers shared memory write
- **"Why did you choose that approach?"** — triggers decision audit lookup

## Requirements

- Python 3.8+ (no additional packages needed)
- Free Octopoda account ([octopodas.com](https://octopodas.com))
- OpenClaw installed (`npm install -g openclaw@latest`)

## Troubleshooting

### Setup check fails

Run the diagnostic:
```bash
python ~/.openclaw/skills/octopoda-memory/scripts/memory.py setup
```

This checks: API key present, API connectivity, agent registration, memory recall. Each step shows `[OK]` or `[FAIL]` with a fix.

### "OCTOPODA_API_KEY not set"

Your key isn't reaching the skill. The **recommended** way is via OpenClaw config (`~/.openclaw/openclaw.json`):
```json
{
  "skills": {
    "entries": {
      "octopoda-memory": {
        "enabled": true,
        "env": {
          "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY_HERE"
        }
      }
    }
  }
}
```

Or re-run the installer: `python install.py --key sk-octopoda-YOUR_KEY`

### "Cannot connect to API"

- Check your internet connection
- Verify your API key starts with `sk-octopoda-`
- If just signed up, make sure you've verified your email

### Skill not showing in OpenClaw

- Check folder exists: `~/.openclaw/skills/octopoda-memory/SKILL.md`
- Restart: `openclaw gateway stop` then `openclaw gateway run`

### OpenClaw making too many tool calls

The skill limits to max 2 memory calls per turn. If excessive:
- Verify `SKILL.md` says "max 2 per turn" in Rules section
- Re-run `python install.py` to get the latest version

### Windows-specific

- Use `python` instead of `python3` if `python3` isn't recognized
- Paths use `$env:USERPROFILE\.openclaw\skills\` in PowerShell

## Privacy

- All memory stored in your isolated Octopoda account (separate database per user)
- No data shared between accounts unless you explicitly use shared memory spaces
- Sensitive data (passwords, API keys, financial info) is never stored
- Trivial messages ("hi", "ok", "thanks") are automatically filtered out
- Delete all data anytime from the Octopoda dashboard
- No conversation data leaves your account

## How It Compares

| | Octopoda | No memory | Custom RAG |
|---|---|---|---|
| Setup time | 30 seconds | N/A | Hours/days |
| Dependencies | None (stdlib only) | N/A | Many |
| Cross-session | Yes | No | Depends |
| Cross-platform | Yes | No | No |
| Loop detection | Yes | No | No |
| Decision audit | Yes | No | No |
| Snapshots | Yes | No | No |
| Version history | Yes | No | No |

## Links

- [Octopoda — Get your API key](https://octopodas.com)
- [GitHub](https://github.com/RyjoxTechnologies/Octopoda-OS)
- [Report issues](https://github.com/RyjoxTechnologies/Octopoda-OS/issues)

## License

MIT — see [LICENSE](LICENSE)
