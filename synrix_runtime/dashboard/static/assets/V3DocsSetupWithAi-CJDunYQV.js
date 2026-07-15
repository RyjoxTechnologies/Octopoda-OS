import{aM as l,aN as e,aU as u,aR as m}from"./index-RsFqQstg.js";import{u as h,a as g,D as y,C as f,P as w}from"./V3DocsShared-BKwaCxO9.js";import{B as b}from"./bot-DH_M4Xsn.js";import{C as v}from"./copy-XIpaKHQY.js";import{M as k,r as x}from"./index-CkQ3-qhY.js";const a=`> Paste this entire document into Cursor, Claude Code, Copilot, ChatGPT, Aider, or any AI coding assistant, with the message:
>
> **"Set up Octopoda cloud memory in my project using this guide. Follow it exactly."**
>
> This is a version-locked spec for Octopoda **3.3.4+**. Every code snippet below was tested end-to-end against live cloud. Follow it in order and the setup will work on the first try.

---

## What you are setting up (read this first)

**Octopoda is persistent memory for AI agents.** Without it, your agent forgets everything when the process restarts. With it, the agent's facts, decisions, goals, and shared state live in a managed cloud database and survive crashes, restarts, and redeploys.

You will install one Python package, authenticate once, and add a few lines to the user's project. The cloud handles storage, search, audit trail, and the dashboard.

**You are not:** building a database, configuring a server, or writing infra code. The cloud at \`api.octopodas.com\` already exists. Your job is to wire the user's Python into it.

---

## What to ask the user

Ask for **one thing only**: their Octopoda **API key**.

They get it from <https://octopodas.com> → Sign in → Dashboard → **API Keys** → "Create new key". The key starts with \`sk-octopoda-\`.

Do **not** ask for:

- A server URL — the default is correct.
- A username or password — the API key authenticates everything.
- A project name — agents are identified by string IDs you choose.
- Any config file path — the CLI handles config files.

---

## Step 1 — Confirm Python 3.9 or newer

\`\`\`bash
python --version
\`\`\`

If the version is below 3.9, stop and ask the user to upgrade. Do not try \`pip install\` on Python 3.8 or earlier — it will fail and confuse the user. Python 3.10+ is recommended; 3.13 is fully supported.

---

## Step 2 — Install the package

\`\`\`bash
pip install "octopoda>=3.3.4"
\`\`\`

That single package contains everything: the cloud client, the four framework wrappers, the CLI tools. No \`octopoda[all]\`, no extras. Don't add \`numpy\`, \`sentence-transformers\`, or any embedding library unless the user specifically asks for local embeddings — the cloud handles those server-side.

**Confirm the install:**

\`\`\`bash
python -c "import octopoda; print(octopoda.__version__)"
\`\`\`

You should see \`3.3.4\` or higher. If you see \`ModuleNotFoundError\`, the wrong Python or wrong virtualenv was used — activate the user's venv and retry.

---

## Step 3 — Authenticate

Octopoda needs the API key in one of two places: a config file (preferred) or an environment variable.

### Preferred: one-command CLI

\`\`\`bash
octopoda-init
\`\`\`

This prompts the user for their API key, validates it against the cloud (so you know it's not a typo), and writes it to \`~/.octopoda/config.json\`. Running it twice is safe — the second run detects the existing config and just re-validates.

### Fallback: environment variable (use for Docker / CI / non-interactive shells)

\`\`\`bash
# macOS / Linux
export OCTOPODA_API_KEY="sk-octopoda-..."

# Windows PowerShell
$env:OCTOPODA_API_KEY = "sk-octopoda-..."
\`\`\`

**Rules:**

- Pick one path, not both. If \`OCTOPODA_API_KEY\` is set, it overrides the config file.
- Never hardcode the key in source files.
- Never commit the key to git.
- Do not manually edit \`~/.octopoda/config.json\` — let \`octopoda-init\` write it.

---

## Step 4 — The smallest thing that proves it works

The point of Octopoda is that memory **survives across process restarts**. Here is a script that demonstrates that — write it as \`octopoda_test.py\`:

\`\`\`python
from octopoda import AgentRuntime

# An "agent" is anything you give a stable name to.
# Use the same string every run so memory accumulates against the same identity.
agent = AgentRuntime("my-first-agent")

# Try to read first — if found, we're on a second run and persistence is proven.
existing = agent.recall("user_preference")

if existing.found:
    print(f"Recalled from a previous run: {existing.value}")
    print("Persistence works. Setup is complete.")
else:
    print("First run — writing memory now.")
    agent.remember("user_preference", "dark mode")
    print("Now run this script again. It should print 'Recalled from a previous run'.")
\`\`\`

**Run it twice:**

\`\`\`bash
python octopoda_test.py
python octopoda_test.py
\`\`\`

**Expected output on run 1:** \`First run — writing memory now.\`

**Expected output on run 2:** \`Recalled from a previous run: dark mode\`

If run 2 says "First run" again, the API key isn't being read — re-check Step 3. If run 1 raises \`AuthError: Invalid API key\`, the key is wrong — re-run \`octopoda-init\`.

**Why this matters:** Run 2 is a completely fresh Python process. The fact that it remembers what run 1 wrote means storage is working, the network is working, auth is working, and the agent identity is consistent. That's the whole setup verified in two commands.

---

## Step 5 — Wire into the user's framework (only if they use one)

Add **at most one** of these. Do not install multiple wrappers the user is not using.

### LangChain

For LangChain 1.x use \`OctopodaChatHistory\` with \`RunnableWithMessageHistory\` — that is the standard pattern and the one we test against:

\`\`\`python
from octopoda import OctopodaChatHistory
from langchain_core.runnables.history import RunnableWithMessageHistory

def get_session_history(session_id: str):
    return OctopodaChatHistory(agent_id="my-langchain-agent", session_id=session_id)

chain_with_memory = RunnableWithMessageHistory(
    your_chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)
\`\`\`

> **\`LangChainMemory\` is legacy** — it only works with the deprecated \`ConversationChain(memory=...)\` pattern, not \`RunnableWithMessageHistory\` (it has no \`.messages\` attribute and raises \`AttributeError\` inside the runnable). For LangChain 1.x use \`OctopodaChatHistory\`.

### CrewAI

\`\`\`python
from octopoda import CrewAIMemory

memory = CrewAIMemory("my-crew")

# Positional args: (agent_role, key, finding).
memory.store_finding(
    "researcher",
    "market_size",
    {"value": "$4.2B", "source": "Gartner 2025"},
)

finding = memory.get_finding("market_size")
print(finding)
\`\`\`

### AutoGen

\`\`\`python
from octopoda import AutoGenMemory

memory = AutoGenMemory("my-autogen-team")
memory.store_message(
    sender="user_proxy",
    recipient="assistant",
    content="Research quantum computing",
)
history = memory.get_conversation_history()
print(history)
\`\`\`

### OpenAI Assistants API

\`\`\`python
from octopoda import OpenAIAgentsMemory

memory = OpenAIAgentsMemory()  # no agent_id needed here
memory.store_thread_state(
    "thread_abc123",
    {"messages": [{"role": "user", "content": "hi"}]},
)
restored = memory.restore_thread("thread_abc123")
print(restored)
\`\`\`

### OpenAI Agents SDK (auto-instrumented)

No wrapper class needed — \`octopoda.init()\` auto-captures every \`Runner.run\` / \`run_sync\` / \`run_streamed\` call:

\`\`\`python
import octopoda
octopoda.init()                 # add once, at the very top — before importing agents

from agents import Agent, Runner

agent = Agent(name="assistant", instructions="...", model="gpt-4o-mini")
result = Runner.run_sync(agent, "Remember: my favorite fruit is mango.")
# The run is captured + stored automatically; recall it from any later process.
\`\`\`

Set \`OCTOPODA_API_KEY\` (optionally \`OCTOPODA_AGENT_ID="my-agent"\` to name it). Requires \`octopoda>=3.3.4\`.

---

## API reference — verified working in 3.3.4

These are the methods you may use. They are tested end-to-end. Do not invent methods not in this table.

### \`AgentRuntime\` — main entry point

\`\`\`python
from octopoda import AgentRuntime

agent = AgentRuntime("agent-id")  # use the same id across runs
\`\`\`

| Method | Notes |
|---|---|
| \`agent.remember(key, value)\` | \`value\` can be \`str\`, \`dict\`, \`list\`, \`int\`, \`float\`, \`bool\`. |
| \`agent.recall(key)\` | Returns a \`RecallResult\`. Use \`.value\`, \`.found\`, \`.latency_us\`. |
| \`agent.recall_similar(query, limit=10)\` | Semantic search. Returns a \`SearchResult\` — iterate it, or use \`.items\` and \`.count\`. The kwarg is \`limit\`, not \`k\`. |
| \`agent.forget(key)\` | Deletes a memory. |
| \`agent.set_goal(goal, milestones=[...])\` | Multi-step goal tracker. \`milestones\` is a list of strings. |
| \`agent.update_progress(milestone_index=N, note="...")\` | Mark milestone N complete. Or pass \`progress=0.75\` directly. |
| \`agent.get_goal()\` | Returns dict with \`progress\` (0.0–1.0). |
| \`agent.log_decision(decision, reasoning, context=None)\` | Appends to audit trail. \`context\` is an optional dict. |
| \`agent.memory_health()\` | Returns dict with \`score\` (0–100). |
| \`agent.export_memories()\` | Portable bundle dict, includes \`memories\`, \`snapshots\`, \`meta\`. |
| \`agent.import_memories(bundle)\` | Restore from a bundle returned by \`export_memories()\`. |
| \`agent.snapshot(label="...")\` | Named checkpoint. The kwarg is \`label\`. |
| \`agent.restore(label="...")\` | Roll back to a named snapshot. |
| \`agent.share(key, value, space="global")\` | Write to a cross-agent space. Default space is \`"global"\`. |
| \`agent.read_shared(key, space="global")\` | Read from a shared space. |
| \`agent.shared_conflicts(space="global", limit=20)\` | List of conflicting writes (returns \`[]\` if none). |

### \`Octopoda\` — lower-level client

\`\`\`python
from octopoda import Octopoda

client = Octopoda()                # auto-reads key from config or env
ag = client.agent("agent-id")
ag.write("key", "value")
ag.search("query string")           # returns search results object
ag.info()                           # dict with agent_id, state, metrics
ag.metrics()                        # detailed counters and latencies
\`\`\`

\`AgentRuntime\` is what you should use for most code. \`Octopoda\` exists for power users who want explicit client control.

---

## Do NOT promise these — they don't work yet

If the user asks for any of the below, tell them honestly that it is not yet supported in cloud:

- **\`send_message\` / \`read_messages\` cross-process.** In-process queues work, but messages do not yet survive process restarts on cloud. (Internal tracking: AUDIT §7.2.)
- **\`OctopodaCloud()\` class.** Old name. Use \`Octopoda()\` instead.
- **\`octopoda.licensing\` imports.** Removed. Licensing is handled automatically via the API key.
- **Self-hosting / local-only mode.** Possible, but out of scope for this guide. Stick to cloud.

Do not invent method names. If a method is not listed in the API reference table above, it does not exist in the public SDK — do not guess.

---

## Error remediation

| Symptom | Likely cause | Fix |
|---|---|---|
| \`ModuleNotFoundError: No module named 'octopoda'\` | Wrong Python / wrong venv | Activate the user's venv, re-run \`pip install "octopoda>=3.3.4"\`. |
| \`AuthError: Invalid API key\` | Key is wrong, expired, or missing | Re-run \`octopoda-init\`. Confirm key starts with \`sk-octopoda-\`. |
| \`OctopodaError: Request timed out\` | Transient cloud slowness | Retry once. Persistent issues → check <https://status.octopodas.com>. |
| \`RateLimitError\` or \`Agent limit reached: X/Y on <plan>\` | Free or comp-tier cap | The user must upgrade or delete unused agents. Re-using a stable \`agent_id\` (instead of creating a new one each run) avoids hitting agent caps. |
| \`SSL: CERTIFICATE_VERIFY_FAILED\` | Corporate proxy intercepting TLS | Set \`REQUESTS_CA_BUNDLE\` env var to the path of the proxy's CA cert. |
| \`TypeError: ...got an unexpected keyword argument...\` | Using an old API name | Re-read this doc's API reference — names like \`k\`, \`name\`, \`finding_key\` are wrong; the correct ones are \`limit\`, \`label\`, positional. |
| User wrote \`OctopodaCloud()\` | Old/copy-pasted from outdated docs | Replace with \`from octopoda import Octopoda; client = Octopoda()\`. |

---

## Mandatory: validate before declaring done

Before telling the user setup is complete, you **must** confirm all three:

1. \`python -c "import octopoda; print(octopoda.__version__)"\` prints \`3.3.4\` or higher.
2. \`python octopoda_test.py\` printed \`First run — writing memory now.\` on first run.
3. \`python octopoda_test.py\` printed \`Recalled from a previous run: dark mode\` on the second run.

If any of those fail, do not claim success. Use the error remediation table.

If the user picked a framework in Step 5, also run a one-line script that calls the framework wrapper's first method and confirm no exception is raised.

---

## What to say to the user when finished

After all three checks pass, output this and stop:

> Octopoda cloud memory is set up. Memory survives across restarts. Your dashboard at <https://octopodas.com> now shows an agent called \`<the agent_id you used>\`. You can write new memories with \`agent.remember(key, value)\` and read them back with \`agent.recall(key).value\`.

Do not list features the user didn't ask about. Do not upsell tiers. Do not add unrequested code to the user's project.

---

## One habit to teach the user

**Re-use stable \`agent_id\` strings.** An "agent" in Octopoda is just whatever string you pass to \`AgentRuntime(...)\`. If you generate a new random ID every run, every run creates a new agent — and agents count against the user's plan limit. Pick a stable name like \`"customer-support-bot"\` or \`"daily-pipeline"\` and use it consistently. Memory accumulates against that identity over time.

That is the entire mental model: one string per persistent identity, forever.

---

**Doc version: 3.3.4 · Verified: 2026-06-16 · Authority: <https://octopodas.com/setup-with-ai>**
`;function P(){const{prev:i,next:d}=h(),[o,r]=l.useState(!1),c=()=>{navigator.clipboard.writeText(a),r(!0),setTimeout(()=>r(!1),2e3)};return e.jsxs(g,{children:[e.jsx(u,{title:"Setup with AI Coding Assistant — Octopodas Docs",path:"/docs/setup-with-ai",description:"Paste this version-locked Octopoda 3.2.2+ guide into Cursor, Claude Code, Copilot, or ChatGPT to set up cloud memory on the first try."}),e.jsx(y,{eyebrow:"Start here",title:"Using AI or assisted coding to set up",lede:"A version-locked spec you paste into Cursor, Claude Code, Copilot, ChatGPT, Aider, or any AI coding assistant so it installs Octopoda cloud memory correctly on the first try.",meta:["Octopoda 3.2.2+","Copy & paste"]}),e.jsxs("div",{className:"my-6 rounded-2xl border border-primary/30 bg-primary/5 p-5",children:[e.jsxs("div",{className:"flex items-start gap-3 mb-3",children:[e.jsx("div",{className:"flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary shrink-0",children:e.jsx(b,{className:"h-5 w-5"})}),e.jsxs("div",{className:"flex-1 min-w-0",children:[e.jsx("p",{className:"text-sm font-semibold text-foreground mb-1",children:"Paste this whole document into your AI coding assistant"}),e.jsx("p",{className:"text-sm text-muted-foreground",children:"Open Cursor / Claude Code / ChatGPT, copy the entire guide below, and prepend the message:"}),e.jsx("p",{className:"mt-2 text-sm font-mono bg-muted/50 rounded px-3 py-2 text-foreground",children:'"Set up Octopoda cloud memory in my project using this guide. Follow it exactly."'})]})]}),e.jsxs("button",{onClick:c,className:"inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors",children:[o?e.jsx(m,{className:"h-4 w-4"}):e.jsx(v,{className:"h-4 w-4"}),o?"Copied!":"Copy entire guide to clipboard"]})]}),e.jsx("article",{className:"prose prose-invert max-w-none prose-headings:font-bold prose-h2:text-2xl prose-h2:mt-12 prose-h2:mb-4 prose-h3:text-xl prose-h3:mt-8 prose-h3:mb-3 prose-p:text-muted-foreground prose-p:leading-relaxed prose-li:text-muted-foreground prose-strong:text-foreground prose-a:text-primary prose-code:text-foreground prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-code:before:content-none prose-code:after:content-none prose-blockquote:border-l-primary prose-blockquote:text-muted-foreground prose-table:text-sm prose-th:text-foreground prose-td:text-muted-foreground prose-hr:border-border",children:e.jsx(k,{remarkPlugins:[x],components:{code:({className:t,children:s,...p})=>{const n=/language-(\w+)/.exec(t||"");return n?e.jsx(f,{lang:n[1],children:String(s).replace(/\n$/,"")}):e.jsx("code",{className:t,...p,children:s})},pre:({children:t})=>e.jsx(e.Fragment,{children:t})},children:a})}),e.jsx(w,{prev:i,next:d})]})}export{P as default};
