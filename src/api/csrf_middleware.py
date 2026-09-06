"""CSRF protection para sesiones por cookie (FASE 05/11).

Requisito: mutaciones autenticadas por cookie deben incluir
`X-Zent-Csrf` (double-submit) igual al cookie `rag_csrf`, y el Origin
debe estar en la allowlist. Las mutaciones con Authorization Bearer
(SDKs/API keys) no usan cookies y no aplican CSRF.
"""
from __future__ import annotations

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.core.config import get_settings
from src.platform.auth.cookies import (
    CSRF_COOKIE,
    PLATFORM_SESSION_COOKIE,
    PORTAL_SESSION_COOKIE,
    origin_allowed,
)

logger = logging.getLogger(__name__)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if settings.SESSION_COOKIE_ENABLED is False:
            return await call_next(request)

        method = request.method.upper()
        if method in _SAFE_METHODS:
            return await call_next(request)

        # Solo aplica cuando la identidad viene por cookie (no Bearer).
        has_bearer = bool(request.headers.get("authorization", "").startswith("Bearer "))
        has_session_cookie = bool(
            request.cookies.get(PORTAL_SESSION_COOKIE)
            or request.cookies.get(PLATFORM_SESSION_COOKIE)
        )
        if has_bearer or not has_session_cookie:
            return await call_next(request)

        origin = request.headers.get("origin")
        if not origin:
            # Cliente no-browser (curl/httpx/SDK): sin Origin no existe el vector
            # de ambient authority; los navegadores SIEMPRE envían Origin en POST.
            return await call_next(request)
        if not origin_allowed(origin):
            logger.warning(
                "CSRF blocked: origin no permitido",
                extra={"origin": origin, "path": request.url.path},
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "error_code": "csrf_origin_blocked",
                        "message": "Origin no permitido para esta operación.",
                    }
                },
            )

        header_token = request.headers.get("x-zent-csrf", "")
        cookie_token = request.cookies.get(CSRF_COOKIE, "")
        if not header_token or not cookie_token or not hmac.compare_digest(header_token, cookie_token):
            logger.warning(
                "CSRF blocked: token inválido",
                extra={"path": request.url.path},
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "error_code": "csrf_token_invalid",
                        "message": "Token CSRF inválido.",
                    }
                },
            )

        return await call_next(request)
