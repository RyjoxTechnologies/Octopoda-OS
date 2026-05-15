"""Smoke tests for CI — runs on Linux, macOS, Windows; Python 3.9+.

Fails the build if any documented path regresses. Zero external deps beyond
octopoda[mcp] itself. No API keys required — pure local mode.

What's covered:
  - Quick Start: AgentRuntime + remember + recall
  - SDK kwarg fixes (session_id isolation, return_messages types, crew_name kwarg)
  - MCP server module imports
  - Local dashboard serves /health when `octopoda` command is booted
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request

os.environ["SYNRIX_DATA_DIR"] = tempfile.mkdtemp(prefix="octopoda_ci_")
os.environ.pop("OCTOPODA_API_KEY", None)

results = []


def run(name, fn):
    try:
        fn()
        results.append((name, True, None))
        print(f"PASS  {name}")
    except Exception:
        tb = traceback.format_exc()
        results.append((name, False, tb))
        print(f"FAIL  {name}")
        for line in tb.splitlines()[-5:]:
            print(f"      {line}")


# ----- Quick Start -----
def quickstart():
    from octopoda import AgentRuntime
    agent = AgentRuntime("ci_smoke_qs")
    agent.remember("key", "value")
    result = agent.recall("key")
    assert result is not None, "recall returned None"


run("Quick Start: AgentRuntime + remember + recall", quickstart)


# ----- LangChain session_id isolation -----
def session_id_isolates():
    from octopoda import LangChainMemory
    a = LangChainMemory("ci_shared_agent", session_id="A")
    b = LangChainMemory("ci_shared_agent", session_id="B")
    a.save_context({"input": "I am Alice"}, {"output": "hi"})
    b.save_context({"input": "I am Bob"}, {"output": "hi"})
    assert "Bob" not in str(a.load_memory_variables({})), "session bleed A"
    assert "Alice" not in str(b.load_memory_variables({})), "session bleed B"


run("LangChainMemory(session_id=...) isolates sessions", session_id_isolates)


# ----- LangChain return_messages returns message objects (if langchain_core installed) -----
def return_messages_true():
    from octopoda import LangChainMemory
    m = LangChainMemory("ci_retmsg", return_messages=True)
    m.save_context({"input": "hello"}, {"output": "hi there"})
    value = m.load_memory_variables({})["history"]
    # With langchain_core available we get message objects; without it we fall back to string.
    # Either is acceptable — what matters is the content round-trips.
    try:
        import langchain_core  # noqa: F401
        assert isinstance(value, list), f"langchain_core installed so expected list, got {type(value).__name__}"
        assert all(hasattr(x, "content") for x in value), "not message objects"
        assert any(getattr(x, "content", "") == "hello" for x in value), "content missing"
    except ImportError:
        # No langchain_core — fallback path; just verify the content is present
        assert "hello" in str(value) and "hi there" in str(value), f"content lost: {value!r}"


run("LangChainMemory(return_messages=True) round-trips content", return_messages_true)


# ----- CrewAI crew_name kwarg -----
def crew_name_accepted():
    from octopoda import CrewAIMemory
    c = CrewAIMemory("ci_crew", crew_name="research-team")
    c.store_finding("r", "k", {"v": 1})
    assert c.get_finding("k") is not None


run("CrewAIMemory(crew_name=...) accepted", crew_name_accepted)


# ----- MCP server module imports + exposes main -----
def mcp_imports():
    import synrix_runtime.api.mcp_server as m
    assert hasattr(m, "main"), "mcp_server missing main()"


run("MCP server module imports with main() entrypoint", mcp_imports)


# ----- Local dashboard boots and serves the SPA -----
def dashboard_boots():
    """Boot `octopoda` CLI, confirm it accepts HTTP, serves the dashboard SPA."""
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "synrix_runtime.start"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        deadline = time.time() + 30
        last_err = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:7842/", timeout=2) as r:
                    assert r.status == 200, f"status={r.status}"
                    body = r.read().decode("utf-8", errors="replace")
                    # Must be the SPA shell, not a generic nginx or blank page
                    assert "<html" in body.lower(), "not HTML"
                    assert "octopoda" in body.lower() or "/assets/index-" in body, \
                        f"not the Octopoda dashboard: {body[:200]}"
                    return
            except Exception as e:
                last_err = e
                time.sleep(1)
        raise RuntimeError(f"dashboard didn't come up: {last_err}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


run("Local dashboard boots and serves the SPA", dashboard_boots)


# ----- Summary -----
passes = sum(1 for _, ok, _ in results if ok)
print()
print(f"{passes}/{len(results)} smoke tests passed")
sys.exit(0 if passes == len(results) else 1)
