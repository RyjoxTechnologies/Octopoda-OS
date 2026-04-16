"""
Octopoda × LangChain Integration (Runtime)
============================================
Drop-in replacement for LangChain memory modules.
All memory is stored in the Octopoda Cloud API (api.octopodas.com).

Setup:
    pip install octopoda[client] langchain
    export OCTOPODA_API_KEY=sk-octopoda-...

Usage:
    from synrix_runtime.integrations.langchain_memory import SynrixMemory
    memory = SynrixMemory(agent_id="my_chain")
    chain = ConversationChain(llm=llm, memory=memory)

For the full LangChain integration (BaseMemory, ChatMessageHistory), use:
    from synrix.integrations.langchain import OctopodaMemory, OctopodaChatHistory
"""

import time
import json
from typing import Dict, List, Any, Optional

from synrix.cloud import Octopoda

try:
    from langchain.memory import BaseMemory
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    class BaseMemory:
        """Stub when LangChain not installed."""
        memory_variables = []
        def save_context(self, inputs, outputs): pass
        def load_memory_variables(self, inputs): return {}
        def clear(self): pass


_client: Optional[Octopoda] = None


def _get_client() -> Octopoda:
    global _client
    if _client is None:
        _client = Octopoda()
    return _client


class SynrixMemory(BaseMemory):
    """
    Drop-in replacement for LangChain memory backed by Octopoda Cloud.

    Usage:
        from synrix_runtime.integrations.langchain_memory import SynrixMemory
        memory = SynrixMemory(agent_id="my_chain")
        # Use with LangChain: ConversationChain(llm=llm, memory=memory)

    Requires OCTOPODA_API_KEY environment variable.
    Get your free key at https://octopodas.com
    """

    def __init__(self, agent_id: str = "langchain_default", memory_key: str = "history",
                 session_id: Optional[str] = None, return_messages: bool = False,
                 backend=None, **kwargs):
        self.agent_id = agent_id
        self.memory_key = memory_key
        self.session_id = session_id
        self.return_messages = return_messages
        self._memory_variables = [memory_key]
        self._message_count = 0

        if backend is not None:
            from synrix_runtime.integrations._local_adapter import _LocalAgentAdapter
            self._agent = _LocalAgentAdapter(backend, agent_id)
            self.backend = backend
        else:
            client = _get_client()
            self._agent = client.agent(agent_id, metadata={"type": "langchain"})
            self.backend = None

    def _messages_prefix(self) -> str:
        """Key prefix for this session's messages. Isolates sessions when session_id is set."""
        if self.session_id:
            return f"langchain:{self.agent_id}:sessions:{self.session_id}:messages:"
        return f"langchain:{self.agent_id}:messages:"

    @property
    def memory_variables(self) -> List[str]:
        return self._memory_variables

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, str]) -> None:
        """Save conversation turn to Octopoda Cloud."""
        self._message_count += 1

        entry = {
            "inputs": inputs,
            "outputs": outputs,
            "turn": self._message_count,
            "timestamp": time.time(),
        }

        self._agent.write(
            f"{self._messages_prefix()}{int(time.time() * 1000000)}",
            entry,
            tags=["langchain_message", self.agent_id],
        )

        # Update summary
        self._agent.write(
            f"langchain:{self.agent_id}:summary",
            {"total_turns": self._message_count, "last_updated": time.time()},
        )

    def load_memory_variables(self, inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        """Load conversation history from Octopoda Cloud.

        If return_messages=True was passed at construction, returns a list of
        LangChain message objects (HumanMessage/AIMessage) suitable for chat models.
        Otherwise returns a concatenated string.
        """
        results = self._agent.keys(prefix=self._messages_prefix(), limit=100)

        messages = []
        for r in results:
            val = r.get("value", r)
            if isinstance(val, dict):
                messages.append(val)

        messages.sort(key=lambda x: x.get("turn", 0))

        if self.return_messages:
            try:
                from langchain_core.messages import HumanMessage, AIMessage
                msg_objects = []
                for msg in messages:
                    inp = msg.get("inputs", {})
                    out = msg.get("outputs", {})
                    human_input = inp.get("input", inp.get("human_input", str(inp)))
                    ai_output = out.get("output", out.get("response", str(out)))
                    msg_objects.append(HumanMessage(content=human_input))
                    msg_objects.append(AIMessage(content=ai_output))
                return {self.memory_key: msg_objects}
            except ImportError:
                pass  # langchain_core not installed — fall through to string format

        history_parts = []
        for msg in messages:
            inp = msg.get("inputs", {})
            out = msg.get("outputs", {})
            human_input = inp.get("input", inp.get("human_input", str(inp)))
            ai_output = out.get("output", out.get("response", str(out)))
            history_parts.append(f"Human: {human_input}")
            history_parts.append(f"AI: {ai_output}")

        return {self.memory_key: "\n".join(history_parts)}

    def clear(self) -> None:
        """Clear is a no-op — Octopoda preserves all history."""
        pass

    def get_full_history(self) -> List[dict]:
        """Get complete conversation history (scoped to the current session_id if set)."""
        results = self._agent.keys(prefix=self._messages_prefix(), limit=500)
        messages = []
        for r in results:
            val = r.get("value", r)
            if isinstance(val, dict):
                messages.append(val)
        messages.sort(key=lambda x: x.get("turn", 0))
        return messages

    def store_entity(self, name: str, data: dict):
        """Store entity information (e.g. a person, place, concept)."""
        payload = data.copy() if isinstance(data, dict) else {"value": data}
        payload["_stored_at"] = time.time()
        self._agent.write(f"langchain:{self.agent_id}:entities:{name}", payload,
                          tags=["entity", name])

    def get_entity(self, name: str) -> Optional[dict]:
        """Get stored entity information."""
        return self._agent.read(f"langchain:{self.agent_id}:entities:{name}")

    def restore_from_crash(self) -> int:
        """Restore message count from stored history after a crash."""
        messages = self.get_full_history()
        self._message_count = len(messages)
        return self._message_count

    def export_conversation(self) -> dict:
        """Export full conversation with metadata."""
        messages = self.get_full_history()
        return {
            "agent_id": self.agent_id,
            "total_turns": len(messages),
            "messages": messages,
            "exported_at": time.time(),
        }
