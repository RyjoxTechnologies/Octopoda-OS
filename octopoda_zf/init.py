"""octopoda.init() — the orchestrator.

Wires the whole auto-instrument loop together:

  user's LLM call
    -> [hook] -> recall_fn (cloud /similar) -> inject
    -> original call
    -> capture_fn -> CaptureWorker -> extraction -> remember (cloud)

Responsibilities:
- **Cloud-only gate (ADR-012):** if no API key, log + return inactive. Local
  mode is untouched; we patch nothing.
- Detect loaded frameworks and patch them.
- Install a late-import hook so frameworks imported AFTER init() are also patched.
- Print a clear startup banner so the user sees exactly what happened.
- `uninstall()` reverts every patch and stops the worker.

Public surface (re-exported from the package root):
    octopoda.init(...)  octopoda.uninstall()  octopoda.scope(...)
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditChain
from .capture import (
    CaptureConfig,
    CaptureWorker,
    anthropic_response_to_text,
    make_capture_fn,
    openai_response_to_text,
)
from .client.api import CloudClient
from .extraction import LexicalEmbedder, LLMClient, OpenAIExtractorClient
from .guard import LoopGuard
from .instrument import (
    anthropic_sdk,
    autogen_hook,
    crewai_hook,
    langchain,
    openai_agents,
    openai_sdk,
)
from .instrument.base import revert_all
from .instrument.langchain import langchain_input_to_dicts, langchain_response_to_text
from .recall import build_injection, generous_injection_config
from .scope import derive_agent_id

logger = logging.getLogger("octopoda")

DEFAULT_BASE_URL = "https://api.octopodas.com"
DASHBOARD_URL = "https://octopodas.com/dashboard"


# Message-based frameworks (recall-inject + capture). Registry value:
#   module name -> (hook module, response_to_text, messages_normalizer | None)
# The detection key is the top-level module that signals the framework is loaded.
_MESSAGE_REGISTRY: dict[str, tuple[Any, Callable[[Any], str], Any]] = {
    "openai": (openai_sdk, openai_response_to_text, None),
    "anthropic": (anthropic_sdk, anthropic_response_to_text, None),
    "langchain_core": (langchain, langchain_response_to_text, langchain_input_to_dicts),
}

# Capture-only frameworks (no recall injection; produce transcripts natively).
#   detection module name -> hook module (exposes install_capture)
_CAPTURE_ONLY_REGISTRY: dict[str, Any] = {
    "crewai": crewai_hook,
    "autogen_agentchat": autogen_hook,
    "agents": openai_agents,
}

# Friendly display names for the banner.
_DISPLAY_NAME = {
    "openai": "openai",
    "anthropic": "anthropic",
    "langchain_core": "langchain",
    "crewai": "crewai",
    "autogen_agentchat": "autogen",
    "agents": "openai-agents",
}


@dataclass
class InitResult:
    active: bool
    frameworks: list[str] = field(default_factory=list)
    agent_id: str = "auto"
    dashboard_url: str = DASHBOARD_URL
    extraction_enabled: bool = False
    server_extraction: bool = False
    reason: str = ""


# Module-global state for the current init (one process = one init).
_worker: CaptureWorker | None = None
_finder: _LateImportFinder | None = None
_guard: LoopGuard | None = None
_audit: AuditChain | None = None
_client: CloudClient | None = None  # active cloud client (for procedural() etc.)


def _make_recall_fn(
    client: CloudClient, *, dual_storage: bool = False, guard: LoopGuard | None = None,
    audit: AuditChain | None = None,
) -> Callable[[str], str | None]:
    """recall_fn(query) -> injection text or None. Resolves agent_id per call so
    scope() is respected. Fail-soft (client already returns [] on error).

    With `dual_storage`, recall pulls a larger candidate set (facts + chunks live
    in one index) and injects with the generous budget so verbatim chunks fit.
    Measured +11pp (docs/MEMORY_QUALITY_PLAN.md §0.5). The wide budget is only
    applied here because chunks are in play — on facts alone it was a dead end."""
    cfg = generous_injection_config() if dual_storage else None
    limit = 12 if dual_storage else 5

    def recall_fn(query: str) -> str | None:
        agent_id = derive_agent_id()
        # Loop detection / circuit breaker: this is the ONE call per turn that
        # records the rate. If the breaker is open (runaway agent), skip recall.
        if guard is not None and not guard.allow(agent_id, query):
            return None
        hits = client.recall_similar(agent_id, query, limit=limit)
        injection = build_injection(hits, cfg)
        if audit is not None:  # tamper-evident log of the recall (best-effort)
            try:
                audit.record(agent_id, "recall", query, injection or "")
            except Exception:  # never break the user's call over audit logging
                pass
        return injection

    return recall_fn


def _all_detection_keys() -> list[str]:
    return list(_MESSAGE_REGISTRY) + list(_CAPTURE_ONLY_REGISTRY)


def _patch_message_framework(
    name: str, recall_fn: Callable, worker: CaptureWorker | None,
    guard: LoopGuard | None = None,
) -> list:
    hook_module, response_to_text, normalizer = _MESSAGE_REGISTRY[name]
    capture_fn = (
        make_capture_fn(worker, derive_agent_id, response_to_text, normalizer, guard=guard)
        if worker
        else None
    )
    return hook_module.resolve_and_patch(recall_fn, capture_fn)


def _guarded_submit(
    submit: Callable[[str, str], None], guard: LoopGuard | None,
) -> Callable[[str, str], None]:
    """Wrap submit_transcript so a runaway capture-only agent (CrewAI/AutoGen/
    Agents) trips the SAME circuit breaker the message frameworks use.

    Capture-only hooks have no recall path, so this submit is the one call per
    turn that records the rate (hence guard.allow(), not is_open()). Once the
    breaker trips — a high kickoff/run rate, or the identical transcript over and
    over — the write is skipped until cooldown. Fail-open + self-healing; the
    user's agent result already returned, so it is unaffected either way."""
    if guard is None:
        return submit

    def guarded(agent_id: str, text: str) -> None:
        if not guard.allow(agent_id, text):
            return  # breaker open — skip the write (don't pollute memory)
        submit(agent_id, text)

    return guarded


def _patch_capture_only_framework(
    name: str, worker: CaptureWorker | None, guard: LoopGuard | None = None,
) -> list:
    if worker is None:
        return []  # capture-only is pointless without extraction
    hook_module = _CAPTURE_ONLY_REGISTRY[name]
    submit = _guarded_submit(worker.submit_transcript, guard)
    return hook_module.install_capture(submit, derive_agent_id)


class _LateImportFinder(importlib.abc.MetaPathFinder):
    """Patches a target framework the moment it is imported (after init()).

    Standard meta-path pattern: when a target top-level module is imported, we
    find the real spec via the remaining finders, wrap its loader's exec_module
    so our patch callback runs right after the module finishes loading.
    """

    def __init__(self, callbacks: dict[str, Callable[[], None]]) -> None:
        self._callbacks = callbacks
        self._in_progress: set[str] = set()

    def find_spec(self, fullname: str, path: Any = None, target: Any = None):
        if fullname not in self._callbacks or fullname in self._in_progress:
            return None
        self._in_progress.add(fullname)
        try:
            idx = sys.meta_path.index(self)
            for finder in sys.meta_path[idx + 1 :]:
                spec = finder.find_spec(fullname, path, target)
                if spec is not None:
                    self._wrap_loader(spec, fullname)
                    return spec
            return None
        finally:
            self._in_progress.discard(fullname)

    def _wrap_loader(self, spec, fullname: str) -> None:
        loader = spec.loader
        if loader is None or not hasattr(loader, "exec_module"):
            return
        callback = self._callbacks[fullname]
        original_exec = loader.exec_module

        def exec_module(module):
            original_exec(module)
            try:
                callback()
            except Exception as e:  # never break the user's import
                logger.warning("late patch of %s failed: %s", fullname, e)

        loader.exec_module = exec_module  # type: ignore[method-assign]


def _print_banner(result: InitResult, recall_budget_tokens: int, flush_turns: int) -> None:
    fw = ", ".join(result.frameworks) if result.frameworks else "none yet"
    lines = [
        f"[octopoda] auto-detected: {fw}",
        f"[octopoda] agent_id: {result.agent_id}",
        f"[octopoda] dashboard: {result.dashboard_url}",
        f"[octopoda] recall budget: {recall_budget_tokens} tokens/call | "
        f"extraction: every {flush_turns} turns"
        + (" (server-side, free tier)" if result.server_extraction
           else "" if result.extraction_enabled else " (DISABLED: no extractor LLM key)"),
    ]
    for line in lines:
        print(line)


def init(
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    *,
    extractor_llm: LLMClient | None = None,
    transport: Any | None = None,
    synchronous: bool = False,
    banner: bool = True,
    flush_every_turns: int = 5,
    dual_storage: bool = False,
    emem: bool = False,
) -> InitResult:
    """Activate auto-instrumentation for this process.

    Cloud-only (ADR-012): requires an Octopoda API key (arg or OCTOPODA_API_KEY).
    Without one, returns an inactive result and patches nothing (local mode
    untouched).

    Extraction needs an LLM (gpt-4o-mini by default, via OPENAI_API_KEY). If
    neither `extractor_llm` nor OPENAI_API_KEY is available, recall still works
    but auto-extraction (writing new memories) is disabled with a clear notice.

    `dual_storage` (default off): also store raw conversational turns verbatim as
    retrievable chunks alongside distilled facts, and recall with the generous
    budget so chunks fit. Measured +11pp on the LongMemEval ablation, beating
    Mem0 (docs/MEMORY_QUALITY_PLAN.md). Requires the server `/similar` to index
    chunk memories (companion server-side change). Off by default so behavior is
    unchanged until the server side ships.

    `emem` (default off): EMem advanced tier — also write event-centric discourse
    units (EDUs) per turn (an extra extraction pass, async/off the hot path), which
    pushed recall toward Zep-level in the ablation. Like dual_storage it needs the
    server `/similar` to index `edu` memories. Use WITH dual_storage for the full
    facts+chunks+EDUs stack.
    """
    global _worker, _finder, _guard, _audit, _client

    api_key = api_key or os.environ.get("OCTOPODA_API_KEY")
    if not api_key:
        msg = (
            "[octopoda] OCTOPODA_API_KEY not set - auto-instrument skipped. "
            "Local mode is unaffected. Set the key to enable cloud memory."
        )
        if banner:
            print(msg)
        logger.info(msg)
        return InitResult(active=False, reason="no_api_key")

    # Build the extractor LLM. With a local key we distill client-side (best quality);
    # without one we fall back to SERVER-side extraction via the platform free tier,
    # so memory works with just the Octopoda key (no OpenAI key required).
    extraction_enabled = True
    server_extraction = False
    if extractor_llm is None:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            extractor_llm = OpenAIExtractorClient(api_key=openai_key)
        else:
            server_extraction = True

    client = CloudClient(api_key, base_url=base_url, transport=transport)
    _client = client        # exposed for procedural() (value-add #3)
    embedder = LexicalEmbedder()
    _guard = LoopGuard()    # loop detection / circuit breaker (value-add #5)
    _audit = AuditChain()   # tamper-evident audit chain (value-add #2)

    # Worker runs whenever we have an API key. With a local extractor it distills
    # client-side; with extractor_llm=None it sends raw turns for SERVER-side
    # extraction via the platform free tier (works with zero extra setup).
    _worker = CaptureWorker(
        extractor_llm,
        client,
        embedder=embedder,
        config=CaptureConfig(
            flush_every_turns=flush_every_turns, write_chunks=dual_storage,
            write_edus=emem, audit=_audit,
        ),
        synchronous=synchronous,
    )
    _worker.start()
    # flush buffered turns at interpreter exit so short sessions still persist.
    import atexit
    atexit.register(_worker.flush_all)

    recall_fn = _make_recall_fn(
        client, dual_storage=dual_storage or emem, guard=_guard, audit=_audit
    )

    # Patch already-loaded frameworks (both categories).
    patched: list[str] = []
    for name in _MESSAGE_REGISTRY:
        if name in sys.modules and _patch_message_framework(name, recall_fn, _worker, _guard):
            patched.append(name)
    for name in _CAPTURE_ONLY_REGISTRY:
        if name in sys.modules and _patch_capture_only_framework(name, _worker, _guard):
            patched.append(name)

    # Install late-import hook for frameworks imported after init().
    callbacks: dict[str, Callable[[], None]] = {}
    for name in _all_detection_keys():
        if name in patched:
            continue

        def _late(n=name):
            if n in _MESSAGE_REGISTRY:
                _patch_message_framework(n, recall_fn, _worker, _guard)
            else:
                _patch_capture_only_framework(n, _worker, _guard)

        callbacks[name] = _late

    if callbacks:
        _finder = _LateImportFinder(callbacks)
        sys.meta_path.insert(0, _finder)

    result = InitResult(
        active=True,
        frameworks=[_DISPLAY_NAME.get(n, n) for n in patched],
        agent_id=derive_agent_id(),
        extraction_enabled=extraction_enabled,
        server_extraction=server_extraction,
    )
    if banner:
        _print_banner(
            result,
            recall_budget_tokens=500 if (dual_storage or emem) else 200,
            flush_turns=flush_every_turns,
        )
    return result


def uninstall() -> None:
    """Revert all patches + stop the capture worker. Restores the process to a
    state as if octopoda.init() was never called."""
    global _worker, _finder, _guard, _audit, _client
    revert_all()
    if _finder is not None and _finder in sys.meta_path:
        sys.meta_path.remove(_finder)
    _finder = None
    _guard = None
    _audit = None
    _client = None
    if _worker is not None:
        _worker.stop()
        _worker = None


def procedural():
    """Return a ProceduralMemory (value-add #3) bound to the active cloud client,
    or None if init() hasn't run (cloud-only). Lets an agent record what WORKED:

        octopoda.procedural().record("deploy", "CI green then flip flag", success=True)
    """
    if _client is None:
        return None
    from .procedural_memory import ProceduralMemory

    return ProceduralMemory(_client)


def audit_chain() -> AuditChain | None:
    """Return the live tamper-evident audit chain (value-add #2), or None if init()
    hasn't run. Lets a user/auditor verify the integrity of the memory log:

        chain = octopoda.audit_chain()
        assert chain.verify()          # every write + recall, hash-linked, untampered
        print(chain.head)              # the head hash to anchor externally
    """
    return _audit
