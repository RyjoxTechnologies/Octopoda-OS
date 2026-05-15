"""Detection orchestrator.

Runs all enabled classifiers against an event window and returns the
combined list of detections (one per rule that fired, flattened across
all classifiers).

DESIGN:
  - Classifiers are independent; one can fire without blocking another.
  - A classifier may return:
      * a single LoopDetection (legacy single-result classifiers)
      * a list of LoopDetections (multi-result classifiers — reflection,
        recall_write, ping_pong can each fire on multiple keys)
      * None / [] — no detection
  - Multiple simultaneous detections for one agent are valid.
  - Detections are sorted by (confidence desc, loop_type alphabetical)
    for stable UI display.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Union

from .models import LoopEvent, LoopDetection, Confidence
from .classifiers import (
    classify_retry,
    classify_polling,
    classify_decision_oscillation,
    classify_cost_inflation,
    classify_self_correction,
    classify_ping_pong,
    classify_tool_nondeterminism,
    classify_recall_write,
    classify_clarification,
    classify_reflection,
)


ClassifyResult = Union[LoopDetection, List[LoopDetection], None]


class Classifier:
    """Binding of (name, classify function) for orchestration + logging."""

    def __init__(self, name: str, fn: Callable[[List[LoopEvent], str], ClassifyResult]):
        self.name = name
        self.fn = fn


DEFAULT_CLASSIFIERS: List[Classifier] = [
    Classifier("retry", classify_retry),
    Classifier("polling", classify_polling),
    Classifier("decision_oscillation", classify_decision_oscillation),
    Classifier("cost_inflation", classify_cost_inflation),
    Classifier("self_correction", classify_self_correction),
    Classifier("ping_pong", classify_ping_pong),
    Classifier("tool_nondeterminism", classify_tool_nondeterminism),
    Classifier("recall_write", classify_recall_write),
    Classifier("clarification", classify_clarification),
    Classifier("reflection", classify_reflection),
]


_CONFIDENCE_ORDER = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}


def _normalize(result: ClassifyResult) -> List[LoopDetection]:
    """Flatten a classifier result to a list (possibly empty)."""
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def detect(
    events: List[LoopEvent],
    agent_id: str,
    classifiers: Optional[List[Classifier]] = None,
) -> List[LoopDetection]:
    """Run all classifiers; return every detection that fired.

    Classifiers may return a single LoopDetection, a list of them, or None.
    All forms are accepted and flattened into the output list.
    """
    active = classifiers if classifiers is not None else DEFAULT_CLASSIFIERS
    detections: List[LoopDetection] = []
    for c in active:
        try:
            raw = c.fn(events, agent_id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "classifier %s raised: %s", c.name, exc
            )
            continue
        detections.extend(_normalize(raw))

    detections.sort(
        key=lambda d: (_CONFIDENCE_ORDER[d.confidence], d.loop_type.value)
    )
    return detections
