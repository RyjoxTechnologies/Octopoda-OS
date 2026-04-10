"""
Octopoda Self-Debugging Agent Demo
====================================
An AI agent that debugs itself. It writes code, runs tests, fails,
stores the failure in memory, learns from it, and tries again.

Both GPT-4o and Claude attempt the same coding challenge.
Every attempt, failure, and fix is tracked through Octopoda.

Dashboard: http://localhost:7842
"""

import requests
import time
import sys
import json
import os
import subprocess
import tempfile

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE = "http://localhost:8741"

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
BLUE = "\033[94m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

MAX_ATTEMPTS = 10

# --The Challenge ──────────────────────────────────────────────────────────

CHALLENGE = """Write a Python function called `parse_cron` that takes a cron expression string
and a datetime, and returns the NEXT datetime that matches the cron expression.

Only support these 5 fields: minute hour day_of_month month day_of_week
Each field can be: a number, * (any), */N (every N), or a range like 1-5

Rules:
1. Input: parse_cron("*/15 * * * *", dt) returns next datetime matching every 15 minutes
2. Input: parse_cron("0 9 * * 1-5", dt) returns next weekday at 9:00 AM
3. Day of week: 0=Monday, 6=Sunday
4. If the current datetime already matches, return the NEXT occurrence (not the same time)
5. Must handle month boundaries (Jan 31 -> Feb 1) and year boundaries (Dec -> Jan)
6. Return a datetime object

Examples (assuming dt = datetime(2026, 4, 10, 14, 30)):
    parse_cron("*/15 * * * *", dt)    -> datetime(2026, 4, 10, 14, 45)  # next 15-min mark
    parse_cron("0 9 * * *", dt)       -> datetime(2026, 4, 11, 9, 0)    # tomorrow at 9am
    parse_cron("0 9 * * 1-5", dt)     -> datetime(2026, 4, 11, 9, 0)    # next weekday 9am (Apr 10 is Thursday, so Friday)
    parse_cron("30 14 * * *", dt)     -> datetime(2026, 4, 11, 14, 30)  # already passed today, so tomorrow
    parse_cron("0 0 1 * *", dt)       -> datetime(2026, 5, 1, 0, 0)     # first of next month
    parse_cron("0 0 * 1 *", dt)       -> datetime(2027, 1, 1, 0, 0)     # next January
"""

TEST_CODE = '''
import sys
from datetime import datetime

def run_tests():
    tests_passed = 0
    tests_total = 7
    results = []
    dt = datetime(2026, 4, 10, 14, 30)

    # Test 1: Every 15 minutes
    try:
        r = parse_cron("*/15 * * * *", dt)
        assert r == datetime(2026, 4, 10, 14, 45), f"Got {r}"
        tests_passed += 1
        results.append("PASS: every_15_min")
    except Exception as e:
        results.append(f"FAIL: every_15_min - {e}")

    # Test 2: Daily at 9am (already passed today)
    try:
        r = parse_cron("0 9 * * *", dt)
        assert r == datetime(2026, 4, 11, 9, 0), f"Got {r}"
        tests_passed += 1
        results.append("PASS: daily_9am")
    except Exception as e:
        results.append(f"FAIL: daily_9am - {e}")

    # Test 3: Weekdays at 9am (Apr 10 is Thursday)
    try:
        r = parse_cron("0 9 * * 0-4", dt)
        assert r == datetime(2026, 4, 11, 9, 0), f"Got {r}, expected Apr 11 (Friday=day 4)"
        tests_passed += 1
        results.append("PASS: weekday_9am")
    except Exception as e:
        results.append(f"FAIL: weekday_9am - {e}")

    # Test 4: Same time already passed today
    try:
        r = parse_cron("30 14 * * *", dt)
        assert r == datetime(2026, 4, 11, 14, 30), f"Got {r}"
        tests_passed += 1
        results.append("PASS: already_passed")
    except Exception as e:
        results.append(f"FAIL: already_passed - {e}")

    # Test 5: First of next month
    try:
        r = parse_cron("0 0 1 * *", dt)
        assert r == datetime(2026, 5, 1, 0, 0), f"Got {r}"
        tests_passed += 1
        results.append("PASS: first_of_month")
    except Exception as e:
        results.append(f"FAIL: first_of_month - {e}")

    # Test 6: Specific month (January next year)
    try:
        r = parse_cron("0 0 1 1 *", dt)
        assert r == datetime(2027, 1, 1, 0, 0), f"Got {r}"
        tests_passed += 1
        results.append("PASS: specific_month")
    except Exception as e:
        results.append(f"FAIL: specific_month - {e}")

    # Test 7: Every hour on the hour
    try:
        r = parse_cron("0 * * * *", dt)
        assert r == datetime(2026, 4, 10, 15, 0), f"Got {r}"
        tests_passed += 1
        results.append("PASS: every_hour")
    except Exception as e:
        results.append(f"FAIL: every_hour - {e}")

    print(f"RESULT: {tests_passed}/{tests_total}")
    for r in results:
        print(f"  {r}")
    sys.exit(0)

run_tests()
'''


# --LLM Calls ──────────────────────────────────────────────────────────────

def call_gpt(prompt):
    start = time.time()
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [
                {"role": "system", "content": "You are a Python expert. Write clean, working code. Return ONLY the function code, no explanations, no markdown, no backticks."},
                {"role": "user", "content": prompt}],
                "max_tokens": 800, "temperature": 0.3},
            timeout=60)
        elapsed = time.time() - start
        data = r.json()
        if "choices" not in data:
            return None, elapsed, 0
        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return text, elapsed, tokens
    except Exception as e:
        return None, time.time() - start, 0


def call_claude(prompt):
    start = time.time()
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 800,
                  "system": "You are a Python expert. Write clean, working code. Return ONLY the function code, no explanations, no markdown, no backticks.",
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        elapsed = time.time() - start
        data = r.json()
        if "content" not in data:
            return None, elapsed, 0
        text = data["content"][0]["text"]
        tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0)
        return text, elapsed, tokens
    except:
        return None, time.time() - start, 0


# --Code Execution ─────────────────────────────────────────────────────────

def run_tests(code):
    """Run the code + tests in a subprocess. Returns (passed, total, details)."""
    full_code = "# -*- coding: utf-8 -*-\n" + code + "\n\n" + TEST_CODE

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, dir='.', encoding='utf-8') as f:
        f.write(full_code)
        f.flush()
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout + result.stderr

        # Parse results
        passed = 0
        total = 7
        details = []

        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('RESULT:'):
                try:
                    parts = line.split(': ')[1].split('/')
                    passed = int(parts[0])
                    total = int(parts[1])
                except:
                    pass
            elif line.startswith('PASS:'):
                details.append(line)
            elif line.startswith('FAIL:'):
                details.append(line)

        if result.returncode != 0 and passed == 0 and not details:
            error = result.stderr.strip().split('\n')[-1] if result.stderr else "Unknown error"
            details = [f"CRASH: {error}"]

        return passed, total, details, output
    except subprocess.TimeoutExpired:
        return 0, 7, ["CRASH: Execution timed out (infinite loop?)"], "Timeout"
    except Exception as e:
        return 0, 7, [f"CRASH: {e}"], str(e)
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass


# --Clean code from LLM response ──────────────────────────────────────────

def clean_code(raw):
    """Strip markdown backticks and other noise from LLM response."""
    if raw is None:
        return None
    code = raw.strip()
    # Remove markdown code blocks
    if code.startswith('```python'):
        code = code[len('```python'):].strip()
    elif code.startswith('```'):
        code = code[3:].strip()
    if code.endswith('```'):
        code = code[:-3].strip()
    return code


# --Octopoda helpers ───────────────────────────────────────────────────────

def api(method, path, data=None):
    url = f"{BASE}{path}"
    if method == "POST":
        return requests.post(url, json=data, timeout=15)
    elif method == "PUT":
        return requests.put(url, json=data, timeout=15)
    return requests.get(url, timeout=15)

def register(agent_id):
    api("POST", "/v1/agents", {"agent_id": agent_id})

def remember(agent_id, key, value):
    api("POST", f"/v1/agents/{agent_id}/remember", {"key": key, "value": value})

def share(agent_id, space, key, value):
    api("POST", f"/v1/shared/{space}", {"key": key, "value": value, "author_agent_id": agent_id})

def log_decision(agent_id, decision, reasoning, context=None):
    api("POST", f"/v1/agents/{agent_id}/decision", {
        "decision": decision, "reasoning": reasoning, "context": context or {}})

def get_loop_status(agent_id):
    r = api("GET", f"/v1/agents/{agent_id}/loops/status")
    return r.json() if r.status_code == 200 else {}


# --Run one agent through the challenge ────────────────────────────────────

def run_agent(agent_id, name, color, llm_fn):
    """Run one agent through the self-debugging challenge."""
    print(f"\n  {color}{BOLD}{name}{RESET}")
    print(f"  {DIM}{'-'*50}{RESET}\n")

    attempts = []
    failure_history = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Build prompt with failure history
        if attempt == 1:
            prompt = f"{CHALLENGE}\n\nWrite the smart_split function."
        else:
            memory = "\n\n".join([
                f"Attempt {f['attempt']}: {f['passed']}/{f['total']} tests passed.\n"
                f"Failures: {'; '.join(f['failures'])}\n"
                f"Code that failed:\n{f['code'][:300]}"
                for f in failure_history[-3:]  # Last 3 failures only
            ])
            prompt = (f"{CHALLENGE}\n\n"
                      f"Your previous attempts failed. Here's what went wrong:\n\n"
                      f"{memory}\n\n"
                      f"Fix the bugs. Write the complete smart_split function. "
                      f"Pay attention to the specific test failures above.")

        # Call LLM
        raw_code, elapsed, tokens = llm_fn(prompt)
        code = clean_code(raw_code)

        if code is None:
            print(f"  {color}Attempt {attempt}{RESET}: {RED}LLM failed to respond{RESET}")
            remember(agent_id, f"attempt:{attempt}:error", "LLM failed to respond")
            attempts.append({"attempt": attempt, "passed": 0, "total": 7, "time": elapsed, "tokens": tokens})
            time.sleep(2)
            continue

        # Run tests
        passed, total, details, raw_output = run_tests(code)

        # Store in memory
        remember(agent_id, f"attempt:{attempt}:code", code[:500])
        remember(agent_id, f"attempt:{attempt}:result", f"{passed}/{total} passed")

        # Share progress
        share(agent_id, "challenge", f"{name.lower().replace(' ', '-')}:attempt{attempt}",
              f"{passed}/{total} tests passed")

        # Build failure list
        failures = [d for d in details if d.startswith('FAIL') or d.startswith('CRASH')]

        if failures:
            failure_history.append({
                "attempt": attempt,
                "passed": passed,
                "total": total,
                "failures": failures,
                "code": code,
            })
            remember(agent_id, f"attempt:{attempt}:failures", "; ".join(failures))

        # Log decision
        if attempt > 1:
            log_decision(agent_id,
                decision=f"Attempt {attempt}: Rewrote function based on {len(failure_history)} previous failures",
                reasoning=f"Previous attempt got {failure_history[-1]['passed'] if len(failure_history) > 1 else 0}/{total}. "
                          f"Key failures: {'; '.join(failures[:2]) if failures else 'none'}. "
                          f"Changed approach to fix: {failures[0] if failures else 'all tests'}.",
                context={"attempt": attempt, "passed": passed, "total": total})

        # Display
        if passed == total:
            print(f"  {color}Attempt {attempt}{RESET}: {GREEN}{BOLD}{passed}/{total} ALL TESTS PASSED{RESET} "
                  f"({elapsed:.1f}s, {tokens} tokens)")
            attempts.append({"attempt": attempt, "passed": passed, "total": total, "time": elapsed, "tokens": tokens, "solved": True})

            # Log success
            log_decision(agent_id,
                decision=f"SOLVED on attempt {attempt}",
                reasoning=f"All {total} tests pass after {attempt} attempts and {len(failure_history)} failures. "
                          f"Total tokens used: {sum(a.get('tokens',0) for a in attempts)}.",
                context={"attempt": attempt, "total_failures": len(failure_history)})
            remember(agent_id, "final:result", f"Solved in {attempt} attempts")
            share(agent_id, "challenge", f"{name.lower().replace(' ', '-')}:final", f"SOLVED in {attempt} attempts")
            break
        else:
            print(f"  {color}Attempt {attempt}{RESET}: {YELLOW}{passed}/{total}{RESET} "
                  f"({elapsed:.1f}s, {tokens} tokens)")
            for d in failures[:3]:
                print(f"    {RED}{d}{RESET}")

        attempts.append({"attempt": attempt, "passed": passed, "total": total, "time": elapsed, "tokens": tokens})
        time.sleep(2)

    else:
        # Failed all attempts
        remember(agent_id, "final:result", f"Failed after {MAX_ATTEMPTS} attempts")
        share(agent_id, "challenge", f"{name.lower().replace(' ', '-')}:final", f"FAILED after {MAX_ATTEMPTS} attempts")
        log_decision(agent_id,
            decision=f"FAILED after {MAX_ATTEMPTS} attempts",
            reasoning=f"Could not solve the challenge. Best result: {max(a.get('passed',0) for a in attempts)}/{total}.",
            context={"max_attempts": MAX_ATTEMPTS})

    return attempts


# --Main ───────────────────────────────────────────────────────────────────

def main():
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        if r.status_code != 200:
            raise Exception()
    except:
        print("\n  Server not running. Start with: octopoda")
        sys.exit(1)

    api("PUT", "/v1/settings", {"llm_model": "gpt-4o"})

    gpt_id = "gpt4o-debugger"
    claude_id = "claude-debugger"
    register(gpt_id)
    register(claude_id)

    print()
    print(f"  {BOLD}OCTOPODA SELF-DEBUGGING AGENT{RESET}")
    print(f"  {DIM}Can an AI debug its own code using memory of past failures?{RESET}")
    print()
    print(f"  Challenge: Write a parse_cron() function that handles:")
    print(f"    - 5-field cron expressions (min hour dom month dow)")
    print(f"    - Wildcards, ranges, and step values")
    print(f"    - Month/year boundaries")
    print(f"    - Returns next matching datetime")
    print(f"  7 test cases. Up to {MAX_ATTEMPTS} attempts per model.")
    print()
    print(f"  Dashboard: {BOLD}http://localhost:7842{RESET}")
    print()

    # Store challenge
    share(gpt_id, "challenge", "description", CHALLENGE)
    remember(gpt_id, "challenge", CHALLENGE)
    remember(claude_id, "challenge", CHALLENGE)

    # Run GPT-4o
    gpt_attempts = run_agent(gpt_id, "GPT-4o", GREEN, call_gpt)

    # Run Claude
    claude_attempts = run_agent(claude_id, "Claude Sonnet", BLUE, call_claude)

    # --Results ────────────────────────────────────────────────────────

    print(f"\n  {BOLD}{'='*60}{RESET}")
    print(f"  {BOLD}RESULTS{RESET}")
    print(f"  {BOLD}{'='*60}{RESET}\n")

    gpt_solved = any(a.get("solved") for a in gpt_attempts)
    claude_solved = any(a.get("solved") for a in claude_attempts)
    gpt_num = next((a["attempt"] for a in gpt_attempts if a.get("solved")), MAX_ATTEMPTS)
    claude_num = next((a["attempt"] for a in claude_attempts if a.get("solved")), MAX_ATTEMPTS)
    gpt_tokens = sum(a.get("tokens", 0) for a in gpt_attempts)
    claude_tokens = sum(a.get("tokens", 0) for a in claude_attempts)
    gpt_time = sum(a.get("time", 0) for a in gpt_attempts)
    claude_time = sum(a.get("time", 0) for a in claude_attempts)

    print(f"  {'Metric':<30} {GREEN+'GPT-4o'+RESET:>20} {BLUE+'Claude Sonnet'+RESET:>20}")
    print(f"  {'-'*62}")
    print(f"  {'Solved?':<30} {'YES' if gpt_solved else 'NO':>12} {'YES' if claude_solved else 'NO':>12}")
    print(f"  {'Attempts needed':<30} {gpt_num:>12} {claude_num:>12}")
    print(f"  {'Total tokens':<30} {gpt_tokens:>12,} {claude_tokens:>12,}")
    print(f"  {'Total time (s)':<30} {gpt_time:>12.1f} {claude_time:>12.1f}")
    print(f"  {'Failures before success':<30} {gpt_num-1 if gpt_solved else gpt_num:>12} {claude_num-1 if claude_solved else claude_num:>12}")

    # Progress chart (ASCII)
    print(f"\n  {BOLD}Progress Chart:{RESET}\n")
    print(f"  Tests")
    print(f"  7/7 |", end="")
    for i in range(max(len(gpt_attempts), len(claude_attempts))):
        gp = gpt_attempts[i]["passed"] if i < len(gpt_attempts) else 0
        cp = claude_attempts[i]["passed"] if i < len(claude_attempts) else 0
        if gp == 7:
            print(f" {GREEN}G{RESET}", end="")
        elif gp > 0:
            print(f" {YELLOW}g{RESET}", end="")
        else:
            print(f" {RED}.{RESET}", end="")
    print()

    for level in range(6, 0, -1):
        print(f"  {level}/7 |", end="")
        for i in range(max(len(gpt_attempts), len(claude_attempts))):
            gp = gpt_attempts[i]["passed"] if i < len(gpt_attempts) else 0
            cp = claude_attempts[i]["passed"] if i < len(claude_attempts) else 0
            if gp == level:
                print(f" {GREEN}G{RESET}", end="")
            elif gp > level:
                print(f" {GREEN}|{RESET}", end="")
            else:
                print(f"  ", end="")
        print()

    print(f"  0/7 |{'--'*max(len(gpt_attempts), len(claude_attempts))*2}--")
    print(f"       ", end="")
    for i in range(max(len(gpt_attempts), len(claude_attempts))):
        print(f" {i+1}", end="")
    print(f"  ← Attempt")

    print(f"\n  {GREEN}G = GPT-4o{RESET}  {BLUE}C = Claude{RESET}")

    # Loop detection
    gpt_loop = get_loop_status(gpt_id)
    claude_loop = get_loop_status(claude_id)
    print(f"\n  Loop detection:")
    print(f"    {GREEN}GPT-4o{RESET}:  {gpt_loop.get('score', '?')}/100 ({gpt_loop.get('severity', '?')})")
    print(f"    {BLUE}Claude{RESET}:  {claude_loop.get('score', '?')}/100 ({claude_loop.get('severity', '?')})")

    if gpt_solved and claude_solved:
        if gpt_num < claude_num:
            print(f"\n  {GREEN}{BOLD}Winner: GPT-4o (solved in {gpt_num} vs {claude_num} attempts){RESET}")
        elif claude_num < gpt_num:
            print(f"\n  {BLUE}{BOLD}Winner: Claude (solved in {claude_num} vs {gpt_num} attempts){RESET}")
        else:
            print(f"\n  {BOLD}Tie: Both solved in {gpt_num} attempts{RESET}")
    elif gpt_solved:
        print(f"\n  {GREEN}{BOLD}Winner: GPT-4o (Claude failed to solve){RESET}")
    elif claude_solved:
        print(f"\n  {BLUE}{BOLD}Winner: Claude (GPT-4o failed to solve){RESET}")
    else:
        print(f"\n  {RED}{BOLD}Neither model solved the challenge{RESET}")

    print(f"\n  Dashboard: {BOLD}http://localhost:7842{RESET}")
    print(f"  See: Shared Memory (progress), Audit Trail (decisions), Memory Explorer (failure history)")
    print()

    # Save data
    output = {
        "challenge": "smart_split function",
        "test_cases": 7,
        "max_attempts": MAX_ATTEMPTS,
        "gpt4o": {"attempts": gpt_attempts, "solved": gpt_solved, "total_tokens": gpt_tokens, "total_time": gpt_time},
        "claude": {"attempts": claude_attempts, "solved": claude_solved, "total_tokens": claude_tokens, "total_time": claude_time},
    }
    with open("self_debug_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"  {DIM}Raw data saved to self_debug_results.json{RESET}")
    print()


if __name__ == "__main__":
    main()
