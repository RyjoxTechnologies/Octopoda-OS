"""EMem-style EDU extraction (event-centric memory — the advanced-tier representation).

Decompose a transcript into ENRICHED ELEMENTARY DISCOURSE UNITS (EDUs): short,
self-contained, third-person, event-like propositions (one event/action/decision/
preference/fact each, with participants + temporal cue + minimal context, entities
verbatim). Stored alongside facts + chunks; on the LongMemEval ablation the EDU layer
lifted recall toward Zep-level (docs/MEMORY_QUALITY_PLAN §0.5 + the gpt-4o confirmation).

Uses the extractor LLM in JSON mode: {"edus": ["...", ...]}. Fail-soft — any error
returns []. The caller sanitizes the transcript BEFORE calling this (EDUs must not
carry secrets the fact path would redact).
"""

from __future__ import annotations

import json

from .llm import LLMClient

_EDU_SYSTEM = (
    "You build an EVENT-CENTRIC memory of a USER from a chat transcript. Decompose it "
    "into ENRICHED ELEMENTARY DISCOURSE UNITS (EDUs): short, self-contained, THIRD-"
    "PERSON statements about the user — each capturing exactly one event, action, "
    "decision, plan, preference, status, or fact. Write ABOUT the user (e.g. 'The user "
    "watched an NBA game at the Staples Center on 2023/01/05'); NEVER copy the dialogue "
    "or use 'user:'/'assistant:'. Each EDU stands alone: who/what, any date, and minimal "
    "context; keep entities VERBATIM (names, places, numbers, brands, amounts, dates). "
    "Include ONLY real, grounded information the user stated or that happened to them — "
    "IGNORE the assistant's generic suggestions, brainstorming, tips, and hypotheticals. "
    'Respond with ONLY JSON: {"edus": ["edu one", "edu two", ...]} (empty list if none).'
)


def extract_edus(
    transcript: str, llm: LLMClient, *, max_edus: int = 12, max_tokens: int = 600
) -> list[str]:
    """Return EMem EDUs for a transcript (already sanitized by the caller). Fail-soft."""
    if not transcript or not transcript.strip():
        return []
    try:
        raw = llm.complete(system=_EDU_SYSTEM, user=transcript[:6000], max_tokens=max_tokens)
    except Exception:
        return []
    return _parse_edus(raw)[:max_edus]


def _parse_edus(raw: str) -> list[str]:
    """Tolerant parse of {"edus": [...]} — handles markdown fences, wrapper-key drift,
    and bare arrays. Drops trivially-short entries."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    parsed = _try_json(text)
    if parsed is None:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            parsed = _try_json(text[start : end + 1])
    if parsed is None:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            parsed = _try_json(text[start : end + 1])
    if parsed is None:
        return []

    items: list = []
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        for key in ("edus", "units", "items", "results", "data"):
            if isinstance(parsed.get(key), list):
                items = parsed[key]
                break
        else:
            for v in parsed.values():  # any list-of-strings under an unexpected key
                if isinstance(v, list) and any(isinstance(x, str) for x in v):
                    items = v
                    break
    return [str(x).strip() for x in items if isinstance(x, str) and len(str(x).strip()) >= 12]


def _try_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
