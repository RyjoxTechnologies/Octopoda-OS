"""Reflection loop classifier.

RULE:
  Flag a reflection loop when the same memory key is overwritten ≥3
  times and each successive value is ≥0.65 similar to the prior value
  (revisions, not replacements).

  One agent can be in MULTIPLE reflection loops simultaneously (one per
  key). This classifier returns every qualifying key as a separate
  detection — no "best key" heuristic.

CONFIDENCE:
  - high:   ≥3 writes to same key, all consecutive pairwise sim ≥0.80
  - medium: ≥3 writes, all consecutive pairwise sim ≥0.65
  - low:    not emitted

FALSE POSITIVES WE AVOID:
  - Completely different consecutive values → not revision.
  - Different keys in isolation → each evaluated independently.
  - Near-duplicate writes (max pair ≥0.995) → handled by dedup, not reflection.
  - Interleaved reads on the same key → that's recall-write territory.
"""

from __future__ import annotations

from collections import defaultdict
from typing import List

from ..models import (
    LoopEvent,
    EventType,
    MemoryWriteEvent,
    LoopDetection,
    LoopType,
    Confidence,
)
from ..similarity import text_similarity

RULE_VERSION = "reflection-v1.2"


def _build_specific_fix(
    agent_id: str,
    key: str,
    min_pair: float,
    max_pair: float,
    revision_count: int,
) -> str:
    """Pattern-aware suggested fix.

    Beats the previous one-size-fits-all template by recognising common key
    shapes and giving advice that's actually true for that pattern. Examples:

      - keys ending in 'running-summary' / ':summary' → likely intentional
        rolling summary (LangChain ConversationSummaryMemory pattern); the
        right fix is to dedup-exclude or whitelist the pattern, not to
        "lower reflection_rounds"
      - 'recovery-marker' keys → reflection here is a symptom of repeated
        crashes, not a reflection trap; point user at recovery history
      - 'health-check' / status keys → polling overhead, not reflection;
        suggest reducing poll frequency or using ephemeral memory
      - 'contested-fact' → decision oscillation surfacing as repeated writes;
        suggest separate keys per view
      - 'goal:current' / goal:* → real goal oscillation; cap planner iterations
      - default → install a dedup guard with a calibrated threshold derived
        from the actual measured similarity, plus framework-agnostic capping
    """
    key_lower = key.lower()

    # 1. Rolling summary pattern (most common false positive on real LangChain users)
    if "running-summary" in key_lower or key_lower.endswith(":summary"):
        return (
            f"This artifact ('{key}') has a 'summary' shape — likely an "
            f"intentional rolling summary, not a reflection trap. "
            f"LangChainMemory's ConversationSummaryMemory and CrewAI's memory "
            f"adapters write progressively-compressed summaries to the same "
            f"key by design. {revision_count} revisions at min "
            f"{min_pair:.0%} similarity is consistent with that pattern.\n\n"
            f"If intentional (likely):\n"
            f"  • Install a dedup guard on '{key}' with similarity ≥ 0.99 — "
            f"only blocks true duplicates, leaves intentional summarisation alone\n"
            f"  • Or add this key pattern to the reflection classifier's "
            f"exclude list for agent '{agent_id}'\n\n"
            f"If unintentional:\n"
            f"  • Check your code for `ConversationSummaryMemory(...)` or a "
            f"`crew_summary` setting — likely enabled accidentally"
        )

    # 2. Recovery markers — symptom of repeated failures, not reflection
    if "recovery-marker" in key_lower or "crash" in key_lower:
        return (
            f"'{key}' is a recovery / crash marker. {revision_count} markers "
            f"in this window means the agent has been failing and recovering "
            f"repeatedly — the reflection here is a symptom, not the bug.\n\n"
            f"Action:\n"
            f"  • Inspect crash history: GET /v1/recovery/history?agent_id={agent_id}\n"
            f"  • Root cause is whatever's making the agent fail repeatedly, "
            f"not the markers themselves\n"
            f"  • Mark this detection as 'expected' to suppress — recovery "
            f"markers will always look similar to each other"
        )

    # 3. Health-check / status / ping keys — polling overhead
    if any(p in key_lower for p in ("health-check", ":status", ":heartbeat", ":ping")):
        return (
            f"'{key}' looks like a polling / status pattern. {revision_count} "
            f"writes at high similarity is monitoring overhead, not reflection.\n\n"
            f"Action:\n"
            f"  • Reduce poll frequency in the monitoring loop\n"
            f"  • Move health checks to ephemeral memory (use "
            f"`agent.heartbeat()` instead of `agent.remember()`) — they don't "
            f"need a durable audit trail\n"
            f"  • Or install a dedup guard at similarity ≥ 0.95 — redundant "
            f"writes get silently dropped without polluting the chain"
        )

    # 4. Contested-fact / disputed values — decision oscillation in disguise
    if "contested" in key_lower or "disputed" in key_lower:
        return (
            f"'{key}' has a 'contested' shape — agent is flip-flopping on a "
            f"single value. This is decision oscillation surfacing as "
            f"repeated writes, not a true reflection trap.\n\n"
            f"Action:\n"
            f"  • If the agent legitimately holds two opposing views, store "
            f"them under separate keys ('view-bull' and 'view-bear') instead "
            f"of overwriting one\n"
            f"  • If only one view should win: add a tie-breaker rule in the "
            f"agent's decision step (last-N-tool-results, confidence threshold)"
        )

    # 5. Goal oscillation — agent never commits to acting
    if key_lower.startswith("goal:") or "goal:current" in key_lower:
        return (
            f"Goal oscillation: agent has rewritten its goal {revision_count} "
            f"times in a narrow window, each ≥{min_pair:.0%} similar to the "
            f"prior. Classic plan/replan/plan loop — agent never commits to "
            f"executing.\n\n"
            f"Action (in order of effort):\n"
            f"  • Add a stop rule: don't accept a new goal if it's >80% "
            f"similar to the prior (the agent is essentially saying the same "
            f"thing again)\n"
            f"  • CrewAI: lower `max_iter` on the planner agent\n"
            f"  • LangChain: cap planner-loop iterations or use a "
            f"`StopAfterN` callback\n"
            f"  • Raw SDK: add a `goal_age_seconds` minimum before allowing "
            f"another goal write"
        )

    # 6. Default — actionable dedup guard suggestion with calibrated threshold
    suggested_threshold = max(0.80, min_pair * 0.95)
    return (
        f"{revision_count} writes to '{key}' in a narrow window, each "
        f"≥{min_pair:.0%} similar to the prior — agent is polishing the "
        f"same artifact repeatedly without external signal driving the change.\n\n"
        f"Concrete actions:\n"
        f"  • Install a dedup guard for this exact key. Threshold "
        f"{suggested_threshold:.2f} would have blocked {revision_count - 1} "
        f"of these {revision_count} writes:\n"
        f"      POST /v1/loops/v2/dedup-guard\n"
        f'      {{ "agent_id": "{agent_id}", '
        f'"key_pattern": "{key}", '
        f'"similarity_threshold": {suggested_threshold:.2f} }}\n'
        f"  • If using a reflection-mode framework (CrewAI, AutoGen with "
        f"reviewer roles): cap reflection_rounds at 2 for this artifact\n"
        f"  • If this is a known-good pattern (intentional refinement): "
        f"add this key to the classifier's exclude list to silence future alerts"
    )


def classify(events: List[LoopEvent], agent_id: str) -> List[LoopDetection]:
    """Return a list of reflection detections — one per qualifying key.

    Empty list = no reflection loops detected for this agent.
    """
    writes: List[MemoryWriteEvent] = [
        e for e in events
        if e.agent_id == agent_id and e.event_type == EventType.MEMORY_WRITE
    ]
    if len(writes) < 3:
        return []
    writes.sort(key=lambda e: e.timestamp)

    reads_by_key: dict = defaultdict(list)
    for e in events:
        if (
            e.agent_id == agent_id
            and e.event_type == EventType.MEMORY_READ
        ):
            key = getattr(e, "key", None)
            if key:
                reads_by_key[key].append(e.timestamp)

    by_key: dict = defaultdict(list)
    for w in writes:
        by_key[w.key].append(w)

    detections: List[LoopDetection] = []

    for key, chain in by_key.items():
        if len(chain) < 3:
            continue
        chain = chain[-6:]
        first_t = chain[0].timestamp
        last_t = chain[-1].timestamp
        read_ts = reads_by_key.get(key, [])
        if any(first_t < rt < last_t for rt in read_ts):
            continue
        pair_sims = [
            text_similarity(chain[i].value, chain[i + 1].value)
            for i in range(len(chain) - 1)
        ]
        min_pair = min(pair_sims)
        max_pair = max(pair_sims)
        if max_pair >= 0.995:
            continue  # duplicate-write thrash — not reflection

        if min_pair >= 0.80:
            confidence = Confidence.HIGH
        elif min_pair >= 0.65:
            confidence = Confidence.MEDIUM
        else:
            continue

        fix = _build_specific_fix(
            agent_id=agent_id,
            key=key,
            min_pair=min_pair,
            max_pair=max_pair,
            revision_count=len(chain),
        )

        detections.append(LoopDetection(
            loop_type=LoopType.REFLECTION,
            confidence=confidence,
            rule_version=RULE_VERSION,
            agent_id=agent_id,
            matched_event_timestamps=[w.timestamp for w in chain],
            evidence={
                "artifact_key": key,
                "revision_count": len(chain),
                "pairwise_similarities": [round(s, 3) for s in pair_sims],
                "min_pair_similarity": round(min_pair, 3),
                "max_pair_similarity": round(max_pair, 3),
                "window_start": chain[0].timestamp,
                "window_end": chain[-1].timestamp,
            },
            rule_description=(
                f"Reflection loop ({RULE_VERSION}): {len(chain)} writes to "
                f"key {key!r}, each revision ≥{min_pair:.0%} similar to the "
                f"prior. Agent is polishing the same draft repeatedly."
            ),
            suggested_fix=fix,
        ))

    return detections
