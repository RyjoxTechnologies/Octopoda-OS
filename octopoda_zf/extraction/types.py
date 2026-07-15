"""Core data types for the extraction pipeline.

A `Fact` is the unit of durable memory. Extraction turns a raw transcript into
a list of Facts; importance filtering drops the weak ones; dedup merges the
repeats; the survivors are written to Octopoda via the existing
/v1/agents/{id}/remember endpoint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class FactType(str, Enum):
    """What kind of durable knowledge a fact represents.

    The extractor classifies each fact so the dashboard can route it to the
    right tab (Goals, Decisions) and so recall can weight by type.
    """

    MEMORY = "memory"          # general durable knowledge
    GOAL = "goal"              # something the user wants to achieve
    DECISION = "decision"      # a choice that was made
    PREFERENCE = "preference"  # a stated like/dislike or default

    @classmethod
    def from_str(cls, raw: str) -> FactType:
        """Tolerant parse: unknown/empty defaults to MEMORY."""
        if not raw:
            return cls.MEMORY
        try:
            return cls(raw.strip().lower())
        except ValueError:
            return cls.MEMORY


_KEY_SAFE = re.compile(r"[^a-z0-9]+")


@dataclass
class Fact:
    """A single durable fact extracted from a transcript.

    Fields mirror a simple (subject, predicate, value) triple plus metadata.
    `confidence` is the extractor LLM's self-reported certainty in [0, 1].
    """

    type: FactType
    subject: str
    predicate: str
    value: str
    confidence: float
    source_turn: int | None = None
    tags: list[str] = field(default_factory=list)
    # bumped when dedup merges a later identical fact into this one
    occurrences: int = 1

    def __post_init__(self) -> None:
        # Normalize/validate on construction so downstream code can trust it.
        self.subject = (self.subject or "").strip()
        self.predicate = (self.predicate or "").strip()
        self.value = (self.value or "").strip()
        if not isinstance(self.type, FactType):
            self.type = FactType.from_str(str(self.type))
        # Clamp confidence into [0, 1] defensively (LLMs return junk sometimes).
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.0

    def to_text(self) -> str:
        """Human-readable single line, also used for embedding/dedup."""
        parts = [p for p in (self.subject, self.predicate, self.value) if p]
        return " ".join(parts).strip()

    def to_memory_key(self) -> str:
        """Stable-ish key for the remember() call.

        Format: `<type>:<slug-of-subject-predicate>`. Not guaranteed unique
        (dedup handles collisions), but human-scannable in the dashboard.
        """
        base = f"{self.subject}-{self.predicate}".lower()
        slug = _KEY_SAFE.sub("-", base).strip("-")[:60] or "fact"
        return f"{self.type.value}:{slug}"

    def to_remember_payload(self) -> dict:
        """Shape sent to the existing /v1/agents/{id}/remember endpoint.

        Mirrors the existing memory `data` jsonb convention: a `value` plus
        metadata tags. Kept deliberately close to what the explicit SDK writes
        so the dashboard renders it identically.
        """
        return {
            "key": self.to_memory_key(),
            "value": {
                "value": self.to_text(),
                "fact_type": self.type.value,
                "subject": self.subject,
                "predicate": self.predicate,
                "confidence": round(self.confidence, 3),
                "occurrences": self.occurrences,
                "tags": list(self.tags),
                "source": "auto-instrument",
            },
        }

    def is_empty(self) -> bool:
        return not self.to_text()
