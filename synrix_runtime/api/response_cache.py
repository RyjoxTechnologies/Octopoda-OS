"""Per-tenant in-memory TTL cache for hot endpoint responses.

A compact cache that sits in front of endpoint handlers. Only used for
endpoints where staleness of a few seconds is fine - overview panels,
cost rollups, brain status - not for anything the caller relies on
being strictly fresh (memory reads, audit lookups).

Public API:
    cached_call(cache_key, ttl_seconds, fn, *args, **kwargs)
        Return fn(*args, **kwargs) result, served from cache if the
        entry is younger than ttl_seconds. Result is serialisable.

    invalidate(prefix)
        Drop every entry whose key starts with `prefix`. Use when a
        write-path wants to force a refresh on next read.

    stats()
        Quick observability: hit/miss counts, entries, oldest entry.

Design choices:
    - Pure in-memory dict keyed by (cache_key). Per-process, not shared
      across uvicorn workers. That is intentional: Redis adds operational
      cost and we don't need cross-worker coherence for 30-second staleness.
    - Single RLock around the map. 30s TTL means very low hit frequency
      on the lock; no contention observed under 100 concurrent users.
    - Values are deep-copied on way out so callers can mutate without
      poisoning cache.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable, Dict, Tuple

_cache: Dict[str, Tuple[float, Any]] = {}  # key -> (expires_at, value)
_lock = threading.RLock()
_hits = 0
_misses = 0


def cached_call(key: str, ttl: float, fn: Callable, *args, **kwargs) -> Any:
    """Return cached value if fresh, else compute + store."""
    global _hits, _misses
    now = time.time()
    with _lock:
        entry = _cache.get(key)
        if entry and entry[0] > now:
            _hits += 1
            return copy.deepcopy(entry[1])
    # Compute outside the lock to avoid blocking concurrent reads
    value = fn(*args, **kwargs)
    with _lock:
        _cache[key] = (now + ttl, copy.deepcopy(value))
        _misses += 1
    return value


def invalidate(prefix: str) -> int:
    """Drop keys starting with prefix. Returns number removed."""
    removed = 0
    with _lock:
        for k in list(_cache.keys()):
            if k.startswith(prefix):
                del _cache[k]
                removed += 1
    return removed


def stats() -> Dict[str, Any]:
    with _lock:
        entries = len(_cache)
        oldest = None
        now = time.time()
        if _cache:
            soonest_expire = min(v[0] for v in _cache.values())
            oldest = now - soonest_expire  # negative if all still fresh
    return {
        "entries": entries,
        "hits": _hits,
        "misses": _misses,
        "hit_rate": (_hits / (_hits + _misses)) if (_hits + _misses) else 0,
        "seconds_until_oldest_expires": oldest,
    }


def clear_all() -> int:
    """Test helper - nuke every entry."""
    with _lock:
        n = len(_cache)
        _cache.clear()
    return n
