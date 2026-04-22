"""
Octopoda Cloud API Server
========================
FastAPI-based REST API for external developers to interact with Octopoda.
Runs on port 8741 (separate from the Flask dashboard on 7842).

Auto-generated docs at /docs (Swagger UI).
"""

import json
import time
import os
import asyncio
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

# Thread pool for blocking runtime calls (embeddings, SQLite writes)
# 16 workers handles concurrent requests from many users without starving
_executor = ThreadPoolExecutor(max_workers=16)

from fastapi import FastAPI, Depends, HTTPException, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import Any, Optional, List, Dict, Tuple


# ---------------------------------------------------------------------------
# Lightweight in-process rate limiter (no external dependency)
# ---------------------------------------------------------------------------

# Per-plan rate limits (requests per minute)
_PLAN_RATE_LIMITS = {
    "free": 60,            # 1 req/sec
    "early_adopter": 300,  # 5 req/sec (grandfathered beta)
    "pro": 300,            # 5 req/sec
    "business": 1000,      # ~17 req/sec
    "scale": 5000,         # ~83 req/sec
    "enterprise": 10000,   # ~167 req/sec
}
_DEFAULT_RPM = int(os.environ.get("SYNRIX_RATE_LIMIT_RPM", "60"))


class _RateLimiter:
    """Token-bucket rate limiter keyed by tenant ID (not IP)."""

    def __init__(self):
        self._buckets: dict = {}  # tenant_id -> [tokens, last_refill, rpm]
        self._lock = threading.Lock()

    def _refill(self, bucket: list):
        now = time.monotonic()
        elapsed = now - bucket[1]
        rpm = bucket[2]
        bucket[0] = min(rpm, bucket[0] + elapsed * (rpm / 60.0))
        bucket[1] = now

    def allow(self, tenant_id: str, plan: str = "free", rpm_override: int = 0) -> bool:
        rpm = rpm_override if rpm_override > 0 else _PLAN_RATE_LIMITS.get(plan, _DEFAULT_RPM)
        with self._lock:
            if tenant_id not in self._buckets:
                self._buckets[tenant_id] = [rpm, time.monotonic(), rpm]
            bucket = self._buckets[tenant_id]
            bucket[2] = rpm  # update if plan changed
            self._refill(bucket)
            if bucket[0] >= 1.0:
                bucket[0] -= 1.0
                return True
            return False

    def get_remaining(self, tenant_id: str) -> int:
        with self._lock:
            if tenant_id not in self._buckets:
                return _DEFAULT_RPM
            bucket = self._buckets[tenant_id]
            self._refill(bucket)
            return int(bucket[0])


_rate_limiter = _RateLimiter()

# Separate stricter rate limiter for auth endpoints (prevent brute-force)
_AUTH_RPM = 5  # 5 attempts per minute per IP (prevents mass account creation)
_auth_rate_limiter = _RateLimiter()

from synrix_runtime.api.cloud_models import (
    RegisterAgentRequest, RememberRequest, BatchRememberRequest,
    SnapshotRequest, RestoreRequest,
    SharedWriteRequest, TaskCreateRequest, TaskActionRequest, DecisionLogRequest,
    RawWriteRequest, HealthResponse, MemoryResponse, RecallResponse, SearchResponse,
    SnapshotResponse, RestoreResponse, AgentResponse, BatchMemoryResponse, ErrorResponse,
    ProcessConversationRequest, GetContextRequest,
)
from synrix_runtime.api.auth import APIKeyManager
from synrix_runtime.log import get_logger

logger = get_logger("api")

# ---------------------------------------------------------------------------
# Sentry — error + performance monitoring. Gated on SENTRY_DSN env var.
# ---------------------------------------------------------------------------
# No-op unless SENTRY_DSN is set; safe for local dev, CI, and pip install users
# who don't install the [monitoring] extra.
_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_dsn,
            # FastApiIntegration attaches automatically when `fastapi` is importable.
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            profiles_sample_rate=0.0,
            send_default_pii=False,  # do not leak request headers / IPs
            release=os.environ.get("OCTOPODA_VERSION", "3.1.0"),
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        )
        logger.info("Sentry initialized (release=%s, env=%s)",
                    os.environ.get("OCTOPODA_VERSION", "3.1.0"),
                    os.environ.get("SENTRY_ENVIRONMENT", "production"))
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed — run: pip install 'octopoda[monitoring]'")
    except Exception as e:
        logger.error("Sentry init failed: %s", e)


def _capture_silent(exc: Exception, op: str = "", **context):
    """Forward a caught-and-swallowed exception to Sentry with tenant/agent context.

    Many paths in this server deliberately catch + swallow exceptions to avoid
    blocking the user's request (auto-checkpoint, brain monitoring, licensing
    tracking, etc.). Before this helper, those failures were invisible once
    the logger.warning line scrolled off journalctl. Now they surface in
    Sentry with the same tags Sentry middleware uses for regular errors.

    No-op if sentry-sdk isn't initialized. Never raises — otherwise we'd
    be introducing a new silent failure to report the old one.
    """
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("silent_op", op or "unknown")
            for k, v in context.items():
                if v is not None:
                    scope.set_extra(k, v)
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Octopoda Agent Memory API",
    version="3.1.1",
    description="Persistent Memory Kernel for AI Agents. Sub-millisecond crash recovery, shared memory bus, full audit trail.",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS: restrict to localhost by default; set SYNRIX_CORS_ORIGINS to override
_cors_origins = os.environ.get("SYNRIX_CORS_ORIGINS", "").strip()
if _cors_origins:
    _allowed_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
    _origin_regex = None
else:
    _allowed_origins = [
        "http://localhost:7842", "http://127.0.0.1:7842",
        "http://localhost:8741", "http://127.0.0.1:8741",
        "http://localhost:3000", "http://localhost:5173",
        "https://octopodas.com", "https://www.octopodas.com",
    ]
    # Allow Lovable preview domains (id-prefixed subdomains only) and octopodas.com subdomains
    _origin_regex = r"https://[a-z0-9-]+\.(lovable\.app|lovableproject\.com|octopodas\.com)"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_origin_regex,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)


@app.on_event("startup")
async def _prewarm_models():
    """Pre-load embedding model so first request isn't slow (~11s cold start)."""
    def _load():
        try:
            from synrix.embeddings import EmbeddingModel
            model = EmbeddingModel.get()
            if model:
                # Warm the model with a dummy encode
                model.encode("warmup")
                import logging
                logging.getLogger("synrix.runtime").info("Embedding model pre-warmed")
        except Exception as e:
            import logging
            logging.getLogger("synrix.runtime").warning("Model pre-warm failed: %s", e)
    import threading
    threading.Thread(target=_load, name="model-prewarm", daemon=True).start()


@app.on_event("startup")
async def _preload_agents():
    """Pre-load all registered agents in background so server starts immediately.

    Without this, agents 'disappear' from the dashboard until their next API call.
    Runs in a background thread so the server accepts requests right away.
    """
    def _load():
        try:
            from synrix_runtime.api.tenant import TenantManager
            tm = TenantManager.get_instance()
            tenants = tm.list_tenants()
            total = 0
            for tenant in tenants:
                tid = tenant["tenant_id"]
                try:
                    agents = tm.get_tenant_agents(tid)
                    for agent in agents:
                        aid = agent.get("agent_id")
                        state = agent.get("state")
                        # Only reload agents that were running (not deregistered)
                        if aid and state in ("running", None):
                            try:
                                runtime = tm.get_runtime(tid, aid)
                                cache_key = f"{tid}:{aid}"
                                _agent_runtimes[cache_key] = runtime
                                # Attach tenant LLM settings
                                tenant_settings = _get_tenant_settings(tid)
                                if tenant_settings:
                                    runtime._llm_config = tenant_settings
                                total += 1
                            except Exception as e:
                                logger.debug("Skip agent %s/%s: %s", tid[:8], aid, e)
                except Exception as e:
                    logger.debug("Skip tenant %s: %s", tid[:8], e)
            logger.info("Pre-loaded %d agents across %d tenants", total, len(tenants))
        except Exception as e:
            logger.warning("Agent pre-load failed: %s", e)
    # Run in background thread — don't block server startup
    import threading
    t = threading.Thread(target=_load, name="agent-preload", daemon=True)
    # t.start()  # Disabled: agents load on-demand to prevent pool exhaustion


# WAL checkpoint code removed — PostgreSQL handles this automatically via autovacuum


def _periodic_ttl_cleanup():
    """Background thread: clean expired TTL memories every 60 seconds."""
    while True:
        time.sleep(60)
        try:
            for cache_key, runtime in list(_agent_runtimes.items()):
                try:
                    # Check if tenant has TTL auto-cleanup enabled
                    tenant_id = cache_key.split(":")[0] if ":" in cache_key else cache_key
                    settings = _tenant_settings.get(tenant_id, {})
                    if not settings.get("ttl_auto_cleanup", True):
                        continue  # Tenant disabled auto-cleanup
                    result = runtime.cleanup_expired()
                    if result.get("deleted", 0) > 0:
                        logger.info("TTL cleanup: deleted %d expired memories for %s",
                                   result["deleted"], result.get("agent_id", cache_key))
                except Exception as _agent_err:
                    logger.warning("TTL cleanup per-agent failed | cache_key=%s: %s",
                                   cache_key, _agent_err)
                    _capture_silent(_agent_err, op="ttl_cleanup_agent",
                                    cache_key=cache_key)
        except Exception as e:
            logger.warning("TTL cleanup outer loop failed: %s", e)
            _capture_silent(e, op="ttl_cleanup_loop")


@app.on_event("startup")
async def _start_ttl_cleanup_thread():
    """Start background thread for periodic TTL cleanup."""
    import threading
    t = threading.Thread(target=_periodic_ttl_cleanup, name="ttl-cleanup", daemon=True)
    # t.start()  # Disabled: agents load on-demand to prevent pool exhaustion
    logger.info("TTL cleanup thread started (every 60s)")


@app.on_event("startup")
async def _start_metrics_background_refresh():
    """Start background thread that pre-computes metrics for all agents every 10s."""
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        mc = MetricsCollector.get_instance()
        mc.start_background_refresh()
        logger.info("Background metrics refresh thread started (every 10s)")
    except Exception as e:
        logger.warning("Could not start metrics background refresh: %s", e)


@app.on_event("shutdown")
async def _graceful_shutdown():
    """Flush pending writes and let executor drain before exit."""
    logger.info("Shutting down — flushing pending work...")
    _executor.shutdown(wait=True, cancel_futures=False)
    logger.info("Shutdown complete")


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Enforce per-tenant rate limiting on all endpoints except /health and auth."""
    path = request.url.path
    if path == "/health":
        return await call_next(request)

    # Rate limit auth endpoints by IP (prevent brute-force)
    if path in ("/v1/auth/login", "/v1/auth/signup", "/v1/auth/verify",
                 "/v1/auth/reset-password", "/v1/auth/forgot-password", "/v1/auth/resend-code"):
        client_ip = request.client.host if request.client else "unknown"
        if not _auth_rate_limiter.allow(f"auth:{client_ip}", rpm_override=_AUTH_RPM):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many attempts. Try again later.", "retry_after_seconds": 60},
            )
        return await call_next(request)

    # Extract tenant from auth header for rate limiting
    tenant_id = "anonymous"
    plan = "free"
    auth_header = request.headers.get("authorization", "") or request.headers.get("x-api-key", "")
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
        try:
            from synrix_runtime.api.tenant import TenantManager
            tm = TenantManager.get_instance()
            tenant = tm.verify_api_key(api_key)
            if tenant:
                tenant_id = tenant.get("tenant_id", "anonymous")
                plan = tenant.get("plan", "free")
        except Exception:
            pass

    # Tag Sentry scope with tenant + plan so errors are filterable by account.
    # Safe no-op if Sentry is not configured.
    if _sentry_dsn:
        try:
            import sentry_sdk
            sentry_sdk.set_tag("tenant_id", tenant_id)
            sentry_sdk.set_tag("plan", plan)
            if tenant_id != "anonymous":
                sentry_sdk.set_user({"id": tenant_id})
        except Exception:
            pass

    if not _rate_limiter.allow(tenant_id, plan):
        from fastapi.responses import JSONResponse
        remaining = _rate_limiter.get_remaining(tenant_id)
        rpm = _PLAN_RATE_LIMITS.get(plan, _DEFAULT_RPM)
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded.",
                "limit": rpm,
                "plan": plan,
                "retry_after_seconds": 1,
            },
            headers={"Retry-After": "1", "X-RateLimit-Limit": str(rpm), "X-RateLimit-Remaining": str(remaining)},
        )
    return await call_next(request)


# Global state (initialized by start_cloud_server())
_boot_time = time.time()
_daemon = None
_auth_manager = None
_config = None


def init_cloud_server(daemon, config):
    """Initialize the cloud server with daemon and config references."""
    global _daemon, _auth_manager, _config, _boot_time
    _daemon = daemon
    _config = config
    _boot_time = time.time()
    _auth_manager = APIKeyManager(
        backend=daemon.backend if daemon else None,
        master_key=config.api_key if config else "",
    )


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def verify_auth(authorization: Optional[str] = Header(None)):
    """Verify API key. Returns tenant info dict or None."""
    auth_disabled = os.environ.get("SYNRIX_AUTH_DISABLED", "").strip() == "1"
    if auth_disabled:
        # Only allow in local development — refuse if running on a public port
        bind_host = os.environ.get("SYNRIX_API_HOST", "127.0.0.1")
        if bind_host not in ("127.0.0.1", "localhost", "::1"):
            logger.error("SYNRIX_AUTH_DISABLED=1 is NOT allowed when binding to %s — blocking request", bind_host)
            raise HTTPException(status_code=403, detail="Auth bypass not allowed on public interfaces")
        else:
            return {"tenant_id": "dev", "plan": "pro", "max_agents": 100, "max_memories_per_agent": 100000}

    # Try multi-tenant auth first
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        if authorization:
            tenant_info = tm.verify_api_key(authorization)
            if tenant_info:
                # Check email verification
                if not tenant_info.get("verified", 0):
                    raise HTTPException(
                        status_code=403,
                        detail="Email not verified. Check your inbox for a verification code, "
                               "or request a new one at POST /v1/auth/resend-code"
                    )
                return tenant_info
    except HTTPException:
        raise
    except Exception:
        pass

    # Fallback to legacy auth
    if _auth_manager:
        if not authorization:
            raise HTTPException(
                status_code=401,
                detail="API key required. Pass Authorization: Bearer sk-octopoda-... "
                       "Sign up at POST /v1/auth/signup",
            )
        key_info = _auth_manager.verify_key(authorization)
        if not key_info:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"tenant_id": key_info.tenant_id, "plan": "legacy", "max_agents": 100, "max_memories_per_agent": 100000}
    raise HTTPException(status_code=401, detail="Authentication required. Pass Authorization: Bearer sk-octopoda-...")


# ---------------------------------------------------------------------------
# Helper: get or create AgentRuntime (tenant-isolated)
# ---------------------------------------------------------------------------

_agent_runtimes: OrderedDict = OrderedDict()
_MAX_CACHED_RUNTIMES = 1000

# Auto-checkpoint: tracks write count per agent, snapshots every 25 writes
_auto_checkpoint_counter: dict = {}
# Bounded pool for background checkpoint + brain work (v3.1.3 p99 fix)
# Prevents thread explosion under high concurrency. Writes queue rather than spawn unbounded threads.
from concurrent.futures import ThreadPoolExecutor as _TPE
_bg_work_pool = _TPE(max_workers=8, thread_name_prefix='octo-bg')


def _get_tenant_id(auth) -> str:
    """Extract tenant_id from auth info. Raises 401 if not authenticated."""
    if auth and isinstance(auth, dict):
        tid = auth.get("tenant_id")
        if tid:
            return tid
    raise HTTPException(status_code=401, detail="Authentication required")


def _get_runtime(agent_id: str, auth=None, register: bool = False):
    """Get or create a tenant-isolated AgentRuntime.

    Args:
        register: If True, write agent state to DB (only for POST /v1/agents).
    """
    tenant_id = _get_tenant_id(auth)
    cache_key = f"{tenant_id}:{agent_id}"

    if cache_key in _agent_runtimes:
        _agent_runtimes.move_to_end(cache_key)
        return _agent_runtimes[cache_key]

    # Dev/test mode: use daemon runtime directly (no PostgreSQL needed)
    auth_disabled = os.environ.get("SYNRIX_AUTH_DISABLED", "").strip() == "1"
    if auth_disabled:
        try:
            from synrix_runtime.api.runtime import AgentRuntime
            runtime = AgentRuntime(agent_id, agent_type="cloud")
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Failed to initialize runtime: {e}")
    else:
        # Use TenantManager for isolated runtime
        try:
            from synrix_runtime.api.tenant import TenantManager, TenantLimitError
            tm = TenantManager.get_instance()

            # Ownership check: if not registering a new agent, verify it belongs to this tenant
            if not register:
                backend = tm.get_backend(tenant_id)
                state = backend.read(f"runtime:agents:{agent_id}:state")
                if state is None:
                    raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

            runtime = tm.get_runtime(tenant_id, agent_id, register=register)
        except TenantLimitError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Failed to initialize tenant runtime: {e}")

    # Attach per-tenant LLM config so fact extractor uses the right provider
    tenant_settings = _get_tenant_settings(tenant_id)
    if tenant_settings:
        # Check platform free tier limit (skip for admin accounts only)
        is_admin = tenant_id in _ADMIN_TENANTS
        if tenant_settings.get("llm_provider") == "platform" and not is_admin:
            used = tenant_settings.get("platform_extractions_used", 0)
            if used >= _PLATFORM_FREE_LIMIT:
                tenant_settings["llm_provider"] = "none"
                _save_tenant_settings(tenant_id, tenant_settings)
                logger.info("Tenant %s exceeded platform free tier (%d/%d), downgraded to embedding-only",
                           tenant_id, used, _PLATFORM_FREE_LIMIT)
        # For admin accounts, ensure provider stays as platform
        if is_admin and tenant_settings.get("llm_provider") == "none":
            tenant_settings["llm_provider"] = "platform"
            _save_tenant_settings(tenant_id, tenant_settings)
        runtime._llm_config = tenant_settings
        runtime._llm_model = tenant_settings.get("llm_model", "unknown")

    # Evict oldest if at capacity
    while len(_agent_runtimes) >= _MAX_CACHED_RUNTIMES:
        oldest_key, oldest_rt = _agent_runtimes.popitem(last=False)
        logger.info("Evicted stale runtime: %s", oldest_key)

    _agent_runtimes[cache_key] = runtime
    return runtime
# ---------------------------------------------------------------------------
# Auth: Signup / Login
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _PydanticBase

class SignupRequest(_PydanticBase):
    email: str
    password: str
    first_name: str
    last_name: str
    company: str = ""
    use_case: str = ""

class LoginRequest(_PydanticBase):
    email: str
    password: str

class VerifyEmailRequest(_PydanticBase):
    email: str
    code: str

class ResendCodeRequest(_PydanticBase):
    email: str


import re as _re

_EMAIL_RE = _re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_AGENT_ID_RE = _re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")

# Disposable email domains — block mass account creation
_DISPOSABLE_DOMAINS = {
    "tempmail.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "mailinator.com", "throwaway.email", "temp-mail.org", "fakeinbox.com",
    "sharklasers.com", "guerrillamailblock.com", "grr.la", "dispostable.com",
    "yopmail.com", "yopmail.fr", "trashmail.com", "trashmail.me", "trashmail.net",
    "10minutemail.com", "10minute.email", "minutemail.com", "tempail.com",
    "mohmal.com", "burnermail.io", "maildrop.cc", "mailnesia.com",
    "mailcatch.com", "tmail.ws", "harakirimail.com", "getairmail.com",
    "meltmail.com", "throwam.com", "getnada.com", "emailondeck.com",
    "33mail.com", "mailexpire.com", "tempinbox.com", "discard.email",
    "discardmail.com", "mailbox92.biz", "spamgourmet.com", "tempr.email",
    "mytemp.email", "mt2015.com", "emailfake.com", "crazymailing.com",
    "mailsac.com", "inboxkitten.com", "tempmailo.com", "emailnator.com",
}

def _check_disposable_email(email: str):
    domain = email.lower().split("@")[-1]
    if domain in _DISPOSABLE_DOMAINS:
        raise HTTPException(status_code=422, detail="Disposable email addresses are not allowed. Please use a real email.")

def _validate_name(name: str, field: str):
    if not name or not name.strip():
        raise HTTPException(status_code=422, detail=f"{field} is required")
    if len(name.strip()) > 100:
        raise HTTPException(status_code=422, detail=f"{field} too long (max 100 characters)")
    if len(name.strip()) < 1:
        raise HTTPException(status_code=422, detail=f"{field} is required")


# ---------------------------------------------------------------------------
# Email verification: 6-digit codes with 10-minute expiry
# ---------------------------------------------------------------------------
import secrets as _secrets
try:
    import fcntl
except ImportError:
    fcntl = None  # Not available on Windows; file locking skipped
# json imported at top of file

_VERIFY_CODE_TTL = 1800  # 30 minutes
_MAX_VERIFY_ATTEMPTS = 5
_VERIFY_FILE = os.environ.get("OCTOPODA_VERIFY_FILE", "/var/lib/octopoda/verification_codes.json")

def _load_verify_codes() -> dict:
    try:
        with open(_VERIFY_FILE, "r") as f:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_verify_codes(codes: dict):
    try:
        os.makedirs(os.path.dirname(_VERIFY_FILE), exist_ok=True)
        with open(_VERIFY_FILE, "w") as f:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(codes, f)
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception as e:
        logger.error("Failed to save verification codes to %s: %s", _VERIFY_FILE, e)

def _generate_verification_code(email: str) -> str:
    code = str(_secrets.randbelow(900000) + 100000)
    codes = _load_verify_codes()
    codes[email] = {"code": code, "expires": time.time() + _VERIFY_CODE_TTL, "attempts": 0}
    _save_verify_codes(codes)
    return code

def _verify_code(email: str, code: str) -> bool:
    codes = _load_verify_codes()
    entry = codes.get(email)
    if not entry:
        return False
    if time.time() > entry["expires"]:
        codes.pop(email, None)
        _save_verify_codes(codes)
        return False
    if entry.get("attempts", 0) >= _MAX_VERIFY_ATTEMPTS:
        codes.pop(email, None)
        _save_verify_codes(codes)
        return False
    if entry["code"] != code:
        entry["attempts"] = entry.get("attempts", 0) + 1
        codes[email] = entry
        _save_verify_codes(codes)
        return False
    codes.pop(email, None)
    _save_verify_codes(codes)
    return True


# ---------------------------------------------------------------------------
# Resend email integration
# ---------------------------------------------------------------------------
_RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
_RESEND_FROM = os.environ.get("RESEND_FROM_EMAIL", "Octopoda <noreply@send.octopodas.com>")

def _send_verification_email(email: str, first_name: str, code: str):
    """Send a verification code email via Resend."""
    if not _RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping verification email to %s (code: %s)", email, code)
        return

    try:
        import requests as _req
        resp = _req.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": _RESEND_FROM,
                "to": [email],
                "subject": f"Your Octopoda verification code: {code}",
                "html": f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
                    <div style="text-align: center; margin-bottom: 32px;">
                        <h1 style="color: #1a1a2e; font-size: 24px; margin: 0;">🐙 Octopoda</h1>
                        <p style="color: #666; font-size: 14px; margin: 4px 0 0;">Agent Memory Infrastructure</p>
                    </div>
                    <div style="background: #f8f9fa; border-radius: 12px; padding: 32px; text-align: center;">
                        <p style="color: #333; font-size: 16px; margin: 0 0 8px;">
                            Hey{(' ' + first_name) if first_name else ''}, welcome to Octopoda!
                        </p>
                        <p style="color: #666; font-size: 14px; margin: 0 0 24px;">
                            Enter this code to verify your email:
                        </p>
                        <div style="background: #1a1a2e; color: #fff; font-size: 32px; letter-spacing: 8px; padding: 16px 24px; border-radius: 8px; display: inline-block; font-family: monospace;">
                            {code}
                        </div>
                        <p style="color: #999; font-size: 12px; margin: 24px 0 0;">
                            This code expires in 30 minutes.
                        </p>
                    </div>
                    <p style="color: #999; font-size: 12px; text-align: center; margin: 24px 0 0;">
                        If you didn't sign up for Octopoda, ignore this email.
                    </p>
                </div>
                """,
            },
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            logger.error("Resend email failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("Failed to send verification email: %s", e)


def _send_password_reset_email(email: str, first_name: str, code: str):
    """Send a password reset code email via Resend."""
    if not _RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping reset email to %s (code: %s)", email, code)
        return

    try:
        import requests as _req
        resp = _req.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {_RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": _RESEND_FROM,
                "to": [email],
                "subject": f"Reset your Octopoda password: {code}",
                "html": f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
                    <div style="text-align: center; margin-bottom: 32px;">
                        <h1 style="color: #1a1a2e; font-size: 24px; margin: 0;">🐙 Octopoda</h1>
                        <p style="color: #666; font-size: 14px; margin: 4px 0 0;">Agent Memory Infrastructure</p>
                    </div>
                    <div style="background: #f8f9fa; border-radius: 12px; padding: 32px; text-align: center;">
                        <p style="color: #333; font-size: 16px; margin: 0 0 8px;">
                            Hey{(' ' + first_name) if first_name else ''}, we received a password reset request.
                        </p>
                        <p style="color: #666; font-size: 14px; margin: 0 0 24px;">
                            Enter this code to reset your password:
                        </p>
                        <div style="background: #1a1a2e; color: #fff; font-size: 32px; letter-spacing: 8px; padding: 16px 24px; border-radius: 8px; display: inline-block; font-family: monospace;">
                            {code}
                        </div>
                        <p style="color: #999; font-size: 12px; margin: 24px 0 0;">
                            This code expires in 30 minutes.
                        </p>
                    </div>
                    <p style="color: #999; font-size: 12px; text-align: center; margin: 24px 0 0;">
                        If you didn't request a password reset, ignore this email. Your password won't change.
                    </p>
                </div>
                """,
            },
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            logger.error("Resend reset email failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("Failed to send reset email: %s", e)
_KEY_RE = _re.compile(r"^[a-zA-Z0-9_\-\.:/]{1,512}$")


def _validate_email(email: str):
    if not email or len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Invalid email address")

def _validate_password(password: str):
    if not password or len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    if len(password) > 128:
        raise HTTPException(status_code=422, detail="Password too long (max 128 characters)")

def _extract_topic_key(text: str, prefix: str = "topic") -> str:
    """Extract a stable, topic-based key from text.

    "I really like Tesla cars" → "preference:tesla_cars"
    "actually I prefer BMW over Tesla" → "preference:bmw_tesla"
    "not a fan of maserati due to performance" → "preference:maserati_performance"

    Uses the longest meaningful words as the key so related preferences
    overwrite each other, creating version history.
    """
    import re
    # Common stop words to filter out
    stop = {
        "i", "me", "my", "we", "our", "you", "your", "the", "a", "an", "is", "am",
        "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
        "does", "did", "will", "would", "could", "should", "shall", "can", "may",
        "might", "must", "not", "no", "but", "and", "or", "if", "then", "so",
        "that", "this", "these", "those", "it", "its", "of", "in", "on", "at",
        "to", "for", "with", "from", "by", "about", "into", "over", "after",
        "before", "between", "really", "actually", "just", "very", "much",
        "like", "dont", "think", "know", "want", "need", "get", "got",
        "also", "too", "even", "still", "already", "than", "more", "most",
        "some", "any", "all", "each", "every", "both", "few", "many",
        "prefer", "love", "hate", "dislike", "fan", "due", "because",
        "though", "although", "however", "tbh", "imo", "yeah", "nah",
        "what", "how", "when", "where", "why", "who", "which",
        "their", "them", "they", "him", "her", "his", "she", "he",
    }
    # Extract words, lowercase, filter stops and short words
    words = re.findall(r'[a-zA-Z]+', text.lower())
    keywords = [w for w in words if w not in stop and len(w) > 2]

    if not keywords:
        # Fallback to timestamp if no keywords found
        import time
        return f"{prefix}_{int(time.time())}"

    # Take up to 3 most significant words (longest first = most specific)
    # Then sort alphabetically so "bmw tesla" and "tesla bmw" produce the same key
    keywords.sort(key=len, reverse=True)
    top = keywords[:3]
    top.sort()  # Alphabetical = stable ordering regardless of sentence structure
    topic = "_".join(top)

    # Cap length
    if len(topic) > 60:
        topic = topic[:60]

    return f"{prefix}:{topic}"


def _validate_agent_id(agent_id: str):
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(
            status_code=422,
            detail="Invalid agent_id. Use letters, numbers, hyphens, underscores, dots (max 128 chars)",
        )

def _validate_key(key: str):
    if not _KEY_RE.match(key):
        raise HTTPException(
            status_code=422,
            detail="Invalid key. Use letters, numbers, hyphens, underscores, dots, colons, slashes (max 512 chars)",
        )


@app.post("/v1/auth/signup")
async def signup(req: SignupRequest):
    """Create a new account. Returns tenant_id + API key (inactive until email verified)."""
    _validate_email(req.email)
    _check_disposable_email(req.email)
    _validate_password(req.password)
    _validate_name(req.first_name, "First name")
    _validate_name(req.last_name, "Last name")
    if req.use_case and req.use_case not in ("ai_agent", "chatbot", "rag_pipeline", "research", "other", ""):
        raise HTTPException(status_code=422, detail="Invalid use_case")

    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    result = tm.create_tenant(
        req.email, req.password,
        first_name=req.first_name.strip(),
        last_name=req.last_name.strip(),
        company=req.company.strip() if req.company else "",
        use_case=req.use_case.strip() if req.use_case else "",
    )
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "Signup failed"))

    # Send verification email
    code = _generate_verification_code(req.email.lower())
    _send_verification_email(req.email.lower(), req.first_name.strip(), code)

    result["email_verified"] = False
    result["message"] = "Check your email for a 6-digit verification code."
    return result


@app.post("/v1/auth/verify")
async def verify_email(req: VerifyEmailRequest):
    """Verify email with 6-digit code sent during signup."""
    _validate_email(req.email)
    if not req.code or len(req.code) != 6 or not req.code.isdigit():
        raise HTTPException(status_code=422, detail="Code must be 6 digits")

    if not _verify_code(req.email.lower(), req.code):
        raise HTTPException(status_code=400, detail="Invalid or expired code. Request a new one.")

    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    tm.set_verified(req.email.lower(), True)
    return {"verified": True, "email": req.email.lower()}


@app.post("/v1/auth/resend-code")
async def resend_verification_code(req: ResendCodeRequest):
    """Resend verification code to email."""
    _validate_email(req.email)
    _check_disposable_email(req.email)

    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    tenant = tm.get_tenant_by_email(req.email.lower())
    if not tenant:
        # Don't reveal if account exists
        return {"sent": True, "message": "If an account exists, a code has been sent."}

    if tenant.get("verified"):
        return {"sent": False, "message": "Email already verified."}

    code = _generate_verification_code(req.email.lower())
    _send_verification_email(req.email.lower(), tenant.get("first_name", ""), code)
    return {"sent": True, "message": "Verification code sent."}


@app.post("/v1/auth/login")
async def login(req: LoginRequest):
    """Login with email + password. Returns tenant info + API key."""
    _validate_email(req.email)
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    tenant = tm.authenticate(req.email, req.password)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    api_key = tm.create_session_key(tenant["tenant_id"])
    return {
        "tenant_id": tenant["tenant_id"],
        "email": tenant["email"],
        "plan": tenant["plan"],
        "api_key": api_key,
    }


@app.post("/v1/auth/api-key")
async def regenerate_key(auth=Depends(verify_auth)):
    """Generate a new API key (deactivates old ones)."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    new_key = tm.regenerate_api_key(tenant_id)
    if not new_key:
        raise HTTPException(status_code=500, detail="Failed to regenerate key")
    return {"api_key": new_key, "warning": "Save this key — it will not be shown again."}


@app.get("/v1/auth/me")
async def get_me(auth=Depends(verify_auth)):
    """Get current account info."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    tenant = tm.get_tenant(tenant_id)
    if not tenant:
        return {"tenant_id": tenant_id, "plan": "dev"}
    return {
        "tenant_id": tenant["tenant_id"],
        "email": tenant["email"],
        "first_name": tenant.get("first_name", ""),
        "last_name": tenant.get("last_name", ""),
        "company": tenant.get("company", ""),
        "use_case": tenant.get("use_case", ""),
        "plan": tenant["plan"],
        "max_agents": tenant["max_agents"],
        "max_memories_per_agent": tenant["max_memories_per_agent"],
        "email_verified": bool(tenant.get("verified", 0)),
    }


class ChangePasswordRequest(_PydanticBase):
    old_password: str
    new_password: str

class ForgotPasswordRequest(_PydanticBase):
    email: str

class ResetPasswordRequest(_PydanticBase):
    email: str
    code: str
    new_password: str


@app.post("/v1/auth/change-password")
async def change_password(req: ChangePasswordRequest, auth=Depends(verify_auth)):
    """Change account password (requires current password)."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    result = tm.change_password(tenant_id, req.old_password, req.new_password)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Password change failed"))
    return {"success": True}


@app.post("/v1/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """Send a password reset code to email."""
    _validate_email(req.email)

    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    tenant = tm.get_tenant_by_email(req.email.lower())

    # Always return success (don't reveal if account exists)
    if not tenant:
        return {"sent": True, "message": "If an account exists, a reset code has been sent."}

    code = _generate_verification_code(f"reset:{req.email.lower()}")
    _send_password_reset_email(req.email.lower(), tenant.get("first_name", ""), code)
    return {"sent": True, "message": "If an account exists, a reset code has been sent."}


@app.post("/v1/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    """Reset password using code from forgot-password email."""
    _validate_email(req.email)
    _validate_password(req.new_password)

    if not req.code or len(req.code) != 6 or not req.code.isdigit():
        raise HTTPException(status_code=422, detail="Code must be 6 digits")

    if not _verify_code(f"reset:{req.email.lower()}", req.code):
        raise HTTPException(status_code=400, detail="Invalid or expired code. Request a new one.")

    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    result = tm.reset_password(req.email.lower(), req.new_password)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Password reset failed"))
    return {"success": True, "message": "Password reset successfully. You can now log in."}


# ---------------------------------------------------------------------------
# GDPR: Data export & account deletion
# ---------------------------------------------------------------------------

@app.get("/v1/auth/export")
async def export_data(auth=Depends(verify_auth)):
    """Download all your data as JSON (GDPR Article 20)."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    return tm.export_tenant_data(tenant_id)


@app.delete("/v1/auth/account")
async def delete_account(auth=Depends(verify_auth)):
    """Permanently delete your account and all data (GDPR Article 17)."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    result = tm.delete_tenant(tenant_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail=result.get("error", "Deletion failed"))
    # Clear from runtime cache
    cache_keys = [k for k in _agent_runtimes if k.startswith(f"{tenant_id}:")]
    for k in cache_keys:
        _agent_runtimes.pop(k, None)
    return result


# ---------------------------------------------------------------------------
# Usage stats
# ---------------------------------------------------------------------------

@app.get("/v1/usage")
async def usage_stats(auth=Depends(verify_auth)):
    """Get usage statistics — agents, memories, plan limits."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    return tm.get_tenant_usage(tenant_id)


# ---------------------------------------------------------------------------
# Health & System
# ---------------------------------------------------------------------------

@app.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health():
    backend_type = "unknown"
    if _daemon and hasattr(_daemon, 'backend'):
        backend_type = getattr(_daemon.backend, 'backend_type', 'unknown')
    return HealthResponse(
        status="ok",
        version="3.1.1",
        backend=backend_type,
        uptime_seconds=time.time() - _boot_time,
    )


@app.get("/v1/status")
async def system_status(auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    agents = _get_agents_from_backend(backend)
    active = [a for a in agents if a.get("state") != "deregistered"]
    return {
        "status": "running",
        "uptime_seconds": round(time.time() - _boot_time, 1),
        "version": "2.0.6",
        "total_agents": len(agents),
        "active_agents": len(active),
        "agents": active,
    }


# ---------------------------------------------------------------------------
# Agent Management (with pagination)
# ---------------------------------------------------------------------------

@app.post("/v1/agents", response_model=AgentResponse)
async def register_agent(req: RegisterAgentRequest, auth=Depends(verify_auth)):
    _validate_agent_id(req.agent_id)
    try:
        runtime = _get_runtime(req.agent_id, auth, register=True)
        return AgentResponse(
            agent_id=req.agent_id,
            agent_type=req.agent_type,
            status="running",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/agents")
async def list_agents(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    auth=Depends(verify_auth),
):
    tenant_id = _get_tenant_id(auth)
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        all_agents = tm.get_tenant_agents(tenant_id)
    except Exception:
        # Dev/test fallback: query agents from daemon backend
        backend = _get_tenant_backend(auth)
        all_agents = _get_agents_from_backend(backend) if backend else []
    total = len(all_agents)
    page = all_agents[offset:offset + limit]

    # Enrich agents with metrics (same as SSE stream)
    backend = _get_tenant_backend(auth)
    if backend and page:
        try:
            from synrix_runtime.monitoring.metrics import MetricsCollector
            collector = MetricsCollector(backend, tenant_id=tenant_id)
            for a in page:
                agent_id = a.get("agent_id", "")
                if agent_id:
                    try:
                        m = collector.get_agent_metrics(agent_id)
                        a["performance_score"] = m.performance_score
                        a["total_operations"] = m.total_operations
                        a["avg_write_latency_us"] = m.avg_write_latency_us
                        a["avg_read_latency_us"] = m.avg_read_latency_us
                        a["memory_node_count"] = m.memory_node_count
                        a["crash_count"] = m.crash_count
                        a["uptime_seconds"] = m.uptime_seconds
                        a["error_rate"] = m.error_rate
                    except Exception as _agent_err:
                        pass
                a["status"] = a.get("state", "unknown")
        except Exception:
            pass

    return {"agents": page, "count": len(page), "total": total, "offset": offset, "limit": limit}


@app.get("/v1/agents/{agent_id}")
async def get_agent(agent_id: str, auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    if not backend:
        raise HTTPException(status_code=503, detail="Backend not available")
    state_result = backend.read(f"runtime:agents:{agent_id}:state")
    state = None
    if state_result:
        data = state_result.get("data", {})
        val = data.get("value", data)
        state = val.get("value") if isinstance(val, dict) else val
    if state:
        try:
            from synrix_runtime.monitoring.metrics import MetricsCollector
            mc = MetricsCollector(backend, tenant_id=tenant_id)
            metrics = mc.get_agent_metrics(agent_id)
            return {
                "agent_id": agent_id,
                "state": state,
                "metrics": {
                    "total_operations": metrics.total_operations,
                    "total_writes": metrics.total_writes,
                    "total_reads": metrics.total_reads,
                    "avg_write_latency_us": metrics.avg_write_latency_us,
                    "avg_read_latency_us": metrics.avg_read_latency_us,
                    "crash_count": metrics.crash_count,
                    "performance_score": metrics.performance_score,
                    "uptime_seconds": metrics.uptime_seconds,
                },
            }
        except Exception:
            return {"agent_id": agent_id, "state": state}
    raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@app.delete("/v1/agents/{agent_id}")
async def deregister_agent(agent_id: str, auth=Depends(verify_auth)):
    tenant_id = _get_tenant_id(auth)
    # Check agent actually exists for this tenant
    backend = _get_tenant_backend(auth)
    if backend:
        state = backend.read(f"runtime:agents:{agent_id}:state")
        if state is None:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
        current = state.get("value", "") if isinstance(state, dict) else state
        if current == "deregistered":
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} already deregistered")
    cache_key = f"{tenant_id}:{agent_id}"
    if cache_key in _agent_runtimes:
        _agent_runtimes[cache_key].shutdown()
        del _agent_runtimes[cache_key]
    if backend:
        backend.write(f"runtime:agents:{agent_id}:state", {"value": "deregistered"})
        backend.write(f"runtime:agents:{agent_id}:last_active", {"value": time.time()})
    return {"agent_id": agent_id, "deregistered": True}


# ---------------------------------------------------------------------------
# Memory Operations
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/remember", response_model=MemoryResponse)
async def remember(agent_id: str, req: RememberRequest, auth=Depends(verify_auth)):
    _validate_agent_id(agent_id)
    _validate_key(req.key)
    tenant_id = _get_tenant_id(auth)

    # Brain kill switch — block writes to paused agents
    try:
        from synrix_runtime.monitoring.brain import LoopBreaker
        if LoopBreaker.is_paused(tenant_id, agent_id):
            raise HTTPException(
                status_code=429,
                detail=f"Agent '{agent_id}' is paused by Brain kill switch. "
                       f"Resume via POST /v1/brain/resume/{agent_id}",
            )
    except HTTPException:
        raise
    except Exception:
        pass

    # Tenant-scoped memory cap enforcement.
    #
    # Previously this called synrix.licensing.check_memory_limit(agent_id) —
    # that module was written for offline self-hosted users with HMAC-signed
    # license keys, not cloud tenants. It tracked counts in a local SQLite
    # ledger using agent_id alone (not tenant-scoped) with stale tier numbers
    # (free=3 agents / 10K per agent) that didn't match the cloud plans
    # (free=5 agents / 5K total). On the cloud, tier is determined by the
    # tenants.plan row — check that directly, and let admins bypass.
    if tenant_id not in _ADMIN_TENANTS:
        try:
            _enforce_tenant_memory_cap(tenant_id)
        except HTTPException:
            raise
        except Exception as e:
            # Fail open on DB glitch — better to accept a write than reject
            # a legitimate one during a transient outage. The error is logged.
            logger.warning("tenant memory cap check failed (failing open) | tenant=%s: %s",
                           tenant_id, e)
            _capture_silent(e, op="memory_cap_check", tenant_id=tenant_id)

    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor, lambda: runtime.remember(req.key, req.value, tags=req.tags)
    )

    # Track platform free tier usage
    _increment_platform_usage(tenant_id)

    # Check if free tier is exhausted — add warning to response
    tier_warning = None
    tenant_settings = _get_tenant_settings(tenant_id)
    if tenant_settings.get("llm_provider") == "none":
        used = tenant_settings.get("platform_extractions_used", 0)
        if used >= _PLATFORM_FREE_LIMIT:
            tier_warning = (
                "Free AI extractions exhausted (100/100). "
                "AI-powered extraction is disabled — memories are stored but without intelligent fact extraction. "
                "Add your own API key at octopodas.com/dashboard/settings to restore full features."
            )

    # (the previous `record_memory_written` call wrote to a server-local
    # SQLite ledger inherited from the offline-license era — it wasn't read
    # by anything on the cloud and was just accumulating rows. Removed.)

    # Track latency & errors for anomaly detection
    _track_latency_and_errors(agent_id, result.latency_us, result.success, runtime)

    # Auto-checkpoint: save a snapshot every 25 writes (non-blocking)
    try:
        _auto_checkpoint_counter[f"{tenant_id}:{agent_id}"] = _auto_checkpoint_counter.get(f"{tenant_id}:{agent_id}", 0) + 1
        if _auto_checkpoint_counter[f"{tenant_id}:{agent_id}"] >= 25:
            _auto_checkpoint_counter[f"{tenant_id}:{agent_id}"] = 0
            def _bg_checkpoint():
                try:
                    runtime.snapshot(label=f"auto-{int(time.time())}")
                except Exception as bg_e:
                    logger.warning("auto-snapshot failed | tenant=%s agent=%s: %s",
                                   tenant_id, agent_id, bg_e)
                    _capture_silent(bg_e, op="auto_snapshot",
                                    tenant_id=tenant_id, agent_id=agent_id)
            _bg_work_pool.submit(_bg_checkpoint)
    except Exception as e:
        logger.warning("auto-checkpoint scheduler failed | tenant=%s agent=%s: %s",
                       tenant_id, agent_id, e)
        _capture_silent(e, op="auto_checkpoint_schedule",
                        tenant_id=tenant_id, agent_id=agent_id)

    # Brain Intelligence — fire-and-forget on bounded pool (v3.1.3 p99 fix)
    # Previously ran synchronously on request path, adding 100-500ms+ p99 spikes.
    # Warnings are no longer returned in-band. Users can fetch via /v1/brain/events if needed.
    brain_warnings = []
    def _bg_brain_process():
        try:
            from synrix_runtime.monitoring.brain import BrainHub
            backend = _get_tenant_backend(auth)
            BrainHub.process_write(
                tenant_id, agent_id, req.key, req.value,
                embedding=None, backend=backend,
            )
        except Exception as e:
            logger.warning("BrainHub.process_write failed | tenant=%s agent=%s: %s",
                           tenant_id, agent_id, e)
            _capture_silent(e, op="brain_process_write",
                            tenant_id=tenant_id, agent_id=agent_id)
    _bg_work_pool.submit(_bg_brain_process)

    return MemoryResponse(
        node_id=result.node_id,
        key=req.key,
        latency_us=result.latency_us,
        timestamp=result.timestamp,
        success=result.success,
        loop_warning=result.loop_warning,
        warning=tier_warning,
    )


@app.post("/v1/agents/{agent_id}/flush")
async def flush_enrichment(agent_id: str, auth=Depends(verify_auth)):
    """Wait for all pending background enrichment (embeddings, facts, NER) to complete.

    Call after writes to ensure memories are searchable via semantic search.
    Returns counts of completed/failed/timed-out enrichment tasks.
    """
    _validate_agent_id(agent_id)
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.flush(timeout=60.0))
    return result


@app.post("/v1/agents/{agent_id}/remember/batch", response_model=BatchMemoryResponse)
async def remember_batch(agent_id: str, req: BatchRememberRequest, auth=Depends(verify_auth)):
    runtime = _get_runtime(agent_id, auth)
    results = []
    for item in req.items:
        # License enforcement: check memory limit per item
        try:
            from synrix.licensing import check_memory_limit, record_memory_written, MemoryLimitError
            check_memory_limit(agent_id)
        except MemoryLimitError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except Exception:
            pass

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, lambda k=item.key, v=item.value, t=item.tags: runtime.remember(k, v, tags=t))

        try:
            record_memory_written(agent_id)
        except Exception:
            pass

        results.append({
            "key": item.key,
            "node_id": result.node_id,
            "latency_us": result.latency_us,
            "success": result.success,
        })
    return BatchMemoryResponse(agent_id=agent_id, results=results, count=len(results))


@app.get("/v1/agents/{agent_id}/recall/{key:path}", response_model=RecallResponse)
async def recall(agent_id: str, key: str, auth=Depends(verify_auth)):
    runtime = _get_runtime(agent_id, auth)
    tenant_id = _get_tenant_id(auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.recall(key))

    # Track read for Memory Health
    if result.found:
        try:
            from synrix_runtime.monitoring.brain import BrainHub
            BrainHub.process_read(tenant_id, agent_id, key)
        except Exception:
            pass

    return RecallResponse(
        value=result.value,
        key=key,
        latency_us=result.latency_us,
        found=result.found,
    )


@app.get("/v1/agents/{agent_id}/search", response_model=SearchResponse)
async def search(
    agent_id: str,
    prefix: str = "",
    limit: int = Query(default=50, ge=1, le=1000),
    auth=Depends(verify_auth),
):
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.search(prefix, limit=limit))
    return SearchResponse(
        items=result.items,
        count=result.count,
        latency_us=result.latency_us,
    )


@app.get("/v1/agents/{agent_id}/similar")
async def semantic_search(
    agent_id: str,
    q: str = Query(..., description="Natural language search query"),
    limit: int = Query(default=10, ge=1, le=100),
    auth=Depends(verify_auth),
):
    """Semantic search — find memories by meaning, not just exact keys."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.recall_similar(q, limit=limit))
    return {
        "agent_id": agent_id,
        "query": q,
        "items": result.items,
        "count": result.count,
        "latency_us": result.latency_us,
    }


# ---------------------------------------------------------------------------
# Debug: Embedding inspection (temporary)
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/debug-embeddings")
async def debug_embeddings(agent_id: str, limit: int = Query(default=20), auth=Depends(verify_auth)):
    """Debug: check what embeddings exist for an agent's memories."""
    runtime = _get_runtime(agent_id, auth)
    backend = runtime.backend
    raw_client = backend.client if hasattr(backend, 'client') else backend
    collection = backend.collection if hasattr(backend, 'collection') else 'default'
    prefix = f"agents:{agent_id}:%"

    def _check():
        with raw_client._conn() as conn:
            # Count total nodes for this agent
            total = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE name LIKE ? AND (valid_until IS NULL OR valid_until = 0)",
                (prefix,),
            ).fetchone()[0]

            # Count nodes with embeddings
            with_emb = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE collection = ? AND embedding IS NOT NULL AND name LIKE ? AND (valid_until IS NULL OR valid_until = 0)",
                (collection, prefix),
            ).fetchone()[0]

            # Count nodes with WRONG collection
            wrong_coll = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE collection != ? AND name LIKE ? AND (valid_until IS NULL OR valid_until = 0)",
                (collection, prefix),
            ).fetchone()[0]

            # Check what collections exist for this agent
            collections = conn.execute(
                "SELECT DISTINCT collection, COUNT(*) as cnt FROM nodes WHERE name LIKE ? GROUP BY collection",
                (prefix,),
            ).fetchall()

            # Sample some nodes
            sample = conn.execute(
                "SELECT name, collection, embedding IS NOT NULL as has_emb, length(embedding) as emb_len FROM nodes WHERE name LIKE ? AND (valid_until IS NULL OR valid_until = 0) ORDER BY name LIMIT ?",
                (prefix, limit),
            ).fetchall()

            # Check fact_embeddings
            fact_count = conn.execute(
                "SELECT COUNT(*) FROM fact_embeddings WHERE collection = ? AND node_name LIKE ?",
                (collection, prefix),
            ).fetchone()[0]

        return {
            "agent_id": agent_id,
            "expected_collection": collection,
            "total_nodes": total,
            "nodes_with_embedding": with_emb,
            "nodes_wrong_collection": wrong_coll,
            "collections": [{"collection": r[0], "count": r[1]} for r in collections],
            "fact_embeddings": fact_count,
            "sample": [
                {"name": r[0], "collection": r[1], "has_emb": bool(r[2]), "emb_len": r[3]}
                for r in sample
            ],
        }

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _check)


# ---------------------------------------------------------------------------
# Conversation Processing (high-level API)
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/process-conversation")
async def process_conversation(agent_id: str, req: ProcessConversationRequest, auth=Depends(verify_auth)):
    """Process a conversation and automatically extract + store memories.

    Extracts preferences, facts, and decisions from the messages,
    stores them as individual memories with semantic embeddings.
    This is the recommended way to add memory to your agents —
    just pass the conversation, Octopoda handles the rest.
    """
    _validate_agent_id(agent_id)
    runtime = _get_runtime(agent_id, auth)
    tenant_id = _get_tenant_id(auth)
    loop = asyncio.get_event_loop()
    t0 = time.time()

    # Build conversation text from messages
    conv_lines = []
    for msg in req.messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        conv_lines.append(f"{role}: {content}")
    conversation_text = "\n".join(conv_lines)

    # Store the full conversation as a timestamped key
    ts = int(time.time())
    conv_key = f"{req.namespace}:turn_{ts}"
    conv_result = await loop.run_in_executor(
        _executor, lambda: runtime.remember(conv_key, conversation_text, tags=["conversation"])
    )
    _increment_platform_usage(tenant_id)

    stored_memories = [{"key": conv_key, "type": "conversation", "node_id": conv_result.node_id}]

    # Extract structured information from the conversation
    # The fact extractor handles decomposition into atomic facts
    # which are stored as embeddings for high-quality semantic search
    user_messages = [m.get("content", "") for m in req.messages if m.get("role") == "user"]
    assistant_messages = [m.get("content", "") for m in req.messages if m.get("role") == "assistant"]

    # Extract and store preferences (what the user wants/likes/dislikes)
    # Uses pgvector semantic search to find existing preferences about the same topic.
    # If found, overwrites the SAME key → creates version history.
    # "I like Italian food" → conversations:preference:food_italian (v1)
    # "I prefer Japanese food" → same key updated (v2) because semantic match > 0.55
    if req.extract_preferences and user_messages:
        pref_text = " ".join(user_messages)

        # Use recall_similar (pgvector) to find existing preference about same topic
        existing_key = None
        try:
            similar = await loop.run_in_executor(
                _executor, lambda: runtime.recall_similar(pref_text, limit=10)
            )
            # recall_similar returns SearchResult with .items = list of dicts
            items = similar.items if hasattr(similar, 'items') else []
            for match in items:
                match_key = match.get("key", "") if isinstance(match, dict) else getattr(match, "key", "")
                match_score = match.get("score", 0) if isinstance(match, dict) else getattr(match, "score", 0)
                if "preference" in match_key and match_score > 0.55:
                    existing_key = match_key
                    break
        except Exception:
            pass

        pref_key = existing_key or _extract_topic_key(pref_text, prefix=f"{req.namespace}:preference")
        pref_result = await loop.run_in_executor(
            _executor, lambda: runtime.remember(pref_key, pref_text, tags=["preference", "user"])
        )
        _increment_platform_usage(tenant_id)
        stored_memories.append({
            "key": pref_key, "type": "preferences",
            "node_id": pref_result.node_id,
            "updated_existing": existing_key is not None,
        })

    # Extract and store decisions/action items
    if req.extract_decisions and assistant_messages:
        decision_text = " ".join(assistant_messages)
        dec_key = _extract_topic_key(decision_text, prefix=f"{req.namespace}:decision")

        dec_result = await loop.run_in_executor(
            _executor, lambda: runtime.remember(dec_key, decision_text, tags=["decision", "action"])
        )
        _increment_platform_usage(tenant_id)
        stored_memories.append({
            "key": dec_key, "type": "decisions",
            "node_id": dec_result.node_id,
        })

    elapsed_ms = (time.time() - t0) * 1000

    # Track latency & errors for anomaly detection
    _track_latency_and_errors(agent_id, elapsed_ms * 1000, True, runtime)

    # Check if free tier is exhausted
    tier_warning = None
    tenant_settings = _get_tenant_settings(tenant_id)
    if tenant_settings.get("llm_provider") == "none":
        used = tenant_settings.get("platform_extractions_used", 0)
        if used >= _PLATFORM_FREE_LIMIT:
            tier_warning = (
                "Free AI extractions exhausted (100/100). "
                "AI-powered extraction is disabled — memories are stored but without intelligent fact extraction. "
                "Add your own API key at octopodas.com/dashboard/settings to restore full features."
            )

    response = {
        "agent_id": agent_id,
        "memories_stored": len(stored_memories),
        "memories": stored_memories,
        "message_count": len(req.messages),
        "latency_ms": round(elapsed_ms, 1),
    }
    if tier_warning:
        response["warning"] = tier_warning
    return response


@app.post("/v1/agents/{agent_id}/context")
async def get_context(agent_id: str, req: GetContextRequest, auth=Depends(verify_auth)):
    """Get relevant context for a query from the agent's memory.

    Searches the agent's memories semantically and returns the most
    relevant context. Use this before your agent generates a response
    to give it access to everything it has learned.
    """
    _validate_agent_id(agent_id)
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    t0 = time.time()

    # Semantic search across all memories
    result = await loop.run_in_executor(
        _executor, lambda: runtime.recall_similar(req.query, limit=req.limit)
    )

    elapsed_ms = (time.time() - t0) * 1000

    now = time.time()

    if req.format == "text":
        # Format as a readable context block for LLM consumption
        context_parts = []
        for item in result.items:
            value = item.get("value", "")
            score = item.get("score", 0)
            # Filter out expired TTL entries
            if isinstance(value, dict) and "__expires_at" in value:
                if value["__expires_at"] < now:
                    continue
                value = value.get("value", str(value))
            elif isinstance(value, dict):
                value = value.get("value", str(value))
            if score > 0.5:  # Only include relevant results
                context_parts.append(str(value))

        context_text = "\n---\n".join(context_parts) if context_parts else ""
        return {
            "agent_id": agent_id,
            "query": req.query,
            "context": context_text,
            "memory_count": len(context_parts),
            "latency_ms": round(elapsed_ms, 1),
        }
    else:
        # Filter out expired TTL entries
        filtered = []
        for item in result.items:
            val = item.get("value", "")
            if isinstance(val, dict) and "__expires_at" in val:
                if val["__expires_at"] < now:
                    continue
            filtered.append(item)
        return {
            "agent_id": agent_id,
            "query": req.query,
            "memories": filtered,
            "memory_count": len(filtered),
            "latency_ms": round(elapsed_ms, 1),
        }


@app.get("/v1/agents/{agent_id}/history/{key:path}")
async def memory_history(agent_id: str, key: str, auth=Depends(verify_auth)):
    """Get all versions of a memory over time."""
    tenant_id = _get_tenant_id(auth)
    backend = _get_tenant_backend(auth)
    if not backend:
        raise HTTPException(status_code=503, detail="Backend not available")

    full_key = f"agents:{agent_id}:{key}"
    loop = asyncio.get_event_loop()
    raw_history = await loop.run_in_executor(_executor, lambda: backend.get_history(full_key))

    versions = []
    for i, r in enumerate(raw_history):
        data = r.get("data", {})
        value = data.get("value", data)
        # Unwrap {"value": X} wrapping from remember()
        if isinstance(value, dict) and "value" in value:
            value = value["value"]

        tags = data.get("_tags", [])
        display_tags = [t for t in tags if isinstance(t, str) and not t.startswith("__")]
        importance = data.get("__importance", "normal")

        valid_from = r.get("valid_from")
        valid_until = r.get("valid_until")
        is_current = valid_until is None or valid_until == 0

        versions.append({
            "value": value,
            "version": i + 1,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "tags": display_tags,
            "importance": importance,
            "is_current": is_current,
        })

    return {
        "agent_id": agent_id,
        "key": key,
        "current_version": len(versions),
        "total_versions": len(versions),
        "versions": versions,
    }


@app.get("/v1/agents/{agent_id}/related/{entity}")
async def related_entities(agent_id: str, entity: str, auth=Depends(verify_auth)):
    """Query the knowledge graph for entity relationships."""
    runtime = _get_runtime(agent_id, auth)
    result = runtime.related(entity)
    return {
        "agent_id": agent_id,
        "entity": result.entity,
        "entity_type": result.entity_type,
        "found": result.found,
        "relationships": result.relationships,
        "latency_us": result.latency_us,
    }


@app.get("/v1/agents/{agent_id}/memory")
async def list_memory(
    agent_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    auth=Depends(verify_auth),
):
    tenant_id = _get_tenant_id(auth)
    backend = _get_tenant_backend(auth)
    if backend:
        prefix = f"agents:{agent_id}:"
        start = time.perf_counter_ns()
        results = backend.query_prefix(prefix, limit=offset + limit)
        latency_us = (time.perf_counter_ns() - start) / 1000

        # Batch-fetch version counts for all keys in one query
        version_counts = {}
        try:
            pg = backend.client  # SynrixPostgresClient (has _conn/tenant_id)
            conn = pg._conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name, COUNT(*) FROM nodes "
                    "WHERE tenant_id = %s AND name LIKE %s GROUP BY name",
                    (pg.tenant_id, f"{prefix}%")
                )
                for row in cur.fetchall():
                    version_counts[row[0]] = row[1]
            finally:
                pg._release(conn)
        except Exception:
            pass

        items = []
        for item in results:
            key = item.get("key", "")
            # Skip internal keys (snapshots, state, heartbeat)
            short = key[len(prefix):] if key.startswith(prefix) else key
            if short.startswith("snapshots:") or short.startswith("__") or short == "state":
                continue
            data = item.get("data", {})
            metadata = item.get("metadata", {})
            valid_from = item.get("valid_from", 0)

            # Extract value (unwrap {"value": X} wrapping)
            value = data.get("value", data)

            # Extract tags (stored as data._tags by remember())
            tags = data.get("_tags", [])

            # Extract importance (stored as data.__importance by remember_important())
            importance = data.get("__importance", "normal")
            # Also check tags for __importance:level format
            if importance == "normal":
                for t in tags:
                    if isinstance(t, str) and t.startswith("__importance:"):
                        importance = t.split(":", 1)[1]
                        break

            # Filter out internal tags from display
            display_tags = [t for t in tags if isinstance(t, str) and not t.startswith("__")]

            # Strip agent prefix from key for cleaner display
            display_key = key[len(prefix):] if key.startswith(prefix) else key

            items.append({
                "key": display_key,
                "value": value,
                "tags": display_tags,
                "importance": importance,
                "created_at": valid_from,
                "version_count": version_counts.get(key, 1),
                "node_id": item.get("id"),
                "type": metadata.get("type", "agent_memory"),
            })

        page = items[offset:offset + limit]
        # Record read metric
        try:
            from synrix_runtime.monitoring.metrics import MetricsCollector
            mc = MetricsCollector(backend, tenant_id=tenant_id)
            mc.record_read(agent_id, f"memory:list", latency_us, len(page) > 0)
        except Exception:
            pass
        return {
            "agent_id": agent_id,
            "items": page,
            "count": len(page),
            "total": len(items),
            "offset": offset,
            "latency_us": round(latency_us, 1),
        }
    return {"agent_id": agent_id, "items": [], "count": 0, "total": 0, "offset": offset}


# ---------------------------------------------------------------------------
# TTL / Auto-Expire
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/remember/ttl")
async def remember_with_ttl(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Store a memory that auto-expires after ttl_seconds."""
    key = req.get("key")
    value = req.get("value")
    ttl_seconds = req.get("ttl_seconds", 3600)
    tags = req.get("tags")
    if not key or value is None:
        raise HTTPException(status_code=422, detail="key and value required")
    if ttl_seconds < 1 or ttl_seconds > 31536000:  # max 1 year
        raise HTTPException(status_code=422, detail="ttl_seconds must be 1-31536000")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.remember_with_ttl(key, value, ttl_seconds, tags=tags))
    return {
        "node_id": result.node_id,
        "key": key,
        "ttl_seconds": ttl_seconds,
        "expires_at": time.time() + ttl_seconds,
        "latency_us": result.latency_us,
        "success": result.success,
    }

@app.post("/v1/agents/{agent_id}/cleanup")
async def cleanup_expired(agent_id: str, auth=Depends(verify_auth)):
    """Remove all expired TTL memories for this agent."""
    runtime = _get_runtime(agent_id, auth)
    result = runtime.cleanup_expired()
    return result


# ---------------------------------------------------------------------------
# Memory Importance Scoring
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/remember/important")
async def remember_important(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Store a memory with importance level (critical/normal/low)."""
    key = req.get("key")
    value = req.get("value")
    importance = req.get("importance", "normal")
    tags = req.get("tags")
    if not key or value is None:
        raise HTTPException(status_code=422, detail="key and value required")
    if importance not in ("critical", "normal", "low"):
        raise HTTPException(status_code=422, detail="importance must be critical, normal, or low")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.remember_important(key, value, importance=importance, tags=tags))
    return {
        "node_id": result.node_id,
        "key": key,
        "importance": importance,
        "latency_us": result.latency_us,
        "success": result.success,
    }


# ---------------------------------------------------------------------------
# Conflict Detection
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/conflicts")
async def detect_conflicts(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Check if a new value conflicts with existing memories."""
    key = req.get("key", "")
    value = req.get("value")
    threshold = req.get("threshold", 0.7)
    if value is None:
        raise HTTPException(status_code=422, detail="value required")
    runtime = _get_runtime(agent_id, auth)
    result = runtime.detect_conflicts(key, value, threshold=threshold)
    return result

@app.post("/v1/agents/{agent_id}/remember/safe")
async def remember_safe(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Write a memory and return any detected conflicts."""
    key = req.get("key")
    value = req.get("value")
    tags = req.get("tags")
    tenant_id = _get_tenant_id(auth)
    settings = _get_tenant_settings(tenant_id)

    # Use tenant's conflict sensitivity if set, otherwise use request threshold or default
    threshold = req.get("conflict_threshold", settings.get("conflict_sensitivity", 0.85))

    if not key or value is None:
        raise HTTPException(status_code=422, detail="key and value required")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()

    # If conflict detection is disabled, just do a normal write
    if not settings.get("conflict_detection", True):
        result = await loop.run_in_executor(_executor, lambda: runtime.remember(key, value, tags=tags))
        return {
            "write": {
                "node_id": result.node_id,
                "key": result.key,
                "latency_us": result.latency_us,
                "success": result.success,
            },
            "conflicts": {"has_conflicts": False, "conflicts": [], "new_key": key, "checked_against": 0},
        }

    result = await loop.run_in_executor(_executor, lambda: runtime.remember_safe(key, value, tags=tags, conflict_threshold=threshold))
    return {
        "write": {
            "node_id": result.write.node_id,
            "key": result.write.key,
            "latency_us": result.write.latency_us,
            "success": result.write.success,
        },
        "conflicts": result.conflicts,
    }


# ---------------------------------------------------------------------------
# Usage Analytics
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/analytics")
async def agent_analytics(agent_id: str, auth=Depends(verify_auth)):
    """Get detailed usage analytics for an agent."""
    runtime = _get_runtime(agent_id, auth)
    return runtime.usage_analytics()


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

# In-memory webhook registry (per-tenant)
_webhook_registry: dict = {}  # tenant_id -> list of webhook configs

@app.post("/v1/webhooks")
async def register_webhook(req: dict, auth=Depends(verify_auth)):
    """Register a webhook URL to receive event notifications.

    Events: agent.crash, agent.recovery, memory.limit, memory.conflict
    """
    url = req.get("url")
    events = req.get("events", ["agent.crash", "agent.recovery"])
    if not url:
        raise HTTPException(status_code=422, detail="url required")
    # SSRF protection: only allow HTTPS URLs to public hosts
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("https",):
        raise HTTPException(status_code=422, detail="Only HTTPS webhook URLs are allowed")
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or hostname.startswith("10.") \
       or hostname.startswith("172.") or hostname.startswith("192.168.") or hostname.startswith("169.254."):
        raise HTTPException(status_code=422, detail="Webhook URLs must point to public hosts")
    tenant_id = _get_tenant_id(auth)
    if tenant_id not in _webhook_registry:
        _webhook_registry[tenant_id] = []
    webhook_id = f"wh_{int(time.time()*1000)}"
    _webhook_registry[tenant_id].append({
        "id": webhook_id,
        "url": url,
        "events": events,
        "created_at": time.time(),
        "active": True,
    })
    return {"id": webhook_id, "url": url, "events": events, "active": True}

@app.get("/v1/webhooks")
async def list_webhooks(auth=Depends(verify_auth)):
    """List all registered webhooks."""
    tenant_id = _get_tenant_id(auth)
    hooks = _webhook_registry.get(tenant_id, [])
    return {"webhooks": [h for h in hooks if h["active"]], "count": len(hooks)}

@app.delete("/v1/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, auth=Depends(verify_auth)):
    """Delete a webhook."""
    tenant_id = _get_tenant_id(auth)
    hooks = _webhook_registry.get(tenant_id, [])
    for h in hooks:
        if h["id"] == webhook_id:
            h["active"] = False
            return {"deleted": True, "id": webhook_id}
    raise HTTPException(status_code=404, detail="Webhook not found")


def _fire_webhooks(tenant_id: str, event: str, payload: dict):
    """Fire webhooks for a given event (runs in background thread)."""
    hooks = _webhook_registry.get(tenant_id, [])
    for h in hooks:
        if h["active"] and event in h["events"]:
            def _send(url, data):
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        url, data=json.dumps(data).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req, timeout=10)
                except Exception as e:
                    logger.warning("Webhook delivery failed to %s: %s", url, e)
            threading.Thread(
                target=_send, args=(h["url"], {"event": event, **payload}),
                daemon=True,
            ).start()


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/snapshot", response_model=SnapshotResponse)
async def snapshot(agent_id: str, req: SnapshotRequest, auth=Depends(verify_auth)):
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_executor, lambda: runtime.snapshot(req.label)),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Snapshot timed out — try again when enrichment load is lower")
    return SnapshotResponse(
        label=result.label,
        keys_captured=result.keys_captured,
        latency_us=result.latency_us,
    )


@app.post("/v1/agents/{agent_id}/restore", response_model=RestoreResponse)
async def restore(agent_id: str, req: RestoreRequest, auth=Depends(verify_auth)):
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_executor, lambda: runtime.restore(req.label)),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Restore timed out — try again when enrichment load is lower")
    return RestoreResponse(
        label=result.label,
        keys_restored=result.keys_restored,
        recovery_time_us=result.recovery_time_us,
    )


@app.get("/v1/agents/{agent_id}/snapshots")
async def list_snapshots(agent_id: str, auth=Depends(verify_auth)):
    """List all snapshots for an agent with metadata."""
    backend = _get_tenant_backend(auth)
    if not backend:
        raise HTTPException(status_code=503, detail="Backend not available")

    prefix = f"agents:{agent_id}:snapshots:"
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        _executor, lambda: backend.query_prefix(prefix, limit=100)
    )

    snapshots = []
    for item in raw:
        data = item.get("data", {})
        val = data.get("value", data)
        if not isinstance(val, dict):
            continue
        label = val.get("label", "unknown")
        key_count = val.get("key_count", len(val.get("keys", {})))
        created_at = val.get("created_at", item.get("valid_from", 0))
        size_bytes = len(json.dumps(val.get("keys", {})).encode())
        snapshots.append({
            "label": label,
            "key_count": key_count,
            "created_at": created_at,
            "size_bytes": size_bytes,
            "keys_preview": list(val.get("keys", {}).keys())[:10],
        })

    snapshots.sort(key=lambda s: s["created_at"], reverse=True)
    return {"agent_id": agent_id, "snapshots": snapshots, "count": len(snapshots)}


@app.delete("/v1/agents/{agent_id}/snapshots/{label}")
async def delete_snapshot(agent_id: str, label: str, auth=Depends(verify_auth)):
    """Delete a specific snapshot."""
    backend = _get_tenant_backend(auth)
    if not backend:
        raise HTTPException(status_code=503, detail="Backend not available")

    key = f"agents:{agent_id}:snapshots:{label}"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, lambda: backend.delete(key))
    return {"deleted": True, "label": label}


# ---------------------------------------------------------------------------
# Shared Memory (with pagination)
# ---------------------------------------------------------------------------

@app.post("/v1/shared/{space}")
async def shared_write(space: str, req: SharedWriteRequest, auth=Depends(verify_auth)):
    runtime = _get_runtime(req.author_agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.share(req.key, req.value, space=space))
    return {
        "node_id": result.node_id,
        "key": req.key,
        "space": space,
        "latency_us": result.latency_us,
        "success": result.success,
    }


def _get_tenant_backend(auth):
    """Get the tenant-isolated backend for the current request.

    In dev/test mode (SYNRIX_AUTH_DISABLED=1), falls back to the daemon's
    backend so endpoints work without PostgreSQL / TenantManager.
    """
    tenant_id = _get_tenant_id(auth)
    try:
        from synrix_runtime.api.tenant import TenantManager
        return TenantManager.get_instance().get_backend(tenant_id)
    except Exception:
        # Dev/test fallback: use daemon backend directly
        auth_disabled = os.environ.get("SYNRIX_AUTH_DISABLED", "").strip() == "1"
        if auth_disabled and _daemon and hasattr(_daemon, 'backend'):
            return _daemon.backend
        return None


def _get_agents_from_backend(backend) -> list:
    """Query agents directly from a tenant backend (for SSE and listings)."""
    if not backend:
        return []
    try:
        results = backend.query_prefix("runtime:agents:", limit=500)
        agents = {}
        for r in results:
            key = r.get("key", "")
            parts = key.split(":")
            if len(parts) >= 3:
                aid = parts[2]
                if aid == "system":
                    continue
                if aid not in agents:
                    agents[aid] = {"agent_id": aid}
                if len(parts) > 3:
                    data = r.get("data", {})
                    value = data.get("value", data)
                    if isinstance(value, dict) and "value" in value:
                        value = value["value"]
                    agents[aid][parts[3]] = value
        return [a for a in agents.values() if a.get("state") != "deregistered"]
    except Exception:
        return []


@app.get("/v1/shared/{space}/detail")
async def shared_space_detail(space: str, auth=Depends(verify_auth)):
    """Get space items + changelog (used by Shared Memory dashboard tab)."""
    backend = _get_tenant_backend(auth)
    try:
        from synrix_runtime.api.shared_memory import SharedMemoryBus
        bus = SharedMemoryBus(backend)
        items = bus.get_all(space)
        changelog = bus.get_changelog(space, limit=20)
        return {"space": space, "items": items, "changelog": changelog}
    except Exception:
        return {"space": space, "items": [], "changelog": []}


@app.get("/v1/shared/{space}/{key:path}")
async def shared_read(space: str, key: str, auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    if backend:
        result = backend.read(f"shared:{space}:{key}")
        if result:
            data = result.get("data", {})
            return {"key": key, "space": space, "value": data.get("value", data), "found": True}
    return {"key": key, "space": space, "value": None, "found": False}


@app.get("/v1/shared/{space}")
async def shared_list(
    space: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    auth=Depends(verify_auth),
):
    backend = _get_tenant_backend(auth)
    if backend:
        results = backend.query_prefix(f"shared:{space}:", limit=offset + limit + 200)
        items = []
        for item in results:
            key = item.get("key", "").replace(f"shared:{space}:", "")
            if ":changelog:" not in key:
                data = item.get("data", {})
                items.append({"key": key, "value": data.get("value", data)})
        page = items[offset:offset + limit]
        return {"space": space, "items": page, "count": len(page), "total": len(items), "offset": offset}
    return {"space": space, "items": [], "count": 0, "total": 0, "offset": offset}


@app.get("/v1/shared")
async def shared_spaces(auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    if backend:
        try:
            from synrix_runtime.api.shared_memory import SharedMemoryBus
            bus = SharedMemoryBus(backend)
            return {"spaces": bus.list_spaces()}
        except Exception:
            pass
    return {"spaces": []}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/audit")
async def agent_audit(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    auth=Depends(verify_auth),
):
    backend = _get_tenant_backend(auth)
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(backend)
        events = audit.replay(agent_id)
        return {"agent_id": agent_id, "events": events[:limit], "count": len(events)}
    except Exception:
        return {"agent_id": agent_id, "events": [], "count": 0}


@app.post("/v1/agents/{agent_id}/decision")
async def log_decision(agent_id: str, req: DecisionLogRequest, auth=Depends(verify_auth)):
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, lambda: runtime.log_decision(req.decision, req.reasoning, req.context))
    return {"agent_id": agent_id, "logged": True}


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/recover")
async def recover_agent(agent_id: str, auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    if not backend:
        raise HTTPException(status_code=503, detail="Backend not available")
    loop = asyncio.get_event_loop()

    def _do_recovery():
        from synrix_runtime.core.recovery import RecoveryOrchestrator
        from dataclasses import asdict
        orch = RecoveryOrchestrator(backend)
        result = orch.full_recovery(agent_id)
        return asdict(result)

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, _do_recovery),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Recovery timed out — try again when enrichment load is lower")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recovery failed: {e}")


@app.get("/v1/recovery/history")
async def recovery_history(auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    try:
        from synrix_runtime.core.recovery import RecoveryOrchestrator
        orch = RecoveryOrchestrator(backend)
        return {
            "history": orch.get_all_recovery_history(),
            "stats": orch.get_recovery_stats(),
        }
    except Exception:
        return {"history": [], "stats": {}}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@app.get("/v1/agents/metrics")
async def all_agents_metrics(auth=Depends(verify_auth)):
    """Bulk endpoint: return pre-computed metrics for ALL agents in one call."""
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        mc = MetricsCollector(backend, tenant_id=tenant_id) if backend else MetricsCollector.get_instance()
        cached = mc.get_all_cached_metrics()
        if cached:
            return {"agents": list(cached.values()), "count": len(cached), "cached": True}
        # Fallback: no cache yet, compute inline (slow but works on first call)
        comparison = mc.get_agent_comparison()
        return {"agents": comparison, "count": len(comparison), "cached": False}
    except Exception:
        return {"agents": [], "count": 0, "cached": False}


@app.get("/v1/agents/{agent_id}/metrics")
async def agent_metrics(agent_id: str, auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    # Ownership check: verify agent belongs to this tenant
    if backend:
        state = backend.read(f"runtime:agents:{agent_id}:state")
        if state is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        mc = MetricsCollector(backend, tenant_id=tenant_id)
        m = mc.get_agent_metrics(agent_id)
        return {
            "agent_id": agent_id,
            "total_operations": m.total_operations,
            "total_writes": m.total_writes,
            "total_reads": m.total_reads,
            "total_queries": m.total_queries,
            "avg_write_latency_us": m.avg_write_latency_us,
            "avg_read_latency_us": m.avg_read_latency_us,
            "crash_count": m.crash_count,
            "recovery_count": m.recovery_count,
            "performance_score": m.performance_score,
            "uptime_seconds": m.uptime_seconds,
            "error_rate": m.error_rate,
            "memory_node_count": m.memory_node_count,
        }
    except Exception:
        return {"agent_id": agent_id, "error": "Metrics not available"}


@app.get("/v1/metrics/system")
async def system_metrics(auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        mc = MetricsCollector(backend, tenant_id=tenant_id)
        m = mc.get_system_metrics()
        # Calculate storage used by this tenant
        storage_bytes = 0
        try:
            from synrix_runtime.api.tenant import TenantManager
            tm = TenantManager.get_instance()
            if hasattr(tm, '_pool') and tm._pool:
                conn = tm._pool.getconn()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT COALESCE(SUM(octet_length(data::text)), 0) FROM nodes "
                        "WHERE tenant_id = %s AND (valid_until IS NULL OR valid_until = 0)",
                        (tenant_id,)
                    )
                    storage_bytes = cur.fetchone()[0] or 0
                    conn.commit()
                finally:
                    tm._pool.putconn(conn)
        except Exception as e:
            logger.error("Storage calculation error: %s", e)

        return {
            "total_agents": m.total_agents,
            "active_agents": m.active_agents,
            "total_operations": m.total_operations,
            "system_uptime_seconds": m.system_uptime_seconds,
            "mean_recovery_time_us": m.mean_recovery_time_us,
            "total_crashes": m.total_crashes,
            "total_recoveries": m.total_recoveries,
            "storage_bytes": storage_bytes,
            "storage_kb": round(storage_bytes / 1024, 1),
        }
    except Exception:
        return {"error": "Metrics not available"}


# ---------------------------------------------------------------------------
# Webhook Ingest — any language, any framework
# ---------------------------------------------------------------------------

class IngestEvent(_PydanticBase):
    agent_id: str
    event_type: str = "memory"  # memory, conversation, task, custom
    key: Optional[str] = None
    value: Any = None
    tags: Optional[list] = None
    metadata: Optional[dict] = None
    timestamp: Optional[float] = None


class BatchIngestRequest(_PydanticBase):
    events: List[IngestEvent]


@app.post("/v1/ingest")
async def ingest_event(event: IngestEvent, auth=Depends(verify_auth)):
    """
    Universal ingest endpoint — send events from any agent, any language.

    Works with Node.js, Go, Rust, Ruby, Java, or any HTTP client.

    Example (curl):
        curl -X POST https://api.octopoda.dev/v1/ingest \\
          -H "Authorization: Bearer sk-octopoda-..." \\
          -H "Content-Type: application/json" \\
          -d '{"agent_id": "my_agent", "key": "user_name", "value": "Alice"}'

    Example (Node.js):
        await fetch("https://api.octopoda.dev/v1/ingest", {
            method: "POST",
            headers: { "Authorization": "Bearer sk-octopoda-...", "Content-Type": "application/json" },
            body: JSON.stringify({ agent_id: "my_agent", key: "user_name", value: "Alice" })
        });
    """
    _validate_agent_id(event.agent_id)
    if event.key:
        _validate_key(event.key)

    runtime = _get_runtime(event.agent_id, auth)

    key = event.key or f"ingest:{event.event_type}:{int((event.timestamp or time.time()) * 1000)}"
    value = event.value or ""

    # Store the event as a memory
    if isinstance(value, dict):
        if event.metadata:
            value["_metadata"] = event.metadata
        if event.event_type != "memory":
            value["_event_type"] = event.event_type
    elif event.metadata or event.event_type != "memory":
        value = {
            "value": value,
            "_event_type": event.event_type,
            "_metadata": event.metadata or {},
        }

    tags = event.tags or []
    if event.event_type not in tags:
        tags.append(event.event_type)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.remember(key, value, tags=tags))

    return {
        "success": result.success,
        "agent_id": event.agent_id,
        "key": key,
        "node_id": result.node_id,
        "latency_us": result.latency_us,
    }


@app.post("/v1/ingest/batch")
async def ingest_batch(req: BatchIngestRequest, auth=Depends(verify_auth)):
    """
    Batch ingest — send multiple events in one request.

    Example:
        curl -X POST https://api.octopoda.dev/v1/ingest/batch \\
          -H "Authorization: Bearer sk-octopoda-..." \\
          -d '{"events": [
            {"agent_id": "bot", "key": "name", "value": "Alice"},
            {"agent_id": "bot", "key": "role", "value": "Engineer"}
          ]}'
    """
    if len(req.events) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 events per batch")

    results = []
    for event in req.events:
        _validate_agent_id(event.agent_id)
        if event.key:
            _validate_key(event.key)

        runtime = _get_runtime(event.agent_id, auth)
        key = event.key or f"ingest:{event.event_type}:{int((event.timestamp or time.time()) * 1000)}"
        value = event.value or ""

        tags = event.tags or []
        if event.event_type not in tags:
            tags.append(event.event_type)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, lambda r=runtime, k=key, v=value, t=tags: r.remember(k, v, tags=t))
        results.append({
            "agent_id": event.agent_id,
            "key": key,
            "success": result.success,
            "node_id": result.node_id,
        })

    return {
        "processed": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Dashboard API: SSE Streaming (real-time updates for Loveable frontend)
# ---------------------------------------------------------------------------

def _sse_event_generator(backend, tenant_id: str = "_default"):
    """Generate SSE events every second for the React dashboard."""
    last_event_ts = time.time()

    while True:
        events = []
        try:
            # Agent update (with enriched metrics) — tenant-isolated
            try:
                agents = _get_agents_from_backend(backend)
                try:
                    from synrix_runtime.monitoring.metrics import MetricsCollector
                    collector = MetricsCollector(backend, tenant_id=tenant_id)
                    for a in agents:
                        agent_id = a.get("agent_id", "")
                        try:
                            m = collector.get_agent_metrics(agent_id)
                            a["performance_score"] = m.performance_score
                            a["total_operations"] = m.total_operations
                            a["avg_write_latency_us"] = m.avg_write_latency_us
                            a["avg_read_latency_us"] = m.avg_read_latency_us
                            a["memory_node_count"] = m.memory_node_count
                            a["crash_count"] = m.crash_count
                            a["uptime_seconds"] = m.uptime_seconds
                            a["error_rate"] = m.error_rate
                        except Exception as _agent_err:
                            # Keep previous values if already set, otherwise use defaults
                            a.setdefault("performance_score", 0.0)
                            a.setdefault("total_operations", 0)
                            a.setdefault("avg_write_latency_us", 0.0)
                            a.setdefault("avg_read_latency_us", 0.0)
                            a.setdefault("memory_node_count", 0)
                            a.setdefault("crash_count", 0)
                            a.setdefault("uptime_seconds", 0.0)
                            a.setdefault("error_rate", 0.0)
                        a["status"] = a.get("state", "unknown")
                except Exception as _agent_err:
                    for a in agents:
                        a["status"] = a.get("state", "unknown")
                events.append(("agent_update", {"agents": agents, "timestamp": time.time()}))
            except Exception as _agent_err:
                pass  # Keep last known agents on error — never send empty list

            # System metrics — tenant-isolated
            try:
                from synrix_runtime.monitoring.metrics import MetricsCollector
                collector = MetricsCollector(backend, tenant_id=tenant_id)
                system = collector.get_system_metrics()
                events.append(("metrics_update", {
                    "total_agents": system.total_agents,
                    "active_agents": system.active_agents,
                    "total_operations": system.total_operations,
                    "mean_recovery_time_us": system.mean_recovery_time_us,
                    "total_crashes": system.total_crashes,
                    "total_recoveries": system.total_recoveries,
                    "uptime_seconds": system.system_uptime_seconds,
                    "timestamp": time.time(),
                }))
            except Exception as _agent_err:
                pass

            # Anomalies
            try:
                from synrix_runtime.monitoring.anomaly import AnomalyDetector
                detector = AnomalyDetector(backend)
                anomalies = detector.get_all_anomalies()
                if anomalies:
                    events.append(("anomaly_alert", {"anomalies": anomalies[:5], "timestamp": time.time()}))
            except Exception as _agent_err:
                pass

            # Recent recoveries
            try:
                from synrix_runtime.core.recovery import RecoveryOrchestrator
                orchestrator = RecoveryOrchestrator(backend)
                recoveries = orchestrator.get_all_recovery_history()
                recent = [r for r in recoveries if isinstance(r, dict) and r.get("timestamp", 0) > last_event_ts - 10]
                if recent:
                    events.append(("recovery_event", {"recoveries": recent, "timestamp": time.time()}))
            except Exception as _agent_err:
                pass

            # Heartbeat
            events.append(("system_heartbeat", {"alive": True, "timestamp": time.time()}))

            last_event_ts = time.time()

            for event_type, data in events:
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

        except GeneratorExit:
            break
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        time.sleep(5)


@app.get("/v1/stream/events")
async def sse_stream(auth=Depends(verify_auth)):
    """
    Server-Sent Events stream for real-time dashboard updates.

    Events emitted every ~1 second:
    - agent_update: all agents with health scores, metrics, state
    - metrics_update: system-wide metrics
    - anomaly_alert: active anomalies (crash loops, latency spikes)
    - recovery_event: recent crash recoveries
    - system_heartbeat: keepalive ping

    Usage (JavaScript):
        const es = new EventSource('/v1/stream/events', {
            headers: { 'Authorization': 'Bearer sk-octopoda-...' }
        });
        es.addEventListener('agent_update', (e) => {
            const data = JSON.parse(e.data);
            updateAgentList(data.agents);
        });
    """
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    return StreamingResponse(
        _sse_event_generator(backend, tenant_id=tenant_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Dashboard API: Anomaly Detection
# ---------------------------------------------------------------------------

@app.get("/v1/anomalies")
async def get_anomalies(auth=Depends(verify_auth)):
    """Get all active anomalies across agents (crash loops, latency spikes, idle agents)."""
    backend = _get_tenant_backend(auth)
    try:
        from synrix_runtime.monitoring.anomaly import AnomalyDetector
        detector = AnomalyDetector(backend)
        return {"anomalies": detector.get_all_anomalies()}
    except Exception:
        return {"anomalies": []}


# ---------------------------------------------------------------------------
# Dashboard API: Metrics Time-Series (for Chart.js graphs)
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/metrics/timeseries")
async def agent_metrics_timeseries(
    agent_id: str,
    minutes: int = Query(default=60, ge=1, le=1440),
    type: str = Query(default="write", description="Metric type: write, read, query"),
    auth=Depends(verify_auth),
):
    """
    Get time-series metrics for Chart.js performance graphs.

    Returns data points over the last N minutes for the specified metric type.
    Used by the Performance tab to render latency/throughput charts.
    """
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector(backend, tenant_id=tenant_id)
        series = collector.get_time_series(agent_id, type, minutes)
        return {"agent_id": agent_id, "type": type, "minutes": minutes, "series": series}
    except Exception:
        return {"agent_id": agent_id, "type": type, "minutes": minutes, "series": []}


@app.get("/v1/metrics/timeseries")
async def system_metrics_timeseries(
    agent_id: str = Query(default="", description="Agent ID (empty for system-wide)"),
    minutes: int = Query(default=60, ge=1, le=1440),
    type: str = Query(default="write", description="Metric type: write, read, query"),
    auth=Depends(verify_auth),
):
    """System-wide or per-agent time-series metrics."""
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector(backend, tenant_id=tenant_id)
        series = collector.get_time_series(agent_id, type, minutes)
        return {"agent_id": agent_id, "type": type, "minutes": minutes, "series": series}
    except Exception:
        return {"agent_id": agent_id, "type": type, "minutes": minutes, "series": []}


# ---------------------------------------------------------------------------
# Dashboard API: Global Audit Timeline + Explain Decision
# ---------------------------------------------------------------------------

@app.get("/v1/audit/timeline")
async def audit_timeline(
    limit: int = Query(default=50, ge=1, le=500),
    auth=Depends(verify_auth),
):
    """
    Global audit timeline — all events across all agents, newest first.

    Used by the Audit tab to show a chronological view of everything
    happening across the system.
    """
    backend = _get_tenant_backend(auth)
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(backend)
        return {"events": audit.get_global_timeline(limit), "limit": limit}
    except Exception:
        return {"events": [], "limit": limit}


@app.get("/v1/audit/explain/{agent_id}/{timestamp}")
async def audit_explain(agent_id: str, timestamp: float, auth=Depends(verify_auth)):
    """
    Explain a decision — show what the agent knew at that exact moment.

    Returns the full causal chain: what was queried, what was decided,
    what was written, and the memory snapshot at decision time.
    """
    backend = _get_tenant_backend(auth)
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(backend)
        return audit.explain_decision(agent_id, timestamp)
    except Exception:
        return {"agent_id": agent_id, "timestamp": timestamp, "explanation": None}


@app.get("/v1/agents/{agent_id}/audit/replay")
async def agent_audit_replay(
    agent_id: str,
    from_ts: Optional[float] = Query(default=None, alias="from", description="Start timestamp"),
    to_ts: Optional[float] = Query(default=None, alias="to", description="End timestamp"),
    auth=Depends(verify_auth),
):
    """Replay agent audit events within a time range."""
    backend = _get_tenant_backend(auth)
    try:
        from synrix_runtime.monitoring.audit import AuditSystem
        audit = AuditSystem(backend)
        events = audit.replay(agent_id, from_ts=from_ts, to_ts=to_ts)
        return {"agent_id": agent_id, "events": events, "count": len(events)}
    except Exception:
        return {"agent_id": agent_id, "events": [], "count": 0}


# ---------------------------------------------------------------------------
# Dashboard API: Performance Breakdown
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/performance")
async def agent_performance(agent_id: str, auth=Depends(verify_auth)):
    """
    Detailed performance breakdown for an agent.

    Returns per-operation-type latency stats, used by the Performance tab
    for detailed charts and analysis.
    """
    backend = _get_tenant_backend(auth)
    tenant_id = _get_tenant_id(auth)
    try:
        from synrix_runtime.monitoring.metrics import MetricsCollector
        collector = MetricsCollector(backend, tenant_id=tenant_id)
        m = collector.get_agent_metrics(agent_id)
        breakdown = collector.get_performance_breakdown(agent_id)
        return {
            "agent_id": agent_id,
            "metrics": {
                "total_operations": m.total_operations,
                "total_writes": m.total_writes,
                "total_reads": m.total_reads,
                "total_queries": m.total_queries,
                "avg_write_latency_us": m.avg_write_latency_us,
                "avg_read_latency_us": m.avg_read_latency_us,
                "avg_query_latency_us": m.avg_query_latency_us,
                "crash_count": m.crash_count,
                "recovery_count": m.recovery_count,
                "performance_score": m.performance_score,
                "uptime_seconds": m.uptime_seconds,
                "error_rate": m.error_rate,
                "memory_node_count": m.memory_node_count,
                "operations_per_minute": m.operations_per_minute,
            },
            "breakdown": breakdown,
        }
    except Exception:
        return {"agent_id": agent_id, "metrics": {}, "breakdown": {}}


# ---------------------------------------------------------------------------
# Raw operations
# ---------------------------------------------------------------------------

@app.post("/v1/raw/write")
async def raw_write(req: RawWriteRequest, auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    if backend:
        start = time.perf_counter_ns()
        node_id = backend.write(req.key, req.value, req.metadata)
        latency_us = (time.perf_counter_ns() - start) / 1000
        return {"node_id": node_id, "key": req.key, "latency_us": round(latency_us, 1)}
    raise HTTPException(status_code=503, detail="Backend not available")


@app.get("/v1/raw/read/{key:path}")
async def raw_read(key: str, auth=Depends(verify_auth)):
    backend = _get_tenant_backend(auth)
    if backend:
        start = time.perf_counter_ns()
        result = backend.read(key)
        latency_us = (time.perf_counter_ns() - start) / 1000
        if result:
            return {"key": key, "data": result.get("data", {}), "latency_us": round(latency_us, 1), "found": True}
        return {"key": key, "data": None, "latency_us": round(latency_us, 1), "found": False}
    raise HTTPException(status_code=503, detail="Backend not available")


@app.get("/v1/raw/query")
async def raw_query(
    prefix: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    auth=Depends(verify_auth),
):
    backend = _get_tenant_backend(auth)
    if backend:
        start = time.perf_counter_ns()
        results = backend.query_prefix(prefix, limit=limit)
        latency_us = (time.perf_counter_ns() - start) / 1000
        return {"items": results, "count": len(results), "latency_us": round(latency_us, 1)}
    raise HTTPException(status_code=503, detail="Backend not available")


# ---------------------------------------------------------------------------
# License Info
# ---------------------------------------------------------------------------

@app.get("/v1/license")
async def license_info(auth=Depends(verify_auth)):
    """Check current license tier, agent count, and limits."""
    backend = _get_tenant_backend(auth)
    agents_list = _get_agents_from_backend(backend)
    tenant_id = _get_tenant_id(auth)
    plan = auth.get("plan", "free") if auth else "free"
    max_agents = auth.get("max_agents", 100) if auth else 100
    max_mem = auth.get("max_memories_per_agent", 100000) if auth else 100000
    return {
        "tier": plan,
        "max_agents": max_agents,
        "max_memories_per_agent": max_mem,
        "current_agents": len(agents_list),
        "agents": [
            {"agent_id": a.get("agent_id", ""), "state": a.get("state", "unknown")}
            for a in agents_list
        ],
    }


# ---------------------------------------------------------------------------
# API Key Management (admin only)
# ---------------------------------------------------------------------------

@app.post("/v1/admin/keys")
async def create_api_key(auth=Depends(verify_auth)):
    """Create a new API key for the authenticated tenant (own account only)."""
    tenant_id = _get_tenant_id(auth)
    if _auth_manager:
        raw_key = _auth_manager.create_key(tenant_id=tenant_id)
        return {"api_key": raw_key, "tenant_id": tenant_id, "warning": "Save this key - it won't be shown again"}
    raise HTTPException(status_code=503, detail="Auth not configured")


# ---------------------------------------------------------------------------
# Per-Tenant LLM Settings
# ---------------------------------------------------------------------------
# In-memory tenant settings (persisted to tenant DB on write)
_tenant_settings: dict = {}  # tenant_id -> {llm_provider, openai_api_key, ...}
_tenant_settings_ts = dict()
_SETTINGS_CACHE_TTL = 30

# Platform free tier: 100 LLM extractions per tenant before downgrade to embedding-only
_PLATFORM_FREE_LIMIT = int(os.environ.get("OCTOPODA_PLATFORM_FREE_LIMIT", "100"))

# ---------------------------------------------------------------------------
# Latency & Error Anomaly Detection (in-memory, per-agent)
# ---------------------------------------------------------------------------
# Tracks recent latencies and errors per agent to detect spikes and high error rates.
# Zero config — runs automatically on every API call.

_latency_tracker: dict = {}  # agent_id -> [{"latency_us": float, "time": float}, ...]
_error_tracker: dict = {}    # agent_id -> [{"time": float, "success": bool}, ...]
_latency_tracker_lock = threading.Lock()

_LATENCY_WINDOW = 300       # 5 minutes
_LATENCY_SPIKE_FACTOR = 5   # alert if recent mean > 5x baseline mean
_LATENCY_MIN_SAMPLES = 10   # need at least 10 samples to establish baseline
_ERROR_WINDOW = 300          # 5 minutes
_ERROR_RATE_THRESHOLD = 0.20 # alert if >20% of calls fail in window
_ERROR_MIN_SAMPLES = 5       # need at least 5 calls to trigger


def _track_latency_and_errors(agent_id: str, latency_us: float, success: bool, runtime):
    """Track latency and error rate, write alerts if anomalous.
    Uses tenant-scoped keys to prevent cross-tenant data mixing."""
    now = time.time()
    cutoff = now - _LATENCY_WINDOW

    # Scope tracker keys by tenant to prevent cross-tenant mixing
    tenant_id = getattr(runtime, 'tenant_id', '_default') if runtime else '_default'
    tracker_key = f"{tenant_id}:{agent_id}"

    with _latency_tracker_lock:
        # Track latency
        if tracker_key not in _latency_tracker:
            _latency_tracker[tracker_key] = []
        entries = _latency_tracker[tracker_key]
        entries.append({"latency_us": latency_us, "time": now})
        # Prune old entries
        _latency_tracker[tracker_key] = [e for e in entries if e["time"] >= cutoff]
        recent_latencies = _latency_tracker[tracker_key]

        # Track errors
        if tracker_key not in _error_tracker:
            _error_tracker[tracker_key] = []
        err_entries = _error_tracker[tracker_key]
        err_entries.append({"time": now, "success": success})
        _error_tracker[tracker_key] = [e for e in err_entries if e["time"] >= cutoff]
        recent_errors = _error_tracker[tracker_key]

    # Check latency spike
    if len(recent_latencies) >= _LATENCY_MIN_SAMPLES:
        values = [e["latency_us"] for e in recent_latencies]
        # Use first half as baseline, second half as recent
        mid = len(values) // 2
        if mid >= 3:
            baseline_mean = sum(values[:mid]) / mid
            recent_mean = sum(values[mid:]) / (len(values) - mid)
            if baseline_mean > 0 and recent_mean > baseline_mean * _LATENCY_SPIKE_FACTOR:
                try:
                    alert_key = f"alerts:{agent_id}:latency_spike:{int(now)}"
                    alert_data = {
                        "agent_id": agent_id,
                        "type": "latency_spike",
                        "severity": "warning",
                        "detail": f"Avg latency {recent_mean:.0f}us is {recent_mean/baseline_mean:.1f}x above baseline {baseline_mean:.0f}us",
                        "current_value": recent_mean,
                        "threshold": baseline_mean * _LATENCY_SPIKE_FACTOR,
                        "timestamp": now,
                    }
                    runtime.remember(alert_key, alert_data)
                except Exception as _agent_err:
                    pass

    # Check error rate
    if len(recent_errors) >= _ERROR_MIN_SAMPLES:
        failures = sum(1 for e in recent_errors if not e["success"])
        error_rate = failures / len(recent_errors)
        if error_rate >= _ERROR_RATE_THRESHOLD:
            try:
                alert_key = f"alerts:{agent_id}:high_error_rate:{int(now)}"
                alert_data = {
                    "agent_id": agent_id,
                    "type": "high_error_rate",
                    "severity": "critical",
                    "detail": f"Error rate {error_rate:.0%} ({failures}/{len(recent_errors)} calls failed in last 5 min)",
                    "current_value": error_rate,
                    "threshold": _ERROR_RATE_THRESHOLD,
                    "timestamp": now,
                }
                runtime.remember(alert_key, alert_data)
            except Exception as _agent_err:
                pass

# ---------------------------------------------------------------------------
# API key encryption at rest (AES-128 via Fernet)
# ---------------------------------------------------------------------------
_SENSITIVE_KEYS = ("openai_api_key", "anthropic_api_key")

def _get_fernet():
    """Get Fernet cipher for encrypting tenant API keys at rest."""
    try:
        from cryptography.fernet import Fernet
        import base64, hashlib
        # Derive from server secret (env var or auto-generated file)
        secret = os.environ.get("OCTOPODA_ENCRYPTION_KEY", "")
        if not secret:
            key_path = os.path.join(os.path.expanduser("~"), ".synrix", ".encryption_key")
            if os.path.exists(key_path):
                with open(key_path, "r") as f:
                    secret = f.read().strip()
            else:
                import secrets as _secrets
                secret = _secrets.token_urlsafe(48)
                os.makedirs(os.path.dirname(key_path), exist_ok=True)
                with open(key_path, "w") as f:
                    f.write(secret)
                os.chmod(key_path, 0o600)
        # Fernet needs a 32-byte URL-safe base64-encoded key
        derived = hashlib.sha256(secret.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(derived)
        return Fernet(fernet_key)
    except ImportError:
        return None  # cryptography not installed — fall back to plaintext

_fernet_cipher = _get_fernet()

def _encrypt_settings(settings: dict) -> dict:
    """Encrypt sensitive API keys before storing to DB."""
    if not _fernet_cipher:
        return settings
    out = dict(settings)
    for key in _SENSITIVE_KEYS:
        val = out.get(key)
        if val and not val.startswith("enc:"):
            out[key] = "enc:" + _fernet_cipher.encrypt(val.encode()).decode()
    return out

def _decrypt_settings(settings: dict) -> dict:
    """Decrypt sensitive API keys after loading from DB."""
    if not _fernet_cipher:
        return settings
    out = dict(settings)
    for key in _SENSITIVE_KEYS:
        val = out.get(key)
        if val and val.startswith("enc:"):
            try:
                out[key] = _fernet_cipher.decrypt(val[4:].encode()).decode()
            except Exception as _agent_err:
                out[key] = ""  # corrupted — clear it
    return out


def _get_tenant_settings(tenant_id: str) -> dict:
    """Get tenant LLM settings from cache or DB.

    New tenants default to 'platform' provider (free tier with 100 LLM extractions).
    """
    if tenant_id in _tenant_settings and (time.time() - _tenant_settings_ts.get(tenant_id, 0)) < _SETTINGS_CACHE_TTL:
        return _tenant_settings[tenant_id]
    # Try to load from tenant DB
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        backend = tm.get_backend(tenant_id)
        result = backend.read("__tenant_settings__")
        if result and "data" in result:
            settings = result["data"].get("value", {})
            # Unwrap nested "value" keys caused by earlier double-wrap bug
            while isinstance(settings, dict) and "value" in settings and "llm_provider" not in settings:
                settings = settings["value"]
            if isinstance(settings, dict) and "llm_provider" in settings:
                # Clean: strip leftover nested "value" key to stop DB bloat
                clean = {k: v for k, v in settings.items() if k != "value"}
                # Decrypt any encrypted API keys
                clean = _decrypt_settings(clean)
                _tenant_settings[tenant_id] = clean
                # Re-save clean+encrypted version to fix the DB entry
                try:
                    backend.write("__tenant_settings__", _encrypt_settings(clean), metadata={"type": "settings"})
                except Exception as _agent_err:
                    pass
                return clean
    except Exception:
        pass
    # New tenant — default to platform free tier
    defaults = {"llm_provider": "platform", "platform_extractions_used": 0}
    _tenant_settings[tenant_id] = defaults
    return defaults


_platform_usage_lock = threading.Lock()

_ADMIN_TENANTS = {"bf1506e1e2bbc462", "1f3442be42cfd12f"}  # platform owner accounts

def _check_and_increment_platform_usage(tenant_id: str) -> bool:
    """Atomically check and increment platform free tier counter.

    ATOMICITY: Uses a single UPDATE ... RETURNING against platform_usage
    so that multiple uvicorn workers cannot double-count or overwrite each
    other. The previous implementation used an in-process threading.Lock,
    which did not protect across workers — users could bypass the cap by
    issuing parallel writes that hit different workers.

    Returns True if extraction is allowed, False if limit exceeded.
    Everyone gets 100 free extractions, then must add their own API key.
    Only admin (platform owner) accounts bypass the limit.
    """
    if tenant_id in _ADMIN_TENANTS:
        return True

    # Fast-path: if we've cached that this tenant is off platform, skip the
    # DB round-trip. Provider changes are rare (once per 100 writes at most).
    cached = _tenant_settings.get(tenant_id)
    if cached and cached.get("llm_provider") not in (None, "platform"):
        return True

    # Atomic increment — one SQL statement, safe across workers.
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        conn = tm._conn()
        try:
            cur = conn.cursor()
            # UPSERT with returning — postgres guarantees the read is of the
            # post-update value. Two workers each running this get distinct
            # increments; neither overwrites the other.
            cur.execute(
                """
                INSERT INTO platform_usage (tenant_id, used)
                VALUES (%s, 1)
                ON CONFLICT (tenant_id) DO UPDATE
                   SET used = platform_usage.used + 1,
                       updated_at = NOW()
                RETURNING used
                """,
                (tenant_id,),
            )
            used = cur.fetchone()[0]
            conn.commit()
        finally:
            tm._release(conn)
    except Exception as e:
        logger.error("platform_usage increment failed | tenant=%s: %s", tenant_id, e)
        _capture_silent(e, op="platform_usage_increment", tenant_id=tenant_id)
        # Fail open: don't block a legitimate write because our counter DB is down.
        return True

    if used > _PLATFORM_FREE_LIMIT:
        # Exceeded — downgrade provider to 'none' once (idempotent across workers)
        settings = _get_tenant_settings(tenant_id)
        if settings.get("llm_provider") == "platform":
            settings["llm_provider"] = "none"
            _save_tenant_settings(tenant_id, settings)
            logger.info("Tenant %s hit platform cap (%d/%d) — llm_provider set to 'none'",
                        tenant_id, used, _PLATFORM_FREE_LIMIT)
        return False
    return True


def _read_platform_usage(tenant_id: str) -> int:
    """Read the current platform_usage counter without incrementing."""
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        conn = tm._conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT used FROM platform_usage WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            return row[0] if row else 0
        finally:
            tm._release(conn)
    except Exception as e:
        logger.warning("platform_usage read failed | tenant=%s: %s", tenant_id, e)
        return 0

def _increment_platform_usage(tenant_id: str):
    """Increment platform extraction counter, raise 402 if over quota.

    Users who have added their own LLM provider key bypass this entirely
    (cached fast-path in _check_and_increment_platform_usage). Admin
    tenants also bypass. Over-quota users get a clear 402 with a pointer
    to add their own key in Settings.
    """
    allowed = _check_and_increment_platform_usage(tenant_id)
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Free platform AI extractions exhausted ({_PLATFORM_FREE_LIMIT}/{_PLATFORM_FREE_LIMIT}). "
                f"Add your own OpenAI or Anthropic key in Settings to continue, "
                f"or upgrade at https://octopodas.com/pricing."
            ),
        )


# ---------------------------------------------------------------------------
# Tenant memory cap enforcement (cloud-side, per-tenant, DB-backed)
# ---------------------------------------------------------------------------

# Short cache so we don't hit Postgres on every single write. 30 seconds means
# a tenant could briefly exceed their cap by a handful of writes across
# workers, which is acceptable (we re-check on cache miss + every 30s).
_memory_cap_cache: Dict[str, Tuple[float, int, int]] = {}  # tenant_id -> (ts, current, limit)
_MEMORY_CAP_TTL = 30.0


def _enforce_tenant_memory_cap(tenant_id: str):
    """Raise HTTPException(402) if the tenant has hit their memory quota.

    Runs per-tenant (not per-agent) so multi-agent tenants share one cap, which
    matches the pricing page. Counts only user-visible memory nodes
    (the `agents:{agent_id}:*` keyspace), not metadata/snapshot/fact-embedding
    side-effect rows. A 30-second cache prevents the DB count from being run
    on every single remember() call.
    """
    now = time.time()
    cached = _memory_cap_cache.get(tenant_id)
    if cached and (now - cached[0]) < _MEMORY_CAP_TTL:
        current, limit = cached[1], cached[2]
        if limit > 0 and current >= limit:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Memory cap reached: {current:,} / {limit:,} on your current plan. "
                    f"Upgrade at https://octopodas.com/pricing to continue writing."
                ),
            )
        return

    # Cache miss or stale — query the DB
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    conn = tm._conn()
    try:
        cur = conn.cursor()
        # Ensure tenant_id is set for RLS so the count is naturally tenant-scoped
        cur.execute("SET LOCAL app.tenant_id = %s", (tenant_id,))
        # Count only user-visible memory rows (keys under agents:*).
        # Excludes runtime state, snapshots, audit entries.
        cur.execute("""
            SELECT COUNT(*) FROM nodes
             WHERE tenant_id = %s
               AND name LIKE 'agents:%%'
               AND name NOT LIKE 'agents:%%:snapshots:%%'
               AND name NOT LIKE 'agents:%%:audit:%%'
               AND name NOT LIKE 'agents:%%:state'
               AND name NOT LIKE 'agents:%%:heartbeat'
               AND valid_until = 0
        """, (tenant_id,))
        current = int(cur.fetchone()[0])
        # Look up the tenant's configured limit
        cur.execute("SELECT max_memories FROM tenants WHERE tenant_id = %s", (tenant_id,))
        row = cur.fetchone()
        limit = int(row[0]) if row and row[0] is not None else 5000
    finally:
        tm._release(conn)

    _memory_cap_cache[tenant_id] = (now, current, limit)

    if limit > 0 and current >= limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Memory cap reached: {current:,} / {limit:,} on your current plan. "
                f"Upgrade at https://octopodas.com/pricing to continue writing."
            ),
        )


def _save_tenant_settings(tenant_id: str, settings: dict):
    """Persist tenant settings to DB (API keys encrypted at rest)."""
    _tenant_settings[tenant_id] = settings  # in-memory cache holds plaintext
    _tenant_settings_ts[tenant_id] = time.time()  # refresh cache TTL
    try:
        from synrix_runtime.api.tenant import TenantManager
        tm = TenantManager.get_instance()
        backend = tm.get_backend(tenant_id)
        backend.write("__tenant_settings__", _encrypt_settings(settings), metadata={"type": "settings"})
    except Exception:
        pass


@app.get("/v1/settings")
async def get_settings(auth=Depends(verify_auth)):
    """Get current LLM and feature settings for your account."""
    tenant_id = _get_tenant_id(auth)
    settings = _get_tenant_settings(tenant_id)
    # Never return full API keys — mask them
    safe = dict(settings)
    for key in ("openai_api_key", "anthropic_api_key"):
        if key in safe and safe[key]:
            safe[key] = safe[key][:8] + "..." + safe[key][-4:]
    provider = safe.get("llm_provider", "platform")
    result = {
        "llm_provider": provider,
        "openai_api_key": safe.get("openai_api_key", ""),
        "openai_model": safe.get("openai_model", "gpt-4o-mini"),
        "openai_base_url": safe.get("openai_base_url", "https://api.openai.com/v1"),
        "anthropic_api_key": safe.get("anthropic_api_key", ""),
        "anthropic_model": safe.get("anthropic_model", "claude-haiku-4-5-20251001"),
        "ollama_model": safe.get("ollama_model", "llama3.2"),
    }
    # Show platform free tier usage if applicable — read from atomic counter
    # (platform_usage table) rather than cached settings, so multi-worker
    # increments are accurate for display.
    if provider == "platform":
        used = _read_platform_usage(tenant_id)
        result["platform_extractions_used"] = used
        result["platform_extractions_limit"] = _PLATFORM_FREE_LIMIT
        result["platform_extractions_remaining"] = max(0, _PLATFORM_FREE_LIMIT - used)

    # Memory feature settings
    result["ttl_auto_cleanup"] = settings.get("ttl_auto_cleanup", True)
    result["conflict_detection"] = settings.get("conflict_detection", True)
    result["conflict_sensitivity"] = settings.get("conflict_sensitivity", 0.85)

    # Cost tracking model selection
    result["llm_model"] = settings.get("llm_model", "unknown")
    try:
        from synrix_runtime.monitoring.cost_models import get_model_names
        result["available_models"] = get_model_names()
    except Exception:
        result["available_models"] = []

    return result


@app.put("/v1/settings")
async def update_settings(req: dict, auth=Depends(verify_auth)):
    """Update LLM provider and API keys for your account.

    Supported fields:
        llm_provider: "ollama" | "openai" | "anthropic" | "none"
        openai_api_key: your OpenAI API key (or any OpenAI-compatible provider key)
        openai_model: model name (default: gpt-4o-mini)
        openai_base_url: API base URL (default: https://api.openai.com/v1)
            — Use this for Groq, Together, Mistral, or any OpenAI-compatible API
        anthropic_api_key: your Anthropic API key
        anthropic_model: model name (default: claude-haiku-4-5-20251001)
        ollama_model: Ollama model name (default: llama3.2)
    """
    tenant_id = _get_tenant_id(auth)
    settings = _get_tenant_settings(tenant_id)

    allowed_fields = {
        "llm_provider", "openai_api_key", "openai_model", "openai_base_url",
        "anthropic_api_key", "anthropic_model", "ollama_model",
        "ttl_auto_cleanup", "conflict_detection", "conflict_sensitivity",
        "llm_model",
    }
    allowed_providers = {"openai", "anthropic", "none", "platform", "ollama"}

    for key, value in req.items():
        if key in allowed_fields:
            if key == "llm_provider" and value not in allowed_providers:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid provider '{value}'. Must be one of: {', '.join(allowed_providers)}"
                )
            # SSRF protection: validate openai_base_url
            if key == "openai_base_url" and value:
                from urllib.parse import urlparse
                parsed = urlparse(str(value))
                if parsed.scheme not in ("https", "http"):
                    raise HTTPException(status_code=422, detail="base_url must be http(s)")
                hostname = (parsed.hostname or "").lower()
                if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "") \
                   or hostname.startswith("10.") or hostname.startswith("172.") \
                   or hostname.startswith("192.168.") or hostname.startswith("169.254."):
                    raise HTTPException(status_code=422, detail="base_url must point to a public host")
            settings[key] = value

    _save_tenant_settings(tenant_id, settings)

    # Evict cached runtimes for this tenant so they pick up the new LLM config
    keys_to_evict = [k for k in _agent_runtimes if k.startswith(f"{tenant_id}:")]
    for k in keys_to_evict:
        _agent_runtimes.pop(k, None)

    return {"updated": True, "llm_provider": settings.get("llm_provider", "platform")}


# ---------------------------------------------------------------------------
# Memory Management (Forget / Consolidate / Health)
# ---------------------------------------------------------------------------

@app.delete("/v1/agents/{agent_id}/memory/{key:path}")
async def forget_memory(agent_id: str, key: str, auth=Depends(verify_auth)):
    """Explicitly forget (delete) a specific memory."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.forget(key))
    return result


@app.post("/v1/agents/{agent_id}/forget/stale")
async def forget_stale(agent_id: str, req: dict = None, auth=Depends(verify_auth)):
    """Forget memories older than max_age_seconds. Preserves critical memories."""
    req = req or {}
    max_age = req.get("max_age_seconds", 604800)  # default 7 days
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.forget_stale(max_age))
    return result


@app.post("/v1/agents/{agent_id}/forget/tag")
async def forget_by_tag(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Forget all memories with a specific tag."""
    tag = req.get("tag")
    if not tag:
        raise HTTPException(status_code=422, detail="tag required")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.forget_by_tag(tag))
    return result


@app.post("/v1/agents/{agent_id}/consolidate")
async def consolidate_memories(agent_id: str, req: dict = None, auth=Depends(verify_auth)):
    """Find and optionally merge duplicate memories.

    Pass dry_run=true (default) to preview without changing anything.
    """
    req = req or {}
    threshold = req.get("similarity_threshold", 0.90)
    dry_run = req.get("dry_run", True)
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor,
        lambda: runtime.consolidate(similarity_threshold=threshold, dry_run=dry_run),
    )
    return result


@app.get("/v1/agents/{agent_id}/memory/health")
async def memory_health(agent_id: str, auth=Depends(verify_auth)):
    """Get a health assessment of this agent's memory (score 0-100)."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.memory_health())
    return result


@app.get("/v1/agents/{agent_id}/recall/{key:path}/confidence")
async def recall_with_confidence(agent_id: str, key: str, auth=Depends(verify_auth)):
    """Recall a memory with confidence score based on age and access patterns."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.recall_with_confidence(key))
    return {
        "found": result.found,
        "key": key,
        "value": result.value,
        "latency_us": result.latency_us,
    }


# ---------------------------------------------------------------------------
# Shared Memory (Safe Write with Conflict Detection)
# ---------------------------------------------------------------------------

@app.post("/v1/shared/{space}/safe")
async def share_safe(space: str, req: dict, auth=Depends(verify_auth)):
    """Write to shared memory with conflict detection."""
    key = req.get("key")
    value = req.get("value")
    agent_id = req.get("author_agent_id", "unknown")
    if not key or value is None:
        raise HTTPException(status_code=422, detail="key and value required")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor,
        lambda: runtime.share_safe(key, value, space=space),
    )
    return result


@app.get("/v1/shared/{space}/conflicts")
async def shared_conflicts(space: str, limit: int = Query(default=20, ge=1, le=100),
                           auth=Depends(verify_auth)):
    """List recent write conflicts in a shared memory space."""
    # Need any runtime to query the backend
    tenant_id = _get_tenant_id(auth)
    backend = _get_tenant_backend(auth)
    results = backend.query_prefix(f"shared:{space}:conflicts:", limit=limit)
    conflicts = []
    for r in results:
        data = r.get("data", {})
        val = data.get("value", data)
        if isinstance(val, dict):
            conflicts.append(val)
    conflicts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"space": space, "conflicts": conflicts, "count": len(conflicts)}


# ---------------------------------------------------------------------------
# Billing (Stripe)
# ---------------------------------------------------------------------------

@app.post("/v1/billing/checkout")
async def billing_checkout(req: dict, auth=Depends(verify_auth)):
    """Create a Stripe Checkout session to upgrade plan."""
    from synrix_runtime.api.billing import create_checkout_session
    tenant_id = _get_tenant_id(auth)
    email = auth.get("email", "")
    name = auth.get("first_name", "")
    plan = req.get("plan", "pro")
    billing = req.get("billing", "monthly")
    success_url = req.get("success_url")
    cancel_url = req.get("cancel_url")
    if plan not in ("pro", "business", "scale"):
        raise HTTPException(status_code=422, detail="Plan must be pro, business, or scale")
    if billing not in ("monthly", "annual"):
        raise HTTPException(status_code=422, detail="Billing must be monthly or annual")
    result = create_checkout_session(tenant_id, email, plan, billing, name, success_url, cancel_url)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/v1/billing/portal")
async def billing_portal(auth=Depends(verify_auth)):
    """Create a Stripe Customer Portal session for managing subscription."""
    from synrix_runtime.api.billing import create_portal_session
    tenant_id = _get_tenant_id(auth)
    email = auth.get("email", "")
    result = create_portal_session(tenant_id, email)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/v1/billing/status")
async def billing_status(auth=Depends(verify_auth)):
    """Get current subscription status."""
    from synrix_runtime.api.billing import get_subscription_status
    tenant_id = _get_tenant_id(auth)
    email = auth.get("email", "")
    return get_subscription_status(tenant_id, email)


@app.get("/v1/billing/plans")
async def billing_plans():
    """List available plans and pricing (no auth required)."""
    from synrix_runtime.api.billing import get_plans
    return {"plans": get_plans()}


@app.post("/v1/billing/webhook")
async def billing_webhook(request: Request):
    """Stripe webhook handler. Verifies signature and processes events."""
    from synrix_runtime.api.billing import handle_webhook_event
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    result = handle_webhook_event(payload, signature)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Advanced Loop Detection v2
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/loops/status")
async def get_loop_status(agent_id: str, auth=Depends(verify_auth)):
    """Get comprehensive loop detection status with multi-signal analysis."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.get_loop_status())

    # Persist cumulative cost savings when a loop is detected
    try:
        if result.get("severity") in ("orange", "red") and result.get("cost"):
            tenant_id = _get_tenant_id(auth)
            backend = runtime.backend
            cost_key = f"metrics:{tenant_id}:cost_saved"
            existing = backend.read(cost_key)
            existing_data = {}
            if existing:
                val = existing.get("data", existing)
                if isinstance(val, dict) and "value" in val:
                    val = val["value"]
                if isinstance(val, dict):
                    existing_data = val

            import time as _time
            new_saved = result["cost"].get("estimated_saved", 0)
            new_wasted = result["cost"].get("estimated_wasted", 0)
            existing_data["total_saved"] = existing_data.get("total_saved", 0) + new_saved
            existing_data["total_wasted"] = existing_data.get("total_wasted", 0) + new_wasted
            existing_data["loops_caught"] = existing_data.get("loops_caught", 0) + 1
            if "since" not in existing_data:
                existing_data["since"] = _time.time()
            backend.write(cost_key, existing_data)
    except Exception:
        pass

    return result


@app.get("/v1/agents/{agent_id}/loops/history")
async def get_loop_history(agent_id: str,
                           hours: int = Query(default=24, ge=1, le=168),
                           auth=Depends(verify_auth)):
    """Get loop detection alert history for pattern analysis."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.get_loop_history(hours))
    return result


# ---------------------------------------------------------------------------
# Agent Messaging
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/messages/send")
async def send_message(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Send a message to another agent."""
    to_agent = req.get("to_agent")
    message = req.get("message")
    message_type = req.get("message_type", "info")
    space = req.get("space", "global")
    if not to_agent or message is None:
        raise HTTPException(status_code=422, detail="to_agent and message required")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor, lambda: runtime.send_message(to_agent, message, message_type, space)
    )
    return result


@app.get("/v1/agents/{agent_id}/messages/inbox")
async def read_messages(agent_id: str, unread_only: bool = Query(default=False),
                        space: str = Query(default="global"),
                        limit: int = Query(default=50, ge=1, le=200),
                        auth=Depends(verify_auth)):
    """Read messages from this agent's inbox."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    messages = await loop.run_in_executor(
        _executor, lambda: runtime.read_messages(space, unread_only, limit)
    )
    return {"agent_id": agent_id, "messages": messages, "count": len(messages)}


@app.post("/v1/agents/{agent_id}/messages/broadcast")
async def broadcast_message(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Broadcast a message to all agents in a space."""
    message = req.get("message")
    message_type = req.get("message_type", "info")
    space = req.get("space", "global")
    if message is None:
        raise HTTPException(status_code=422, detail="message required")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor, lambda: runtime.broadcast(message, message_type, space)
    )
    return result


# ---------------------------------------------------------------------------
# Goal Tracking
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/goal")
async def set_goal(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Set a goal for this agent."""
    goal = req.get("goal")
    milestones = req.get("milestones", [])
    if not goal:
        raise HTTPException(status_code=422, detail="goal required")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor, lambda: runtime.set_goal(goal, milestones)
    )
    return result


@app.get("/v1/agents/{agent_id}/goal")
async def get_goal(agent_id: str, auth=Depends(verify_auth)):
    """Get current goal and progress."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: runtime.get_goal())
    return result


@app.post("/v1/agents/{agent_id}/goal/progress")
async def update_progress(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Update progress on the current goal."""
    progress = req.get("progress")
    milestone_index = req.get("milestone_index")
    note = req.get("note")
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor, lambda: runtime.update_progress(progress, milestone_index, note)
    )
    return result


# ---------------------------------------------------------------------------
# Memory Export / Import
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/export")
async def export_memories(agent_id: str,
                          include_snapshots: bool = Query(default=False),
                          auth=Depends(verify_auth)):
    """Export all agent memories as a portable JSON bundle."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor, lambda: runtime.export_memories(include_snapshots)
    )
    return result


@app.post("/v1/agents/{agent_id}/import")
async def import_memories(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Import memories from an export bundle."""
    overwrite = req.get("overwrite", False)
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _executor, lambda: runtime.import_memories(req, overwrite)
    )
    return result


# ---------------------------------------------------------------------------
# Filtered Search
# ---------------------------------------------------------------------------

@app.post("/v1/agents/{agent_id}/search/filtered")
async def search_filtered(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Search memories with combined filters (query + tags + importance + time)."""
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        _executor,
        lambda: runtime.search_filtered(
            query=req.get("query"),
            tags=req.get("tags"),
            importance=req.get("importance"),
            min_age_seconds=req.get("min_age_seconds"),
            max_age_seconds=req.get("max_age_seconds"),
            limit=req.get("limit", 20),
        ),
    )
    return {"agent_id": agent_id, "results": results, "count": len(results)}


# ---------------------------------------------------------------------------
# Brain Intelligence API
# ---------------------------------------------------------------------------

@app.get("/v1/brain/status")
async def brain_status(auth=Depends(verify_auth)):
    """Get overall Brain intelligence status for the tenant."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.monitoring.brain import BrainHub
    return BrainHub.get_brain_status(tenant_id)


@app.get("/v1/brain/events")
async def brain_events(
    agent_id: str = Query(default=None),
    event_type: str = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    auth=Depends(verify_auth),
):
    """Get Brain intelligence events (loops, drift, conflicts, costs)."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.monitoring.brain import BrainHub
    events = BrainHub.get_events(tenant_id, agent_id=agent_id,
                                  event_type=event_type, limit=limit)
    return {"events": events, "count": len(events)}


@app.get("/v1/brain/drift/{agent_id}")
async def brain_drift(agent_id: str, auth=Depends(verify_auth)):
    """Get drift/alignment status for a specific agent."""
    _get_tenant_id(auth)
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.monitoring.brain import DriftRadar
    return DriftRadar.get_agent_drift(tenant_id, agent_id)


@app.get("/v1/brain/health/{agent_id}")
async def brain_health(agent_id: str, auth=Depends(verify_auth)):
    """Get memory health breakdown for a specific agent."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.monitoring.brain import MemoryHealth
    return MemoryHealth.get_health(tenant_id, agent_id)


@app.get("/v1/brain/conflicts/{agent_id}")
async def brain_conflicts(agent_id: str, auth=Depends(verify_auth)):
    """Get memory conflicts/contradictions for a specific agent."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.monitoring.brain import ContradictionShield
    conflicts = ContradictionShield.get_conflicts(tenant_id, agent_id)
    return {"agent_id": agent_id, "conflicts": conflicts, "count": len(conflicts)}


@app.post("/v1/brain/pause/{agent_id}")
async def brain_pause(agent_id: str, auth=Depends(verify_auth)):
    """Pause an agent (kill switch)."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.monitoring.brain import LoopBreaker
    LoopBreaker.pause_agent(tenant_id, agent_id, reason="manual")
    return {"agent_id": agent_id, "paused": True}


@app.post("/v1/brain/resume/{agent_id}")
async def brain_resume(agent_id: str, auth=Depends(verify_auth)):
    """Resume a paused agent."""
    tenant_id = _get_tenant_id(auth)
    from synrix_runtime.monitoring.brain import LoopBreaker
    LoopBreaker.resume_agent(tenant_id, agent_id)
    return {"agent_id": agent_id, "resumed": True}


@app.post("/v1/brain/goal/{agent_id}")
async def set_brain_goal(agent_id: str, req: dict, auth=Depends(verify_auth)):
    """Set the goal/task for drift tracking."""
    tenant_id = _get_tenant_id(auth)
    goal_text = req.get("goal", "")
    if not goal_text:
        raise HTTPException(400, "goal text required")

    # Encode the goal text
    try:
        from synrix.embeddings import EmbeddingModel
        model = EmbeddingModel.get()
        if model:
            embedding = model.encode(goal_text)
            from synrix_runtime.monitoring.brain import DriftRadar
            DriftRadar.set_goal(tenant_id, agent_id, embedding, goal_text)
            return {"agent_id": agent_id, "goal_set": True, "goal": goal_text}
    except Exception as e:
        raise HTTPException(500, f"Failed to encode goal: {e}")
    raise HTTPException(503, "Embedding model not available")


@app.get("/v1/brain/cost-summary")
async def brain_cost_summary(auth=Depends(verify_auth)):
    """Get cumulative cost tracking across all loop detections.

    Shows total money saved by catching loops, total wasted before detection,
    and number of loops caught. Requires llm_model to be set in settings.
    """
    tenant_id = _get_tenant_id(auth)
    settings = _get_tenant_settings(tenant_id)
    model = settings.get("llm_model", "unknown")

    try:
        backend = None
        try:
            from synrix_runtime.api.tenant import TenantManager
            tm = TenantManager.get_instance()
            backend = tm.get_backend(tenant_id)
        except Exception:
            pass

        # Fall back to daemon backend for local mode
        if not backend:
            try:
                from synrix_runtime.core.daemon import RuntimeDaemon
                daemon = RuntimeDaemon.get_instance()
                if daemon and daemon.backend:
                    backend = daemon.backend
            except Exception:
                pass

        if not backend:
            return {"model": model, "total_saved": 0, "loops_caught": 0,
                    "total_wasted_before_detection": 0, "since": None}

        # Read cumulative cost data
        cost_data = backend.read(f"metrics:{tenant_id}:cost_saved")
        if cost_data:
            val = cost_data.get("data", cost_data)
            if isinstance(val, dict) and "value" in val:
                val = val["value"]
            if isinstance(val, dict):
                return {
                    "model": model,
                    "total_saved": val.get("total_saved", 0),
                    "loops_caught": val.get("loops_caught", 0),
                    "total_wasted_before_detection": val.get("total_wasted", 0),
                    "since": val.get("since", None),
                }

        return {"model": model, "total_saved": 0, "loops_caught": 0,
                "total_wasted_before_detection": 0, "since": None}
    except Exception:
        return {"model": model, "total_saved": 0, "loops_caught": 0,
                "total_wasted_before_detection": 0, "since": None}


# ---------------------------------------------------------------------------
# Agent Timeline & Replay
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/timeline")
async def get_agent_timeline(
    agent_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=200, ge=1, le=1000),
    auth=Depends(verify_auth),
):
    """Get a chronological timeline of all agent events.

    Returns writes, recalls, decisions, loop detections, crashes,
    recoveries, and snapshots in time order. Use for replay/debugging.
    """
    _validate_agent_id(agent_id)
    runtime = _get_runtime(agent_id, auth)
    now = time.time()
    cutoff = now - (hours * 3600)
    events = []

    loop = asyncio.get_event_loop()

    def _build_timeline():
        backend = runtime.backend

        # 1. Memory writes (agents:{agent_id}:*)
        try:
            writes = backend.query_prefix(f"agents:{agent_id}:", limit=limit)
            for w in writes:
                data = w.get("data", {})
                val = data.get("value", data) if isinstance(data, dict) else data
                ts = data.get("timestamp", w.get("valid_from", 0))
                if isinstance(ts, (int, float)) and ts >= cutoff:
                    key = w.get("key", w.get("name", ""))
                    clean_key = key.replace(f"agents:{agent_id}:", "")
                    events.append({
                        "type": "write",
                        "time": ts,
                        "key": clean_key,
                        "preview": str(val)[:100] if val else "",
                    })
        except Exception:
            pass

        # 2. Decisions (audit:{agent_id}:*)
        try:
            decisions = backend.query_prefix(f"audit:{agent_id}:", limit=50)
            for d in decisions:
                data = d.get("data", {})
                val = data.get("value", data) if isinstance(data, dict) else data
                ts = val.get("timestamp", 0) if isinstance(val, dict) else 0
                if ts >= cutoff:
                    events.append({
                        "type": "decision",
                        "time": ts,
                        "decision": val.get("decision", "") if isinstance(val, dict) else "",
                        "reasoning": str(val.get("reasoning", ""))[:150] if isinstance(val, dict) else "",
                    })
        except Exception:
            pass

        # 3. Loop alerts (alerts:{agent_id}:*)
        try:
            alerts = backend.query_prefix(f"alerts:{agent_id}:", limit=50)
            for a in alerts:
                data = a.get("data", {})
                val = data.get("value", data) if isinstance(data, dict) else data
                ts = val.get("timestamp", 0) if isinstance(val, dict) else 0
                if ts >= cutoff:
                    events.append({
                        "type": "loop_alert",
                        "time": ts,
                        "severity": val.get("severity", "unknown") if isinstance(val, dict) else "unknown",
                        "detail": str(val.get("details", ""))[:100] if isinstance(val, dict) else "",
                    })
        except Exception:
            pass

        # 4. Snapshots (agents:{agent_id}:snapshots:*)
        try:
            snaps = backend.query_prefix(f"agents:{agent_id}:snapshots:", limit=20)
            for s in snaps:
                data = s.get("data", {})
                val = data.get("value", data) if isinstance(data, dict) else data
                ts = val.get("timestamp", 0) if isinstance(val, dict) else 0
                label = val.get("label", "") if isinstance(val, dict) else ""
                events.append({
                    "type": "snapshot",
                    "time": ts,
                    "label": label,
                })
        except Exception:
            pass

        # Sort by time — coerce to float so mixed str/int timestamps don't crash
        def _ts(e):
            t = e.get("time", 0)
            try:
                return float(t)
            except (TypeError, ValueError):
                return 0.0
        events.sort(key=_ts)
        return events[-limit:]

    result = await loop.run_in_executor(_executor, _build_timeline)
    return {
        "agent_id": agent_id,
        "hours": hours,
        "event_count": len(result),
        "events": result,
    }


# ---------------------------------------------------------------------------
# Auto-Checkpoints List
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/checkpoints")
async def list_checkpoints(agent_id: str, auth=Depends(verify_auth)):
    """List all checkpoints (manual + auto) for an agent.

    Returns checkpoint labels with timestamps, sorted newest first.
    Use with POST /v1/agents/{agent_id}/restore to rollback.
    """
    _validate_agent_id(agent_id)
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()

    def _get_checkpoints():
        backend = runtime.backend
        snaps = backend.query_prefix(f"agents:{agent_id}:snapshots:", limit=50)
        checkpoints = []
        for s in snaps:
            data = s.get("data", {})
            val = data.get("value", data) if isinstance(data, dict) else data
            if isinstance(val, dict):
                checkpoints.append({
                    "label": val.get("label", ""),
                    "timestamp": val.get("timestamp", 0),
                    "keys_captured": val.get("keys_captured", 0),
                    "auto": str(val.get("label", "")).startswith("auto-"),
                })
        def _cp_ts(c):
            t = c.get("timestamp", 0)
            try:
                return float(t)
            except (TypeError, ValueError):
                return 0.0
        checkpoints.sort(key=_cp_ts, reverse=True)
        return checkpoints

    result = await loop.run_in_executor(_executor, _get_checkpoints)
    return {"agent_id": agent_id, "checkpoints": result, "count": len(result)}


# ---------------------------------------------------------------------------
# Per-Agent Cost Tracking
# ---------------------------------------------------------------------------

@app.get("/v1/agents/{agent_id}/cost")
async def get_agent_cost(agent_id: str, auth=Depends(verify_auth)):
    """Get cumulative cost tracking for a specific agent.

    Shows estimated spend, loops caught, and projected costs.
    """
    _validate_agent_id(agent_id)
    tenant_id = _get_tenant_id(auth)
    runtime = _get_runtime(agent_id, auth)
    loop = asyncio.get_event_loop()

    def _get_cost():
        backend = runtime.backend
        settings = _get_tenant_settings(tenant_id)
        model = settings.get("llm_model", "unknown")

        # Get loop status for current cost data
        try:
            loop_status = runtime.get_loop_status()
            cost = loop_status.get("cost", {})
        except Exception:
            cost = {}

        # Get agent metrics for operation count
        try:
            from synrix_runtime.monitoring.metrics import MetricsCollector
            collector = MetricsCollector(backend, tenant_id=tenant_id)
            metrics = collector.get_agent_metrics(agent_id)
            total_ops = metrics.total_operations
            avg_write_latency = metrics.avg_write_latency_us
        except Exception:
            total_ops = 0
            avg_write_latency = 0

        # Estimate total cost based on operations
        try:
            from synrix_runtime.monitoring.cost_models import get_cost_per_write
            cost_per_op = get_cost_per_write(model)
            estimated_total = round(cost_per_op * total_ops, 4)
        except Exception:
            cost_per_op = 0
            estimated_total = 0

        return {
            "agent_id": agent_id,
            "model": model,
            "total_operations": total_ops,
            "cost_per_operation": cost_per_op,
            "estimated_total_cost": estimated_total,
            "loop_cost": cost,
            "loop_severity": loop_status.get("severity", "green") if 'loop_status' in dir() else "green",
            "loop_score": loop_status.get("score", 100) if 'loop_status' in dir() else 100,
        }

    result = await loop.run_in_executor(_executor, _get_cost)
    return result


# ---------------------------------------------------------------------------
# Sentry verification endpoint
# ---------------------------------------------------------------------------
# Triggers a controlled exception to confirm Sentry is receiving events.
# Restricted to platform-owner tenants so random users can't flood your quota.
@app.get("/v1/admin/sentry-test")
async def sentry_test(auth=Depends(verify_auth)):
    tenant_id = _get_tenant_id(auth)
    if tenant_id not in _ADMIN_TENANTS:
        raise HTTPException(status_code=403, detail="Admin only")
    if not _sentry_dsn:
        raise HTTPException(status_code=503, detail="Sentry is not configured on this instance (SENTRY_DSN unset)")
    # Controlled exception — this SHOULD land in Sentry within ~30 seconds.
    raise RuntimeError("Sentry verification — ignore this, it's intentional.")


# ---------------------------------------------------------------------------
# Admin health + activation canary
# ---------------------------------------------------------------------------
# /v1/admin/health tests every critical path end-to-end so we catch silent
# regressions. /v1/admin/activation reports cohort activation — we caught
# the null-byte bug because 25/37 users touched the API but only 3/37 wrote
# memories. Monitoring this ratio is the early warning.

@app.get("/v1/admin/activation")
async def admin_activation(auth=Depends(verify_auth)):
    """Cohort activation report. Returns per-time-window signup-to-activation rates.

    Activation = tenant has written at least one memory (nodes row).
    Healthy SaaS runs 20-40%. Drops below 20% → something's broken.
    """
    tenant_id_auth = _get_tenant_id(auth)
    if tenant_id_auth not in _ADMIN_TENANTS:
        raise HTTPException(status_code=403, detail="Admin only")

    # The cross-tenant COUNT requires SECURITY DEFINER bypass of RLS because
    # the app user can't see other tenants' nodes. See:
    # scripts/create_admin_activation_fn.py — run once to install the function.
    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    conn = tm._conn()
    windows = {}
    try:
        cur = conn.cursor()
        for label, interval in [("24h", "24 hours"), ("7d", "7 days"),
                                ("30d", "30 days"), ("all_time", "100 years")]:
            try:
                cur.execute(
                    "SELECT * FROM admin_cohort_activation(%s::interval)",
                    (interval,)
                )
                s, v, u, a = cur.fetchone()
            except Exception as e:
                logger.error("admin_cohort_activation(%s) failed: %s", interval, e)
                s = v = u = a = 0
            windows[label] = {
                "signups": s, "verified": v, "used_api": u, "activated": a,
                "signup_to_verified_pct": round((v / s) * 100, 1) if s else 0,
                "signup_to_api_pct": round((u / s) * 100, 1) if s else 0,
                "signup_to_activation_pct": round((a / s) * 100, 1) if s else 0,
                "tried_but_failed": max(0, u - a),  # Touched API, never wrote
            }
    finally:
        tm._release(conn)

    # Health signal: activation <20% in last 7d is a red flag
    last7d_pct = windows.get("7d", {}).get("signup_to_activation_pct", 0)
    health = "healthy" if last7d_pct >= 20 else "degraded" if last7d_pct >= 10 else "critical"

    return {
        "health": health,
        "threshold": "activation >=20% healthy, >=10% degraded, else critical",
        "windows": windows,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/v1/admin/health")
async def admin_health(auth=Depends(verify_auth)):
    """End-to-end smoke test of every critical write/read path.

    Runs against the calling admin's tenant. Creates a test agent, writes a
    memory with a null byte (the bug that broke 67% of users), recalls it,
    semantically searches, writes shared memory, logs a decision, takes a
    snapshot, then cleans up. Returns per-step status.

    Run manually or from a cron. If anything fails, the response shows which
    step + the error, so we catch regressions before users hit them.
    """
    tenant_id = _get_tenant_id(auth)
    if tenant_id not in _ADMIN_TENANTS:
        raise HTTPException(status_code=403, detail="Admin only")

    import uuid
    test_agent = f"healthcheck-{uuid.uuid4().hex[:8]}"
    results = []
    ok = True

    def _step(name, fn):
        nonlocal ok
        t0 = time.time()
        try:
            out = fn()
            results.append({"step": name, "ok": True, "latency_ms": round((time.time() - t0) * 1000, 1),
                            "detail": str(out)[:120] if out is not None else ""})
            return out
        except Exception as e:
            ok = False
            results.append({"step": name, "ok": False, "latency_ms": round((time.time() - t0) * 1000, 1),
                            "error": f"{type(e).__name__}: {e}"[:200]})
            return None

    # Admin accounts may be at the agent cap (e.g. platform owner has 50
    # demo agents). Fall back to an ephemeral AgentRuntime that skips the
    # cap-gated registration so the smoke test still runs.
    def _make_runtime():
        try:
            return _get_runtime(test_agent, auth, register=True)
        except HTTPException as e:
            if e.status_code in (402, 403):
                from synrix_runtime.api.tenant import TenantManager
                from synrix_runtime.api.runtime import AgentRuntime
                tm = TenantManager.get_instance()
                backend = tm.get_backend(tenant_id)
                return AgentRuntime(
                    test_agent, agent_type="healthcheck",
                    backend_override=backend, tenant_id=tenant_id,
                    require_account=False,
                )
            raise
    runtime = _step("register_and_get_runtime", _make_runtime)
    if runtime:
        # Null-byte regression test — this is the exact bug that hid for months
        _step("write_with_null_byte",
              lambda: runtime.remember("healthcheck_null",
                                       "data with null \u0000 embedded"))
        recall_result = _step("recall",
                              lambda: runtime.recall("healthcheck_null"))
        _step("recall_value_present",
              lambda: ("value" in str(recall_result.__dict__)) if recall_result else False)
        _step("shared_write",
              lambda: runtime.share("healthcheck_shared", "shared-value", space="healthcheck"))
        _step("log_decision",
              lambda: runtime.log_decision(decision="test-decision", reasoning="health-check"))
        _step("snapshot",
              lambda: runtime.snapshot(label="healthcheck"))
        # Cleanup
        try:
            from synrix_runtime.api.tenant import TenantManager
            tm = TenantManager.get_instance()
            conn = tm._conn()
            try:
                cur = conn.cursor()
                cur.execute("SET LOCAL app.tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM nodes WHERE name LIKE %s OR name LIKE %s",
                            (f"agents:{test_agent}:%", f"shared:healthcheck:%"))
                conn.commit()
            finally:
                tm._release(conn)
            results.append({"step": "cleanup", "ok": True})
        except Exception as e:
            results.append({"step": "cleanup", "ok": False, "error": str(e)[:200]})

    return {
        "ok": ok,
        "test_agent_id": test_agent,
        "steps": results,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ---------------------------------------------------------------------------
# Admin billing overview — paid tenants + MRR + recent events
# ---------------------------------------------------------------------------
# Monthly price per plan (matches billing.get_plans() — keep in sync).
_PLAN_MONTHLY_USD = {
    "free": 0, "early_adopter": 0,
    "pro": 19, "business": 49, "scale": 99,
    "enterprise": 0,  # custom — not counted in auto-MRR
}

@app.get("/v1/admin/billing/overview")
async def admin_billing_overview(auth=Depends(verify_auth)):
    """Admin-only billing dashboard data: paid tenants, MRR, recent Stripe events."""
    tenant_id = _get_tenant_id(auth)
    if tenant_id not in _ADMIN_TENANTS:
        raise HTTPException(status_code=403, detail="Admin only")

    from synrix_runtime.api.tenant import TenantManager
    tm = TenantManager.get_instance()
    conn = tm._conn()
    summary_by_plan = {}
    paid_tenants = []
    total_tenants = 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT plan, COUNT(*) FROM tenants GROUP BY plan")
        for plan, count in cur.fetchall():
            summary_by_plan[plan or "unknown"] = count
            total_tenants += count

        # Paid tenants (anything with a stripe subscription ID)
        cur.execute("""
            SELECT tenant_id, email, first_name, last_name, plan, created_at,
                   max_agents, max_memories, stripe_customer_id, stripe_subscription_id
              FROM tenants
             WHERE stripe_subscription_id IS NOT NULL
               AND stripe_subscription_id <> ''
             ORDER BY created_at DESC
        """)
        for row in cur.fetchall():
            paid_tenants.append({
                "tenant_id": row[0],
                "email": row[1],
                "name": (f"{row[2] or ''} {row[3] or ''}".strip()) or None,
                "plan": row[4],
                "created_at": row[5].isoformat() if row[5] else None,
                "max_agents": row[6],
                "max_memories": row[7],
                "stripe_customer_id": row[8],
                "stripe_subscription_id": row[9],
            })
    finally:
        tm._release(conn)

    # MRR from plan counts (free + early_adopter contribute $0)
    mrr_usd = sum(_PLAN_MONTHLY_USD.get(t["plan"], 0) for t in paid_tenants)

    # Recent billing events from Stripe — last 20, all billing-related types
    recent_events = []
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if stripe_key:
        try:
            import requests as _req
            r = _req.get(
                "https://api.stripe.com/v1/events",
                auth=(stripe_key, ""),
                params={
                    "limit": 20,
                    "types[]": ["checkout.session.completed",
                                "customer.subscription.updated",
                                "customer.subscription.deleted",
                                "invoice.payment_failed",
                                "invoice.payment_succeeded"],
                },
                timeout=10,
            )
            for ev in r.json().get("data", []):
                obj = ev.get("data", {}).get("object", {})
                recent_events.append({
                    "id": ev.get("id"),
                    "type": ev.get("type"),
                    "created": ev.get("created"),
                    "livemode": ev.get("livemode"),
                    "customer": obj.get("customer") or "",
                    "tenant_id": obj.get("metadata", {}).get("tenant_id", "")
                                 if isinstance(obj.get("metadata"), dict) else "",
                    "amount": (obj.get("amount_paid") or obj.get("amount_due") or 0) / 100.0,
                    "currency": (obj.get("currency") or "").upper(),
                })
        except Exception as e:
            logger.error("Stripe events fetch failed: %s", e)

    return {
        "summary": {
            "total_tenants": total_tenants,
            "paid_tenants": len(paid_tenants),
            "mrr_usd": mrr_usd,
            "arr_usd": mrr_usd * 12,
            "by_plan": summary_by_plan,
        },
        "paid_tenants": paid_tenants,
        "recent_events": recent_events,
    }
