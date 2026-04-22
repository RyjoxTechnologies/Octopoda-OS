"""
Octopoda MCP Server
====================
Model Context Protocol server that exposes Octopoda cloud memory as tools.
Any MCP-compatible AI (Claude, Cursor, ChatGPT, VS Code, etc.) can use this.

All memory operations go through the Octopoda Cloud API (api.octopodas.com).
Requires OCTOPODA_API_KEY — get your free key at https://octopodas.com

Setup (Claude Desktop):
    Add to claude_desktop_config.json:
    {
        "mcpServers": {
            "octopoda": {
                "command": "octopoda-mcp",
                "env": {
                    "OCTOPODA_API_KEY": "sk-octopoda-YOUR_KEY"
                }
            }
        }
    }

Run standalone:
    OCTOPODA_API_KEY=sk-octopoda-... octopoda-mcp
    OCTOPODA_API_KEY=sk-octopoda-... python -m synrix_runtime.api.mcp_server
"""
import logging

logger = logging.getLogger(__name__)


import os
import json
import time
from collections import OrderedDict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Octopoda Memory")

# -----------------------------------------------------------------------
# Cloud client cache (LRU, max 100 agents)
# -----------------------------------------------------------------------

_client = None
_agents: OrderedDict = OrderedDict()
_MAX_AGENTS = 100


_local_mode = False
_runtimes: OrderedDict = OrderedDict()


class _FastClient:
    """Lightweight cloud client using only requests. No synrix imports.
    This avoids loading numpy/torch/sentence-transformers (~8s) on startup."""

    def __init__(self, api_key, base_url="https://api.octopodas.com"):
        import requests as _req
        self._s = _req.Session()
        self._s.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        self._base = base_url.rstrip("/")

    def _raise_for_api_error(self, r):
        """Raise a descriptive error surfacing the server's message (e.g. agent limit, auth, rate limit)."""
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = (r.text or "")[:300]
        raise RuntimeError(f"Octopoda API {r.status_code}: {detail or 'request failed'}")

    def _post(self, path, data):
        r = self._s.post(f"{self._base}{path}", json=data, timeout=10)
        if r.status_code not in (200, 201):
            self._raise_for_api_error(r)
        return r.json()

    def _get(self, path, params=None):
        r = self._s.get(f"{self._base}{path}", params=params, timeout=10)
        if r.status_code != 200:
            self._raise_for_api_error(r)
        return r.json()

    def agent(self, agent_id, metadata=None):
        self._post("/v1/agents", {"agent_id": agent_id, **({"metadata": metadata} if metadata else {})})
        return _FastAgent(self, agent_id)

    def agents(self):
        return [a.get("agent_id", "") for a in self._get("/v1/agents").get("agents", [])]

    def read_shared(self, space, key):
        r = self._get(f"/v1/shared/{space}/{key}")
        if r.get("found"):
            v = r.get("value")
            return v.get("value", v) if isinstance(v, dict) and "value" in v else v
        return None


class _FastAgent:
    """Lightweight agent handle using only HTTP."""

    def __init__(self, client, agent_id):
        self._c = client
        self.agent_id = agent_id
        self._base = f"/v1/agents/{agent_id}"

    def write(self, key, value, tags=None):
        d = {"key": key, "value": value}
        if tags: d["tags"] = tags
        return self._c._post(f"{self._base}/remember", d)

    def read(self, key):
        r = self._c._get(f"{self._base}/recall/{key}")
        return r.get("value") if r.get("found") else None

    def keys(self, prefix="", limit=100):
        return self._c._get(f"{self._base}/search", {"prefix": prefix, "limit": limit}).get("items", [])

    def search(self, query, limit=10):
        return self._c._get(f"{self._base}/similar", {"q": query, "limit": limit}).get("items", [])

    def history(self, key):
        return self._c._get(f"{self._base}/history/{key}").get("versions", [])

    def related(self, entity):
        return self._c._get(f"{self._base}/related/{entity}").get("relationships", [])

    def snapshot(self, label=None):
        return self._c._post(f"{self._base}/snapshot", {"label": label})

    def restore(self, label=None):
        return self._c._post(f"{self._base}/restore", {"label": label})

    def write_batch(self, items):
        return self._c._post(f"{self._base}/remember/batch", {"items": items})

    def metrics(self):
        return self._c._get(self._base)

    def share(self, space, key, value):
        return self._c._post(f"/v1/shared/{space}", {"key": key, "value": value, "author_agent_id": self.agent_id})

    def decide(self, decision, reasoning, context=None):
        return self._c._post(f"{self._base}/decision", {"decision": decision, "reasoning": reasoning, "context": context or {}})

    def get_loop_status(self):
        return self._c._get(f"{self._base}/loops/status")

    def get_loop_history(self, hours=24):
        return self._c._get(f"{self._base}/loops/history", {"hours": hours})

    def send_message(self, to_agent, message, msg_type="info"):
        return self._c._post(f"{self._base}/messages/send", {"to_agent": to_agent, "message": message, "message_type": msg_type})

    def read_messages(self, unread_only=False):
        return self._c._get(f"{self._base}/messages/inbox", {"unread_only": unread_only}).get("messages", [])

    def broadcast(self, message, msg_type="info"):
        return self._c._post(f"{self._base}/messages/broadcast", {"message": message, "message_type": msg_type})

    def set_goal(self, goal, milestones=None):
        return self._c._post(f"{self._base}/goals", {"goal": goal, "milestones": milestones or []})

    def get_goal(self):
        return self._c._get(f"{self._base}/goals")

    def update_progress(self, progress=None, milestone_index=None, note=None):
        d = {}
        if progress is not None: d["progress"] = progress
        if milestone_index is not None: d["milestone_index"] = milestone_index
        if note: d["note"] = note
        return self._c._post(f"{self._base}/goals/progress", d)

    def forget(self, key):
        return self._c._post(f"{self._base}/forget", {"key": key})

    def forget_stale(self, max_age_seconds):
        return self._c._post(f"{self._base}/forget/stale", {"max_age_seconds": max_age_seconds})

    def memory_health(self):
        return self._c._get(f"{self._base}/health")

    def consolidate(self, dry_run=True):
        return self._c._post(f"{self._base}/consolidate", {"dry_run": dry_run})

    def search_filtered(self, query=None, tags=None, importance=None, max_age_seconds=None):
        params = {}
        if query: params["q"] = query
        if tags: params["tags"] = ",".join(tags)
        if importance: params["importance"] = importance
        if max_age_seconds: params["max_age_seconds"] = max_age_seconds
        return self._c._get(f"{self._base}/search/filtered", params).get("items", [])

    def process_conversation(self, messages, **kwargs):
        return self._c._post(f"{self._base}/process", {"messages": messages, **kwargs})

    def get_context(self, query, limit=10, format="text"):
        return self._c._get(f"{self._base}/context", {"q": query, "limit": limit, "format": format})


def _get_client():
    """Get or create the Octopoda client (singleton).
    Uses lightweight HTTP client — no heavy synrix imports."""
    global _client, _local_mode
    if _client is not None:
        return _client

    api_key = os.environ.get("OCTOPODA_API_KEY", "")
    if api_key and api_key != "YOUR_KEY_HERE":
        _client = _FastClient(api_key)
        _local_mode = False
    else:
        _client = _LocalClientAdapter()
        _local_mode = True
    return _client


class _LocalAgentAdapter:
    """Wraps AgentRuntime to match the cloud Agent interface used by MCP tools."""

    def __init__(self, runtime):
        self._rt = runtime
        self.agent_id = runtime.agent_id

    def _to_dict(self, obj):
        """Convert dataclass results to dicts."""
        if obj is None:
            return None
        if hasattr(obj, '__dataclass_fields__'):
            return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
        return obj

    def write(self, key, value, tags=None):
        result = self._rt.remember(key, value, tags=tags)
        return self._to_dict(result)

    def read(self, key):
        result = self._rt.recall(key)
        if result is None:
            return None
        d = self._to_dict(result)
        if isinstance(d, dict) and d.get("found") is False:
            return None
        if isinstance(d, dict):
            return d.get("value", d)
        return result

    def keys(self, prefix="", limit=100):
        results = self._rt.search(prefix, limit=limit)
        if hasattr(results, 'items'):
            return [self._to_dict(r) if hasattr(r, '__dataclass_fields__') else r for r in results.items]
        if isinstance(results, list):
            return results
        return []

    def search(self, query, limit=10):
        results = self._rt.search(query, limit=limit)
        if hasattr(results, 'items'):
            return results.items
        return results if isinstance(results, list) else []

    def write_batch(self, items):
        return self._rt.remember_many(items)

    def snapshot(self, label=None):
        result = self._rt.snapshot(label=label)
        return self._to_dict(result)

    def restore(self, label=None):
        result = self._rt.restore(label=label)
        return self._to_dict(result)

    def share(self, space, key, value):
        result = self._rt.share(key, value, space=space)
        return self._to_dict(result)

    def decide(self, decision, reasoning, context=None):
        result = self._rt.log_decision(decision, reasoning, context=context)
        return self._to_dict(result) or {"decision": decision, "logged": True}

    def metrics(self):
        stats = self._rt.get_stats()
        return self._to_dict(stats) or {}

    def history(self, key):
        return self._rt.recall_history(key)

    def delete(self):
        self._rt.shutdown()


class _LocalClientAdapter:
    """Wraps local runtime access to match the cloud Octopoda client interface."""

    def read_shared(self, space, key):
        """Read shared memory in local mode using an existing agent's backend."""
        if not _runtimes:
            return None
        adapter = next(iter(_runtimes.values()))
        full_key = f"shared:{space}:{key}"
        result = adapter._rt.backend.read(full_key)
        if result is None:
            return None
        # Navigate: result -> data -> value -> actual content
        data = result.get("data", result) if isinstance(result, dict) else result
        val = data.get("value", data) if isinstance(data, dict) else data
        if isinstance(val, dict):
            return {k: v for k, v in val.items() if not k.startswith("_")}
        return val

    def agents(self):
        """List agents in local mode."""
        return list(_runtimes.keys())


def _get_runtime(agent_id: str):
    """Get or create a local AgentRuntime (wrapped) for the given agent_id."""
    if agent_id in _runtimes:
        _runtimes.move_to_end(agent_id)
        return _runtimes[agent_id]

    while len(_runtimes) >= _MAX_AGENTS:
        _runtimes.popitem(last=False)

    from synrix_runtime.api.runtime import AgentRuntime
    runtime = AgentRuntime(agent_id, agent_type="mcp")
    adapter = _LocalAgentAdapter(runtime)
    _runtimes[agent_id] = adapter
    return adapter


def _get_agent(agent_id: str):
    """Get or create an Agent handle for the given agent_id.
    Uses cloud client if API key is set, otherwise local runtime."""
    _get_client()  # ensure client/mode is initialized

    if _local_mode:
        return _get_runtime(agent_id)

    if agent_id in _agents:
        _agents.move_to_end(agent_id)
        return _agents[agent_id]

    while len(_agents) >= _MAX_AGENTS:
        _agents.popitem(last=False)

    agent = _client.agent(agent_id, metadata={"type": "mcp"})
    _agents[agent_id] = agent
    return agent


def _parse_value(value: str):
    """Parse a value string as JSON if possible, otherwise return as-is."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {"value": value}


def _timed(fn):
    """Call fn, return (result, latency_us)."""
    t0 = time.perf_counter()
    result = fn()
    latency = (time.perf_counter() - t0) * 1_000_000
    return result, round(latency, 1)


# -----------------------------------------------------------------------
# Memory Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_remember(agent_id: str, key: str, value: str, tags: list[str] | None = None) -> dict:
    """Store a persistent memory for an AI agent. Memory is stored in the cloud and persists across sessions.

    Args:
        agent_id: Unique identifier for the agent (e.g. "research_bot", "code_assistant")
        key: Memory key (e.g. "user_preference", "task:current")
        value: Data to store (JSON string or plain text)
        tags: Optional list of tags for categorization
    """
    agent = _get_agent(agent_id)
    parsed = _parse_value(value)
    result, latency = _timed(lambda: agent.write(key, parsed, tags=tags))
    return {
        "success": True,
        "key": key,
        "agent_id": agent_id,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_recall(agent_id: str, key: str) -> dict:
    """Retrieve a stored memory by key.

    Args:
        agent_id: The agent whose memory to read
        key: The memory key to retrieve
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.read(key))
    return {
        "found": result is not None,
        "key": key,
        "value": result,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_search(agent_id: str, prefix: str, limit: int = 20) -> dict:
    """Search an agent's memories by key prefix.

    Args:
        agent_id: The agent whose memories to search
        prefix: Key prefix to search for (e.g. "task:" finds "task:current", "task:history")
        limit: Maximum number of results (default 20)
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.keys(prefix=prefix, limit=limit))
    return {
        "count": len(result),
        "items": result,
        "latency_us": latency,
    }


# -----------------------------------------------------------------------
# Semantic Search & Temporal Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_recall_similar(agent_id: str, query: str, limit: int = 10) -> dict:
    """Search an agent's memories by meaning (semantic similarity).
    Finds memories related to the query even if the exact words don't match.

    Args:
        agent_id: The agent whose memories to search
        query: Natural language query (e.g. "what food does the user like?")
        limit: Maximum number of results (default 10)
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.search(query, limit=limit))
    return {
        "count": len(result),
        "items": result,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_recall_history(agent_id: str, key: str) -> dict:
    """Get the full timeline of how a memory changed over time.
    Shows all versions with timestamps for when each was valid.

    Args:
        agent_id: The agent whose memory to inspect
        key: The memory key to get history for
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.history(key))
    return {
        "key": key,
        "versions": result,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_related(agent_id: str, entity: str) -> dict:
    """Query the knowledge graph for an entity and its connections.
    Shows what other entities are related and how.

    Args:
        agent_id: The agent whose knowledge graph to query
        entity: Entity name to look up (e.g. "London", "Alice")
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.related(entity))
    return {
        "entity": entity,
        "relationships": result,
        "latency_us": latency,
    }


# -----------------------------------------------------------------------
# Snapshot Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_snapshot(agent_id: str, label: str | None = None) -> dict:
    """Take a snapshot (checkpoint) of all agent memory. Use before risky operations.

    Args:
        agent_id: The agent whose memory to snapshot
        label: Optional label for the snapshot (auto-generated if omitted)
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.snapshot(label))
    return {
        "label": result.get("label", label),
        "keys_captured": result.get("keys_captured", 0),
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_restore(agent_id: str, label: str | None = None) -> dict:
    """Restore agent memory from a snapshot. Reverts to the saved state.

    Args:
        agent_id: The agent whose memory to restore
        label: Snapshot label to restore from (latest if omitted)
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.restore(label or "latest"))
    return {
        "label": label,
        "keys_restored": result.get("keys_restored", 0),
        "latency_us": latency,
    }


# -----------------------------------------------------------------------
# Shared Memory Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_share(agent_id: str, key: str, value: str, space: str = "global") -> dict:
    """Write to shared memory that other agents can read.

    Args:
        agent_id: The agent writing the data
        key: Shared memory key
        value: Data to share (JSON string or plain text)
        space: Memory space name (default "global")
    """
    agent = _get_agent(agent_id)
    parsed = _parse_value(value)
    result, latency = _timed(lambda: agent.share(space, key, parsed))
    return {
        "success": True,
        "key": key,
        "space": space,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_read_shared(agent_id: str, key: str, space: str = "global") -> dict:
    """Read from shared memory written by any agent.

    Args:
        agent_id: The agent reading the data
        key: Shared memory key to read
        space: Memory space name (default "global")
    """
    client = _get_client()
    result, latency = _timed(lambda: client.read_shared(space, key))
    return {
        "found": result is not None and "error" not in (result or {}),
        "key": key,
        "space": space,
        "value": result,
        "latency_us": latency,
    }


# -----------------------------------------------------------------------
# Agent Management Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_list_agents() -> dict:
    """List all registered agents in your Octopoda account."""
    client = _get_client()
    result, latency = _timed(lambda: client.agents())
    return {
        "count": len(result),
        "agents": result,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_agent_stats(agent_id: str) -> dict:
    """Get performance statistics and analytics for an agent.

    Args:
        agent_id: The agent to get stats for
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.metrics())
    base = {
        "agent_id": agent_id,
        "latency_us": latency,
    }
    if isinstance(result, dict):
        base.update(result)
    else:
        base["metrics"] = result
    return base


# -----------------------------------------------------------------------
# Conversation Processing Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_process_conversation(agent_id: str, user_message: str, assistant_response: str) -> dict:
    """Process a conversation turn — automatically extracts and stores memories.
    Call this after your agent responds to learn from the conversation.

    Args:
        agent_id: The agent to store memories for
        user_message: What the user said
        assistant_response: What the assistant replied
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.process_conversation(
        messages=[
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_response},
        ],
        extract_preferences=True,
        extract_facts=True,
        extract_decisions=True,
        namespace="conversations",
    ))
    return {
        "agent_id": agent_id,
        "processed": True,
        "details": result,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_get_context(agent_id: str, query: str, limit: int = 10) -> dict:
    """Get relevant context from memory before generating a response.
    Returns memories related to the query, ready to inject into your prompt.

    Args:
        agent_id: The agent whose memories to search
        query: The current user message or topic
        limit: Max memories to retrieve (default 10)
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.get_context(query, limit=limit, format="text"))
    return {
        "context": result.get("context", ""),
        "latency_us": latency,
    }


# -----------------------------------------------------------------------
# Audit Tool
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_log_decision(
    agent_id: str, decision: str, reasoning: str, context: str | None = None
) -> dict:
    """Log an agent decision with full audit trail.

    Args:
        agent_id: The agent making the decision
        decision: What was decided ("allow", "deny", or "escalate")
        reasoning: Why this decision was made
        context: Optional JSON string with additional context
    """
    agent = _get_agent(agent_id)
    ctx = _parse_value(context) if context else {}
    result, latency = _timed(lambda: agent.decide(decision, reasoning, ctx))
    return {
        "agent_id": agent_id,
        "logged": True,
        "decision": decision,
        "latency_us": latency,
    }


# -----------------------------------------------------------------------
# Memory Management Tools (Forget / Consolidate / Health)
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_forget(agent_id: str, key: str) -> dict:
    """Explicitly forget (delete) a specific memory. Use when a memory is
    no longer relevant or correct.

    Args:
        agent_id: The agent whose memory to forget
        key: The memory key to delete
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.forget(key))
    return {
        "agent_id": agent_id,
        "key": key,
        "deleted": result.get("deleted", False),
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_forget_stale(agent_id: str, max_age_days: int = 7) -> dict:
    """Forget old memories to keep the agent's knowledge fresh.
    Critical memories are always preserved regardless of age.

    Args:
        agent_id: The agent to clean up
        max_age_days: Delete memories older than this many days (default 7)
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.forget_stale(max_age_days * 86400))
    return {
        "agent_id": agent_id,
        "deleted": result.get("deleted", 0),
        "preserved_critical": result.get("preserved_critical", 0),
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_memory_health(agent_id: str) -> dict:
    """Check the health of an agent's memory. Returns a score from 0-100
    with actionable recommendations for improving retrieval quality.

    Args:
        agent_id: The agent to check
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.memory_health())
    return {
        "agent_id": agent_id,
        "health": result,
        "latency_us": latency,
    }


@mcp.tool()
def octopoda_consolidate(agent_id: str, dry_run: bool = True) -> dict:
    """Find and optionally merge duplicate memories. Duplicates degrade
    retrieval quality because similar but stale memories surface alongside
    current ones.

    Args:
        agent_id: The agent whose memories to consolidate
        dry_run: If true (default), reports duplicates without deleting them
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.consolidate(dry_run=dry_run))
    return {
        "agent_id": agent_id,
        "consolidation": result,
        "latency_us": latency,
    }


# -----------------------------------------------------------------------
# Advanced Loop Detection v2 Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_loop_status(agent_id: str) -> dict:
    """Get comprehensive loop detection status for an agent. Combines 5
    signals: write similarity, key overwrites, velocity spikes, alert
    frequency, and goal drift. Returns severity (green/yellow/orange/red)
    with actionable recovery suggestions.

    Use this when you suspect an agent is stuck, looping, or behaving
    abnormally. The severity score tells you how urgently to intervene.

    Args:
        agent_id: The agent to check for loops
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.get_loop_status())
    return {"agent_id": agent_id, "loop_status": result, "latency_us": latency}


@mcp.tool()
def octopoda_loop_history(agent_id: str, hours: int = 24) -> dict:
    """Get loop detection alert history for pattern analysis. Shows how
    loop behavior has evolved over time, broken down by hour and type.
    Automatically detects recurring patterns.

    Args:
        agent_id: The agent to analyze
        hours: How many hours of history to analyze (default 24, max 168)
    """
    agent = _get_agent(agent_id)
    hours = min(max(1, hours), 168)
    result, latency = _timed(lambda: agent.get_loop_history(hours))
    return {"agent_id": agent_id, "history": result, "latency_us": latency}


# -----------------------------------------------------------------------
# Agent Messaging Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_send_message(agent_id: str, to_agent: str, message: str,
                          message_type: str = "info") -> dict:
    """Send a message from one agent to another. Creates an inbox/outbox
    system for asynchronous agent-to-agent communication.

    Args:
        agent_id: The sending agent
        to_agent: The receiving agent ID
        message: Message content (plain text or JSON string)
        message_type: "info", "request", "response", or "alert"
    """
    agent = _get_agent(agent_id)
    parsed = _parse_value(message)
    result, latency = _timed(lambda: agent.send_message(to_agent, parsed, message_type))
    return {"sent": True, "to": to_agent, "msg_id": result.get("msg_id"), "latency_us": latency}


@mcp.tool()
def octopoda_read_messages(agent_id: str, unread_only: bool = False) -> dict:
    """Read messages from an agent's inbox.

    Args:
        agent_id: The agent whose inbox to read
        unread_only: If true, only return unread messages
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.read_messages(unread_only=unread_only))
    return {"agent_id": agent_id, "messages": result, "count": len(result), "latency_us": latency}


@mcp.tool()
def octopoda_broadcast(agent_id: str, message: str, message_type: str = "info") -> dict:
    """Broadcast a message to all agents. Any agent can read broadcasts.

    Args:
        agent_id: The broadcasting agent
        message: Message to broadcast
        message_type: "info", "request", "response", or "alert"
    """
    agent = _get_agent(agent_id)
    parsed = _parse_value(message)
    result, latency = _timed(lambda: agent.broadcast(parsed, message_type))
    return {"broadcast": True, "msg_id": result.get("msg_id"), "latency_us": latency}


# -----------------------------------------------------------------------
# Goal Tracking Tools
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_set_goal(agent_id: str, goal: str, milestones: str | None = None) -> dict:
    """Set a goal for an agent with optional milestones. Goals are tracked
    persistently and integrate with drift detection.

    Args:
        agent_id: The agent to set a goal for
        goal: Description of what the agent should accomplish
        milestones: Optional comma-separated list of milestone descriptions
    """
    agent = _get_agent(agent_id)
    milestone_list = [m.strip() for m in milestones.split(",")] if milestones else []
    result, latency = _timed(lambda: agent.set_goal(goal, milestone_list))
    return {"agent_id": agent_id, "goal_set": True, "goal": goal, "latency_us": latency}


@mcp.tool()
def octopoda_get_goal(agent_id: str) -> dict:
    """Get the current goal and progress for an agent.

    Args:
        agent_id: The agent to check
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.get_goal())
    return {"agent_id": agent_id, "goal": result, "latency_us": latency}


@mcp.tool()
def octopoda_update_progress(agent_id: str, progress: float | None = None,
                             milestone_index: int | None = None,
                             note: str | None = None) -> dict:
    """Update progress on an agent's current goal.

    Args:
        agent_id: The agent to update
        progress: Overall progress 0.0 to 1.0 (optional)
        milestone_index: Mark a specific milestone as complete (optional)
        note: Progress note to log (optional)
    """
    agent = _get_agent(agent_id)
    result, latency = _timed(lambda: agent.update_progress(progress, milestone_index, note))
    return {"agent_id": agent_id, "progress": result, "latency_us": latency}


# -----------------------------------------------------------------------
# Filtered Search Tool
# -----------------------------------------------------------------------

@mcp.tool()
def octopoda_search_filtered(agent_id: str, query: str | None = None,
                             tags: str | None = None,
                             importance: str | None = None,
                             max_age_days: int | None = None) -> dict:
    """Search memories with combined filters. All filters are AND-combined.

    Args:
        agent_id: The agent to search
        query: Semantic search query (optional)
        tags: Comma-separated tags to filter by (optional)
        importance: Filter by importance: "critical", "normal", or "low" (optional)
        max_age_days: Only return memories from the last N days (optional)
    """
    agent = _get_agent(agent_id)
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    max_age_sec = max_age_days * 86400 if max_age_days else None
    result, latency = _timed(lambda: agent.search_filtered(
        query=query, tags=tag_list, importance=importance, max_age_seconds=max_age_sec
    ))
    return {"agent_id": agent_id, "results": result, "count": len(result), "latency_us": latency}


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

def main():
    """Run the MCP server (stdio transport).

    Works in two modes:
    - Cloud: set OCTOPODA_API_KEY to a real key (sk-octopoda-...)
    - Local: leave OCTOPODA_API_KEY unset (or any non-real value) — uses local SQLite
    """
    import sys
    api_key = os.environ.get("OCTOPODA_API_KEY", "")
    if not api_key:
        print("Octopoda MCP starting in LOCAL mode (no OCTOPODA_API_KEY set).",
              file=sys.stderr)
        print("Using SQLite at ~/.synrix/data/synrix.db", file=sys.stderr)
        print("For cloud sync, set OCTOPODA_API_KEY=sk-octopoda-...", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
