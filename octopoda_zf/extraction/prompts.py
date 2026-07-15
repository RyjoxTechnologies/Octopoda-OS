"""Extraction prompt + output schema.

The prompt is the single highest-leverage artifact in the whole rebuild: it
determines extraction precision, which determines whether auto-instrument
produces signal or noise (the core bet, per RFC § 1).

Kept in its own module so it can be versioned + A/B tested (OCTOPODA_EXTRACTOR
flag) without touching pipeline code.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
You are a memory extractor for AI agents. Given a transcript of an agent's \
conversation, identify the small number of DURABLE facts worth remembering for \
future runs.

Return ONLY a JSON object of the form {"facts": [ ... ]}, where each element of \
the "facts" array is:
{
  "type": "memory" | "goal" | "decision" | "preference",
  "subject": "what or who the fact is about",
  "predicate": "the relation, short",
  "value": "the fact itself, using the transcript's own words",
  "confidence": 0.0 to 1.0
}

Definitions:
- "goal": something the user wants to achieve.
- "decision": a choice that was made (not merely discussed).
- "preference": a stated like/dislike or default setting.
- "memory": any other durable, future-useful knowledge.

Rules:
- Only include facts that would genuinely help a FUTURE agent. A good test: \
would recalling this save work or avoid a mistake next session?
- SKIP: greetings, filler, errors, failed tool calls, debug output, restatements \
of your own instructions, and anything transient ("user said hi just now").
- NEVER include credentials, API keys, passwords, tokens, or personal contact \
information, even if present in the transcript.
- Use the transcript's own language. Do not invent or embellish.
- Prefer 0 to 5 facts. If nothing is worth remembering, return {"facts": []}.
- Set confidence honestly: 0.9+ for explicit clear statements, 0.6-0.8 for \
reasonable inferences, below 0.6 for guesses (which will be dropped).
"""

USER_PROMPT_TEMPLATE = """\
Transcript:
{transcript}

Return the JSON array of durable facts now.
"""


def build_messages(transcript: str) -> tuple[str, str]:
    """Return (system, user) prompt pair for the LLM client."""
    return SYSTEM_PROMPT, USER_PROMPT_TEMPLATE.format(transcript=transcript)
