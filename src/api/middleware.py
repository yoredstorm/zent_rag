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
import re
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

_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9\-_]{8,128}$")


class TraceMiddleware(BaseHTTPMiddleware):
    """Middleware que inyecta trace_id, tenant_id y user_id en cada request.

    - Trace ID: hereda X-Trace-Id del cliente SOLO si es un formato válido
      (anti log poisoning); en caso contrario genera UUID v4.
    - tenant_id/user_id para logs parten en 'system'/'anonymous' y son
      reemplazados por BillingMiddleware con la identidad autenticada real.
    - Se añade X-Trace-Id a la respuesta para que el cliente pueda referenciarlo
    - Mide latencia total del request para el log estructurado
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Genera o hereda trace_id (solo formatos válidos del cliente)
        header_trace = request.headers.get("X-Trace-Id", "")
        if _TRACE_ID_RE.match(header_trace):
            trace_id = header_trace
        else:
            trace_id = str(uuid.uuid4())

        # Identidad real la inyecta BillingMiddleware para rutas autenticadas.
        set_trace_context(trace_id=trace_id, tenant_id="system", user_id="anonymous")

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
