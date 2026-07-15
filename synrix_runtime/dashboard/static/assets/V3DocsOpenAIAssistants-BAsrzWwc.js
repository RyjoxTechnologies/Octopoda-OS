import{aN as e,aU as a}from"./index-RsFqQstg.js";import{u as o,a as i,D as d,C as t,b as h,I as s,P as l}from"./V3DocsShared-BKwaCxO9.js";function p(){const{prev:r,next:n}=o();return e.jsxs(i,{children:[e.jsx(a,{title:"OpenAI Assistants API — Octopodas Docs",path:"/docs/openai-assistants",description:"Add persistent memory to OpenAI Assistants API threads with OpenAIAgentsMemory. Resume conversations across restarts. Manual integration."}),e.jsx(d,{eyebrow:"Framework",title:"OpenAI Assistants API",lede:"Add persistent memory to OpenAI Assistants API threads in two lines. When your process restarts, conversations resume from where they left off. This is the manual thread-state integration — for the OpenAI Agents SDK (Runner.run), see the auto-instrumented Agents SDK page.",meta:["openai 2.x","~3 min","Manual"]}),e.jsx("h2",{children:"Quickstart"}),e.jsx("p",{children:"Two lines. This is the whole integration."}),e.jsx(t,{children:"pip install octopoda openai"}),e.jsx("p",{children:"Then in your code:"}),e.jsx(t,{lang:"python",children:`from octopoda import OpenAIAgentsMemory

memory = OpenAIAgentsMemory()

# After each run, persist the thread state:
memory.store_thread_state(thread_id=thread.id, state={"messages": [...]})

# Later, in any new process:
restored = memory.restore_thread(thread.id)`}),e.jsx("p",{children:"That's it. Your thread survives process restarts, server crashes, and redeploys."}),e.jsxs("p",{children:[e.jsx("strong",{children:"What it does:"})," stores OpenAI thread state (messages, step, any custom fields) in Octopoda. You restore it by thread_id any time, anywhere, even on a different machine."]}),e.jsx("p",{children:e.jsx("em",{children:"Keep reading only if you hit issues or want more control."})}),e.jsxs(h,{title:"Before you start",children:[e.jsx("strong",{children:"Requires:"})," Python 3.9+, octopoda 3.1.4+, openai 2.x."," ",e.jsx("strong",{children:"Note:"})," OpenAI has deprecated the Assistants API in favour of the Responses API. This integration still works. For new projects, check OpenAI's current recommendation first."]}),e.jsx("h2",{children:"API keys"}),e.jsxs("p",{children:["Only ",e.jsx(s,{children:"OCTOPODA_API_KEY"})," is required — Octopoda's server-side extraction means no other key is needed for memory itself. An"," ",e.jsx(s,{children:"OPENAI_API_KEY"})," is only required if ",e.jsx("em",{children:"your own code"})," also calls the OpenAI API directly (as in the example below):"]}),e.jsx(t,{children:`export OCTOPODA_API_KEY=sk-octopoda-...
export OPENAI_API_KEY=sk-...   # optional — only if you call OpenAI yourself`}),e.jsx("h2",{children:"Persist thread state"}),e.jsx("p",{children:"Call this after each meaningful thread update:"}),e.jsx(t,{lang:"python",children:`memory.store_thread_state(
    thread_id=thread.id,
    state={
        "messages": [
            {"role": m.role, "content": m.content[0].text.value}
            for m in messages.data
        ],
    },
)`}),e.jsxs("p",{children:["The ",e.jsx(s,{children:"state"})," dict accepts any JSON-serialisable data — messages, tool calls, your own fields. Stored verbatim."]}),e.jsx("h2",{children:"Persist run results"}),e.jsx("p",{children:"After a run completes:"}),e.jsx(t,{lang:"python",children:`memory.store_run_result(
    run_id=run.id,
    result={"status": run.status},
)`}),e.jsx("p",{children:"Useful for audit logs and run analytics."}),e.jsx("h2",{children:"Restore a thread (safely)"}),e.jsx(t,{lang:"python",children:`restored = memory.restore_thread(thread.id)

if restored.get("found") and restored.get("state"):
    state = restored["state"]
    messages = state.get("messages", [])
else:
    messages = []  # thread was never stored`}),e.jsxs("p",{children:["Always guard with the ",e.jsx(s,{children:"if"}),". ",e.jsx(s,{children:"restore_thread"})," always returns a dict with three keys: ",e.jsx(s,{children:"state"}),", ",e.jsx(s,{children:"latency_us"}),", and ",e.jsx(s,{children:"found"}),". When the thread doesn't exist, ",e.jsx(s,{children:"state"})," is ",e.jsx(s,{children:"None"})," and ",e.jsx(s,{children:"found"})," is ",e.jsx(s,{children:"False"}),". Accessing ",e.jsx(s,{children:'restored["state"]["messages"]'})," directly on a missing thread crashes with ",e.jsx(s,{children:"TypeError: 'NoneType' object is not subscriptable"}),"."]}),e.jsx("p",{children:"Octopoda injects two metadata fields into the state dict:"}),e.jsxs("ul",{children:[e.jsxs("li",{children:[e.jsx(s,{children:"_tags"})," — list of storage tags"]}),e.jsxs("li",{children:[e.jsx(s,{children:"_stored_at"})," — float timestamp"]})]}),e.jsx("p",{children:"Filter them out if needed:"}),e.jsx(t,{lang:"python",children:'state_clean = {k: v for k, v in state.items() if not k.startswith("_")}'}),e.jsx("h2",{children:"Additional methods"}),e.jsx(t,{lang:"python",children:`memory.get_all_threads()           # list every stored thread state
memory.get_all_runs()              # list every stored run result
memory.get_agent_history(agent_id) # semantic history for a named agent`}),e.jsx("h2",{children:"Full working example"}),e.jsx(t,{lang:"python",children:`from openai import OpenAI
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
    print(f"Restored {len(prior)} messages")`}),e.jsx("h2",{children:"Cloud mode vs local mode"}),e.jsxs("p",{children:["If ",e.jsx(s,{children:"OCTOPODA_API_KEY"})," is set, state goes to Octopoda Cloud. If not set, OpenAIAgentsMemory falls back to local SQLite at ",e.jsx(s,{children:"~/.synrix/data/synrix.db"}),". Same API, no code change."]}),e.jsx("p",{children:"Requires octopoda v3.1.4 or newer."}),e.jsx("h2",{children:"Common mistakes"}),e.jsx("h3",{children:"Passing arguments to OpenAIAgentsMemory()"}),e.jsx(t,{lang:"python",children:'OpenAIAgentsMemory(agent_id="x")   # TypeError'}),e.jsx("p",{children:"The constructor takes no arguments."}),e.jsx("h3",{children:"Crashing on missing thread"}),e.jsx(t,{lang:"python",children:`restored = memory.restore_thread("nonexistent")
if restored.get("found") and restored.get("state"):
    messages = restored["state"].get("messages", [])
else:
    messages = []  # thread was never stored`}),e.jsxs("p",{children:[e.jsx(s,{children:"restore_thread"})," always returns a dict with ",e.jsx(s,{children:"state"}),", ",e.jsx(s,{children:"latency_us"}),", and ",e.jsx(s,{children:"found"}),". When the thread doesn't exist, ",e.jsx(s,{children:"state"})," is ",e.jsx(s,{children:"None"})," and ",e.jsx(s,{children:"found"})," is ",e.jsx(s,{children:"False"}),". Always check ",e.jsx(s,{children:"found"})," (or that ",e.jsx(s,{children:"state"})," is truthy) before using it — accessing ",e.jsx(s,{children:'restored["state"]["messages"]'})," directly on a missing thread crashes with ",e.jsx(s,{children:"TypeError: 'NoneType' object is not subscriptable"}),"."]}),e.jsx("h3",{children:"Storing raw OpenAI message objects"}),e.jsx(t,{lang:"python",children:`memory.store_thread_state(thread.id, {"messages": messages.data})
# TypeError — not JSON-serialisable`}),e.jsx("p",{children:"Convert to dicts first:"}),e.jsx(t,{lang:"python",children:'{"role": m.role, "content": m.content[0].text.value}'}),e.jsx("h2",{children:"Troubleshooting"}),e.jsxs("p",{children:[e.jsx("strong",{children:"TypeError on OpenAIAgentsMemory()"})," — you passed an argument. It takes none."]}),e.jsxs("p",{children:[e.jsx("strong",{children:"openai.AuthenticationError"})," — ",e.jsx(s,{children:"OPENAI_API_KEY"})," not set. Export it."]}),e.jsxs("p",{children:[e.jsx("strong",{children:"restore_thread returns None for state"})," — thread_id doesn't match between store and restore, or you never stored it. IDs are case-sensitive. ",e.jsx(s,{children:"restore_thread"})," always returns a dict with ",e.jsx(s,{children:"state"}),", ",e.jsx(s,{children:"latency_us"}),", and ",e.jsx(s,{children:"found"}),". When the thread doesn't exist, ",e.jsx(s,{children:"state"})," is ",e.jsx(s,{children:"None"})," and ",e.jsx(s,{children:"found"})," is ",e.jsx(s,{children:"False"}),". Always check ",e.jsx(s,{children:"found"})," (or that ",e.jsx(s,{children:"state"})," is truthy) before using it — accessing ",e.jsx(s,{children:'restored["state"]["messages"]'})," directly on a missing thread crashes with ",e.jsx(s,{children:"TypeError: 'NoneType' code--object is not subscriptable"}),"."]}),e.jsxs("p",{children:[e.jsx("strong",{children:"AuthError: api_key is required"})," — you're on octopoda < 3.1.4. Upgrade: ",e.jsx(s,{children:"pip install --upgrade octopoda"}),". v3.1.4+ falls back to local SQLite with no key."]}),e.jsx("h2",{children:"Next step"}),e.jsx("p",{children:"For LangChain integration, see LangChain. For multi-agent chat, see AutoGen. For crew-based task execution, see CrewAI."}),e.jsx(l,{prev:r,next:n})]})}export{p as default};
