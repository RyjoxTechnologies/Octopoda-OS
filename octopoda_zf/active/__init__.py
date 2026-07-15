"""Active Memory — the agent-native memory engine (see docs/ACTIVE_MEMORY_RFC.md).

Phase A: query router + computed recall + sandbox. Shift from passive store
(retrieve + guess) to active memory (compute the answer, deterministically and
auditably). Gated by the router so the common agent turn is untouched.
"""

from __future__ import annotations

from .compute import ComputedRecall, ComputeResult
from .router import Route, RouteClass, is_hybrid, primary, route
from .sandbox import RestrictedSandbox, Sandbox, SandboxResult, literals_grounded

__all__ = [
    "route",
    "primary",
    "is_hybrid",
    "Route",
    "RouteClass",
    "ComputedRecall",
    "ComputeResult",
    "Sandbox",
    "RestrictedSandbox",
    "SandboxResult",
    "literals_grounded",
]
