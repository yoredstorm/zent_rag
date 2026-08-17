# =============================================================================
# Prometheus Metrics — Exposición de métricas para scraping
# =============================================================================
# Usa prometheus-fastapi-instrumentator para exponer automáticamente:
# - http_requests_total (contador por method, handler, status)
# - http_request_duration_seconds (histograma de latencia)
# - http_requests_in_flight (gauge de requests concurrentes)
#
# Métricas personalizadas: tokens consumidos, latencia del LLM, errores.
# =============================================================================
from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_fastapi_instrumentator.metrics import Info

# -----------------------------------------------------------------------------
# Métricas de negocio personalizadas (más allá de las HTTP estándar)
# -----------------------------------------------------------------------------
rag_queries_total = Counter(
    "rag_queries_total",
    "Total de consultas RAG procesadas",
    labelnames=["tenant_id", "status", "method"],
)

rag_rerank_latency = Histogram(
    "rag_rerank_latency_seconds",
    "Latencia de reranking post-retrieval",
    labelnames=["tenant_id"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

rag_rerank_top_score = Gauge(
    "rag_rerank_top_score",
    "Score del top-1 tras rerank (último request)",
    labelnames=["tenant_id"],
)

rag_feedback_approval_rate = Gauge(
    "rag_feedback_approval_rate",
    "Tasa de aprobación de feedback humano (0-1)",
    labelnames=["tenant_id"],
)

rag_tokens_consumed = Counter(
    "rag_tokens_consumed_total",
    "Total de tokens consumidos por LLM",
    labelnames=["tenant_id", "model", "token_type"],  # token_type: prompt | completion | total
)

rag_llm_latency = Histogram(
    "rag_llm_latency_seconds",
    "Latencia de invocación al LLM en segundos",
    labelnames=["tenant_id", "model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

rag_embeddings_latency = Histogram(
    "rag_embeddings_latency_seconds",
    "Latencia de generación de embeddings",
    labelnames=["tenant_id", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

rag_vector_search_latency = Histogram(
    "rag_vector_search_latency_seconds",
    "Latencia de búsqueda vectorial en Qdrant",
    labelnames=["tenant_id"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

rag_cache_hits = Counter(
    "rag_cache_hits_total",
    "Total de hits en caché de respuestas RAG",
    labelnames=["tenant_id"],
)

rag_cache_misses = Counter(
    "rag_cache_misses_total",
    "Total de misses en caché de respuestas RAG",
    labelnames=["tenant_id"],
)

rag_errors_total = Counter(
    "rag_errors_total",
    "Total de errores en el flujo RAG",
    labelnames=["tenant_id", "error_type"],
)

rag_active_requests = Gauge(
    "rag_active_requests",
    "Número de consultas RAG en proceso",
    labelnames=["tenant_id"],
)

rag_lazy_ingestion_triggers_total = Counter(
    "rag_lazy_ingestion_triggers_total",
    "Total de fallbacks de ingesta perezosa disparados",
    labelnames=["tenant_id"],
)

rag_lazy_ingestion_rows_indexed = Counter(
    "rag_lazy_ingestion_rows_indexed_total",
    "Filas indexadas por ingesta perezosa",
    labelnames=["tenant_id"],
)

rag_lazy_ingestion_latency = Histogram(
    "rag_lazy_ingestion_latency_seconds",
    "Latencia del fallback de ingesta perezosa",
    labelnames=["tenant_id"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 4.0, 8.0, 15.0, 30.0),
)


def setup_metrics(app: FastAPI) -> Instrumentator:
    """Configura y expone /metrics para Prometheus scraping.

    Incluye métricas HTTP estándar + custom business metrics.
    """
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=False,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        inprogress_name="http_requests_in_flight",
        inprogress_labels=True,
        body_handlers=[],
    )

    instrumentator.add(
        metrics.request_size(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
        )
    ).add(
        metrics.response_size(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
        )
    ).add(
        metrics.latency(
            metric_name="http_request_duration_seconds",
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
        )
    ).add(
        metrics.requests(
            metric_name="http_requests_total",
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
        )
    )

    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)

    return instrumentator
