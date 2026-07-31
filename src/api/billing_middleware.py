from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.infrastructure.billing_service import (
    PUBLIC_PATHS,
    BillingService,
    TokenValidationError,
)
from src.infrastructure.logging_config import get_logger, set_trace_context

logger = get_logger(__name__)

_billing_service: BillingService | None = None


def get_billing_service() -> BillingService:
    global _billing_service
    if _billing_service is None:
        from src.infrastructure.relational_db import PostgresBillingRepository
        _billing_service = BillingService(PostgresBillingRepository())
    return _billing_service


class BillingMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith("/api/v1/admin/") or path.startswith("/api/v1/billing/"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)

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
                    headers={"Access-Control-Allow-Origin": "*"},
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
                headers={"Access-Control-Allow-Origin": "*"},
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
                headers={"Access-Control-Allow-Origin": "*"},
            )

        response = await call_next(request)

        response.headers["X-Plan"] = ctx.plan_name
        response.headers["X-Subscription-Status"] = ctx.status.value

        return response
