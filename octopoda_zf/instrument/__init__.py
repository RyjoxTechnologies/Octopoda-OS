"""Auto-instrumentation — import hooks + monkey-patches per framework.

This is the translation layer (RFC § 5): it intercepts a framework's LLM call
sites, injects recall before, captures for extraction after, and routes
everything into the EXISTING cloud API. It adds no runtime logic of its own.

`base` holds the safe-patching machinery (idempotent, reversible, conflict-
aware). Each `<framework>.py` module is a concrete hook built on `base`.
"""

from __future__ import annotations

from .base import (
    PatchHandle,
    PatchRegistry,
    already_wrapped_by_other,
    apply_patch,
    global_registry,
    is_octopoda_wrapped,
    revert_all,
)

__all__ = [
    "PatchHandle",
    "PatchRegistry",
    "apply_patch",
    "revert_all",
    "is_octopoda_wrapped",
    "already_wrapped_by_other",
    "global_registry",
]
