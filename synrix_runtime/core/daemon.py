"""
Octopoda Agent Runtime — Central Daemon
The central nervous system of the entire runtime.
"""

import os
import time
import json
import threading
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor
from synrix.agent_backend import get_synrix_backend
from synrix_runtime.log import get_logger

logger = get_logger("daemon")


class RuntimeDaemon:
    """Central daemon that manages agent lifecycle, heartbeat monitoring, and recovery."""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """Singleton access to the daemon."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    def __init__(self):
        self.backend = None
        self.running = False
        self._threads = []
        self._event_listeners = []
        self._boot_time = None
        self._total_ops = 0
        self._ops_lock = threading.Lock()

    def start(self):
        """Start the daemon — connect to Octopoda and launch all background threads."""
        # Connect to Octopoda with real persistent backend
        start = time.perf_counter_ns()
        try:
            from synrix_runtime.config import SynrixConfig
            config = SynrixConfig.from_env()
            self.backend = get_synrix_backend(**config.get_backend_kwargs())
        except Exception:
            # Fallback to auto-detection
            self.backend = get_synrix_backend(backend="auto")
        connect_us = (time.perf_counter_ns() - start) / 1000

        self._boot_time = time.time()
        self.running = True

        # Write system boot keys
        start = time.perf_counter_ns()
        self.backend.write("runtime:system:boot_time", {"value": self._boot_time}, metadata={"type": "system"})
        boot_write_us = (time.perf_counter_ns() - start) / 1000

        self.backend.write("runtime:system:version", {"value": "1.0.0"}, metadata={"type": "system"})
        self.backend.write("runtime:system:status", {"value": "running"}, metadata={"type": "system"})
        self.backend.write("runtime:system:agent_count", {"value": 0}, metadata={"type": "system"})

        logger.info("Connected to Octopoda in %.1fus (backend: %s)", connect_us, self.backend.backend_type)
        logger.info("Boot record written in %.1fus", boot_write_us)
        logger.info("Daemon running - PID: %s", threading.get_ident())

        # Cold-start recovery: run in background thread so API starts immediately
        self._start_thread("cold_start_recovery", self._cold_start_recovery_bg)

        # Start background threads
        self._start_thread("heartbeat_monitor", self._heartbeat_monitor_loop)
        self._start_thread("anomaly_detector", self._anomaly_detector_loop)
        self._start_thread("metrics_aggregator", self._metrics_aggregator_loop)
        self._start_thread("recovery_watchdog", self._recovery_watchdog_loop)
        self._start_thread("garbage_collector", self._gc_loop)

        return {"connect_latency_us": connect_us, "boot_write_latency_us": boot_write_us, "agents_recovered": 0}

    def _start_thread(self, name, target):
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def register_agent(self, agent_id: str, agent_type: str = "generic", metadata: dict = None) -> dict:
        """Register an agent with the runtime."""
        metadata = metadata or {}
        now = time.time()

        profile = {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "metadata": metadata,
            "registered_at": now,
        }

        start = time.perf_counter_ns()
        writes = [
            (f"runtime:agents:{agent_id}:profile", profile, {"type": "agent_profile"}),
            (f"runtime:agents:{agent_id}:state", {"value": "running"}, {"type": "agent_state"}),
            (f"runtime:agents:{agent_id}:type", {"value": agent_type}, {"type": "agent_type"}),
            (f"runtime:agents:{agent_id}:heartbeat", {"value": now}, {"type": "heartbeat"}),
            (f"runtime:agents:{agent_id}:stats", {"writes": 0, "reads": 0, "queries": 0, "crashes": 0, "recoveries": 0}, {"type": "agent_stats"}),
            (f"runtime:agents:{agent_id}:metadata", metadata, {"type": "agent_metadata"}),
            (f"runtime:agents:{agent_id}:registered_at", {"value": now}, {"type": "timestamp"}),
            (f"runtime:agents:{agent_id}:last_active", {"value": now}, {"type": "timestamp"}),
        ]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda w: self.backend.write(w[0], w[1], metadata=w[2]), writes))
        latency_us = (time.perf_counter_ns() - start) / 1000

        # Update agent count
        self._update_agent_count()

        self._increment_ops(8)
        self.emit_event("agent_registered", {"agent_id": agent_id, "agent_type": agent_type, "latency_us": latency_us})

        return {"agent_id": agent_id, "registered": True, "latency_us": latency_us}

    def deregister_agent(self, agent_id: str):
        """Mark agent as deregistered. Memory is never deleted."""
        self.backend.write(f"runtime:agents:{agent_id}:state", {"value": "deregistered"}, metadata={"type": "agent_state"})
        self.backend.write(f"runtime:agents:{agent_id}:last_active", {"value": time.time()}, metadata={"type": "timestamp"})
        self._update_agent_count()
        self.emit_event("agent_deregistered", {"agent_id": agent_id})

    def update_heartbeat(self, agent_id: str):
        """Update heartbeat timestamp for an agent."""
        now = time.time()
        self.backend.write(f"runtime:agents:{agent_id}:heartbeat", {"value": now}, metadata={"type": "heartbeat"})
        self.backend.write(f"runtime:agents:{agent_id}:last_active", {"value": now}, metadata={"type": "timestamp"})
        self._increment_ops(2)

    def get_agent_state(self, agent_id: str) -> Optional[str]:
        """Get current state of an agent."""
        result = self.backend.read(f"runtime:agents:{agent_id}:state")
        if result and "data" in result:
            data = result["data"]
            return data.get("value", {}).get("value") if isinstance(data.get("value"), dict) else data.get("value")
        return None

    def set_agent_state(self, agent_id: str, state: str):
        """Set agent state."""
        self.backend.write(f"runtime:agents:{agent_id}:state", {"value": state}, metadata={"type": "agent_state"})
        self.emit_event("agent_state_changed", {"agent_id": agent_id, "state": state})

    def get_all_agents(self) -> List[dict]:
        """Get all registered agents with their current state."""
        results = self.backend.query_prefix("runtime:agents:", limit=500)
        agents = {}
        for r in results:
            key = r.get("key", "")
            parts = key.split(":")
            if len(parts) >= 3:
                agent_id = parts[2]
                if agent_id not in agents:
                    agents[agent_id] = {"agent_id": agent_id}
                field = parts[3] if len(parts) > 3 else "unknown"
                data = r.get("data", {})
                value = data.get("value", data)
                if isinstance(value, dict) and "value" in value:
                    value = value["value"]
                agents[agent_id][field] = value

        # Filter out system keys and deregistered
        agent_list = []
        for aid, info in agents.items():
            if aid in ("system",):
                continue
            agent_list.append(info)
        return agent_list

    def get_active_agents(self) -> List[dict]:
        """Get only agents that are not deregistered."""
        return [a for a in self.get_all_agents() if a.get("state") != "deregistered"]

    def recover_agent(self, agent_id: str) -> dict:
        """Recover a crashed agent — restore full state from Synrix."""
        total_start = time.perf_counter_ns()

        # Step 1: Query agent memory
        step1_start = time.perf_counter_ns()
        memory_keys = self.backend.query_prefix(f"agents:{agent_id}:", limit=500)
        step1_us = (time.perf_counter_ns() - step1_start) / 1000

        # Step 2: Query snapshots
        step2_start = time.perf_counter_ns()
        snapshots = self.backend.query_prefix(f"agents:{agent_id}:snapshots:", limit=50)
        step2_us = (time.perf_counter_ns() - step2_start) / 1000

        # Step 3: Query task states
        step3_start = time.perf_counter_ns()
        tasks = self.backend.query_prefix(f"tasks:handoff:", limit=100)
        agent_tasks = [t for t in tasks if agent_id in json.dumps(t.get("data", {}))]
        step3_us = (time.perf_counter_ns() - step3_start) / 1000

        # Step 4: Reconstruct state
        step4_start = time.perf_counter_ns()
        recovered_state = {
            "memory_keys": len(memory_keys),
            "snapshots": len(snapshots),
            "pending_tasks": len(agent_tasks),
            "memory": memory_keys,
            "latest_snapshot": snapshots[-1] if snapshots else None,
        }
        step4_us = (time.perf_counter_ns() - step4_start) / 1000

        # Step 5: Write recovered state
        step5_start = time.perf_counter_ns()
        self.backend.write(f"runtime:agents:{agent_id}:state", {"value": "recovering"}, metadata={"type": "agent_state"})
        self.backend.write(f"runtime:agents:{agent_id}:state", {"value": "running"}, metadata={"type": "agent_state"})
        self.backend.write(f"runtime:agents:{agent_id}:heartbeat", {"value": time.time()}, metadata={"type": "heartbeat"})
        step5_us = (time.perf_counter_ns() - step5_start) / 1000

        total_us = (time.perf_counter_ns() - total_start) / 1000

        # Step 6: Log recovery event
        recovery_event = {
            "agent_id": agent_id,
            "recovery_time_us": total_us,
            "keys_restored": len(memory_keys),
            "snapshots_found": len(snapshots),
            "tasks_found": len(agent_tasks),
            "step_timings": {
                "query_memory_us": step1_us,
                "query_snapshots_us": step2_us,
                "query_tasks_us": step3_us,
                "reconstruct_us": step4_us,
                "write_state_us": step5_us,
            },
            "timestamp": time.time(),
        }
        self.backend.write(
            f"runtime:events:recovery:{agent_id}:{int(time.time()*1000000)}",
            recovery_event,
            metadata={"type": "recovery_event"}
        )

        self.emit_event("recovery_complete", recovery_event)
        self._increment_ops(10)

        return recovery_event

    def get_system_status(self) -> dict:
        """Get complete system status."""
        agents = self.get_all_agents()
        active = [a for a in agents if a.get("state") not in ("deregistered",)]

        uptime = time.time() - self._boot_time if self._boot_time else 0

        return {
            "status": "running" if self.running else "stopped",
            "uptime_seconds": round(uptime, 1),
            "boot_time": self._boot_time,
            "version": "1.0.0",
            "total_agents": len(agents),
            "active_agents": len(active),
            "agents": active,
            "total_operations": self._total_ops,
            "daemon_threads": len(self._threads),
        }

    def emit_event(self, event_type: str, payload: dict):
        """Write an event to Synrix and notify listeners."""
        ts = int(time.time() * 1000000)
        event = {
            "event_type": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }
        self.backend.write(f"runtime:events:{event_type}:{ts}", event, metadata={"type": "event"})

        for listener in self._event_listeners:
            try:
                listener(event)
            except Exception:
                pass

    def add_event_listener(self, callback):
        """Add a callback that receives all events."""
        self._event_listeners.append(callback)

    def remove_event_listener(self, callback):
        if callback in self._event_listeners:
            self._event_listeners.remove(callback)

    def _update_agent_count(self):
        agents = self.get_active_agents()
        self.backend.write("runtime:system:agent_count", {"value": len(agents)}, metadata={"type": "system"})

    def _increment_ops(self, count=1):
        with self._ops_lock:
            self._total_ops += count

    def _cold_start_recovery_bg(self):
        """Background wrapper for cold-start recovery."""
        try:
            self._cold_start_recovery()
        except Exception as e:
            logger.error("Background cold-start recovery error: %s", e)

    def _cold_start_recovery(self) -> int:
        """On daemon restart, detect agents that were running and recover them.

        Agents whose state is still 'running' from a previous session are stale —
        the daemon crashed or was stopped without clean shutdown. We mark them
        as crashed and trigger recovery so their memory is replayed.

        Returns the number of agents recovered.
        """
        recovered = 0
        try:
            agents = self.get_all_agents()
            for agent in agents:
                state = agent.get("state")
                agent_id = agent.get("agent_id")
                if not agent_id:
                    continue
                # Agents left in 'running' or 'recovering' state from a prior session
                # are stale — the previous daemon died without cleaning up
                if state in ("running", "recovering"):
                    logger.info("Cold-start: recovering stale agent '%s' (was %s)", agent_id, state)
                    try:
                        self.backend.write(
                            f"runtime:agents:{agent_id}:state",
                            {"value": "crashed"},
                            metadata={"type": "agent_state"},
                        )
                        self.recover_agent(agent_id)
                        recovered += 1
                    except Exception as e:
                        logger.error("Cold-start recovery failed for %s: %s", agent_id, e)
            if recovered > 0:
                logger.info("Cold-start recovery complete: %d agent(s) restored", recovered)
        except Exception as e:
            logger.error("Cold-start recovery error: %s", e, exc_info=True)
        return recovered

    def _heartbeat_monitor_loop(self):
        """Background thread: check agent heartbeats every 3 seconds."""
        while self.running:
            try:
                agents = self.get_all_agents()
                now = time.time()
                for agent in agents:
                    state = agent.get("state")
                    if state in ("deregistered", "crashed", "recovering"):
                        continue
                    heartbeat = agent.get("heartbeat")
                    if isinstance(heartbeat, (int, float)) and (now - heartbeat) > 10:
                        agent_id = agent.get("agent_id")
                        if agent_id:
                            self.set_agent_state(agent_id, "crashed")
                            ts = int(now * 1000000)
                            self.backend.write(
                                f"runtime:events:crash:{agent_id}:{ts}",
                                {"agent_id": agent_id, "reason": "heartbeat_timeout", "timestamp": now},
                                metadata={"type": "crash_event"}
                            )
                            self.emit_event("agent_crashed", {"agent_id": agent_id, "reason": "heartbeat_timeout"})
                            # Trigger recovery
                            try:
                                self.recover_agent(agent_id)
                            except Exception as e:
                                logger.error("Recovery failed for %s: %s", agent_id, e)
            except Exception as e:
                logger.error("Heartbeat monitor error: %s", e, exc_info=True)
            time.sleep(int(os.getenv("SYNRIX_HEARTBEAT_INTERVAL_SEC", "3")))

    def _anomaly_detector_loop(self):
        """Background thread: check for anomalies (default every 5 seconds, override via SYNRIX_ANOMALY_INTERVAL_SEC)."""
        while self.running:
            try:
                # Import here to avoid circular imports
                from synrix_runtime.monitoring.anomaly import AnomalyDetector
                detector = AnomalyDetector(self.backend)
                agents = self.get_active_agents()
                for agent in agents:
                    agent_id = agent.get("agent_id")
                    if agent_id:
                        anomalies = detector.check_for_anomalies(agent_id)
                        for anomaly in anomalies:
                            self.emit_event("anomaly_detected", anomaly)
            except Exception as e:
                logger.error("Anomaly detector error: %s", e, exc_info=True)
            time.sleep(int(os.getenv("SYNRIX_ANOMALY_INTERVAL_SEC", "5")))

    def _metrics_aggregator_loop(self):
        """Background thread: aggregate system metrics (default every 10 seconds, override via SYNRIX_METRICS_INTERVAL_SEC)."""
        while self.running:
            try:
                agents = self.get_active_agents()
                ts = int(time.time() * 1000000)
                self.backend.write(
                    f"metrics:system:ops:{ts}",
                    {"total_ops": self._total_ops, "agents_active": len(agents), "timestamp": time.time()},
                    metadata={"type": "system_metrics"}
                )
            except Exception as e:
                logger.error("Metrics aggregator error: %s", e, exc_info=True)
            time.sleep(int(os.getenv("SYNRIX_METRICS_INTERVAL_SEC", "10")))

    def _recovery_watchdog_loop(self):
        """Background thread: watch for agents needing recovery (default every 5 seconds, override via SYNRIX_RECOVERY_INTERVAL_SEC)."""
        while self.running:
            try:
                agents = self.get_all_agents()
                for agent in agents:
                    if agent.get("state") == "crashed":
                        agent_id = agent.get("agent_id")
                        if agent_id:
                            try:
                                self.recover_agent(agent_id)
                            except Exception as e:
                                logger.error("Watchdog recovery failed for %s: %s", agent_id, e)
            except Exception as e:
                logger.error("Recovery watchdog error: %s", e, exc_info=True)
            time.sleep(int(os.getenv("SYNRIX_RECOVERY_INTERVAL_SEC", "5")))

    def _gc_loop(self):
        """Background thread: run garbage collection periodically."""
        try:
            from synrix_runtime.core.gc import GCConfig, GarbageCollector
            gc_config = GCConfig.from_env()
            if not gc_config.enabled:
                logger.info("Garbage collection disabled")
                return
            gc = GarbageCollector(self.backend, gc_config)
            interval_seconds = gc_config.interval_hours * 3600
            logger.info(
                "GC started: interval=%dh, metrics=%dd, events=%dd, audit=%dd, runtime_agents=%dd",
                gc_config.interval_hours, gc_config.metrics_days,
                gc_config.events_days, gc_config.audit_days,
                gc_config.runtime_agents_days,
            )
        except Exception as e:
            logger.error("Failed to initialize GC: %s", e)
            return

        while self.running:
            try:
                stats = gc.run_gc()
                total = stats.get("metrics_deleted", 0) + stats.get("events_deleted", 0) + \
                        stats.get("alerts_deleted", 0) + stats.get("audit_deleted", 0) + \
                        stats.get("runtime_agents_deleted", 0) + stats.get("snapshots_pruned", 0)
                if total > 0:
                    logger.info("GC cycle: %d entries pruned in %.1fms", total, stats.get("elapsed_ms", 0))
            except Exception as e:
                logger.error("GC cycle error: %s", e, exc_info=True)
            # Sleep in small increments so shutdown is responsive
            for _ in range(interval_seconds):
                if not self.running:
                    break
                time.sleep(1)

    def shutdown(self):
        """Shutdown the daemon gracefully."""
        self.running = False
        if self.backend:
            self.backend.write("runtime:system:status", {"value": "stopped"}, metadata={"type": "system"})
        logger.info("Shutdown complete.")
