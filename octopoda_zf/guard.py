"""Loop detection + circuit breaker — an operational guardrail (value-add #5).

A runaway agent (a tight retry loop, an accidental recursion, a misbehaving chain)
can hammer the memory layer: exploding recall + extraction cost and polluting memory
with near-identical writes. The `LoopGuard` watches, per agent, the call RATE and
REPEATED-identical-query signal, and trips a circuit breaker that makes recall +
capture a NO-OP until a short cooldown passes.

Design principles:
- **Fail-OPEN.** When unsure, allow. A legitimate busy agent must never be blocked;
  the breaker only trips on a clear runaway signal (high rate OR the same query over
  and over). Memory degrades gracefully (skipped) — the user's LLM call is untouched.
- **Per-agent.** One looping agent doesn't trip the breaker for others.
- **Self-healing.** The breaker re-closes automatically after `cooldown_s`.
- **Thread-safe + cheap.** A lock + a small deque per agent; ~microseconds.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class LoopGuardConfig:
    max_calls: int = 60          # more than this many calls within window_s -> trip
    window_s: float = 10.0       # sliding rate window
    repeat_threshold: int = 10   # the SAME query this many times in a row -> trip
    cooldown_s: float = 30.0     # breaker stays open (skipping) this long after a trip


class LoopGuard:
    """Per-agent loop detector + circuit breaker. `allow()` is called once per turn
    (records the call); `is_open()` queries breaker state without recording."""

    def __init__(self, config: LoopGuardConfig | None = None) -> None:
        self._cfg = config or LoopGuardConfig()
        self._lock = threading.Lock()
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._last_q: dict[str, str] = {}
        self._repeat: dict[str, int] = defaultdict(int)
        self._open_until: dict[str, float] = {}
        self.trips = 0  # telemetry: how many times the breaker has fired

    def allow(self, agent_id: str, query: str = "", now: float | None = None) -> bool:
        """Record a call and decide whether instrumentation should proceed.

        Returns True to proceed (recall + capture), False if the breaker is open
        (skip them this turn). The user's LLM call is unaffected either way."""
        t = time.monotonic() if now is None else now
        with self._lock:
            if t < self._open_until.get(agent_id, 0.0):
                return False  # breaker open -> skip

            dq = self._calls[agent_id]
            dq.append(t)
            cutoff = t - self._cfg.window_s
            while dq and dq[0] < cutoff:
                dq.popleft()

            if query and query == self._last_q.get(agent_id):
                self._repeat[agent_id] += 1
            else:
                self._repeat[agent_id] = 0
                self._last_q[agent_id] = query

            tripped = (
                len(dq) > self._cfg.max_calls
                or self._repeat[agent_id] >= self._cfg.repeat_threshold
            )
            if tripped:
                self._open_until[agent_id] = t + self._cfg.cooldown_s
                self._repeat[agent_id] = 0
                dq.clear()
                self.trips += 1
                return False
            return True

    def is_open(self, agent_id: str, now: float | None = None) -> bool:
        """True if the breaker is currently open for this agent (does NOT record)."""
        t = time.monotonic() if now is None else now
        with self._lock:
            return t < self._open_until.get(agent_id, 0.0)

    def reset(self, agent_id: str | None = None) -> None:
        """Clear breaker state (a specific agent, or all). Mainly for tests/admin."""
        with self._lock:
            if agent_id is None:
                self._calls.clear()
                self._last_q.clear()
                self._repeat.clear()
                self._open_until.clear()
            else:
                self._calls.pop(agent_id, None)
                self._last_q.pop(agent_id, None)
                self._repeat.pop(agent_id, None)
                self._open_until.pop(agent_id, None)
