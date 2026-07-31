# =============================================================================
# Structured Logging — structlog + JSON para Loki
# =============================================================================
# Cada log incluye obligatoriamente tenant_id, trace_id y user_id.
# Formato JSON pipeline-friendly para que Loki indexe campos individuales.
# =============================================================================
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# -----------------------------------------------------------------------------
# Context Variables — Thread-safe, propagan información a través de async calls
# -----------------------------------------------------------------------------
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="unknown")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="system")
user_id_var: ContextVar[str] = ContextVar("user_id", default="anonymous")


def set_trace_context(trace_id: str, tenant_id: str = "unknown", user_id: str = "anonymous") -> None:
    """Establece el contexto de trazabilidad para la request actual."""
    trace_id_var.set(trace_id)
    tenant_id_var.set(tenant_id)
    user_id_var.set(user_id)


def _add_observability_context(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Procesador de structlog que inyecta trace_id, tenant_id y user_id."""
    event_dict.setdefault("trace_id", trace_id_var.get())
    event_dict.setdefault("tenant_id", tenant_id_var.get())
    event_dict.setdefault("user_id", user_id_var.get())
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configura structlog para emitir JSON compatible con Loki."""

    # Silencia loggers ruidosos de librerías
    for noisy in ("httpx", "httpcore", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            # Inyecta nombre del logger
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            # Timestamps en ISO 8601 con timezone UTC
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Stack info para errores
            structlog.processors.StackInfoRenderer(),
            # Formatea excepciones
            structlog.processors.format_exc_info,
            # Añade trace context
            _add_observability_context,
            # Render final: JSON
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configura el nivel en el root logger
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Retorna un logger estructurado listo para usar."""
    return structlog.get_logger(name or __name__)
