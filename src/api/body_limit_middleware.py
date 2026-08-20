# =============================================================================
# Body Size Limit Middleware — rechaza requests con body excesivo (DoS)
# =============================================================================
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.core.config import get_settings


class BodySizeLimitMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = get_settings()
        content_length = request.headers.get("content-length", "")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = -1
            if size > settings.MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error_code": "payload_too_large",
                        "message": (
                            f"Request body exceeds the maximum size "
                            f"({settings.MAX_BODY_BYTES} bytes)."
                        ),
                    },
                )
        return await call_next(request)
