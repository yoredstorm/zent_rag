# =============================================================================
# Idempotency Middleware — deduplica retries de operaciones de creación
# =============================================================================
# Header: Idempotency-Key (opcional). Las respuestas de POST/PUT exitosos o
# rechazos 4xx quedan almacenadas 24h; un replay con la misma key devuelve
# la respuesta original sin re-ejecutar la operación.
# =============================================================================
from __future__ import annotations

import base64
import json
import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9\-_]{8,128}$")
_TTL_SECONDS = 86400
_STOREABLE_STATUS = {200, 201, 202, 204, 400, 401, 402, 403, 404, 409, 422, 429}


class IdempotencyMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        method = request.method.upper()
        if method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key", "")
        if not idem_key or not _IDEMPOTENCY_KEY_RE.match(idem_key):
            return await call_next(request)

        organization_id = getattr(request.state, "organization_id", "")
        client_ip = request.client.host if request.client else "unknown"
        namespace = f"organization:{organization_id}" if organization_id else f"ip:{client_ip}"
        redis_key = f"rag:idem:{namespace}:{idem_key}"

        try:
            client = await _get_redis()
            stored = await client.get(redis_key)
        except Exception:
            stored = None

        if stored:
            try:
                payload = json.loads(stored)
                return Response(
                    content=base64.b64decode(payload["body"]),
                    status_code=payload["status"],
                    headers=payload.get("headers", {}),
                    media_type=payload.get("media_type"),
                )
            except Exception as exc:
                logger.warning("Corrupt idempotency record", key=idem_key, error=str(exc))

        response = await call_next(request)

        if response.status_code in _STOREABLE_STATUS and getattr(response, "body", None):
            payload = {
                "status": response.status_code,
                "media_type": response.media_type,
                "headers": {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() in ("content-type", "cache-control")
                },
                "body": base64.b64encode(response.body).decode("ascii"),
            }
            try:
                await client.setex(redis_key, _TTL_SECONDS, json.dumps(payload))
            except Exception as exc:
                logger.debug("Could not store idempotency record", error=str(exc))

        return response
