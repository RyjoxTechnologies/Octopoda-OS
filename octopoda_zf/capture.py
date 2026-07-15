"""Capture pipeline: turn intercepted LLM turns into written memories.

The hook hands us (messages, response) after each LLM call. We must:
  1. NOT block the user's call -> processing happens off the hot path.
  2. Batch turns per agent (RFC: extract every ~5 turns, not every turn) to
     control extraction cost.
  3. Run the extraction pipeline, dedup against existing memories, and write via
     the cloud client.

Design:
- `process_and_write(...)` is the pure core: transcript -> facts -> dedup ->
  write. Fully testable with mock llm + mock client.
- `CaptureWorker` buffers turns per agent and flushes on a turn threshold.
  In `synchronous=True` mode it processes inline (deterministic, for tests);
  in threaded mode a background worker drains a queue (production, non-blocking).
"""

from __future__ import annotations

import hashlib
import logging
import queue
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .client.api import CloudClient, MemoryHit
from .extraction import (
    Embedder,
    ExtractionConfig,
    Fact,
    FactType,
    LexicalEmbedder,
    LLMClient,
    decide,
    extract,
    extract_edus,
    sanitize,
)

logger = logging.getLogger("octopoda.capture")


# ---------------------------------------------------------------------------
# Response text extraction (framework-specific shapes -> plain text)
# ---------------------------------------------------------------------------

def openai_response_to_text(response: Any) -> str:
    """Extract assistant text from an OpenAI ChatCompletion response."""
    try:
        choice = response.choices[0]
        content = getattr(choice.message, "content", None)
        return content or ""
    except Exception:
        # dict-shaped or unexpected — best effort
        try:
            return response["choices"][0]["message"]["content"] or ""
        except Exception:
            return ""


def anthropic_response_to_text(response: Any) -> str:
    """Extract assistant text from an Anthropic Messages response.

    Anthropic responses have `.content` = list of blocks; text blocks have
    `.type == 'text'` and `.text`."""
    try:
        blocks = response.content
        parts = []
        for b in blocks:
            if getattr(b, "type", None) == "text":
                parts.append(getattr(b, "text", "") or "")
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", "") or "")
        return " ".join(p for p in parts if p)
    except Exception:
        return ""


def transcript_from_turn(messages: list[dict], response_text: str) -> str:
    """Render one (messages, response) turn into transcript text for extraction.

    We include the latest user message + the assistant response. Earlier history
    is already captured by prior turns, so we avoid re-sending the whole context
    every time (cost control)."""
    lines: list[str] = []
    # last user message
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                lines.append(f"User: {content.strip()}")
            break
    if response_text.strip():
        lines.append(f"Assistant: {response_text.strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dual storage (memory-quality lever): alongside distilled facts, store the raw
# conversational turns VERBATIM as retrievable chunks. Measured on the stratified
# LongMemEval ablation (docs/MEMORY_QUALITY_PLAN.md §0.5): facts-only 44% ->
# facts+chunks ~55% (+11pp), beating Mem0 (49%). The win is the raw-turn
# REPRESENTATION: ≤8-fact distillation throws away specifics single-session
# questions ask for ("17 skeins of worsted yarn"), but the verbatim turn keeps
# them. Facts stay (current-state / dashboard / dedup); chunks add recall detail.
# ---------------------------------------------------------------------------

_TURN_RE = re.compile(r"^\s*(user|assistant|system)\s*:\s?", re.IGNORECASE)


def transcript_to_chunks(
    transcript: str, *, max_chars: int = 400, min_chars: int = 15
) -> list[str]:
    """Split a transcript into one verbatim chunk per turn.

    Groups each `Role:`-prefixed line with its continuation lines, drops
    trivially-short turns ("ok", "thanks"), and truncates each so a single long
    turn can't blow the injection budget. Mirrors the benchmark's chunker."""
    chunks: list[str] = []
    cur: list[str] = []

    def _flush() -> None:
        if not cur:
            return
        text = " ".join(part.strip() for part in cur).strip()
        if len(text) >= min_chars:
            chunks.append(text[:max_chars])

    for line in transcript.splitlines():
        if _TURN_RE.match(line):
            _flush()
            cur = [line]
        elif cur:
            cur.append(line)
    _flush()
    return chunks


def _chunk_payload(text: str) -> tuple[str, dict]:
    """A chunk memory, shaped like a fact so the dashboard + /similar treat it
    uniformly. Key = content hash -> identical turns dedup by upsert (idempotent,
    no extra LLM dedup needed)."""
    key = "chunk:" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    value = {
        "value": text,
        "fact_type": "chunk",
        "source": "auto-instrument-chunk",
        "tags": ["raw_turn"],
    }
    return key, value


def _edu_payload(text: str) -> tuple[str, dict]:
    """An EMem EDU memory (event-centric, advanced tier). Shaped like a fact;
    content-hash keyed so identical EDUs dedup by upsert."""
    key = "edu:" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    value = {
        "value": text,
        "fact_type": "edu",
        "source": "auto-instrument-edu",
        "tags": ["edu", "event"],
    }
    return key, value


# ---------------------------------------------------------------------------
# Pure core: transcript -> facts -> dedup -> write
# ---------------------------------------------------------------------------

def _hit_to_fact(hit: MemoryHit) -> Fact:
    """Adapt an existing memory hit into a Fact for dedup comparison."""
    return Fact(
        type=FactType.MEMORY,
        subject="",
        predicate="",
        value=hit.value,
        confidence=1.0,
    )


@dataclass
class WriteSummary:
    extracted: int = 0
    written: int = 0
    merged_skipped: int = 0
    superseded: int = 0
    chunks_written: int = 0
    edus_written: int = 0
    redactions: dict[str, int] = field(default_factory=dict)


def process_and_write(
    agent_id: str,
    transcript: str,
    *,
    llm: LLMClient,
    client: CloudClient,
    embedder: Embedder | None = None,
    config: ExtractionConfig | None = None,
    recall_existing: bool = True,
    write_dedup_threshold: float = 0.92,
    supersede: bool = True,
    write_chunks: bool = False,
    write_edus: bool = False,
    audit: Any | None = None,
) -> WriteSummary:
    """Extract facts from a transcript and write the new ones to the cloud.

    Three-way write-time decision per fact:
    - **supersede** (ADR-016+): a new fact that REPLACES an existing memory
      (location/status/value changed) deletes the stale one, so recall returns
      the current fact. Closes the staleness gap.
    - **merge** (ADR-005): a near-duplicate of an existing memory is skipped.
    - **insert**: genuinely new fact is written.

    `write_chunks` (dual storage): also store the raw turns VERBATIM as chunk
    memories (sanitized first — chunks must not bypass secret/PII redaction).
    Measured +11pp vs facts-only (docs/MEMORY_QUALITY_PLAN.md §0.5). Chunks are
    written independently of facts (raw turns are useful even when extraction
    finds no durable fact)."""
    emb = embedder or LexicalEmbedder()
    result = extract(transcript, llm, emb, config)
    summary = WriteSummary(extracted=len(result.facts), redactions=result.redactions)

    # Dual storage (chunks) + EMem (EDUs): both derived from the SANITIZED transcript
    # (so they can never leak a secret/PII the fact path would scrub), and both
    # independent of facts (they run even on a no-fact turn). Sanitize once.
    if write_chunks or write_edus:
        clean = sanitize(transcript).text
        if write_chunks:
            seen_keys: set[str] = set()
            for chunk in transcript_to_chunks(clean):
                key, value = _chunk_payload(chunk)
                if key in seen_keys:  # identical turn twice in one batch
                    continue
                seen_keys.add(key)
                if client.remember(agent_id, key, value):
                    summary.chunks_written += 1
        if write_edus:  # EMem: event-centric discourse units (advanced tier)
            edu_keys: set[str] = set()
            for edu in extract_edus(clean, llm):
                key, value = _edu_payload(edu)
                if key in edu_keys:
                    continue
                edu_keys.add(key)
                if client.remember(agent_id, key, value):
                    summary.edus_written += 1

    if not result.facts:
        return summary

    hits = []
    if recall_existing:
        pool_query = " ".join(f.to_text() for f in result.facts)[:500]
        try:
            hits = client.recall_similar(agent_id, pool_query, limit=20)
        except Exception as e:  # fail-soft: dedup/supersession are best-effort
            logger.debug("write-time recall failed, writing without: %s", e)

    # --- supersession: delete stale memories the new facts replace ---
    if supersede and hits:
        from .extraction.supersede import detect_superseded_keys

        existing_pairs = [(h.key, h.value) for h in hits if h.key]
        try:
            superseded_keys = detect_superseded_keys(llm, result.facts, existing_pairs)
        except Exception as e:
            logger.debug("supersession detection failed (skipping): %s", e)
            superseded_keys = set()
        for key in superseded_keys:
            if client.forget(agent_id, key):
                summary.superseded += 1
        # don't dedup new facts against memories we just superseded
        hits = [h for h in hits if h.key not in superseded_keys]

    existing: list[Fact] = [_hit_to_fact(h) for h in hits]

    for fact in result.facts:
        decision = decide(fact, existing, emb, write_dedup_threshold)
        if decision.action == "merge":
            summary.merged_skipped += 1
            continue
        payload = fact.to_remember_payload()
        if client.remember(agent_id, payload["key"], payload["value"]):
            summary.written += 1
            existing.append(fact)  # dedup later facts in THIS batch against it too
            if audit is not None:  # tamper-evident log of the write (best-effort)
                try:
                    audit.record(agent_id, "write", payload["key"], fact.to_text())
                except Exception:
                    pass
    return summary


# ---------------------------------------------------------------------------
# Async worker
# ---------------------------------------------------------------------------

@dataclass
class CaptureConfig:
    flush_every_turns: int = 5
    extraction: ExtractionConfig | None = None
    recall_existing: bool = True
    write_chunks: bool = False  # dual storage (memory-quality lever)
    write_edus: bool = False    # EMem event-centric units (advanced tier)
    audit: Any | None = None    # tamper-evident audit chain (value-add #2)


class CaptureWorker:
    """Buffers turns per agent and flushes them through the extraction pipeline.

    synchronous=True  -> processing happens inline on submit() (tests).
    synchronous=False -> a daemon thread drains a queue (production, non-blocking).
    """

    def __init__(
        self,
        llm: LLMClient | None,
        client: CloudClient,
        embedder: Embedder | None = None,
        config: CaptureConfig | None = None,
        synchronous: bool = False,
    ) -> None:
        self._llm = llm
        self._client = client
        self._embedder = embedder or LexicalEmbedder()
        self._cfg = config or CaptureConfig()
        self._synchronous = synchronous

        self._buffers: dict[str, list[str]] = {}
        self._lock = threading.Lock()
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        # telemetry counters
        self.submitted = 0
        self.flushes = 0

    def start(self) -> None:
        if self._synchronous or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="octopoda-capture", daemon=False)
        self._thread.start()

    def submit(self, agent_id: str, messages: list[dict], response_text: str) -> None:
        """Non-blocking: enqueue a (messages, response) turn. Builds the
        transcript then delegates to submit_transcript."""
        self.submit_transcript(agent_id, transcript_from_turn(messages, response_text))

    def submit_transcript(self, agent_id: str, text: str) -> None:
        """Non-blocking: enqueue a pre-built transcript turn for processing.

        Used directly by capture-only frameworks (CrewAI, AutoGen, OpenAI Agents)
        that produce a transcript natively rather than a (messages, response)
        request/response pair."""
        if not text or not text.strip():
            return
        self.submitted += 1
        if self._synchronous:
            self._ingest(agent_id, text)
        else:
            self._q.put((agent_id, text))

    def _run(self) -> None:
        while self._running and threading.main_thread().is_alive():
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:  # shutdown sentinel
                break
            agent_id, turn = item
            try:
                self._ingest(agent_id, turn)
            except Exception as e:  # never let the worker thread die
                logger.warning("capture worker error: %s", e)
            finally:
                self._q.task_done()
        try:
            while True:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    self._q.task_done(); continue
                agent_id, turn = item
                try:
                    with self._lock:
                        self._buffers.setdefault(agent_id, []).append(turn)
                finally:
                    self._q.task_done()
            self.flush_all()
        except Exception as e:
            logger.warning('capture worker exit-flush error: %s', e)

    def _ingest(self, agent_id: str, turn: str) -> None:
        with self._lock:
            buf = self._buffers.setdefault(agent_id, [])
            buf.append(turn)
            ready = len(buf) >= self._cfg.flush_every_turns
        if ready:
            self.flush(agent_id)

    def flush(self, agent_id: str) -> WriteSummary | None:
        with self._lock:
            buf = self._buffers.get(agent_id)
            if not buf:
                return None
            transcript = "\n".join(buf)
            self._buffers[agent_id] = []
        self.flushes += 1
        if self._llm is None:
            # No local extractor LLM: hand the raw turns to the server, which
            # distills them via the platform key (free tier). One write per flush.
            import hashlib
            _ck = "conversation:" + hashlib.sha1(transcript.encode("utf-8")).hexdigest()[:12]
            try:
                self._client.remember(agent_id, _ck, {"value": transcript, "fact_type": "conversation"})
            except Exception as _e:
                logger.warning("server-extraction write failed for %s: %s", agent_id, _e)
            return None
        return process_and_write(
            agent_id,
            transcript,
            llm=self._llm,
            client=self._client,
            embedder=self._embedder,
            config=self._cfg.extraction,
            recall_existing=self._cfg.recall_existing,
            write_chunks=self._cfg.write_chunks,
            write_edus=self._cfg.write_edus,
            audit=self._cfg.audit,
        )

    def flush_all(self) -> None:
        for agent_id in list(self._buffers.keys()):
            self.flush(agent_id)

    def stop(self, timeout: float = 5.0) -> None:
        """Drain the queue, flush remaining buffers, stop the thread."""
        if not self._synchronous and self._running:
            self._q.join()  # wait for queued items to be processed
            self._running = False
            self._q.put(None)  # wake the thread to exit
            if self._thread:
                self._thread.join(timeout=timeout)
        self.flush_all()


def make_capture_fn(
    worker: CaptureWorker,
    agent_id_fn: Callable[[], str],
    response_to_text: Callable[[Any], str],
    messages_normalizer: Callable[[Any], list[dict]] | None = None,
    guard: Any | None = None,
) -> Callable[[Any, Any], None]:
    """Build the capture_fn a message-based hook calls. Resolves agent_id at call
    time so `scope()` is respected per call. Non-blocking: just enqueues.

    `messages_normalizer` (optional) converts a framework's native message input
    into the list[dict] {role, content} shape the transcript builder expects.
    OpenAI/Anthropic already pass dicts so they omit it; LangChain passes one.

    `guard` (optional LoopGuard): if its circuit breaker is open for this agent
    (runaway loop detected), capture is skipped — don't pollute memory with the
    flood. The user's LLM call is unaffected."""

    def capture_fn(messages: Any, response: Any) -> None:
        try:
            agent_id = agent_id_fn()
            if guard is not None and guard.is_open(agent_id):
                return  # circuit breaker open — skip capturing the loop
            text = response_to_text(response)
            msgs = messages_normalizer(messages) if messages_normalizer else (messages or [])
            worker.submit(agent_id, msgs, text)
        except Exception as e:  # never break the user's call
            logger.debug("capture_fn error (ignored): %s", e)

    return capture_fn
