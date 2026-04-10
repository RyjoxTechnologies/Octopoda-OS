Title: I built a memory system for AI agents that runs 100% locally with Ollama

Body:

Hey everyone. Been lurking here for a while and finally have something worth sharing.

I built Octopoda, an open source memory engine for AI agents. The whole thing runs locally on your machine with SQLite and Ollama. No cloud, no API keys, no data leaving your box.

The basic idea is that agents forget everything between runs. You close the script, context is gone. Octopoda gives them persistent memory that survives restarts, crashes, whatever. You just do agent.remember("key", "value") and agent.recall("key") and it handles the rest.

But the part I think this sub would care about is the Ollama integration. When you store a memory, Octopoda can use your local model (I use llama3.2) to extract structured facts and tag them semantically. So if you store "Alice is a vegetarian who lives in London", it breaks that into searchable facts. Then when you ask "what does Alice eat?" the semantic search actually finds the right memory even though the words dont match.

Without Ollama it still works fine, you just get exact key matching and embedding based search (using bge-small-en locally, no OpenAI). With Ollama you get the fact extraction layer on top which bumped our recall accuracy from 0.60 to 0.81 in testing.

It also does loop detection which catches when your agent is stuck repeating itself (writing the same thing over and over), crash recovery, audit trails, and theres a local dashboard you can open in the browser to watch everything in real time.

Quick start is literally:

pip install octopoda

```python
from octopoda import AgentRuntime

agent = AgentRuntime("my_agent")
agent.remember("user_pref", "prefers dark mode")
agent.recall("user_pref")
```

That runs on SQLite locally. If you want the Ollama fact extraction:

```
export OCTOPODA_OLLAMA_URL=http://localhost:11434
export OCTOPODA_OLLAMA_MODEL=llama3.2
```

And for the dashboard: pip install octopoda[server] then just run octopoda and open localhost:7842.

Works with LangChain, CrewAI, AutoGen, and OpenAI Agents SDK too if you use any of those.

Few questions for you lot:

1. What local models are you using for agent memory and fact extraction? I went with llama3.2 because its fast but wondering if there are better options for structured extraction specifically.

2. Anyone else running into the problem where agents just loop endlessly? Like they store the same preference 50 times or keep flip flopping on a decision. Curious how you handle that without something watching for it.

3. For those of you building multi agent systems locally, how do you handle shared memory between agents? Thats been one of the trickier problems to solve cleanly.

GitHub: https://github.com/RyjoxTechnologies/Octopoda-OS
PyPI: pip install octopoda
MIT licensed, whole thing is free.

Would love feedback, especially from people actually running local agents day to day. What am I missing? What would make this actually useful for your setup?
