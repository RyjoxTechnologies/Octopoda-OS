"""Extraction pipeline — turns raw transcripts into durable, deduped facts.

Public surface:
    extract(transcript, llm, embedder=None, config=None) -> ExtractionResult

Building blocks (exposed for testing + reuse):
    Fact, FactType
    sanitize
    filter_facts, passes, FilterConfig
    decide, dedupe_within_batch, merge_facts
    LLMClient, MockLLMClient, safe_parse_facts
    Embedder, LexicalEmbedder, CachedEmbedder
"""

from __future__ import annotations

from .deduper import (
    DEFAULT_BATCH_THRESHOLD,
    DEFAULT_WRITE_THRESHOLD,
    DedupDecision,
    decide,
    dedupe_within_batch,
    merge_facts,
)
from .edu import extract_edus
from .embeddings import CachedEmbedder, Embedder, LexicalEmbedder
from .extractor import (
    ExtractionConfig,
    ExtractionResult,
    extract,
)
from .importance import FilterConfig, FilterResult, filter_facts, passes
from .llm import LLMClient, MockLLMClient, OpenAIExtractorClient, safe_parse_facts
from .sanitizer import SanitizeResult, sanitize
from .supersede import detect_superseded_keys
from .types import Fact, FactType

__all__ = [
    "Fact",
    "FactType",
    "sanitize",
    "SanitizeResult",
    "detect_superseded_keys",
    "filter_facts",
    "passes",
    "FilterConfig",
    "FilterResult",
    "decide",
    "dedupe_within_batch",
    "merge_facts",
    "DedupDecision",
    "DEFAULT_WRITE_THRESHOLD",
    "DEFAULT_BATCH_THRESHOLD",
    "LLMClient",
    "MockLLMClient",
    "OpenAIExtractorClient",
    "safe_parse_facts",
    "Embedder",
    "LexicalEmbedder",
    "CachedEmbedder",
    "extract",
    "ExtractionConfig",
    "ExtractionResult",
    "extract_edus",
]
