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
    labelnames=["organization_id", "status", "method"],
)

rag_rerank_latency = Histogram(
    "rag_rerank_latency_seconds",
    "Latencia de reranking post-retrieval",
    labelnames=["organization_id"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

rag_rerank_top_score = Gauge(
    "rag_rerank_top_score",
    "Score del top-1 tras rerank (último request)",
    labelnames=["organization_id"],
)

rag_feedback_approval_rate = Gauge(
    "rag_feedback_approval_rate",
    "Tasa de aprobación de feedback humano (0-1)",
    labelnames=["organization_id"],
)

rag_tokens_consumed = Counter(
    "rag_tokens_consumed_total",
    "Total de tokens consumidos por LLM",
    labelnames=["organization_id", "model", "token_type"],  # token_type: prompt | completion | total
)

rag_llm_latency = Histogram(
    "rag_llm_latency_seconds",
    "Latencia de invocación al LLM en segundos",
    labelnames=["organization_id", "model"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

rag_embeddings_latency = Histogram(
    "rag_embeddings_latency_seconds",
    "Latencia de generación de embeddings",
    labelnames=["organization_id", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

rag_vector_search_latency = Histogram(
    "rag_vector_search_latency_seconds",
    "Latencia de búsqueda vectorial en Qdrant",
    labelnames=["organization_id"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

rag_cache_hits = Counter(
    "rag_cache_hits_total",
    "Total de hits en caché de respuestas RAG",
    labelnames=["organization_id"],
)

rag_cache_misses = Counter(
    "rag_cache_misses_total",
    "Total de misses en caché de respuestas RAG",
    labelnames=["organization_id"],
)

rag_errors_total = Counter(
    "rag_errors_total",
    "Total de errores en el flujo RAG",
    labelnames=["organization_id", "error_type"],
)

rag_active_requests = Gauge(
    "rag_active_requests",
    "Número de consultas RAG en proceso",
    labelnames=["organization_id"],
)

rag_lazy_ingestion_triggers_total = Counter(
    "rag_lazy_ingestion_triggers_total",
    "Total de fallbacks de ingesta perezosa disparados",
    labelnames=["organization_id"],
)

rag_lazy_ingestion_rows_indexed = Counter(
    "rag_lazy_ingestion_rows_indexed_total",
    "Filas indexadas por ingesta perezosa",
    labelnames=["organization_id"],
)

rag_lazy_ingestion_latency = Histogram(
    "rag_lazy_ingestion_latency_seconds",
    "Latencia del fallback de ingesta perezosa",
    labelnames=["organization_id"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 4.0, 8.0, 15.0, 30.0),
)

# Knowledge V2 (Phase B+): parseo de documentos estructurados
knowledge_parse_total = Counter(
    "knowledge_parse_total",
    "Documentos parseados por Knowledge V2",
    labelnames=["organization_id", "format", "outcome"],
)

knowledge_parse_latency = Histogram(
    "knowledge_parse_latency_seconds",
    "Latencia de parseo estructurado (Knowledge V2)",
    labelnames=["organization_id", "format"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Knowledge Tabular V2 (Excel/CSV): profiling, detección, dual indexing.
knowledge_tabular_ingestion_total = Counter(
    "knowledge_tabular_ingestion_total",
    "Workbooks tabulares procesados (Excel/CSV)",
    labelnames=["organization_id", "format", "outcome"],
)

knowledge_tabular_parse_latency = Histogram(
    "knowledge_tabular_parse_latency_seconds",
    "Latencia de parseo+persistencia estructurada tabular",
    labelnames=["organization_id", "format"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

knowledge_tabular_tables_detected = Histogram(
    "knowledge_tabular_tables_detected",
    "Tablas detectadas por workbook",
    labelnames=["organization_id", "format"],
    buckets=(0, 1, 2, 3, 5, 8, 13, 21, 50),
)

knowledge_tabular_rows_processed = Counter(
    "knowledge_tabular_rows_processed_total",
    "Filas tabulares procesadas por operación de fingerprint",
    labelnames=["organization_id", "format", "operation"],
)

knowledge_tabular_rows_upserted = Counter(
    "knowledge_tabular_rows_upserted_total",
    "Filas tabulares escritas en la representación estructurada",
    labelnames=["organization_id", "format"],
)

knowledge_tabular_cells_processed = Counter(
    "knowledge_tabular_cells_processed_total",
    "Celdas no vacías procesadas",
    labelnames=["organization_id", "format"],
)

knowledge_tabular_chunks_created = Counter(
    "knowledge_tabular_chunks_created_total",
    "Chunks tabulares creados por nivel jerárquico",
    labelnames=["organization_id", "format", "level"],
)

knowledge_tabular_embeddings_created = Counter(
    "knowledge_tabular_embeddings_created_total",
    "Embeddings tabulares generados (incluye parents)",
    labelnames=["organization_id", "format"],
)

knowledge_tabular_parse_errors = Counter(
    "knowledge_tabular_parse_errors_total",
    "Errores del pipeline tabular por etapa",
    labelnames=["organization_id", "format", "stage"],
)

knowledge_tabular_schema_changes = Counter(
    "knowledge_tabular_schema_changes_total",
    "Tablas con schema_hash distinto en re-ingesta",
    labelnames=["organization_id", "format"],
)

knowledge_tabular_quality_warnings = Counter(
    "knowledge_tabular_quality_warnings_total",
    "Warnings del reporte de calidad tabular por código",
    labelnames=["organization_id", "format", "code"],
)

# Retrieval: latencia por etapa (query embedding, dense/sparse, rerank, total).
rag_retrieval_stage_latency = Histogram(
    "rag_retrieval_stage_latency_seconds",
    "Latencia por etapa del retrieval (tool-level y orquestador)",
    labelnames=["organization_id", "stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Phase F: retrieval V2 en sombra (comparar contra V1 sin cambiar la respuesta)
knowledge_shadow_retrievals_total = Counter(
    "knowledge_shadow_retrievals_total",
    "Retrievals V2 en sombra ejecutados (orchestrator)",
    labelnames=["organization_id", "intent"],
)

knowledge_shadow_overlap = Gauge(
    "knowledge_shadow_overlap",
    "Overlap de content_hash V1 vs V2 en el top-k (último shadow)",
    labelnames=["organization_id"],
)

knowledge_shadow_latency = Histogram(
    "knowledge_shadow_latency_seconds",
    "Latencia del retrieval V2 en sombra",
    labelnames=["organization_id"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# -----------------------------------------------------------------------------
# Zent Intelligence Layer — Answerability Engine (PHASE 23)
# Baja cardinalidad: organization_id (+ reason = 10 estados formales).
# -----------------------------------------------------------------------------
rag_answerable_queries_total = Counter(
    "rag_answerable_queries_total",
    "Consultas que el Answerability Gate consideró contestables",
    labelnames=["organization_id"],
)

rag_abstained_queries_total = Counter(
    "rag_abstained_queries_total",
    "Consultas abstenidas de forma estructurada (por estado formal)",
    labelnames=["organization_id", "reason"],
)

rag_context_missing_total = Counter(
    "rag_context_missing_total",
    "Abstenciones por CONTEXT_MISSING (data existe sin definición/regla)",
    labelnames=["organization_id"],
)

rag_data_missing_total = Counter(
    "rag_data_missing_total",
    "Abstenciones por DATA_MISSING (información física inexistente/no conectada)",
    labelnames=["organization_id"],
)

rag_ambiguous_queries_total = Counter(
    "rag_ambiguous_queries_total",
    "Consultas ambiguas (AMBIGUOUS o CLARIFICATION_REQUIRED)",
    labelnames=["organization_id"],
)

rag_source_conflicts_total = Counter(
    "rag_source_conflicts_total",
    "Abstenciones por SOURCE_CONFLICT (fuentes contradictorias)",
    labelnames=["organization_id"],
)

rag_execution_failures_total = Counter(
    "rag_execution_failures_total",
    "Abstenciones por EXECUTION_FAILED (ejecución fallida sin evidencia)",
    labelnames=["organization_id"],
)

rag_sql_repair_attempts_total = Counter(
    "rag_sql_repair_attempts_total",
    "Intentos de reparación del SQL Expert (loop prevention incluida)",
    labelnames=["organization_id"],
)

rag_agent_loop_preventions_total = Counter(
    "rag_agent_loop_preventions_total",
    "Operaciones idénticas bloqueadas por loop prevention",
    labelnames=["organization_id", "scope"],  # scope: sql_repair | agent_runtime
)

# -----------------------------------------------------------------------------
# Zent Discovery Engine & Semantic Catalog (FASE 24)
# -----------------------------------------------------------------------------
rag_discovery_jobs_total = Counter(
    "rag_discovery_jobs_total",
    "Jobs de discovery ejecutados por el Discovery Engine",
    labelnames=["organization_id", "engine", "status"],
)

rag_discovery_duration_seconds = Histogram(
    "rag_discovery_duration_seconds",
    "Duración de scans de discovery",
    labelnames=["organization_id"],
    buckets=(1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

rag_catalog_objects_total = Counter(
    "rag_catalog_objects_total",
    "Objetos registrados en el catálogo",
    labelnames=["organization_id", "object_type"],
)

rag_inferred_relationships_total = Counter(
    "rag_inferred_relationships_total",
    "Relaciones inferidas sin FK declarada",
    labelnames=["organization_id"],
)

rag_approved_relationships_total = Counter(
    "rag_approved_relationships_total",
    "Relaciones confirmadas/aprobadas",
    labelnames=["organization_id"],
)

rag_unknown_codes_total = Counter(
    "rag_unknown_codes_total",
    "Columnas categóricas sin significado documentado (UNDEFINED_ENUM)",
    labelnames=["organization_id"],
)

rag_semantic_suggestions_total = Counter(
    "rag_semantic_suggestions_total",
    "Sugerencias semánticas creadas",
    labelnames=["organization_id", "type"],
)

rag_semantic_suggestions_approved_total = Counter(
    "rag_semantic_suggestions_approved_total",
    "Sugerencias semánticas aprobadas por humanos",
    labelnames=["organization_id"],
)

rag_context_readiness = Gauge(
    "rag_context_readiness",
    "Context Readiness global (último cálculo, 0-100)",
    labelnames=["organization_id"],
)

# -----------------------------------------------------------------------------
# Governed Learning (FASE 25)
# -----------------------------------------------------------------------------
rag_context_gaps_total = Counter(
    "rag_context_gaps_total",
    "Gaps de contexto registrados",
    labelnames=["organization_id", "type"],
)

rag_context_gaps_resolved_total = Counter(
    "rag_context_gaps_resolved_total",
    "Gaps resueltos",
    labelnames=["organization_id"],
)

rag_semantic_approvals_total = Counter(
    "rag_semantic_approvals_total",
    "Aprobaciones de conocimiento semántico",
    labelnames=["organization_id", "knowledge_type"],
)

rag_semantic_rejections_total = Counter(
    "rag_semantic_rejections_total",
    "Rechazos de conocimiento semántico",
    labelnames=["organization_id"],
)

rag_answerability_rate = Gauge(
    "rag_answerability_rate",
    "Tasa de answerability (último cálculo, 0-100)",
    labelnames=["organization_id"],
)

rag_unsupported_question_rate = Gauge(
    "rag_unsupported_question_rate",
    "Tasa de preguntas no soportadas (último cálculo, 0-100)",
    labelnames=["organization_id"],
)

rag_context_gap_resolution_time = Histogram(
    "rag_context_gap_resolution_time_seconds",
    "Tiempo entre creación y resolución de gaps",
    labelnames=["organization_id"],
    buckets=(60, 600, 3600, 86400, 604800, 2592000),
)

rag_spider_scan_duration_seconds = Histogram(
    "rag_spider_scan_duration_seconds",
    "Duración de scans del Zent Spider",
    labelnames=["organization_id"],
    buckets=(1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

rag_spider_findings_total = Counter(
    "rag_spider_findings_total",
    "Hallazgos del Zent Spider",
    labelnames=["organization_id", "kind"],
)

rag_knowledge_invalidations_total = Counter(
    "rag_knowledge_invalidations_total",
    "Invalidaciones de conocimiento por revocación",
    labelnames=["organization_id"],
)

# -----------------------------------------------------------------------------
# Knowledge Learning Engine (FASE 33)
# -----------------------------------------------------------------------------
knowledge_learning_runs_total = Counter(
    "knowledge_learning_runs_total",
    "Runs de aprendizaje de conocimiento",
    labelnames=["organization_id", "trigger", "status"],
)

knowledge_learning_duration_seconds = Histogram(
    "knowledge_learning_duration_seconds",
    "Duración de runs de aprendizaje",
    labelnames=["organization_id"],
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 900.0),
)

knowledge_learning_failures_total = Counter(
    "knowledge_learning_failures_total",
    "Fallos de runs de aprendizaje",
    labelnames=["organization_id"],
)

knowledge_entities_discovered_total = Counter(
    "knowledge_entities_discovered_total",
    "Entidades de negocio detectadas por el Learning Engine",
    labelnames=["organization_id"],
)

knowledge_relationships_discovered_total = Counter(
    "knowledge_relationships_discovered_total",
    "Relaciones detectadas por el Learning Engine",
    labelnames=["organization_id"],
)

knowledge_readiness_score = Gauge(
    "knowledge_readiness_score",
    "Knowledge Readiness (último cálculo, 0-100)",
    labelnames=["organization_id", "scope"],
)

knowledge_learning_fingerprints_updated_total = Counter(
    "knowledge_learning_fingerprints_updated_total",
    "Fingerprints de schema actualizados (posible invalidación de cache LLM)",
    labelnames=["organization_id"],
)

knowledge_llm_requests_total = Counter(
    "knowledge_llm_requests_total",
    "Llamadas LLM del Learning Engine (completed|cached|failed|skipped)",
    labelnames=["organization_id", "status"],
)

knowledge_llm_tokens_total = Counter(
    "knowledge_llm_tokens_total",
    "Tokens consumidos por el Learning Engine",
    labelnames=["organization_id", "token_type"],
)

knowledge_llm_latency_seconds = Histogram(
    "knowledge_llm_latency_seconds",
    "Latencia de llamadas LLM del Learning Engine",
    labelnames=["organization_id"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

knowledge_evaluation_runs_total = Counter(
    "knowledge_evaluation_runs_total",
    "Auto-evaluaciones RAG del Learning Engine",
    labelnames=["organization_id", "status"],
)

knowledge_evaluation_composite = Gauge(
    "knowledge_evaluation_composite",
    "Score compuesto de la última auto-evaluación (0-1)",
    labelnames=["organization_id"],
)


# Decision Engine — low-cardinality labels only (no org/capability id).
zent_decision_requests_total = Counter(
    "zent_decision_requests_total",
    "Decision Engine evaluations",
    labelnames=["provider", "resolved"],
)
zent_decision_provider_total = Counter(
    "zent_decision_provider_total",
    "Decision Engine provider invocations",
    labelnames=["provider"],
)
zent_decision_latency_seconds = Histogram(
    "zent_decision_latency_seconds",
    "Decision Engine latency",
    labelnames=["provider"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
zent_decision_confidence = Histogram(
    "zent_decision_confidence",
    "Decision confidence (0-1)",
    labelnames=["provider"],
    buckets=(0.1, 0.25, 0.5, 0.65, 0.8, 0.9, 0.95, 1.0),
)
zent_decision_fallback_total = Counter(
    "zent_decision_fallback_total",
    "Decision Engine fallbacks",
    labelnames=["reason"],
)
zent_decision_agreement_total = Counter(
    "zent_decision_agreement_total",
    "Shadow agreement between JEV and the live path",
    labelnames=["agreed"],
)
zent_decision_cost_usd = Counter(
    "zent_decision_cost_usd",
    "Estimated Decision Engine cost in USD",
    labelnames=["provider"],
)
zent_decision_capability_total = Counter(
    "zent_decision_capability_total",
    "Selected capability family (not full id)",
    labelnames=["capability"],
)
zent_decision_judge_total = Counter(
    "zent_decision_judge_total",
    "System One judge calls (non-routing questions)",
    labelnames=["outcome", "phase"],
)
zent_decision_judge_tokens_total = Counter(
    "zent_decision_judge_tokens_total",
    "Tokens spent on System One judge calls",
    labelnames=["kind", "phase"],
)
zent_decision_judge_latency_seconds = Histogram(
    "zent_decision_judge_latency_seconds",
    "System One judge latency by phase",
    labelnames=["phase"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 8.0),
)
zent_decision_judge_cost_usd = Counter(
    "zent_decision_judge_cost_usd",
    "Estimated System One judge cost in USD by phase",
    labelnames=["phase"],
)
zent_decision_traces_total = Counter(
    "zent_decision_traces_total",
    "Decision traces written",
    labelnames=["provider"],
)
zent_decision_judge_dedup_total = Counter(
    "zent_decision_judge_dedup_total",
    "JEV judge calls avoided by the request-scoped judgment cache",
    labelnames=["phase"],
)
zent_decision_batch_total = Counter(
    "zent_decision_batch_total",
    "Batched JEV phase calls (one per compatible state)",
    labelnames=["mode", "phase", "outcome"],
)
zent_decision_batch_questions_per_call = Histogram(
    "zent_decision_batch_questions_per_call",
    "Atomic questions per batched JEV call",
    labelnames=["phase"],
    buckets=(1, 2, 4, 6, 8, 12, 16, 24, 32),
)
zent_decision_batch_shadow_total = Counter(
    "zent_decision_batch_shadow_total",
    "Legacy vs batched agreement observed in shadow mode",
    labelnames=["phase", "agreement"],
)
# --- JEV Preflight: juicio barato antes de pagar generación cara -------------
zent_decision_preflight_total = Counter(
    "zent_decision_preflight_total",
    "Preflight packs executed by phase and outcome",
    labelnames=["mode", "phase", "outcome"],
)
zent_decision_preflight_questions_total = Counter(
    "zent_decision_preflight_questions_total",
    "Atomic questions answered by the preflight, by phase and primitive",
    labelnames=["phase", "type"],
)
zent_decision_preflight_escalation_total = Counter(
    "zent_decision_preflight_escalation_total",
    "Composed escalation decisions (action + tier)",
    labelnames=["mode", "action", "tier"],
)
zent_decision_preflight_avoided_total = Counter(
    "zent_decision_preflight_avoided_total",
    "Expensive LLM calls avoided by a judgment (no invented baseline)",
    labelnames=["reason"],
)
zent_decision_preflight_uncertain_total = Counter(
    "zent_decision_preflight_uncertain_total",
    "Critical judgments left uncertain (information, not success)",
    labelnames=["phase"],
)
# --- Response Intelligence: forma de explicar --------------------------------
zent_response_section_labels_stripped_total = Counter(
    "zent_response_section_labels_stripped_total",
    "Internal section labels leaked by the model and removed from the answer",
)
zent_adaptive_passage_judge_total = Counter(
    "zent_adaptive_passage_judge_total",
    "Passage judge verdicts composed in code",
    labelnames=["verdict"],
)
zent_adaptive_injection_suspected_total = Counter(
    "zent_adaptive_injection_suspected_total",
    "Retrieved passages flagged as suspected prompt injection",
    labelnames=["stage"],
)
zent_adaptive_claim_verdict_total = Counter(
    "zent_adaptive_claim_verdict_total",
    "Claim verification verdicts",
    labelnames=["verdict"],
)
zent_adaptive_claims_ledger_total = Counter(
    "zent_adaptive_claims_ledger_total",
    "Claim ledger writes from claim verification",
    labelnames=["outcome"],
)
zent_decision_candidates_total = Histogram(
    "zent_decision_candidates_total",
    "Authorized candidates offered to JEV per kind",
    labelnames=["kind"],
    buckets=(0, 1, 2, 3, 5, 8, 13, 21),
)
zent_decision_candidates_rejected_total = Counter(
    "zent_decision_candidates_rejected_total",
    "Candidates rejected by the deterministic resolver",
    labelnames=["kind", "reason"],
)
zent_decision_target_selection_total = Counter(
    "zent_decision_target_selection_total",
    "Target selection outcomes (JEV choice + policy)",
    labelnames=["mode", "kind", "action"],
)
zent_decision_policy_total = Counter(
    "zent_decision_policy_total",
    "Policy results by reason",
    labelnames=["reason", "risk"],
)

zent_adaptive_requests_total = Counter(
    "zent_adaptive_requests_total",
    "Adaptive RAG plans",
    labelnames=["mode", "path", "applied"],
)
zent_adaptive_strategy_total = Counter(
    "zent_adaptive_strategy_total",
    "Adaptive retrieval strategy",
    labelnames=["strategy"],
)
zent_adaptive_source_route_total = Counter(
    "zent_adaptive_source_route_total",
    "Adaptive source route",
    labelnames=["route"],
)
zent_adaptive_retrieval_attempts = Histogram(
    "zent_adaptive_retrieval_attempts",
    "Retrieval attempts per request",
    buckets=(1, 2, 3, 4, 5),
)
zent_adaptive_top_k = Histogram(
    "zent_adaptive_top_k",
    "Dynamic context top_k",
    buckets=(1, 3, 5, 8, 12, 20, 50),
)
zent_adaptive_evidence_quality = Histogram(
    "zent_adaptive_evidence_quality",
    "Evidence quality score (0-1)",
    buckets=(0.1, 0.25, 0.5, 0.65, 0.8, 0.9, 1.0),
)
zent_adaptive_decision_confidence = Histogram(
    "zent_adaptive_decision_confidence",
    "Adaptive plan confidence (0-1)",
    buckets=(0.1, 0.25, 0.5, 0.65, 0.8, 0.9, 1.0),
)
zent_adaptive_grounding_score = Histogram(
    "zent_adaptive_grounding_score",
    "Grounding score (0-1)",
    buckets=(0.1, 0.25, 0.5, 0.65, 0.8, 0.9, 1.0),
)
zent_adaptive_context_tokens = Histogram(
    "zent_adaptive_context_tokens",
    "Context tokens before/after packing",
    labelnames=["stage"],
    buckets=(32, 64, 128, 256, 512, 1024, 2048, 4096, 8192),
)
zent_adaptive_llm_skipped_total = Counter(
    "zent_adaptive_llm_skipped_total",
    "Generative LLM calls avoided by Adaptive RAG",
)
zent_adaptive_cache_hit_total = Counter(
    "zent_adaptive_cache_hit_total",
    "Adaptive plan cache hits",
    labelnames=["kind"],
)
zent_adaptive_fallback_total = Counter(
    "zent_adaptive_fallback_total",
    "Adaptive RAG fallbacks",
    labelnames=["reason"],
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
