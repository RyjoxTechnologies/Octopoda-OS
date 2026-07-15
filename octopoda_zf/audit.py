"""Tamper-evident audit chain (value-add #2).

Every memory WRITE and every RECALL is recorded as a hash-chained entry: each
entry's hash folds in the PREVIOUS entry's hash, so altering, reordering, or
deleting ANY entry breaks every subsequent hash. `verify()` walks the chain and
detects tampering. This is the differentiator for regulated / high-stakes agents:
"prove what the agent remembered and recalled, and that the log wasn't edited."

Privacy: we store only a HASH of the content, never the content itself — the audit
log is verifiable without holding the (possibly sensitive) memory text.

Honesty: this is tamper-EVIDENT, not tamper-PROOF. A party with full write access
could re-forge the entire chain from the tampered point onward. Production anchors
the head hash externally (sign / publish it) so even a full re-forge is detectable;
this module is the in-process primitive that the server anchors.

Thread-safe. Recording is best-effort and must NEVER raise into the user's path.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass

_GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    ts: float
    agent_id: str
    op: str           # "write" | "recall"
    detail: str       # key (write) or query (recall), truncated
    content_hash: str  # sha256 of the content (content itself is NOT stored)
    prev_hash: str
    entry_hash: str


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", "replace"))
        h.update(b"\x00")  # delimiter so fields can't be ambiguously concatenated
    return h.hexdigest()


def _entry_hash(seq: int, ts: float, agent_id: str, op: str, detail: str,
                content_hash: str, prev_hash: str) -> str:
    return _sha(str(seq), f"{ts:.6f}", agent_id, op, detail, content_hash, prev_hash)


class AuditChain:
    """An append-only, hash-chained log of memory operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[AuditEntry] = []

    def record(self, agent_id: str, op: str, detail: str, content: str = "") -> AuditEntry:
        """Append an entry. Best-effort: callers wrap in try/except so a logging
        failure never breaks the user's call."""
        with self._lock:
            seq = len(self._entries)
            prev = self._entries[-1].entry_hash if self._entries else _GENESIS
            ts = time.time()
            detail = (detail or "")[:200]
            content_hash = _sha(content or "")
            eh = _entry_hash(seq, ts, agent_id, op, detail, content_hash, prev)
            entry = AuditEntry(seq, ts, agent_id, op, detail, content_hash, prev, eh)
            self._entries.append(entry)
            return entry

    def verify(self) -> bool:
        """True if the chain is intact: sequential seqs, linked prev_hashes, and
        every entry_hash recomputes. Any edit/reorder/delete -> False."""
        with self._lock:
            prev = _GENESIS
            for i, e in enumerate(self._entries):
                if e.seq != i or e.prev_hash != prev:
                    return False
                if _entry_hash(e.seq, e.ts, e.agent_id, e.op, e.detail,
                               e.content_hash, e.prev_hash) != e.entry_hash:
                    return False
                prev = e.entry_hash
            return True

    @property
    def head(self) -> str:
        """The current head hash (what production would anchor externally)."""
        with self._lock:
            return self._entries[-1].entry_hash if self._entries else _GENESIS

    @property
    def entries(self) -> list[AuditEntry]:
        with self._lock:
            return list(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
