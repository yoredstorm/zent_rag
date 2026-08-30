# =============================================================================
# Security headers + optional per-org CORS allowlist
# =============================================================================
from __future__ import annotations

from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        path = request.url.path
        if not path.startswith(("/docs", "/redoc", "/openapi.json")):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault(
                "Referrer-Policy", "strict-origin-when-cross-origin"
            )
        if not path.startswith(("/embed", "/docs", "/redoc")):
            response.headers.setdefault("X-Frame-Options", "DENY")
        return response


class OrgCorsMiddleware(BaseHTTPMiddleware):
    """If the org set config_json.cors_origins, reject other Origins."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        origin = (request.headers.get("origin") or "").strip().rstrip("/")
        org_id = getattr(request.state, "organization_id", None)
        if (
            origin
            and org_id
            and org_id != "platform"
            and request.method.upper() != "OPTIONS"
        ):
            try:
                oid = UUID(str(org_id))
            except ValueError:
                oid = None
            if oid is not None:
                from src.api.deps import get_organization_repo

                organization = await get_organization_repo().get_by_id(oid)
                raw = (organization.config_json or {}).get("cors_origins") if organization else None
                if isinstance(raw, list) and raw:
                    allowed = {str(item).strip().rstrip("/") for item in raw if item}
                    if origin not in allowed:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "error_code": "origin_not_allowed",
                                "message": "Origin is not in the organization CORS allowlist.",
                            },
                        )
        return await call_next(request)
