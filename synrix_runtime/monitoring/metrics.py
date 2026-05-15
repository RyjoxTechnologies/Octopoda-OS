"""
Synrix Agent Runtime — Metrics Collector
Every metric stored in real Synrix. Complete time series.
"""

import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class AgentMetrics:
    agent_id: str
    total_operations: int = 0
    total_writes: int = 0
    total_reads: int = 0
    total_queries: int = 0
    avg_write_latency_us: float = 0.0
    avg_read_latency_us: float = 0.0
    avg_query_latency_us: float = 0.0
    error_rate: float = 0.0
    uptime_seconds: float = 0.0
    crash_count: int = 0
    recovery_count: int = 0
    avg_recovery_time_us: float = 0.0
    memory_node_count: int = 0
    operations_per_minute: float = 0.0
    performance_score: float = 100.0
    handoffs_sent: int = 0
    handoffs_received: int = 0
    snapshots: int = 0


@dataclass
class SystemMetrics:
    total_agents: int = 0
    active_agents: int = 0
    total_operations: int = 0
    system_uptime_seconds: float = 0.0
    mean_recovery_time_us: float = 0.0
    operations_per_minute: float = 0.0
    memory_bus_throughput: int = 0
    most_active_agent: str = ""
    slowest_agent: str = ""
    total_crashes: int = 0
    total_recoveries: int = 0


class MetricsCollector:
    """Collects, stores, and analyzes all runtime metrics via Synrix."""

    _instance = None
    _instances: Dict[str, "MetricsCollector"] = {}  # Per-tenant instances
    _lock = threading.Lock()
    # Server-side metrics cache: "tenant_id:agent_id" -> {"metrics": AgentMetrics, "timestamp": float}
    # Keyed by tenant-scoped cache key to ensure strict tenant isolation.
    _metrics_cache: dict = {}
    _cache_lock = threading.Lock()
    _CACHE_TTL = 90  # seconds — serve cached metrics if fresh enough

    # Background pre-computation
    _bg_thread: threading.Thread = None
    _bg_running = False
    _BG_INTERVAL = int(__import__("os").environ.get("OCTOPODA_METRICS_REFRESH_SEC", "60"))  # 60s default (was 10 — too aggressive)

    @classmethod
    def get_instance(cls, backend=None, tenant_id: str = None):
        """Get or create a MetricsCollector for a specific tenant."""
        tid = tenant_id or "_default"
        with cls._lock:
            if tid in cls._instances:
                return cls._instances[tid]
            instance = cls(backend, tenant_id=tid)
            cls._instances[tid] = instance
            # Legacy singleton compat
            if cls._instance is None:
                cls._instance = instance
            return instance

    def __init__(self, backend=None, tenant_id: str = None):
        self.backend = backend
        self.tenant_id = tenant_id or "_default"
        if self.backend is None:
            from synrix.agent_backend import get_synrix_backend
            from synrix_runtime.config import SynrixConfig
            config = SynrixConfig.from_env()
            self.backend = get_synrix_backend(**config.get_backend_kwargs())
        self._op_count = 0
        self._count_lock = threading.Lock()

    def _cache_key(self, agent_id: str) -> str:
        """Return a tenant-scoped cache key to prevent cross-tenant data leaks."""
        return f"{self.tenant_id}:{agent_id}"

    def start_background_refresh(self):
        """Start background thread that pre-computes metrics for all agents every 10s."""
        if MetricsCollector._bg_running:
            return
        MetricsCollector._bg_running = True
        MetricsCollector._bg_thread = threading.Thread(
            target=self._background_refresh_loop, daemon=True, name="metrics-bg-refresh"
        )
        MetricsCollector._bg_thread.start()

    def _background_refresh_loop(self):
        """Background loop: discover all agents, compute metrics, cache them."""
        import logging
        logger = logging.getLogger("synrix.metrics")
        logger.info("Background metrics refresh started (every %ds)", self._BG_INTERVAL)
        # Wait for server to finish starting up before first run
        time.sleep(15)
        while MetricsCollector._bg_running:
            try:
                self._refresh_all_agents()
            except Exception as e:
                logger.warning("Background metrics refresh error: %s", e)
            time.sleep(self._BG_INTERVAL)

    def _refresh_all_agents(self):
        """Discover all agents and pre-compute their metrics."""
        # Find all agent IDs from the backend
        try:
            results = self.backend.query_prefix("runtime:agents:", limit=500)
            agent_ids = set()
            for r in results:
                key = r.get("key", "")
                parts = key.split(":")
                if len(parts) >= 3:
                    aid = parts[2]
                    if aid != "system":
                        agent_ids.add(aid)
        except Exception:
            return

        # Batch-refresh via get_metrics_batch (single tenant-wide query)
        # instead of N+1 per-agent DB round-trips. 100 agents: ~3 queries
        # instead of ~900.
        if not agent_ids:
            return
        try:
            _ = self.get_metrics_batch(list(agent_ids))
            # get_metrics_batch already populates _metrics_cache internally
        except Exception:
                pass  # Keep existing cache entry if computation fails

    def get_all_cached_metrics(self) -> dict:
        """Return cached metrics for THIS tenant only. Filters by tenant_id prefix."""
        prefix = f"{self.tenant_id}:"
        with MetricsCollector._cache_lock:
            result = {}
            for cache_key, entry in MetricsCollector._metrics_cache.items():
                # Only return metrics belonging to this tenant
                if not cache_key.startswith(prefix):
                    continue
                m = entry["metrics"]
                result[m.agent_id] = {
                    "agent_id": m.agent_id,
                    "performance_score": m.performance_score,
                    "total_operations": m.total_operations,
                    "total_writes": m.total_writes,
                    "total_reads": m.total_reads,
                    "total_queries": m.total_queries,
                    "avg_write_latency_us": m.avg_write_latency_us,
                    "avg_read_latency_us": m.avg_read_latency_us,
                    "crash_count": m.crash_count,
                    "recovery_count": m.recovery_count,
                    "error_rate": m.error_rate,
                    "uptime_seconds": m.uptime_seconds,
                    "memory_node_count": m.memory_node_count,
                }
            return result

    def _ts(self):
        return int(time.time() * 1000000)

    def record_write(self, agent_id: str, key: str, latency_us: float, success: bool, node_id: Optional[int] = None):
        ts = self._ts()
        self.backend.write(
            f"metrics:{agent_id}:write:{ts}",
            {"latency_us": latency_us, "key": key, "success": success, "node_id": node_id, "timestamp": time.time()},
            metadata={"type": "metric_write"}
        )
        with self._count_lock:
            self._op_count += 1

    def record_read(self, agent_id: str, key: str, latency_us: float, found: bool):
        ts = self._ts()
        self.backend.write(
            f"metrics:{agent_id}:read:{ts}",
            {"latency_us": latency_us, "key": key, "found": found, "timestamp": time.time()},
            metadata={"type": "metric_read"}
        )
        with self._count_lock:
            self._op_count += 1

    def record_query(self, agent_id: str, prefix: str, latency_us: float, result_count: int):
        ts = self._ts()
        self.backend.write(
            f"metrics:{agent_id}:query:{ts}",
            {"latency_us": latency_us, "prefix": prefix, "count": result_count, "timestamp": time.time()},
            metadata={"type": "metric_query"}
        )
        with self._count_lock:
            self._op_count += 1

    def record_crash(self, agent_id: str, reason: str):
        ts = self._ts()
        self.backend.write(
            f"metrics:{agent_id}:crash:{ts}",
            {"reason": reason, "timestamp": time.time()},
            metadata={"type": "metric_crash"}
        )

    def record_recovery(self, agent_id: str, recovery_time_us: float, keys_restored: int):
        ts = self._ts()
        self.backend.write(
            f"metrics:{agent_id}:recovery:{ts}",
            {"recovery_time_us": recovery_time_us, "keys_restored": keys_restored, "timestamp": time.time()},
            metadata={"type": "metric_recovery"}
        )

    def record_handoff(self, from_agent: str, to_agent: str, task_id: str, latency_us: float):
        ts = self._ts()
        self.backend.write(
            f"metrics:{from_agent}:handoff:{ts}",
            {"from_agent": from_agent, "to_agent": to_agent, "task_id": task_id, "latency_us": latency_us, "timestamp": time.time()},
            metadata={"type": "metric_handoff"}
        )

    def record_snapshot(self, agent_id: str, label: str, keys_count: int, latency_us: float):
        ts = self._ts()
        self.backend.write(
            f"metrics:{agent_id}:snapshot:{ts}",
            {"label": label, "keys": keys_count, "latency_us": latency_us, "timestamp": time.time()},
            metadata={"type": "metric_snapshot"}
        )

    def get_agent_metrics(self, agent_id: str) -> AgentMetrics:
        """Calculate complete metrics for an agent. Uses tenant-scoped cache to prevent 0-flicker."""
        cache_key = self._cache_key(agent_id)
        # Check cache first — return cached if fresh enough
        with MetricsCollector._cache_lock:
            cached = MetricsCollector._metrics_cache.get(cache_key)
            if cached and (time.time() - cached["timestamp"]) < MetricsCollector._CACHE_TTL:
                return cached["metrics"]

        try:
            metrics = self._compute_agent_metrics(agent_id)
            # Cache successful result (tenant-scoped)
            with MetricsCollector._cache_lock:
                MetricsCollector._metrics_cache[cache_key] = {"metrics": metrics, "timestamp": time.time()}
            return metrics
        except Exception:
            # On failure, return cached (even if stale) rather than zeros
            with MetricsCollector._cache_lock:
                if cache_key in MetricsCollector._metrics_cache:
                    return MetricsCollector._metrics_cache[cache_key]["metrics"]
            return AgentMetrics(agent_id=agent_id)

    def get_metrics_batch(self, agent_ids):
        """Fetch metrics for many agents in ~3 DB queries instead of 9N.

        Returns {agent_id: AgentMetrics}. Uses cache where fresh; falls
        back to tenant-wide prefix queries for the miss set.
        """
        if not agent_ids:
            return {}
        now = time.time()
        result = {}
        miss_ids = []
        # Cache hits first
        with MetricsCollector._cache_lock:
            for aid in agent_ids:
                ck = self._cache_key(aid)
                cached = MetricsCollector._metrics_cache.get(ck)
                if cached and (now - cached["timestamp"]) < MetricsCollector._CACHE_TTL:
                    result[aid] = cached["metrics"]
                else:
                    miss_ids.append(aid)

        if not miss_ids:
            return result

        # Default metrics for every miss
        for aid in miss_ids:
            result[aid] = AgentMetrics(agent_id=aid)

        try:
            # ONE tenant-wide query per metric category. Each returns rows
            # like `metrics:{aid}:{kind}:{ts}` which we bucket in Python.
            miss_set = set(miss_ids)

            def bucket(rows):
                """Return {aid: [row, ...]} for rows belonging to miss_set."""
                out = {}
                for r in rows:
                    name = r.get("key") or r.get("name") or ""
                    # name = "metrics:<aid>:<kind>:<ts>"
                    parts = name.split(":", 3)
                    if len(parts) < 3:
                        continue
                    aid = parts[1]
                    if aid in miss_set:
                        out.setdefault(aid, []).append(r)
                return out

            # Tenant-wide category pulls (bounded to sensible sizes so
            # pathological tenants don't blow up memory). If a tenant
            # has > 50k per-category events the older ones are excluded.
            writes = self.backend.query_prefix("metrics:", limit=50000)
            # Since the query_prefix for "metrics:" is a SINGLE SQL call,
            # we bucket and then sub-filter by the trailing subkind.
            per_aid_all = bucket(writes)

            memory = self.backend.query_prefix("agents:", limit=50000)
            per_aid_mem = bucket(memory) if False else {}  # memory uses different prefix structure
            # Correctly bucket memory rows:
            mem_bucket = {}
            for r in memory:
                name = r.get("key") or r.get("name") or ""
                parts = name.split(":", 2)  # "agents:<aid>:..."
                if len(parts) >= 2 and parts[1] in miss_set:
                    mem_bucket.setdefault(parts[1], 0)
                    mem_bucket[parts[1]] += 1

            # One tenant-wide SELECT for registered_at keys
            reg_rows = self.backend.query_prefix("runtime:agents:", limit=50000)
            reg_bucket = {}
            for r in reg_rows:
                name = r.get("key") or r.get("name") or ""
                parts = name.split(":", 3)  # runtime:agents:<aid>:<field>
                if len(parts) >= 4 and parts[2] in miss_set and parts[3] == "registered_at":
                    data = r.get("data", {})
                    val = data.get("value", data)
                    if isinstance(val, dict):
                        val = val.get("value")
                    if isinstance(val, (int, float)) and val > 0:
                        reg_bucket[parts[2]] = val

            # Now compute per-agent metrics from buckets
            cutoff_5min = now - 300
            for aid in miss_ids:
                m = result[aid]
                rows = per_aid_all.get(aid, [])
                # Split by kind based on 3rd segment
                writes_a, reads_a, queries_a, crashes_a, recoveries_a, handoffs_a, snapshots_a = [], [], [], [], [], [], []
                for r in rows:
                    name = r.get("key") or r.get("name") or ""
                    parts = name.split(":", 3)
                    if len(parts) < 3: continue
                    kind = parts[2]
                    if   kind == "write":    writes_a.append(r)
                    elif kind == "read":     reads_a.append(r)
                    elif kind == "query":    queries_a.append(r)
                    elif kind == "crash":    crashes_a.append(r)
                    elif kind == "recovery": recoveries_a.append(r)
                    elif kind == "handoff":  handoffs_a.append(r)
                    elif kind == "snapshot": snapshots_a.append(r)

                m.total_writes = len(writes_a)
                m.total_reads = len(reads_a)
                m.total_queries = len(queries_a)
                m.total_operations = m.total_writes + m.total_reads + m.total_queries
                m.crash_count = len(crashes_a)
                m.recovery_count = len(recoveries_a)
                m.handoffs_sent = len(handoffs_a)
                m.snapshots = len(snapshots_a)

                def avg_latency(items):
                    lats = []
                    for item in items:
                        data = item.get("data", {})
                        val = data.get("value", data)
                        if isinstance(val, dict):
                            lat = val.get("latency_us", 0)
                            if lat:
                                lats.append(lat)
                    return sum(lats) / len(lats) if lats else 0.0

                m.avg_write_latency_us = avg_latency(writes_a)
                m.avg_read_latency_us = avg_latency(reads_a)
                m.avg_query_latency_us = avg_latency(queries_a)

                failed_writes = sum(1 for w in writes_a
                                    if not self._extract_value(w).get("success", True))
                failed_reads = sum(1 for r2 in reads_a
                                   if not self._extract_value(r2).get("found", True))
                total_ops = m.total_operations or 1
                m.error_rate = (failed_writes + failed_reads) / total_ops

                recovery_times = [self._extract_value(r2).get("recovery_time_us", 0)
                                   for r2 in recoveries_a]
                m.avg_recovery_time_us = sum(recovery_times) / len(recovery_times) if recovery_times else 0.0

                m.memory_node_count = mem_bucket.get(aid, 0)

                recent_ops = 0
                for items in (writes_a, reads_a, queries_a):
                    for item in items:
                        ts = self._extract_value(item).get("timestamp", 0)
                        if ts > cutoff_5min:
                            recent_ops += 1
                m.operations_per_minute = recent_ops / 5.0

                reg_time = reg_bucket.get(aid)
                if reg_time:
                    m.uptime_seconds = now - reg_time

                m.performance_score = self.calculate_performance_score(aid, m)

                # Cache per-agent result
                with MetricsCollector._cache_lock:
                    MetricsCollector._metrics_cache[self._cache_key(aid)] = {
                        "metrics": m, "timestamp": now,
                    }
        except Exception as e:
            import sys as _sys
            print(f"[metrics batch] fallback to per-agent due to: {e}",
                  file=_sys.stderr)
            # Safe fallback: return defaults (already populated) or call individually
            for aid in miss_ids:
                try:
                    result[aid] = self._compute_agent_metrics(aid)
                except Exception:
                    pass
        return result

    def _compute_agent_metrics(self, agent_id: str) -> AgentMetrics:
        """Actually compute metrics from backend queries."""
        metrics = AgentMetrics(agent_id=agent_id)

        # Get all metric entries
        writes = self.backend.query_prefix(f"metrics:{agent_id}:write:", limit=500)
        reads = self.backend.query_prefix(f"metrics:{agent_id}:read:", limit=500)
        queries = self.backend.query_prefix(f"metrics:{agent_id}:query:", limit=500)
        crashes = self.backend.query_prefix(f"metrics:{agent_id}:crash:", limit=100)
        recoveries = self.backend.query_prefix(f"metrics:{agent_id}:recovery:", limit=100)
        handoffs = self.backend.query_prefix(f"metrics:{agent_id}:handoff:", limit=100)
        snapshots = self.backend.query_prefix(f"metrics:{agent_id}:snapshot:", limit=100)

        metrics.total_writes = len(writes)
        metrics.total_reads = len(reads)
        metrics.total_queries = len(queries)
        metrics.total_operations = metrics.total_writes + metrics.total_reads + metrics.total_queries
        metrics.crash_count = len(crashes)
        metrics.recovery_count = len(recoveries)
        metrics.handoffs_sent = len(handoffs)
        metrics.snapshots = len(snapshots)

        # Average latencies
        def avg_latency(items):
            lats = []
            for item in items:
                data = item.get("data", {})
                val = data.get("value", data)
                if isinstance(val, dict):
                    lat = val.get("latency_us", 0)
                    if lat:
                        lats.append(lat)
            return sum(lats) / len(lats) if lats else 0.0

        metrics.avg_write_latency_us = avg_latency(writes)
        metrics.avg_read_latency_us = avg_latency(reads)
        metrics.avg_query_latency_us = avg_latency(queries)

        # Error rate
        failed_writes = sum(1 for w in writes if not self._extract_value(w).get("success", True))
        failed_reads = sum(1 for r in reads if not self._extract_value(r).get("found", True))
        total = metrics.total_operations or 1
        metrics.error_rate = (failed_writes + failed_reads) / total

        # Recovery time
        recovery_times = [self._extract_value(r).get("recovery_time_us", 0) for r in recoveries]
        metrics.avg_recovery_time_us = sum(recovery_times) / len(recovery_times) if recovery_times else 0.0

        # Memory nodes
        memory = self.backend.query_prefix(f"agents:{agent_id}:", limit=500)
        metrics.memory_node_count = len(memory)

        # Ops per minute (last 5 minutes)
        cutoff = time.time() - 300
        recent_ops = 0
        for items in [writes, reads, queries]:
            for item in items:
                ts = self._extract_value(item).get("timestamp", 0)
                if ts > cutoff:
                    recent_ops += 1
        metrics.operations_per_minute = recent_ops / 5.0

        # Uptime
        reg = self.backend.read(f"runtime:agents:{agent_id}:registered_at")
        if reg:
            reg_data = reg.get("data", {})
            reg_val = reg_data.get("value", reg_data)
            reg_time = reg_val.get("value", 0) if isinstance(reg_val, dict) else reg_val
            if isinstance(reg_time, (int, float)) and reg_time > 0:
                metrics.uptime_seconds = time.time() - reg_time

        # Performance score
        metrics.performance_score = self.calculate_performance_score(agent_id, metrics)

        return metrics

    def _extract_value(self, item: dict) -> dict:
        """Extract the actual value dict from a Synrix result."""
        data = item.get("data", {})
        val = data.get("value", data)
        return val if isinstance(val, dict) else {"value": val}

    def get_system_metrics(self) -> SystemMetrics:
        """Calculate system-wide metrics."""
        sm = SystemMetrics()

        # Get agents from tenant backend (not global daemon)
        try:
            results = self.backend.query_prefix("runtime:agents:", limit=500)
            agent_ids = set()
            active_ids = set()
            for r in results:
                key = r.get("key", "")
                parts = key.split(":")
                if len(parts) >= 3:
                    aid = parts[2]
                    if aid == "system":
                        continue
                    agent_ids.add(aid)
                    if len(parts) > 3 and parts[3] == "state":
                        data = r.get("data", {})
                        val = data.get("value", data)
                        state = val.get("value") if isinstance(val, dict) else val
                        if state != "deregistered":
                            active_ids.add(aid)
            sm.total_agents = len(agent_ids)
            sm.active_agents = len(active_ids)
            # Get uptime from earliest agent registration
            reg_times = []
            for r in results:
                key = r.get("key", "")
                if ":registered_at" in key:
                    data = r.get("data", {})
                    val = data.get("value", data)
                    t = val.get("value") if isinstance(val, dict) else val
                    if isinstance(t, (int, float)):
                        reg_times.append(t)
            sm.system_uptime_seconds = time.time() - min(reg_times) if reg_times else 0
        except Exception:
            sm.total_agents = 0
            sm.active_agents = 0

        # Aggregate metrics across all agents (count actual per-agent operations)
        total_ops = 0
        all_metrics = self.backend.query_prefix("metrics:", limit=5000)
        for r in all_metrics:
            key = r.get("key", "")
            if ":write:" in key or ":read:" in key or ":query:" in key:
                total_ops += 1
        sm.total_operations = total_ops

        # Recovery stats
        all_recoveries = self.backend.query_prefix("runtime:events:recovery:", limit=200)
        recovery_times = []
        for r in all_recoveries:
            val = self._extract_value(r)
            rt = val.get("recovery_time_us", 0)
            if rt:
                recovery_times.append(rt)
        sm.total_recoveries = len(all_recoveries)
        sm.mean_recovery_time_us = sum(recovery_times) / len(recovery_times) if recovery_times else 0

        # Crash count
        all_crashes = self.backend.query_prefix("runtime:events:crash:", limit=200)
        sm.total_crashes = len(all_crashes)

        # Find most active and slowest agent
        agent_ops = {}
        agent_latencies = {}
        for agent_type in ["write", "read", "query"]:
            results = self.backend.query_prefix(f"metrics:", limit=500)
            for r in results:
                key = r.get("key", "")
                parts = key.split(":")
                if len(parts) >= 3 and parts[2] in ("write", "read", "query"):
                    aid = parts[1]
                    agent_ops[aid] = agent_ops.get(aid, 0) + 1
                    val = self._extract_value(r)
                    lat = val.get("latency_us", 0)
                    if lat:
                        if aid not in agent_latencies:
                            agent_latencies[aid] = []
                        agent_latencies[aid].append(lat)

        if agent_ops:
            sm.most_active_agent = max(agent_ops, key=agent_ops.get)
        if agent_latencies:
            avg_lats = {aid: sum(lats)/len(lats) for aid, lats in agent_latencies.items()}
            sm.slowest_agent = max(avg_lats, key=avg_lats.get)

        return sm

    def get_time_series(self, agent_id: str, metric_type: str, minutes_back: int = 60) -> list:
        """Get time series data for charting."""
        results = self.backend.query_prefix(f"metrics:{agent_id}:{metric_type}:", limit=500)
        cutoff = time.time() - (minutes_back * 60)

        series = []
        for r in results:
            val = self._extract_value(r)
            ts = val.get("timestamp", 0)
            if ts >= cutoff:
                series.append({
                    "timestamp": ts,
                    "latency_us": val.get("latency_us", 0),
                    "success": val.get("success", True),
                    "found": val.get("found", True),
                    "count": val.get("count", 0),
                })

        series.sort(key=lambda x: x["timestamp"])
        return series

    def calculate_performance_score(self, agent_id: str, metrics: AgentMetrics = None) -> float:
        """Calculate 0-100 performance score.

        Components:
            - Reliability (25pts): error rate — fewer errors = higher score
            - Latency (20pts): avg latency vs 50ms baseline — faster = higher
            - Stability (15pts): crash frequency per hour of uptime
            - Activity (15pts): operations volume — more usage = more proven
            - Search quality (15pts): read/query ratio vs writes — balanced usage
            - Memory utilisation (10pts): memories per operation — efficient storage
        """
        if metrics is None:
            metrics = self.get_agent_metrics(agent_id)

        # 1. Reliability (25 points) — error rate
        reliability = max(0, 25 * (1 - metrics.error_rate * 10))

        # 2. Latency (20 points) — normalized against 50ms baseline
        avg_lat = (metrics.avg_write_latency_us + metrics.avg_read_latency_us) / 2 if metrics.total_operations > 0 else 0
        latency = max(0, 20 * (1 - min(avg_lat / 50000, 1)))

        # 3. Stability (15 points) — crash frequency
        uptime_hours = max(metrics.uptime_seconds / 3600, 0.01)
        crash_rate = metrics.crash_count / uptime_hours
        stability = max(0, 15 * (1 - min(crash_rate, 1)))

        # 4. Activity volume (15 points) — more ops = more battle-tested
        #    Scale: 0 ops = 0pts, 10 ops = 5pts, 50 ops = 10pts, 100+ ops = 15pts
        if metrics.total_operations >= 100:
            activity = 15.0
        elif metrics.total_operations >= 50:
            activity = 10.0 + 5.0 * ((metrics.total_operations - 50) / 50)
        elif metrics.total_operations >= 10:
            activity = 5.0 + 5.0 * ((metrics.total_operations - 10) / 40)
        elif metrics.total_operations > 0:
            activity = 5.0 * (metrics.total_operations / 10)
        else:
            activity = 0.0

        # 5. Search quality (15 points) — agents that read/search show healthy usage
        #    Pure-write agents score lower; balanced read+write agents score higher
        total_reads = metrics.total_reads + metrics.total_queries
        if metrics.total_operations > 0:
            read_ratio = total_reads / metrics.total_operations
            # Sweet spot is 30-70% reads — penalize pure-write or pure-read
            if 0.3 <= read_ratio <= 0.7:
                search_quality = 15.0
            elif read_ratio > 0.7:
                search_quality = 15.0 * (1 - (read_ratio - 0.7) / 0.3)
            else:
                search_quality = 15.0 * (read_ratio / 0.3)
        else:
            search_quality = 0.0

        # 6. Memory utilisation (10 points) — having stored memories shows value
        #    Scale: 0 memories = 0pts, 5+ = 5pts, 15+ = 8pts, 25+ = 10pts
        mem_count = metrics.memory_node_count
        if mem_count >= 25:
            utilisation = 10.0
        elif mem_count >= 15:
            utilisation = 8.0 + 2.0 * ((mem_count - 15) / 10)
        elif mem_count >= 5:
            utilisation = 5.0 + 3.0 * ((mem_count - 5) / 10)
        elif mem_count > 0:
            utilisation = 5.0 * (mem_count / 5)
        else:
            utilisation = 0.0

        total = reliability + latency + stability + activity + search_quality + utilisation
        total = total * 0.7 + 30  # Compress to 30-100 range for friendlier scores
        return round(min(100, total), 1)

    def get_agent_comparison(self) -> list:
        """Get all agents ranked by performance score."""
        try:
            results = self.backend.query_prefix("runtime:agents:", limit=500)
            seen = {}
            for r in results:
                key = r.get("key", "")
                parts = key.split(":")
                if len(parts) >= 3:
                    aid = parts[2]
                    if aid == "system":
                        continue
                    if aid not in seen:
                        seen[aid] = {"agent_id": aid}
                    if len(parts) > 3:
                        data = r.get("data", {})
                        value = data.get("value", data)
                        if isinstance(value, dict) and "value" in value:
                            value = value["value"]
                        seen[aid][parts[3]] = value
            agents = [a for a in seen.values() if a.get("state") != "deregistered"]
        except Exception:
            agents = []

        comparison = []
        for agent in agents:
            agent_id = agent.get("agent_id")
            if agent_id:
                m = self.get_agent_metrics(agent_id)
                comparison.append({
                    "agent_id": agent_id,
                    "agent_type": agent.get("type", "generic"),
                    "performance_score": m.performance_score,
                    "total_operations": m.total_operations,
                    "avg_write_latency_us": m.avg_write_latency_us,
                    "avg_read_latency_us": m.avg_read_latency_us,
                    "crash_count": m.crash_count,
                    "memory_node_count": m.memory_node_count,
                    "error_rate": m.error_rate,
                    "uptime_seconds": m.uptime_seconds,
                })

        comparison.sort(key=lambda x: x["performance_score"], reverse=True)
        return comparison

    def get_performance_breakdown(self, agent_id: str) -> dict:
        """Get detailed performance score breakdown (6 components)."""
        m = self.get_agent_metrics(agent_id)

        # 1. Reliability (25 points)
        reliability = max(0, 25 * (1 - m.error_rate * 10))

        # 2. Latency (20 points)
        avg_lat = (m.avg_write_latency_us + m.avg_read_latency_us) / 2 if m.total_operations > 0 else 0
        latency_score = max(0, 20 * (1 - min(avg_lat / 50000, 1)))

        # 3. Stability (15 points)
        uptime_hours = max(m.uptime_seconds / 3600, 0.01)
        crash_rate = m.crash_count / uptime_hours
        stability = max(0, 15 * (1 - min(crash_rate, 1)))

        # 4. Activity volume (15 points)
        if m.total_operations >= 100:
            activity = 15.0
        elif m.total_operations >= 50:
            activity = 10.0 + 5.0 * ((m.total_operations - 50) / 50)
        elif m.total_operations >= 10:
            activity = 5.0 + 5.0 * ((m.total_operations - 10) / 40)
        elif m.total_operations > 0:
            activity = 5.0 * (m.total_operations / 10)
        else:
            activity = 0.0

        # 5. Search quality (15 points)
        total_reads = m.total_reads + m.total_queries
        if m.total_operations > 0:
            read_ratio = total_reads / m.total_operations
            if 0.3 <= read_ratio <= 0.7:
                search_quality = 15.0
            elif read_ratio > 0.7:
                search_quality = 15.0 * (1 - (read_ratio - 0.7) / 0.3)
            else:
                search_quality = 15.0 * (read_ratio / 0.3)
        else:
            search_quality = 0.0

        # 6. Memory utilisation (10 points)
        mem_count = m.memory_node_count
        if mem_count >= 25:
            utilisation = 10.0
        elif mem_count >= 15:
            utilisation = 8.0 + 2.0 * ((mem_count - 15) / 10)
        elif mem_count >= 5:
            utilisation = 5.0 + 3.0 * ((mem_count - 5) / 10)
        elif mem_count > 0:
            utilisation = 5.0 * (mem_count / 5)
        else:
            utilisation = 0.0

        total = reliability + latency_score + stability + activity + search_quality + utilisation

        return {
            "agent_id": agent_id,
            "total_score": round(min(100, total), 1),
            "reliability_component": {"score": round(reliability, 1), "max": 25, "error_rate": m.error_rate},
            "latency_component": {"score": round(latency_score, 1), "max": 20, "avg_latency_us": avg_lat},
            "stability_component": {"score": round(stability, 1), "max": 15, "crash_count": m.crash_count, "crash_rate_per_hour": round(crash_rate, 4)},
            "activity_component": {"score": round(activity, 1), "max": 15, "total_operations": m.total_operations},
            "search_quality_component": {"score": round(search_quality, 1), "max": 15, "read_ratio": round(total_reads / m.total_operations, 2) if m.total_operations > 0 else 0},
            "memory_utilisation_component": {"score": round(utilisation, 1), "max": 10, "memory_count": mem_count},
        }
