"""
Synrix Memory — High-Level Convenience Interface
==================================================
The simplest way to use Synrix. Three lines to persistent agent memory.

Usage:
    from synrix import Memory

    mem = Memory("my_agent")
    mem.remember("user_name", "Alice")
    print(mem.recall("user_name"))   # "Alice"
    print(mem.search("user_"))       # [{"key": "user_name", "value": "Alice"}]
"""
import logging

logger = logging.getLogger(__name__)


import json
import time
from typing import Any, Optional, List, Dict


class Memory:
    """
    High-level persistent memory for AI agents.

    Backed by Synrix's auto-detected backend (lattice binary or SQLite).
    Every write is ACID — data survives crashes and restarts.

    Args:
        agent_id: Unique identifier for this agent (default: "default").
        backend:  Backend type — "auto", "sqlite", "lattice", or "mock".
    """

    def __init__(self, agent_id: str = "default", backend: str = "auto"):
        from .agent_backend import get_synrix_backend
        self._backend = get_synrix_backend(backend=backend)
        self._agent_id = agent_id
        self._prefix = f"agents:{agent_id}:"

        # License enforcement: check agent limit
        from .licensing import check_agent_limit
        check_agent_limit(agent_id)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def remember(self, key: str, value: Any, metadata: Optional[Dict] = None) -> int:
        """
        Store a memory. Overwrites if key already exists.

        Args:
            key:      Memory key (e.g. "user_preference", "finding_01").
            value:    Any JSON-serializable value.
            metadata: Optional metadata dict.

        Returns:
            Node ID of the stored memory.
        """
        # License enforcement: check memory limit before write
        from .licensing import check_memory_limit, record_memory_written
        check_memory_limit(self._agent_id)

        full_key = self._prefix + key
        payload = {"value": value}
        meta = {"type": "agent_memory", "agent_id": self._agent_id}
        if metadata:
            meta.update(metadata)
        result = self._backend.write(full_key, payload, metadata=meta)

        # Track the write for future limit checks
        record_memory_written(self._agent_id)

        return result

    def recall(self, key: str) -> Any:
        """
        Retrieve a memory by exact key.

        Args:
            key: Memory key to look up.

        Returns:
            The stored value, or None if not found.
        """
        full_key = self._prefix + key
        result = self._backend.read(full_key)
        if result and "data" in result:
            data = result["data"]
            val = data.get("value", data)
            if isinstance(val, dict) and "value" in val:
                return val["value"]
            return val
        return None

    def search(self, prefix: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """
        Search memories by key prefix.

        Args:
            prefix: Key prefix to match (e.g. "finding_" matches "finding_01", "finding_02").
            limit:  Maximum results.

        Returns:
            List of dicts with "key" and "value" fields.
        """
        full_prefix = self._prefix + prefix
        results = self._backend.query_prefix(full_prefix, limit=limit)
        items = []
        for r in results:
            raw_key = r.get("key", "")
            # Strip agent prefix to return clean keys
            clean_key = raw_key[len(self._prefix):] if raw_key.startswith(self._prefix) else raw_key
            data = r.get("data", {})
            val = data.get("value", data)
            if isinstance(val, dict) and "value" in val:
                val = val["value"]
            items.append({"key": clean_key, "value": val})
        return items

    def forget(self, key: str) -> bool:
        """
        Delete a memory by key (writes a tombstone — data is never truly lost).

        Args:
            key: Memory key to forget.

        Returns:
            True if the key existed, False otherwise.
        """
        full_key = self._prefix + key
        existing = self._backend.read(full_key)
        if existing:
            self._backend.write(full_key, {"value": None, "_deleted": True},
                                metadata={"type": "tombstone"})
            return True
        return False

    def remember_many(self, items: Dict[str, Any]) -> int:
        """
        Store multiple memories at once.

        Args:
            items: Dict mapping keys to values.

        Returns:
            Number of items stored.
        """
        count = 0
        for key, value in items.items():
            self.remember(key, value)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def backend_type(self) -> str:
        return self._backend.backend_type

    def __repr__(self) -> str:
        return f"Memory(agent_id='{self._agent_id}', backend='{self.backend_type}')"
