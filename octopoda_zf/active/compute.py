"""Computed recall engine (Active Memory, mechanism M2).

For COMPUTE-routed queries: ask the model to write Python over the retrieved
facts, validate it (anti-hallucination grounding), execute it in the sandbox,
and return a deterministic answer + the code (the provenance).

Golden rule: NEVER worse than today. Any failure (bad code, ungrounded literal,
sandbox error, timeout) returns ok=False so the caller falls back to the normal
natural-language answer over the same facts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..extraction.llm import LLMClient
from .sandbox import RestrictedSandbox, Sandbox, literals_grounded

logger = logging.getLogger("octopoda.active.compute")

CODEGEN_SYSTEM = """\
You write short Python that COMPUTES the answer to a question from a set of
facts. Rules:
- Extract the needed values as literals FROM THE FACTS ONLY. Never invent a
  number or date that is not in the facts.
- Do the arithmetic / sorting / counting / date-math.
- Assign the final answer to a variable named `result`, as a concise
  natural-language STRING — never a raw list or dict. For an ordering/sequence,
  spell it out ("First X, then Y, then Z"). For a count or duration a short
  phrase or number is fine ("4", "24 days").
- You may use only: datetime, math, statistics. No I/O, no network, no other
  imports.
- Output ONLY the code. No prose, no markdown fences, no explanation.
- If the facts are insufficient to compute the answer, output exactly:
  result = "INSUFFICIENT"
"""

CODEGEN_USER = """\
Facts:
{facts}

Question: {question}

Write the Python now (assign to `result`):"""


@dataclass
class ComputeResult:
    ok: bool
    answer: str = ""
    code: str = ""
    fallback_used: bool = False
    error: str = ""


def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


class ComputedRecall:
    def __init__(
        self,
        llm: LLMClient,
        sandbox: Sandbox | None = None,
        *,
        ground_literals: bool = True,
        retries: int = 1,
        max_tokens: int = 300,
    ) -> None:
        self._llm = llm
        self._sandbox = sandbox or RestrictedSandbox()
        self._ground = ground_literals
        self._retries = retries
        self._max_tokens = max_tokens

    def compute(self, question: str, facts: str) -> ComputeResult:
        """Compute the answer by code. ok=False means the caller should fall
        back to a normal NL answer (never worse than today)."""
        if not question.strip() or not facts.strip():
            return ComputeResult(ok=False, fallback_used=True, error="empty input")

        user = CODEGEN_USER.format(facts=facts[:6000], question=question)
        last_err = ""
        for attempt in range(self._retries + 1):
            prompt_user = user if attempt == 0 else (
                user + f"\n\n(Your previous code failed: {last_err}. Fix it.)"
            )
            try:
                raw = self._llm.complete(
                    system=CODEGEN_SYSTEM, user=prompt_user, max_tokens=self._max_tokens
                )
            except Exception as e:
                return ComputeResult(ok=False, fallback_used=True, error=f"codegen: {e}")

            code = _strip_code_fences(raw)
            if not code:
                last_err = "empty code"
                continue

            # anti-hallucination: literals must be grounded in the facts
            if self._ground and not literals_grounded(code, facts):
                last_err = "code used a value not in the facts"
                logger.debug("computed recall rejected ungrounded code")
                continue

            res = self._sandbox.run(code)
            if not res.ok:
                last_err = res.error
                continue

            if res.result.strip().upper() == "INSUFFICIENT":
                return ComputeResult(ok=False, code=code, fallback_used=True,
                                     error="insufficient facts")

            return ComputeResult(ok=True, answer=res.result, code=code)

        # all attempts failed -> caller falls back to NL
        return ComputeResult(ok=False, fallback_used=True, error=last_err)
