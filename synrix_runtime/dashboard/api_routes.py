"""
Synrix Agent Runtime — Dashboard API Routes
All REST API endpoints for the dashboard.
"""

import time
import json
from flask import Blueprint, jsonify, request, Response
from synrix.agent_backend import get_synrix_backend

api = Blueprint("api", __name__)

_backend = None

def get_backend():
    global _backend
    if _backend is None:
        try:
            from synrix_runtime.core.daemon import RuntimeDaemon
            daemon = RuntimeDaemon.get_instance()
            if daemon.backend is not None:
                _backend = daemon.backend
                return _backend
        except Exception:
            pass
        from synrix_runtime.config import SynrixConfig
        config = SynrixConfig.from_env()
        _backend = get_synrix_backend(**config.get_backend_kwargs())
    return _backend


@api.route("/api/system/status")
def system_status():
    try:
        from synrix_runtime.core.daemon import RuntimeDaemon
        daemon = RuntimeDaemon.get_instance()
        return jsonify(daemon.get_system_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents")
def list_agents():
    try:
        from synrix_runtime.core.daemon import RuntimeDaemon
        daemon = RuntimeDaemon.get_instance()
        agents = daemon.get_active_agents()

        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector.get_instance(get_backend())

        enriched = []
        for agent in agents:
            agent_id = agent.get("agent_id", "")
            try:
                m = collector.get_agent_metrics(agent_id)
                agent["performance_score"] = m.performance_score
                agent["total_operations"] = m.total_operations
                agent["avg_write_latency_us"] = m.avg_write_latency_us
                agent["avg_read_latency_us"] = m.avg_read_latency_us
                agent["memory_node_count"] = m.memory_node_count
                agent["crash_count"] = m.crash_count
                agent["uptime_seconds"] = m.uptime_seconds
                agent["error_rate"] = m.error_rate
            except Exception:
                pass
            # Normalize: frontend uses "status", backend uses "state"
            agent["status"] = agent.get("state", "unknown")
            enriched.append(agent)

        return jsonify(enriched)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>")
def agent_detail(agent_id):
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector.get_instance(get_backend())
        m = collector.get_agent_metrics(agent_id)
        breakdown = collector.get_performance_breakdown(agent_id)

        from synrix_runtime.core.daemon import RuntimeDaemon
        daemon = RuntimeDaemon.get_instance()
        agents = daemon.get_all_agents()
        agent_info = next((a for a in agents if a.get("agent_id") == agent_id), {})

        return jsonify({
            "agent_id": agent_id,
            "info": agent_info,
            "metrics": {
                "total_operations": m.total_operations,
                "total_writes": m.total_writes,
                "total_reads": m.total_reads,
                "total_queries": m.total_queries,
                "avg_write_latency_us": m.avg_write_latency_us,
                "avg_read_latency_us": m.avg_read_latency_us,
                "crash_count": m.crash_count,
                "recovery_count": m.recovery_count,
                "memory_node_count": m.memory_node_count,
                "performance_score": m.performance_score,
                "uptime_seconds": m.uptime_seconds,
                "error_rate": m.error_rate,
            },
            "breakdown": breakdown,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>/memory")
def agent_memory(agent_id):
    try:
        backend = get_backend()
        results = backend.query_prefix(f"agents:{agent_id}:", limit=200)
        items = []
        for r in results:
            key = r.get("key", "")
            data = r.get("data", {})
            val = data.get("value", data)
            items.append({
                "key": key,
                "value": val,
                "node_id": r.get("id"),
                "size_bytes": len(json.dumps(val).encode()) if val else 0,
            })
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>/metrics")
def agent_metrics(agent_id):
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector.get_instance(get_backend())
        minutes = request.args.get("minutes", 60, type=int)
        metric_type = request.args.get("type", "write")
        series = collector.get_time_series(agent_id, metric_type, minutes)
        return jsonify(series)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>/audit")
def agent_audit(agent_id):
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(get_backend())
        events = audit.replay(agent_id)
        return jsonify(events)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>/replay")
def agent_replay(agent_id):
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(get_backend())
        from_ts = request.args.get("from", None, type=float)
        to_ts = request.args.get("to", None, type=float)
        events = audit.replay(agent_id, from_ts=from_ts, to_ts=to_ts)
        return jsonify(events)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/shared")
def shared_spaces():
    try:
        from synrix_runtime.api.shared_memory import SharedMemoryBus
        bus = SharedMemoryBus(get_backend())
        return jsonify(bus.list_spaces())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/shared/<space>")
def shared_space_detail(space):
    try:
        from synrix_runtime.api.shared_memory import SharedMemoryBus
        bus = SharedMemoryBus(get_backend())
        items = bus.get_all(space)
        changelog = bus.get_changelog(space, limit=20)
        return jsonify({"items": items, "changelog": changelog})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/metrics/system")
def system_metrics():
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector.get_instance(get_backend())
        m = collector.get_system_metrics()
        return jsonify({
            "total_agents": m.total_agents,
            "active_agents": m.active_agents,
            "total_operations": m.total_operations,
            "system_uptime_seconds": m.system_uptime_seconds,
            "mean_recovery_time_us": m.mean_recovery_time_us,
            "operations_per_minute": m.operations_per_minute,
            "total_crashes": m.total_crashes,
            "total_recoveries": m.total_recoveries,
            "most_active_agent": m.most_active_agent,
            "slowest_agent": m.slowest_agent,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/metrics/timeseries")
def metrics_timeseries():
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector.get_instance(get_backend())
        agent_id = request.args.get("agent_id", "")
        metric_type = request.args.get("type", "write")
        minutes = request.args.get("minutes", 60, type=int)
        series = collector.get_time_series(agent_id, metric_type, minutes)
        return jsonify(series)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/anomalies")
def anomalies():
    try:
        from synrix_runtime.monitoring.anomaly import AnomalyDetector
        detector = AnomalyDetector(get_backend())
        return jsonify(detector.get_all_anomalies())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/audit/timeline")
def audit_timeline():
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(get_backend())
        limit = request.args.get("limit", 50, type=int)
        return jsonify(audit.get_global_timeline(limit))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/audit/explain/<agent_id>/<timestamp>")
def audit_explain(agent_id, timestamp):
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(get_backend())
        return jsonify(audit.explain_decision(agent_id, float(timestamp)))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/recovery/history")
def recovery_history():
    try:
        from synrix_runtime.core.recovery import RecoveryOrchestrator
        orchestrator = RecoveryOrchestrator(get_backend())
        history = orchestrator.get_all_recovery_history()
        stats = orchestrator.get_recovery_stats()
        return jsonify({"history": history, "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>/similar")
def agent_semantic_search(agent_id):
    """Semantic search across an agent's memories."""
    try:
        from synrix_runtime.api.runtime import AgentRuntime
        q = request.args.get("q", "")
        limit = request.args.get("limit", 10, type=int)
        if not q:
            return jsonify({"error": "Query parameter 'q' is required"}), 400
        agent = AgentRuntime(agent_id)
        result = agent.recall_similar(q, limit=limit)
        return jsonify({
            "agent_id": agent_id,
            "query": q,
            "items": result.items,
            "count": result.count,
            "latency_us": result.latency_us,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>/history/<path:key>")
def agent_memory_history(agent_id, key):
    """Get version history of a memory key."""
    try:
        from synrix_runtime.api.runtime import AgentRuntime
        agent = AgentRuntime(agent_id)
        result = agent.recall_history(key)
        return jsonify({
            "agent_id": agent_id,
            "key": result.key,
            "current_version": result.current_version,
            "versions": result.versions,
            "latency_us": result.latency_us,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/agents/<agent_id>/related/<entity>")
def agent_related_entities(agent_id, entity):
    """Query the knowledge graph for entity relationships."""
    try:
        from synrix_runtime.api.runtime import AgentRuntime
        agent = AgentRuntime(agent_id)
        result = agent.related(entity)
        return jsonify({
            "agent_id": agent_id,
            "entity": result.entity,
            "entity_type": result.entity_type,
            "found": result.found,
            "relationships": result.relationships,
            "latency_us": result.latency_us,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/memory/browse")
def memory_browse():
    try:
        prefix = request.args.get("prefix", "")
        limit = request.args.get("limit", 100, type=int)
        backend = get_backend()

        start = time.perf_counter_ns()
        results = backend.query_prefix(prefix, limit=limit)
        latency_us = (time.perf_counter_ns() - start) / 1000

        items = []
        for r in results:
            key = r.get("key", "")
            data = r.get("data", {})
            val = data.get("value", data)
            items.append({
                "key": key,
                "value": val,
                "node_id": r.get("id"),
                "size_bytes": len(json.dumps(val).encode()) if val else 0,
            })
        return jsonify({"items": items, "count": len(items), "latency_us": latency_us})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/demo/start", methods=["POST"])
def demo_start():
    try:
        import threading
        from synrix_runtime.demo.three_agent_demo import run_demo
        t = threading.Thread(target=run_demo, daemon=True)
        t.start()
        return jsonify({"started": True, "message": "Three agent demo started"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/demo/crash/<agent_id>", methods=["POST"])
def demo_crash(agent_id):
    try:
        from synrix_runtime.api.system_calls import SystemCalls
        syscalls = SystemCalls(get_backend())
        result = syscalls.simulate_crash(agent_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/api/demo/reboot/<agent_id>", methods=["POST"])
def demo_reboot(agent_id):
    try:
        from synrix_runtime.api.system_calls import SystemCalls
        syscalls = SystemCalls(get_backend())
        result = syscalls.trigger_recovery(agent_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api.route("/stream/events")
def stream_events():
    from synrix_runtime.dashboard.sse import SSEManager
    manager = SSEManager(get_backend())
    return Response(
        manager.event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ---------------------------------------------------------------------------
# /v1 compatibility layer — the current octopodas.com dashboard bundle speaks
# the cloud API's /v1/* routes. Locally there is no auth and no billing, so
# auth endpoints return a local pseudo-identity and plan/settings endpoints
# return sensible local defaults. Data routes alias the /api handlers above.
# ---------------------------------------------------------------------------
from flask import redirect

_LOCAL_KEY = "sk-octopoda-local-mode"

@api.route("/v1/auth/login", methods=["POST"])
@api.route("/v1/auth/signup", methods=["POST"])
def v1_auth_local():
    body = request.get_json(silent=True) or {}
    return jsonify({
        "success": True, "api_key": _LOCAL_KEY, "tenant_id": "local",
        "email": body.get("email", "local@localhost"), "verified": True,
        "plan": "local", "first_name": body.get("first_name", "Local"),
        "last_name": body.get("last_name", "User"),
    })

@api.route("/v1/auth/me")
def v1_me():
    return jsonify({"tenant_id": "local", "email": "local@localhost",
                    "plan": "local", "verified": True, "company": "Local mode"})

@api.route("/v1/usage")
def v1_usage():
    return jsonify({"memories": {"used": 0, "limit": 999999},
                    "agents": {"used": 0, "limit": 999999}})

@api.route("/v1/settings", methods=["GET", "PUT"])
def v1_settings():
    return jsonify({"llm_provider": "local", "updated": request.method == "PUT"})

def _alias(view_name):
    def _fn(**kw):
        endpoint = api.name + "." + view_name
        from flask import current_app
        view = current_app.view_functions.get(endpoint)
        return view(**kw) if view else (jsonify({"error": "not available locally"}), 404)
    return _fn

_V1_MAP = {
    "/v1/agents": "list_agents",
    "/v1/agents/<agent_id>": "agent_detail",
    "/v1/agents/<agent_id>/metrics": "agent_metrics",
    "/v1/anomalies": "anomalies",
    "/v1/metrics/system": "system_metrics",
    "/v1/metrics/timeseries": "metrics_timeseries",
    "/v1/audit/timeline": "audit_timeline",
    "/v1/recovery/history": "recovery_history",
    "/v1/shared": "shared_spaces",
    "/v1/shared/<space>": "shared_space_detail",
}
for _path, _view in _V1_MAP.items():
    try:
        api.add_url_rule(_path, endpoint="v1_" + _view, view_func=_alias(_view))
    except Exception:
        pass

@api.route("/v1/<path:rest>", methods=["GET", "POST", "PUT", "DELETE"])
def v1_fallback(rest):
    # Unknown cloud-only endpoints (billing, loops v2 config, brain extras):
    # return an empty-but-valid shape so dashboard panels show empty states
    # instead of error toasts in local mode.
    return jsonify({"local_mode": True, "items": [], "events": [],
                    "history": [], "guards": [], "anomalies": []})
