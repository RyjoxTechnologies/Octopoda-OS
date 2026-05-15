"""Data models for Loop Intelligence v2.

Events are the input substrate. A classifier sees a window of recent events
for one agent (or two agents for cross-agent loops) and decides whether
any loop pattern is present.

Design decisions:
  - Dataclasses, not SQLAlchemy models. This module is testable without a DB.
  - Events carry their own timestamp; the classifier orders them.
  - Embeddings are opt-in — if absent, similarity-based rules skip (don't
    false-fire).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    MEMORY_WRITE = "memory_write"
    MEMORY_READ = "memory_read"
    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    DECISION = "decision"


class Confidence(str, Enum):
    """Classification confidence. Low is logged only, never notifies."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LoopType(str, Enum):
    """The 16 loop types the system can detect.

    Types in the BASIC_* group are implemented in v1 of this module.
    Types in the ADVANCED_* group are implemented in v2.
    """
    # Basic (highest-signal, 4)
    RETRY = "retry"
    POLLING = "polling"
    DECISION_OSCILLATION = "decision_oscillation"
    COST_INFLATION = "cost_inflation"

    # Basic (remaining, 4)
    SELF_CORRECTION = "self_correction"
    PING_PONG = "ping_pong"
    TOOL_NONDETERMINISM = "tool_nondeterminism"
    RECALL_WRITE = "recall_write"

    # Advanced (8)
    CONVERGENT_HALLUCINATION = "convergent_hallucination"
    REFLECTION = "reflection"
    PLAN_REPLAN = "plan_replan"
    TOOL_OSCILLATION = "tool_oscillation"
    CLARIFICATION = "clarification"
    SUBGOAL_PROLIFERATION = "subgoal_proliferation"
    CONSENSUS_FAILURE = "consensus_failure"
    CROSS_SESSION_CONTAMINATION = "cross_session_contamination"

    # Meta
    STEALTH = "stealth"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

@dataclass
class LoopEvent:
    """Base event. Subclasses carry event-type-specific fields."""
    event_type: EventType
    timestamp: float
    agent_id: str
    tenant_id: str = "default"
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class MemoryWriteEvent(LoopEvent):
    key: str = ""
    value: Any = None
    embedding: Optional[List[float]] = None
    source: str = "generated"  # "generated" | "tool" | "user" — for convergent-hallucination detection

    def __post_init__(self):
        if self.event_type != EventType.MEMORY_WRITE:
            self.event_type = EventType.MEMORY_WRITE


@dataclass
class MemoryReadEvent(LoopEvent):
    key: str = ""
    value_returned: Any = None

    def __post_init__(self):
        if self.event_type != EventType.MEMORY_READ:
            self.event_type = EventType.MEMORY_READ


@dataclass
class ToolCallEvent(LoopEvent):
    tool_name: str = ""
    args: dict = field(default_factory=dict)
    result: Any = None
    status_code: Optional[int] = None  # HTTP tools only
    duration_ms: Optional[float] = None
    success: bool = True

    def __post_init__(self):
        if self.event_type != EventType.TOOL_CALL:
            self.event_type = EventType.TOOL_CALL


@dataclass
class LLMCallEvent(LoopEvent):
    model: str = ""
    prompt_hash: str = ""
    prompt_preview: str = ""
    response_text: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self):
        if self.event_type != EventType.LLM_CALL:
            self.event_type = EventType.LLM_CALL


@dataclass
class DecisionEvent(LoopEvent):
    decision_key: str = ""
    decision_value: Any = None
    decision_type: str = ""  # e.g. "plan", "route", "action"

    def __post_init__(self):
        if self.event_type != EventType.DECISION:
            self.event_type = EventType.DECISION


# ---------------------------------------------------------------------------
# Detection output
# ---------------------------------------------------------------------------

@dataclass
class LoopDetection:
    """Output of a classifier. Fully self-describing.

    A UI or log consumer should be able to render the full "why did this fire"
    story from this struct alone — no extra lookups.
    """
    loop_type: LoopType
    confidence: Confidence
    rule_version: str
    agent_id: str
    matched_event_timestamps: List[float]
    evidence: dict  # structured rule-match evidence (keys, similarity values, etc.)
    rule_description: str  # human-readable rule text (for "Why did this fire?" panel)
    suggested_fix: Optional[str] = None  # optional per-type fix template
