# =============================================================================
# Rate Limit Middleware — sliding window (Redis) por organization e IP
# =============================================================================
# - Organization autenticado: RATE_LIMIT_PER_ORGANIZATION_MINUTE requests/min por organization.
# - IP global (rutas costosas): RATE_LIMIT_PER_MINUTE requests/min.
# - Endpoints públicos (signup/trial): RATE_LIMIT_PUBLIC_PER_MINUTE por IP
#   (skip loopback para no romper dev/tests locales).
# Fail-open si Redis no está disponible (availability > protection) con
# contador in-memory por proceso como mitigación parcial.
# =============================================================================
from __future__ import annotations

import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

_PUBLIC_POST_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/signup",
    "/api/v1/auth/platform/login",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/billing/subscription/create-trial",
}
_PUBLIC_GET_PATHS = {"/api/v1/connectors/oauth/drive/callback"}
_EXEMPT_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1",
    "/api/v1/openapi.json",
}
_LOOPBACK_IPS = {"127.0.0.1", "::1", "testclient"}

_mem_lock = threading.Lock()
_mem_windows: dict[str, tuple[list[float], float]] = {}


def _mem_check(key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    with _mem_lock:
        entry = _mem_windows.get(key)
        if entry is None:
            _mem_windows[key] = ([now], now + window_seconds)
            return True
        hits, expires = entry
        if now >= expires:
            _mem_windows[key] = ([now], now + window_seconds)
            return True
        hits = [h for h in hits if now - h < window_seconds]
        if len(hits) >= limit:
            _mem_windows[key] = (hits, expires)
            return False
        hits.append(now)
        _mem_windows[key] = (hits, expires)
        return True


async def _redis_check(key: str, limit: int, window_seconds: int) -> bool:
    client = await _get_redis()
    pipe = client.pipeline()
    now_ms = int(time.time() * 1000)
    window_ms = window_seconds * 1000
    pipe.zremrangebyscore(key, 0, now_ms - window_ms)
    pipe.zadd(key, {str(now_ms): now_ms})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    results = await pipe.execute()
    return results[2] <= limit


class RateLimitMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = get_settings()
        path = request.url.path
        method = request.method.upper()

        if not settings.RATE_LIMIT_ENABLED or path in _EXEMPT_PATHS:
            return await call_next(request)

        if method == "OPTIONS":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # -----------------------------------------------------------------
        # Endpoints públicos sensibles (signup/trial/login): limitar por IP.
        # -----------------------------------------------------------------
        if (
            method == "POST"
            and (path in _PUBLIC_POST_PATHS or path.startswith("/api/v1/embed/"))
        ) or (method == "GET" and path in _PUBLIC_GET_PATHS):
            if client_ip in _LOOPBACK_IPS:
                return await call_next(request)
            key = f"rl:pub:{client_ip}"
            allowed = await self._check(
                key, settings.RATE_LIMIT_PUBLIC_PER_MINUTE, 60
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "rate_limited",
                        "message": "Too many requests from this IP. Try again later.",
                    },
                )
            return await call_next(request)

        # -----------------------------------------------------------------
        # API key: cuota por token (live 100/min 10k/día; test más estricto).
        # -----------------------------------------------------------------
        tenant_ctx = getattr(request.state, "tenant_context", None)
        token_id = getattr(tenant_ctx, "token_id", None) if tenant_ctx else None
        auth_type = getattr(tenant_ctx, "auth_type", None) if tenant_ctx else None
        if token_id and auth_type == "api_token":
            environment = getattr(request.state, "api_key_environment", "live")
            if environment == "test":
                rpm, rpd = settings.API_KEY_TEST_RPM, settings.API_KEY_TEST_RPD
            else:
                rpm, rpd = settings.API_KEY_LIVE_RPM, settings.API_KEY_LIVE_RPD
            minute_key = f"rag:rl:key:{token_id}"
            day_key = f"rag:rl:key:{token_id}:day"
            minute_ok = await self._check(minute_key, rpm, 60)
            day_ok = await self._check(day_key, rpd, 86_400)
            if not minute_ok or not day_ok:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "api_key_rate_limited",
                        "message": "Rate limit exceeded for this API key. Try again shortly.",
                    },
                )

        # -----------------------------------------------------------------
        # Organization autenticado: limitar por organization (rutas costosas).
        # -----------------------------------------------------------------
        organization_id = getattr(request.state, "organization_id", None) or getattr(
            request.state, "billing_context", None
        )
        if organization_id is not None and hasattr(organization_id, "organization_id"):
            organization_id = organization_id.organization_id
        if organization_id:
            organization_id = str(organization_id)

        if organization_id:
            key = f"rl:organization:{organization_id}"
            allowed = await self._check(
                key, settings.RATE_LIMIT_PER_ORGANIZATION_MINUTE, 60
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "organization_rate_limited",
                        "message": "Rate limit exceeded for this organization. Try again shortly.",
                    },
                )
            return await call_next(request)

        # -----------------------------------------------------------------
        # IP global sobre todo lo demás autenticado.
        # -----------------------------------------------------------------
        if client_ip not in _LOOPBACK_IPS:
            key = f"rl:ip:{client_ip}"
            allowed = await self._check(key, settings.RATE_LIMIT_PER_MINUTE, 60)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "rate_limited",
                        "message": "Too many requests. Try again later.",
                    },
                )

        return await call_next(request)

    async def _check(self, key: str, limit: int, window_seconds: int) -> bool:
        try:
            return await _redis_check(key, limit, window_seconds)
        except Exception as exc:
            logger.debug(
                "Rate limit Redis unavailable; using in-memory fallback",
                key=key,
                error=str(exc),
            )
            return _mem_check(key, limit, window_seconds)
