"""
Octopoda Agent Runtime — Garbage Collector
============================================
Prunes old metrics, events, heartbeats, alerts, and audit entries to prevent
SQLite bloat. Runs as a background thread in the daemon (every 6 hours by
default).

Configuration via environment variables:
    SYNRIX_GC_ENABLED=true               (default: true)
    SYNRIX_GC_INTERVAL_HOURS=6           (default: 6)
    SYNRIX_GC_METRICS_DAYS=7             (default: 7)
    SYNRIX_GC_EVENTS_DAYS=14             (default: 14)
    SYNRIX_GC_ALERTS_DAYS=14             (default: 14)
    SYNRIX_GC_AUDIT_DAYS=90              (default: 90)
    SYNRIX_GC_RUNTIME_AGENTS_DAYS=1      (default: 1) — heartbeats / agent state
    SYNRIX_GC_MAX_SNAPSHOTS=10           (default: 10 per agent)

The `runtime_agents_days` retention applies to the `runtime:agents:*` prefix,
which holds heartbeat writes (~3 writes/sec/agent) plus per-agent state. Old
versions of these keys accumulate forever otherwise — issue #6 documented a
case where this single prefix grew to 2.2M of 4.1M total rows. The daemon
only ever reads the *most recent* heartbeat or state row per agent, so
1-day retention is safe.
"""

import time
from dataclasses import dataclass
from synrix_runtime.log import get_logger

logger = get_logger("gc")


@dataclass
class GCConfig:
    """Garbage collection configuration."""
    enabled: bool = True
    interval_hours: int = 6
    metrics_days: int = 7
    events_days: int = 14
    alerts_days: int = 14
    audit_days: int = 90
    runtime_agents_days: int = 1
    max_snapshots_per_agent: int = 10

    @classmethod
    def from_env(cls) -> "GCConfig":
        import os
        return cls(
            enabled=os.getenv("SYNRIX_GC_ENABLED", "true").lower() == "true",
            interval_hours=int(os.getenv("SYNRIX_GC_INTERVAL_HOURS", "6")),
            metrics_days=int(os.getenv("SYNRIX_GC_METRICS_DAYS", "7")),
            events_days=int(os.getenv("SYNRIX_GC_EVENTS_DAYS", "14")),
            alerts_days=int(os.getenv("SYNRIX_GC_ALERTS_DAYS", "14")),
            audit_days=int(os.getenv("SYNRIX_GC_AUDIT_DAYS", "90")),
            runtime_agents_days=int(os.getenv("SYNRIX_GC_RUNTIME_AGENTS_DAYS", "1")),
            max_snapshots_per_agent=int(os.getenv("SYNRIX_GC_MAX_SNAPSHOTS", "10")),
        )


class GarbageCollector:
    """Prunes old data from the Octopoda backend."""

    def __init__(self, backend, config: GCConfig = None):
        self.backend = backend
        self.config = config or GCConfig.from_env()
        self._last_run = 0

    def run_gc(self) -> dict:
        """Run a full garbage collection cycle. Returns stats."""
        start = time.time()
        stats = {
            "metrics_deleted": 0,
            "events_deleted": 0,
            "alerts_deleted": 0,
            "audit_deleted": 0,
            "runtime_agents_deleted": 0,
            "snapshots_pruned": 0,
        }

        now = time.time()

        # 1. Prune metrics (highest volume)
        if self.config.metrics_days > 0:
            cutoff = now - (self.config.metrics_days * 86400)
            stats["metrics_deleted"] = self.backend.delete_prefix_before("metrics:", cutoff)

        # 2. Prune runtime events
        if self.config.events_days > 0:
            cutoff = now - (self.config.events_days * 86400)
            stats["events_deleted"] = self.backend.delete_prefix_before("runtime:events:", cutoff)

        # 3. Prune alerts
        if self.config.alerts_days > 0:
            cutoff = now - (self.config.alerts_days * 86400)
            stats["alerts_deleted"] = self.backend.delete_prefix_before("alerts:", cutoff)

        # 4. Prune audit trail
        if self.config.audit_days > 0:
            cutoff = now - (self.config.audit_days * 86400)
            stats["audit_deleted"] = self.backend.delete_prefix_before("audit:", cutoff)

        # 5. Prune runtime:agents:* (heartbeats + state) — fixes issue #6
        # Heartbeats write ~3x/sec per agent; without GC this prefix becomes
        # the dominant contributor to nodes-table growth (54% in one
        # reported production case before this prune was added).
        # The daemon only reads the most recent row per key, so 1-day
        # retention is safe; older versions are pure history nothing reads.
        if self.config.runtime_agents_days > 0:
            cutoff = now - (self.config.runtime_agents_days * 86400)
            stats["runtime_agents_deleted"] = self.backend.delete_prefix_before(
                "runtime:agents:", cutoff
            )

        # 6. Prune old snapshots (keep latest N per agent)
        stats["snapshots_pruned"] = self._prune_snapshots()

        # 7. VACUUM if we deleted a significant amount
        total_deleted = sum(v for k, v in stats.items() if isinstance(v, int))
        if total_deleted > 1000:
            self.backend.vacuum()
            stats["vacuumed"] = True

        elapsed_ms = (time.time() - start) * 1000
        stats["elapsed_ms"] = round(elapsed_ms, 1)
        self._last_run = now

        if total_deleted > 0:
            logger.info(
                "GC complete: %d entries pruned in %.1fms "
                "(metrics=%d events=%d alerts=%d audit=%d runtime_agents=%d snapshots=%d)",
                total_deleted, elapsed_ms,
                stats["metrics_deleted"], stats["events_deleted"],
                stats["alerts_deleted"], stats["audit_deleted"],
                stats["runtime_agents_deleted"], stats["snapshots_pruned"],
            )

        return stats

    def _prune_snapshots(self) -> int:
        """Keep only the latest N snapshots per agent."""
        max_snaps = self.config.max_snapshots_per_agent
        if max_snaps <= 0:
            return 0

        # Find all snapshot keys
        results = self.backend.query_prefix("agents:", limit=5000)
        agent_snapshots: dict[str, list] = {}

        for r in results:
            key = r.get("key", "")
            if ":snapshots:" in key:
                parts = key.split(":")
                if len(parts) >= 4:
                    agent_id = parts[1]
                    if agent_id not in agent_snapshots:
                        agent_snapshots[agent_id] = []
                    data = r.get("data", {})
                    val = data.get("value", data)
                    ts = val.get("created_at", 0) if isinstance(val, dict) else 0
                    agent_snapshots[agent_id].append({"key": key, "ts": ts})

        total_pruned = 0
        for agent_id, snapshots in agent_snapshots.items():
            if len(snapshots) <= max_snaps:
                continue
            # Sort by timestamp descending, delete the oldest beyond max
            snapshots.sort(key=lambda x: x["ts"], reverse=True)
            for snap in snapshots[max_snaps:]:
                if self.backend.delete(snap["key"]):
                    total_pruned += 1

        return total_pruned
