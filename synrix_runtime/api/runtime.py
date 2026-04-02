"""
Synrix Agent Runtime — Developer API
The developer-facing interface. Clean, fast, intuitive.

Usage:
    from synrix_runtime import AgentRuntime
    agent = AgentRuntime("my_agent", agent_type="researcher")
    agent.remember("user_preference", {"format": "bullet_points"})
    value = agent.recall("user_preference")
"""

import logging
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("synrix.runtime")

# Bounded thread pool for background enrichment (fact extraction + NER).
# Prevents thread explosion: max 4 concurrent LLM calls, extras queue up.
_enrichment_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="enrich")

# Track ALL pending enrichment futures so flush() can wait for completion.
_all_pending_futures: list = []
_pending_lock = threading.Lock()

# Loop detection: tracks recent write embeddings per agent (in-memory, no DB queries)
_repeat_tracker: dict = {}  # agent_id -> [{"embedding": ndarray, "time": float, "key": str}, ...]
_repeat_tracker_lock = threading.Lock()


@dataclass
class MemoryResult:
    node_id: Optional[int]
    key: str
    latency_us: float
    timestamp: float
    success: bool = True
    loop_warning: Optional[dict] = None


@dataclass
class SafeWriteResult:
    write: MemoryResult
    conflicts: dict

    @property
    def node_id(self):
        return self.write.node_id

    @property
    def success(self):
        return self.write.success

    @property
    def has_conflicts(self):
        return self.conflicts.get("has_conflicts", False)


@dataclass
class RecallResult:
    value: Any
    key: str
    latency_us: float
    found: bool


@dataclass
class SearchResult:
    items: list
    count: int
    latency_us: float

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def __len__(self):
        return len(self.items)

    def __bool__(self):
        return len(self.items) > 0


@dataclass
class SnapshotResult:
    label: str
    keys_captured: int
    latency_us: float
    size_bytes: int = 0


@dataclass
class RestoreResult:
    label: str
    keys_restored: int
    recovery_time_us: float


@dataclass
class HandoffResult:
    task_id: str
    latency_us: float
    success: bool = True


@dataclass
class TaskResult:
    task_id: str
    payload: dict
    latency_us: float
    found: bool = True


@dataclass
class HistoryResult:
    key: str
    versions: list
    current_version: int
    latency_us: float


@dataclass
class GraphResult:
    entity: str
    entity_type: str
    relationships: list
    latency_us: float
    found: bool


@dataclass
class AgentStats:
    agent_id: str
    total_operations: int = 0
    total_writes: int = 0
    total_reads: int = 0
    total_queries: int = 0
    avg_write_latency_us: float = 0.0
    avg_read_latency_us: float = 0.0
    crash_count: int = 0
    memory_node_count: int = 0
    performance_score: float = 100.0
    uptime_seconds: float = 0.0


class AgentRuntime:
    """
    The Synrix Agent Runtime.

    Usage:
        from synrix_runtime import AgentRuntime
        agent = AgentRuntime("my_agent", agent_type="researcher")
        agent.remember("user_preference", {"format": "bullet_points"})
        value = agent.recall("user_preference")
    """

    def __init__(self, agent_id: str, agent_type: str = "generic", metadata: dict = None,
                 backend_override=None, tenant_id: str = None, api_key: str = None,
                 require_account: bool = True):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.metadata = metadata or {}
        self.tenant_id = tenant_id or "_default"
        self._write_count = 0
        self._read_count = 0
        self._query_count = 0
        self._started_at = time.time()
        self._api_key = api_key

        # Account check — ensure user is authenticated
        # Skip if: backend is pre-injected (cloud server), or explicitly disabled
        if backend_override is None and require_account:
            try:
                from synrix_runtime.auth_flow import ensure_authenticated
                self._api_key = self._api_key or ensure_authenticated()
            except Exception as e:
                logger.debug("Auth flow error (non-fatal): %s", e)

        # Connect to Synrix — use pre-injected backend for tenant isolation,
        # or fall back to daemon's shared backend for local/SDK usage.
        start = time.perf_counter_ns()
        if backend_override is not None:
            # Tenant-isolated mode: skip daemon registration entirely to
            # prevent writing agent state to the shared global backend.
            self.backend = backend_override
            self._daemon = None
        else:
            try:
                from synrix_runtime.core.daemon import RuntimeDaemon
                self._daemon = RuntimeDaemon.get_instance()
                if not self._daemon.running:
                    self._daemon.start()
                # Reuse the daemon's backend so all agents share the same store
                self.backend = self._daemon.backend
                self._daemon.register_agent(agent_id, agent_type, self.metadata)
            except Exception:
                from synrix.agent_backend import get_synrix_backend
                from synrix_runtime.config import SynrixConfig
                config = SynrixConfig.from_env()
                self.backend = get_synrix_backend(**config.get_backend_kwargs())
                self._daemon = None
        connect_us = (time.perf_counter_ns() - start) / 1000

        # Initialize metrics collector (tenant-scoped)
        try:
            from synrix_runtime.monitoring.metrics import MetricsCollector
            self._metrics = MetricsCollector(self.backend, tenant_id=self.tenant_id)
        except Exception:
            self._metrics = None

        # Start heartbeat thread
        self._heartbeat_running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"heartbeat-{agent_id}", daemon=True
        )
        self._heartbeat_thread.start()

        # Track if running in local or cloud mode
        self._is_cloud = backend_override is not None and tenant_id != "_default"

        mode = "cloud" if self._is_cloud else "local"
        logger.info(f"[{agent_id}] Runtime connected in {connect_us:.1f}us | type={agent_type} | mode={mode}")
        if not self._is_cloud:
            logger.info("Running in local mode. For cloud dashboard, shared memory across machines, "
                       "and Brain intelligence: https://octopodas.com")

    def remember(self, key: str, value: Any, tags: list = None) -> MemoryResult:
        """Store a memory in Synrix.

        Fast path: writes to DB immediately (no embedding), returns in <10ms.
        Slow path (background): computes embedding, updates node, extracts facts.
        Semantic search finds the memory once background processing completes (~2-5s).
        """
        full_key = f"agents:{self.agent_id}:{key}"
        payload = value if isinstance(value, dict) else {"value": value}
        if tags:
            payload["_tags"] = tags

        # Extract text for background processing (cheap, no model needed)
        text_for_nlp = self._value_to_text(value)

        # Compute embedding NOW so memory is immediately searchable
        embedding = None
        if text_for_nlp and len(text_for_nlp.strip()) > 0:
            try:
                from synrix.embeddings import EmbeddingModel
                emb_model = EmbeddingModel.get()
                if emb_model:
                    embedding = emb_model.encode(text_for_nlp)
            except Exception as e:
                logger.error("Inline embedding error: %s", e)

        # Loop detection: check if this is a repeated write
        loop_warning = None
        if embedding is not None:
            try:
                loop_warning = self._check_write_loop(embedding, key)
            except Exception:
                pass

        # Write to DB with embedding (searchable immediately)
        start = time.perf_counter_ns()
        node_id = self.backend.write(
            full_key, payload,
            metadata={"type": "agent_memory", "agent_id": self.agent_id},
            embedding=embedding,
        )
        latency_us = (time.perf_counter_ns() - start) / 1000

        # SLOW PATH: embedding + fact extraction + NER all run in background
        if node_id is not None and text_for_nlp and len(text_for_nlp.strip()) > 0:
            def _enrich_background(backend, agent_id, nid, nkey, text, llm_config=None):
                # All writes in this function use _background=True to avoid
                # acquiring the Python-level _write_lock. SQLite WAL mode +
                # busy_timeout handles write serialization natively. This
                # prevents background enrichment from blocking foreground writes.

                # Step 1: Embedding already computed and stored during write.
                # Nothing to do here — memory is already searchable.

                # Step 2: LLM fact extraction → embed each fact for better search
                try:
                    from synrix.fact_extractor import FactExtractor
                    from synrix.embeddings import EmbeddingModel
                    safe_config = {k: ("***" if "key" in k.lower() or "secret" in k.lower() else v) for k, v in (llm_config or {}).items()}
                    logger.info("Fact extraction starting for node %s (config=%s)", nid, safe_config)
                    fact_extractor = FactExtractor.get(config=llm_config)
                    emb_model = EmbeddingModel.get()
                    if fact_extractor is None:
                        logger.warning("FactExtractor.get() returned None — no LLM available")
                    if emb_model is None:
                        logger.warning("EmbeddingModel.get() returned None")
                    if fact_extractor and emb_model:
                        fact_result = fact_extractor.extract_facts(text)
                        logger.info("Fact extraction result: %d facts, used_llm=%s, provider=%s, time=%.0fms",
                                   len(fact_result.facts), fact_result.used_llm, fact_result.provider, fact_result.extraction_time_ms)
                        if fact_result.facts:
                            fact_rows = []
                            for fact_text in fact_result.facts:
                                fact_emb = emb_model.encode(fact_text)
                                fact_rows.append({"text": fact_text, "embedding": fact_emb})
                            backend.store_fact_embeddings(
                                node_id=nid, node_name=nkey, facts=fact_rows,
                                _background=True,
                            )
                            logger.info("Stored %d facts for node %s (used_llm=%s)", len(fact_rows), nid, fact_result.used_llm)
                        else:
                            logger.warning("No facts extracted — provider=%s", fact_result.provider)
                except Exception as e:
                    logger.error("Fact extraction error: %s", e, exc_info=True)

                # Step 3: spaCy entity extraction → knowledge graph
                try:
                    from synrix.extractor import EntityExtractor
                    extractor = EntityExtractor.get()
                    if extractor:
                        result = extractor.extract(text)
                        self._store_extraction(result, nid, _background=True)
                except Exception:
                    pass

            # Load per-tenant LLM config if available
            _llm_config = getattr(self, '_llm_config', None)
            # Submit to bounded pool (max 4 concurrent) — extras queue, never explode
            future = _enrichment_pool.submit(
                _enrich_background,
                self.backend, self.agent_id, node_id, full_key, text_for_nlp, _llm_config,
            )
            # Track future globally so flush() can wait for all pending enrichment
            with _pending_lock:
                _all_pending_futures.append(future)
                # Prune completed futures to prevent unbounded memory growth
                if len(_all_pending_futures) > 100:
                    _all_pending_futures[:] = [f for f in _all_pending_futures if not f.done()]

        self._write_count += 1
        if self._metrics:
            self._metrics.record_write(self.agent_id, key, latency_us, node_id is not None, node_id)

        return MemoryResult(
            node_id=node_id,
            key=key,
            latency_us=latency_us,
            timestamp=time.time(),
            success=node_id is not None,
            loop_warning=loop_warning,
        )

    def flush(self, timeout: float = 120.0) -> dict:
        """Wait for ALL pending background enrichment to complete.

        Drains the global enrichment queue — all agents, not just this one.
        Call after a batch of writes to ensure embeddings/facts are ready for search.
        Returns stats about completed/failed/timed-out futures.
        """
        from concurrent.futures import wait
        with _pending_lock:
            # Grab all pending futures and clear the list
            futures = [f for f in _all_pending_futures if not f.done()]
            _all_pending_futures.clear()

        if not futures:
            return {"pending": 0, "completed": 0, "failed": 0, "timed_out": 0}

        done, not_done = wait(futures, timeout=timeout)
        completed = sum(1 for f in done if not f.exception())
        failed = sum(1 for f in done if f.exception())
        timed_out = len(not_done)

        for f in done:
            exc = f.exception()
            if exc:
                logger.error("Enrichment failed: %s", exc)

        return {
            "pending": len(futures),
            "completed": completed,
            "failed": failed,
            "timed_out": timed_out,
        }

    def _value_to_text(self, value: Any) -> Optional[str]:
        """Extract searchable text from a memory value."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            parts = []
            for k in ("value", "text", "content", "description", "message"):
                v = value.get(k)
                if isinstance(v, str):
                    parts.append(v)
            return " ".join(parts) if parts else json.dumps(value, default=str)
        return str(value) if value is not None else None

    def _store_extraction(self, extraction, source_node_id: int, _background: bool = False):
        """Store extracted entities and relationships in the knowledge graph.

        Args:
            _background: If True, skip Python write lock on SQLite operations.
                         Used by background enrichment to avoid blocking foreground writes.
        """
        entity_ids = {}
        for ent_name, ent_type in extraction.entities:
            eid = self.backend.add_entity(
                name=ent_name, entity_type=ent_type,
                source_node_id=source_node_id,
                _background=_background,
            )
            if eid is not None:
                entity_ids[ent_name] = eid

        for subj, rel, obj in extraction.relationships:
            src_id = entity_ids.get(subj)
            tgt_id = entity_ids.get(obj)
            if src_id is None:
                src_id = self.backend.add_entity(
                    name=subj, entity_type="UNKNOWN",
                    source_node_id=source_node_id,
                    _background=_background,
                )
                if src_id:
                    entity_ids[subj] = src_id
            if tgt_id is None:
                tgt_id = self.backend.add_entity(
                    name=obj, entity_type="UNKNOWN",
                    source_node_id=source_node_id,
                    _background=_background,
                )
                if tgt_id:
                    entity_ids[obj] = tgt_id
            if src_id and tgt_id:
                self.backend.add_relationship(
                    source_entity_id=src_id, target_entity_id=tgt_id,
                    relation=rel, source_node_id=source_node_id,
                    _background=_background,
                )

    def recall(self, key: str) -> RecallResult:
        """Recall a memory from Synrix."""
        full_key = f"agents:{self.agent_id}:{key}"

        start = time.perf_counter_ns()
        result = self.backend.read(full_key)
        latency_us = (time.perf_counter_ns() - start) / 1000

        found = result is not None
        value = None
        if result:
            data = result.get("data", {})
            value = data.get("value", data)
            # Unwrap double-wrapped values: {'value': X, '_tags': [...]} -> X
            # Strip internal keys (starting with _) then unwrap if only 'value' remains
            if isinstance(value, dict) and "value" in value:
                non_internal = {k: v for k, v in value.items() if not k.startswith("_")}
                if len(non_internal) == 1 and "value" in non_internal:
                    value = value["value"]

        self._read_count += 1
        if self._metrics:
            self._metrics.record_read(self.agent_id, key, latency_us, found)

        return RecallResult(value=value, key=key, latency_us=latency_us, found=found)

    def search(self, prefix: str, limit: int = 50) -> SearchResult:
        """Search agent memory by prefix."""
        full_prefix = f"agents:{self.agent_id}:{prefix}" if prefix else f"agents:{self.agent_id}:"

        start = time.perf_counter_ns()
        results = self.backend.query_prefix(full_prefix, limit=limit)
        latency_us = (time.perf_counter_ns() - start) / 1000

        items = []
        for r in results:
            key = r.get("key", "")
            # Strip the agent prefix for cleaner results
            short_key = key.replace(f"agents:{self.agent_id}:", "", 1)
            data = r.get("data", {})
            value = data.get("value", data)
            items.append({"key": short_key, "value": value, "node_id": r.get("id")})

        self._query_count += 1
        if self._metrics:
            self._metrics.record_query(self.agent_id, prefix, latency_us, len(items))

        return SearchResult(items=items, count=len(items), latency_us=latency_us)

    def recall_similar(self, query: str, limit: int = 10) -> SearchResult:
        """Search agent memories by semantic similarity.

        Requires sentence-transformers to be installed.
        Returns empty results if embeddings are not available.
        """
        start = time.perf_counter_ns()
        # Search scoped to this agent's data only via SQL prefix filter
        agent_prefix = f"agents:{self.agent_id}:"
        results = self.backend.semantic_search(
            query, limit=limit, name_prefix=agent_prefix
        )
        latency_us = (time.perf_counter_ns() - start) / 1000

        items = []
        for r in results:
            key = r.get("key", "")
            short_key = key.replace(agent_prefix, "", 1)
            data = r.get("data", {})
            value = data.get("value", data)
            entry = {
                "key": short_key,
                "value": value,
                "score": r.get("score", 0.0),
                "node_id": r.get("id"),
            }
            if "matched_fact" in r:
                entry["matched_fact"] = r["matched_fact"]
            items.append(entry)

        self._query_count += 1
        return SearchResult(items=items, count=len(items), latency_us=latency_us)

    def recall_history(self, key: str) -> HistoryResult:
        """Get the full temporal history of a memory key.

        Returns all versions including when they were valid.
        """
        full_key = f"agents:{self.agent_id}:{key}"

        start = time.perf_counter_ns()
        results = self.backend.get_history(full_key)
        latency_us = (time.perf_counter_ns() - start) / 1000

        versions = []
        current_version = 0
        for r in results:
            data = r.get("data", {})
            value = data.get("value", data)
            # Unwrap double-nested {"value": "actual_value"} from remember()
            if isinstance(value, dict) and "value" in value and len(value) == 1:
                value = value["value"]
            v = r.get("version", 1)
            if v > current_version:
                current_version = v
            versions.append({
                "value": value,
                "version": v,
                "valid_from": r.get("valid_from"),
                "valid_until": r.get("valid_until"),
            })

        self._read_count += 1
        return HistoryResult(
            key=key, versions=versions,
            current_version=current_version, latency_us=latency_us,
        )

    def related(self, entity_name: str) -> GraphResult:
        """Query the knowledge graph for an entity and its relationships."""
        start = time.perf_counter_ns()
        result = self.backend.query_entity(entity_name)
        latency_us = (time.perf_counter_ns() - start) / 1000

        if result is None:
            return GraphResult(
                entity=entity_name, entity_type="",
                relationships=[], latency_us=latency_us, found=False,
            )

        return GraphResult(
            entity=result["name"],
            entity_type=result["entity_type"],
            relationships=result.get("relationships", []),
            latency_us=latency_us,
            found=True,
        )

    # -----------------------------------------------------------------
    # TTL / Auto-Expire
    # -----------------------------------------------------------------

    def remember_with_ttl(self, key: str, value: Any, ttl_seconds: int,
                          tags: list = None) -> MemoryResult:
        """Store a memory that auto-expires after ttl_seconds.

        The memory is written normally but tagged with an expiry timestamp.
        Expired memories are filtered out on read and cleaned up periodically.
        """
        if tags is None:
            tags = []
        tags.append("__ttl")

        # Wrap value with expiry metadata
        expires_at = time.time() + ttl_seconds
        if isinstance(value, dict):
            value = {**value, "__expires_at": expires_at, "__ttl_seconds": ttl_seconds}
        else:
            value = {"value": value, "__expires_at": expires_at, "__ttl_seconds": ttl_seconds}

        return self.remember(key, value, tags=tags)

    def cleanup_expired(self) -> dict:
        """Remove all expired TTL memories for this agent. Returns count deleted."""
        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=10000)
        now = time.time()
        deleted = 0
        for item in all_items:
            data = item.get("data", {})
            # Unwrap nested value dicts to find __expires_at at any depth
            val = data.get("value", data)
            if isinstance(val, dict) and "value" in val and isinstance(val["value"], dict):
                val = val["value"]  # unwrap double-wrapped values
            if isinstance(val, dict) and "__expires_at" in val:
                if val["__expires_at"] < now:
                    key = item.get("key", "")
                    try:
                        self.backend.delete(key)
                        deleted += 1
                    except Exception:
                        pass
            # Also check top-level data for __expires_at
            elif isinstance(data, dict) and "__expires_at" in data:
                if data["__expires_at"] < now:
                    key = item.get("key", "")
                    try:
                        self.backend.delete(key)
                        deleted += 1
                    except Exception:
                        pass
        return {"deleted": deleted, "agent_id": self.agent_id}

    # -----------------------------------------------------------------
    # Memory Importance Scoring
    # -----------------------------------------------------------------

    def remember_important(self, key: str, value: Any, importance: str = "normal",
                           tags: list = None) -> MemoryResult:
        """Store a memory with importance level: critical, normal, or low.

        Critical memories are boosted in search results.
        """
        if importance not in ("critical", "normal", "low"):
            importance = "normal"
        if tags is None:
            tags = []
        tags.append(f"__importance:{importance}")

        if isinstance(value, dict):
            value = {**value, "__importance": importance}
        else:
            value = {"value": value, "__importance": importance}

        return self.remember(key, value, tags=tags)

    # -----------------------------------------------------------------
    # Conflict Detection
    # -----------------------------------------------------------------

    def detect_conflicts(self, key: str, new_value: Any, threshold: float = 0.7) -> dict:
        """Check if a new memory contradicts existing memories.

        Uses semantic similarity to find potentially conflicting information.
        Returns conflicts found with similarity scores.

        Args:
            key: The key being written
            new_value: The new value to check
            threshold: Similarity threshold (0-1) to flag as potential conflict

        Returns:
            dict with 'conflicts' list and 'has_conflicts' bool
        """
        text = self._value_to_text(new_value)
        if not text:
            return {"has_conflicts": False, "conflicts": []}

        # Search for semantically similar existing memories (scoped to this agent)
        agent_prefix = f"agents:{self.agent_id}:"
        try:
            results = self.backend.semantic_search(
                text, limit=20, name_prefix=agent_prefix
            )
        except Exception:
            return {"has_conflicts": False, "conflicts": []}

        conflicts = []
        full_key = f"agents:{self.agent_id}:{key}"
        same_key_exists = False
        for r in results:
            existing_key = r.get("key", "")
            existing_data = r.get("data", {})
            existing_val = existing_data.get("value", existing_data)
            # Check if the same key already has a value (overwrite detection)
            if existing_key == full_key:
                same_key_exists = True
                conflicts.append({
                    "existing_key": key,
                    "existing_value": existing_val,
                    "similarity_score": 1.0,
                    "conflict_type": "key_overwrite",
                    "message": f"Key '{key}' already exists and will be overwritten",
                    "matched_fact": r.get("matched_fact"),
                })
                continue
            score = r.get("score", 0)
            if score >= threshold:
                conflicts.append({
                    "existing_key": existing_key.replace(f"agents:{self.agent_id}:", "", 1),
                    "existing_value": existing_val,
                    "similarity_score": score,
                    "conflict_type": "semantic_similarity",
                    "matched_fact": r.get("matched_fact"),
                })

        # Also check key existence even if not in semantic results
        if not same_key_exists:
            try:
                existing = self.backend.read(full_key)
                if existing:
                    existing_data = existing.get("data", {})
                    existing_val = existing_data.get("value", existing_data)
                    conflicts.insert(0, {
                        "existing_key": key,
                        "existing_value": existing_val,
                        "similarity_score": 1.0,
                        "conflict_type": "key_overwrite",
                        "message": f"Key '{key}' already exists and will be overwritten",
                    })
            except Exception:
                pass

        return {
            "has_conflicts": len(conflicts) > 0,
            "conflicts": conflicts,
            "new_key": key,
            "checked_against": len(results),
        }

    def remember_safe(self, key: str, value: Any, tags: list = None,
                      conflict_threshold: float = 0.85) -> SafeWriteResult:
        """Write a memory but warn if it conflicts with existing memories.

        Returns a SafeWriteResult with the write result plus any detected conflicts.
        """
        conflict_check = self.detect_conflicts(key, value, threshold=conflict_threshold)
        result = self.remember(key, value, tags=tags)
        return SafeWriteResult(write=result, conflicts=conflict_check)

    # -----------------------------------------------------------------
    # Automatic Loop Detection
    # -----------------------------------------------------------------

    def _check_write_loop(self, embedding, key: str) -> Optional[dict]:
        """Check if this write is part of a repetitive loop.

        Compares the new embedding against recent writes (in-memory, no DB query).
        Returns a warning dict if 3+ similar writes detected in 5 minutes, else None.
        """
        try:
            import numpy as np
        except ImportError:
            return None

        now = time.time()
        cutoff = now - 300  # 5-minute window
        threshold = 0.92

        # Use tenant-scoped key to prevent cross-tenant repeat detection
        tracker_key = f"{self.tenant_id}:{self.agent_id}"

        with _repeat_tracker_lock:
            entries = _repeat_tracker.get(tracker_key, [])
            # Prune old entries
            entries = [e for e in entries if e["time"] >= cutoff]

            # Compare new embedding against recent ones
            similar_count = 0
            emb_array = np.frombuffer(embedding, dtype=np.float32) if isinstance(embedding, bytes) else np.array(embedding, dtype=np.float32)
            norm = np.linalg.norm(emb_array)
            if norm > 0:
                emb_array = emb_array / norm

            for entry in entries:
                prev = entry["embedding"]
                score = float(np.dot(emb_array, prev))
                if score >= threshold:
                    similar_count += 1

            # Add current embedding to tracker
            entries.append({"embedding": emb_array, "time": now, "key": key})
            # Keep max 20 entries per agent
            if len(entries) > 20:
                entries = entries[-20:]
            _repeat_tracker[tracker_key] = entries

        if similar_count >= 2:  # Current + 2 previous = 3 similar writes
            # Write anomaly alert
            try:
                ts = int(now * 1000000)
                self.backend.write(
                    f"alerts:{self.agent_id}:{ts}",
                    {
                        "agent_id": self.agent_id,
                        "type": "repeat_loop",
                        "severity": "warning",
                        "detail": f"Agent stored similar content {similar_count + 1} times in 5 minutes (key: {key})",
                        "current_value": similar_count + 1,
                        "threshold": 3,
                        "timestamp": now,
                    },
                    metadata={"type": "anomaly_alert"},
                )
            except Exception:
                pass
            return {
                "type": "repeat_loop",
                "message": f"Repeated write detected: {similar_count + 1} similar stores in 5 minutes",
                "repeat_count": similar_count + 1,
            }
        return None

    def _check_decision_loop(self, decision: str, reasoning: str) -> Optional[dict]:
        """Check if this decision repeats a recent one.

        Queries last 5 decisions and compares semantically.
        Returns a warning dict if a similar decision was made in 10 minutes, else None.
        """
        now = time.time()
        cutoff = now - 600  # 10-minute window

        try:
            from synrix.embeddings import EmbeddingModel
            import numpy as np

            emb_model = EmbeddingModel.get()
            if not emb_model:
                return None

            # Embed the new decision
            decision_text = f"{decision} {reasoning}"
            new_emb = emb_model.encode(decision_text)
            if isinstance(new_emb, bytes):
                new_vec = np.frombuffer(new_emb, dtype=np.float32)
            else:
                new_vec = np.array(new_emb, dtype=np.float32)
            norm = np.linalg.norm(new_vec)
            if norm > 0:
                new_vec = new_vec / norm

            # Get recent decisions from audit trail
            recent = self.backend.query_prefix(f"audit:{self.agent_id}:", limit=5)
            for item in recent:
                data = item.get("data", {})
                val = data.get("value", data)
                if not isinstance(val, dict):
                    try:
                        val = json.loads(val) if isinstance(val, str) else {}
                    except Exception:
                        continue

                ts = val.get("timestamp", 0)
                if ts < cutoff:
                    continue

                prev_decision = val.get("decision", "")
                prev_reasoning = val.get("reasoning", "")
                if not prev_decision:
                    continue

                prev_text = f"{prev_decision} {prev_reasoning}"
                prev_emb = emb_model.encode(prev_text)
                if isinstance(prev_emb, bytes):
                    prev_vec = np.frombuffer(prev_emb, dtype=np.float32)
                else:
                    prev_vec = np.array(prev_emb, dtype=np.float32)
                prev_norm = np.linalg.norm(prev_vec)
                if prev_norm > 0:
                    prev_vec = prev_vec / prev_norm

                score = float(np.dot(new_vec, prev_vec))
                if score >= 0.90:
                    # Write anomaly alert
                    try:
                        alert_ts = int(now * 1000000)
                        self.backend.write(
                            f"alerts:{self.agent_id}:{alert_ts}",
                            {
                                "agent_id": self.agent_id,
                                "type": "decision_loop",
                                "severity": "warning",
                                "detail": f"Agent repeated decision: '{decision[:80]}' (similarity: {score:.2f})",
                                "current_value": score,
                                "threshold": 0.90,
                                "timestamp": now,
                            },
                            metadata={"type": "anomaly_alert"},
                        )
                    except Exception:
                        pass
                    return {
                        "type": "decision_loop",
                        "message": f"Repeated decision detected (similarity: {score:.2f})",
                        "similarity": score,
                        "previous_decision": prev_decision[:100],
                    }
        except Exception as e:
            logger.debug("Decision loop check error: %s", e)
        return None

    # -----------------------------------------------------------------
    # Advanced Loop Detection v2
    # -----------------------------------------------------------------

    def get_loop_status(self) -> dict:
        """Get comprehensive loop detection status for this agent.

        Combines multiple signals into a single intelligence report:
        - Write loops (repeated similar content)
        - Key overwrite loops (same key written repeatedly)
        - Decision loops (same decisions repeated)
        - Error patterns (same errors recurring)
        - Velocity anomalies (sudden bursts of writes)

        Returns a severity level (green/yellow/orange/red) with
        actionable suggestions for each detected pattern.

        This is the single endpoint a dashboard or monitoring system
        needs to check for loop health.
        """
        now = time.time()
        tracker_key = f"{self.tenant_id}:{self.agent_id}"
        signals = []
        severity = "green"
        score = 100  # Start at 100, deduct for each issue

        # --- Signal 1: Write embedding similarity (existing, enhanced) ---
        with _repeat_tracker_lock:
            entries = _repeat_tracker.get(tracker_key, [])
            recent_entries = [e for e in entries if e["time"] >= (now - 300)]

        if len(recent_entries) >= 3:
            try:
                import numpy as np
                # Check pairwise similarity of recent writes
                high_sim_pairs = 0
                total_pairs = 0
                for i in range(len(recent_entries)):
                    for j in range(i + 1, len(recent_entries)):
                        score_ij = float(np.dot(recent_entries[i]["embedding"],
                                               recent_entries[j]["embedding"]))
                        total_pairs += 1
                        if score_ij >= 0.88:
                            high_sim_pairs += 1

                if total_pairs > 0:
                    sim_ratio = high_sim_pairs / total_pairs
                    if sim_ratio > 0.7:
                        score -= 30
                        signals.append({
                            "type": "write_similarity",
                            "severity": "red" if sim_ratio > 0.85 else "orange",
                            "detail": f"{high_sim_pairs}/{total_pairs} recent write pairs are semantically similar (>{sim_ratio:.0%})",
                            "suggestion": "Agent is storing the same information repeatedly. Check if the agent is stuck in a retry loop or if the prompt is causing redundant memory writes.",
                            "action": "Call agent.consolidate() to merge duplicates, or agent.forget_stale() to clean up.",
                        })
                    elif sim_ratio > 0.4:
                        score -= 15
                        signals.append({
                            "type": "write_similarity",
                            "severity": "yellow",
                            "detail": f"{high_sim_pairs}/{total_pairs} recent writes are moderately similar",
                            "suggestion": "Some repetition detected. Not critical yet but worth monitoring.",
                            "action": "Monitor — may resolve naturally or escalate.",
                        })
            except ImportError:
                pass

        # --- Signal 2: Key overwrite frequency ---
        with _repeat_tracker_lock:
            recent_keys = [e.get("key", "") for e in recent_entries]
        key_counts = {}
        for k in recent_keys:
            key_counts[k] = key_counts.get(k, 0) + 1
        hot_keys = {k: v for k, v in key_counts.items() if v >= 3}
        if hot_keys:
            worst_key = max(hot_keys, key=hot_keys.get)
            worst_count = hot_keys[worst_key]
            score -= min(25, worst_count * 5)
            signals.append({
                "type": "key_overwrite",
                "severity": "red" if worst_count >= 5 else "orange",
                "detail": f"Key '{worst_key}' overwritten {worst_count} times in 5 minutes",
                "hot_keys": hot_keys,
                "suggestion": f"Agent is repeatedly overwriting the same key. This usually means the agent is trying to 'fix' a value but not succeeding, or the write is inside an unintended loop.",
                "action": f"Check the agent's logic around key '{worst_key}'. Consider using remember_with_ttl() for temporary values.",
            })

        # --- Signal 3: Write velocity (burst detection) ---
        with _repeat_tracker_lock:
            last_60s = [e for e in entries if e["time"] >= (now - 60)]
            last_300s = [e for e in entries if e["time"] >= (now - 300)]
        writes_per_minute = len(last_60s)
        writes_per_5min = len(last_300s)
        if writes_per_minute >= 10:
            score -= 20
            signals.append({
                "type": "velocity_spike",
                "severity": "red",
                "detail": f"{writes_per_minute} writes in the last 60 seconds ({writes_per_5min} in 5 minutes)",
                "suggestion": "Extremely high write velocity. Agent is likely stuck in a tight loop writing rapidly.",
                "action": "Pause the agent immediately. Check for infinite loops in the agent logic.",
            })
        elif writes_per_minute >= 5:
            score -= 10
            signals.append({
                "type": "velocity_spike",
                "severity": "orange",
                "detail": f"{writes_per_minute} writes in the last 60 seconds",
                "suggestion": "High write velocity. May be normal for batch operations, but could indicate a loop.",
                "action": "Check if this is intentional batch processing or an unintended loop.",
            })

        # --- Signal 4: Recent alerts history ---
        try:
            alerts = self.backend.query_prefix(f"alerts:{self.agent_id}:", limit=20)
            recent_alerts = []
            for a in alerts:
                data = a.get("data", {})
                val = data.get("value", data)
                if isinstance(val, dict):
                    alert_time = val.get("timestamp", 0)
                    if alert_time >= (now - 3600):  # Last hour
                        recent_alerts.append(val)

            if len(recent_alerts) >= 5:
                score -= 20
                alert_types = {}
                for al in recent_alerts:
                    t = al.get("type", "unknown")
                    alert_types[t] = alert_types.get(t, 0) + 1
                signals.append({
                    "type": "alert_frequency",
                    "severity": "red" if len(recent_alerts) >= 10 else "orange",
                    "detail": f"{len(recent_alerts)} anomaly alerts in the last hour",
                    "alert_breakdown": alert_types,
                    "suggestion": "Persistent loop behavior. The agent has triggered multiple loop warnings without recovery.",
                    "action": "Agent needs intervention. Consider: 1) Restart with a different prompt, 2) Clear recent memories with forget_stale(), 3) Restore from a known-good snapshot.",
                })
        except Exception:
            pass

        # --- Signal 5: Goal drift (if goal is set) ---
        try:
            goal_result = self.backend.read(f"agents:{self.agent_id}:goal:current")
            goal_emb_result = self.backend.read(f"agents:{self.agent_id}:goal:embedding")
            if goal_result and goal_emb_result and recent_entries:
                import numpy as np
                goal_data = goal_emb_result.get("data", {})
                goal_val = goal_data.get("value", goal_data)
                if isinstance(goal_val, dict) and "embedding" in goal_val:
                    goal_vec = np.array(goal_val["embedding"], dtype=np.float32)
                    goal_norm = np.linalg.norm(goal_vec)
                    if goal_norm > 0:
                        goal_vec = goal_vec / goal_norm

                    # Compare recent writes against goal
                    drift_scores = []
                    for entry in recent_entries[-5:]:
                        drift_score = float(np.dot(entry["embedding"], goal_vec))
                        drift_scores.append(drift_score)

                    if drift_scores:
                        avg_drift = sum(drift_scores) / len(drift_scores)
                        if avg_drift < 0.3:
                            score -= 20
                            goal_text = goal_result.get("data", {}).get("value", {})
                            if isinstance(goal_text, dict):
                                goal_text = goal_text.get("goal", "")
                            signals.append({
                                "type": "goal_drift",
                                "severity": "red" if avg_drift < 0.2 else "orange",
                                "detail": f"Recent writes have {avg_drift:.0%} relevance to the agent's goal",
                                "goal": str(goal_text)[:100] if goal_text else "unknown",
                                "suggestion": "Agent's recent activity is diverging from its stated goal. It may be distracted or stuck on a tangent.",
                                "action": "Review the agent's recent decisions. Consider calling update_progress() to refocus, or set a new sub-goal.",
                            })
        except Exception:
            pass

        # --- Calculate overall severity ---
        score = max(0, score)
        if score >= 80:
            severity = "green"
        elif score >= 60:
            severity = "yellow"
        elif score >= 35:
            severity = "orange"
        else:
            severity = "red"

        # --- Build recovery suggestions based on severity ---
        recovery = []
        if severity == "red":
            recovery = [
                "IMMEDIATE: Pause or restart the agent",
                "Run agent.consolidate() to remove duplicate memories",
                "Run agent.forget_stale() to clean old memories",
                "Check agent prompt for unintended loop patterns",
                "Consider restoring from snapshot: agent.restore()",
            ]
        elif severity == "orange":
            recovery = [
                "Monitor closely for the next few minutes",
                "Run agent.memory_health() for a full diagnostic",
                "Consider running agent.consolidate(dry_run=True) to check for duplicates",
            ]
        elif severity == "yellow":
            recovery = [
                "No immediate action needed",
                "Run agent.memory_health() periodically to track trends",
            ]

        return {
            "agent_id": self.agent_id,
            "severity": severity,
            "score": score,
            "signals": signals,
            "signal_count": len(signals),
            "recovery_suggestions": recovery,
            "recent_writes_5min": writes_per_5min if 'writes_per_5min' in dir() else 0,
            "recent_writes_1min": writes_per_minute if 'writes_per_minute' in dir() else 0,
            "checked_at": now,
        }

    def get_loop_history(self, hours: int = 24) -> dict:
        """Get loop detection history for this agent over time.

        Shows how loop behavior has evolved, helping identify patterns
        like "loops every time the agent runs task X" or "loops after
        memory exceeds N entries".
        """
        cutoff = time.time() - (hours * 3600)
        alerts = self.backend.query_prefix(f"alerts:{self.agent_id}:", limit=500)

        history = []
        type_counts = {}
        hourly_buckets = {}

        for a in alerts:
            data = a.get("data", {})
            val = data.get("value", data)
            if not isinstance(val, dict):
                continue
            ts = val.get("timestamp", 0)
            if ts < cutoff:
                continue

            alert_type = val.get("type", "unknown")
            type_counts[alert_type] = type_counts.get(alert_type, 0) + 1

            hour_key = time.strftime("%Y-%m-%d %H:00", time.localtime(ts))
            hourly_buckets[hour_key] = hourly_buckets.get(hour_key, 0) + 1

            history.append({
                "type": alert_type,
                "severity": val.get("severity", "unknown"),
                "detail": val.get("detail", ""),
                "timestamp": ts,
                "time_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            })

        history.sort(key=lambda x: x["timestamp"], reverse=True)

        # Detect recurring patterns
        patterns = []
        if type_counts.get("repeat_loop", 0) >= 5:
            patterns.append("Persistent write repetition — agent consistently stores similar content")
        if type_counts.get("decision_loop", 0) >= 3:
            patterns.append("Decision cycling — agent keeps making the same decision")
        if len(hourly_buckets) > 1:
            counts = list(hourly_buckets.values())
            if max(counts) > 3 * (sum(counts) / len(counts)):
                worst_hour = max(hourly_buckets, key=hourly_buckets.get)
                patterns.append(f"Spike detected at {worst_hour} — investigate what triggered the burst")

        return {
            "agent_id": self.agent_id,
            "hours_analyzed": hours,
            "total_alerts": len(history),
            "by_type": type_counts,
            "by_hour": hourly_buckets,
            "patterns_detected": patterns,
            "recent_alerts": history[:20],
        }

    # -----------------------------------------------------------------
    # Usage Analytics
    # -----------------------------------------------------------------

    def usage_analytics(self) -> dict:
        """Get detailed usage analytics for this agent.

        Returns memory count, most accessed keys, storage breakdown, etc.
        """
        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=10000)

        total_memories = 0
        total_size_bytes = 0
        tags_count = {}
        importance_breakdown = {"critical": 0, "normal": 0, "low": 0}
        ttl_count = 0
        expired_count = 0
        now = time.time()

        for item in all_items:
            key = item.get("key", "")
            if ":snapshots:" in key:
                continue
            total_memories += 1
            data = item.get("data", {})
            total_size_bytes += len(json.dumps(data, default=str).encode())

            val = data.get("value", data)
            if isinstance(val, dict):
                # Check importance
                imp = val.get("__importance", "normal")
                if imp in importance_breakdown:
                    importance_breakdown[imp] += 1
                else:
                    importance_breakdown["normal"] += 1

                # Check TTL
                if "__expires_at" in val:
                    ttl_count += 1
                    if val["__expires_at"] < now:
                        expired_count += 1

                # Count tags
                tags = val.get("_tags", [])
                for tag in tags:
                    if not tag.startswith("__"):
                        tags_count[tag] = tags_count.get(tag, 0) + 1

        return {
            "agent_id": self.agent_id,
            "total_memories": total_memories,
            "total_size_bytes": total_size_bytes,
            "total_size_human": f"{total_size_bytes / 1024:.1f} KB" if total_size_bytes < 1048576 else f"{total_size_bytes / 1048576:.1f} MB",
            "importance": importance_breakdown,
            "ttl_memories": ttl_count,
            "expired_memories": expired_count,
            "top_tags": dict(sorted(tags_count.items(), key=lambda x: -x[1])[:10]),
            "writes": self._write_count,
            "reads": self._read_count,
            "queries": self._query_count,
            "uptime_seconds": time.time() - self._started_at,
        }

    def snapshot(self, label: str = None) -> SnapshotResult:
        """Take a snapshot of all current memory."""
        if label is None:
            label = f"snap_{int(time.time()*1000000)}"

        start = time.perf_counter_ns()

        # Get all current memory keys
        all_keys = self.backend.query_prefix(f"agents:{self.agent_id}:", limit=500)
        snapshot_data = {}
        for item in all_keys:
            key = item.get("key", "")
            if ":snapshots:" not in key:
                data = item.get("data", {})
                snapshot_data[key] = data.get("value", data)

        # Write snapshot — use _background=True to avoid blocking on _write_lock
        # during heavy enrichment periods
        snapshot_payload = {
            "label": label,
            "agent_id": self.agent_id,
            "keys": snapshot_data,
            "key_count": len(snapshot_data),
            "created_at": time.time(),
        }
        size_bytes = len(json.dumps(snapshot_payload).encode())
        try:
            raw_client = self.backend.client
            raw_client.add_node(
                name=f"agents:{self.agent_id}:snapshots:{label}",
                data=json.dumps(snapshot_payload),
                collection=self.backend.collection,
                node_type="snapshot",
                metadata={"type": "snapshot", "agent_id": self.agent_id},
                _background=True,
            )
        except Exception as e:
            logger.warning("Snapshot write with _background failed (%s), retrying normal", e)
            self.backend.write(
                f"agents:{self.agent_id}:snapshots:{label}",
                snapshot_payload,
                metadata={"type": "snapshot", "agent_id": self.agent_id}
            )
        latency_us = (time.perf_counter_ns() - start) / 1000

        if self._metrics:
            self._metrics.record_snapshot(self.agent_id, label, len(snapshot_data), latency_us)

        return SnapshotResult(
            label=label,
            keys_captured=len(snapshot_data),
            latency_us=latency_us,
            size_bytes=size_bytes,
        )

    def restore(self, label: str = None) -> RestoreResult:
        """Restore from a named snapshot or the latest one."""
        start = time.perf_counter_ns()

        if label:
            result = self.backend.read(f"agents:{self.agent_id}:snapshots:{label}")
        else:
            # Find latest snapshot
            snapshots = self.backend.query_prefix(f"agents:{self.agent_id}:snapshots:", limit=50)
            if not snapshots:
                return RestoreResult(label="none", keys_restored=0, recovery_time_us=0)
            snapshots.sort(key=lambda x: x.get("data", {}).get("value", {}).get("created_at", 0)
                          if isinstance(x.get("data", {}).get("value"), dict)
                          else x.get("data", {}).get("timestamp", 0), reverse=True)
            result = snapshots[0]
            data = result.get("data", {})
            val = data.get("value", data)
            label = val.get("label", "unknown") if isinstance(val, dict) else "unknown"

        if result is None:
            return RestoreResult(label=label or "none", keys_restored=0, recovery_time_us=0)

        # Extract snapshot data
        data = result.get("data", {})
        val = data.get("value", data)
        keys_data = val.get("keys", {}) if isinstance(val, dict) else {}

        # Purge keys created after the snapshot that aren't in it
        agent_prefix = f"agents:{self.agent_id}:"
        try:
            current_keys = self.backend.query_prefix(agent_prefix, limit=100000)
            snapshot_keys = set(keys_data.keys())
            for item in current_keys:
                key = item.get("key", "")
                # Don't delete snapshots or runtime metadata
                if ":snapshots:" in key or key.startswith(f"runtime:agents:{self.agent_id}:"):
                    continue
                if key not in snapshot_keys:
                    try:
                        self.backend.delete(key)
                    except Exception:
                        pass
        except Exception:
            pass

        # Restore each key — use raw client with _background=True to avoid
        # blocking on _write_lock during heavy enrichment periods
        restored = 0
        raw_client = self.backend.client
        for key, value in keys_data.items():
            try:
                raw_client.add_node(
                    name=key,
                    data=json.dumps(value) if isinstance(value, dict) else json.dumps({"value": value}),
                    collection=self.backend.collection,
                    node_type="memory",
                    metadata={"type": "restored", "agent_id": self.agent_id},
                    _background=True,
                )
            except Exception:
                # Fallback to normal write if _background fails
                self.backend.write(key, value, metadata={"type": "restored", "agent_id": self.agent_id})
            restored += 1

        recovery_us = (time.perf_counter_ns() - start) / 1000

        if self._metrics:
            self._metrics.record_recovery(self.agent_id, recovery_us, restored)

        return RestoreResult(label=label, keys_restored=restored, recovery_time_us=recovery_us)

    def share(self, key: str, value: Any, space: str = "global") -> MemoryResult:
        """Write to shared memory space."""
        full_key = f"shared:{space}:{key}"
        payload = value if isinstance(value, dict) else {"value": value}
        payload["_author"] = self.agent_id
        payload["_shared_at"] = time.time()

        start = time.perf_counter_ns()
        node_id = self.backend.write(full_key, payload, metadata={"type": "shared_memory", "space": space, "author": self.agent_id})
        latency_us = (time.perf_counter_ns() - start) / 1000

        # Write changelog
        ts = int(time.time() * 1000000)
        self.backend.write(
            f"shared:{space}:changelog:{ts}",
            {"key": key, "author": self.agent_id, "action": "write", "timestamp": time.time()},
            metadata={"type": "shared_changelog"}
        )

        self._write_count += 1
        if self._metrics:
            self._metrics.record_write(self.agent_id, f"shared:{space}:{key}", latency_us, True, node_id)

        return MemoryResult(node_id=node_id, key=key, latency_us=latency_us, timestamp=time.time())

    def read_shared(self, key: str, space: str = "global") -> RecallResult:
        """Read from shared memory space."""
        full_key = f"shared:{space}:{key}"

        start = time.perf_counter_ns()
        result = self.backend.read(full_key)
        latency_us = (time.perf_counter_ns() - start) / 1000

        found = result is not None
        value = None
        if result:
            data = result.get("data", {})
            value = data.get("value", data)

        self._read_count += 1
        if self._metrics:
            self._metrics.record_read(self.agent_id, f"shared:{space}:{key}", latency_us, found)

        return RecallResult(value=value, key=key, latency_us=latency_us, found=found)

    def subscribe_shared(self, space: str, callback: callable):
        """Poll a shared space for new keys and call callback on changes."""
        seen_keys = set()

        def _poll():
            while self._heartbeat_running:
                try:
                    results = self.backend.query_prefix(f"shared:{space}:", limit=200)
                    for r in results:
                        key = r.get("key", "")
                        if key not in seen_keys:
                            seen_keys.add(key)
                            data = r.get("data", {})
                            value = data.get("value", data)
                            try:
                                callback(key, value)
                            except Exception:
                                pass
                except Exception:
                    pass
                time.sleep(1)

        t = threading.Thread(target=_poll, name=f"sub-{space}-{self.agent_id}", daemon=True)
        t.start()

    def handoff(self, task_id: str, to_agent: str, payload: dict) -> HandoffResult:
        """Hand off a task to another agent."""
        handoff_data = {
            "task_id": task_id,
            "from_agent": self.agent_id,
            "to_agent": to_agent,
            "payload": payload,
            "status": "pending",
            "created_at": time.time(),
        }

        start = time.perf_counter_ns()
        self.backend.write(
            f"tasks:handoff:{task_id}",
            handoff_data,
            metadata={"type": "task_handoff", "from": self.agent_id, "to": to_agent}
        )
        latency_us = (time.perf_counter_ns() - start) / 1000

        # Audit event
        try:
            from synrix_runtime.monitoring.audit import AuditSystem
            audit = AuditSystem(self.backend)
            audit.log_handoff(self.agent_id, to_agent, task_id, payload, {})
        except Exception:
            pass

        if self._metrics:
            self._metrics.record_handoff(self.agent_id, to_agent, task_id, latency_us)

        return HandoffResult(task_id=task_id, latency_us=latency_us)

    def claim_task(self, task_id: str) -> TaskResult:
        """Claim a pending task."""
        start = time.perf_counter_ns()
        result = self.backend.read(f"tasks:handoff:{task_id}")
        latency_us = (time.perf_counter_ns() - start) / 1000

        if result is None:
            return TaskResult(task_id=task_id, payload={}, latency_us=latency_us, found=False)

        data = result.get("data", {})
        val = data.get("value", data)

        # Update status
        if isinstance(val, dict):
            val["status"] = "claimed"
            val["claimed_by"] = self.agent_id
            val["claimed_at"] = time.time()
        self.backend.write(f"tasks:handoff:{task_id}", val, metadata={"type": "task_claimed"})

        return TaskResult(task_id=task_id, payload=val, latency_us=latency_us)

    def complete_task(self, task_id: str, result: dict) -> TaskResult:
        """Mark a task as complete with result."""
        completion = {
            "task_id": task_id,
            "completed_by": self.agent_id,
            "result": result,
            "completed_at": time.time(),
        }

        start = time.perf_counter_ns()
        self.backend.write(f"tasks:complete:{task_id}", completion, metadata={"type": "task_complete"})
        latency_us = (time.perf_counter_ns() - start) / 1000

        # Audit
        try:
            from synrix_runtime.monitoring.audit import AuditSystem
            audit = AuditSystem(self.backend)
            audit.log_handoff(self.agent_id, "system", task_id, completion, {})
        except Exception:
            pass

        return TaskResult(task_id=task_id, payload=completion, latency_us=latency_us)

    def log_decision(self, decision: str, reasoning: str, context: dict = None):
        """Log a decision with full audit trail."""
        ts = int(time.time() * 1000000)

        # Loop detection: check if this decision repeats a recent one
        decision_loop = None
        try:
            decision_loop = self._check_decision_loop(decision, reasoning)
        except Exception:
            pass

        # Capture memory snapshot at decision time (with timeout protection)
        memory_snapshot = {}
        try:
            import concurrent.futures
            def _capture_snapshot():
                snap = {}
                all_keys = self.backend.query_prefix(f"agents:{self.agent_id}:", limit=50)
                for item in all_keys:
                    key = item.get("key", "")
                    if ":snapshots:" not in key:
                        data = item.get("data", {})
                        snap[key] = data.get("value", data)
                return snap
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_capture_snapshot)
                memory_snapshot = future.result(timeout=10.0)
        except Exception:
            pass  # Log decision even without snapshot

        decision_data = {
            "agent_id": self.agent_id,
            "decision": decision,
            "reasoning": reasoning,
            "context": context or {},
            "memory_snapshot": memory_snapshot,
            "timestamp": time.time(),
            "loop_warning": decision_loop,
        }

        # Write audit record in background — never block the response.
        # Submit to enrichment pool so it doesn't compete with API executor.
        def _write_audit():
            try:
                raw_client = self.backend.client if hasattr(self.backend, 'client') else self.backend
                collection = self.backend.collection if hasattr(self.backend, 'collection') else 'agent_memory'
                raw_client.add_node(
                    name=f"audit:{self.agent_id}:{ts}:decision",
                    data=json.dumps(decision_data, default=str),
                    collection=collection,
                )
            except Exception as e:
                logger.error("Decision audit write failed: %s", e)

        _enrichment_pool.submit(_write_audit)
        return decision_data

    def get_stats(self) -> AgentStats:
        """Get complete performance statistics."""
        if self._metrics:
            m = self._metrics.get_agent_metrics(self.agent_id)
            return AgentStats(
                agent_id=self.agent_id,
                total_operations=m.total_operations,
                total_writes=m.total_writes,
                total_reads=m.total_reads,
                total_queries=m.total_queries,
                avg_write_latency_us=m.avg_write_latency_us,
                avg_read_latency_us=m.avg_read_latency_us,
                crash_count=m.crash_count,
                memory_node_count=m.memory_node_count,
                performance_score=m.performance_score,
                uptime_seconds=time.time() - self._started_at,
            )
        return AgentStats(
            agent_id=self.agent_id,
            total_operations=self._write_count + self._read_count + self._query_count,
            total_writes=self._write_count,
            total_reads=self._read_count,
            total_queries=self._query_count,
            uptime_seconds=time.time() - self._started_at,
        )

    def _heartbeat_loop(self):
        """Background heartbeat — writes to Synrix every 5 seconds."""
        while self._heartbeat_running:
            try:
                now = time.time()
                self.backend.write(
                    f"runtime:agents:{self.agent_id}:heartbeat",
                    {"value": now},
                    metadata={"type": "heartbeat"}
                )
                self.backend.write(
                    f"runtime:agents:{self.agent_id}:last_active",
                    {"value": now},
                    metadata={"type": "timestamp"}
                )
            except Exception:
                pass
            time.sleep(5)

    # -----------------------------------------------------------------
    # Memory Forgetting / Compression (addresses scale degradation)
    # -----------------------------------------------------------------

    def forget(self, key: str) -> dict:
        """Explicitly forget (delete) a specific memory.

        Use this when a memory is no longer relevant. Unlike TTL which
        expires automatically, forget() is an intentional removal.
        Returns the deleted key and whether it was found.
        """
        full_key = f"agents:{self.agent_id}:{key}"
        try:
            existing = self.backend.read(full_key)
            if existing is None:
                return {"key": key, "deleted": False, "reason": "not_found"}
            self.backend.delete(full_key)

            # Log the forget event for audit trail
            ts = int(time.time() * 1000000)
            self.backend.write(
                f"audit:{self.agent_id}:{ts}:forget",
                {
                    "agent_id": self.agent_id,
                    "action": "forget",
                    "key": key,
                    "timestamp": time.time(),
                },
                metadata={"type": "audit_forget"},
            )
            return {"key": key, "deleted": True, "reason": "explicit_forget"}
        except Exception as e:
            logger.error("Forget error for key %s: %s", key, e)
            return {"key": key, "deleted": False, "reason": str(e)}

    def forget_by_tag(self, tag: str) -> dict:
        """Forget all memories with a specific tag.

        Useful for bulk cleanup — e.g., forget all 'temporary' tagged memories.
        """
        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=10000)
        deleted = 0
        for item in all_items:
            data = item.get("data", {})
            val = data.get("value", data)
            if isinstance(val, dict):
                tags = val.get("_tags", [])
                if tag in tags:
                    try:
                        self.backend.delete(item.get("key", ""))
                        deleted += 1
                    except Exception:
                        pass
        return {"tag": tag, "deleted": deleted, "agent_id": self.agent_id}

    def forget_stale(self, max_age_seconds: int = 604800) -> dict:
        """Forget memories older than max_age_seconds (default: 7 days).

        Only removes memories with low importance. Critical memories are
        preserved regardless of age. This prevents memory bloat while
        keeping valuable knowledge intact.
        """
        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=10000)
        now = time.time()
        cutoff = now - max_age_seconds
        deleted = 0
        preserved = 0

        for item in all_items:
            key = item.get("key", "")
            if ":snapshots:" in key or ":changelog:" in key:
                continue

            data = item.get("data", {})
            val = data.get("value", data)

            # Never delete critical memories
            if isinstance(val, dict) and val.get("__importance") == "critical":
                preserved += 1
                continue

            # Check timestamp — use metadata timestamp or _shared_at
            item_time = data.get("timestamp", 0)
            if isinstance(val, dict):
                item_time = max(item_time, val.get("_shared_at", 0), val.get("timestamp", 0))

            if item_time > 0 and item_time < cutoff:
                try:
                    self.backend.delete(key)
                    deleted += 1
                except Exception:
                    pass

        return {
            "deleted": deleted,
            "preserved_critical": preserved,
            "max_age_seconds": max_age_seconds,
            "agent_id": self.agent_id,
        }

    # -----------------------------------------------------------------
    # Memory Consolidation (addresses redundancy at scale)
    # -----------------------------------------------------------------

    def consolidate(self, similarity_threshold: float = 0.90, dry_run: bool = True) -> dict:
        """Find and optionally merge redundant memories.

        Scans all memories for semantic duplicates. When dry_run=True
        (default), reports what would be merged without changing anything.
        When dry_run=False, keeps the newest version and removes duplicates.

        This addresses the key scaling issue: at 1000+ memories, redundant
        entries degrade retrieval quality because similar but stale memories
        surface alongside current ones.
        """
        try:
            import numpy as np
            from synrix.embeddings import EmbeddingModel
            emb_model = EmbeddingModel.get()
            if not emb_model:
                return {"error": "Embedding model not available", "consolidated": 0}
        except ImportError:
            return {"error": "numpy or embeddings not installed", "consolidated": 0}

        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=10000)

        # Filter to actual memories (not snapshots, audit, access logs)
        memories = []
        for item in all_items:
            key = item.get("key", "")
            if any(skip in key for skip in [":snapshots:", ":changelog:", ":__access_log:", "audit:", "alerts:", "runtime:"]):
                continue
            data = item.get("data", {})
            val = data.get("value", data)
            text = self._value_to_text(val)
            if text and len(text.strip()) > 5:
                memories.append({
                    "key": key,
                    "text": text,
                    "data": data,
                    "timestamp": data.get("timestamp", 0),
                })

        if len(memories) < 2:
            return {"consolidated": 0, "total_memories": len(memories), "dry_run": dry_run}

        # Embed all memories
        embeddings = []
        for mem in memories:
            emb = emb_model.encode(mem["text"])
            if isinstance(emb, bytes):
                vec = np.frombuffer(emb, dtype=np.float32)
            else:
                vec = np.array(emb, dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec)
            mem["embedding"] = vec

        # Find duplicate clusters
        merged_indices = set()
        duplicates = []

        for i in range(len(memories)):
            if i in merged_indices:
                continue
            cluster = [i]
            for j in range(i + 1, len(memories)):
                if j in merged_indices:
                    continue
                score = float(np.dot(embeddings[i], embeddings[j]))
                if score >= similarity_threshold:
                    cluster.append(j)
                    merged_indices.add(j)
            if len(cluster) > 1:
                # Keep the newest memory in each cluster
                cluster_mems = [(idx, memories[idx]) for idx in cluster]
                cluster_mems.sort(key=lambda x: x[1]["timestamp"], reverse=True)
                keeper = cluster_mems[0]
                removals = cluster_mems[1:]
                duplicates.append({
                    "kept": keeper[1]["key"].replace(prefix, ""),
                    "removed": [r[1]["key"].replace(prefix, "") for r in removals],
                    "cluster_size": len(cluster),
                })
                if not dry_run:
                    for _, mem in removals:
                        try:
                            self.backend.delete(mem["key"])
                        except Exception:
                            pass

        return {
            "consolidated": sum(len(d["removed"]) for d in duplicates),
            "clusters_found": len(duplicates),
            "total_memories": len(memories),
            "dry_run": dry_run,
            "details": duplicates[:20],  # Cap detail output
        }

    # -----------------------------------------------------------------
    # Shared Memory Conflict Detection (multi-agent safety)
    # -----------------------------------------------------------------

    def share_safe(self, key: str, value: Any, space: str = "global") -> dict:
        """Write to shared memory with conflict detection.

        Before writing, checks if another agent recently wrote to the same
        key. If a conflict is detected, returns both values so the caller
        can decide how to resolve it. This prevents the silent overwrite
        problem in multi-agent systems.
        """
        full_key = f"shared:{space}:{key}"

        # Check for existing value from a different author
        conflict = None
        try:
            existing = self.backend.read(full_key)
            if existing:
                existing_data = existing.get("data", {})
                existing_val = existing_data.get("value", existing_data)
                if isinstance(existing_val, dict):
                    existing_author = existing_val.get("_author", "unknown")
                    existing_time = existing_val.get("_shared_at", 0)
                    # Conflict if different author wrote in last 5 minutes
                    if existing_author != self.agent_id and (time.time() - existing_time) < 300:
                        conflict = {
                            "has_conflict": True,
                            "existing_author": existing_author,
                            "existing_value": {k: v for k, v in existing_val.items() if not k.startswith("_")},
                            "existing_time": existing_time,
                            "your_agent": self.agent_id,
                            "resolution": "your_value_written",
                        }
        except Exception:
            pass

        # Write anyway but include conflict info
        result = self.share(key, value, space)

        # Log conflict event if detected
        if conflict:
            try:
                ts = int(time.time() * 1000000)
                self.backend.write(
                    f"shared:{space}:conflicts:{ts}",
                    {
                        "key": key,
                        "space": space,
                        "conflict": conflict,
                        "resolved_by": self.agent_id,
                        "timestamp": time.time(),
                    },
                    metadata={"type": "shared_conflict"},
                )
            except Exception:
                pass

        return {
            "write": {"key": key, "node_id": result.node_id, "latency_us": result.latency_us},
            "conflict": conflict,
        }

    def shared_conflicts(self, space: str = "global", limit: int = 20) -> list:
        """List recent write conflicts in a shared memory space.

        Returns a list of conflicts where multiple agents wrote to the
        same key within a short window. Useful for debugging multi-agent
        coordination issues.
        """
        results = self.backend.query_prefix(f"shared:{space}:conflicts:", limit=limit)
        conflicts = []
        for r in results:
            data = r.get("data", {})
            val = data.get("value", data)
            if isinstance(val, dict):
                conflicts.append(val)
        conflicts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return conflicts

    # -----------------------------------------------------------------
    # Memory Health Score (overall agent memory quality)
    # -----------------------------------------------------------------

    def memory_health(self) -> dict:
        """Get a health assessment of this agent's memory.

        Checks for common issues that degrade agent performance at scale:
        - Duplicate/redundant memories
        - Stale memories (old, never accessed)
        - Memory bloat (too many low-importance entries)
        - Contradiction density

        Returns a score from 0-100 with actionable recommendations.
        """
        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=10000)
        now = time.time()

        total = 0
        stale_count = 0
        low_importance = 0
        critical_count = 0
        has_ttl = 0
        total_size = 0
        issues = []
        score = 100.0

        for item in all_items:
            key = item.get("key", "")
            if any(skip in key for skip in [":snapshots:", ":changelog:", ":__access_log:", "audit:", "alerts:", "runtime:"]):
                continue
            total += 1
            data = item.get("data", {})
            total_size += len(json.dumps(data, default=str).encode())
            val = data.get("value", data)

            if isinstance(val, dict):
                imp = val.get("__importance", "normal")
                if imp == "low":
                    low_importance += 1
                elif imp == "critical":
                    critical_count += 1
                if "__expires_at" in val:
                    has_ttl += 1

            # Check staleness (older than 7 days)
            item_time = data.get("timestamp", 0)
            if isinstance(val, dict):
                item_time = max(item_time, val.get("timestamp", 0))
            if item_time > 0 and (now - item_time) > 604800:
                stale_count += 1

        # Scoring
        if total > 0:
            stale_ratio = stale_count / total
            if stale_ratio > 0.5:
                score -= 20
                issues.append(f"{stale_count}/{total} memories are older than 7 days. Run agent.forget_stale() to clean up.")
            elif stale_ratio > 0.3:
                score -= 10
                issues.append(f"{stale_count} stale memories detected. Consider running forget_stale().")

            low_ratio = low_importance / total
            if low_ratio > 0.4:
                score -= 10
                issues.append(f"{low_importance} low-importance memories. Use remember_important() to prioritize.")

            if total > 500 and has_ttl == 0:
                score -= 10
                issues.append("No TTL memories found. Use remember_with_ttl() for temporary data to prevent bloat.")

            if total > 1000:
                score -= 5
                issues.append(f"{total} memories stored. Run agent.consolidate() to find and remove duplicates.")

        if total_size > 10 * 1024 * 1024:  # > 10MB
            score -= 10
            issues.append(f"Memory size is {total_size / 1024 / 1024:.1f}MB. Consider cleanup.")

        if not issues:
            issues.append("Memory is healthy. No action needed.")

        return {
            "score": max(0, round(score)),
            "total_memories": total,
            "stale_memories": stale_count,
            "critical_memories": critical_count,
            "low_importance": low_importance,
            "ttl_memories": has_ttl,
            "total_size_bytes": total_size,
            "total_size_human": f"{total_size / 1024:.1f} KB" if total_size < 1048576 else f"{total_size / 1048576:.1f} MB",
            "issues": issues,
            "agent_id": self.agent_id,
        }

    # -----------------------------------------------------------------
    # Agent-to-Agent Messaging (real-time coordination)
    # -----------------------------------------------------------------

    def send_message(self, to_agent: str, message: Any, message_type: str = "info",
                     space: str = "global") -> dict:
        """Send a message to another agent through shared memory.

        Creates an inbox/outbox system where agents can communicate
        asynchronously. Messages are stored with timestamps and read receipts.

        Args:
            to_agent: Target agent ID
            message: Any JSON-serializable message content
            message_type: "info", "request", "response", "alert" (default "info")
            space: Memory space for the messages (default "global")
        """
        ts = int(time.time() * 1000000)
        msg_id = f"msg_{ts}"
        msg_data = {
            "msg_id": msg_id,
            "from_agent": self.agent_id,
            "to_agent": to_agent,
            "message": message,
            "message_type": message_type,
            "timestamp": time.time(),
            "read": False,
        }

        # Write to recipient's inbox
        self.backend.write(
            f"shared:{space}:inbox:{to_agent}:{msg_id}",
            msg_data,
            metadata={"type": "agent_message", "from": self.agent_id, "to": to_agent},
        )
        # Write to sender's outbox
        self.backend.write(
            f"shared:{space}:outbox:{self.agent_id}:{msg_id}",
            msg_data,
            metadata={"type": "agent_message_sent", "to": to_agent},
        )
        return {"msg_id": msg_id, "to": to_agent, "sent": True}

    def read_messages(self, space: str = "global", unread_only: bool = False,
                      limit: int = 50) -> list:
        """Read messages from this agent's inbox.

        Args:
            space: Memory space (default "global")
            unread_only: If True, only return unread messages
            limit: Max messages to return
        """
        results = self.backend.query_prefix(
            f"shared:{space}:inbox:{self.agent_id}:", limit=limit
        )
        messages = []
        for r in results:
            data = r.get("data", {})
            val = data.get("value", data)
            if isinstance(val, dict):
                if unread_only and val.get("read", False):
                    continue
                messages.append(val)
        messages.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return messages

    def mark_read(self, msg_id: str, space: str = "global") -> dict:
        """Mark a message as read."""
        key = f"shared:{space}:inbox:{self.agent_id}:{msg_id}"
        result = self.backend.read(key)
        if result:
            data = result.get("data", {})
            val = data.get("value", data)
            if isinstance(val, dict):
                val["read"] = True
                val["read_at"] = time.time()
                self.backend.write(key, val, metadata={"type": "agent_message"})
                return {"msg_id": msg_id, "marked_read": True}
        return {"msg_id": msg_id, "marked_read": False, "reason": "not_found"}

    def broadcast(self, message: Any, message_type: str = "info",
                  space: str = "global") -> dict:
        """Broadcast a message to ALL agents in a shared space.

        Writes to a broadcast channel that any agent can read.
        """
        ts = int(time.time() * 1000000)
        msg_data = {
            "msg_id": f"broadcast_{ts}",
            "from_agent": self.agent_id,
            "message": message,
            "message_type": message_type,
            "timestamp": time.time(),
        }
        self.backend.write(
            f"shared:{space}:broadcast:{ts}",
            msg_data,
            metadata={"type": "broadcast", "from": self.agent_id},
        )
        return {"broadcast": True, "msg_id": msg_data["msg_id"]}

    def read_broadcasts(self, space: str = "global", since_seconds: int = 3600,
                        limit: int = 50) -> list:
        """Read recent broadcast messages from all agents.

        Args:
            space: Memory space (default "global")
            since_seconds: Only show broadcasts from the last N seconds (default 1 hour)
            limit: Max messages to return
        """
        results = self.backend.query_prefix(f"shared:{space}:broadcast:", limit=limit)
        cutoff = time.time() - since_seconds
        messages = []
        for r in results:
            data = r.get("data", {})
            val = data.get("value", data)
            if isinstance(val, dict) and val.get("timestamp", 0) > cutoff:
                messages.append(val)
        messages.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return messages

    # -----------------------------------------------------------------
    # Goal Tracking with Progress
    # -----------------------------------------------------------------

    def set_goal(self, goal: str, milestones: list = None) -> dict:
        """Set a goal for this agent with optional milestones.

        Goals are tracked persistently and can be checked for progress.
        Integrates with the Brain drift detection system.

        Args:
            goal: Description of what the agent should accomplish
            milestones: Optional list of milestone descriptions
        """
        goal_data = {
            "goal": goal,
            "milestones": [{"description": m, "completed": False, "completed_at": None}
                          for m in (milestones or [])],
            "set_at": time.time(),
            "status": "active",
            "progress": 0.0,
        }
        self.backend.write(
            f"agents:{self.agent_id}:goal:current",
            goal_data,
            metadata={"type": "agent_goal", "agent_id": self.agent_id},
        )

        # Store goal embedding for drift detection
        try:
            from synrix.embeddings import EmbeddingModel
            emb_model = EmbeddingModel.get()
            if emb_model:
                goal_emb = emb_model.encode(goal)
                self.backend.write(
                    f"agents:{self.agent_id}:goal:embedding",
                    {"embedding": goal_emb.tolist() if hasattr(goal_emb, 'tolist') else list(goal_emb)},
                    metadata={"type": "goal_embedding"},
                )
        except Exception:
            pass

        return {"goal_set": True, "goal": goal, "milestones": len(milestones or [])}

    def update_progress(self, progress: float = None, milestone_index: int = None,
                        note: str = None) -> dict:
        """Update progress on the current goal.

        Args:
            progress: Overall progress 0.0 to 1.0 (optional)
            milestone_index: Mark a specific milestone as complete (optional)
            note: Progress note to log (optional)
        """
        result = self.backend.read(f"agents:{self.agent_id}:goal:current")
        if not result:
            return {"error": "No active goal. Use set_goal() first."}

        data = result.get("data", {})
        goal = data.get("value", data)
        if not isinstance(goal, dict):
            return {"error": "Invalid goal data"}

        if progress is not None:
            goal["progress"] = max(0.0, min(1.0, progress))

        if milestone_index is not None:
            milestones = goal.get("milestones", [])
            if 0 <= milestone_index < len(milestones):
                milestones[milestone_index]["completed"] = True
                milestones[milestone_index]["completed_at"] = time.time()
                # Auto-calculate progress from milestones
                completed = sum(1 for m in milestones if m["completed"])
                goal["progress"] = completed / len(milestones)

        if goal["progress"] >= 1.0:
            goal["status"] = "completed"
            goal["completed_at"] = time.time()

        goal["last_updated"] = time.time()

        # Log progress note
        if note:
            ts = int(time.time() * 1000000)
            self.backend.write(
                f"agents:{self.agent_id}:goal:progress:{ts}",
                {"note": note, "progress": goal["progress"], "timestamp": time.time()},
                metadata={"type": "goal_progress"},
            )

        self.backend.write(
            f"agents:{self.agent_id}:goal:current",
            goal,
            metadata={"type": "agent_goal"},
        )
        return {
            "progress": goal["progress"],
            "status": goal["status"],
            "milestones_completed": sum(1 for m in goal.get("milestones", []) if m["completed"]),
            "milestones_total": len(goal.get("milestones", [])),
        }

    def get_goal(self) -> dict:
        """Get the current goal and progress."""
        result = self.backend.read(f"agents:{self.agent_id}:goal:current")
        if not result:
            return {"has_goal": False}
        data = result.get("data", {})
        goal = data.get("value", data)
        if isinstance(goal, dict):
            goal["has_goal"] = True
            return goal
        return {"has_goal": False}

    # -----------------------------------------------------------------
    # Memory Export / Import (portability)
    # -----------------------------------------------------------------

    def export_memories(self, include_snapshots: bool = False) -> dict:
        """Export all agent memories as a portable JSON structure.

        This creates a complete backup of the agent's knowledge that can
        be imported into another agent or system. Useful for:
        - Migration between environments
        - Backup before risky operations
        - Cloning an agent's knowledge to a new agent

        Args:
            include_snapshots: Whether to include snapshot data (default False)
        """
        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=100000)

        memories = {}
        snapshot_data = {}
        meta = {
            "agent_id": self.agent_id,
            "exported_at": time.time(),
            "version": "1.0",
        }

        for item in all_items:
            key = item.get("key", "")
            data = item.get("data", {})
            val = data.get("value", data)

            # Strip the agent prefix for portability
            portable_key = key.replace(prefix, "")

            if ":snapshots:" in key:
                if include_snapshots:
                    snapshot_data[portable_key] = val
            elif any(skip in key for skip in ["audit:", "alerts:", "runtime:", ":__access_log:"]):
                continue  # Skip internal data
            else:
                memories[portable_key] = {
                    "value": val,
                    "timestamp": data.get("timestamp", 0),
                }

        return {
            "meta": meta,
            "memories": memories,
            "snapshots": snapshot_data if include_snapshots else {},
            "count": len(memories),
        }

    def import_memories(self, export_data: dict, overwrite: bool = False) -> dict:
        """Import memories from an export bundle.

        Args:
            export_data: Output from export_memories()
            overwrite: If True, overwrite existing keys. If False (default),
                      skip keys that already exist.
        """
        memories = export_data.get("memories", {})
        imported = 0
        skipped = 0

        for portable_key, mem_data in memories.items():
            full_key = f"agents:{self.agent_id}:{portable_key}"

            if not overwrite:
                existing = self.backend.read(full_key)
                if existing is not None:
                    skipped += 1
                    continue

            value = mem_data.get("value", mem_data) if isinstance(mem_data, dict) else mem_data
            self.backend.write(full_key, value, metadata={"type": "imported"})
            imported += 1

        return {
            "imported": imported,
            "skipped": skipped,
            "total_in_bundle": len(memories),
            "agent_id": self.agent_id,
            "source_agent": export_data.get("meta", {}).get("agent_id", "unknown"),
        }

    # -----------------------------------------------------------------
    # Filtered Search (time range + importance + tags combined)
    # -----------------------------------------------------------------

    def search_filtered(self, query: str = None, tags: list = None,
                        importance: str = None, min_age_seconds: int = None,
                        max_age_seconds: int = None, limit: int = 20) -> list:
        """Search memories with multiple filters combined.

        All filters are AND-combined. Omit a filter to skip it.

        Args:
            query: Semantic search query (optional — if omitted, filters only)
            tags: Only include memories with ALL of these tags
            importance: Filter by importance level ("critical", "normal", "low")
            min_age_seconds: Only memories older than this
            max_age_seconds: Only memories newer than this
            limit: Max results (default 20)
        """
        prefix = f"agents:{self.agent_id}:"
        all_items = self.backend.query_prefix(prefix, limit=10000)
        now = time.time()

        # First pass: apply non-semantic filters
        candidates = []
        for item in all_items:
            key = item.get("key", "")
            if any(skip in key for skip in [":snapshots:", ":changelog:", ":__access_log:",
                                            "audit:", "alerts:", "runtime:"]):
                continue

            data = item.get("data", {})
            val = data.get("value", data)

            # Importance filter
            if importance:
                mem_imp = val.get("__importance", "normal") if isinstance(val, dict) else "normal"
                if mem_imp != importance:
                    continue

            # Tag filter
            if tags:
                mem_tags = val.get("_tags", []) if isinstance(val, dict) else []
                if not all(t in mem_tags or f"auto:{t}" in mem_tags for t in tags):
                    continue

            # Age filter
            item_time = data.get("timestamp", 0)
            if isinstance(val, dict):
                item_time = max(item_time, val.get("timestamp", 0))

            if min_age_seconds and item_time > 0:
                if (now - item_time) < min_age_seconds:
                    continue
            if max_age_seconds and item_time > 0:
                if (now - item_time) > max_age_seconds:
                    continue

            text = self._value_to_text(val)
            portable_key = key.replace(prefix, "")
            candidates.append({
                "key": portable_key,
                "value": val,
                "text": text or "",
                "timestamp": item_time,
            })

        # Second pass: semantic ranking if query provided
        if query and candidates:
            try:
                import numpy as np
                from synrix.embeddings import EmbeddingModel
                emb_model = EmbeddingModel.get()
                if emb_model:
                    query_emb = emb_model.encode(query)
                    if isinstance(query_emb, bytes):
                        query_vec = np.frombuffer(query_emb, dtype=np.float32)
                    else:
                        query_vec = np.array(query_emb, dtype=np.float32)
                    norm = np.linalg.norm(query_vec)
                    if norm > 0:
                        query_vec = query_vec / norm

                    for c in candidates:
                        if c["text"]:
                            mem_emb = emb_model.encode(c["text"])
                            if isinstance(mem_emb, bytes):
                                mem_vec = np.frombuffer(mem_emb, dtype=np.float32)
                            else:
                                mem_vec = np.array(mem_emb, dtype=np.float32)
                            mem_norm = np.linalg.norm(mem_vec)
                            if mem_norm > 0:
                                mem_vec = mem_vec / mem_norm
                            c["relevance"] = float(np.dot(query_vec, mem_vec))
                        else:
                            c["relevance"] = 0.0

                    candidates.sort(key=lambda x: x["relevance"], reverse=True)
            except ImportError:
                pass
        else:
            # Sort by timestamp (newest first)
            candidates.sort(key=lambda x: x["timestamp"], reverse=True)

        # Clean up output
        results = []
        for c in candidates[:limit]:
            entry = {"key": c["key"], "value": c["value"]}
            if "relevance" in c:
                entry["relevance"] = round(c["relevance"], 4)
            if c["timestamp"]:
                entry["timestamp"] = c["timestamp"]
            results.append(entry)

        return results

    # -----------------------------------------------------------------
    # Cloud Feature Hints
    # -----------------------------------------------------------------

    def get_brain_status(self) -> dict:
        """Get Brain Intelligence status (Drift Radar, Contradiction Shield, Cost X-Ray).

        This is a cloud-only feature that provides advanced agent intelligence.
        Locally, use get_loop_status() for loop detection and memory_health()
        for memory diagnostics.
        """
        if not self._is_cloud:
            return {
                "available": False,
                "message": "Brain Intelligence (Drift Radar, Contradiction Shield, Cost X-Ray) "
                          "is available on the Octopoda cloud platform.",
                "local_alternatives": {
                    "loop_detection": "agent.get_loop_status() — 5-signal loop analysis",
                    "memory_health": "agent.memory_health() — health scoring with recommendations",
                    "consolidation": "agent.consolidate() — find and merge duplicates",
                },
                "upgrade_url": "https://octopodas.com/pricing",
            }
        # In cloud mode, this is handled by cloud_server.py /v1/brain/status
        return {"available": True, "mode": "cloud"}

    def get_dashboard_url(self) -> dict:
        """Get the dashboard URL for monitoring this agent.

        Local mode: Flask dashboard at localhost:7842
        Cloud mode: Full dashboard at octopodas.com/dashboard
        """
        if not self._is_cloud:
            return {
                "local_dashboard": "http://localhost:7842",
                "message": "Local dashboard available. For the full cloud dashboard with "
                          "real-time visualization, knowledge graph explorer, and team features: "
                          "https://octopodas.com/dashboard",
            }
        return {
            "dashboard": "https://octopodas.com/dashboard",
            "mode": "cloud",
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()

    def shutdown(self):
        """Gracefully shut down the agent."""
        self._heartbeat_running = False

        # Final snapshot
        try:
            self.snapshot("shutdown_auto")
        except Exception:
            pass

        # Deregister
        try:
            if self._daemon:
                self._daemon.deregister_agent(self.agent_id)
        except Exception:
            pass

        logger.info(f"[{self.agent_id}] Shutdown complete | writes={self._write_count} reads={self._read_count}")
