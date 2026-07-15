"""Thin client over the EXISTING Octopoda cloud API.

This package does NOT reimplement any runtime logic. It calls the same
/v1/agents/{id}/remember and /v1/agents/{id}/similar endpoints the explicit SDK
and dashboard already use. All the heavy lifting (embedding, loop detection,
audit chain, RLS) stays server-side and unchanged.
"""

from __future__ import annotations

from .api import (
    CloudClient,
    MemoryHit,
    MockTransport,
    Response,
    Transport,
    UrllibTransport,
)

__all__ = [
    "CloudClient",
    "MemoryHit",
    "Transport",
    "Response",
    "UrllibTransport",
    "MockTransport",
]
