"""Code sandbox (Active Memory, mechanism M2 safety layer).

Computed recall executes model-written Python over retrieved facts. That code is
UNTRUSTED. This module defines the `Sandbox` interface so prod can swap in a real
isolate (managed micro-VM / seccomp subprocess), plus a `RestrictedSandbox` for
dev/benchmarks.

SECURITY (read this):
  RestrictedSandbox uses a restricted `exec` with an allowlisted builtin set, a
  custom import that permits only {datetime, math, statistics}, and a thread
  timeout. This blocks the casual cases (open/eval/network/import abuse) and is
  fine for OUR-OWN-model code in benchmarks. It is NOT a hard security boundary
  (a determined adversary can escape a Python restricted exec, and a thread
  can't be force-killed). PRODUCTION MUST use a real isolate behind this same
  interface. Documented as Risk S1 in ACTIVE_MEMORY_RFC.md.

Also provides `literals_grounded` — the anti-hallucination check: every numeric/
date literal in the code must appear in the facts (the model may not invent
values).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_ALLOWED_MODULES = {"datetime", "math", "statistics", "re"}

# Safe builtins only. Notably ABSENT: open, eval, exec, compile, input, exit,
# globals, locals, vars, getattr, setattr, __import__ (provided via guard).
_SAFE_BUILTINS = {
    "len": len, "sum": sum, "min": min, "max": max, "sorted": sorted,
    "abs": abs, "round": round, "range": range, "list": list, "dict": dict,
    "set": set, "tuple": tuple, "int": int, "float": float, "str": str,
    "bool": bool, "enumerate": enumerate, "zip": zip, "map": map,
    "filter": filter, "reversed": reversed, "any": any, "all": all,
    "divmod": divmod, "pow": pow, "print": lambda *a, **k: None,
}


@dataclass
class SandboxResult:
    ok: bool
    result: str = ""
    error: str = ""


@runtime_checkable
class Sandbox(Protocol):
    def run(self, code: str, timeout: float = 2.0) -> SandboxResult:
        ...


def _guarded_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root not in _ALLOWED_MODULES:
        raise ImportError(f"import of '{name}' is not allowed in the sandbox")
    return __import__(name, *args, **kwargs)


class RestrictedSandbox:
    """Dev/benchmark sandbox. See module docstring: NOT a hard boundary; prod
    swaps a real isolate behind the `Sandbox` interface."""

    def _safe_globals(self) -> dict:
        builtins = dict(_SAFE_BUILTINS)
        builtins["__import__"] = _guarded_import
        return {"__builtins__": builtins}

    def run(self, code: str, timeout: float = 2.0) -> SandboxResult:
        if not code or not code.strip():
            return SandboxResult(False, error="empty code")
        box: dict = {}

        def target():
            try:
                ns: dict = {}
                exec(code, self._safe_globals(), ns)  # noqa: S102 - sandboxed; see docstring
                box["result"] = ns.get("result")
            except Exception as e:  # any error -> caller falls back to NL
                box["error"] = f"{type(e).__name__}: {str(e)[:120]}"

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            # thread can't be force-killed in CPython; daemon dies with process.
            return SandboxResult(False, error="timeout")
        if "error" in box:
            return SandboxResult(False, error=box["error"])
        result = box.get("result")
        if result is None:
            return SandboxResult(False, error="no `result` variable set")
        return SandboxResult(True, result=str(result).strip())


# ---------------------------------------------------------------------------
# Anti-hallucination: literals in code must be grounded in the facts.
# ---------------------------------------------------------------------------

# numeric tokens (handles "1,200", "12.5"); the dash in "2026-02-17" splits it
# into 2026 / 02 / 17 — which is what we want for grounding date parts.
_NUM_TOKEN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CODE_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _norm_num(tok: str) -> str:
    """Normalize so '03' == '3', '1,200' == '1200', '12.0' == '12'."""
    t = tok.replace(",", "")
    try:
        f = float(t)
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return t


def _facts_numbers(facts: str) -> set[str]:
    return {_norm_num(t) for t in _NUM_TOKEN_RE.findall(facts)}


def literals_grounded(code: str, facts: str, *, allow_small: bool = True) -> bool:
    """True if every numeric literal in `code` is justified by the facts.

    Normalizes leading zeros / commas / trailing .0 so '3' matches a fact's '03'.
    `allow_small` permits 0/1/2 without grounding (structural: indices, range(2),
    +1 offsets) to avoid false rejects."""
    fact_nums = _facts_numbers(facts)
    for lit in _CODE_NUM_RE.findall(code):
        if allow_small and lit in {"0", "1", "2", "0.0", "1.0", "2.0"}:
            continue
        if _norm_num(lit) in fact_nums:
            continue
        return False
    return True
