"""
Octopoda Brain — Intelligent Agent Monitoring
================================================
Four core intelligence features that solve the biggest problems
in production AI agent deployments:

1. Loop Breaker    — Detect and auto-pause semantic loops
2. Drift Radar     — Track goal alignment over time
3. Contradiction Shield — Flag conflicting memories
4. Cost X-Ray      — Per-agent cost tracking with budget caps

All features use existing Octopoda infrastructure (embeddings,
temporal versioning, audit trails) to provide intelligence that
no other memory system offers.
"""

import time
import json
import struct
import threading
import logging
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger("synrix.brain")


# ---------------------------------------------------------------------------
# Data classes for Brain events
# ---------------------------------------------------------------------------

@dataclass
class BrainEvent:
    """A single event from the Brain intelligence system."""
    event_type: str  # "loop", "drift", "conflict", "cost"
    severity: str  # "info", "warning", "critical"
    agent_id: str
    tenant_id: str
    message: str
    details: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    action_required: bool = False
    action_type: str = ""  # "authorize", "kill", "resolve", "budget_pause"


# ---------------------------------------------------------------------------
# 1. LOOP BREAKER — Enhanced semantic loop detection
# ---------------------------------------------------------------------------

class LoopBreaker:
    """
    Detects when an agent is stuck in a semantic loop —
    writing the same or very similar content repeatedly.

    Enhanced beyond basic repeat detection:
    - Tracks cost of the loop (estimated tokens wasted)
    - Provides auto-pause capability
    - Calculates savings from early detection
    """

    # Shared state across all agents
    _trackers: Dict[str, list] = {}
    _paused_agents: Dict[str, dict] = {}  # agent_key -> {paused_at, reason, cost_saved}
    _lock = threading.Lock()

    # Thresholds
    SIMILARITY_THRESHOLD = 0.90  # Cosine similarity to consider "same"
    WINDOW_SECONDS = 300  # 5-minute rolling window
    TRIGGER_COUNT = 3  # 3 similar writes = loop
    MAX_HISTORY = 30  # Keep last 30 entries per agent

    @classmethod
    def check(cls, tenant_id: str, agent_id: str, embedding, key: str,
              value_size: int = 0) -> Optional[BrainEvent]:
        """Check if this write is part of a loop. Returns BrainEvent if loop detected."""
        if embedding is None:
            return None

        tracker_key = f"{tenant_id}:{agent_id}"
        now = time.time()

        # Convert embedding to numpy for comparison
        try:
            import numpy as np
            if isinstance(embedding, bytes):
                dim = len(embedding) // 4
                query_vec = np.frombuffer(embedding, dtype=np.float32)
            elif isinstance(embedding, np.ndarray):
                query_vec = embedding
            else:
                return None
        except Exception:
            return None

        with cls._lock:
            if tracker_key not in cls._trackers:
                cls._trackers[tracker_key] = []

            entries = cls._trackers[tracker_key]

            # Prune old entries outside window
            entries[:] = [e for e in entries if now - e["time"] < cls.WINDOW_SECONDS]

            # Count similar entries
            similar_count = 0
            similar_keys = []
            for entry in entries:
                try:
                    stored_vec = entry["embedding"]
                    if isinstance(stored_vec, bytes):
                        stored_vec = np.frombuffer(stored_vec, dtype=np.float32)
                    dot = float(np.dot(query_vec, stored_vec))
                    norm = float(np.linalg.norm(query_vec) * np.linalg.norm(stored_vec))
                    if norm > 0:
                        similarity = dot / norm
                        if similarity >= cls.SIMILARITY_THRESHOLD:
                            similar_count += 1
                            similar_keys.append(entry["key"])
                except Exception:
                    continue

            # Add current entry
            entries.append({
                "embedding": embedding if isinstance(embedding, bytes) else embedding.tobytes(),
                "time": now,
                "key": key,
            })

            # Cap history
            if len(entries) > cls.MAX_HISTORY:
                entries[:] = entries[-cls.MAX_HISTORY:]

        # Check if loop detected
        if similar_count >= cls.TRIGGER_COUNT:
            # Estimate cost wasted (rough: ~100 tokens per write at $0.002/1K tokens)
            estimated_cost = similar_count * 0.0002
            return BrainEvent(
                event_type="loop",
                severity="critical",
                agent_id=agent_id,
                tenant_id=tenant_id,
                message=f"Loop detected: {similar_count} similar writes in {cls.WINDOW_SECONDS}s",
                details={
                    "repeat_count": similar_count,
                    "similar_keys": similar_keys[-5:],
                    "current_key": key,
                    "window_seconds": cls.WINDOW_SECONDS,
                    "estimated_cost_wasted": round(estimated_cost, 4),
                    "similarity_threshold": cls.SIMILARITY_THRESHOLD,
                },
                action_required=True,
                action_type="kill",
            )
        return None

    @classmethod
    def pause_agent(cls, tenant_id: str, agent_id: str, reason: str = "loop"):
        """Pause an agent due to detected loop."""
        key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            cls._paused_agents[key] = {
                "paused_at": time.time(),
                "reason": reason,
                "agent_id": agent_id,
            }

    @classmethod
    def is_paused(cls, tenant_id: str, agent_id: str) -> bool:
        key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            return key in cls._paused_agents

    @classmethod
    def resume_agent(cls, tenant_id: str, agent_id: str):
        key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            cls._paused_agents.pop(key, None)


# ---------------------------------------------------------------------------
# 2. DRIFT RADAR — Goal alignment tracking
# ---------------------------------------------------------------------------

class DriftRadar:
    """
    Tracks how far an agent has drifted from its original goal.

    On first memory write, captures the "goal embedding" — the semantic
    fingerprint of what the agent was supposed to do. On subsequent writes,
    compares the rolling average of recent embeddings against the goal.

    Alignment score: 100% = on track, 0% = completely off topic.
    """

    _goals: Dict[str, dict] = {}  # agent_key -> {goal_embedding, initial_keys, created_at}
    _recent_embeddings: Dict[str, list] = {}  # agent_key -> [last N embeddings]
    _lock = threading.Lock()

    WINDOW_SIZE = 20  # Compare against last 20 embeddings
    WARNING_THRESHOLD = 0.65  # Below this = drifting
    CRITICAL_THRESHOLD = 0.45  # Below this = severely drifted

    @classmethod
    def set_goal(cls, tenant_id: str, agent_id: str, embedding, goal_text: str = ""):
        """Set the goal embedding for an agent (called on first write or explicitly)."""
        key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            if key not in cls._goals:
                cls._goals[key] = {
                    "embedding": embedding if isinstance(embedding, bytes) else embedding.tobytes() if hasattr(embedding, 'tobytes') else embedding,
                    "goal_text": goal_text,
                    "created_at": time.time(),
                }

    @classmethod
    def track(cls, tenant_id: str, agent_id: str, embedding) -> Optional[BrainEvent]:
        """Track a new embedding and check for drift."""
        if embedding is None:
            return None

        key = f"{tenant_id}:{agent_id}"

        with cls._lock:
            # Auto-set goal from first write
            if key not in cls._goals:
                cls._goals[key] = {
                    "embedding": embedding if isinstance(embedding, bytes) else embedding.tobytes() if hasattr(embedding, 'tobytes') else embedding,
                    "created_at": time.time(),
                }
                return None  # First write, no drift yet

            # Add to recent embeddings
            if key not in cls._recent_embeddings:
                cls._recent_embeddings[key] = []
            cls._recent_embeddings[key].append(
                embedding if isinstance(embedding, bytes) else embedding.tobytes() if hasattr(embedding, 'tobytes') else embedding
            )
            if len(cls._recent_embeddings[key]) > cls.WINDOW_SIZE:
                cls._recent_embeddings[key] = cls._recent_embeddings[key][-cls.WINDOW_SIZE:]

            # Need at least 5 writes to measure drift
            if len(cls._recent_embeddings[key]) < 5:
                return None

        # Compute alignment
        alignment = cls.get_alignment(tenant_id, agent_id)
        if alignment is None:
            return None

        if alignment < cls.CRITICAL_THRESHOLD:
            return BrainEvent(
                event_type="drift",
                severity="critical",
                agent_id=agent_id,
                tenant_id=tenant_id,
                message=f"Agent severely drifted from goal. Alignment: {alignment:.0%}",
                details={
                    "alignment_percent": round(alignment * 100, 1),
                    "threshold_warning": cls.WARNING_THRESHOLD,
                    "threshold_critical": cls.CRITICAL_THRESHOLD,
                    "recent_writes": len(cls._recent_embeddings.get(f"{tenant_id}:{agent_id}", [])),
                },
                action_required=True,
                action_type="authorize",
            )
        elif alignment < cls.WARNING_THRESHOLD:
            return BrainEvent(
                event_type="drift",
                severity="warning",
                agent_id=agent_id,
                tenant_id=tenant_id,
                message=f"Agent drifting from goal. Alignment: {alignment:.0%}",
                details={
                    "alignment_percent": round(alignment * 100, 1),
                },
            )
        return None

    @classmethod
    def get_alignment(cls, tenant_id: str, agent_id: str) -> Optional[float]:
        """Get current goal alignment as a float 0.0-1.0."""
        key = f"{tenant_id}:{agent_id}"

        with cls._lock:
            if key not in cls._goals or key not in cls._recent_embeddings:
                return None
            if not cls._recent_embeddings[key]:
                return None

            goal_emb = cls._goals[key]["embedding"]
            recent = cls._recent_embeddings[key]

        try:
            import numpy as np
            if isinstance(goal_emb, bytes):
                goal_vec = np.frombuffer(goal_emb, dtype=np.float32).copy()
            else:
                goal_vec = np.array(goal_emb, dtype=np.float32)

            # Average of recent embeddings
            recent_vecs = []
            for r in recent:
                if isinstance(r, bytes):
                    recent_vecs.append(np.frombuffer(r, dtype=np.float32).copy())
                else:
                    recent_vecs.append(np.array(r, dtype=np.float32))

            avg_vec = np.mean(recent_vecs, axis=0)

            # Cosine similarity
            dot = float(np.dot(goal_vec, avg_vec))
            norm = float(np.linalg.norm(goal_vec) * np.linalg.norm(avg_vec))
            if norm == 0:
                return None
            return max(0.0, min(1.0, dot / norm))
        except Exception as e:
            logger.error("Drift alignment error: %s", e)
            return None

    @classmethod
    def get_agent_drift(cls, tenant_id: str, agent_id: str) -> dict:
        """Get drift info for an agent (for API response)."""
        alignment = cls.get_alignment(tenant_id, agent_id)
        key = f"{tenant_id}:{agent_id}"
        goal = cls._goals.get(key, {})
        return {
            "agent_id": agent_id,
            "alignment_percent": round(alignment * 100, 1) if alignment is not None else None,
            "status": (
                "on_track" if alignment is None or alignment >= cls.WARNING_THRESHOLD
                else "drifting" if alignment >= cls.CRITICAL_THRESHOLD
                else "severely_drifted"
            ),
            "goal_set_at": goal.get("created_at"),
            "recent_samples": len(cls._recent_embeddings.get(key, [])),
            "thresholds": {
                "warning": cls.WARNING_THRESHOLD,
                "critical": cls.CRITICAL_THRESHOLD,
            },
        }


# ---------------------------------------------------------------------------
# 3. CONTRADICTION SHIELD — Memory conflict detection
# ---------------------------------------------------------------------------

class ContradictionShield:
    """
    Detects when a new memory contradicts an existing one.

    Uses semantic similarity to find related memories, then flags
    potential contradictions for human review.

    The key insight: high similarity + different value = contradiction.
    "user prefers dark mode" and "user wants light theme" are
    semantically similar (both about UI preference) but contradictory.
    """

    _conflicts: Dict[str, list] = {}  # tenant:agent -> [conflict events]
    _lock = threading.Lock()

    SIMILARITY_THRESHOLD = 0.88  # High threshold — only flag very similar content that differs

    @classmethod
    def check(cls, tenant_id: str, agent_id: str, key: str, value: Any,
              embedding, backend) -> Optional[BrainEvent]:
        """Check if this new memory contradicts existing ones."""
        if embedding is None or backend is None:
            return None

        try:
            # Search for semantically similar existing memories
            results = backend.semantic_search(
                query_embedding=embedding,
                limit=5,
                threshold=cls.SIMILARITY_THRESHOLD,
                name_prefix=f"agents:{agent_id}:",
            )

            if not results:
                return None

            conflicts = []
            for r in results:
                existing_key = r.get("key", r.get("name", ""))
                existing_data = r.get("data", {})
                existing_value = existing_data.get("value", existing_data)
                if isinstance(existing_value, dict) and "value" in existing_value:
                    existing_value = existing_value["value"]

                score = r.get("score", 0)
                short_key = existing_key.replace(f"agents:{agent_id}:", "", 1)

                # Skip if it's the same key (that's an update, not a conflict)
                if short_key == key:
                    continue

                # High similarity but different key = potential conflict
                if score >= cls.SIMILARITY_THRESHOLD:
                    conflicts.append({
                        "existing_key": short_key,
                        "existing_value": str(existing_value)[:200],
                        "new_key": key,
                        "new_value": str(value)[:200],
                        "similarity": round(score, 4),
                    })

            if conflicts:
                tracker_key = f"{tenant_id}:{agent_id}"
                event = BrainEvent(
                    event_type="conflict",
                    severity="warning",
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    message=f"Potential contradiction: {len(conflicts)} similar memories found",
                    details={
                        "conflicts": conflicts,
                        "new_key": key,
                        "new_value": str(value)[:200],
                    },
                    action_required=True,
                    action_type="resolve",
                )

                with cls._lock:
                    if tracker_key not in cls._conflicts:
                        cls._conflicts[tracker_key] = []
                    cls._conflicts[tracker_key].append({
                        "event": event.details,
                        "timestamp": time.time(),
                    })
                    # Keep last 50 conflicts per agent
                    if len(cls._conflicts[tracker_key]) > 50:
                        cls._conflicts[tracker_key] = cls._conflicts[tracker_key][-50:]

                return event

        except Exception as e:
            logger.debug("Contradiction check error: %s", e)

        return None

    @classmethod
    def get_conflicts(cls, tenant_id: str, agent_id: str) -> list:
        """Get recent conflicts for an agent."""
        key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            return list(cls._conflicts.get(key, []))


# ---------------------------------------------------------------------------
# 4. COST X-RAY — Per-agent cost tracking with budget caps
# ---------------------------------------------------------------------------

class MemoryHealth:
    """
    Tracks memory freshness and health per agent.

    Identifies stale, hot, and dead memories based on access patterns:
    - HOT: Read within last 24 hours (actively used)
    - WARM: Read within last 7 days
    - STALE: Not read in 30+ days (possibly outdated)
    - DEAD: Not read in 90+ days (likely obsolete)

    Provides a health score: 100% = all memories are fresh and accessed,
    0% = all memories are stale and never read.
    """

    # Track read timestamps: tenant:agent:key -> last_read_time
    _reads: Dict[str, Dict[str, float]] = {}  # tenant:agent -> {key: timestamp}
    _writes: Dict[str, Dict[str, float]] = {}  # tenant:agent -> {key: timestamp}
    _lock = threading.Lock()

    # Thresholds (seconds)
    HOT_THRESHOLD = 86400       # 24 hours
    WARM_THRESHOLD = 604800     # 7 days
    STALE_THRESHOLD = 2592000   # 30 days
    DEAD_THRESHOLD = 7776000    # 90 days

    @classmethod
    def record_write(cls, tenant_id: str, agent_id: str, key: str):
        """Record a memory write."""
        tracker_key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            if tracker_key not in cls._writes:
                cls._writes[tracker_key] = {}
            cls._writes[tracker_key][key] = time.time()

    @classmethod
    def record_read(cls, tenant_id: str, agent_id: str, key: str):
        """Record a memory read/recall."""
        tracker_key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            if tracker_key not in cls._reads:
                cls._reads[tracker_key] = {}
            cls._reads[tracker_key][key] = time.time()

    @classmethod
    def check(cls, tenant_id: str, agent_id: str) -> Optional[BrainEvent]:
        """Check memory health and alert if too many stale memories."""
        health = cls.get_health(tenant_id, agent_id)
        stale_pct = health.get("stale_percent", 0)
        dead_count = health.get("dead", 0)

        if stale_pct > 50:
            return BrainEvent(
                event_type="health",
                severity="warning",
                agent_id=agent_id,
                tenant_id=tenant_id,
                message=f"Memory health declining: {stale_pct:.0f}% stale, {dead_count} dead memories",
                details={
                    "health_score": health.get("health_score"),
                    "total_memories": health.get("total"),
                    "hot": health.get("hot"),
                    "warm": health.get("warm"),
                    "stale": health.get("stale"),
                    "dead": health.get("dead"),
                    "stale_percent": stale_pct,
                },
                action_required=dead_count > 10,
                action_type="cleanup" if dead_count > 10 else "",
            )
        return None

    @classmethod
    def get_health(cls, tenant_id: str, agent_id: str) -> dict:
        """Get memory health breakdown for an agent."""
        tracker_key = f"{tenant_id}:{agent_id}"
        now = time.time()

        with cls._lock:
            writes = dict(cls._writes.get(tracker_key, {}))
            reads = dict(cls._reads.get(tracker_key, {}))

        # For each memory, determine its status based on last access
        # Last access = max(last_read, last_write)
        all_keys = set(writes.keys()) | set(reads.keys())
        total = len(all_keys)

        if total == 0:
            return {
                "agent_id": agent_id,
                "health_score": 100,
                "total": 0,
                "hot": 0, "warm": 0, "stale": 0, "dead": 0,
                "stale_percent": 0,
                "hot_keys": [], "stale_keys": [], "dead_keys": [],
            }

        hot = 0
        warm = 0
        stale = 0
        dead = 0
        hot_keys = []
        stale_keys = []
        dead_keys = []

        for key in all_keys:
            last_write = writes.get(key, 0)
            last_read = reads.get(key, 0)
            last_access = max(last_write, last_read)
            age = now - last_access

            if age < cls.HOT_THRESHOLD:
                hot += 1
                hot_keys.append(key)
            elif age < cls.WARM_THRESHOLD:
                warm += 1
            elif age < cls.DEAD_THRESHOLD:
                stale += 1
                stale_keys.append(key)
            else:
                dead += 1
                dead_keys.append(key)

        # Health score: weighted by freshness
        # Hot=100, Warm=75, Stale=25, Dead=0
        if total > 0:
            score = ((hot * 100) + (warm * 75) + (stale * 25) + (dead * 0)) / total
        else:
            score = 100

        stale_pct = ((stale + dead) / total * 100) if total > 0 else 0

        return {
            "agent_id": agent_id,
            "health_score": round(score, 1),
            "total": total,
            "hot": hot,
            "warm": warm,
            "stale": stale,
            "dead": dead,
            "stale_percent": round(stale_pct, 1),
            "hot_keys": hot_keys[:10],  # Top 10
            "stale_keys": stale_keys[:10],
            "dead_keys": dead_keys[:10],
        }


# ---------------------------------------------------------------------------
# 5. DARK RADAR — Detect memories invisible to search
# ---------------------------------------------------------------------------

class DarkRadar:
    """
    Detects memories that exist in the store but are invisible to search.

    A memory is "dark" when it was written successfully but cannot be
    retrieved by semantic search — a silent data loss worse than not
    writing at all. The agent believes it remembered something; it cannot
    find it.

    Two detection levels:
    - Embedding-level (always runs): None or zero-vector embedding means
      the record will never match any semantic query.
    - Search-level (optional, requires backend): after write, verify the
      key surfaces in a search for its own content. Catches indexing
      failures where the embedding exists but didn't land in the index.

    Discovered in production: Willow memory audit found 27/28 atoms
    (96%) dark in a Postgres knowledge store due to FTS tokenization gaps.
    Embedding-based stores have their own failure mode — silent index
    desync when the write path and the embedding path diverge.
    """

    ZERO_VEC_THRESHOLD = 1e-6  # Embedding norm below this = effectively zero
    _dark_counts: Dict[str, int] = {}  # tenant:agent -> count of dark writes
    _lock = threading.Lock()

    @classmethod
    def check(
        cls,
        tenant_id: str,
        agent_id: str,
        key: str,
        value: Any,
        embedding,
        backend=None,
    ) -> Optional[BrainEvent]:
        """
        Check if this memory will be findable by search after writing.

        Args:
            tenant_id: Tenant identifier.
            agent_id:  Agent identifier.
            key:       Memory key just written.
            value:     Memory value just written.
            embedding: Embedding returned by the write path (may be None).
            backend:   Optional — if provided, performs a live search
                       verification to catch index desync.

        Returns:
            BrainEvent with event_type="dark" if the memory is dark,
            otherwise None.
        """
        dark_reason: Optional[str] = None

        # Level 1: embedding is None — record has no vector, invisible to search
        if embedding is None:
            dark_reason = "embedding is None — memory has no vector representation"

        # Level 2: zero-vector embedding — mathematically invisible (cos sim = 0 with everything)
        if dark_reason is None:
            try:
                import numpy as np

                if isinstance(embedding, bytes):
                    vec = np.frombuffer(embedding, dtype=np.float32).copy()
                else:
                    vec = np.array(embedding, dtype=np.float32)

                norm = float(np.linalg.norm(vec))
                if norm < cls.ZERO_VEC_THRESHOLD:
                    dark_reason = f"embedding is a zero-vector (norm={norm:.2e}) — will never match any query"
            except Exception:
                pass  # Non-fatal — skip this check if numpy is unavailable

        # Level 3: search verification — write landed but not findable
        if dark_reason is None and backend is not None and embedding is not None:
            try:
                results = backend.semantic_search(
                    query_embedding=embedding,
                    limit=5,
                    threshold=0.90,
                    name_prefix=f"agents:{agent_id}:",
                )
                found = any(
                    r.get("key", r.get("name", "")).endswith(key)
                    for r in (results or [])
                )
                if not found:
                    dark_reason = (
                        f"memory written but not returned by semantic search "
                        f"(searched key='{key}', got {len(results or [])} results)"
                    )
            except Exception:
                pass  # Non-fatal — backend errors don't block writes

        if dark_reason is None:
            return None

        tracker_key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            cls._dark_counts[tracker_key] = cls._dark_counts.get(tracker_key, 0) + 1
            total_dark = cls._dark_counts[tracker_key]

        return BrainEvent(
            event_type="dark",
            severity="warning",
            agent_id=agent_id,
            tenant_id=tenant_id,
            message=f"Dark memory: '{key}' written but invisible to search",
            details={
                "key": key,
                "reason": dark_reason,
                "total_dark_this_session": total_dark,
                "value_preview": str(value)[:100] if value is not None else None,
            },
            action_required=True,
            action_type="reindex",
        )

    @classmethod
    def get_dark_count(cls, tenant_id: str, agent_id: str) -> int:
        """Return total dark writes recorded this session for the agent."""
        key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            return cls._dark_counts.get(key, 0)

    @classmethod
    def reset(cls, tenant_id: str, agent_id: str):
        """Reset dark count for an agent (e.g. after a successful reindex)."""
        key = f"{tenant_id}:{agent_id}"
        with cls._lock:
            cls._dark_counts.pop(key, None)


# ---------------------------------------------------------------------------
# Brain Hub — Unified interface for all 5 features
# ---------------------------------------------------------------------------

class BrainHub:
    """
    Central hub for all Brain intelligence features.
    Called from runtime.remember() and cloud_server.py endpoints.
    """

    _events: Dict[str, list] = {}  # tenant_id -> [BrainEvent]
    _lock = threading.Lock()
    MAX_EVENTS_PER_TENANT = 200

    @classmethod
    def process_write(cls, tenant_id: str, agent_id: str, key: str,
                      value: Any, embedding, backend=None,
                      has_extraction: bool = False) -> List[BrainEvent]:
        """
        Process a memory write through all 5 Brain features.
        Called from runtime.remember() after the write succeeds.
        Returns list of any triggered events.
        """
        events = []

        # 1. Loop Breaker
        loop_event = LoopBreaker.check(tenant_id, agent_id, embedding, key)
        if loop_event:
            events.append(loop_event)
            cls._store_event(tenant_id, loop_event)

        # 2. Drift Radar
        drift_event = DriftRadar.track(tenant_id, agent_id, embedding)
        if drift_event:
            events.append(drift_event)
            cls._store_event(tenant_id, drift_event)

        # 3. Contradiction Shield
        conflict_event = ContradictionShield.check(
            tenant_id, agent_id, key, value, embedding, backend
        )
        if conflict_event:
            events.append(conflict_event)
            cls._store_event(tenant_id, conflict_event)

        # 4. Memory Health
        MemoryHealth.record_write(tenant_id, agent_id, key)
        health_event = MemoryHealth.check(tenant_id, agent_id)
        if health_event:
            events.append(health_event)
            cls._store_event(tenant_id, health_event)

        # 5. Dark Radar — detect writes invisible to search
        dark_event = DarkRadar.check(tenant_id, agent_id, key, value, embedding, backend)
        if dark_event:
            events.append(dark_event)
            cls._store_event(tenant_id, dark_event)

        return events

    @classmethod
    def process_read(cls, tenant_id: str, agent_id: str, key: str):
        """Record a memory read for health tracking."""
        MemoryHealth.record_read(tenant_id, agent_id, key)

    @classmethod
    def _store_event(cls, tenant_id: str, event: BrainEvent):
        """Store an event in the tenant's event log."""
        with cls._lock:
            if tenant_id not in cls._events:
                cls._events[tenant_id] = []
            cls._events[tenant_id].append({
                "event_type": event.event_type,
                "severity": event.severity,
                "agent_id": event.agent_id,
                "message": event.message,
                "details": event.details,
                "timestamp": event.timestamp,
                "action_required": event.action_required,
                "action_type": event.action_type,
            })
            # Cap per tenant
            if len(cls._events[tenant_id]) > cls.MAX_EVENTS_PER_TENANT:
                cls._events[tenant_id] = cls._events[tenant_id][-cls.MAX_EVENTS_PER_TENANT:]

    @classmethod
    def get_events(cls, tenant_id: str, agent_id: str = None,
                   event_type: str = None, limit: int = 50) -> list:
        """Get Brain events for a tenant, optionally filtered."""
        with cls._lock:
            events = list(cls._events.get(tenant_id, []))

        if agent_id:
            events = [e for e in events if e["agent_id"] == agent_id]
        if event_type:
            events = [e for e in events if e["event_type"] == event_type]

        # Most recent first
        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return events[:limit]

    @classmethod
    def get_brain_status(cls, tenant_id: str) -> dict:
        """Get overall Brain status for a tenant (for dashboard)."""
        events = cls.get_events(tenant_id, limit=100)

        active_loops = len([e for e in events if e["event_type"] == "loop"
                           and time.time() - e["timestamp"] < 300])
        active_drifts = len([e for e in events if e["event_type"] == "drift"
                            and e["severity"] in ("warning", "critical")
                            and time.time() - e["timestamp"] < 600])
        active_conflicts = len([e for e in events if e["event_type"] == "conflict"
                               and e.get("action_required")])
        health_warnings = len([e for e in events if e["event_type"] == "health"
                              and e["severity"] in ("warning", "critical")
                              and time.time() - e["timestamp"] < 3600])
        dark_warnings = len([e for e in events if e["event_type"] == "dark"
                            and time.time() - e["timestamp"] < 3600])

        return {
            "status": "healthy" if not any([active_loops, active_drifts, active_conflicts,
                                            health_warnings, dark_warnings]) else "attention_needed",
            "active_loops": active_loops,
            "active_drifts": active_drifts,
            "active_conflicts": active_conflicts,
            "health_warnings": health_warnings,
            "dark_warnings": dark_warnings,
            "total_events": len(events),
            "recent_events": events[:10],
        }
