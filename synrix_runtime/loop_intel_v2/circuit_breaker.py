"""Cost circuit breaker — background watcher that auto-pauses spending agents.

Architecture:
  - Threshold config stored in `circuit_breaker_config` table (per-tenant,
    optional per-agent override)
  - Background daemon thread wakes every CHECK_INTERVAL seconds
  - For each allowlisted tenant, sums cost_usd from audit_v2 events written
    in the last WINDOW_SEC seconds, grouped by agent_id
  - If an agent's spend rate exceeds its threshold, calls
    LoopBreaker.pause_agent + emits a notification + records pause_count
  - Auto-resume is NOT done here — operator must explicitly resume after
    fixing the underlying cause

This is best-effort safety. It does NOT replace per-call cost limits or
proper agent code. It catches runaway loops before the bill arrives.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SEC = int(os.environ.get("OCTOPODA_CIRCUIT_BREAKER_INTERVAL", "30"))
WINDOW_SEC = int(os.environ.get("OCTOPODA_CIRCUIT_BREAKER_WINDOW", "60"))
DEFAULT_THRESHOLD_USD_PER_MIN = float(
    os.environ.get("OCTOPODA_CIRCUIT_BREAKER_DEFAULT_USD_PER_MIN", "0.50")
)


_thread_started = False
_thread_lock = threading.Lock()


def _get_resend_key() -> Optional[str]:
    val = os.environ.get("RESEND_API_KEY")
    if val:
        return val
    try:
        for line in open("/root/octopoda/.env"):
            if line.startswith("RESEND_API_KEY="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def _send_alert_email(to: str, agent_id: str, spend: float, threshold: float, tenant_id: str):
    key = _get_resend_key()
    if not key:
        logger.warning("RESEND_API_KEY missing; skipping circuit-breaker email")
        return
    body = {
        "from": "Octopoda Alerts <noreply@octopodas.com>",
        "to": [to],
        "subject": f"⚠️ Octopoda circuit breaker tripped — agent {agent_id}",
        "html": (
            f"<h2 style='color:#dc2626'>Circuit breaker auto-paused agent {agent_id}</h2>"
            f"<p>Spending in the last {WINDOW_SEC}s: <b>${spend:.4f}</b></p>"
            f"<p>Threshold: <b>${threshold:.2f}/min</b></p>"
            f"<p>Tenant: <code>{tenant_id}</code></p>"
            f"<p>The agent has been paused. Investigate the cause then resume "
            f"with <code>POST /v1/brain/resume/{agent_id}</code>.</p>"
        ),
    }
    try:
        subprocess.run(
            ["curl", "-s", "-X", "POST", "https://api.resend.com/emails",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(body)],
            timeout=10,
            capture_output=True,
        )
        logger.info("circuit-breaker email sent for agent %s", agent_id)
    except Exception as e:
        logger.warning("circuit-breaker email failed: %s", e)


def _resolve_threshold(cur, tenant_id: str, agent_id: str) -> Optional[Tuple[float, Optional[str], int]]:
    """Return (threshold_usd_per_min, notify_email, config_id) or None.

    Per-agent override beats tenant-default. enabled=false means no check.
    """
    # Per-agent override
    cur.execute(
        """SELECT threshold_usd_per_min, notify_email, id, enabled
           FROM circuit_breaker_config
           WHERE tenant_id = %s AND agent_id = %s
           LIMIT 1""",
        (tenant_id, agent_id),
    )
    row = cur.fetchone()
    if row:
        thr, email, cid, enabled = row
        if not enabled:
            return None
        return float(thr), email, cid

    # Tenant default (agent_id IS NULL)
    cur.execute(
        """SELECT threshold_usd_per_min, notify_email, id, enabled
           FROM circuit_breaker_config
           WHERE tenant_id = %s AND agent_id IS NULL
           LIMIT 1""",
        (tenant_id,),
    )
    row = cur.fetchone()
    if row:
        thr, email, cid, enabled = row
        if not enabled:
            return None
        return float(thr), email, cid

    return None


def compute_recent_spend(conn, tenant_id: str) -> Dict[str, float]:
    """Sum cost_usd over the last WINDOW_SEC seconds, grouped by agent_id.

    Reads from audit_v2 events stored in the nodes table with name prefix
    `auditv2:{tenant_short}:{agent_id}:...`.

    Returns {agent_id: spend_usd_in_window}.
    """
    cur = conn.cursor()
    cur.execute("SELECT set_config('app.tenant_id', %s, FALSE)", (tenant_id,))
    cur.execute("SET LOCAL statement_timeout = '5s'")

    cutoff = time.time() - WINDOW_SEC
    # Use valid_until=0 to hit the partial index idx_nodes_name_prefix.
    # auditv2 events are append-only — each unique key has valid_until=0.
    cur.execute(
        """
        SELECT data, valid_from
        FROM nodes
        WHERE tenant_id = %s
          AND name LIKE 'auditv2:%%'
          AND valid_until = 0
          AND valid_from >= %s
        LIMIT 5000
        """,
        (tenant_id, cutoff),
    )
    by_agent: Dict[str, float] = {}
    for data, _ts in cur.fetchall():
        if not isinstance(data, dict):
            continue
        # Sometimes `data` is wrapped under "value" depending on writer path.
        ev = data.get("value", data)
        if not isinstance(ev, dict):
            continue
        agent = ev.get("agent_id")
        cost = ev.get("cost_usd", 0.0)
        if not agent:
            continue
        try:
            cost_f = float(cost or 0)
        except (TypeError, ValueError):
            cost_f = 0.0
        if cost_f <= 0:
            continue
        by_agent[agent] = by_agent.get(agent, 0.0) + cost_f
    return by_agent


def check_tenant(conn, tenant_id: str) -> List[Dict[str, object]]:
    """Run the circuit-breaker check for one tenant.

    For each agent with recent spend > threshold (and not already paused),
    pause the agent and emit a notification.

    Returns a list of action records describing what was done.
    """
    actions: List[Dict[str, object]] = []
    spend_by_agent = compute_recent_spend(conn, tenant_id)
    if not spend_by_agent:
        return actions

    cur = conn.cursor()
    for agent_id, spend in spend_by_agent.items():
        resolved = _resolve_threshold(cur, tenant_id, agent_id)
        if resolved is None:
            continue
        threshold_usd_per_min, notify_email, config_id = resolved
        # Spend in the WINDOW_SEC window vs. threshold (USD/min).
        rate_per_min = spend * (60.0 / WINDOW_SEC)
        if rate_per_min < threshold_usd_per_min:
            continue

        # Trip!
        try:
            from synrix_runtime.monitoring.brain import LoopBreaker
            LoopBreaker.pause_agent(
                tenant_id, agent_id,
                reason=f"circuit_breaker:spend=${spend:.4f}/{WINDOW_SEC}s>{threshold_usd_per_min}/min",
            )
            paused = True
        except Exception as e:
            logger.warning("circuit_breaker pause failed for %s: %s", agent_id, e)
            paused = False

        # Update pause_count + last_paused_at
        cur.execute(
            """UPDATE circuit_breaker_config
               SET pause_count = pause_count + 1,
                   last_paused_at = now(),
                   updated_at = now()
               WHERE id = %s""",
            (config_id,),
        )
        conn.commit()

        if notify_email and paused:
            _send_alert_email(notify_email, agent_id, spend, threshold_usd_per_min, tenant_id)

        actions.append({
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "spend_usd_in_window": round(spend, 4),
            "rate_usd_per_min": round(rate_per_min, 4),
            "threshold_usd_per_min": threshold_usd_per_min,
            "paused": paused,
            "notified": bool(notify_email and paused),
            "at": time.time(),
        })

    return actions


def run_check_for_all_allowlisted_tenants() -> List[Dict[str, object]]:
    """One-shot check across every tenant in ALLOWED_TENANTS."""
    from .api import ALLOWED_TENANTS
    from .api import _get_connection
    actions: List[Dict[str, object]] = []
    for tenant_id in ALLOWED_TENANTS:
        try:
            conn = _get_connection()
            try:
                actions.extend(check_tenant(conn, tenant_id))
            finally:
                conn.close()
        except Exception as e:
            logger.warning("circuit_breaker tenant %s check failed: %s", tenant_id, e)
    return actions


def _watcher_loop():
    logger.info("circuit-breaker watcher started (interval=%ds, window=%ds)",
                CHECK_INTERVAL_SEC, WINDOW_SEC)
    while True:
        try:
            actions = run_check_for_all_allowlisted_tenants()
            if actions:
                logger.warning("circuit-breaker tripped on %d agent(s): %s",
                               len(actions),
                               [a["agent_id"] for a in actions])
        except Exception as e:
            logger.warning("circuit-breaker watcher iteration failed: %s", e)
        time.sleep(CHECK_INTERVAL_SEC)


def start_watcher_once() -> bool:
    """Idempotent: start the background watcher if not already running."""
    global _thread_started
    with _thread_lock:
        if _thread_started:
            return False
        # Honor a flag — useful to disable in tests / dev.
        if os.environ.get("OCTOPODA_CIRCUIT_BREAKER_DISABLED") == "1":
            logger.info("circuit-breaker disabled via env; not starting watcher")
            _thread_started = True
            return False
        t = threading.Thread(target=_watcher_loop, daemon=True, name="circuit-breaker-watcher")
        t.start()
        _thread_started = True
        return True
