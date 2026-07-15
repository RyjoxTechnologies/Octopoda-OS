"""Safe monkey-patch machinery.

Every framework hook uses this so that patching is:

- **idempotent**: applying the same patch twice does NOT double-wrap
  (RFC Phase 2 acceptance criterion). Re-importing octopoda is safe.
- **reversible**: `revert_all()` restores every original, so a process can
  cleanly uninstall (RFC `octopoda.uninstall()`).
- **conflict-aware**: detects when a target is already wrapped by Sentry /
  OpenTelemetry / Datadog and records it (R10) rather than fighting them.

Markers used:
- `_octopoda_patched = True` on our wrapper.
- `_octopoda_original` points at the function we replaced (for revert).
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("octopoda.instrument")

# --- Re-entrancy guard -------------------------------------------------------
# Octopoda's OWN machinery (the extractor, supersession) makes LLM calls through
# the SAME SDK we patch. Without a guard, the extractor's openai.create call gets
# intercepted -> recall + capture fire -> extract again -> INFINITE LOOP / API burn.
# Any code path that calls an instrumented SDK on octopoda's behalf runs inside
# `reentrancy_guard()`; every wrapper checks `is_reentrant()` and, if set, passes
# straight through to the original (no recall, no capture). contextvars are
# per-thread/per-task, so this is correct for both the sync inline path and the
# async capture-worker thread (each sets the flag in its own context).
_reentrant: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "octopoda_reentrant", default=False
)


def is_reentrant() -> bool:
    """True if we're already inside an octopoda-internal call → skip instrumentation."""
    return _reentrant.get()


@contextlib.contextmanager
def reentrancy_guard():
    """Mark the current context as octopoda-internal so nested instrumented SDK
    calls (e.g. the extractor's own LLM call) are NOT re-instrumented."""
    token = _reentrant.set(True)
    try:
        yield
    finally:
        _reentrant.reset(token)


async def run_in_thread(fn: Callable[..., Any], *args: Any) -> Any:
    """Run a BLOCKING callable in the default thread executor without blocking the
    running event loop.

    Used by the async SDK wrappers so a synchronous recall (~110ms cloud round
    trip) doesn't stall the caller's loop. The current contextvars (active
    `scope()`, the re-entrancy flag) are copied into the worker thread, so agent
    identity + the re-entrancy guard stay correct off-thread."""
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    return await loop.run_in_executor(None, lambda: ctx.run(fn, *args))

# Attribute markers other instrumentation libraries set on their wrappers.
# Used only for detection/telemetry, never to modify their behavior.
_OTHER_WRAPPER_MARKERS = (
    "__wrapped__",            # functools.wraps / many libs
    "_sentry_patched",
    "_ddtrace_patched",
    "_otel_instrumented",
    "__opentelemetry_instrumented__",
)


@dataclass
class PatchHandle:
    """Record of one applied patch, enough to revert it."""

    target: Any           # the object/class holding the attribute
    attr: str             # attribute name that was replaced
    original: Callable    # the function we replaced
    wrapper: Callable     # our wrapper that's currently installed
    label: str = ""       # human label, e.g. "openai.Completions.create"

    def revert(self) -> bool:
        """Restore the original. Returns True if reverted, False if the current
        value is not our wrapper (someone patched on top of us — don't clobber)."""
        current = getattr(self.target, self.attr, None)
        if current is not self.wrapper:
            logger.warning(
                "skip revert of %s: current value is not our wrapper "
                "(something patched on top)", self.label or self.attr
            )
            return False
        setattr(self.target, self.attr, self.original)
        return True


@dataclass
class PatchRegistry:
    """Tracks applied patches for reversibility + introspection."""

    handles: list[PatchHandle] = field(default_factory=list)

    def add(self, handle: PatchHandle) -> None:
        self.handles.append(handle)

    def revert_all(self) -> int:
        """Revert in reverse order. Returns count reverted."""
        reverted = 0
        for handle in reversed(self.handles):
            if handle.revert():
                reverted += 1
        self.handles.clear()
        return reverted

    @property
    def labels(self) -> list[str]:
        return [h.label or h.attr for h in self.handles]


# Process-global registry (one Python process = one set of patches).
global_registry = PatchRegistry()


def is_octopoda_wrapped(fn: Any) -> bool:
    """True if `fn` is one of our wrappers."""
    return bool(getattr(fn, "_octopoda_patched", False))


def already_wrapped_by_other(fn: Any) -> str | None:
    """If `fn` looks wrapped by a non-octopoda instrumentation lib, return a
    short marker name; else None. Detection only — we don't modify their code."""
    for marker in _OTHER_WRAPPER_MARKERS:
        if hasattr(fn, marker):
            return marker
    return None


def apply_patch(
    target: Any,
    attr: str,
    wrapper_factory: Callable[[Callable], Callable],
    *,
    label: str = "",
    registry: PatchRegistry | None = None,
) -> PatchHandle | None:
    """Patch `target.attr` with `wrapper_factory(original)`.

    - Idempotent: if `target.attr` is already our wrapper, returns the existing
      handle (or None) without re-wrapping.
    - Records the handle for revert.
    - Logs (but does not block on) detected conflicts with other instrumentation.

    Returns the PatchHandle, or None if nothing was patched (already patched, or
    target missing the attribute).
    """
    reg = registry if registry is not None else global_registry

    original = getattr(target, attr, None)
    if original is None:
        logger.warning("apply_patch: %s has no attribute %r", target, attr)
        return None

    if is_octopoda_wrapped(original):
        # Already patched by us — idempotent no-op.
        logger.debug("apply_patch: %s.%s already octopoda-wrapped, skipping", label, attr)
        # Return the existing handle if we have one.
        for h in reg.handles:
            if h.target is target and h.attr == attr:
                return h
        return None

    other = already_wrapped_by_other(original)
    if other:
        logger.info(
            "apply_patch: %s.%s already wrapped by %s; octopoda will wrap on top "
            "(both will run)", label, attr, other
        )

    wrapper = wrapper_factory(original)
    # Tag the wrapper so future apply_patch calls are idempotent + revert works.
    wrapper._octopoda_patched = True       # type: ignore[attr-defined]
    wrapper._octopoda_original = original   # type: ignore[attr-defined]

    setattr(target, attr, wrapper)
    handle = PatchHandle(
        target=target, attr=attr, original=original, wrapper=wrapper, label=label or attr
    )
    reg.add(handle)
    logger.debug("apply_patch: wrapped %s.%s", label, attr)
    return handle


def revert_all(registry: PatchRegistry | None = None) -> int:
    """Revert every patch in the registry (default: the global one)."""
    reg = registry if registry is not None else global_registry
    return reg.revert_all()
