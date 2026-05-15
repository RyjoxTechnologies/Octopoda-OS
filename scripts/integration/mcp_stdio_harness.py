"""MCP stdio harness — drive octopoda-mcp like Claude Code would.

Speaks JSON-RPC 2.0 over the subprocess stdio:
  1. spawn `octopoda-mcp`
  2. send `initialize`
  3. send `notifications/initialized`
  4. send `tools/list`
  5. invoke tools (`octopoda_status`, `octopoda_remember`, `octopoda_recall`)
  6. assert each response is well-formed and the round-trip works

This closes the last "as a user" gap from user_simulation.py. If this passes,
the MCP integration that Claude Code would use is actually functional.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import threading

PYBIN = "C:/Users/user/AppData/Local/Temp/mcp-test/venv/Scripts/python.exe"
MCP_BIN = "C:/Users/user/AppData/Local/Temp/mcp-test/venv/Scripts/octopoda-mcp.exe"
DATA_DIR = "/tmp/mcp-harness-data"
shutil.rmtree(DATA_DIR, ignore_errors=True)
os.makedirs(DATA_DIR, exist_ok=True)


class StdioMCPClient:
    """Minimal MCP client over a subprocess's stdio, JSON-RPC 2.0 framed
    by newlines (FastMCP's stdio transport uses line-delimited JSON-RPC).
    """

    def __init__(self, cmd, env=None):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        self._id = 0
        self._responses = {}
        self._lock = threading.Lock()
        self._stderr_buf = []
        # Reader threads — stdout (responses) and stderr (logs)
        self._stop = False
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mid = msg.get("id")
            if mid is not None:
                with self._lock:
                    self._responses[mid] = msg

    def _read_stderr(self):
        for line in self.proc.stderr:
            self._stderr_buf.append(line.decode("utf-8", "replace") if isinstance(line, bytes) else line)

    def call(self, method, params=None, timeout=15.0):
        with self._lock:
            self._id += 1
            rid = self._id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        line = (json.dumps(msg) + "\n").encode()
        self.proc.stdin.write(line)
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if rid in self._responses:
                    return self._responses.pop(rid)
            time.sleep(0.05)
        raise TimeoutError(f"MCP call {method} timed out after {timeout}s")

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()

    def stop(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def main():
    print("=" * 70)
    print("MCP STDIO HARNESS — drive octopoda-mcp like Claude Code would")
    print("=" * 70)
    print(f"Spawn:    {MCP_BIN}")
    print(f"Data dir: {DATA_DIR}")
    print()

    if not os.path.exists(MCP_BIN):
        print(f"ERROR: {MCP_BIN} not found. Run user_simulation.py first to install.")
        sys.exit(1)

    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["OCTOPODA_API_KEY"] = "local"
    env["OCTOPODA_DATA_DIR"] = DATA_DIR

    client = StdioMCPClient([MCP_BIN], env=env)
    results = []

    try:
        # 1. Initialize
        resp = client.call("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "harness", "version": "0.1"},
            "capabilities": {},
        })
        ok = "result" in resp and resp["result"].get("serverInfo", {}).get("name")
        server_name = resp.get("result", {}).get("serverInfo", {}).get("name", "?")
        print(f"  [{'PASS' if ok else 'FAIL'}] initialize -> serverInfo.name = {server_name}")
        results.append(("initialize", ok))

        client.notify("notifications/initialized")

        # 2. tools/list — should list ~30 MCP tools
        resp = client.call("tools/list")
        tools = resp.get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools]
        has_status = any("octopoda_status" in n for n in tool_names)
        has_remember = any("remember" in n for n in tool_names)
        has_recall = any(n.endswith("recall") for n in tool_names)
        ok = len(tools) >= 20 and has_status and has_remember and has_recall
        print(f"  [{'PASS' if ok else 'FAIL'}] tools/list -> {len(tools)} tools "
              f"(status={has_status}, remember={has_remember}, recall={has_recall})")
        results.append(("tools/list", ok))

        # Pick the exact names (they may be prefixed differently depending on FastMCP version)
        def pick(needle):
            return next((n for n in tool_names if needle in n and "octopoda" in n), None)

        STATUS_T = pick("octopoda_status")
        REMEMBER_T = pick("remember") or "octopoda_remember"
        RECALL_T = pick("recall") if pick("recall") else None
        # Make sure recall isn't recall_similar/history etc.
        for n in tool_names:
            if n.endswith("_recall"):
                RECALL_T = n
                break

        # 3. octopoda_status — should return the diagnostic dict
        if STATUS_T:
            resp = client.call("tools/call", {"name": STATUS_T, "arguments": {}})
            body = resp.get("result", {}).get("content", [])
            text = body[0].get("text") if body and isinstance(body[0], dict) else None
            try:
                payload = json.loads(text) if text else {}
            except Exception:
                payload = {}
            ok = payload.get("mode") == "local" and "version" in payload
            print(f"  [{'PASS' if ok else 'FAIL'}] tools/call {STATUS_T} -> mode={payload.get('mode')} version={payload.get('version')}")
            results.append((STATUS_T, ok))
        else:
            print("  [SKIP] octopoda_status not present in tools/list")

        # 4. remember -> recall round-trip
        agent_id = "mcp-harness"
        resp = client.call("tools/call", {
            "name": REMEMBER_T,
            "arguments": {"agent_id": agent_id, "key": "favorite_drink", "value": "coffee"},
        })
        rblob = resp.get("result", {}).get("content", [])
        is_err = resp.get("result", {}).get("isError", False)
        wrote = bool(rblob) and not is_err
        # Optionally inspect the inner JSON for success=true
        inner_text = rblob[0].get("text", "") if rblob and isinstance(rblob[0], dict) else ""
        if "success" in inner_text:
            try:
                wrote = wrote and json.loads(inner_text).get("success") is True
            except Exception:
                pass
        print(f"  [{'PASS' if wrote else 'FAIL'}] tools/call {REMEMBER_T} -> success={wrote}")
        results.append((REMEMBER_T, bool(wrote)))

        if RECALL_T:
            resp = client.call("tools/call", {
                "name": RECALL_T,
                "arguments": {"agent_id": agent_id, "key": "favorite_drink"},
            })
            content = resp.get("result", {}).get("content", [])
            txt = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
            found = "coffee" in txt
            print(f"  [{'PASS' if found else 'FAIL'}] tools/call {RECALL_T} -> 'coffee' in body = {found}")
            results.append((RECALL_T, found))

        # 5. log_decision with DICT context (the audit fix for Issue #10)
        log_dec_t = pick("log_decision")
        if log_dec_t:
            resp = client.call("tools/call", {
                "name": log_dec_t,
                "arguments": {
                    "agent_id": agent_id,
                    "decision": "allow",
                    "reasoning": "harness check",
                    "context": {"who": "harness", "why": "verify dict accepted"},
                },
            })
            is_err = resp.get("result", {}).get("isError", False)
            content = resp.get("result", {}).get("content", [])
            txt = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
            logged = '"logged": true' in txt or '"logged":true' in txt
            ok = (not is_err) and logged
            print(f"  [{'PASS' if ok else 'FAIL'}] tools/call {log_dec_t}(context=dict) -> logged={logged}")
            results.append((log_dec_t, ok))

        # 6. recall_similar — should run, return empty or matches, NEVER crash
        rsim_t = pick("recall_similar")
        if rsim_t:
            resp = client.call("tools/call", {
                "name": rsim_t,
                "arguments": {"agent_id": agent_id, "query": "what do they drink", "limit": 3},
            })
            content = resp.get("result", {}).get("content", [])
            txt = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
            try:
                payload = json.loads(txt)
            except Exception:
                payload = {}
            ok = "count" in payload and "mode" in payload
            print(f"  [{'PASS' if ok else 'FAIL'}] tools/call {rsim_t} -> count={payload.get('count')} mode={payload.get('mode')}")
            results.append((rsim_t, ok))

    finally:
        client.stop()

    print()
    print("=" * 70)
    passes = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"MCP HARNESS RESULTS: {passes}/{total} PASS")
    print("=" * 70)
    if passes < total:
        print()
        print("Server stderr (last 30 lines):")
        for line in client._stderr_buf[-30:]:
            print(f"  {line.rstrip()}")
    return 0 if passes == total else 1


if __name__ == "__main__":
    sys.exit(main())
