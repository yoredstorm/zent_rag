# =============================================================================
# OpenTelemetry Tracing — Distributed tracing for RAG pipeline
# =============================================================================
# Instruments FastAPI HTTP layer automatically and provides manual span
# helpers for key RAG operations (embedding, vector search, SQL, LLM).
# Exports to OTLP collector when TRACING_ENABLED=true.
# =============================================================================
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

_tracer = None
_tracing_enabled = False

# Opcional: throttle spam when SDK exists but collector is unreachable
_EXPORT_FAILURE_LOGGED = False


def _get_tracer():
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        _tracer = None
        return None

    from src.config import get_settings
    settings = get_settings()
    if not settings.TRACING_ENABLED:
        _tracer = None
        return None

    try:
        resource = Resource.create({SERVICE_NAME: "rag-platform"})
        provider = TracerProvider(resource=resource)

        endpoint = settings.TRACING_OTLP_ENDPOINT or "http://localhost:4318/v1/traces"
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer("rag-platform")
        logger.info("OpenTelemetry tracing enabled", endpoint=endpoint)
        return _tracer
    except Exception as exc:
        global _EXPORT_FAILURE_LOGGED
        if not _EXPORT_FAILURE_LOGGED:
            _EXPORT_FAILURE_LOGGED = True
            logger.warning("OpenTelemetry exporter failed, tracing disabled", error=str(exc))
        _tracer = None
        return None


def setup_tracing(app) -> None:
    tracer = _get_tracer()
    if tracer is None:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, tracer_provider=trace.get_tracer_provider())  # type: ignore[name-defined]
        logger.info("FastAPI instrumentation applied")
    except Exception as exc:
        logger.warning("FastAPI instrumentation failed", error=str(exc))


@asynccontextmanager
async def trace_span(name: str, **attrs: str | int | float) -> AsyncIterator[None]:
    """Manual span for RAG pipeline steps."""
    tracer = _get_tracer()
    if tracer is None:
        yield
        return

    with tracer.start_as_current_span(name) as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)
        yield
