"""Recall injection — turn retrieved memories into a system message.

The injector decides what (if anything) to prepend to an agent's prompt so it
"remembers" relevant context. It enforces the token + relevance budgets from
PERFORMANCE_BUDGET.md so injection never bloats the user's prompt or bill.
"""

from __future__ import annotations

from .injector import (
    InjectionConfig,
    build_injection,
    estimate_tokens,
    generous_injection_config,
    select_memories,
)

__all__ = [
    "InjectionConfig",
    "build_injection",
    "select_memories",
    "estimate_tokens",
    "generous_injection_config",
]
