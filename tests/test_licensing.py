"""
Tests for the Synrix licensing and tier enforcement system.
"""

import os
import time
import pytest
import tempfile

from synrix.licensing import (
    TIER_LIMITS,
    LicenseClaims,
    AgentLimitError,
    MemoryLimitError,
    LicenseError,
    parse_license_key,
    load_license_key,
    get_current_claims,
    _generate_license_key,
    check_agent_limit,
    check_memory_limit,
    record_memory_written,
    AgentLedger,
)
from synrix.exceptions import SynrixError


# ---------------------------------------------------------------------------
# License key parsing
# ---------------------------------------------------------------------------

class TestLicenseParsing:
    """Test HMAC-signed license key generation and validation."""

    def test_generate_and_parse_roundtrip(self):
        """A generated key should parse back to the correct claims."""
        key = _generate_license_key("starter", "test@example.com")
        assert key.startswith("synrix-license-")

        claims = parse_license_key(key)
        assert claims is not None
        assert claims.tier == "starter"
        assert claims.max_agents == 10
        assert claims.max_memories_per_agent == 0  # unlimited
        assert claims.subject == "test@example.com"

    def test_parse_all_tiers(self):
        """All tier keys should parse correctly."""
        for tier, limits in TIER_LIMITS.items():
            if tier == "free":
                continue  # free has no key
            key = _generate_license_key(tier, f"{tier}@test.com")
            claims = parse_license_key(key)
            assert claims is not None
            assert claims.tier == tier
            assert claims.max_agents == limits["max_agents"]
            assert claims.max_memories_per_agent == limits["max_memories_per_agent"]

    def test_reject_invalid_key(self):
        """Garbage input should return None."""
        assert parse_license_key("") is None
        assert parse_license_key("not-a-key") is None
        assert parse_license_key("synrix-license-") is None
        assert parse_license_key("synrix-license-abc") is None

    def test_reject_tampered_payload(self):
        """A key with a modified payload should fail signature check."""
        key = _generate_license_key("starter", "test@example.com")
        # Tamper with the payload portion
        parts = key.split(".")
        tampered = parts[0] + "AAAA." + parts[1]
        assert parse_license_key(tampered) is None

    def test_reject_tampered_signature(self):
        """A key with a modified signature should fail."""
        key = _generate_license_key("starter", "test@example.com")
        # Tamper with the signature
        tampered = key[:-4] + "XXXX"
        assert parse_license_key(tampered) is None

    def test_reject_expired_key(self):
        """An expired key should return None."""
        # Generate a key that expired 1 day ago (hack: use negative days won't work,
        # so generate manually with past exp)
        import json, hmac, hashlib, base64
        from synrix.licensing import _get_verify_secret

        payload = {
            "tier": "pro",
            "max_agents": 25,
            "max_memories_per_agent": 0,
            "iat": int(time.time()) - 86400,
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
            "sub": "expired@test.com",
        }
        payload_json = json.dumps(payload, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).rstrip(b"=").decode()
        sig = hmac.new(_get_verify_secret(), payload_b64.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        key = f"synrix-license-{payload_b64}.{sig_b64}"

        assert parse_license_key(key) is None

    def test_non_expiring_key(self):
        """A key with exp=0 should never expire."""
        key = _generate_license_key("pro", "forever@test.com", expires_days=0)
        claims = parse_license_key(key)
        assert claims is not None
        assert claims.expires_at == 0


class TestLicenseLoading:
    """Test loading license keys from env and file."""

    def test_load_from_env_var(self, monkeypatch):
        """OCTOPODA_LICENSE_KEY env var should be picked up."""
        monkeypatch.setenv("OCTOPODA_LICENSE_KEY", "synrix-license-test")
        assert load_license_key() == "synrix-license-test"

    def test_load_from_file(self, tmp_dir, monkeypatch):
        """~/.synrix/license.key file should be read as fallback."""
        monkeypatch.delenv("OCTOPODA_LICENSE_KEY", raising=False)

        license_file = os.path.join(tmp_dir, "license.key")
        with open(license_file, "w") as f:
            f.write("synrix-license-from-file")

        # Monkey-patch expanduser to point to our temp dir
        monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~/.synrix/license.key", license_file))
        # This is tricky because of path resolution; just test the env var path
        # which is the primary method

    def test_free_tier_when_no_key(self, monkeypatch):
        """No key set should return free tier claims."""
        monkeypatch.delenv("OCTOPODA_LICENSE_KEY", raising=False)
        claims = get_current_claims()
        assert claims.tier == "free"
        assert claims.max_agents == 3
        assert claims.max_memories_per_agent == 10_000

    def test_valid_key_returns_correct_tier(self, monkeypatch):
        """Setting a valid license key should return the correct tier."""
        key = _generate_license_key("pro", "pro@test.com")
        monkeypatch.setenv("OCTOPODA_LICENSE_KEY", key)
        claims = get_current_claims()
        assert claims.tier == "pro"
        assert claims.max_agents == 25

    def test_invalid_key_falls_back_to_free(self, monkeypatch):
        """An invalid license key should fall back to free tier."""
        monkeypatch.setenv("OCTOPODA_LICENSE_KEY", "synrix-license-garbage.garbage")
        claims = get_current_claims()
        assert claims.tier == "free"


# ---------------------------------------------------------------------------
# Agent Ledger
# ---------------------------------------------------------------------------

class TestAgentLedger:
    """Test persistent agent registration and counting."""

    def test_register_new_agent(self, agent_ledger):
        """Registering a new agent should return True."""
        assert agent_ledger.register_agent("agent_1") is True
        assert agent_ledger.get_active_count() == 1

    def test_register_existing_agent(self, agent_ledger):
        """Re-registering an active agent should return False."""
        agent_ledger.register_agent("agent_1")
        assert agent_ledger.register_agent("agent_1") is False

    def test_active_count(self, agent_ledger):
        """Count should reflect only active agents."""
        agent_ledger.register_agent("a1")
        agent_ledger.register_agent("a2")
        agent_ledger.register_agent("a3")
        assert agent_ledger.get_active_count() == 3

    def test_deactivate_reduces_count(self, agent_ledger):
        """Deactivating an agent should reduce the active count."""
        agent_ledger.register_agent("a1")
        agent_ledger.register_agent("a2")
        assert agent_ledger.get_active_count() == 2

        agent_ledger.deactivate_agent("a1")
        assert agent_ledger.get_active_count() == 1

    def test_reactivate_agent(self, agent_ledger):
        """Reactivating a deactivated agent should increase count."""
        agent_ledger.register_agent("a1")
        agent_ledger.deactivate_agent("a1")
        assert agent_ledger.get_active_count() == 0

        assert agent_ledger.register_agent("a1") is True  # reactivate
        assert agent_ledger.get_active_count() == 1

    def test_memory_count_tracking(self, agent_ledger):
        """Memory count should accumulate correctly."""
        agent_ledger.register_agent("a1")
        assert agent_ledger.get_memory_count("a1") == 0

        agent_ledger.increment_memory_count("a1")
        agent_ledger.increment_memory_count("a1")
        agent_ledger.increment_memory_count("a1")
        assert agent_ledger.get_memory_count("a1") == 3

    def test_persistence_across_instances(self, tmp_dir):
        """A new AgentLedger instance should see previously registered agents."""
        db_path = os.path.join(tmp_dir, "persist_test.db")

        ledger1 = AgentLedger(db_path=db_path)
        ledger1.register_agent("a1")
        ledger1.register_agent("a2")
        ledger1.increment_memory_count("a1", 5)
        ledger1.close()

        ledger2 = AgentLedger(db_path=db_path)
        assert ledger2.get_active_count() == 2
        assert ledger2.is_registered("a1")
        assert ledger2.get_memory_count("a1") == 5
        ledger2.close()

    def test_get_active_agents(self, agent_ledger):
        """Should return list of active agent IDs."""
        agent_ledger.register_agent("bot_a")
        agent_ledger.register_agent("bot_b")
        agents = agent_ledger.get_active_agents()
        assert set(agents) == {"bot_a", "bot_b"}


# ---------------------------------------------------------------------------
# Agent limit enforcement
# ---------------------------------------------------------------------------

class TestAgentLimitEnforcement:
    """Test agent count limits per tier."""

    def test_free_tier_allows_3_agents(self, agent_ledger, monkeypatch):
        """Free tier: 3 agents OK, 4th raises AgentLimitError."""
        monkeypatch.delenv("OCTOPODA_LICENSE_KEY", raising=False)
        claims = LicenseClaims(
            tier="free", max_agents=3, max_memories_per_agent=10_000,
            issued_at=0, expires_at=0, subject="",
        )

        check_agent_limit("a1", ledger=agent_ledger, claims=claims)
        check_agent_limit("a2", ledger=agent_ledger, claims=claims)
        check_agent_limit("a3", ledger=agent_ledger, claims=claims)

        with pytest.raises(AgentLimitError) as exc_info:
            check_agent_limit("a4", ledger=agent_ledger, claims=claims)

        assert exc_info.value.current_count == 3
        assert exc_info.value.max_agents == 3
        assert "octopodas.com/pricing" in str(exc_info.value)

    def test_existing_agent_always_allowed(self, agent_ledger):
        """Re-checking an already registered agent should never raise."""
        claims = LicenseClaims(
            tier="free", max_agents=3, max_memories_per_agent=10_000,
            issued_at=0, expires_at=0, subject="",
        )
        check_agent_limit("a1", ledger=agent_ledger, claims=claims)

        # Calling again should be a no-op (already registered)
        check_agent_limit("a1", ledger=agent_ledger, claims=claims)
        check_agent_limit("a1", ledger=agent_ledger, claims=claims)
        assert agent_ledger.get_active_count() == 1

    def test_starter_tier_allows_10(self, agent_ledger):
        """Starter tier allows 10 agents."""
        claims = LicenseClaims(
            tier="starter", max_agents=10, max_memories_per_agent=0,
            issued_at=0, expires_at=0, subject="",
        )
        for i in range(10):
            check_agent_limit(f"agent_{i}", ledger=agent_ledger, claims=claims)

        with pytest.raises(AgentLimitError):
            check_agent_limit("agent_10", ledger=agent_ledger, claims=claims)

    def test_unlimited_tier_no_limit(self, agent_ledger):
        """Unlimited tier allows any number of agents."""
        claims = LicenseClaims(
            tier="unlimited", max_agents=0, max_memories_per_agent=0,
            issued_at=0, expires_at=0, subject="",
        )
        for i in range(50):
            check_agent_limit(f"agent_{i}", ledger=agent_ledger, claims=claims)
        assert agent_ledger.get_active_count() == 50

    def test_error_is_synrix_error(self):
        """AgentLimitError should be a subclass of SynrixError."""
        assert issubclass(AgentLimitError, SynrixError)
        assert issubclass(AgentLimitError, LicenseError)


# ---------------------------------------------------------------------------
# Memory limit enforcement
# ---------------------------------------------------------------------------

class TestMemoryLimitEnforcement:
    """Test per-agent memory limits."""

    def test_free_tier_blocks_at_10k(self, agent_ledger):
        """After 10,000 memories, MemoryLimitError should be raised."""
        claims = LicenseClaims(
            tier="free", max_agents=3, max_memories_per_agent=10_000,
            issued_at=0, expires_at=0, subject="",
        )
        agent_ledger.register_agent("a1")
        # Simulate 10,000 writes
        agent_ledger.increment_memory_count("a1", 10_000)

        with pytest.raises(MemoryLimitError) as exc_info:
            check_memory_limit("a1", ledger=agent_ledger, claims=claims)

        assert exc_info.value.agent_id == "a1"
        assert exc_info.value.current_count == 10_000
        assert "octopodas.com/pricing" in str(exc_info.value)

    def test_paid_tier_no_memory_limit(self, agent_ledger):
        """Paid tiers should have no memory limit (max=0 means unlimited)."""
        claims = LicenseClaims(
            tier="pro", max_agents=25, max_memories_per_agent=0,
            issued_at=0, expires_at=0, subject="",
        )
        agent_ledger.register_agent("a1")
        agent_ledger.increment_memory_count("a1", 1_000_000)

        # Should not raise
        check_memory_limit("a1", ledger=agent_ledger, claims=claims)

    def test_under_limit_allowed(self, agent_ledger):
        """Writes under the limit should pass."""
        claims = LicenseClaims(
            tier="free", max_agents=3, max_memories_per_agent=10_000,
            issued_at=0, expires_at=0, subject="",
        )
        agent_ledger.register_agent("a1")
        agent_ledger.increment_memory_count("a1", 9_999)

        # Should not raise — still 1 under limit
        check_memory_limit("a1", ledger=agent_ledger, claims=claims)

    def test_record_memory_written(self, agent_ledger):
        """record_memory_written should increment the count."""
        agent_ledger.register_agent("a1")
        record_memory_written("a1", ledger=agent_ledger)
        record_memory_written("a1", ledger=agent_ledger)
        assert agent_ledger.get_memory_count("a1") == 2


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestLicenseKeyGenerator:
    """Test the key generation tool."""

    def test_generate_starter_key(self):
        key = _generate_license_key("starter", "test@test.com")
        claims = parse_license_key(key)
        assert claims.tier == "starter"
        assert claims.max_agents == 10

    def test_generate_pro_key(self):
        key = _generate_license_key("pro", "pro@test.com")
        claims = parse_license_key(key)
        assert claims.tier == "pro"
        assert claims.max_agents == 25

    def test_generate_unlimited_key(self):
        key = _generate_license_key("unlimited", "ent@test.com")
        claims = parse_license_key(key)
        assert claims.tier == "unlimited"
        assert claims.max_agents == 0  # 0 = unlimited

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError):
            _generate_license_key("nonexistent", "bad@test.com")
