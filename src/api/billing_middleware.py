from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import get_settings
from src.infrastructure.billing_service import (
    PUBLIC_PATHS,
    BillingService,
    TokenValidationError,
)
from src.infrastructure.logging_config import get_logger, set_trace_context

logger = get_logger(__name__)

_billing_service: BillingService | None = None

# Exact public paths beyond PUBLIC_PATHS
_PUBLIC_BILLING_GET = {"/api/v1/billing/plans"}
_PUBLIC_BILLING_POST = {"/api/v1/billing/subscription/create-trial"}

# Dev-only SQL admin (not prompt management)
_ADMIN_SQL_PREFIXES = (
    "/api/v1/admin/tables",
    "/api/v1/admin/sql",
)


def get_billing_service() -> BillingService:
    global _billing_service
    if _billing_service is None:
        from src.infrastructure.relational_db import PostgresBillingRepository
        _billing_service = BillingService(PostgresBillingRepository())
    return _billing_service


def _is_public(path: str, method: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if method == "GET" and path in _PUBLIC_BILLING_GET:
        return True
    if method == "POST" and path in _PUBLIC_BILLING_POST:
        return True
    return False


def _is_admin_sql(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _ADMIN_SQL_PREFIXES)


class BillingMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        method = request.method.upper()

        # CORS preflight
        if method == "OPTIONS":
            return await call_next(request)

        if _is_public(path, method):
            return await call_next(request)

        settings = get_settings()
        if _is_admin_sql(path) and not settings.RAG_ADMIN_ENABLED:
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "admin_disabled",
                    "message": "Admin SQL endpoints are disabled. Set RAG_ADMIN_ENABLED=true for local use.",
                },
            )

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error_code": "missing_token",
                    "message": "Authorization: Bearer <token> is required",
                },
            )

        token = auth_header[7:]
        billing = get_billing_service()

        try:
            ctx = await billing.validate_token(token)

            within_quota = await billing.check_quota(ctx)
            if not within_quota:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "quota_exceeded",
                        "message": f"Monthly request quota ({ctx.requests_limit}) exceeded. Upgrade your plan.",
                        "requests_limit": ctx.requests_limit,
                    },
                )

            await billing.touch_token(ctx.token_id)

            request.state.billing_context = ctx
            request.state.tenant_id = str(ctx.tenant_id)

            set_trace_context(trace_id=str(uuid4()), tenant_id=str(ctx.tenant_id))
        except TokenValidationError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error_code": exc.error_code,
                    "message": str(exc),
                },
            )
        except Exception as exc:
            logger.error(
                "Billing middleware error",
                error=str(exc),
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error_code": "BILLING_ERROR",
                    "message": str(exc),
                },
            )

        response = await call_next(request)

        response.headers["X-Plan"] = ctx.plan_name
        response.headers["X-Subscription-Status"] = ctx.status.value

        return response
