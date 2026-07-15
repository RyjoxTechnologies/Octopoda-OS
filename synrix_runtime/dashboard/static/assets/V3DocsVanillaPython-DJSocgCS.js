import{aN as e,aU as i}from"./index-RsFqQstg.js";import{u as a,a as l,D as o,b as c,C as r,I as s,P as h}from"./V3DocsShared-BKwaCxO9.js";function m(){const{prev:n,next:t}=a();return e.jsxs(l,{children:[e.jsx(i,{title:"Vanilla Python — Octopodas Docs",path:"/docs/vanilla-python",description:"Two lines of code give your Python agent persistent memory across restarts, processes, and machines. No framework required."}),e.jsx(o,{eyebrow:"Vanilla Python",title:"Vanilla Python",lede:"For agents written without a framework. Two lines of code give your agent persistent memory across restarts, processes, and machines.",meta:["~2 min","Python 3.9+","octopoda 3.1.4+"]}),e.jsx(c,{tone:"info",title:"Prerequisite",children:"Finish the Getting started guide first so your API key is set. Without a key, this still works but writes to a local SQLite file instead of Octopoda Cloud."}),e.jsx("h2",{children:"Install"}),e.jsx("p",{children:"If you completed Getting started, you already have this:"}),e.jsx(r,{children:"pip install octopoda"}),e.jsx("h2",{children:"Two-line integration"}),e.jsx("p",{children:"Add this to the top of your agent script:"}),e.jsx(r,{lang:"python",children:`from octopoda import AgentRuntime

agent = AgentRuntime("your_agent_id")`}),e.jsx("p",{children:"That's the integration. You now have an agent with persistent memory. Everything below is how to use it."}),e.jsx("h2",{children:"Choosing your agent_id"}),e.jsxs("p",{children:["The string you pass to ",e.jsx(s,{children:"AgentRuntime()"})," is your agent's identity. Memory is scoped to this string. Use the same value every time you start your script, or you'll create a brand-new agent with empty memory."]}),e.jsx("p",{children:"Three common patterns:"}),e.jsx("h3",{children:"One agent per user (chatbots, personal assistants)"}),e.jsx(r,{lang:"python",children:'agent = AgentRuntime(f"user_{user_id}")'}),e.jsx("h3",{children:"One agent per role (support bot, research bot)"}),e.jsx(r,{lang:"python",children:'agent = AgentRuntime("customer_support_bot")'}),e.jsx("h3",{children:"One agent per conversation (short-lived sessions)"}),e.jsx(r,{lang:"python",children:'agent = AgentRuntime(f"conversation_{session_uuid}")'}),e.jsx("h3",{children:"Rules for agent_id"}),e.jsxs("ul",{className:"v3-list",children:[e.jsx("li",{children:"Must be a non-empty string"}),e.jsxs("li",{children:["Case-sensitive (",e.jsx(s,{children:'"MyBot"'})," and ",e.jsx(s,{children:'"mybot"'})," are two different agents)"]}),e.jsxs("li",{children:["No whitespace stripping (",e.jsx(s,{children:'"bot "'})," and ",e.jsx(s,{children:'"bot"'})," are two different agents)"]}),e.jsx("li",{children:"Stable across runs — if you're using f-strings, make sure the variable is deterministic"})]}),e.jsx("h3",{children:"Multiple agents in one script"}),e.jsx("p",{children:"You can create as many agents as you want. Each has independent memory:"}),e.jsx(r,{lang:"python",children:`support = AgentRuntime("support_bot")
research = AgentRuntime("research_bot")

support.remember("active_ticket", "T-1234")
research.remember("active_topic", "quantum computing")

support.recall("active_topic").found   # False — different agent
research.recall("active_topic").value  # "quantum computing"`}),e.jsx("h2",{children:"Storing memories (remember)"}),e.jsx("p",{children:"Anywhere in your code:"}),e.jsx(r,{lang:"python",children:'agent.remember("key", "value")'}),e.jsx("h3",{children:"What can value be?"}),e.jsx("p",{children:"Anything JSON-serialisable:"}),e.jsx(r,{lang:"python",children:`agent.remember("user_name", "Alex")                    # string
agent.remember("ticket_count", 42)                     # int
agent.remember("preferences", {"lang": "en", "tz": "GMT"})  # dict
agent.remember("recent_orders", [1001, 1002, 1003])    # list`}),e.jsx("p",{children:"Octopoda stores values verbatim and returns them unchanged on recall. You can nest structures up to any reasonable depth."}),e.jsx("h3",{children:"Key naming convention"}),e.jsx("p",{children:"Keys are just strings, but a namespace-like structure with colons makes your memory easier to browse in the dashboard:"}),e.jsx(r,{lang:"python",children:`agent.remember("user:name", "Alex")
agent.remember("user:email", "alex@example.com")
agent.remember("task:current", "process_refund")`}),e.jsx("p",{children:"No enforcement, but most users adopt this pattern."}),e.jsx("h3",{children:"What remember returns"}),e.jsx(r,{lang:"python",children:`result = agent.remember("user:name", "Alex")
# MemoryResult(node_id=..., key="user:name", success=True, latency_us=...)`}),e.jsxs("p",{children:["You rarely need to check it. Failures raise exceptions (network errors, quota exceeded, etc.), not silent ",e.jsx(s,{children:"success=False"}),". Check for exceptions if you need error handling."]}),e.jsx("h2",{children:"Reading memories (recall)"}),e.jsx(r,{lang:"python",children:'result = agent.recall("key")'}),e.jsxs("p",{children:[e.jsx(s,{children:"result"})," is a ",e.jsx(s,{children:"RecallResult"})," with four fields:"]}),e.jsxs("ul",{className:"v3-list",children:[e.jsxs("li",{children:[e.jsx(s,{children:"result.value"})," — the stored value, or ",e.jsx(s,{children:"None"})," if the key doesn't exist"]}),e.jsxs("li",{children:[e.jsx(s,{children:"result.found"})," — ",e.jsx(s,{children:"True"})," if the key exists, ",e.jsx(s,{children:"False"})," if not"]}),e.jsxs("li",{children:[e.jsx(s,{children:"result.key"})," — echo of the key you asked for"]}),e.jsxs("li",{children:[e.jsx(s,{children:"result.latency_us"})," — how long the recall took, in microseconds"]})]}),e.jsx("h3",{children:"Always check .found before using .value"}),e.jsxs("p",{children:["If the key doesn't exist, ",e.jsx(s,{children:"value"})," is ",e.jsx(s,{children:"None"}),". Using it unchecked can crash:"]}),e.jsx(r,{lang:"python",children:`name = agent.recall("user:name")

# Wrong — crashes if never stored
print(name.value.upper())

# Right
if name.found:
    print(name.value.upper())
else:
    print("user hasn't introduced themselves yet")`}),e.jsx("h2",{children:"Forgetting memories"}),e.jsx("p",{children:"To delete a memory:"}),e.jsx(r,{lang:"python",children:`result = agent.forget("user:name")
# {'key': 'user:name', 'deleted': True, 'reason': 'explicit_forget'}`}),e.jsxs("p",{children:[e.jsx(s,{children:"deleted"})," is ",e.jsx(s,{children:"False"})," only if the key didn't exist. No exception is raised."]}),e.jsx("h2",{children:"Thread safety"}),e.jsxs("p",{children:[e.jsx(s,{children:"AgentRuntime"})," is safe to share across threads. This is common in web servers:"]}),e.jsx(r,{lang:"python",children:`# Flask example
from flask import Flask
from octopoda import AgentRuntime

app = Flask(__name__)
agent = AgentRuntime("web_app")  # one instance, shared

@app.route("/remember", methods=["POST"])
def store():
    data = request.json
    agent.remember(data["key"], data["value"])
    return "ok"`}),e.jsx("p",{children:"Parallel writes from multiple requests are serialised correctly. Tested up to 100 concurrent writes per second with 100% persistence."}),e.jsx("h2",{children:"Semantic search (optional)"}),e.jsxs("p",{children:["The core install gives you exact-key lookups via ",e.jsx(s,{children:"recall"}),". For searching memories by meaning rather than exact key, install the AI extra:"]}),e.jsx(r,{children:'pip install "octopoda[ai]"'}),e.jsx("p",{children:"Then:"}),e.jsx(r,{lang:"python",children:`result = agent.recall_similar("what language does the user speak?", limit=3)
for item in result.items:
    print(item["key"], item["value"], item["score"])`}),e.jsx("h3",{children:"When to use recall_similar vs recall vs search"}),e.jsx("div",{className:"v3-table-wrap",children:e.jsxs("table",{className:"v3-table",children:[e.jsx("thead",{children:e.jsxs("tr",{children:[e.jsx("th",{children:"You want to…"}),e.jsx("th",{children:"Use"})]})}),e.jsxs("tbody",{children:[e.jsxs("tr",{children:[e.jsx("td",{children:"Find a specific value by exact key"}),e.jsx("td",{children:e.jsx(s,{children:'agent.recall("user:name")'})})]}),e.jsxs("tr",{children:[e.jsx("td",{children:"Find keys starting with a prefix"}),e.jsx("td",{children:e.jsx(s,{children:'agent.search("user:")'})})]}),e.jsxs("tr",{children:[e.jsx("td",{children:"Find memories by meaning"}),e.jsx("td",{children:e.jsx(s,{children:`agent.recall_similar("what is the user's language?")`})})]})]})]})}),e.jsxs("ul",{className:"v3-list",children:[e.jsxs("li",{children:[e.jsx(s,{children:"recall"})," is instant (under 100ms) and free."]}),e.jsxs("li",{children:[e.jsx(s,{children:"search"})," is instant and free."]}),e.jsxs("li",{children:[e.jsx(s,{children:"recall_similar"})," needs the ",e.jsx(s,{children:"[ai]"})," extra installed, uses embeddings, and takes ~100–200ms."]})]}),e.jsx("h2",{children:"Running two sessions — proving persistence"}),e.jsx("p",{children:"The clearest demo that memory survives process restarts is to put it in two separate files."}),e.jsx("h3",{children:"session_1.py"}),e.jsx(r,{lang:"python",children:`from octopoda import AgentRuntime

agent = AgentRuntime("triage_bot")
agent.remember("user:name", "Alex")
agent.remember("user:preferred_language", "en-GB")
print("stored")`}),e.jsx("h3",{children:"session_2.py (run AFTER session_1.py has exited)"}),e.jsx(r,{lang:"python",children:`from octopoda import AgentRuntime

agent = AgentRuntime("triage_bot")
name = agent.recall("user:name")
if name.found:
    print(f"Welcome back, {name.value}!")
else:
    print("No user stored yet.")`}),e.jsx("p",{children:"Run them in sequence:"}),e.jsx(r,{children:`python session_1.py
# output: stored

python session_2.py
# output: Welcome back, Alex!`}),e.jsxs("p",{children:["If ",e.jsx(s,{children:"session_2.py"}),' prints "Welcome back, Alex!", your agent has true cross-process memory. If it says "No user stored yet", either your'," ",e.jsx(s,{children:"agent_id"})," doesn't match between runs, or your environment variable isn't being picked up by the second run. Re-run the sanity check from Getting started."]}),e.jsx("h2",{children:"Local mode vs cloud mode"}),e.jsxs("p",{children:["If ",e.jsx(s,{children:"OCTOPODA_API_KEY"})," is set in your environment,"," ",e.jsx(s,{children:"AgentRuntime"})," uses cloud storage (Octopoda Cloud on our servers). If it's ",e.jsx("strong",{children:"not"})," set, everything above still works — writes go to"," ",e.jsx(s,{children:"~/.synrix/data/synrix.db"})," on your local machine."]}),e.jsx("p",{children:"No code change is needed to switch between modes. The same script works both ways. Upgrade from local to cloud by setting the env var whenever you're ready."}),e.jsx("h2",{children:"Full working example"}),e.jsx("p",{children:"A single file showing a typical usage pattern:"}),e.jsx(r,{lang:"python",children:`from octopoda import AgentRuntime

def greet_user(user_id: str) -> str:
    agent = AgentRuntime(f"user_{user_id}")

    name = agent.recall("user:name")
    if name.found:
        return f"Welcome back, {name.value}!"
    return "Hi there! What's your name?"

def remember_name(user_id: str, name: str):
    agent = AgentRuntime(f"user_{user_id}")
    agent.remember("user:name", name)

# On first visit:
print(greet_user("u123"))  # "Hi there! What's your name?"
remember_name("u123", "Alex")

# On next visit, even hours later, in a fresh process:
print(greet_user("u123"))  # "Welcome back, Alex!"`}),e.jsx("h2",{children:"Common mistakes"}),e.jsx("h3",{children:"Forgetting to check .found"}),e.jsx(r,{lang:"python",children:`agent.recall("user:name").value.upper()
# AttributeError if never stored. Check .found first.`}),e.jsx("h3",{children:"Using a different agent_id between runs"}),e.jsx(r,{lang:"python",children:`# File A
AgentRuntime("customer_bot").remember("x", "y")

# File B
AgentRuntime("customerBot").recall("x").found  # False — different agent`}),e.jsx("p",{children:"Case and whitespace matter."}),e.jsx("h3",{children:"Assuming recall_similar works without [ai] extras"}),e.jsx(r,{lang:"python",children:`# Without octopoda[ai] installed:
agent.recall_similar("query")
# Returns empty SearchResult. No error, just no results.`}),e.jsxs("p",{children:["Install the extra if you need semantic search:"," ",e.jsx(s,{children:'pip install "octopoda[ai]"'}),"."]}),e.jsx("h3",{children:"Treating recall_similar results like a plain list"}),e.jsx(r,{lang:"python",children:`# Wrong:
for h in agent.recall_similar("query"):
    print(h.key)
# TypeError — SearchResult is not iterable, .items is.

# Right:
result = agent.recall_similar("query")
for item in result.items:
    print(item["key"])`}),e.jsx("h2",{children:"Next step"}),e.jsx("p",{children:"You now have persistent memory. Most users stop here — Vanilla Python is all they need."}),e.jsx("p",{children:"If you use a framework (LangChain, CrewAI, AutoGen, OpenAI Agents), the framework-specific guide is a thin layer on top of what you just learned. Read those if you want framework integration."}),e.jsx(h,{prev:n,next:t})]})}export{m as default};
