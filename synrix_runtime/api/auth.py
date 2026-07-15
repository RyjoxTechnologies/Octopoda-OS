"""
Synrix Cloud API - Authentication
===================================
API key authentication for the cloud API.
"""

import hashlib
import secrets
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class APIKeyInfo:
    key_id: str
    tenant_id: str
    key_hash: str
    created_at: float
    permissions: list


class APIKeyManager:
    """Manages API key creation and verification."""

    def __init__(self, backend=None, master_key: str = ""):
        self.backend = backend
        self.master_key = master_key
        self._master_hash = hashlib.sha256(master_key.encode()).hexdigest() if master_key else ""

    def create_key(self, tenant_id: str = "default", permissions: list = None) -> str:
        """Generate a new API key. Returns the raw key (shown only once)."""
        raw_key = f"sk-synrix-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = key_hash[:16]

        key_data = {
            "key_id": key_id,
            "tenant_id": tenant_id,
            "key_hash": key_hash,
            "permissions": permissions or ["read", "write"],
            "created_at": time.time(),
        }

        if self.backend:
            self.backend.write(f"auth:keys:{key_id}", key_data)

        return raw_key

    def verify_key(self, raw_key: str) -> Optional[APIKeyInfo]:
        """Verify an API key. Returns key info or None."""
        if not raw_key:
            return None

        # Strip "Bearer " prefix if present
        if raw_key.startswith("Bearer "):
            raw_key = raw_key[7:]

        # Check against master key (env var)
        if self.master_key and secrets.compare_digest(raw_key, self.master_key):
            return APIKeyInfo(
                key_id="master",
                tenant_id="default",
                key_hash=self._master_hash,
                created_at=0,
                permissions=["read", "write", "admin"],
            )

        # Check against stored keys
        if self.backend:
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            key_id = key_hash[:16]
            result = self.backend.read(f"auth:keys:{key_id}")
            if result:
                stored = result.get("data", {}).get("value", {})
                if stored.get("key_hash") == key_hash:
                    return APIKeyInfo(
                        key_id=stored["key_id"],
                        tenant_id=stored.get("tenant_id", "default"),
                        key_hash=key_hash,
                        created_at=stored.get("created_at", 0),
                        permissions=stored.get("permissions", ["read", "write"]),
                    )

        return None

    def is_auth_required(self) -> bool:
        """Check if authentication is configured."""
        return bool(self.master_key)
