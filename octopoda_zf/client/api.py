"""Cloud client: thin, fail-soft wrapper over the existing Octopoda /v1 API.

Endpoints used (all pre-existing, unchanged):
- POST /v1/agents/{agent_id}/remember     body {"key":..., "value":{...}}
- GET  /v1/agents/{agent_id}/similar?q=&limit=   -> {"items":[...]}

Design principles:
- **Fail-soft**: a network error or non-2xx NEVER raises into the user's agent.
  Recall returns [] (agent proceeds with no memory); write is queued/dropped
  with a logged warning. The user's LLM call must always complete.
- **Budgeted**: every request carries a timeout (PERFORMANCE_BUDGET hot-path
  recall hard cap = 300ms).
- **Transport seam**: `Transport` protocol lets tests inject a mock with zero
  network. Production default is a stdlib urllib transport (no extra deps).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("octopoda.client")


@dataclass
class Response:
    status_code: int
    body: Any  # parsed JSON, or None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@runtime_checkable
class Transport(Protocol):
    """Anything that can perform an HTTP request and return a Response."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> Response:
        ...


@dataclass
class MemoryHit:
    """One result from a similarity search."""

    key: str
    value: str
    score: float
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> MemoryHit:
        """Tolerant parse of a /similar item. The runtime's shape may vary, so
        we look for the value under several likely keys."""
        value = ""
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        if isinstance(data, dict):
            value = (
                data.get("value")
                or data.get("content")
                or data.get("text")
                or ""
            )
            if isinstance(value, dict):
                # nested {"value": "..."} convention
                value = value.get("value") or json.dumps(value)
        score = (
            item.get("score")
            or item.get("similarity")
            or item.get("distance_score")
            or 0.0
        )
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        return cls(
            key=str(item.get("key") or item.get("name") or ""),
            value=str(value),
            score=score,
            raw=item,
        )


class UrllibTransport:
    """Stdlib-only HTTP transport (no requests/httpx dependency).

    Note: opens a fresh connection per call (no pooling). Fine for correctness;
    a pooled transport is a perf optimization tracked for later. The Transport
    seam makes swapping trivial.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> Response:
        if params:
            from urllib.parse import urlencode

            url = f"{url}?{urlencode(params)}"
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else None
                return Response(status_code=resp.status, body=parsed)
        except urllib.error.HTTPError as e:
            body = None
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                pass
            return Response(status_code=e.code, body=body)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # network failure — surfaced as a sentinel status so the client
            # can fail-soft without the caller distinguishing causes.
            logger.warning("transport error for %s %s: %s", method, url, e)
            return Response(status_code=0, body=None)


class MockTransport:
    """Test double. Returns scripted responses + records calls."""

    def __init__(self, responses: dict[str, Response] | None = None) -> None:
        # key: f"{METHOD} {path-substring}" -> Response
        self._responses = responses or {}
        self.calls: list[dict[str, Any]] = []
        self.default = Response(status_code=200, body={})

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> Response:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json_body": json_body,
                "timeout": timeout,
            }
        )
        for needle, resp in self._responses.items():
            m, _, path = needle.partition(" ")
            if m == method and path in url:
                return resp
        return self.default


class CloudClient:
    """Fail-soft client for the existing Octopoda cloud API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.octopodas.com",
        transport: Transport | None = None,
        recall_timeout: float | None = None,  # None -> OCTOPODA_RECALL_TIMEOUT env, else 3.0s
        write_timeout: float | None = None,   # None -> OCTOPODA_WRITE_TIMEOUT env, else 5.0s
    ) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._transport = transport or UrllibTransport()
        if recall_timeout is None:
            # 3.3.1: the old 0.3s default was an in-process budget that timed out
            # ~100% of real WAN recalls (live /similar is 0.4-1.3s + RTT). Recall
            # stays fail-soft on timeout; the budget is now WAN-realistic.
            recall_timeout = float(os.environ.get("OCTOPODA_RECALL_TIMEOUT", "3.0"))
        if write_timeout is None:
            # 3.3.2: the old 2.0s default fired false "remember failed" client logs
            # under server load even though the write LANDS server-side (the sync
            # /remember response just lagged). Writes are fail-soft regardless.
            write_timeout = float(os.environ.get("OCTOPODA_WRITE_TIMEOUT", "5.0"))
        self._recall_timeout = recall_timeout
        self._write_timeout = write_timeout
        # 3.3.4: writes stay fail-soft but now make a few BOUNDED retries on a
        # rate-limit / transient-overload response (429/503) before giving up,
        # so a memory isn't silently dropped during a brief throttle (e.g. when
        # concurrent agents contend for the shared embedding key). Bounded so a
        # background flush — and the at-exit drain — can't stall for long.
        # Recall is deliberately NOT retried (it's the agent's hot path).
        self._write_retries = int(os.environ.get("OCTOPODA_WRITE_RETRIES", "2"))
        self._write_retry_backoff = float(os.environ.get("OCTOPODA_WRITE_RETRY_BACKOFF", "0.5"))
        self._write_retry_cap = float(os.environ.get("OCTOPODA_WRITE_RETRY_CAP", "2.0"))
        self._sleep = time.sleep  # seam for tests

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def recall_similar(
        self, agent_id: str, query: str, limit: int = 5
    ) -> list[MemoryHit]:
        """Semantic search. Fail-soft: returns [] on any error."""
        if not query.strip():
            return []
        url = f"{self._base}/v1/agents/{agent_id}/similar"
        try:
            resp = self._transport.request(
                "GET",
                url,
                headers=self._headers,
                params={"q": query, "limit": limit},
                timeout=self._recall_timeout,
            )
            if not resp.ok or not isinstance(resp.body, dict):
                # 404 = agent has no memories yet (cold start, before its first
                # write) — normal for a new agent's opening turns, not a warning.
                if resp.status_code not in (0, 200, 404):
                    logger.warning("recall_similar non-ok status %s", resp.status_code)
                return []
            items = resp.body.get("items") or resp.body.get("results") or []
            if not isinstance(items, list):
                return []
            return [MemoryHit.from_item(it) for it in items if isinstance(it, dict)]
        except Exception as e:  # defense-in-depth: recall must NEVER break the agent
            logger.warning("recall_similar failed (returning no memories): %s", e)
            return []

    def remember(self, agent_id: str, key: str, value: dict[str, Any]) -> bool:
        """Write a memory. Fail-soft: returns False on any error (never raises).

        Retries a bounded number of times on a 429 (rate limited) or 503
        (transient overload) so a memory isn't silently dropped during a brief
        throttle — e.g. when concurrent agents contend for the shared embedding
        key. Honors a `retry_after_seconds` hint from the body when present
        (capped). All other failures (other 4xx/5xx, network) fail-soft at once."""
        url = f"{self._base}/v1/agents/{agent_id}/remember"
        attempts = max(1, self._write_retries + 1)
        for attempt in range(attempts):
            try:
                resp = self._transport.request(
                    "POST",
                    url,
                    headers=self._headers,
                    json_body={"key": key, "value": value},
                    timeout=self._write_timeout,
                )
            except Exception as e:  # defense-in-depth: a write must never raise into capture
                logger.warning("remember raised for %s/%s (dropped): %s", agent_id, key, e)
                return False
            if resp.ok:
                return True
            # Retry ONLY transient throttling, and only while attempts remain.
            if resp.status_code in (429, 503) and attempt < attempts - 1:
                wait = self._write_retry_backoff * (2 ** attempt)
                if isinstance(resp.body, dict):
                    hint = resp.body.get("retry_after_seconds")
                    if isinstance(hint, (int, float)) and hint > 0:
                        wait = float(hint)
                wait = min(wait, self._write_retry_cap)
                logger.warning(
                    "remember %s/%s throttled (status=%s); retry %d/%d in %.2fs",
                    agent_id, key, resp.status_code, attempt + 1, attempts - 1, wait,
                )
                self._sleep(wait)
                continue
            logger.warning("remember failed for %s/%s status=%s", agent_id, key, resp.status_code)
            return False
        return False

    def forget(self, agent_id: str, key: str) -> bool:
        """Delete a memory by key (used for supersession - a changed fact
        replaces the stale one). Fail-soft: returns False on error, never raises.

        Uses the existing DELETE /v1/agents/{id}/memory/{key} endpoint."""
        if not key:
            return False
        url = f"{self._base}/v1/agents/{agent_id}/memory/{key}"
        try:
            resp = self._transport.request(
                "DELETE", url, headers=self._headers, timeout=self._write_timeout,
            )
        except Exception as e:  # defense-in-depth: supersession delete never raises
            logger.warning("forget raised for %s/%s (skipped): %s", agent_id, key, e)
            return False
        if not resp.ok:
            logger.warning("forget failed for %s/%s status=%s", agent_id, key, resp.status_code)
            return False
        return True
