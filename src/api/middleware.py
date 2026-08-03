# =============================================================================
# Trace ID Middleware — Inyecta trazabilidad en cada request HTTP
# =============================================================================
# Genera un trace_id único por request (UUID7-like) y lo propaga:
# 1. En el header de respuesta X-Trace-Id
# 2. En los logs estructurados vía ContextVar
# 3. En las métricas de Prometheus vía exemplars
#
# El trace_id permite correlacionar una request HTTP con sus logs en Loki
# y sus métricas en Prometheus, trazando el ciclo de vida completo.
# =============================================================================
from __future__ import annotations

import contextvars
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.infrastructure.logging_config import get_logger, set_trace_context

logger = get_logger(__name__)

# ContextVar para latencia de request (accesible desde métricas)
request_latency_var: contextvars.ContextVar[float] = contextvars.ContextVar(
    "request_latency", default=0.0
)


class TraceMiddleware(BaseHTTPMiddleware):
    """Middleware que inyecta trace_id, tenant_id y user_id en cada request.

    - Trace ID: UUID v4 (compatible con Loki + Prometheus exemplars)
    - Si el cliente envía X-Tenant-Id y X-User-Id, se respetan
    - Se añade X-Trace-Id a la respuesta para que el cliente pueda referenciarlo
    - Mide latencia total del request para el log estructurado
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Genera o hereda trace_id
        trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
        tenant_id = request.headers.get("X-Tenant-Id", "system")
        user_id = request.headers.get("X-User-Id", "anonymous")

        # Inyecta en ContextVar para que todos los logs de esta request lo incluyan
        set_trace_context(trace_id=trace_id, tenant_id=tenant_id, user_id=user_id)

        start = time.perf_counter()

        # Procesa la request
        response: Response = await call_next(request)

        # Calcula latencia total
        elapsed_ms = (time.perf_counter() - start) * 1000
        request_latency_var.set(elapsed_ms)

        # Inyecta trace_id en la respuesta para que el cliente pueda trazarlo
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Request-Duration-Ms"] = f"{elapsed_ms:.2f}"

        # Log de acceso estructurado (JSON)
        logger.info(
            "Request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=round(elapsed_ms, 2),
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("User-Agent", "unknown")[:255],
        )

        return response
