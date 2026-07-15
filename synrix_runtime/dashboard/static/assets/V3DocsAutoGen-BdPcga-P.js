import{aN as e,aU as o}from"./index-RsFqQstg.js";import{u as i,a,D as c,b as l,I as n,C as t,P as h}from"./V3DocsShared-BKwaCxO9.js";function m(){const{prev:r,next:s}=i();return e.jsxs(a,{children:[e.jsx(o,{title:"AutoGen — Octopodas Docs",path:"/docs/autogen",description:"Group-scoped persistent memory for AutoGen group chats. Store every message and replay across runs."}),e.jsx(c,{eyebrow:"Framework",title:"AutoGen",lede:"AutoGen organises around group chats, so Octopoda memory is group-scoped. Store every message and replay the conversation in any future run.",meta:["autogen-agentchat 0.7+","~3 min"]}),e.jsxs(l,{title:"Before you start",children:[e.jsx("strong",{children:"Requires:"})," Python 3.9+, octopoda 3.1.4+, autogen-agentchat 0.7+."," ",e.jsx("strong",{children:"Prerequisite:"})," Finish Getting started so your API key is set."]}),e.jsx("h2",{children:"Install"}),e.jsxs("p",{children:["Use the modern ",e.jsx(n,{children:"autogen-agentchat"})," package. The older ",e.jsx(n,{children:"pyautogen"})," package is deprecated and not supported."]}),e.jsx(t,{children:"pip install octopoda autogen-agentchat autogen-core"}),e.jsx("p",{children:"For the OpenAI model client used in the full example:"}),e.jsx(t,{children:'pip install "autogen-ext[openai]"'}),e.jsxs("p",{children:["Only ",e.jsx(n,{children:"OCTOPODA_API_KEY"})," is required for memory. Your LLM provider key is optional and only needed if your agent code calls that provider directly:"]}),e.jsx(t,{children:"export OPENAI_API_KEY=sk-...   # optional — only if you use OpenAIChatCompletionClient"}),e.jsx("h2",{children:"Two-step integration"}),e.jsx("h3",{children:"Step 1 — Import the memory bus"}),e.jsx(t,{lang:"python",children:"from octopoda import AutoGenMemory"}),e.jsx("h3",{children:"Step 2 — Create it with your group_id"}),e.jsx(t,{lang:"python",children:'memory = AutoGenMemory(group_id="your_group_id")'}),e.jsxs("p",{children:["The argument is ",e.jsx(n,{children:"group_id"}),", not ",e.jsx(n,{children:"agent_id"}),". Passing"," ",e.jsx(n,{children:"agent_id="})," will raise ",e.jsx(n,{children:"TypeError: got an unexpected keyword argument 'agent_id'"}),"."]}),e.jsxs("p",{children:[e.jsx(n,{children:"group_id"})," identifies one group chat configuration. Use the same value every run of the same team."]}),e.jsx("h2",{children:"Store messages as they happen"}),e.jsx("p",{children:"After each message event in your group chat:"}),e.jsx(t,{lang:"python",children:"memory.store_message(sender, recipient, content)"}),e.jsx("p",{children:"All three arguments are strings, all three are positional (or pass as keywords for clarity):"}),e.jsxs("ul",{children:[e.jsxs("li",{children:[e.jsx(n,{children:"sender"})," — agent name that sent the message"]}),e.jsxs("li",{children:[e.jsx(n,{children:"recipient"})," — target agent name, or ",e.jsx(n,{children:'"group"'})," for broadcasts"]}),e.jsxs("li",{children:[e.jsx(n,{children:"content"})," — the message text"]})]}),e.jsx("h3",{children:'When to use "group" vs a specific agent name'}),e.jsxs("p",{children:["In RoundRobinGroupChat and similar broadcast patterns, every agent sees every message. Use ",e.jsx(n,{children:'"group"'})," as recipient."]}),e.jsx("p",{children:"In targeted multi-agent setups where you want who-said-what-to-whom tracking, pass the specific target agent's name."}),e.jsx("h2",{children:"Retrieve in a later run"}),e.jsx(t,{lang:"python",children:`memory = AutoGenMemory(group_id="your_group_id")
history = memory.get_conversation_history()

for m in history:
    print(f"{m['sender']} to {m['recipient']}: {m['content']}")`}),e.jsxs("p",{children:["Each message is a dict with ",e.jsx(n,{children:"sender"}),", ",e.jsx(n,{children:"recipient"}),","," ",e.jsx(n,{children:"content"}),", and a ",e.jsx(n,{children:"timestamp"})," field."]}),e.jsx("h2",{children:"Other useful methods"}),e.jsx(t,{lang:"python",children:`# Semantic search within the conversation
memory.search_conversations("user's preferences")

# All messages a specific agent sent or received
memory.get_agent_knowledge("planner")

# Export whole conversation as text/JSON
memory.export_conversation()

# Conversation statistics
memory.get_stats()
# {'message_count': 42, 'unique_agents': 3, ...}`}),e.jsx("h2",{children:"Full working example"}),e.jsx(t,{lang:"python",children:`import asyncio
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_ext.models.openai import OpenAIChatCompletionClient
from octopoda import AutoGenMemory

memory = AutoGenMemory(group_id="research_team")

# Replay prior conversation, if any
for m in memory.get_conversation_history():
    print(f"[history] {m['sender']} -> {m['recipient']}: {m['content']}")

model = OpenAIChatCompletionClient(model="gpt-4o-mini")

planner = AssistantAgent("planner", model_client=model,
    system_message="Plan tasks concisely.")
worker = AssistantAgent("worker", model_client=model,
    system_message="Execute tasks concisely.")

team = RoundRobinGroupChat(
    [planner, worker],
    termination_condition=MaxMessageTermination(max_messages=4),
)

async def run():
    async for event in team.run_stream(task="Plan and execute: research AI memory tools"):
        if hasattr(event, 'source') and hasattr(event, 'content'):
            memory.store_message(
                sender=str(event.source),
                recipient="group",
                content=str(event.content),
            )

asyncio.run(run())

# After the run, inspect what was stored
print(f"Stored {len(memory.get_conversation_history())} messages")`}),e.jsx("h2",{children:"Cross-process persistence"}),e.jsxs("p",{children:["The simplest proof that memory survives restarts: run the example above, print"," ",e.jsx(n,{children:"len(memory.get_conversation_history())"})," — say 4 messages. Then quit Python, open a new process:"]}),e.jsx(t,{lang:"python",children:`from octopoda import AutoGenMemory

memory = AutoGenMemory(group_id="research_team")
print(len(memory.get_conversation_history()))
# 4`}),e.jsx("p",{children:"Same count, no loss. Memory persisted."}),e.jsx("h2",{children:"Common mistakes"}),e.jsx("h3",{children:"Passing agent_id instead of group_id"}),e.jsx(t,{lang:"python",children:'AutoGenMemory(agent_id="x")   # TypeError'}),e.jsxs("p",{children:["Use ",e.jsx(n,{children:"group_id="}),"."]}),e.jsx("h3",{children:"Not filtering event types"}),e.jsx(t,{lang:"python",children:`for event in team.run_stream(task="..."):
    memory.store_message(event.source, "group", event.content)
# AttributeError on TaskResult or ToolCallEvent`}),e.jsx("p",{children:"Always check attributes first:"}),e.jsx(t,{lang:"python",children:"if hasattr(event, 'source') and hasattr(event, 'content'):"}),e.jsx("h3",{children:"Forgetting asyncio.run"}),e.jsx(t,{lang:"python",children:`async def run(): ...
# script ends without ever running the coroutine`}),e.jsxs("p",{children:["The async function must be invoked: ",e.jsx(n,{children:"asyncio.run(run())"})," or ",e.jsx(n,{children:"await run()"})," inside another async context."]}),e.jsx("h3",{children:"model_client=..."}),e.jsx("p",{children:"Literal ellipsis is a placeholder in docs. Real code needs a real client:"}),e.jsx(t,{lang:"python",children:`from autogen_ext.models.openai import OpenAIChatCompletionClient
model = OpenAIChatCompletionClient(model="gpt-4o-mini")`}),e.jsx("h3",{children:"Changing group_id between runs"}),e.jsx(t,{lang:"python",children:`AutoGenMemory(group_id="team_1")          # run 1
AutoGenMemory(group_id="team-1")          # run 2
# Different groups. Run 2 sees empty history.`}),e.jsxs("p",{children:["Stable ",e.jsx(n,{children:"group_id"})," is required for persistence."]}),e.jsx("h2",{children:"Troubleshooting"}),e.jsx("h3",{children:"TypeError: got an unexpected keyword argument 'agent_id'"}),e.jsxs("p",{children:["Use ",e.jsx(n,{children:"group_id="})," instead. AutoGen memory is group-scoped."]}),e.jsx("h3",{children:"AttributeError: 'TaskResult' has no attribute 'content'"}),e.jsx("p",{children:"Your stream loop isn't filtering event types. See Common Mistakes."}),e.jsx("h3",{children:"openai.AuthenticationError"}),e.jsxs("p",{children:[e.jsx(n,{children:"OPENAI_API_KEY"})," is not set. Export it."]}),e.jsx("h3",{children:"ImportError: cannot import name 'OpenAIChatCompletionClient'"}),e.jsx("p",{children:"Missing the ext package:"}),e.jsx(t,{children:'pip install "autogen-ext[openai]"'}),e.jsx("h3",{children:"AuthError: api_key is required (Octopoda)"}),e.jsx("p",{children:"You're on octopoda < 3.1.4. Upgrade:"}),e.jsx(t,{children:"pip install --upgrade octopoda"}),e.jsx("p",{children:"v3.1.4+ falls back to local SQLite when no cloud key is set."}),e.jsx("h3",{children:"History empty after many runs"}),e.jsxs("p",{children:["Your ",e.jsx(n,{children:"group_id"})," is changing between runs, or your env var isn't being picked up. Check both."]}),e.jsx("h2",{children:"Next step"}),e.jsx("p",{children:"For single-agent chat with LangChain, see LangChain. For crew-based task execution, see CrewAI. For raw memory outside any framework, see Vanilla Python."}),e.jsx(h,{prev:r,next:s})]})}export{m as default};
