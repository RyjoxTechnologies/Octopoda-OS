"""LLM client abstraction for the extractor.

Production uses gpt-4o-mini (ADR-006). For tests we use `MockLLMClient` so the
pipeline runs with no API key, no network, and deterministic output.

The seam is the `LLMClient` protocol. `extractor.py` depends only on the
protocol, never on a concrete client.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Minimal completion interface the extractor needs."""

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        """Return the model's text response (expected to be JSON)."""
        ...


class MockLLMClient:
    """Test double.

    Construct with either:
    - a dict mapping a substring-of-user-prompt -> canned response, or
    - a callable (system, user) -> response string.

    Lets tests force malformed JSON, empty arrays, specific facts, etc.
    """

    def __init__(
        self,
        responder: dict[str, str] | Callable[[str, str], str] | None = None,
        default: str = "[]",
    ) -> None:
        self._responder = responder
        self._default = default
        self.calls: list[tuple[str, str]] = []  # (system, user) for assertions

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        if self._responder is None:
            return self._default
        if callable(self._responder):
            return self._responder(system, user)
        # dict: first key that is a substring of the user prompt wins
        for needle, response in self._responder.items():
            if needle in user:
                return response
        return self._default


class OpenAIExtractorClient:
    """Production client (gpt-4o-mini). Thin wrapper over the OpenAI SDK.

    NOT exercised in unit tests (no network). Integration tests in Phase 1
    wire this with a real key. Kept import-lazy so the package doesn't hard-
    depend on `openai` for users who only use the explicit SDK.
    """

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model
        self._client = None  # lazy

    def _ensure(self) -> None:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:  # pragma: no cover - import guard
                raise RuntimeError(
                    "OpenAIExtractorClient requires the 'openai' package. "
                    "Install it or inject a different LLMClient."
                ) from e
            self._client = OpenAI(api_key=self._api_key)

    def complete(self, *, system: str, user: str, max_tokens: int) -> str:  # pragma: no cover
        self._ensure()
        # Re-entrancy guard: this LLM call goes through the SAME openai SDK that
        # auto-instrument patches. Without the guard it would be intercepted ->
        # recall + capture -> extract again -> infinite loop. The guard makes the
        # wrapper pass our own call straight through. (Lazy import avoids any
        # module load-order cycle between extraction and instrument.)
        from ..instrument.base import reentrancy_guard

        with reentrancy_guard():
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or "[]"


def safe_parse_facts(raw: str) -> list[dict] | None:
    """Parse the extractor's JSON output defensively.

    Returns a list of dicts, or None if unparseable (caller decides whether to
    retry or drop). Handles:
    - bare JSON arrays: `[ {...}, {...} ]`
    - object-wrapped arrays: `{ "facts": [ ... ] }`
    - markdown-fenced JSON: ```json ... ```
    - trailing prose after the JSON
    """
    if not raw or not raw.strip():
        return []

    text = raw.strip()

    # Strip markdown fences if present.
    if text.startswith("```"):
        # remove first fence line and trailing fence
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct parse first.
    parsed = _try_json(text)
    if parsed is not None:
        return _coerce_to_list(parsed)

    # Try to locate the first JSON array or object in the text.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            parsed = _try_json(candidate)
            if parsed is not None:
                return _coerce_to_list(parsed)

    return None


def _try_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _coerce_to_list(parsed) -> list[dict]:
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict):
        # common wrappers
        for key in ("facts", "items", "memories", "results", "data"):
            if isinstance(parsed.get(key), list):
                return [x for x in parsed[key] if isinstance(x, dict)]
        # single fact object
        if {"value", "subject"} & set(parsed.keys()):
            return [parsed]
        # defensive fallback: any value that is a list of dicts (handles models
        # that wrap the array under an unexpected key name in json_object mode)
        for v in parsed.values():
            if isinstance(v, list) and any(isinstance(x, dict) for x in v):
                return [x for x in v if isinstance(x, dict)]
    return []
