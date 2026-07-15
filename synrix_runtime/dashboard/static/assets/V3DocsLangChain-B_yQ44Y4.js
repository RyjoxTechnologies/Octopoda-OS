import{aN as e,aU as t}from"./index-RsFqQstg.js";import{u as r,a,D as h,b as l,C as o,I as s,P as c}from"./V3DocsShared-BKwaCxO9.js";function m(){const{prev:n,next:i}=r();return e.jsxs(a,{children:[e.jsx(t,{title:"LangChain — Octopodas Docs",path:"/docs/langchain",description:"Add persistent memory to LangChain 1.x runnables with OctopodaChatHistory. Drop-in replacement for in-memory chat history."}),e.jsx(h,{eyebrow:"Framework",title:"LangChain",lede:"OctopodaChatHistory plugs into RunnableWithMessageHistory. Your chain keeps the same shape — only the message history backend changes. Works with cloud or local mode from v3.1.4 onward.",meta:["LangChain 1.x","~3 min"]}),e.jsxs(l,{title:"Before you start",children:[e.jsx("strong",{children:"Requires:"})," Python 3.9+, octopoda 3.1.4+, langchain 1.x."," ",e.jsx("strong",{children:"Prerequisite:"})," Finish Getting started so your API key is set. Local mode (no key) also works from v3.1.4."]}),e.jsx("h2",{children:"Install"}),e.jsx("p",{children:"Check your LangChain version:"}),e.jsx(o,{children:"pip show langchain"}),e.jsx("p",{children:"If it's 0.x, upgrade:"}),e.jsx(o,{children:"pip install --upgrade langchain langchain-core"}),e.jsx("p",{children:"Install all the pieces the examples below use:"}),e.jsx(o,{children:"pip install octopoda langchain langchain-core langchain-openai"}),e.jsxs("p",{children:["You only need ",e.jsx(s,{children:"langchain-openai"})," if you're using OpenAI as the LLM. For Anthropic:"," ",e.jsx(s,{children:"pip install langchain-anthropic"}),". For Groq, Ollama, etc., install the matching package."]}),e.jsx("h2",{children:"API keys"}),e.jsxs("p",{children:["Only ",e.jsx(s,{children:"OCTOPODA_API_KEY"})," is required for memory — Octopoda extracts on its servers, so no LLM provider key is needed for the memory layer. You only need an LLM key if ",e.jsx("em",{children:"your own LangChain code"})," calls a provider directly (e.g.",e.jsx(s,{children:"ChatOpenAI"}),"):"]}),e.jsx(o,{children:`export OPENAI_API_KEY=sk-...           # optional — only if you use ChatOpenAI
export ANTHROPIC_API_KEY=sk-ant-...    # optional — only if you use ChatAnthropic`}),e.jsx("h2",{children:"Two-step integration"}),e.jsx("h3",{children:"Step 1 — Import the message history class"}),e.jsx(o,{lang:"python",children:`from octopoda import OctopodaChatHistory
from langchain_core.runnables.history import RunnableWithMessageHistory`}),e.jsxs("p",{children:[e.jsx(s,{children:"OctopodaChatHistory"})," is a ",e.jsx(s,{children:"BaseChatMessageHistory"})," subclass. Any LangChain component that accepts a message history accepts this."]}),e.jsx("h3",{children:"Step 2 — Wrap your chain"}),e.jsx("p",{children:"Build your chain as normal, then wrap it:"}),e.jsx(o,{lang:"python",children:`def get_session_history(session_id: str):
    return OctopodaChatHistory(agent_id="your_bot_id", session_id=session_id)

chain_with_memory = RunnableWithMessageHistory(
    your_chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)`}),e.jsx("h3",{children:"What agent_id and session_id mean"}),e.jsxs("ul",{children:[e.jsxs("li",{children:[e.jsx(s,{children:"agent_id"})," — identifies your bot. One per product or role. Hardcode it."]}),e.jsxs("li",{children:[e.jsx(s,{children:"session_id"})," — identifies a single conversation. Pass a different value per user or per thread."]})]}),e.jsx("p",{children:"Example mapping:"}),e.jsx(o,{lang:"python",children:`# support bot with many users
OctopodaChatHistory(agent_id="support_bot", session_id=f"user_{user_id}")

# research bot with many threads
OctopodaChatHistory(agent_id="research_bot", session_id=f"thread_{thread_id}")`}),e.jsx("h2",{children:"Your prompt template must include MessagesPlaceholder"}),e.jsx("p",{children:"This is the most common silent failure. If your prompt doesn't inject the history back in, the bot stores memory but acts as if it has none."}),e.jsx(o,{lang:"python",children:`from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant."),
    MessagesPlaceholder("history"),
    ("human", "{input}"),
])`}),e.jsxs("p",{children:["The ",e.jsx(s,{children:"history"})," name in ",e.jsx(s,{children:"MessagesPlaceholder"})," must match the"," ",e.jsx(s,{children:"history_messages_key"})," you pass to ",e.jsx(s,{children:"RunnableWithMessageHistory"}),"."]}),e.jsx("h2",{children:"Invoke the wrapped chain"}),e.jsx(o,{lang:"python",children:`config = {"configurable": {"session_id": "user_12345"}}

response = chain_with_memory.invoke({"input": "Hi, I'm Alex."}, config=config)
print(response.content)

response = chain_with_memory.invoke({"input": "What's my name?"}, config=config)
print(response.content)
# "Your name is Alex."`}),e.jsxs("p",{children:["Same ",e.jsx(s,{children:"session_id"})," across invocations continues the same conversation. Different ",e.jsx(s,{children:"session_id"})," starts a fresh one."]}),e.jsx("h2",{children:"Clearing a session's history"}),e.jsx("p",{children:"To let a user start over without affecting other sessions:"}),e.jsx(o,{lang:"python",children:`history = OctopodaChatHistory(agent_id="your_bot_id", session_id="user_12345")
history.clear()`}),e.jsxs("p",{children:["This deletes only that session's messages. Other sessions under the same ",e.jsx(s,{children:"agent_id"})," are untouched."]}),e.jsx("h2",{children:"Inspecting raw history"}),e.jsx("p",{children:"For debugging or custom summarisation:"}),e.jsx(o,{lang:"python",children:`history = OctopodaChatHistory(agent_id="your_bot_id", session_id="user_12345")
for msg in history.messages:
    print(type(msg).__name__, msg.content)
# HumanMessage Hi, I'm Alex.
# AIMessage Hi Alex, nice to meet you.`}),e.jsxs("p",{children:[e.jsx(s,{children:".messages"})," returns a ",e.jsx(s,{children:"List[BaseMessage]"})," —"," ",e.jsx(s,{children:"HumanMessage"}),", ",e.jsx(s,{children:"AIMessage"}),", ",e.jsx(s,{children:"SystemMessage"}),". Standard LangChain types."]}),e.jsx("h2",{children:"Async and streaming"}),e.jsx("p",{children:"Works out of the box with LangChain's async methods:"}),e.jsx(o,{lang:"python",children:`# async invoke
response = await chain_with_memory.ainvoke({"input": "Hi"}, config=config)

# streaming
async for chunk in chain_with_memory.astream({"input": "Hi"}, config=config):
    print(chunk.content, end="")`}),e.jsx("p",{children:"OctopodaChatHistory saves messages after the invocation completes, regardless of whether you used invoke, ainvoke, stream, or astream."}),e.jsx("h2",{children:"LangGraph compatibility"}),e.jsxs("p",{children:["LangGraph users can use OctopodaChatHistory inside a stateful graph by treating it as the conversation memory store for a node. The integration pattern is the same — wrap the runnable node in ",e.jsx(s,{children:"RunnableWithMessageHistory"})," or call the history API directly from within your graph's state updater."]}),e.jsx("h2",{children:"Local mode vs cloud mode"}),e.jsxs("p",{children:["If ",e.jsx(s,{children:"OCTOPODA_API_KEY"})," is set, messages go to Octopoda Cloud. If not set, OctopodaChatHistory falls back to local SQLite at ",e.jsx(s,{children:"~/.synrix/data/synrix.db"}),". Same API, no code change."]}),e.jsxs("p",{children:["Requires octopoda v3.1.4 or newer. Earlier versions required a cloud key and would raise ",e.jsx(s,{children:"AuthError"})," in local mode."]}),e.jsx("h2",{children:"Cross-process persistence (the real test)"}),e.jsx("p",{children:"Two separate files to prove memory survives restarts."}),e.jsx("p",{children:e.jsx("strong",{children:"session_1.py:"})}),e.jsx(o,{lang:"python",children:`from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from octopoda import OctopodaChatHistory

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are helpful. Remember what the user tells you."),
    MessagesPlaceholder("history"),
    ("human", "{input}"),
])
chain = prompt | ChatOpenAI(model="gpt-4o-mini")

def get_history(session_id):
    return OctopodaChatHistory(agent_id="demo_bot", session_id=session_id)

bot = RunnableWithMessageHistory(chain, get_history,
    input_messages_key="input", history_messages_key="history")

cfg = {"configurable": {"session_id": "alice"}}
print(bot.invoke({"input": "My name is Alex. I live in Paris."}, config=cfg).content)`}),e.jsxs("p",{children:[e.jsx("strong",{children:"session_2.py"})," (run AFTER session_1.py exits):"]}),e.jsx(o,{lang:"python",children:`from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from octopoda import OctopodaChatHistory

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are helpful. Remember what the user tells you."),
    MessagesPlaceholder("history"),
    ("human", "{input}"),
])
chain = prompt | ChatOpenAI(model="gpt-4o-mini")

def get_history(session_id):
    return OctopodaChatHistory(agent_id="demo_bot", session_id=session_id)

bot = RunnableWithMessageHistory(chain, get_history,
    input_messages_key="input", history_messages_key="history")

cfg = {"configurable": {"session_id": "alice"}}
print(bot.invoke({"input": "What's my name and where do I live?"}, config=cfg).content)
# "Your name is Alex and you live in Paris."`}),e.jsx("p",{children:"If session 2 remembers Alex and Paris, your persistence is working."}),e.jsx("h2",{children:"Full example (single file, two turns)"}),e.jsx(o,{lang:"python",children:`from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from octopoda import OctopodaChatHistory

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant."),
    MessagesPlaceholder("history"),
    ("human", "{input}"),
])
chain = prompt | ChatOpenAI(model="gpt-4o-mini")

def get_session_history(session_id: str):
    return OctopodaChatHistory(agent_id="support_bot", session_id=session_id)

bot = RunnableWithMessageHistory(
    chain, get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)

config = {"configurable": {"session_id": "user_12345"}}
print(bot.invoke({"input": "My name is Alex."}, config=config).content)
print(bot.invoke({"input": "What is my name?"}, config=config).content)`}),e.jsx("h2",{children:"Common mistakes"}),e.jsx("h3",{children:"Forgetting MessagesPlaceholder"}),e.jsx(o,{lang:"python",children:`prompt = ChatPromptTemplate.from_messages([
    ("system", "You are helpful."),
    ("human", "{input}"),  # no history injected
])`}),e.jsx("p",{children:"Memory stores correctly but never reaches the LLM. Bot seems amnesiac."}),e.jsx("h3",{children:"Mismatched history key name"}),e.jsx(o,{lang:"python",children:`prompt = ChatPromptTemplate.from_messages([..., MessagesPlaceholder("chat_history"), ...])
RunnableWithMessageHistory(..., history_messages_key="history")  # different`}),e.jsx("p",{children:"Memory loads but into the wrong slot. Add the wrong name to either side and history disappears."}),e.jsx("h3",{children:"Using the deprecated LangChainMemory class"}),e.jsx(o,{lang:"python",children:"from octopoda import LangChainMemory  # old, broken on LangChain 1.x"}),e.jsxs("p",{children:["Raises ",e.jsx(s,{children:"AttributeError: 'SynrixMemory' object has no attribute 'messages'"})," when wrapped in RunnableWithMessageHistory. Use ",e.jsx(s,{children:"OctopodaChatHistory"})," instead (shown throughout this guide)."]}),e.jsx("h3",{children:"Context window growing forever"}),e.jsx("p",{children:"By default, every turn is appended. A 100-turn conversation is sent to the LLM in full every invoke. Either:"}),e.jsxs("ul",{children:[e.jsxs("li",{children:["Limit how many messages get injected using LangChain's ",e.jsx(s,{children:"trim_messages"})]}),e.jsxs("li",{children:["Periodically ",e.jsx(s,{children:"history.clear()"})," to reset"]}),e.jsxs("li",{children:["Move older messages to semantic memory (via ",e.jsx(s,{children:"agent.remember"})," from the Vanilla Python SDK) and only keep the last N in chat history"]})]}),e.jsx("h2",{children:"Troubleshooting"}),e.jsx("h3",{children:"AttributeError: 'SynrixMemory' object has no attribute 'messages'"}),e.jsxs("p",{children:["You're using the deprecated ",e.jsx(s,{children:"LangChainMemory"}),". Switch to ",e.jsx(s,{children:"OctopodaChatHistory"}),":"]}),e.jsx(o,{children:`pip install --upgrade octopoda
# Then in your code:
from octopoda import OctopodaChatHistory`}),e.jsx("h3",{children:"openai.AuthenticationError"}),e.jsxs("p",{children:[e.jsx(s,{children:"OPENAI_API_KEY"})," is not set. Run ",e.jsx(s,{children:"echo $OPENAI_API_KEY"})," (or ",e.jsx(s,{children:"$env:OPENAI_API_KEY"})," on Windows). If empty, set it."]}),e.jsx("h3",{children:"Bot seems to have no memory even though writes succeed"}),e.jsxs("p",{children:["Almost always the prompt template is missing ",e.jsx(s,{children:'MessagesPlaceholder("history")'}),", or the name doesn't match ",e.jsx(s,{children:"history_messages_key"}),". See Common mistakes."]}),e.jsx("h3",{children:"Memory works in one terminal but not another"}),e.jsxs("p",{children:["Different ",e.jsx(s,{children:"OCTOPODA_API_KEY"})," (or no key in the second terminal, so it falls to local mode — different data location). Check ",e.jsx(s,{children:"echo $OCTOPODA_API_KEY"})," in both windows."]}),e.jsx("h3",{children:"Invocations get very slow after many turns"}),e.jsx("p",{children:"Context window is growing. See the last Common Mistake for mitigation."}),e.jsx("h3",{children:"AuthError: api_key is required"}),e.jsx("p",{children:"You're on octopoda < 3.1.4 running in local mode. Upgrade:"}),e.jsx(o,{children:"pip install --upgrade octopoda"}),e.jsx("p",{children:"From v3.1.4 onward, no key = local SQLite fallback. No AuthError."}),e.jsx("h2",{children:"Next step"}),e.jsx("p",{children:"If you're using other LangChain patterns (tools, agents, LangGraph), the same OctopodaChatHistory pattern plugs into any chain-like or graph-like runnable. For multi-agent crews, see the CrewAI guide. For raw memory operations outside a chain, see the Vanilla Python guide."}),e.jsx(c,{prev:n,next:i})]})}export{m as default};
