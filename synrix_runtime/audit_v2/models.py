"""audit_v2.models - event shape + safe string handling.

Dataclass for an audit event plus helpers that make sure we never store
unbounded blobs or PII-smelling things verbatim. All fields have strict
types so the UI never has to guess.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# Canonical event types. UI uses these for colored pills.
# Keep this list short - add new types here deliberately, not ad-hoc.
EVENT_TYPES = frozenset([
    # SDK primitives
    "memory.write",
    "memory.read",
    "memory.important",          # remember_important
    "memory.semantic_search",    # recall_similar
    "memory.prefix_search",      # search
    "memory.share",
    "memory.shared_read",
    "memory.delete",
    "memory.snapshot",       # explicit snapshot event
    # Framework adapters
    "conversation.message",      # LangChain
    "crew.task",                 # CrewAI
    "crew.finding",              # CrewAI
    "autogen.turn",              # AutoGen
    "thread.updated",            # OpenAI Assistants
    # MCP
    "tool.call",
    "tool.result",
    "tool.error",
    # Runtime
    "crash",
    "recovery",
    "decision",                  # explicit agent decision
    # LLM provider calls
    "llm.call",
    "llm.response",
    "llm.error",
])

# Sources the event can originate from.
SOURCES = frozenset(["sdk", "langchain", "crewai", "autogen", "openai", "mcp", "api"])

# Outcomes.
OUTCOMES = frozenset(["success", "fail", "timeout", "unknown"])

# Crude PII detectors. Not comprehensive - intentionally conservative.
# If a value looks like it contains PII we redact the preview but keep the
# event itself (the key, type, cost, latency all remain). This is one of
# the features we can strengthen later.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b")

# Max preview length we store. Prevents giant prompts from bloating audit.
MAX_PREVIEW = 240


def _redact(text: str) -> str:
    """Replace PII-looking substrings with [REDACTED_*]."""
    if not text:
        return text
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _CARD_RE.sub("[REDACTED_CARD]", text)
    text = _SSN_RE.sub("[REDACTED_SSN]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    return text


def safe_preview(value: Any, redact: bool = True) -> str:
    """Return a short string preview of any value, safe to store in audit.

    - dicts / lists are JSON-ish (no crash on non-serialisable)
    - long strings are truncated to MAX_PREVIEW
    - PII is redacted by default
    """
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return f"<binary {len(value)}B>"
    if isinstance(value, (dict, list, tuple)):
        try:
            import json
            text = json.dumps(value, default=str)
        except Exception:
            text = repr(value)
    else:
        text = str(value)

    # Strip NUL bytes - Postgres JSONB rejects them in text
    _NUL = chr(0)
    if _NUL in text:
        text = text.replace(_NUL, "\\x00")
    # Truncate BEFORE redacting so redact regexes never see huge input
    # (prevents catastrophic backtracking DoS on pathological inputs)
    if len(text) > MAX_PREVIEW:
        text = text[: MAX_PREVIEW - 3] + "..."
    if redact:
        text = _redact(text)
    return text


@dataclass
class AuditEvent:
    """One row of the audit trail. Immutable once emitted."""

    agent_id: str
    event_type: str
    source: str = "sdk"
    key: Optional[str] = None
    value_preview: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    outcome: str = "success"
    error_message: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    prev_hash: Optional[str] = None
    # Default None so write_event() can assign the timestamp INSIDE the
    # per-agent write lock; that keeps the chain order strictly monotonic
    # under concurrent writes. Callers that want a deterministic timestamp
    # (tests, back-fill) can pass one explicitly.
    timestamp: Optional[float] = None

    def validate(self) -> None:
        """Raise ValueError if the event is malformed."""
        if not self.agent_id:
            raise ValueError("agent_id is required")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(
                f"event_type {self.event_type!r} is not in EVENT_TYPES. "
                f"Add it to audit_v2/models.py EVENT_TYPES first."
            )
        if self.source not in SOURCES:
            raise ValueError(f"source {self.source!r} is not in SOURCES")
        if self.outcome not in OUTCOMES:
            raise ValueError(f"outcome {self.outcome!r} is not in OUTCOMES")
        if self.cost_usd < 0:
            raise ValueError("cost_usd cannot be negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready dict. Strips None values to keep rows tight."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, [], {}, "")}

    def storage_key(self, tenant_id: str) -> str:
        """Canonical key used inside the `nodes` table.

        Format:
          auditv2:<tenant_prefix>:<agent_id>:<timestamp_us>:<event_type>

        tenant_prefix is the first 8 chars of tenant_id - enough to make
        keys per-tenant-visually-distinct while keeping them short.
        """
        ts_us = int(self.timestamp * 1_000_000)
        tp = (tenant_id or "")[:8]
        return f"auditv2:{tp}:{self.agent_id}:{ts_us}:{self.event_type}"
