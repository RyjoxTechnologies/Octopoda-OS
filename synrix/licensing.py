"""
Synrix Licensing — Tier Enforcement
=====================================
Agent-count and memory-per-agent limits enforced via HMAC-signed license keys.
Runs entirely offline — no phone-home required.

Tiers:
    Free:      3 agents, 10,000 memories per agent
    Starter:  10 agents, unlimited memories
    Pro:      25 agents, unlimited memories
    Unlimited: unlimited agents, unlimited memories

Usage:
    # Automatic — just set the env var and limits are enforced
    export OCTOPODA_LICENSE_KEY="synrix-license-..."

    # Or save to file
    echo "synrix-license-..." > ~/.synrix/license.key
"""

import os
import json
import hmac
import hashlib
import base64
import time
import sqlite3
import threading
from dataclasses import dataclass
from typing import Optional, Dict, List

from .exceptions import SynrixError


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

TIER_LIMITS = {
    "free":      {"max_agents": 3,  "max_memories_per_agent": 10_000},
    "starter":   {"max_agents": 10, "max_memories_per_agent": 0},
    "pro":       {"max_agents": 25, "max_memories_per_agent": 0},
    "unlimited": {"max_agents": 0,  "max_memories_per_agent": 0},
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LicenseError(SynrixError):
    """Base class for licensing errors."""
    pass


class AgentLimitError(LicenseError):
    """Raised when agent count exceeds the tier limit."""

    def __init__(self, current_count: int, max_agents: int, tier: str):
        self.current_count = current_count
        self.max_agents = max_agents
        self.tier = tier
        super().__init__(
            f"Agent limit reached: {current_count}/{max_agents} agents "
            f"on {tier} tier. Upgrade your license at https://octopodas.com/pricing "
            f"and set OCTOPODA_LICENSE_KEY in your environment."
        )


class MemoryLimitError(LicenseError):
    """Raised when memory count per agent exceeds the tier limit."""

    def __init__(self, agent_id: str, current_count: int, max_memories: int, tier: str):
        self.agent_id = agent_id
        self.current_count = current_count
        self.max_memories = max_memories
        self.tier = tier
        super().__init__(
            f"Memory limit reached for agent '{agent_id}': "
            f"{current_count}/{max_memories} memories on {tier} tier. "
            f"Upgrade your license at https://octopodas.com/pricing "
            f"and set OCTOPODA_LICENSE_KEY in your environment."
        )


# ---------------------------------------------------------------------------
# License claims
# ---------------------------------------------------------------------------

@dataclass
class LicenseClaims:
    tier: str
    max_agents: int
    max_memories_per_agent: int
    issued_at: int
    expires_at: int  # 0 = never expires
    subject: str     # customer email/id


# ---------------------------------------------------------------------------
# License key parsing & validation
# ---------------------------------------------------------------------------

# HMAC verification secret — loaded from environment variable at call time.
# Set SYNRIX_HMAC_SECRET in production (must match the signing secret).
_DEFAULT_HMAC_SECRET = b"synrix-hmac-verify-k8x92mPqR7nL4wB6yT1"


def _get_verify_secret() -> bytes:
    """Get the HMAC verification secret from environment or default."""
    env_val = os.environ.get("SYNRIX_HMAC_SECRET", "").strip()
    if env_val:
        return env_val.encode("utf-8")
    return _DEFAULT_HMAC_SECRET


def parse_license_key(key: str) -> Optional[LicenseClaims]:
    """
    Parse and validate a synrix-license-... key.

    Returns LicenseClaims on success, None if invalid or expired.
    """
    if not key or not key.startswith("synrix-license-"):
        return None

    try:
        body = key[len("synrix-license-"):]
        parts = body.rsplit(".", 1)
        if len(parts) != 2:
            return None

        payload_b64, sig_b64 = parts

        # Verify HMAC signature
        expected_sig = hmac.new(
            _get_verify_secret(),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        # Pad base64 for decoding
        sig_padded = sig_b64 + "=" * (4 - len(sig_b64) % 4) if len(sig_b64) % 4 else sig_b64
        provided_sig = base64.urlsafe_b64decode(sig_padded)

        if not hmac.compare_digest(expected_sig, provided_sig):
            return None

        # Decode payload
        payload_padded = payload_b64 + "=" * (4 - len(payload_b64) % 4) if len(payload_b64) % 4 else payload_b64
        payload_json = base64.urlsafe_b64decode(payload_padded)
        payload = json.loads(payload_json)

        # Check expiration
        exp = payload.get("exp", 0)
        if exp > 0 and time.time() > exp:
            return None

        tier = payload.get("tier", "free")
        if tier not in TIER_LIMITS:
            return None

        return LicenseClaims(
            tier=tier,
            max_agents=payload.get("max_agents", TIER_LIMITS[tier]["max_agents"]),
            max_memories_per_agent=payload.get(
                "max_memories_per_agent",
                TIER_LIMITS[tier]["max_memories_per_agent"],
            ),
            issued_at=payload.get("iat", 0),
            expires_at=exp,
            subject=payload.get("sub", ""),
        )
    except Exception:
        return None


def _generate_license_key(tier: str, email: str, expires_days: int = 0) -> str:
    """
    Generate a signed license key. Used internally for testing.
    In production, use tools/generate_license_key.py (not shipped with product).
    """
    if tier not in TIER_LIMITS:
        raise ValueError(f"Unknown tier: {tier}")

    limits = TIER_LIMITS[tier]
    payload = {
        "tier": tier,
        "max_agents": limits["max_agents"],
        "max_memories_per_agent": limits["max_memories_per_agent"],
        "iat": int(time.time()),
        "exp": int(time.time() + expires_days * 86400) if expires_days > 0 else 0,
        "sub": email,
    }

    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).rstrip(b"=").decode()

    sig = hmac.new(
        _get_verify_secret(),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

    return f"synrix-license-{payload_b64}.{sig_b64}"


# ---------------------------------------------------------------------------
# License key loading
# ---------------------------------------------------------------------------

def load_license_key() -> Optional[str]:
    """
    Load license key from environment or config file.
    Priority: OCTOPODA_LICENSE_KEY env var > ~/.octopoda/license.key
              (fallback to legacy ~/.synrix/license.key for older installs)
    """
    key = os.environ.get("OCTOPODA_LICENSE_KEY", "").strip()
    if key:
        return key

    for candidate in ("~/.octopoda/license.key", "~/.synrix/license.key"):
        license_file = os.path.expanduser(candidate)
        if os.path.exists(license_file):
            try:
                with open(license_file, "r") as f:
                    return f.read().strip()
            except Exception:
                pass

    return None


def get_current_claims() -> LicenseClaims:
    """
    Get current license claims. Returns free tier if no valid license found.
    """
    key = load_license_key()
    if key:
        claims = parse_license_key(key)
        if claims:
            return claims

    # Default: free tier
    return LicenseClaims(
        tier="free",
        max_agents=TIER_LIMITS["free"]["max_agents"],
        max_memories_per_agent=TIER_LIMITS["free"]["max_memories_per_agent"],
        issued_at=0,
        expires_at=0,
        subject="",
    )


# ---------------------------------------------------------------------------
# Persistent Agent Ledger
# ---------------------------------------------------------------------------

class AgentLedger:
    """
    Persistent ledger of registered agent IDs.

    Stored in a dedicated SQLite DB (separate from main data store).
    Survives process restarts. Thread-safe.
    """

    _instance: Optional["AgentLedger"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: str = None) -> "AgentLedger":
        """Get or create the singleton ledger instance."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
            return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton (for testing)."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.close()
            cls._instance = None

    def __init__(self, db_path: str = None):
        if db_path is None:
            data_dir = os.path.expanduser("~/.synrix/data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "agent_ledger.db")
        else:
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        self._db_path = db_path
        self._write_lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    memory_count INTEGER DEFAULT 0,
                    active INTEGER DEFAULT 1
                );
            """)
            conn.commit()
        finally:
            conn.close()

    def register_agent(self, agent_id: str) -> bool:
        """
        Register an agent. Returns True if newly registered or reactivated,
        False if already active. Does NOT check limits — caller does that.
        """
        with self._write_lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT agent_id, active FROM agents WHERE agent_id = ?",
                    (agent_id,),
                ).fetchone()

                if row:
                    if not row["active"]:
                        # Reactivate
                        conn.execute(
                            "UPDATE agents SET active = 1 WHERE agent_id = ?",
                            (agent_id,),
                        )
                        conn.commit()
                        return True
                    return False  # Already active

                # New agent
                conn.execute(
                    "INSERT INTO agents (agent_id, created_at, memory_count, active) VALUES (?, ?, 0, 1)",
                    (agent_id, time.time()),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    def is_registered(self, agent_id: str) -> bool:
        """Check if an agent is currently registered and active."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT agent_id FROM agents WHERE agent_id = ? AND active = 1",
                (agent_id,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_active_count(self) -> int:
        """Count active agents."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM agents WHERE active = 1"
            ).fetchone()
            return row["cnt"]
        finally:
            conn.close()

    def get_active_agents(self) -> List[str]:
        """List all active agent IDs."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT agent_id FROM agents WHERE active = 1 ORDER BY created_at"
            ).fetchall()
            return [r["agent_id"] for r in rows]
        finally:
            conn.close()

    def get_memory_count(self, agent_id: str) -> int:
        """Get current memory count for an agent."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT memory_count FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            return row["memory_count"] if row else 0
        finally:
            conn.close()

    def increment_memory_count(self, agent_id: str, delta: int = 1):
        """Increment the memory count after a successful write."""
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE agents SET memory_count = memory_count + ? WHERE agent_id = ?",
                    (delta, agent_id),
                )
                conn.commit()
            finally:
                conn.close()

    def deactivate_agent(self, agent_id: str):
        """Deactivate an agent (frees up an agent slot)."""
        with self._write_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE agents SET active = 0 WHERE agent_id = ?",
                    (agent_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def close(self):
        """No-op — connections are per-call."""
        pass


# ---------------------------------------------------------------------------
# Enforcement functions
# ---------------------------------------------------------------------------

def check_agent_limit(agent_id: str, ledger: AgentLedger = None, claims: LicenseClaims = None):
    """
    Check if this agent_id is allowed under the current tier.

    If the agent is already registered, always allows (no-op).
    If it's new and would exceed the limit, raises AgentLimitError.
    If allowed, registers the agent in the ledger.
    """
    if ledger is None:
        ledger = AgentLedger.get_instance()
    if claims is None:
        claims = get_current_claims()

    # Already registered — always allow
    if ledger.is_registered(agent_id):
        return

    # Check limit (0 = unlimited)
    if claims.max_agents > 0:
        current_count = ledger.get_active_count()
        if current_count >= claims.max_agents:
            raise AgentLimitError(current_count, claims.max_agents, claims.tier)

    # Register the new agent
    ledger.register_agent(agent_id)


def check_memory_limit(agent_id: str, ledger: AgentLedger = None, claims: LicenseClaims = None):
    """
    Check if this agent has exceeded its memory-per-agent limit.

    Raises MemoryLimitError if the agent has hit the limit.
    No-op if tier has unlimited memories (max_memories_per_agent == 0).
    """
    if ledger is None:
        ledger = AgentLedger.get_instance()
    if claims is None:
        claims = get_current_claims()

    # 0 = unlimited
    if claims.max_memories_per_agent <= 0:
        return

    current_count = ledger.get_memory_count(agent_id)
    if current_count >= claims.max_memories_per_agent:
        raise MemoryLimitError(
            agent_id, current_count, claims.max_memories_per_agent, claims.tier
        )


def record_memory_written(agent_id: str, ledger: AgentLedger = None):
    """Call after a successful memory write to update the count."""
    if ledger is None:
        ledger = AgentLedger.get_instance()
    ledger.increment_memory_count(agent_id)
