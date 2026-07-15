"""Agent identity + scoping.

Auto-instrument needs to decide WHICH agent a memory belongs to. Resolution
order (RFC § 5.3 / ARCHITECTURE.md):

    1. OCTOPODA_AGENT_ID env var          (explicit override)
    2. active `scope(...)` context manager (programmatic override)
    3. __main__ script filename slug       (best heuristic)
    4. "auto"                              (REPL / embedded fallback)

`scope()` is a context manager + decorator so a user with multiple agents in
one process can disambiguate:

    with octopoda.scope("billing-bot"):
        run_billing_agent()
"""

from __future__ import annotations

import contextvars
import os
import re
from contextlib import contextmanager
from pathlib import Path

_active_scope: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "octopoda_scope", default=None
)

_SLUG = re.compile(r"[^a-z0-9_]+")
_MAX_LEN = 64


def sanitize_agent_id(raw: str) -> str:
    """Lowercase, collapse non-alnum to underscores, trim, cap length."""
    slug = _SLUG.sub("_", raw.strip().lower()).strip("_")
    slug = slug[:_MAX_LEN].strip("_")
    return slug or "auto"


def _from_main_file() -> str | None:
    try:
        import __main__

        path = getattr(__main__, "__file__", None)
        if not path:
            return None
        stem = Path(path).stem
        if not stem or stem in {"__main__", "-c"}:
            return None
        return sanitize_agent_id(stem)
    except Exception:
        return None


def derive_agent_id() -> str:
    """Resolve the current agent id using the precedence above."""
    env = os.environ.get("OCTOPODA_AGENT_ID")
    if env and env.strip():
        return sanitize_agent_id(env)

    scoped = _active_scope.get()
    if scoped:
        return scoped

    from_file = _from_main_file()
    if from_file:
        return from_file

    return "auto"


@contextmanager
def scope(name: str):
    """Scope all auto-instrument writes within this block to `name`.

    Nests correctly: the previous scope is restored on exit (even on exception).
    """
    token = _active_scope.set(sanitize_agent_id(name))
    try:
        yield
    finally:
        _active_scope.reset(token)


def current_scope() -> str | None:
    """The currently active explicit scope, or None."""
    return _active_scope.get()
