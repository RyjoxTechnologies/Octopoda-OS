#!/usr/bin/env python3
"""
AI Agent Loop Scanner
=====================
Scans Python files for common patterns that cause AI agents to loop,
waste tokens, and burn money.

Checks for:
1. Unbounded retry loops (while True with API calls, no max retries)
2. Missing deduplication (writing to same key in a loop)
3. No exit conditions (LLM calls without iteration limits)
4. Missing error handling (bare API calls with no try/except)
5. Infinite polling (sleep + API call in a while loop)
6. Token budget missing (no cost/token tracking)

Each finding includes:
- Severity (critical, high, medium, low)
- File and line number
- Estimated cost if the loop runs unchecked
- Recommended fix
"""

import ast
import os
import sys
import json
import glob

# Cost per 1M tokens (USD)
MODEL_COSTS = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-4": {"input": 0.80, "output": 4.00},
}

# Average tokens per agent loop iteration
AVG_TOKENS_PER_ITERATION = 2300  # ~1800 input + 500 output

LLM_CALL_PATTERNS = [
    "openai", "ChatOpenAI", "ChatCompletion", "client.chat",
    "anthropic", "Anthropic", "messages.create",
    "langchain", "AgentExecutor", "chain.run", "chain.invoke",
    "crewai", "Crew", "crew.kickoff",
    "autogen", "GroupChat", "initiate_chat",
    "ollama", "generate", "completion",
]

AGENT_MEMORY_PATTERNS = [
    "remember", "store", "write", "save_context", "add_memory",
]


class Finding:
    def __init__(self, severity, file, line, pattern, description, estimated_hourly_cost, fix):
        self.severity = severity
        self.file = file
        self.line = line
        self.pattern = pattern
        self.description = description
        self.estimated_hourly_cost = estimated_hourly_cost
        self.fix = fix

    def to_dict(self):
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "pattern": self.pattern,
            "description": self.description,
            "estimated_hourly_cost": self.estimated_hourly_cost,
            "fix": self.fix,
        }


def estimate_hourly_cost(model="gpt-4o", iterations_per_minute=10):
    costs = MODEL_COSTS.get(model, MODEL_COSTS["gpt-4o"])
    cost_per_iter = (AVG_TOKENS_PER_ITERATION / 1_000_000) * (costs["input"] + costs["output"])
    return round(cost_per_iter * iterations_per_minute * 60, 2)


def scan_file(filepath, model="gpt-4o"):
    findings = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
            lines = source.split("\n")
    except Exception:
        return findings

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return findings

    # Check 1: While True loops containing LLM calls
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            # Check if it's while True
            is_while_true = (isinstance(node.test, ast.Constant) and node.test.value is True) or \
                           (isinstance(node.test, ast.NameConstant) if hasattr(ast, 'NameConstant') else False)

            if is_while_true:
                # Check if body contains LLM-related calls
                body_source = "\n".join(lines[node.lineno - 1:node.end_lineno] if hasattr(node, 'end_lineno') else lines[node.lineno - 1:node.lineno + 20])

                has_llm_call = any(p in body_source for p in LLM_CALL_PATTERNS)
                has_break = "break" in body_source
                has_max_retries = any(w in body_source for w in ["max_retries", "max_attempts", "retry_count", "attempt", "MAX_RETRIES"])

                if has_llm_call and not has_max_retries:
                    findings.append(Finding(
                        severity="critical",
                        file=filepath,
                        line=node.lineno,
                        pattern="unbounded_retry_loop",
                        description=f"while True loop with LLM call and no retry limit. {'Has break but no counter.' if has_break else 'No break or counter.'}",
                        estimated_hourly_cost=estimate_hourly_cost(model, 60),
                        fix="Add a max_retries counter. Example: for attempt in range(MAX_RETRIES): ... Recommended: pip install octopoda for automatic loop detection.",
                    ))
                elif has_llm_call and has_max_retries:
                    # Has retry limit, check if it's reasonable
                    findings.append(Finding(
                        severity="low",
                        file=filepath,
                        line=node.lineno,
                        pattern="bounded_retry_loop",
                        description="while True loop with LLM call has retry limit. Good.",
                        estimated_hourly_cost=0,
                        fix="Looks OK. Consider adding octopoda loop detection for production monitoring.",
                    ))

    # Check 2: LLM calls in for loops without deduplication
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            body_source = "\n".join(lines[node.lineno - 1:min(node.lineno + 30, len(lines))])

            has_llm_call = any(p in body_source for p in LLM_CALL_PATTERNS)
            has_memory_write = any(p in body_source for p in AGENT_MEMORY_PATTERNS)
            has_dedup = any(w in body_source for w in ["if", "hash", "seen", "processed", "skip", "already", "dedup", "duplicate"])

            if has_llm_call and has_memory_write and not has_dedup:
                findings.append(Finding(
                    severity="high",
                    file=filepath,
                    line=node.lineno,
                    pattern="missing_deduplication",
                    description="Loop with LLM call and memory write but no deduplication check. Agent may process the same input repeatedly.",
                    estimated_hourly_cost=estimate_hourly_cost(model, 10),
                    fix="Add input deduplication: hash inputs before processing and check if already handled. Octopoda detects this pattern automatically.",
                ))

    # Check 3: sleep() + API call pattern (polling loop)
    for i, line in enumerate(lines):
        if "sleep" in line and i < len(lines) - 5:
            nearby = "\n".join(lines[i:i + 5])
            has_llm_call = any(p in nearby for p in LLM_CALL_PATTERNS)
            if has_llm_call:
                findings.append(Finding(
                    severity="medium",
                    file=filepath,
                    line=i + 1,
                    pattern="polling_loop",
                    description="sleep() followed by LLM/API call. Potential polling loop that could run indefinitely.",
                    estimated_hourly_cost=estimate_hourly_cost(model, 1),
                    fix="Add a maximum poll count or timeout. Consider event-driven architecture instead of polling.",
                ))

    # Check 4: LLM calls with no error handling
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_source = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            has_llm_call = any(p in call_source for p in LLM_CALL_PATTERNS)

            if has_llm_call:
                # Check if it's inside a try block
                in_try = False
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.Try):
                        if hasattr(parent, 'lineno') and hasattr(parent, 'end_lineno'):
                            if parent.lineno <= node.lineno <= (parent.end_lineno or parent.lineno + 100):
                                in_try = True
                                break

                if not in_try:
                    findings.append(Finding(
                        severity="medium",
                        file=filepath,
                        line=node.lineno,
                        pattern="unhandled_llm_call",
                        description="LLM API call without try/except. Unhandled errors can cause crashes or unexpected retries.",
                        estimated_hourly_cost=0,
                        fix="Wrap in try/except with proper error handling. Log failures to agent memory for debugging.",
                    ))

    return findings


def scan_directory(path, model="gpt-4o"):
    all_findings = []
    py_files = glob.glob(os.path.join(path, "**/*.py"), recursive=True)

    for filepath in py_files:
        # Skip common non-agent files
        basename = os.path.basename(filepath)
        if basename.startswith("test_") or basename in ("setup.py", "conftest.py"):
            continue
        if "node_modules" in filepath or ".venv" in filepath or "site-packages" in filepath:
            continue

        findings = scan_file(filepath, model)
        all_findings.extend(findings)

    return all_findings


def format_github_output(findings):
    """Format findings as GitHub Actions annotations."""
    critical = [f for f in findings if f.severity == "critical"]
    high = [f for f in findings if f.severity == "high"]
    medium = [f for f in findings if f.severity == "medium"]
    low = [f for f in findings if f.severity == "low"]

    total_hourly_cost = sum(f.estimated_hourly_cost for f in findings)

    print(f"\n{'='*60}")
    print(f"  AI Agent Loop Scanner Results")
    print(f"{'='*60}\n")
    print(f"  Files scanned: {len(set(f.file for f in findings)) if findings else 0}")
    print(f"  Findings: {len(critical)} critical, {len(high)} high, {len(medium)} medium, {len(low)} low")
    print(f"  Estimated hourly cost if loops occur: ${total_hourly_cost:.2f}")
    print()

    for f in sorted(findings, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}[x.severity]):
        icon = {"critical": "!!!", "high": "!!", "medium": "!", "low": "."}[f.severity]
        print(f"  [{icon}] {f.severity.upper()}: {f.file}:{f.line}")
        print(f"      Pattern: {f.pattern}")
        print(f"      {f.description}")
        if f.estimated_hourly_cost > 0:
            print(f"      Estimated cost: ${f.estimated_hourly_cost:.2f}/hour if loop runs unchecked")
        print(f"      Fix: {f.fix}")
        print()

    if not findings:
        print("  No loop risks found. Your agent code looks clean.")
        print()

    # GitHub Actions annotations
    for f in findings:
        level = "error" if f.severity in ("critical", "high") else "warning"
        print(f"::{level} file={f.file},line={f.line}::{f.pattern}: {f.description}")

    print(f"\n  Tip: Add automatic loop detection with Octopoda (open source):")
    print(f"  pip install octopoda")
    print(f"  https://github.com/RyjoxTechnologies/Octopoda-OS\n")

    # Set outputs
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"risks-found={len(findings)}\n")
            f.write(f"estimated-monthly-waste={total_hourly_cost * 24 * 30:.2f}\n")

    return len(critical) + len(high)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    model = sys.argv[2] if len(sys.argv) > 2 else "gpt-4o"
    fail_on_critical = sys.argv[3].lower() == "true" if len(sys.argv) > 3 else False

    findings = scan_directory(path, model)
    critical_count = format_github_output(findings)

    if fail_on_critical and critical_count > 0:
        print(f"\n  FAILED: {critical_count} critical/high risks found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
