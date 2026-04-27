"""
Local backend adapter for framework integrations.

Wraps a SynrixAgentBackend to match the cloud Agent API so integrations
(LangChain / CrewAI / AutoGen / OpenCode) work in both local and cloud
mode without code changes.

Method coverage:
  - core memory:     write, read, keys, search, forget
  - context:         get_context, related, history
  - goals/progress:  set_goal, get_goal, update_progress
  - messaging:       send_message, read_messages, broadcast
  - health/cleanup:  memory_health, consolidate
  - lifecycle:       snapshot (no-op locally), agent_stats, log_decision

The cloud Agent API has ~15 methods; before this version only 4 were
implemented (write/read/keys/search), so calls to anything else from
local mode raised AttributeError. This file closes that gap by mapping
each method onto operations the backend already supports.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _unwrap_value(raw):
    """Unwrap backend storage format to get the actual value.

    Backend stores: {"value": X, "metadata": {...}, "timestamp": ...}
    or nested:      {"data": {"value": X, ...}, "key": ..., "score": ...}
    Returns just X (or the inner dict if X is a dict).
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return raw

    if "data" in raw and isinstance(raw["data"], dict):
        inner = raw["data"]
        if "value" in inner:
            return inner["value"]
        return inner

    if "value" in raw:
        return raw["value"]

    return raw


def _ts_us() -> int:
    """Microsecond timestamp — used in keys to keep them ordered."""
    return int(time.time() * 1_000_000)


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------

class _LocalAgentAdapter:
    """Adapts a local SynrixAgentBackend to the cloud Agent interface.

    Used when `backend=` is passed to integration constructors, enabling
    local-only usage without a cloud account or HTTP API.
    """

    def __init__(self, backend, agent_id: str = "local"):
        self.backend = backend
        self.agent_id = agent_id

    # ── core memory primitives ───────────────────────────────────────────

    def write(self, key: str, value: Any, metadata: Optional[Dict] = None,
              tags: Optional[List[str]] = None) -> Dict:
        payload = value if isinstance(value, dict) else {"value": value}
        if tags:
            payload["_tags"] = tags
        nid = self.backend.write(self._scope(key), payload, metadata=metadata)
        return {"node_id": nid, "key": key}

    def read(self, key: str) -> Optional[Any]:
        return _unwrap_value(self.backend.read(self._scope(key)))

    def keys(self, prefix: str = "", limit: int = 50) -> List[Dict]:
        full_prefix = self._scope(prefix) if prefix else self._scope("")
        results = self.backend.query_prefix(full_prefix, limit=limit) or []
        items: List[Dict] = []
        for r in results:
            raw_key = r.get("key", r.get("name", ""))
            user_key = self._unscope(raw_key)
            items.append({"key": user_key, "value": _unwrap_value(r)})
        return items

    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Semantic search if the backend supports it; otherwise prefix browse."""
        try:
            sem = getattr(self.backend, "semantic_search", None)
            if callable(sem):
                results = sem(query=query, limit=limit) or []
                items = []
                for r in results:
                    raw_key = r.get("key", r.get("name", ""))
                    items.append({
                        "key": self._unscope(raw_key),
                        "value": _unwrap_value(r),
                        "score": r.get("score"),
                    })
                return items
        except Exception:
            pass
        return self.keys(prefix="", limit=limit)

    def forget(self, key: str) -> Dict[str, Any]:
        """Delete a memory by key. Returns {'deleted': bool, 'key': ...}."""
        full = self._scope(key)
        deleted = False
        try:
            delete_fn = getattr(self.backend, "delete", None)
            if callable(delete_fn):
                deleted = bool(delete_fn(full))
        except Exception:
            deleted = False
        return {"deleted": deleted, "key": key}

    # ── context / related ────────────────────────────────────────────────

    def get_context(self, key: str, window: int = 5) -> Dict[str, Any]:
        """Return a memory and a few neighbours for situational context.

        Cloud version uses recency + co-occurrence. Locally we approximate
        by returning the key plus the N most recent rows under the
        agent's own prefix.
        """
        target = self.read(key)
        recent = self.keys(prefix="", limit=window + 1)
        recent = [r for r in recent if r.get("key") != key][:window]
        return {
            "key": key,
            "value": target,
            "recent": recent,
            "agent_id": self.agent_id,
        }

    def related(self, key_or_entity: str, limit: int = 10) -> List[Dict]:
        """Find memories related to a key or entity. Tries semantic search
        first (if embeddings are available), falls back to prefix browse."""
        try:
            return self.search(key_or_entity, limit=limit)
        except Exception:
            return []

    def history(self, key: str) -> List[Dict[str, Any]]:
        """Version history for a key (if the backend supports temporal)."""
        try:
            fn = getattr(self.backend, "get_history", None)
            if callable(fn):
                return fn(self._scope(key)) or []
        except Exception:
            pass
        return []

    # ── goals / progress ─────────────────────────────────────────────────

    def set_goal(self, goal: str, **kwargs) -> Dict:
        return self.write("goal", {
            "value": goal,
            "set_at": time.time(),
            **kwargs,
        })

    def get_goal(self) -> Optional[Any]:
        v = self.read("goal")
        if isinstance(v, dict) and "value" in v:
            return v["value"]
        return v

    def update_progress(self, status: str, **kwargs) -> Dict:
        """Append a progress note. Uses a unique timestamp suffix so
        progress entries form a history rather than overwriting."""
        return self.write(f"progress:{_ts_us()}", {
            "status": status,
            "ts": time.time(),
            **kwargs,
        })

    # ── messaging ────────────────────────────────────────────────────────

    def send_message(self, to_agent: str, message: Any,
                     subject: str = "", **kwargs) -> Dict:
        """Drop a message into another agent's inbox. The recipient reads
        it via read_messages()."""
        key = f"_inbox:{to_agent}:{_ts_us()}"
        nid = self.backend.write(key, {
            "from": self.agent_id,
            "to": to_agent,
            "subject": subject,
            "message": message,
            "ts": time.time(),
            "read": False,
            **kwargs,
        })
        return {"node_id": nid, "to": to_agent}

    def read_messages(self, unread_only: bool = False,
                      limit: int = 50) -> List[Dict]:
        """Read this agent's inbox, newest first."""
        prefix = f"_inbox:{self.agent_id}:"
        rows = self.backend.query_prefix(prefix, limit=limit) or []
        items: List[Dict] = []
        for r in rows:
            v = _unwrap_value(r)
            if not isinstance(v, dict):
                continue
            if unread_only and v.get("read"):
                continue
            v["_key"] = r.get("key", r.get("name", ""))
            items.append(v)
        items.sort(key=lambda x: x.get("ts", 0), reverse=True)
        return items

    def broadcast(self, message: Any, channel: str = "all",
                  **kwargs) -> Dict:
        """Drop a message into a shared channel any agent can read."""
        key = f"_broadcast:{channel}:{_ts_us()}"
        nid = self.backend.write(key, {
            "from": self.agent_id,
            "channel": channel,
            "message": message,
            "ts": time.time(),
            **kwargs,
        })
        return {"node_id": nid, "channel": channel}

    # ── health / cleanup ─────────────────────────────────────────────────

    def memory_health(self) -> Dict[str, Any]:
        """Report counts + age distribution of this agent's memories."""
        rows = self.backend.query_prefix(self._scope(""), limit=10_000) or []
        now = time.time()
        ages: List[float] = []
        for r in rows:
            data = r.get("data") or {}
            ts = (data.get("timestamp")
                  if isinstance(data, dict) else None) or r.get("valid_from") or 0
            try:
                ts = float(ts)
            except Exception:
                continue
            ages.append(max(0.0, now - ts))
        ages.sort()
        n = len(ages)
        median = ages[n // 2] if n else 0.0
        return {
            "agent_id": self.agent_id,
            "total_memories": n,
            "median_age_seconds": median,
            "newest_age_seconds": ages[0] if ages else 0,
            "oldest_age_seconds": ages[-1] if ages else 0,
        }

    def consolidate(self, similarity_threshold: float = 0.90,
                    dry_run: bool = True) -> Dict[str, Any]:
        """Find near-duplicate memories. Local fallback uses string
        equality on the value preview when embeddings aren't available."""
        rows = self.backend.query_prefix(self._scope(""), limit=2000) or []
        groups: Dict[str, List[str]] = {}
        for r in rows:
            v = _unwrap_value(r)
            sig = repr(v)[:200]
            groups.setdefault(sig, []).append(
                self._unscope(r.get("key", r.get("name", ""))))
        dupes = {sig: keys for sig, keys in groups.items() if len(keys) > 1}
        merged = 0
        if not dry_run:
            for keys in dupes.values():
                # Keep the first, delete the rest.
                for k in keys[1:]:
                    if self.forget(k).get("deleted"):
                        merged += 1
        return {
            "agent_id": self.agent_id,
            "duplicate_groups": len(dupes),
            "merged_count": merged,
            "dry_run": dry_run,
            "similarity_threshold": similarity_threshold,
        }

    # ── lifecycle ────────────────────────────────────────────────────────

    def snapshot(self, label: Optional[str] = None) -> Dict[str, Any]:
        """Locally we don't take a true point-in-time copy — we just
        write a marker row so log_decision/agent_stats stays consistent
        with the cloud surface."""
        label = label or f"auto-{int(time.time())}"
        self.write(f"snapshots:{label}", {
            "label": label,
            "captured_at": time.time(),
            "note": "local-mode marker (no point-in-time copy)",
        })
        return {"label": label, "keys_captured": 0}

    def agent_stats(self) -> Dict[str, Any]:
        h = self.memory_health()
        return {
            "agent_id": self.agent_id,
            "total_memories": h.get("total_memories", 0),
            "median_age_seconds": h.get("median_age_seconds", 0),
        }

    def log_decision(self, decision: str, reasoning: str = "",
                     **kwargs) -> Dict[str, Any]:
        return self.write(f"decisions:{_ts_us()}", {
            "decision": decision,
            "reasoning": reasoning,
            "ts": time.time(),
            **kwargs,
        })

    # ── internal: scoping ────────────────────────────────────────────────

    def _scope(self, key: str) -> str:
        """Prefix user-facing keys with `agents:<agent_id>:` for storage so
        per-agent isolation matches the cloud convention."""
        if not key:
            return f"agents:{self.agent_id}:"
        if key.startswith("agents:") or key.startswith("_inbox:") \
                or key.startswith("_broadcast:"):
            return key  # already scoped or cross-agent shared
        return f"agents:{self.agent_id}:{key}"

    def _unscope(self, full_key: str) -> str:
        """Strip the agents:<agent_id>: prefix when surfacing keys to users."""
        head = f"agents:{self.agent_id}:"
        if full_key.startswith(head):
            return full_key[len(head):]
        return full_key
