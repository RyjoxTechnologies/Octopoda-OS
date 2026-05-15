"""
Octopoda Multi-Tenant Manager (PostgreSQL)
============================================
All tenant data lives in a single PostgreSQL database.
Row-Level Security (RLS) enforces isolation at the database level —
application bugs cannot leak data between tenants.

Architecture:
    PostgreSQL + pgvector + RLS
    Single database, single connection pool
    Each request sets: SET LOCAL app.tenant_id = '{tenant_id}'
"""

import os
import time
import logging
import hashlib
import secrets
import threading
import json
from typing import Dict, Optional, List

logger = logging.getLogger("octopoda.tenant")


# ---------------------------------------------------------------------------
# Secure password hashing (PBKDF2 — stdlib, no extra deps)
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 600_000  # OWASP 2023 recommendation for SHA256

def _hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 + random salt. Returns 'salt$hash'."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"{salt}${dk.hex()}"

def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored 'salt$hash' string.
    Also accepts legacy plain SHA256 hashes for migration."""
    if "$" in stored:
        salt, hash_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
        return secrets.compare_digest(dk.hex(), hash_hex)
    else:
        legacy = hashlib.sha256(password.encode()).hexdigest()
        return secrets.compare_digest(legacy, stored)

def _is_legacy_hash(stored: str) -> bool:
    return "$" not in stored


# ---------------------------------------------------------------------------
# PostgreSQL connection pool
# ---------------------------------------------------------------------------

_pg_pool = None
_pg_pool_lock = threading.Lock()


def _get_pg_pool(dsn: str = None):
    """Get or create the global PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is not None:
            return _pg_pool
        import psycopg2
        from psycopg2 import pool as pg_pool
        dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not dsn:
            raise ValueError("DATABASE_URL not set")
        _pg_pool = pg_pool.ThreadedConnectionPool(minconn=2, maxconn=int(os.environ.get("OCTOPODA_TENANT_POOL_MAX", "32")), dsn=dsn)
        return _pg_pool


def _reset_pg_pool():
    """Reset pool (for testing)."""
    global _pg_pool
    with _pg_pool_lock:
        if _pg_pool:
            _pg_pool.closeall()
        _pg_pool = None


class TenantManager:
    """
    Manages multi-tenant authentication and data isolation.
    Uses PostgreSQL for both the tenant registry and tenant data.
    RLS enforces isolation at the database level.
    """

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, data_dir: str = None, dsn: str = None) -> "TenantManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(data_dir=data_dir, dsn=dsn)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)."""
        cls._instance = None

    # Sentinels that mean "I'm a local user, don't try to authenticate against cloud."
    # Mirrors the MCP server's _LOCAL_SENTINELS. Closes audit issue #7 (Yeraze):
    # cloud_server.py used to require DATABASE_URL even in local install, so
    # OCTOPODA_API_KEY=local crashed with "DATABASE_URL not set" on the first
    # /v1/auth/me call.
    _LOCAL_SENTINELS = {"", "YOUR_KEY_HERE", "local", "offline", "dev", "none"}

    def __init__(self, data_dir: str = None, dsn: str = None):
        self._dsn = dsn or os.environ.get("DATABASE_URL", "")
        self._data_dir = data_dir or os.path.expanduser(
            os.environ.get("OCTOPODA_DATA_DIR")
            or os.environ.get("SYNRIX_DATA_DIR")
            or "~/.synrix/data"
        )
        # Local mode = no Postgres DSN configured. Single-tenant SQLite path.
        # OCTOPODA_LOCAL_MODE=1 forces local even if DATABASE_URL is set
        # (useful for self-hosted users who have a stray DSN in env).
        force_local = (os.environ.get("OCTOPODA_LOCAL_MODE", "") or "").strip().lower() in (
            "1", "true", "yes", "on"
        )
        self._local_mode = force_local or not bool(self._dsn)

        if self._local_mode:
            self._pool = None
            self._local_tenant = {
                "tenant_id": "_local",
                "email": "local@octopoda.local",
                "plan": "local",
                "name": "Local Mode",
                "created_at": time.time(),
                "verified": True,
                "api_key": "local",
            }
            logger.info(
                "TenantManager started in LOCAL mode (no DATABASE_URL). "
                "Single-tenant SQLite at %s. To use cloud, set DATABASE_URL.",
                self._data_dir,
            )
        else:
            self._pool = _get_pg_pool(self._dsn)
            self._local_tenant = None

        # Cache: tenant_id -> backend instance
        self._backends: Dict[str, object] = {}
        # Cache: (tenant_id, agent_id) -> AgentRuntime instance
        self._runtimes: Dict[tuple, object] = {}
        self._cache_lock = threading.Lock()

    def _conn(self):
        """Get a connection from the pool."""
        conn = self._pool.getconn()
        conn.autocommit = False
        return conn

    def _release(self, conn):
        """Return connection to pool."""
        try:
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        self._pool.putconn(conn)

    # ------------------------------------------------------------------
    # Tenant CRUD
    # ------------------------------------------------------------------

    def create_tenant(self, email: str, password: str, plan: str = "free",
                       first_name: str = "", last_name: str = "",
                       company: str = "", use_case: str = "") -> dict:
        """Create a new tenant account. Returns tenant_id + API key."""
        tenant_id = hashlib.sha256(email.lower().encode()).hexdigest()[:16]
        password_hash = _hash_password(password)
        api_key = f"sk-octopoda-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_prefix = api_key[:20]

        plan_limits = {
            "free":           (5,      5_000),
            "early_adopter":  (50,     100_000),
            "pro":            (25,     250_000),
            "business":       (75,     1_000_000),
            "scale":          (999999, 5_000_000),
            "enterprise":     (999999, 999_999_999),
        }
        max_agents, max_memories = plan_limits.get(plan, (5, 5_000))

        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tenants (tenant_id, email, password_hash, plan, "
                "max_agents, max_memories, first_name, last_name, company, use_case, verified) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)",
                (tenant_id, email.lower(), password_hash, plan, max_agents, max_memories,
                 first_name, last_name, company, use_case),
            )
            cur.execute(
                "INSERT INTO api_keys (key_hash, tenant_id, key_prefix, active) "
                "VALUES (%s, %s, %s, TRUE)",
                (key_hash, tenant_id, key_prefix),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return {"error": "Account already exists for this email", "success": False}
            raise
        finally:
            self._release(conn)

        return {
            "success": True,
            "tenant_id": tenant_id,
            "api_key": api_key,
            "email": email.lower(),
            "first_name": first_name,
            "last_name": last_name,
            "plan": plan,
            "max_agents": max_agents,
            "max_memories_per_agent": max_memories,
            "warning": "Save your API key — it will not be shown again.",
        }

    def set_verified(self, email: str, verified: bool = True):
        """Mark an email as verified."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tenants SET verified = %s WHERE email = %s AND active = TRUE",
                (verified, email.lower()),
            )
            conn.commit()
        finally:
            self._release(conn)

    def get_tenant_by_email(self, email: str) -> Optional[dict]:
        """Get tenant info by email address."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT tenant_id, email, password_hash, plan, max_agents, max_memories, "
                "active, verified, first_name, last_name, company, use_case, created_at "
                "FROM tenants WHERE email = %s AND active = TRUE",
                (email.lower(),),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["tenant_id", "email", "password_hash", "plan", "max_agents",
                    "max_memories_per_agent", "active", "verified", "first_name",
                    "last_name", "company", "use_case", "created_at"]
            return dict(zip(cols, row))
        finally:
            self._release(conn)

    def authenticate(self, email: str, password: str) -> Optional[dict]:
        """Authenticate with email + password. Returns tenant info or None."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT tenant_id, email, password_hash, plan, max_agents, max_memories, "
                "active, verified, first_name, last_name, company, use_case, created_at "
                "FROM tenants WHERE email = %s AND active = TRUE",
                (email.lower(),),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["tenant_id", "email", "password_hash", "plan", "max_agents",
                    "max_memories_per_agent", "active", "verified", "first_name",
                    "last_name", "company", "use_case", "created_at"]
            tenant = dict(zip(cols, row))

            if not _verify_password(password, tenant["password_hash"]):
                return None

            # Auto-migrate legacy SHA256 hashes to PBKDF2
            if _is_legacy_hash(tenant["password_hash"]):
                new_hash = _hash_password(password)
                cur.execute(
                    "UPDATE tenants SET password_hash = %s WHERE tenant_id = %s",
                    (new_hash, tenant["tenant_id"]),
                )
                conn.commit()

            return tenant
        finally:
            self._release(conn)

    def verify_api_key(self, raw_key: str) -> Optional[dict]:
        """Verify an API key. Returns {tenant_id, plan, max_agents, ...} or None."""
        if raw_key is None:
            raw_key = ""
        if raw_key.startswith("Bearer "):
            raw_key = raw_key[7:]
        raw_key = raw_key.strip()

        # Local-mode auth: accept the sentinels (or empty) as the local tenant.
        # In local mode there's no Postgres `api_keys` table to query against,
        # so any sentinel just passes through as the fixed _local tenant.
        # Audit fix §7 (Yeraze): pre-fix this would have hit the empty pool
        # and raised "DATABASE_URL not set" on the first auth check.
        if self._local_mode:
            if raw_key.lower() in self._LOCAL_SENTINELS:
                return dict(self._local_tenant, key_active=True,
                            tenant_active=True, max_agents=None,
                            max_memories_per_agent=None,
                            first_name="Local", last_name="User")
            # Cloud-shaped keys are still rejected in local mode — caller
            # probably meant to point at a real cloud server.
            if raw_key.startswith("sk-octopoda-"):
                logger.info(
                    "Cloud-shaped API key supplied to a local-mode server. "
                    "Set DATABASE_URL to enable multi-tenant cloud auth."
                )
            return None

        if not raw_key:
            return None
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT k.tenant_id, k.active as key_active, "
                "t.email, t.plan, t.max_agents, t.max_memories, t.active as tenant_active, "
                "t.verified, t.first_name, t.last_name "
                "FROM api_keys k JOIN tenants t ON k.tenant_id = t.tenant_id "
                "WHERE k.key_hash = %s",
                (key_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["tenant_id", "key_active", "email", "plan", "max_agents",
                    "max_memories_per_agent", "tenant_active", "verified",
                    "first_name", "last_name"]
            result = dict(zip(cols, row))

            if not result["key_active"] or not result["tenant_active"]:
                return None

            # Update last_used
            cur.execute(
                "UPDATE api_keys SET last_used = NOW() WHERE key_hash = %s",
                (key_hash,),
            )
            conn.commit()
            return result
        finally:
            self._release(conn)

    def create_session_key(self, tenant_id: str) -> Optional[str]:
        """Create an additional API key without deactivating existing ones (for login)."""
        api_key = f"sk-octopoda-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_prefix = api_key[:20]
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO api_keys (key_hash, tenant_id, key_prefix, active) "
                "VALUES (%s, %s, %s, TRUE)",
                (key_hash, tenant_id, key_prefix),
            )
            conn.commit()
        finally:
            self._release(conn)
        return api_key

    def regenerate_api_key(self, tenant_id: str) -> Optional[str]:
        """Deactivate old keys, generate a new one. Returns raw key."""
        api_key = f"sk-octopoda-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_prefix = api_key[:20]
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE api_keys SET active = FALSE WHERE tenant_id = %s", (tenant_id,))
            cur.execute(
                "INSERT INTO api_keys (key_hash, tenant_id, key_prefix, active) "
                "VALUES (%s, %s, %s, TRUE)",
                (key_hash, tenant_id, key_prefix),
            )
            conn.commit()
        finally:
            self._release(conn)
        return api_key

    def get_tenant(self, tenant_id: str) -> Optional[dict]:
        """Get tenant info by ID."""
        if self._local_mode:
            if tenant_id == "_local":
                return dict(self._local_tenant, max_agents=None,
                            max_memories_per_agent=None, active=True,
                            company=None, use_case=None,
                            first_name="Local", last_name="User")
            return None
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT tenant_id, email, plan, max_agents, max_memories, "
                "active, verified, first_name, last_name, company, use_case, created_at "
                "FROM tenants WHERE tenant_id = %s AND active = TRUE",
                (tenant_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["tenant_id", "email", "plan", "max_agents", "max_memories_per_agent",
                    "active", "verified", "first_name", "last_name", "company",
                    "use_case", "created_at"]
            return dict(zip(cols, row))
        finally:
            self._release(conn)

    def list_tenants(self) -> List[dict]:
        """List all active tenants (admin only)."""
        if self._local_mode:
            return [dict(self._local_tenant)]
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT tenant_id, email, plan, created_at, max_agents, max_memories "
                "FROM tenants WHERE active = TRUE ORDER BY created_at DESC"
            )
            cols = ["tenant_id", "email", "plan", "created_at", "max_agents", "max_memories_per_agent"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            self._release(conn)

    # ------------------------------------------------------------------
    # Backend / Runtime isolation
    # ------------------------------------------------------------------

    def get_backend(self, tenant_id: str):
        """Get or create an isolated backend for a tenant.
        Cloud mode: PostgreSQL with RLS (tenant_id set on every connection).
        Local mode: shared SQLite backend (audit fix §7 — Yeraze).
        """
        with self._cache_lock:
            if tenant_id in self._backends:
                return self._backends[tenant_id]

        from synrix.agent_backend import SynrixAgentBackend

        if self._local_mode:
            # Single-tenant SQLite. No RLS, no DSN. Caches per tenant_id
            # (always "_local" in practice) so repeat lookups are O(1).
            backend = SynrixAgentBackend(
                backend="sqlite",
            )
        else:
            backend = SynrixAgentBackend(
                backend="postgres",
                dsn=self._dsn,
                tenant_id=tenant_id,
            )

        with self._cache_lock:
            self._backends[tenant_id] = backend
        return backend

    def get_runtime(self, tenant_id: str, agent_id: str, register: bool = False):
        """Get or create an AgentRuntime isolated to a specific tenant.

        Args:
            register: If True, write agent state to DB (for POST /v1/agents).
                      If False, just create the runtime without registering
                      (for recall/search on existing agents).
        """
        cache_key = (tenant_id, agent_id)
        with self._cache_lock:
            if cache_key in self._runtimes:
                return self._runtimes[cache_key]

        if register:
            # Check agent limit only when registering new agents. Local mode
            # sets max_agents=None (uncapped). Skip the comparison entirely
            # in that case to avoid TypeError on `int >= None`.
            tenant = self.get_tenant(tenant_id)
            if tenant and tenant.get("max_agents") is not None:
                agent_count = self.count_agents(tenant_id)
                if agent_count >= tenant["max_agents"]:
                    raise TenantLimitError(
                        f"Agent limit reached: {agent_count}/{tenant['max_agents']} "
                        f"on {tenant['plan']} plan. Upgrade at https://octopodas.com/pricing"
                    )

        from synrix_runtime.api.runtime import AgentRuntime

        backend = self.get_backend(tenant_id)

        runtime = AgentRuntime(
            agent_id, agent_type="cloud",
            metadata={"tenant_id": tenant_id},
            backend_override=backend,
            tenant_id=tenant_id,
        )

        # Only register agent in DB when explicitly asked (POST /v1/agents)
        if register:
            now = time.time()
            try:
                backend.write(f"runtime:agents:{agent_id}:state", {"value": "running"})
                backend.write(f"runtime:agents:{agent_id}:type", {"value": "cloud"})
                backend.write(f"runtime:agents:{agent_id}:registered_at", {"value": now})
            except Exception:
                pass

        with self._cache_lock:
            self._runtimes[cache_key] = runtime
        return runtime

    def count_agents(self, tenant_id: str) -> int:
        """Count active agents for a tenant."""
        try:
            backend = self.get_backend(tenant_id)
            results = backend.query_prefix("runtime:agents:", limit=500)
            # Build a set of all agent IDs, then remove deregistered ones
            all_agents = set()
            deregistered = set()
            for r in results:
                key = r.get("key", "")
                parts = key.split(":")
                if len(parts) >= 3 and parts[2] != "system":
                    aid = parts[2]
                    all_agents.add(aid)
                    # Check :state keys for deregistered status
                    if len(parts) >= 4 and parts[3] == "state":
                        data = r.get("data", {})
                        state = data.get("value", data)
                        if isinstance(state, dict):
                            state = state.get("value", "")
                        if str(state) == "deregistered":
                            deregistered.add(aid)
            return len(all_agents - deregistered)
        except Exception:
            return 0

    def get_tenant_agents(self, tenant_id: str) -> List[dict]:
        """List all agents for a specific tenant."""
        try:
            backend = self.get_backend(tenant_id)
            results = backend.query_prefix("runtime:agents:", limit=500)
            agents = {}
            for r in results:
                key = r.get("key", "")
                parts = key.split(":")
                if len(parts) >= 3:
                    aid = parts[2]
                    if aid == "system":
                        continue
                    if aid not in agents:
                        agents[aid] = {"agent_id": aid}
                    if len(parts) > 3:
                        data = r.get("data", {})
                        value = data.get("value", data)
                        if isinstance(value, dict) and "value" in value:
                            value = value["value"]
                        agents[aid][parts[3]] = value
            # Filter out deregistered agents
            return [a for a in agents.values() if a.get("state") != "deregistered"]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # GDPR: Data export & account deletion
    # ------------------------------------------------------------------

    def export_tenant_data(self, tenant_id: str) -> dict:
        """Export all tenant data as a JSON-serializable dict (GDPR Article 20)."""
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return {"error": "Tenant not found"}

        export = {
            "account": {
                "tenant_id": tenant["tenant_id"],
                "email": tenant["email"],
                "plan": tenant["plan"],
                "created_at": str(tenant["created_at"]),
                "max_agents": tenant["max_agents"],
            },
            "agents": [],
            "memories": [],
        }

        try:
            backend = self.get_backend(tenant_id)
            export["agents"] = self.get_tenant_agents(tenant_id)
            results = backend.query_prefix("agents:", limit=100000)
            for r in results:
                data = r.get("data", {})
                val = data.get("value", data)
                export["memories"].append({"key": r.get("key", ""), "value": val})
        except Exception:
            pass

        return export

    def delete_tenant(self, tenant_id: str) -> dict:
        """Permanently delete a tenant account and all their data (GDPR Article 17)."""
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return {"error": "Tenant not found", "deleted": False}

        # 1. Remove from runtime caches
        with self._cache_lock:
            self._backends.pop(tenant_id, None)
            keys_to_remove = [k for k in self._runtimes if k[0] == tenant_id]
            for k in keys_to_remove:
                self._runtimes.pop(k, None)

        # 2. Delete all tenant data from Postgres (RLS not needed — admin connection)
        conn = self._conn()
        try:
            cur = conn.cursor()
            # Delete in order (foreign key constraints)
            cur.execute("DELETE FROM relationships WHERE tenant_id = %s", (tenant_id,))
            cur.execute("DELETE FROM entities WHERE tenant_id = %s", (tenant_id,))
            cur.execute("DELETE FROM fact_embeddings WHERE tenant_id = %s", (tenant_id,))
            cur.execute("DELETE FROM nodes WHERE tenant_id = %s", (tenant_id,))
            cur.execute("DELETE FROM tenant_settings WHERE tenant_id = %s", (tenant_id,))
            cur.execute("DELETE FROM api_keys WHERE tenant_id = %s", (tenant_id,))
            cur.execute("DELETE FROM tenants WHERE tenant_id = %s", (tenant_id,))
            conn.commit()
        finally:
            self._release(conn)

        return {"deleted": True, "tenant_id": tenant_id, "email": tenant["email"]}

    # ------------------------------------------------------------------
    # Usage stats
    # ------------------------------------------------------------------

    def get_tenant_usage(self, tenant_id: str) -> dict:
        """Get usage statistics for a tenant's dashboard."""
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return {"error": "Tenant not found"}

        agent_count = self.count_agents(tenant_id)
        memory_count = 0
        try:
            backend = self.get_backend(tenant_id)
            results = backend.query_prefix("agents:", limit=100000)
            memory_count = len(results)
        except Exception:
            pass

        return {
            "tenant_id": tenant_id,
            "plan": tenant["plan"],
            "agents": {"used": agent_count, "limit": tenant["max_agents"]},
            "memories": {"used": memory_count, "limit": tenant["max_memories_per_agent"] * max(agent_count, 1)},
            "created_at": str(tenant["created_at"]),
        }

    # ------------------------------------------------------------------
    # Password management
    # ------------------------------------------------------------------

    def reset_password(self, email: str, new_password: str) -> dict:
        """Reset password without requiring old password (after code verification)."""
        if len(new_password) < 8:
            return {"error": "Password must be at least 8 characters", "success": False}
        new_hash = _hash_password(new_password)
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE tenants SET password_hash = %s WHERE email = %s AND active = TRUE",
                (new_hash, email.lower()),
            )
            conn.commit()
            if cur.rowcount == 0:
                return {"error": "Account not found", "success": False}
        finally:
            self._release(conn)
        return {"success": True}

    def change_password(self, tenant_id: str, old_password: str, new_password: str) -> dict:
        """Change tenant password. Requires old password verification."""
        conn = self._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT password_hash FROM tenants WHERE tenant_id = %s AND active = TRUE",
                (tenant_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "Tenant not found", "success": False}
            if not _verify_password(old_password, row[0]):
                return {"error": "Incorrect current password", "success": False}
            if len(new_password) < 8:
                return {"error": "Password must be at least 8 characters", "success": False}
            new_hash = _hash_password(new_password)
            cur.execute(
                "UPDATE tenants SET password_hash = %s WHERE tenant_id = %s",
                (new_hash, tenant_id),
            )
            conn.commit()
        finally:
            self._release(conn)
        return {"success": True}


class TenantLimitError(Exception):
    """Raised when a tenant exceeds their plan limits."""
    pass
