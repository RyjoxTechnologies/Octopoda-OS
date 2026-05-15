"""Rule registry — single source of truth for what rules exist, their
versions, accuracy targets, and current measured metrics.

The UI reads this to populate the "What rules are active?" panel and the
per-type precision/recall display. Deployment scripts read it to validate
rules are registered before enabling them.

The registry is in-code (not DB) so it ships atomically with the rule
versions themselves — no drift between what's deployed and what's claimed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import LoopType


@dataclass
class RuleSpec:
    loop_type: LoopType
    version: str
    description_short: str   # one-line human description for the UI
    status: str              # "shadow" | "live" | "deprecated"
    target_precision: float  # from the plan
    target_recall: float     # from the plan
    measured_precision: Optional[float] = None
    measured_recall: Optional[float] = None
    measured_at: Optional[str] = None  # ISO 8601
    corpus_version: Optional[str] = None
    notes: str = ""

    @property
    def meets_targets(self) -> Optional[bool]:
        if self.measured_precision is None or self.measured_recall is None:
            return None
        return (
            self.measured_precision >= self.target_precision
            and self.measured_recall >= self.target_recall
        )


RULES: Dict[LoopType, RuleSpec] = {
    LoopType.RETRY: RuleSpec(
        loop_type=LoopType.RETRY,
        version="retry-v1.0",
        description_short="Repeated failed calls to the same tool with identical args.",
        status="live",
        target_precision=0.95,
        target_recall=0.90,
    ),
    LoopType.POLLING: RuleSpec(
        loop_type=LoopType.POLLING,
        version="polling-v1.0",
        description_short="Scheduled polling that keeps returning identical data.",
        status="live",
        target_precision=0.90,
        target_recall=0.85,
    ),
    LoopType.DECISION_OSCILLATION: RuleSpec(
        loop_type=LoopType.DECISION_OSCILLATION,
        version="decision-oscillation-v1.0",
        description_short="Agent flip-flopping between two values on the same decision key.",
        status="live",
        target_precision=0.95,
        target_recall=0.90,
    ),
    LoopType.COST_INFLATION: RuleSpec(
        loop_type=LoopType.COST_INFLATION,
        version="cost-inflation-v1.0",
        description_short="Same prompt retried on progressively bigger models.",
        status="live",
        target_precision=0.95,
        target_recall=0.90,
    ),
    LoopType.SELF_CORRECTION: RuleSpec(
        loop_type=LoopType.SELF_CORRECTION,
        version="self-correction-v1.0",
        description_short="Agent repeatedly second-guesses itself across LLM calls.",
        status="live",
        target_precision=0.85,
        target_recall=0.75,
    ),
    LoopType.PING_PONG: RuleSpec(
        loop_type=LoopType.PING_PONG,
        version="ping-pong-v1.0",
        description_short="Two agents alternating writes to the same shared key.",
        status="live",
        target_precision=0.95,
        target_recall=0.85,
    ),
    LoopType.TOOL_NONDETERMINISM: RuleSpec(
        loop_type=LoopType.TOOL_NONDETERMINISM,
        version="tool-nondeterminism-v1.0",
        description_short="Same tool + same input returns different outputs repeatedly.",
        status="live",
        target_precision=0.90,
        target_recall=0.80,
    ),
    LoopType.RECALL_WRITE: RuleSpec(
        loop_type=LoopType.RECALL_WRITE,
        version="recall-write-v1.0",
        description_short="Agent reads a key and writes back a near-identical value.",
        status="live",
        target_precision=0.85,
        target_recall=0.75,
    ),
    LoopType.CLARIFICATION: RuleSpec(
        loop_type=LoopType.CLARIFICATION,
        version="clarification-v1.0",
        description_short="Agent keeps asking the same question, slightly rephrased.",
        status="shadow",  # language-heuristic — shadow first
        target_precision=0.80,
        target_recall=0.70,
        notes="In shadow mode pending real-data validation.",
    ),
    LoopType.REFLECTION: RuleSpec(
        loop_type=LoopType.REFLECTION,
        version="reflection-v1.0",
        description_short="Same artifact revised repeatedly with minor tweaks.",
        status="live",
        target_precision=0.85,
        target_recall=0.75,
    ),
}


def list_rules(status: Optional[str] = None) -> List[RuleSpec]:
    """Return rules optionally filtered by lifecycle status."""
    if status is None:
        return list(RULES.values())
    return [r for r in RULES.values() if r.status == status]


def get_rule(loop_type: LoopType) -> Optional[RuleSpec]:
    return RULES.get(loop_type)


def record_measurement(
    loop_type: LoopType,
    precision: float,
    recall: float,
    corpus_version: str,
    measured_at: str,
) -> None:
    """Update a rule's measured metrics from a corpus run.

    Kept in-memory for the life of the process; intended to be called by
    a CI job or the shadow-mode reviewer. For persistent storage, wire
    this to a DB-backed store in the integration phase.
    """
    rule = RULES.get(loop_type)
    if rule is None:
        raise KeyError(f"Unknown loop type: {loop_type}")
    rule.measured_precision = precision
    rule.measured_recall = recall
    rule.corpus_version = corpus_version
    rule.measured_at = measured_at
