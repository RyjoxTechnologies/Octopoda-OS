"""`octopoda-run` — the zero-friction CLI entry point (RFC Phase 3).

Usage:
    octopoda-run python your_agent.py [args...]   # run with auto-instrument active
    octopoda-run your_agent.py [args...]          # 'python' is implied
    octopoda-run doctor                           # diagnostics

Design — IN-PROCESS, not subprocess injection:
    We call `octopoda.init()` (which installs the late-import hook) and then run
    the user's script with `runpy` in THIS process. When the script imports a
    framework (openai, langchain, ...), the import hook fires and patches it.
    This is simpler and more reliable for our import-hook architecture than the
    `python -c "import octopoda; octopoda.init()"` subprocess trick, and it
    preserves stdout/stderr ordering and exit-code propagation for free.

Cloud-only (ADR-012): with no OCTOPODA_API_KEY, `init()` prints a clear "skipped"
notice and patches nothing — the user's script still runs (local mode unaffected),
just without auto-memory. `doctor` tells them exactly what's missing.
"""

from __future__ import annotations

import importlib.util
import os
import runpy
import sys

from ..init import (
    _CAPTURE_ONLY_REGISTRY,
    _DISPLAY_NAME,
    _MESSAGE_REGISTRY,
    DASHBOARD_URL,
)
from ..scope import derive_agent_id

_USAGE = (
    "usage:\n"
    "  octopoda-run python your_agent.py [args...]   run a script with auto-instrument\n"
    "  octopoda-run your_agent.py [args...]          ('python' is implied)\n"
    "  octopoda-run doctor                           diagnostics\n"
)


def _installed(module: str) -> bool:
    """True if a module is importable, without importing it. Tolerant of the
    namespace-package / missing-parent edge cases find_spec can raise on."""
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _detection_keys() -> list[str]:
    return list(_MESSAGE_REGISTRY) + list(_CAPTURE_ONLY_REGISTRY)


def doctor() -> int:
    """Diagnostics: keys present, agent id, dashboard, which frameworks are
    installed, and concrete fixes for whatever is missing."""
    has_octo = bool(os.environ.get("OCTOPODA_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    keys = _detection_keys()
    detected = [k for k in keys if _installed(k)]
    octo_note = "set" if has_octo else "MISSING"
    openai_note = "set (extraction on)" if has_openai else "missing (recall-only)"

    print("octopoda doctor")
    print("=" * 48)
    print(f"  OCTOPODA_API_KEY : {octo_note}")
    print(f"  OPENAI_API_KEY   : {openai_note}")
    print(f"  agent_id         : {derive_agent_id()}")
    print(f"  dashboard        : {DASHBOARD_URL}")
    print("  frameworks (installed in this env):")
    for k in keys:
        mark = "x" if _installed(k) else " "
        print(f"    [{mark}] {_DISPLAY_NAME.get(k, k)}")

    fixes = []
    if not has_octo:
        fixes.append("set OCTOPODA_API_KEY (from the dashboard) to enable cloud memory")
    if not detected:
        fixes.append(
            "install a supported framework "
            "(openai, anthropic, langchain, crewai, autogen, openai-agents)"
        )
    if fixes:
        print("\n  suggested fixes:")
        for f in fixes:
            print(f"    - {f}")
    else:
        print("\n  all set — `octopoda-run python your_agent.py` will auto-instrument.")
    return 0


def _normalize_target(argv: list[str]) -> list[str]:
    """Drop a leading 'python'/'python3'/sys.executable so both
    'octopoda-run python s.py' and 'octopoda-run s.py' work."""
    if argv and (argv[0] in ("python", "python3") or argv[0] == sys.executable):
        return argv[1:]
    return argv


def run_script(argv: list[str]) -> int:
    """Run a user script with auto-instrument active, in this process."""
    argv = _normalize_target(argv)
    if not argv:
        print("octopoda-run: no script given\n" + _USAGE, file=sys.stderr)
        return 2
    script = argv[0]
    if not os.path.exists(script):
        print(f"octopoda-run: script not found: {script}", file=sys.stderr)
        return 2

    os.environ.setdefault("OCTOPODA_AUTO", "on")
    import octopoda_zf  # lazy: avoid import cost / cycles unless we actually run

    octopoda_zf.init()  # prints the banner (or the cloud-key-missing notice)

    # Present argv to the script exactly as if it were invoked directly.
    saved_argv = sys.argv
    sys.argv = [script, *argv[1:]]
    try:
        runpy.run_path(script, run_name="__main__")
        return 0
    except SystemExit as e:  # honor the script's own exit code
        if e.code is None:
            return 0
        return e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = saved_argv
        try:
            octopoda_zf.uninstall()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0
    if argv[0] == "doctor":
        return doctor()
    return run_script(argv)


if __name__ == "__main__":
    raise SystemExit(main())
