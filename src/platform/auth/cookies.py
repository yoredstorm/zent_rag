"""Sesiones por cookie (FASE 05/11): HttpOnly + SameSite + CSRF double-submit.

El portal se sirve same-origin vía nginx (proxy /api), por lo que las cookies
de sesión viven en el origen del portal (:8080) sin relajar CORS.
SDKs y API keys siguen usando Authorization: Bearer — sin cambios.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlparse

from starlette.responses import Response

from src.core.config import get_settings

PORTAL_SESSION_COOKIE = "rag_portal_session"
PLATFORM_SESSION_COOKIE = "rag_platform_session"
CSRF_COOKIE = "rag_csrf"

_SESSION_COOKIE_MAX_AGE = 24 * 60 * 60  # absoluto; el token expira igual por sí solo


def _cookie_base_kwargs(max_age: int | None = None) -> dict:
    settings = get_settings()
    kwargs: dict = {
        "path": "/",
        "secure": settings.SESSION_COOKIE_SECURE,
        "samesite": "lax",
        "max_age": max_age,
    }
    return kwargs


def set_portal_session_cookie(response: Response, token: str, max_age: int | None = None) -> None:
    response.set_cookie(
        PORTAL_SESSION_COOKIE,
        token,
        httponly=True,
        **_cookie_base_kwargs(max_age or _SESSION_COOKIE_MAX_AGE),
    )


def set_platform_session_cookie(response: Response, token: str, max_age: int | None = None) -> None:
    response.set_cookie(
        PLATFORM_SESSION_COOKIE,
        token,
        httponly=True,
        **_cookie_base_kwargs(max_age or _SESSION_COOKIE_MAX_AGE),
    )


def clear_portal_session_cookie(response: Response) -> None:
    response.delete_cookie(PORTAL_SESSION_COOKIE, path="/")


def clear_platform_session_cookie(response: Response) -> None:
    response.delete_cookie(PLATFORM_SESSION_COOKIE, path="/")


def set_csrf_cookie(response: Response) -> str:
    """Emite el token CSRF (no HttpOnly; double-submit con header)."""
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        **_cookie_base_kwargs(),
    )
    return token


def origin_allowed(origin: str | None) -> bool:
    """Valida que el Origin (si existe) sea el propio servicio o el portal proxy."""
    if not origin:
        return False
    try:
        host = urlparse(origin).netloc
    except ValueError:
        return False
    allowed = set(get_settings().CSRF_ALLOWED_ORIGINS)
    return host in allowed
