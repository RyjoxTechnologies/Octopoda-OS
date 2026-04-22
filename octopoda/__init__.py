"""
Octopoda -- Persistent Memory Kernel for AI Agents
====================================================
Install: pip install octopoda

Quick start:
    from octopoda import AgentRuntime
    agent = AgentRuntime("my_agent")
    agent.remember("key", {"data": "value"})
    result = agent.recall("key")
"""

__version__ = "3.1.3"

# Cloud SDK (the main developer-facing API)
from synrix.cloud import Octopoda, Agent, OctopodaError, AuthError, RateLimitError

# Core SDK (low-level)
from synrix import (
    SynrixAgentBackend,
    get_synrix_backend,
    SynrixError,
    SynrixConnectionError,
    SynrixNotFoundError,
)

try:
    from synrix import Memory
except ImportError:
    Memory = None

# Runtime (high-level developer API)
from synrix_runtime.api.runtime import AgentRuntime
from synrix_runtime.config import SynrixConfig

# Framework integrations — simple one-line wrappers
# Usage: from octopoda import LangChainMemory
#        memory = LangChainMemory("my_agent")

def _get_backend_auto():
    """Auto-detect backend: cloud if API key set, local otherwise."""
    import os
    if os.environ.get("OCTOPODA_API_KEY", "").startswith("sk-octopoda-"):
        return None  # Let integration use cloud
    # Local mode: create a local backend
    from synrix_runtime.api.runtime import AgentRuntime
    _rt = AgentRuntime("_integrations", require_account=False)
    return _rt.backend


class LangChainMemory:
    """One-line LangChain integration. Works locally or cloud automatically.

    Usage:
        from octopoda import LangChainMemory
        memory = LangChainMemory("my_agent")
        chain = ConversationChain(llm=llm, memory=memory)
    """
    def __new__(cls, agent_id="langchain_default", **kwargs):
        from synrix_runtime.integrations.langchain_memory import SynrixMemory
        if "backend" not in kwargs:
            kwargs["backend"] = _get_backend_auto()
        return SynrixMemory(agent_id=agent_id, **kwargs)


class CrewAIMemory:
    """One-line CrewAI integration. Works locally or cloud automatically.

    Usage:
        from octopoda import CrewAIMemory
        crew = CrewAIMemory("my_crew")
        crew.store_finding("researcher", "key", "value")
    """
    def __new__(cls, crew_id="default_crew", **kwargs):
        from synrix_runtime.integrations.crewai_memory import SynrixCrewMemory
        if "backend" not in kwargs:
            kwargs["backend"] = _get_backend_auto()
        return SynrixCrewMemory(crew_id=crew_id, **kwargs)


class AutoGenMemory:
    """One-line AutoGen integration. Works locally or cloud automatically.

    Usage:
        from octopoda import AutoGenMemory
        memory = AutoGenMemory("my_group")
        memory.store_message(sender="user", recipient="bot", content="hello")
    """
    def __new__(cls, group_id="default", **kwargs):
        from synrix_runtime.integrations.autogen_memory import SynrixAutoGenMemory
        if "backend" not in kwargs:
            kwargs["backend"] = _get_backend_auto()
        return SynrixAutoGenMemory(group_id=group_id, **kwargs)


class OpenAIAgentsMemory:
    """One-line OpenAI Agents SDK integration. Works locally or cloud automatically.

    Usage:
        from octopoda import OpenAIAgentsMemory
        memory = OpenAIAgentsMemory()
        memory.store_thread_state("thread_123", {"messages": [...]})
    """
    def __new__(cls, **kwargs):
        from synrix_runtime.integrations.openai_agents import SynrixOpenAIMemory
        if "backend" not in kwargs:
            kwargs["backend"] = _get_backend_auto()
        return SynrixOpenAIMemory(**kwargs)


__all__ = [
    # Core
    "Octopoda",
    "Agent",
    "AgentRuntime",
    # Framework integrations (simple)
    "LangChainMemory",
    "CrewAIMemory",
    "AutoGenMemory",
    "OpenAIAgentsMemory",
    # Config
    "SynrixConfig",
    # Errors
    "OctopodaError",
    "AuthError",
    "RateLimitError",
    "SynrixError",
    "SynrixConnectionError",
    "SynrixNotFoundError",
    # Low-level
    "get_synrix_backend",
    "SynrixAgentBackend",
    "Memory",
]
