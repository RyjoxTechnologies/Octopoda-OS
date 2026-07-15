"""
octopoda_zf — zero-friction auto-instrumentation for Octopoda.

Powers the two-line integration: `import octopoda; octopoda.init(api_key=...)`
detects the framework in use (LangChain, CrewAI, AutoGen, OpenAI Agents,
Anthropic, MCP), captures what matters from each turn, and injects relevant
recall into future calls — with no change to your agent's logic.

Public entry points:
    octopoda.init()           # detect frameworks + activate auto-instrument
    octopoda.uninstall()      # revert all patches, stop the worker
    octopoda_zf.scope(name)   # context manager to set agent_id for a block
"""

from __future__ import annotations

from .audit import AuditChain, AuditEntry
from .guard import LoopGuard, LoopGuardConfig
from .init import InitResult, audit_chain, init, procedural, uninstall
from .procedural_memory import ProceduralMemory, Procedure
from .scope import current_scope, derive_agent_id, scope

__version__ = "0.0.1-dev"

__all__ = [
    "init",
    "uninstall",
    "scope",
    "current_scope",
    "derive_agent_id",
    "InitResult",
    "LoopGuard",
    "LoopGuardConfig",
    "AuditChain",
    "AuditEntry",
    "procedural",
    "ProceduralMemory",
    "Procedure",
    "audit_chain",
]
