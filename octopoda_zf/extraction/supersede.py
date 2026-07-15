"""Write-time supersession (knowledge updates).

When a newly-learned fact REPLACES an existing memory (a location/status/owner/
value changed), the old memory should be removed so recall returns the CURRENT
fact, not the stale one. This closes the staleness gap measured in
docs/BENCHMARKS.md (0% -> 100% in the prototype).

Mem0 uses the same ADD/UPDATE/DELETE idea. We reuse the extraction LLM, so there
is no extra model dependency. The LLM judges single-valued changes ("lives in X"
-> replace) vs coexisting facts ("likes X" + "likes Y" -> keep both).
"""

from __future__ import annotations

import json
import logging

from .llm import LLMClient
from .types import Fact

logger = logging.getLogger("octopoda.extraction.supersede")

SUPERSEDE_SYSTEM = """\
You maintain an AI agent's long-term memory. NEW facts were just learned. Below
are EXISTING memories that may relate.

Decide which existing memories the new facts make OUTDATED (superseded or
contradicted) - e.g. a location, status, owner, plan, or value changed.

Return ONLY a JSON object: {"superseded": [list of integer ids]}.
- Include an id only if a new fact genuinely REPLACES it.
- Do NOT include facts that can coexist with the new ones (e.g. "likes Python"
  and "likes Rust" coexist; "lives in London" and "moved to Tokyo" do not).
- If none are superseded, return {"superseded": []}.
"""


def _parse_superseded_ids(raw: str) -> list[int]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # tolerate an array or fenced output
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return [int(x) for x in json.loads(raw[start : end + 1])]
            except Exception:
                return []
        return []
    if isinstance(data, dict):
        ids = data.get("superseded", [])
    elif isinstance(data, list):
        ids = data
    else:
        ids = []
    out = []
    for x in ids:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def detect_superseded_keys(
    llm: LLMClient,
    new_facts: list[Fact],
    existing: list[tuple[str, str]],
    max_tokens: int = 150,
) -> set[str]:
    """Return the set of existing-memory keys the new facts supersede.

    `existing` is a list of (key, text). Fail-soft: any error returns an empty
    set (no supersession) rather than raising - a missed supersession is far
    safer than wrongly deleting a memory."""
    if not new_facts or not existing:
        return set()
    new_text = "; ".join(f.to_text() for f in new_facts)
    listing = "\n".join(f"{i}: {text}" for i, (_key, text) in enumerate(existing))
    user = f"New facts: {new_text}\n\nExisting memories:\n{listing}"
    try:
        raw = llm.complete(system=SUPERSEDE_SYSTEM, user=user, max_tokens=max_tokens)
    except Exception as e:
        logger.debug("supersession LLM call failed (skipping): %s", e)
        return set()
    ids = _parse_superseded_ids(raw)
    return {existing[i][0] for i in ids if 0 <= i < len(existing) and existing[i][0]}
