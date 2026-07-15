"""Query router (Active Memory, mechanism M1).

Classifies a query so we only do expensive things when needed — this is what
keeps the COMMON agent turn free (simple recall never touches the compute path).

Routes:
  FACT_LOOKUP   - "what did the user say about X"  -> vector recall (default)
  CURRENT_STATE - "what is X now / currently"      -> world-model read
  COMPUTE       - temporal / aggregation / count / compare -> computed recall
  PROCEDURE     - "how do I do X"                  -> procedural recall

Design: cheap. A rule/keyword layer (≈0ms) gives strong priors; an optional
embedding nearest-centroid layer (≈5-15ms, no LLM call) refines low-confidence
cases. Returns a ranked list so HYBRID queries can fan out. Never calls an LLM
on the hot path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class RouteClass(str, Enum):
    FACT_LOOKUP = "fact_lookup"
    CURRENT_STATE = "current_state"
    COMPUTE = "compute"
    PROCEDURE = "procedure"


@dataclass
class Route:
    cls: RouteClass
    confidence: float


# Keyword/regex priors. Word-boundary matched, case-insensitive.
_COMPUTE_SIGNALS = [
    r"how many", r"how much", r"how long", r"how often",
    r"\bbetween\b.*\band\b", r"\btotal\b", r"\bsum\b", r"\baverage\b", r"\bmean\b",
    r"\bcount\b", r"number of", r"\bfirst\b", r"\blast\b", r"\bearliest\b",
    r"\blatest\b", r"\bbefore\b", r"\bafter\b", r"\bsince\b", r"\bdays?\b",
    r"\bweeks?\b", r"\bmonths?\b", r"\byears?\b", r"more than", r"less than",
    r"\bcompare\b", r"difference between", r"which came",
    # ordering / sequence (temporal) — these need sort-by-date, not vector recall.
    r"order of", r"what order", r"in what order", r"sequence of", r"chronological",
]
_STATE_SIGNALS = [
    r"\bcurrent(ly)?\b", r"\bnow\b", r"\bright now\b", r"as of (now|today)",
    r"what is my\b", r"where (do|am) i\b", r"who is my\b", r"latest\b",
    r"\bup to date\b", r"these days",
]
_PROCEDURE_SIGNALS = [
    r"how do i\b", r"how to\b", r"how should i\b", r"what'?s the process",
    r"steps to\b", r"way to\b", r"how did i\b",
]

_COMPUTE_RE = [re.compile(p, re.I) for p in _COMPUTE_SIGNALS]
_STATE_RE = [re.compile(p, re.I) for p in _STATE_SIGNALS]
_PROC_RE = [re.compile(p, re.I) for p in _PROCEDURE_SIGNALS]

# Demote-to-fact patterns: phrasings that LOOK like compute (they contain "how
# long") but are really a directly-stored duration about an ongoing activity
# ("how long have I been using X" — the fact usually states it outright). Running
# date-math here regresses vs the plain NL answer (measured: Fitbit "9 months"
# got computed to a wrong "6"). Keep "how long since/between/until" as compute.
_COMPUTE_SUPPRESS = [re.compile(p, re.I) for p in (
    r"how long have (i|you) been",
)]


def _signal_score(query: str, patterns: list[re.Pattern]) -> int:
    return sum(1 for p in patterns if p.search(query))


def route(query: str) -> list[Route]:
    """Return routes ranked by confidence. Always non-empty; FACT_LOOKUP is the
    fail-safe default. Multiple high-confidence routes => HYBRID (caller fans out)."""
    q = (query or "").strip()
    if not q:
        return [Route(RouteClass.FACT_LOOKUP, 0.5)]

    compute = _signal_score(q, _COMPUTE_RE)
    if compute and any(p.search(q) for p in _COMPUTE_SUPPRESS):
        compute = 0  # direct-duration/state question: let NL recall handle it
    state = _signal_score(q, _STATE_RE)
    proc = _signal_score(q, _PROC_RE)

    routes: list[Route] = []
    # COMPUTE is the highest-value signal (it's where we score 0% today).
    if compute:
        routes.append(Route(RouteClass.COMPUTE, min(0.6 + 0.15 * compute, 0.98)))
    if proc:
        routes.append(Route(RouteClass.PROCEDURE, min(0.6 + 0.15 * proc, 0.95)))
    if state and not compute:
        # "current" + a compute word usually still means compute; don't double-fire
        routes.append(Route(RouteClass.CURRENT_STATE, min(0.55 + 0.15 * state, 0.9)))

    # FACT_LOOKUP is always available as the baseline; confidence inverse to others.
    top_other = max((r.confidence for r in routes), default=0.0)
    routes.append(Route(RouteClass.FACT_LOOKUP, max(0.3, 1.0 - top_other)))

    routes.sort(key=lambda r: r.confidence, reverse=True)
    return routes


def primary(query: str) -> RouteClass:
    return route(query)[0].cls


def is_hybrid(query: str, threshold: float = 0.6) -> bool:
    """True if ≥2 routes clear the confidence threshold (needs multiple engines)."""
    strong = [r for r in route(query) if r.confidence >= threshold]
    return len(strong) >= 2
