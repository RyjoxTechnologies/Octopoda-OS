# OpenAI Assistants API

Add persistent memory to OpenAI Assistants threads in two lines. When your process restarts, conversations resume from where they left off.

## Quickstart

Two lines. This is the whole integration.

```
pip install octopoda openai
```

Then in your code:

```python
from octopoda import OpenAIAgentsMemory
memory = OpenAIAgentsMemory()

# After each run, persist the thread state:
memory.store_thread_state(thread_id=thread.id, state={"messages": [...]})

# Later, in any new process:
restored = memory.restore_thread(thread.id)
```

That's it. Your thread survives process restarts, server crashes, and redeploys.

**What it does:** stores OpenAI thread state (messages, step, any custom fields) in Octopoda. You restore it by thread_id any time, anywhere, even on a different machine.

---

Keep reading only if you hit issues or want more control.

---

**Requires:** Python 3.9+, octopoda 3.1.4+, openai 2.x
**Setup time:** 3 minutes

**Note:** OpenAI has deprecated the Assistants API in favour of the Responses API. This integration still works. For new projects, check OpenAI's current recommendation first.

## Set both API keys

Octopoda and OpenAI each have their own key:

```
export OCTOPODA_API_KEY=sk-octopoda-...
export OPENAI_API_KEY=sk-...
```

If only `OCTOPODA_API_KEY` is set, your OpenAI calls fail with `openai.AuthenticationError`.

## Persist thread state

Call this after each meaningful thread update:

```python
memory.store_thread_state(
    thread_id=thread.id,
    state={
        "messages": [
            {"role": m.role, "content": m.content[0].text.value}
            for m in messages.data
        ],
    },
)
```

The `state` dict accepts any JSON-serialisable data — messages, tool calls, your own fields. Stored verbatim.

## Persist run results

After a run completes:

```python
memory.store_run_result(
    run_id=run.id,
    result={"status": run.status},
)
```

Useful for audit logs and run analytics.

## Restore a thread (safely)

```python
restored = memory.restore_thread(thread.id)

if restored.get("found") and restored.get("state"):
    state = restored["state"]
    messages = state.get("messages", [])
else:
    messages = []  # thread was never stored
```

`restore_thread` always returns a dict with three keys: `state`, `latency_us`, and `found`. When the thread doesn't exist, `state` is `None` and `found` is `False`. Always check `found` (or `state` being truthy) before using it — accessing `restored["state"]["messages"]` directly on a missing thread crashes with `TypeError: 'NoneType' object is not subscriptable`.

Octopoda injects two metadata fields into the state dict:

- `_tags` — list of storage tags
- `_stored_at` — float timestamp

Filter them out if needed:

```python
state_clean = {k: v for k, v in state.items() if not k.startswith("_")}
```

## Additional methods

```python
memory.get_all_threads()           # list every stored thread state
memory.get_all_runs()              # list every stored run result
memory.get_agent_history(agent_id) # semantic history for a named agent
```

## Full working example

```python
from openai import OpenAI
from octopoda import OpenAIAgentsMemory

client = OpenAI()
memory = OpenAIAgentsMemory()

# Create an assistant (once, reuse the ID)
assistant = client.beta.assistants.create(
    name="Support",
    instructions="Answer customer questions concisely.",
    model="gpt-4o-mini",
)

# Start a thread and send a message
thread = client.beta.threads.create()
client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="How do I reset my password?",
)

# Run the assistant and wait for completion
run = client.beta.threads.runs.create_and_poll(
    thread_id=thread.id,
    assistant_id=assistant.id,
)

# Pull the messages and persist
messages = client.beta.threads.messages.list(thread_id=thread.id)
memory.store_thread_state(
    thread_id=thread.id,
    state={
        "messages": [
            {"role": m.role, "content": m.content[0].text.value}
            for m in messages.data
        ],
    },
)
memory.store_run_result(run_id=run.id, result={"status": run.status})

# Later, in a fresh process
restored = memory.restore_thread(thread.id)
if restored.get("found") and restored.get("state"):
    prior = restored["state"].get("messages", [])
    print(f"Restored {len(prior)} messages")
```

## Cloud mode vs local mode

If `OCTOPODA_API_KEY` is set, state goes to Octopoda Cloud. If not set, OpenAIAgentsMemory falls back to local SQLite at `~/.synrix/data/synrix.db`. Same API, no code change.

Requires octopoda v3.1.4 or newer.

## Common mistakes

**Passing arguments to OpenAIAgentsMemory()**

```python
OpenAIAgentsMemory(agent_id="x")   # TypeError
```

The constructor takes no arguments.

**Crashing on missing thread**

```python
memory.restore_thread("nonexistent")["state"]["messages"]
# TypeError: 'NoneType' object is not subscriptable
```

`restore_thread` always returns a dict with `state`, `latency_us`, and `found` keys. For missing threads, `state` is `None` and `found` is `False`. Guard with `if restored.get("found") and restored.get("state")`.

**Storing raw OpenAI message objects**

```python
memory.store_thread_state(thread.id, {"messages": messages.data})
# TypeError — not JSON-serialisable
```

Convert to dicts first:

```python
{"role": m.role, "content": m.content[0].text.value}
```

## Troubleshooting

**TypeError on OpenAIAgentsMemory()** — you passed an argument. It takes none.

**openai.AuthenticationError** — `OPENAI_API_KEY` not set. Export it.

**restore_thread returns `{"state": null, "found": false}`** — thread_id doesn't match between store and restore, or you never stored it. IDs are case-sensitive.

**AuthError: api_key is required** — you're on octopoda < 3.1.4. Upgrade: `pip install --upgrade octopoda`. v3.1.4+ falls back to local SQLite with no key.

## Next step

For LangChain integration, see LangChain. For multi-agent chat, see AutoGen. For crew-based task execution, see CrewAI.
