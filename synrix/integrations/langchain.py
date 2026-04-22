"""
Octopoda × LangChain Integration
==================================
Drop-in memory for LangChain agents and chains.
All memory is stored in the Octopoda Cloud API (api.octapodas.com).

Setup:
    pip install octopoda[client] langchain langchain-core
    export OCTOPODA_API_KEY=sk-octopoda-...

Usage with ConversationChain:
    from synrix.integrations.langchain import OctopodaMemory
    from langchain.chains import ConversationChain
    from langchain_openai import ChatOpenAI

    memory = OctopodaMemory(agent_id="support_bot")
    chain = ConversationChain(llm=ChatOpenAI(), memory=memory)
    chain.invoke({"input": "My name is Alice"})
    chain.invoke({"input": "What's my name?"})  # Remembers Alice

Usage with RunnableWithMessageHistory:
    from synrix.integrations.langchain import OctopodaChatHistory

    def get_session_history(session_id):
        return OctopodaChatHistory(agent_id="my_agent", session_id=session_id)

    with_history = RunnableWithMessageHistory(chain, get_session_history)

Usage with AgentExecutor:
    from synrix.integrations.langchain import OctopodaMemory
    memory = OctopodaMemory(agent_id="research_agent")
    agent_executor = AgentExecutor(agent=agent, tools=tools, memory=memory)
"""

from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from synrix.cloud import Octopoda


# ---------------------------------------------------------------------------
# Shared client singleton
# ---------------------------------------------------------------------------

_client: Optional[Octopoda] = None


def _get_client() -> Octopoda:
    global _client
    if _client is None:
        _client = Octopoda()  # reads OCTOPODA_API_KEY from env
    return _client


def _get_agent(agent_id: str):
    client = _get_client()
    return client.agent(agent_id, metadata={"type": "langchain"})


# ---------------------------------------------------------------------------
# LangChain BaseMemory adapter
# ---------------------------------------------------------------------------

try:
    from langchain_core.memory import BaseMemory
    LANGCHAIN_AVAILABLE = True
except ImportError:
    try:
        from langchain.memory.base import BaseMemory
        LANGCHAIN_AVAILABLE = True
    except ImportError:
        BaseMemory = object
        LANGCHAIN_AVAILABLE = False

try:
    from langchain_core.chat_history import BaseChatMessageHistory
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
    CHAT_HISTORY_AVAILABLE = True
except ImportError:
    BaseChatMessageHistory = object
    CHAT_HISTORY_AVAILABLE = False


class OctopodaMemory(BaseMemory):
    """
    Drop-in LangChain memory backed by Octopoda Cloud.

    Persists conversation history across restarts via the cloud API.
    Supports semantic search for relevant context retrieval.
    Works with ConversationChain, AgentExecutor, and any LangChain
    component that accepts a BaseMemory.

    Requires OCTOPODA_API_KEY environment variable.
    Get your free key at https://octopodas.com
    """

    # Pydantic fields (LangChain uses pydantic for BaseMemory)
    agent_id: str = "langchain_agent"
    memory_key: str = "history"
    input_key: str = "input"
    output_key: str = "output"
    human_prefix: str = "Human"
    ai_prefix: str = "AI"
    return_messages: bool = False
    k: int = 50  # Max conversation turns to return

    # Internal
    _agent: Any = None

    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True

    def __init__(self, **kwargs):
        if LANGCHAIN_AVAILABLE:
            super().__init__(**kwargs)
        else:
            # LangChain not installed — set defaults then override with kwargs
            defaults = {
                "agent_id": "langchain_agent", "memory_key": "history",
                "input_key": "input", "output_key": "output",
                "human_prefix": "Human", "ai_prefix": "AI",
                "return_messages": False, "k": 50,
            }
            defaults.update(kwargs)
            for key, value in defaults.items():
                object.__setattr__(self, key, value)
        self._agent = _get_agent(self.agent_id)

    @property
    def memory_variables(self) -> List[str]:
        return [self.memory_key]

    def _get_conversation_key(self) -> str:
        return "conversation_history"

    def load_memory_variables(self, inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        """Load conversation history from Octopoda Cloud."""
        value = self._agent.read(self._get_conversation_key())

        if value is None:
            if self.return_messages:
                return {self.memory_key: []}
            return {self.memory_key: ""}

        history = value
        if isinstance(history, str):
            try:
                history = json.loads(history)
            except (json.JSONDecodeError, TypeError):
                if self.return_messages:
                    return {self.memory_key: []}
                return {self.memory_key: history}

        if not isinstance(history, list):
            if self.return_messages:
                return {self.memory_key: []}
            return {self.memory_key: str(history)}

        # Limit to last k turns
        turns = history[-self.k:] if len(history) > self.k else history

        if self.return_messages:
            messages = []
            for turn in turns:
                if isinstance(turn, dict):
                    if turn.get("role") == "human":
                        messages.append(HumanMessage(content=turn.get("content", "")))
                    elif turn.get("role") == "ai":
                        messages.append(AIMessage(content=turn.get("content", "")))
                    elif turn.get("role") == "system":
                        messages.append(SystemMessage(content=turn.get("content", "")))
            return {self.memory_key: messages}

        # Return as formatted string
        lines = []
        for turn in turns:
            if isinstance(turn, dict):
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                if role == "human":
                    lines.append(f"{self.human_prefix}: {content}")
                elif role == "ai":
                    lines.append(f"{self.ai_prefix}: {content}")
        return {self.memory_key: "\n".join(lines)}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, str]) -> None:
        """Save a conversation turn to Octopoda Cloud."""
        # Load existing history
        value = self._agent.read(self._get_conversation_key())
        history = []
        if value is not None:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    value = []
            if isinstance(value, list):
                history = value

        # Extract input/output
        human_input = inputs.get(self.input_key, "")
        ai_output = outputs.get(self.output_key, "")
        if not ai_output and isinstance(outputs, dict):
            for key in ("output", "text", "response", "answer"):
                if key in outputs:
                    ai_output = outputs[key]
                    break

        # Append new turn
        history.append({"role": "human", "content": str(human_input), "timestamp": time.time()})
        history.append({"role": "ai", "content": str(ai_output), "timestamp": time.time()})

        # Save back
        self._agent.write(self._get_conversation_key(), json.dumps(history))

        # Also store each exchange as a separate searchable memory
        turn_num = len(history) // 2
        self._agent.write(
            f"turn_{turn_num}",
            f"{self.human_prefix}: {human_input}\n{self.ai_prefix}: {ai_output}",
        )

    def clear(self) -> None:
        """Clear conversation history."""
        self._agent.write(self._get_conversation_key(), json.dumps([]))

    # ----- Bonus: semantic recall for RAG-style memory -----

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Search past conversations by meaning (semantic search).

        Usage:
            results = memory.search("What did the user say about pricing?")
            for r in results:
                print(r["value"], r["score"])
        """
        return self._agent.search(query, limit=limit)


# ---------------------------------------------------------------------------
# LangChain ChatMessageHistory adapter
# ---------------------------------------------------------------------------

class OctopodaChatHistory(BaseChatMessageHistory):
    """
    Octopoda Cloud-backed ChatMessageHistory for RunnableWithMessageHistory.

    Usage:
        from synrix.integrations.langchain import OctopodaChatHistory

        def get_session_history(session_id: str):
            return OctopodaChatHistory(agent_id="my_agent", session_id=session_id)

        chain_with_history = RunnableWithMessageHistory(
            runnable, get_session_history
        )
    """

    def __init__(self, agent_id: str = "langchain_agent", session_id: str = "default"):
        self.agent_id = agent_id
        self.session_id = session_id
        # v3.1.4: if cloud fails (no key / offline), fall back to local AgentRuntime.
        # Previously raised AuthError and broke every local LangChain user.
        self._local_rt = None
        try:
            self._agent = _get_agent(agent_id)
        except Exception as cloud_err:
            try:
                from synrix_runtime.api.runtime import AgentRuntime as _AR
                self._local_rt = _AR(agent_id)
                self._agent = None
            except Exception as local_err:
                raise RuntimeError(
                    f"OctopodaChatHistory failed both cloud (err: {cloud_err}) "
                    f"and local (err: {local_err}). Set OCTOPODA_API_KEY or install synrix_runtime."
                )

    @property
    def messages(self) -> List[BaseMessage]:
        """Retrieve all messages from Octopoda Cloud (or local fallback)."""
        if not CHAT_HISTORY_AVAILABLE:
            return []

        key = f"chat_history:{self.session_id}"
        # v3.1.4: local fallback path
        if self._local_rt is not None:
            r = self._local_rt.recall(key)
            data = r.value if r.found else None
        else:
            data = self._agent.read(key)

        if data is None:
            return []

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return []

        if not isinstance(data, list):
            return []

        messages = []
        for msg in data:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                role = msg.get("role", "human")
                if role == "human":
                    messages.append(HumanMessage(content=content))
                elif role == "ai":
                    messages.append(AIMessage(content=content))
                elif role == "system":
                    messages.append(SystemMessage(content=content))
        return messages

    def add_message(self, message: BaseMessage) -> None:
        """Add a message to the history."""
        key = f"chat_history:{self.session_id}"
        if self._local_rt is not None:
            r = self._local_rt.recall(key)
            data = r.value if r.found else None
        else:
            data = self._agent.read(key)

        history = []
        if data is not None:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    data = []
            if isinstance(data, list):
                history = data

        role = "human"
        if isinstance(message, AIMessage):
            role = "ai"
        elif isinstance(message, SystemMessage):
            role = "system"

        history.append({
            "role": role,
            "content": message.content,
            "timestamp": time.time(),
        })

        # v3.1.4: local fallback path
        if self._local_rt is not None:
            self._local_rt.remember(key, json.dumps(history))
        else:
            self._agent.write(key, json.dumps(history))

    def clear(self) -> None:
        """Clear all messages."""
        key = f"chat_history:{self.session_id}"
        self._agent.write(key, json.dumps([]))
