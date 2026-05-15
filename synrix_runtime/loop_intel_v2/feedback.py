"""Feedback recorder — captures user signals about detections.

Every alert shown in the UI has a "This was wrong" / "This was correct"
button. This module provides the interface those buttons call.

Storage:
  - Default: in-memory (for tests + early dev).
  - Interface abstracts the backend so integration can swap in a DB store
    without changing callers.

Schema of a feedback record:
  tenant_id, agent_id, rule_version, loop_type, verdict, at_timestamp,
  detection_ref (optional pointer to original alert), notes (optional free text)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Protocol

from .models import LoopType


class Verdict(str, Enum):
    """What the user said about the alert."""
    CORRECT = "correct"                # "yes this was a real loop"
    FALSE_POSITIVE = "false_positive"  # "no this wasn't a loop"
    WRONG_TYPE = "wrong_type"          # "it was a loop but not this type"
    UNCLEAR = "unclear"                # "I can't tell — investigate"


@dataclass
class FeedbackRecord:
    tenant_id: str
    agent_id: str
    rule_version: str
    loop_type: LoopType
    verdict: Verdict
    at_timestamp: float = field(default_factory=lambda: time.time())
    detection_ref: Optional[str] = None
    corrected_type: Optional[LoopType] = None  # set if verdict == WRONG_TYPE
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


class FeedbackStore(Protocol):
    def record(self, fb: FeedbackRecord) -> None: ...
    def all(self) -> List[FeedbackRecord]: ...
    def by_rule_version(self, rule_version: str) -> List[FeedbackRecord]: ...
    def false_positive_count(self, rule_version: str) -> int: ...


class InMemoryFeedbackStore:
    """Default store. Persistent for process lifetime only.

    Integration phase will replace with a DB-backed store implementing
    the same Protocol.
    """

    def __init__(self):
        self._records: List[FeedbackRecord] = []

    def record(self, fb: FeedbackRecord) -> None:
        self._records.append(fb)

    def all(self) -> List[FeedbackRecord]:
        return list(self._records)

    def by_rule_version(self, rule_version: str) -> List[FeedbackRecord]:
        return [r for r in self._records if r.rule_version == rule_version]

    def by_loop_type(self, loop_type: LoopType) -> List[FeedbackRecord]:
        return [r for r in self._records if r.loop_type == loop_type]

    def false_positive_count(self, rule_version: str) -> int:
        return sum(
            1 for r in self._records
            if r.rule_version == rule_version and r.verdict == Verdict.FALSE_POSITIVE
        )

    def precision_estimate(self, rule_version: str) -> Optional[float]:
        """Estimate precision from user feedback alone.

        Returns precision = correct / (correct + false_positive) among
        users who gave verdicts for this rule version. Returns None if
        no feedback received yet.

        NOTE: user feedback is biased — users report FP more often than
        they confirm TP. Use in combination with corpus measurements,
        not instead of.
        """
        rule_records = self.by_rule_version(rule_version)
        correct = sum(1 for r in rule_records if r.verdict == Verdict.CORRECT)
        fp = sum(1 for r in rule_records if r.verdict == Verdict.FALSE_POSITIVE)
        if correct + fp == 0:
            return None
        return correct / (correct + fp)


# Module-level default store. Callers can swap via `set_store`.
_default_store: FeedbackStore = InMemoryFeedbackStore()


def set_store(store: FeedbackStore) -> None:
    global _default_store
    _default_store = store


def record(fb: FeedbackRecord) -> None:
    _default_store.record(fb)


def get_store() -> FeedbackStore:
    return _default_store
