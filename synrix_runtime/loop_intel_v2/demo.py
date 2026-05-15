"""Demo: feed synthetic loop scenarios through the detector and print results.

Run with:
  python -m synrix_runtime.loop_intel_v2.demo

Shows exactly what the detector produces — type, confidence, rule version,
evidence, and suggested fix — for each scenario.
"""

from __future__ import annotations

import json
from typing import List

from .models import (
    EventType,
    ToolCallEvent,
    LLMCallEvent,
    DecisionEvent,
    MemoryWriteEvent,
    LoopEvent,
)
from .detection import detect


def _pretty(d) -> str:
    return json.dumps(d, default=str, indent=2, sort_keys=True)


def _print_detection(scenario_name: str, events: List[LoopEvent], agent_id: str = "agent-1"):
    print(f"\n{'=' * 72}\nSCENARIO: {scenario_name}\n{'=' * 72}")
    print(f"Events: {len(events)}")
    detections = detect(events, agent_id=agent_id)
    if not detections:
        print("DETECTIONS: (none)\n")
        return
    for i, d in enumerate(detections, 1):
        print(f"\n[{i}/{len(detections)}] {d.loop_type.value.upper()} · {d.confidence.value}")
        print(f"  Rule:        {d.rule_version}")
        print(f"  Agent:       {d.agent_id}")
        print(f"  Description: {d.rule_description}")
        print(f"  Evidence:")
        for line in _pretty(d.evidence).splitlines():
            print(f"    {line}")
        if d.suggested_fix:
            print(f"  Suggested fix:")
            for line in d.suggested_fix.splitlines():
                print(f"    {line}")


def _tc(t, tool="api", args=None, code=200, success=True, result=None, agent="agent-1"):
    return ToolCallEvent(
        event_type=EventType.TOOL_CALL,
        timestamp=t,
        agent_id=agent,
        tool_name=tool,
        args=args or {"id": "X"},
        status_code=code,
        success=success,
        result=result or {"ok": True},
    )


def _llm(t, model="claude-sonnet-4-6", prompt_hash="p1", cost=0.01, response="ok", agent="agent-1"):
    return LLMCallEvent(
        event_type=EventType.LLM_CALL,
        timestamp=t,
        agent_id=agent,
        model=model,
        prompt_hash=prompt_hash,
        cost_usd=cost,
        response_text=response,
    )


def _dec(t, key="priority", value="A", agent="agent-1"):
    return DecisionEvent(
        event_type=EventType.DECISION,
        timestamp=t,
        agent_id=agent,
        decision_key=key,
        decision_value=value,
        decision_type="route",
    )


def _mw(t, key="shared:vote", value="x", agent="agent-1"):
    return MemoryWriteEvent(
        event_type=EventType.MEMORY_WRITE,
        timestamp=t,
        agent_id=agent,
        key=key,
        value=value,
    )


def run():
    # 1. Retry loop — tool failing with 429
    _print_detection("Retry loop: 4 identical 429s", [
        _tc(1.0, tool="fetch_crm", args={"id": "C-42"}, code=429, success=False),
        _tc(2.0, tool="fetch_crm", args={"id": "C-42"}, code=429, success=False),
        _tc(3.0, tool="fetch_crm", args={"id": "C-42"}, code=429, success=False),
        _tc(4.0, tool="fetch_crm", args={"id": "C-42"}, code=429, success=False),
    ])

    # 2. Polling loop
    _print_detection("Polling loop: status check every 30s, never changes", [
        _tc(0.0, tool="get_status", args={"job": "J-1"}, result={"status": "pending"}),
        _tc(30.0, tool="get_status", args={"job": "J-1"}, result={"status": "pending"}),
        _tc(60.0, tool="get_status", args={"job": "J-1"}, result={"status": "pending"}),
        _tc(90.0, tool="get_status", args={"job": "J-1"}, result={"status": "pending"}),
    ])

    # 3. Decision oscillation
    _print_detection("Decision oscillation: flip-flopping priority", [
        _dec(1.0, key="priority", value="urgent"),
        _dec(2.0, key="priority", value="low"),
        _dec(3.0, key="priority", value="urgent"),
        _dec(4.0, key="priority", value="low"),
    ])

    # 4. Cost inflation
    _print_detection("Cost inflation: haiku → sonnet → opus on same prompt", [
        _llm(1.0, model="claude-haiku-4-5", prompt_hash="solve-X", cost=0.001),
        _llm(2.0, model="claude-sonnet-4-6", prompt_hash="solve-X", cost=0.012),
        _llm(3.0, model="claude-opus-4-7", prompt_hash="solve-X", cost=0.08),
    ])

    # 5. Self-correction
    _print_detection("Self-correction: agent second-guessing itself", [
        _llm(1.0, prompt_hash="answer-Q", response="Actually, let me rethink — X might be wrong"),
        _llm(2.0, prompt_hash="answer-Q", response="Wait, on second thought I should reconsider"),
        _llm(3.0, prompt_hash="answer-Q", response="Let me reconsider — actually Z is correct"),
    ])

    # 6. Ping-pong
    _print_detection("Ping-pong: two reviewers alternating approve/reject", [
        _mw(1.0, key="shared:vote:ticket-42", value="approve", agent="reviewer-1"),
        _mw(2.0, key="shared:vote:ticket-42", value="reject", agent="reviewer-2"),
        _mw(3.0, key="shared:vote:ticket-42", value="approve", agent="reviewer-1"),
        _mw(4.0, key="shared:vote:ticket-42", value="reject", agent="reviewer-2"),
    ], agent_id="")  # ping-pong ignores agent_id

    # 7. Healthy operation — should produce nothing
    _print_detection("Healthy operation: varied tools, different prompts, exploring decisions", [
        _tc(1.0, tool="search_db", args={"q": "alice"}, result={"rows": 3}),
        _tc(2.0, tool="fetch_user", args={"id": "U-99"}, result={"name": "Alice"}),
        _llm(3.0, prompt_hash="classify-intent"),
        _llm(4.0, prompt_hash="generate-reply"),
        _dec(5.0, key="strategy", value="A"),
        _dec(6.0, key="strategy", value="B"),
        _dec(7.0, key="strategy", value="C"),
    ])

    print(f"\n{'=' * 72}\nDemo complete. 6 loop types demonstrated + 1 healthy baseline.\n{'=' * 72}\n")


if __name__ == "__main__":
    run()
