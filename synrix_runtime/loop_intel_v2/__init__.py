"""Loop Intelligence v2 — rule-based, explainable, testable loop detection.

Every classifier in this package is:
  - Rule-based (no LLMs in the detection path)
  - Deterministic (same input → same output)
  - Versioned (rule_version is reported on every detection)
  - Unit-testable (pure functions of input events)
  - Self-documenting (rule text explains when it fires)

Public API:
  - LoopEvent, MemoryWriteEvent, MemoryReadEvent, ToolCallEvent, LLMCallEvent, DecisionEvent
  - LoopDetection, Confidence
  - Classifier (ABC), detect(events)
"""

from .models import (
    LoopEvent,
    EventType,
    MemoryWriteEvent,
    MemoryReadEvent,
    ToolCallEvent,
    LLMCallEvent,
    DecisionEvent,
    LoopDetection,
    Confidence,
    LoopType,
)
from .detection import detect, Classifier

__all__ = [
    "LoopEvent",
    "EventType",
    "MemoryWriteEvent",
    "MemoryReadEvent",
    "ToolCallEvent",
    "LLMCallEvent",
    "DecisionEvent",
    "LoopDetection",
    "Confidence",
    "LoopType",
    "Classifier",
    "detect",
]
