# =============================================================================
# Knowledge Learning Orchestrator — pipeline explícito de aprendizaje (FASE 33)
# =============================================================================
# CONNECTION -> DISCOVERY -> PROFILING -> SEMANTIC ANALYSIS -> RELATIONSHIPS
# -> ... -> KNOWLEDGE READINESS
#
# - Reutiliza Discovery Engine, SemanticInference, RelationshipDetector y
#   CatalogStore: el Learning Engine ENRIQUECE lo existente, no lo reemplaza.
# - Cada etapa registra timestamps, métricas y eventos reales (durables).
# - Ningún estado de UI se simula: todo proviene de knowledge_learning_steps,
#   knowledge_events y knowledge_scores.
# - El LLM nunca es la única fuente de verdad (FASE 33B lo integra).
# =============================================================================
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from src.catalog.inference import SemanticInference
from src.catalog.jobs import resolve_source_runtime, run_physical_discovery
from src.catalog.relationships import (
    RelationshipDetector,
    publish_relationship_suggestions,
)
from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.base import ConnectorError
from src.core.config import get_settings
from src.core.domain.knowledge_learning import (
    PHASE1_ACTIVE_STAGES,
    PHASE1_STAGE_WEIGHTS,
    KnowledgeEventType,
    KnowledgeGate,
    LearningStage,
    LearningTrigger,
    stage_label,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    knowledge_entities_discovered_total,
    knowledge_learning_duration_seconds,
    knowledge_learning_failures_total,
    knowledge_learning_fingerprints_updated_total,
    knowledge_learning_runs_total,
    knowledge_relationships_discovered_total,
)
from src.intelligence.store import PostgresIntelligenceStore
from src.platform.knowledge_learning.business_analyzer import BusinessAnalyzer
from src.platform.knowledge_learning.evaluation import KnowledgeEvaluationService
from src.platform.knowledge_learning.events import KnowledgeEventEmitter
from src.platform.knowledge_learning.knowledge_score import KnowledgeScoreService
from src.platform.knowledge_learning.llm_analyzer import (
    LLMAnalyzer,
    select_tables_for_analysis,
)
from src.platform.knowledge_learning.question_generator import QuestionGenerator
from src.platform.knowledge_learning.relationship_analyzer import (
    RelationshipAnalyzer,
)
from src.platform.knowledge_learning.repository import (
    PostgresKnowledgeLearningRepository,
)
from src.platform.knowledge_learning.schema_analyzer import SchemaAnalyzer

logger = get_logger(__name__)

LEARNING_JOB_PREFIX = "knowledge_learning"


class _RunCancelledError(RuntimeError):
    """El run fue cancelado durante la ejecución (finalización limpia)."""

# Límite de eventos detallados por run (los agregados siempre se emiten).
_MAX_DETAIL_EVENTS = 1000


class _StageProgress:
    """Progreso real: suma de pesos de etapas completadas (sin timers)."""

    def __init__(self, stages: tuple[LearningStage, ...]) -> None:
        self._weights = {
            stage: PHASE1_STAGE_WEIGHTS.get(stage, 0) for stage in stages
        }
        self._total = max(sum(self._weights.values()), 1)
        self._completed = 0

    def overall(self, stage: LearningStage | None = None, stage_progress: int = 0) -> int:
        current = (
            self._weights.get(stage, 0) * max(0, min(100, stage_progress)) / 100
            if stage is not None
            else 0.0
        )
        return int(round((self._completed + current) / self._total * 100))

    def complete(self, stage: LearningStage) -> int:
        self._completed += self._weights.get(stage, 0)
        return self.overall()


def _llm_completion_message(table: str, result: dict) -> str:
    status = result.get("status")
    if status == "cached":
        return f"{table}: análisis reutilizado desde cache (schema sin cambios)."
    if status == "failed":
        error = result.get("error") or "error desconocido"
        return f"{table}: el LLM no pudo analizarla ({str(error)[:120]})."
    if status == "skipped":
        reason = result.get("error") or "sin proveedor"
        return f"{table}: análisis LLM omitido ({str(reason)[:120]})."
    confidence = result.get("confidence")
    confidence_text = (
        f" (confianza {round(float(confidence) * 100)}%)"
        if isinstance(confidence, (int, float))
        else ""
    )
    summary = (result.get("reasoning_summary") or "").strip()
    base = f"Hipótesis semántica generada para {table}{confidence_text}."
    return f"{base} {summary[:220]}" if summary else base


class KnowledgeLearningEngine:
    """Ejecuta el pipeline de aprendizaje con jobs durables (patrón FASE 24)."""

    def __init__(
        self,
        *,
        job_repo: Any,
        connector_repo: Any,
        catalog_store: PostgresCatalogStore | None = None,
        intelligence_store: PostgresIntelligenceStore | None = None,
        secret_store: Any | None = None,
        llm_provider: Any | None = None,
        repository: PostgresKnowledgeLearningRepository | None = None,
        score_service: KnowledgeScoreService | None = None,
        backoff_base_seconds: int = 10,
        max_attempts_default: int = 3,
    ) -> None:
        self._jobs = job_repo
        self._connectors = connector_repo
        self._store = catalog_store or PostgresCatalogStore()
        self._intel = intelligence_store or PostgresIntelligenceStore()
        self._secrets = secret_store
        self._llm = llm_provider
        self._repo = repository or PostgresKnowledgeLearningRepository()
        self._events = KnowledgeEventEmitter(self._repo)
        self._score = score_service or KnowledgeScoreService(
            self._store, repository=self._repo
        )
        self._backoff_base = backoff_base_seconds
        self._max_attempts = max_attempts_default

    # ------------------------------------------------------------------ start
    def _active_stages(self) -> tuple[LearningStage, ...]:
        """Etapas reales según feature flags (nunca etapas simuladas)."""
        settings = get_settings()
        stages = list(PHASE1_ACTIVE_STAGES)
        if settings.RAG_KNOWLEDGE_LLM_ANALYSIS_ENABLED:
            stages.insert(
                stages.index(LearningStage.DETECTING_RELATIONSHIPS),
                LearningStage.LLM_REASONING,
            )
        if settings.RAG_KNOWLEDGE_EVALUATION_ENABLED:
            stages.insert(stages.index(LearningStage.SCORING), LearningStage.EVALUATING)
        return tuple(stages)

    async def start_run(
        self,
        organization_id: UUID,
        *,
        catalog_source_id: UUID,
        workspace_id: UUID | None = None,
        kb_source_id: UUID | None = None,
        training_run_id: UUID | None = None,
        trigger: str = LearningTrigger.MANUAL.value,
        created_by: UUID | None = None,
    ) -> dict:
        """Crea el run + steps y encola el job durable.

        Raises:
            ValueError: fuente inexistente (404 en API).
            ActiveRunExistsError: ya hay un run activo para la fuente (409).
        """
        await self._repo.ensure_tables()
        source = await self._store.get_source(organization_id, catalog_source_id)
        if source is None:
            raise ValueError("catalog_source_not_found")

        run = await self._repo.create_run(
            organization_id,
            catalog_source_id=catalog_source_id,
            workspace_id=workspace_id,
            kb_source_id=kb_source_id,
            training_run_id=training_run_id,
            trigger=trigger,
            created_by=created_by,
        )
        await self._repo.create_steps(
            organization_id,
            UUID(run["id"]),
            [stage.value for stage in self._active_stages()],
        )

        job = await self._jobs.create_job(
            organization_id,
            job_type=f"{LEARNING_JOB_PREFIX}:run",
            source_id=None,
            knowledge_base_id=kb_source_id,
        )
        await self._jobs.update_job(
            job.id,
            cursor_snapshot={
                "run_id": run["id"],
                "catalog_source_id": str(catalog_source_id),
                "workspace_id": str(workspace_id) if workspace_id else None,
                "trigger": trigger,
            },
        )
        try:
            from src.knowledge.queue import enqueue_knowledge_job

            await enqueue_knowledge_job(str(job.id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning job enqueue failed", error=str(exc)[:200])
        return {"run": run, "job_id": str(job.id), "queued": True}

    # ------------------------------------------------------------------ entry
    async def execute_job(self, job_id: UUID) -> Any:
        """Ejecuta el job durable (worker). Retorna el job actualizado."""
        job = await self._jobs.get_job(None, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        if job.is_terminal:
            return job

        cursor = job.cursor_snapshot or {}
        run_id_raw = cursor.get("run_id")
        if not run_id_raw:
            raise ValueError("Learning job missing run_id in cursor")
        run_id = UUID(str(run_id_raw))

        run = await self._repo.get_run(job.organization_id, run_id)
        if run is None:
            raise ValueError(f"Learning run {run_id} not found")
        if run["status"] == "completed":
            await self._jobs.update_job(
                job_id,
                status="completed",
                retry_at=None,
                completed_at=datetime.now(timezone.utc),
            )
            return await self._jobs.get_job(None, job_id)
        if run["status"] == "cancelled":
            await self._jobs.update_job(
                job_id,
                status="canceled",
                retry_at=None,
                completed_at=datetime.now(timezone.utc),
                error_summary={"cancelled": True},
            )
            return await self._jobs.get_job(None, job_id)

        await self._jobs.update_job(
            job_id,
            status="running",
            attempts=job.attempts + 1,
            started_at=datetime.now(timezone.utc),
        )
        job = await self._jobs.get_job(None, job_id)
        started = time.perf_counter()
        await self._store.ensure_tables()
        await self._repo.ensure_tables()
        if run["status"] == "cancelled":
            await self._jobs.update_job(
                job_id,
                status="canceled",
                retry_at=None,
                completed_at=datetime.now(timezone.utc),
                error_summary={"cancelled": True},
            )
            return await self._jobs.get_job(None, job_id)
        try:
            await self._execute_run(job, run)
            elapsed = time.perf_counter() - started
            knowledge_learning_duration_seconds.labels(
                organization_id=str(job.organization_id)
            ).observe(elapsed)
            knowledge_learning_runs_total.labels(
                organization_id=str(job.organization_id),
                trigger=run.get("trigger") or "manual",
                status="completed",
            ).inc()
        except _RunCancelledError:
            await self._jobs.update_job(
                job_id,
                status="canceled",
                retry_at=None,
                completed_at=datetime.now(timezone.utc),
                error_summary={"cancelled": True},
            )
            knowledge_learning_runs_total.labels(
                organization_id=str(job.organization_id),
                trigger=run.get("trigger") or "manual",
                status="cancelled",
            ).inc()
            return await self._jobs.get_job(None, job_id)
        except Exception as exc:  # noqa: BLE001
            await self._handle_failure(job, run, exc)
        return await self._jobs.get_job(None, job_id)

    # -------------------------------------------------------------------- run
    async def _execute_run(self, job: Any, run: dict) -> None:
        settings = get_settings()
        org: UUID = job.organization_id
        run_id = UUID(run["id"])
        source_id_raw = run.get("catalog_source_id")
        if not source_id_raw:
            raise ConnectorError("Learning run requires catalog_source_id")
        source_id = UUID(source_id_raw)
        run_steps = await self._repo.list_steps(org, run_id)
        valid_stages = {s.value for s in LearningStage}
        run_stages = tuple(
            LearningStage(step["stage"])
            for step in run_steps
            if step.get("stage") in valid_stages
        )
        if not run_stages:
            run_stages = self._active_stages()
        progress = _StageProgress(run_stages)

        await self._repo.update_run(
            org,
            run_id,
            status="running",
            started_at=datetime.now(timezone.utc),
            finished_at=None,
            gate=None,
            error_summary={},
        )
        await self._emit(
            org,
            KnowledgeEventType.LEARNING_STARTED,
            run_id=run_id,
            source_id=source_id,
            stage=LearningStage.CONNECTING.value,
            message="Zent comenzó a aprender cómo funciona tu negocio.",
            severity="info",
        )

        # ---------------------------------------------------------- CONNECTING
        await self._begin_stage(org, run_id, source_id, LearningStage.CONNECTING, progress)
        source, connector, plugin, budgets = await resolve_source_runtime(
            connector_repo=self._connectors,
            secret_store=self._secrets,
            store=self._store,
            organization_id=org,
            catalog_source_id=source_id,
        )
        await self._end_stage(
            org,
            run_id,
            source_id,
            LearningStage.CONNECTING,
            progress,
            metrics={"engine": connector.type, "connector_id": str(connector.id)},
        )

        # -------------------------------------------------- DISCOVERING_SCHEMA
        await self._begin_stage(
            org, run_id, source_id, LearningStage.DISCOVERING_SCHEMA, progress
        )
        physical = await run_physical_discovery(
            store=self._store,
            intelligence_store=self._intel,
            organization_id=org,
            catalog_source_id=source_id,
            connector_id=connector.id,
            plugin=plugin,
            budgets=budgets,
            scan_type=(
                "scheduled"
                if (run.get("trigger") or "") == LearningTrigger.SCHEDULED.value
                else "manual"
            ),
            profiling_enabled=settings.RAG_CATALOG_PROFILING_ENABLED,
            drift_check_enabled=settings.RAG_CATALOG_DRIFT_CHECK_ENABLED,
        )
        outcome = physical["outcome"]
        adapter = physical["adapter"]
        schema_analysis = await SchemaAnalyzer(self._store).analyze(org, source_id)
        knowledge_learning_fingerprints_updated_total.labels(
            organization_id=str(org)
        ).inc(schema_analysis.fingerprints_updated)
        await self._emit(
            org,
            KnowledgeEventType.SCHEMA_DISCOVERED,
            run_id=run_id,
            source_id=source_id,
            stage=LearningStage.DISCOVERING_SCHEMA.value,
            message=(
                f"Schema descubierto: {schema_analysis.tables_total} tablas, "
                f"{schema_analysis.columns_total} columnas."
            ),
            severity="success",
            payload={
                **schema_analysis.to_metrics(),
                "engine": source.get("engine") or connector.type,
                "partial": bool(outcome.partial),
            },
        )
        for index, table in enumerate(schema_analysis.tables):
            if index >= _MAX_DETAIL_EVENTS:
                break
            await self._emit(
                org,
                KnowledgeEventType.TABLE_ANALYZED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.DISCOVERING_SCHEMA.value,
                message=f"Tabla analizada: {table.qualified_name}.",
                payload={
                    "table": table.qualified_name,
                    "columns": table.columns_total,
                    "primary_keys": table.primary_keys,
                    "fingerprint": table.fingerprint[:16],
                },
            )
        await self._repo.update_run(
            org, run_id, tables_analyzed=schema_analysis.tables_total
        )
        await self._end_stage(
            org,
            run_id,
            source_id,
            LearningStage.DISCOVERING_SCHEMA,
            progress,
            metrics=schema_analysis.to_metrics(),
        )

        # ------------------------------------------------------------ PROFILING
        await self._begin_stage(org, run_id, source_id, LearningStage.PROFILING, progress)
        enum_values = sum(
            len(entry.get("samples", {}) or {}) for entry in outcome.enum_columns
        )
        await self._end_stage(
            org,
            run_id,
            source_id,
            LearningStage.PROFILING,
            progress,
            metrics={
                "profiled_columns": schema_analysis.profiled_columns,
                "enum_columns": len(outcome.enum_columns),
                "enum_columns_with_values": enum_values,
            },
        )

        deep = await adapter.deep_discover()
        tables_meta = await self._store.list_tables(org, source_id, limit=5000)
        inference = SemanticInference(
            self._store,
            llm_provider=self._llm,
            llm_enabled=settings.RAG_KNOWLEDGE_LLM_ANALYSIS_ENABLED,
        )

        # -------------------------------------------------- DETECTING_ENTITIES
        await self._begin_stage(
            org, run_id, source_id, LearningStage.DETECTING_ENTITIES, progress
        )
        entity_suggestions, entity_state = await inference.run_entities(
            organization_id=org,
            catalog_source_id=source_id,
            deep=deep,
            tables_meta=tables_meta,
        )
        for index, entity in enumerate(entity_suggestions):
            if index >= _MAX_DETAIL_EVENTS:
                break
            await self._emit(
                org,
                KnowledgeEventType.ENTITY_DETECTED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.DETECTING_ENTITIES.value,
                message=f"Entidad detectada: {entity['entity']}.",
                severity="success",
                payload={
                    "entity": entity["entity"],
                    "entity_id": entity.get("entity_id"),
                    "table": entity.get("table"),
                    "confidence": entity.get("confidence"),
                    "evidence": entity.get("evidence") or [],
                },
            )
        knowledge_entities_discovered_total.labels(
            organization_id=str(org)
        ).inc(len(entity_state))
        await self._repo.update_run(
            org, run_id, entities_detected=len(entity_state)
        )
        await self._end_stage(
            org,
            run_id,
            source_id,
            LearningStage.DETECTING_ENTITIES,
            progress,
            metrics={
                "entities_detected": len(entity_state),
                "entities_new": len(entity_suggestions),
            },
        )

        # ---------------------------------------------------- ANALYZING_FIELDS
        await self._begin_stage(
            org, run_id, source_id, LearningStage.ANALYZING_FIELDS, progress
        )
        field_suggestions = await inference.run_fields(
            organization_id=org,
            catalog_source_id=source_id,
            deep=deep,
            state=entity_state,
        )
        field_mappings = [
            item for item in field_suggestions if item.get("type") == "field_mapping"
        ]
        conflicting = [item for item in field_mappings if item.get("conflicting")]
        for index, field in enumerate(field_mappings):
            if index >= _MAX_DETAIL_EVENTS:
                break
            await self._emit(
                org,
                KnowledgeEventType.FIELD_DETECTED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.ANALYZING_FIELDS.value,
                message=(
                    f"Campo detectado: {field['entity']}.{field['field']} "
                    f"(desde {field['column']})."
                ),
                payload={
                    "entity": field["entity"],
                    "field": field["field"],
                    "field_id": field.get("field_id"),
                    "column": field["column"],
                    "confidence": field.get("confidence"),
                    "role": field.get("role"),
                    "conflicting": bool(field.get("conflicting")),
                    "evidence": field.get("evidence") or [],
                },
            )
        await self._repo.update_run(
            org, run_id, fields_detected=len(field_mappings)
        )
        await self._end_stage(
            org,
            run_id,
            source_id,
            LearningStage.ANALYZING_FIELDS,
            progress,
            metrics={
                "fields_detected": len(field_mappings),
                "conflicting_fields": len(conflicting),
            },
        )

        # ------------------------------------------------- LLM_REASONING (33B)
        if LearningStage.LLM_REASONING in run_stages:
            await self._begin_stage(
                org, run_id, source_id, LearningStage.LLM_REASONING, progress
            )
            llm_metrics = await self._run_llm_analysis(
                org, run_id=run_id, source_id=source_id, deep=deep
            )
            await self._end_stage(
                org,
                run_id,
                source_id,
                LearningStage.LLM_REASONING,
                progress,
                metrics=llm_metrics,
            )

        # --------------------------------------------- DETECTING_RELATIONSHIPS
        await self._begin_stage(
            org, run_id, source_id, LearningStage.DETECTING_RELATIONSHIPS, progress
        )
        detector = RelationshipDetector(self._store, budgets=budgets)
        relationships = await detector.detect(
            organization_id=org,
            catalog_source_id=source_id,
            deep=deep,
        )
        intelligence_metrics: dict = {}
        try:
            llm_analyses: list[dict] = []
            if LearningStage.LLM_REASONING in run_stages:
                llm_analyses = await self._repo.list_llm_analyses(
                    org, source_id=source_id, limit=500
                )
            intelligence_metrics = await RelationshipAnalyzer(self._store).apply(
                org,
                source_id,
                deep=deep,
                llm_analyses=llm_analyses,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Relationship intelligence failed; deterministic results kept",
                organization_id=str(org),
                error=str(exc)[:200],
            )
        suggestions_created = await publish_relationship_suggestions(
            store=self._store,
            organization_id=org,
            catalog_source_id=source_id,
        )
        created_hypotheses = intelligence_metrics.pop("created_hypotheses", [])
        for hypothesis in created_hypotheses:
            await self._emit(
                org,
                KnowledgeEventType.RELATIONSHIP_DETECTED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.DETECTING_RELATIONSHIPS.value,
                message=(
                    f"Relación inferida por el LLM: {hypothesis.get('from_column')} "
                    f"-> {hypothesis.get('to_table')}.{hypothesis.get('to_column')} "
                    f"({round(float(hypothesis.get('confidence') or 0) * 100)}%)."
                ),
                payload={**hypothesis, "source": "llm"},
            )
        confirmed = sum(1 for r in relationships if r.get("status") == "confirmed")
        for index, rel in enumerate(relationships):
            if index >= _MAX_DETAIL_EVENTS:
                break
            await self._emit(
                org,
                KnowledgeEventType.RELATIONSHIP_DETECTED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.DETECTING_RELATIONSHIPS.value,
                message=f"Relación detectada: {rel.get('from')} -> {rel.get('to')}.",
                payload={
                    "from": rel.get("from"),
                    "to": rel.get("to"),
                    "relation_type": rel.get("relation_type"),
                    "status": rel.get("status"),
                    "confidence": rel.get("confidence"),
                },
            )
        knowledge_relationships_discovered_total.labels(
            organization_id=str(org)
        ).inc(len(relationships))
        await self._repo.update_run(
            org, run_id, relationships_detected=len(relationships)
        )
        await self._end_stage(
            org,
            run_id,
            source_id,
            LearningStage.DETECTING_RELATIONSHIPS,
            progress,
            metrics={
                "relationships_detected": len(relationships),
                "relationships_confirmed": confirmed,
                "relationships_suggested": len(relationships) - confirmed,
                "suggestions_created": suggestions_created,
                **intelligence_metrics,
            },
        )

        # ------------------------------------------------------------- SCORING
        if LearningStage.GENERATING_QUESTIONS in run_stages:
            await self._begin_stage(
                org, run_id, source_id, LearningStage.GENERATING_QUESTIONS, progress
            )
            questions_metrics = await self._run_question_generation(
                org, run_id=run_id, source_id=source_id
            )
            await self._end_stage(
                org,
                run_id,
                source_id,
                LearningStage.GENERATING_QUESTIONS,
                progress,
                metrics=questions_metrics,
            )

        # ------------------------------------------------------------ EVALUATING
        if LearningStage.EVALUATING in run_stages:
            await self._begin_stage(
                org, run_id, source_id, LearningStage.EVALUATING, progress
            )
            evaluation_metrics = await self._run_evaluation(
                org, run_id=run_id, source_id=source_id
            )
            await self._end_stage(
                org,
                run_id,
                source_id,
                LearningStage.EVALUATING,
                progress,
                metrics=evaluation_metrics,
            )

        # ------------------------------------------------------------- SCORING
        await self._begin_stage(org, run_id, source_id, LearningStage.SCORING, progress)
        score = await self._score.compute(
            org,
            source_id=source_id,
            run_id=run_id,
            active_run={},  # el run actual ya terminó sus etapas
            persist=True,
        )
        await self._emit(
            org,
            KnowledgeEventType.SCORE_COMPUTED,
            run_id=run_id,
            source_id=source_id,
            stage=LearningStage.SCORING.value,
            message=f"Knowledge Readiness: {score.overall:.0f}% ({score.gate.value}).",
            severity="success" if score.gate == KnowledgeGate.READY else "info",
            payload={
                "overall": score.overall,
                "gate": score.gate.value,
                "dimensions": [d.to_dict() for d in score.dimensions],
                "reasons": score.reasons,
            },
        )
        await self._end_stage(
            org,
            run_id,
            source_id,
            LearningStage.SCORING,
            progress,
            metrics={"overall": score.overall, "gate": score.gate.value},
        )

        blocking_questions = 0
        try:
            blocking_questions = await self._repo.count_pending_questions(
                org,
                run_id=run_id,
                priorities=["critical", "high"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Blocking questions lookup failed", error=str(exc)[:200]
            )
        final_status = (
            "awaiting_validation"
            if score.gate == KnowledgeGate.NEEDS_INPUT or blocking_questions > 0
            else "completed"
        )
        percent = 100 if final_status == "completed" else progress.overall()
        await self._repo.update_run(
            org,
            run_id,
            status=final_status,
            current_stage=(
                LearningStage.AWAITING_VALIDATION.value
                if final_status == "awaiting_validation"
                else LearningStage.READY.value
            ),
            overall_progress=percent,
            stage_progress=100,
            gate=score.gate.value,
            finished_at=(
                None
                if final_status == "awaiting_validation"
                else datetime.now(timezone.utc)
            ),
        )
        await self._emit(
            org,
            KnowledgeEventType.LEARNING_COMPLETED,
            run_id=run_id,
            source_id=source_id,
            stage=LearningStage.READY.value,
            message=(
                f"Aprendizaje completado: {len(entity_state)} entidades, "
                f"{len(field_mappings)} campos y {len(relationships)} relaciones."
            ),
            severity="success",
            payload={
                "gate": score.gate.value,
                "overall": score.overall,
                "entities": len(entity_state),
                "fields": len(field_mappings),
                "relationships": len(relationships),
                "blocking_questions": blocking_questions,
            },
        )

        if final_status == "awaiting_validation" and blocking_questions > 0:
            try:
                from src.platform.notifyv2.notifications import notify

                await notify(
                    org,
                    "knowledge.questions_pending",
                    f"Zent necesita tu ayuda: {blocking_questions} pregunta(s) sin responder",
                    (
                        f"El aprendizaje de la fuente detectó {blocking_questions} "
                        "conceptos que requieren tu validación para mejorar el "
                        "conocimiento y el score."
                    ),
                    data={
                        "run_id": str(run_id),
                        "source_id": str(source_id),
                        "pending_questions": blocking_questions,
                        "overall": score.overall,
                    },
                    channels={"in_app"},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Pending-questions notification failed",
                    organization_id=str(org),
                    error=str(exc)[:200],
                )

        await self._jobs.update_job(
            job.id,
            status="completed",
            progress=100,
            records_processed=schema_analysis.tables_total,
            completed_at=datetime.now(timezone.utc),
            retry_at=None,
            error_summary={},
        )
        logger.info(
            "Knowledge learning run finished",
            organization_id=str(org),
            run_id=str(run_id),
            source_id=str(source_id),
            gate=score.gate.value,
            overall=score.overall,
        )

    # ------------------------------------------------------------ evaluation
    async def _run_evaluation(
        self,
        organization_id: UUID,
        *,
        run_id: UUID,
        source_id: UUID,
    ) -> dict:
        """Auto-evaluación RAG: el sistema se examina a sí mismo (FASE 33G)."""
        settings = get_settings()
        await self._emit(
            organization_id,
            KnowledgeEventType.EVALUATION_STARTED,
            run_id=run_id,
            source_id=source_id,
            stage=LearningStage.EVALUATING.value,
            message=(
                "Zent se evalúa a sí mismo con preguntas sintéticas "
                "derivadas del catálogo."
            ),
            payload={
                "max_questions": settings.RAG_KNOWLEDGE_EVALUATION_MAX_QUESTIONS,
                "judge_enabled": settings.RAG_KNOWLEDGE_EVALUATION_JUDGE,
            },
        )
        service = KnowledgeEvaluationService(self._store, self._repo)
        try:
            result = await service.run(
                organization_id,
                source_id=source_id,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Auto-evaluation stage failed; knowledge follows without it",
                organization_id=str(organization_id),
                error=str(exc)[:300],
            )
            await self._emit(
                organization_id,
                KnowledgeEventType.EVALUATION_COMPLETED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.EVALUATING.value,
                message="La auto-evaluación falló; el score queda sin medir.",
                severity="warning",
                payload={"status": "failed", "error": str(exc)[:300]},
            )
            return {"status": "failed", "error": str(exc)[:300]}

        if result.get("status") == "skipped":
            await self._emit(
                organization_id,
                KnowledgeEventType.EVALUATION_COMPLETED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.EVALUATING.value,
                message=(
                    "Auto-evaluación omitida: "
                    + ("sin preguntas justificables del catálogo."
                       if result.get("reason") == "no_synthetic_questions"
                       else "infraestructura no disponible.")
                ),
                severity="info",
                payload={"status": "skipped", "reason": result.get("reason")},
            )
            return {
                "status": "skipped",
                "reason": result.get("reason"),
                "questions": 0,
            }

        summary_metrics: dict = {
            "status": result.get("status"),
            "questions": result.get("questions") or 0,
            "failed_cases": result.get("failed_cases") or 0,
            "composite_score": result.get("composite_score"),
            "judge_enabled": (result.get("quality") or {}).get("judge_enabled", False),
            "tokens": (result.get("performance") or {}).get("total_tokens") or 0,
            "cost": (result.get("performance") or {}).get("total_cost") or 0.0,
        }
        quality = result.get("quality") or {}
        for key in (
            "retrieval_precision",
            "retrieval_recall",
            "answer_relevance",
            "faithfulness",
            "citation_accuracy",
        ):
            if quality.get(key) is not None:
                summary_metrics[key] = quality[key]
        await self._emit(
            organization_id,
            KnowledgeEventType.EVALUATION_COMPLETED,
            run_id=run_id,
            source_id=source_id,
            stage=LearningStage.EVALUATING.value,
            message=(
                f"Auto-evaluación completada: "
                f"{(result.get('composite_score') or 0) * 100:.0f}% compuesto "
                f"sobre {result.get('questions') or 0} preguntas."
            ),
            severity=(
                "success"
                if (result.get("composite_score") or 0) >= 0.6
                else "warning"
            ),
            payload={"status": "completed", **summary_metrics},
        )
        return summary_metrics

    # ------------------------------------------------------------- questions
    async def _run_question_generation(
        self,
        organization_id: UUID,
        *,
        run_id: UUID,
        source_id: UUID,
    ) -> dict:
        """Genera preguntas de negocio desde ambigüedad real (nunca genéricas)."""
        settings = get_settings()
        llm_analyses: list[dict] = []
        if settings.RAG_KNOWLEDGE_AI_QUESTIONS_ENABLED:
            try:
                llm_analyses = await self._repo.list_llm_analyses(
                    organization_id, source_id=source_id, limit=500
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LLM analyses lookup for questions failed",
                    error=str(exc)[:200],
                )
        generator = QuestionGenerator(self._store, self._repo)
        try:
            result = await generator.generate(
                organization_id,
                source_id=source_id,
                run_id=run_id,
                llm_analyses=llm_analyses,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Question generation failed",
                organization_id=str(organization_id),
                error=str(exc)[:300],
            )
            return {"generated": 0, "error": str(exc)[:300]}

        for question in result.get("questions", []):
            critical = question.get("priority") == "critical"
            await self._emit(
                organization_id,
                KnowledgeEventType.QUESTION_GENERATED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.GENERATING_QUESTIONS.value,
                message=f"Nueva pregunta: {question.get('title', '')[:180]}",
                severity="warning" if critical else "info",
                payload={
                    "question_id": question.get("id"),
                    "question_type": question.get("question_type"),
                    "priority": question.get("priority"),
                    "priority_score": question.get("priority_score"),
                    "evidence": question.get("evidence") or [],
                    "options": question.get("options") or [],
                },
            )
        return {
            "candidates": result.get("candidates", 0),
            "generated": result.get("generated", 0),
            "updated": result.get("updated", 0),
            "critical": result.get("critical", 0),
            "high": result.get("high", 0),
            "by_type": result.get("by_type", {}),
            "by_priority": result.get("by_priority", {}),
        }

    # ------------------------------------------------------------- llm stage
    async def _run_llm_analysis(
        self,
        organization_id: UUID,
        *,
        run_id: UUID,
        source_id: UUID,
        deep: Any,
    ) -> dict:
        """Análisis LLM por tabla (1 llamada por tabla) con fallback heurístico."""
        settings = get_settings()
        analyzer = LLMAnalyzer(
            repository=self._repo,
            catalog_store=self._store,
            llm_provider=self._llm,
        )
        metrics: dict = {
            "tables_selected": 0,
            "completed": 0,
            "cached": 0,
            "failed": 0,
            "skipped": 0,
            "tokens_input": 0,
            "tokens_output": 0,
            "estimated_cost": 0.0,
            "fields_enriched": 0,
            "suggestions_created": 0,
            "questions_detected": 0,
            "aborted": False,
        }
        if not analyzer.available:
            metrics["skipped"] = 1
            metrics["reason"] = "llm_provider_unavailable"
            await self._emit(
                organization_id,
                KnowledgeEventType.LLM_ANALYSIS_COMPLETED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.LLM_REASONING.value,
                message=(
                    "Análisis LLM omitido: proveedor no disponible. "
                    "Zent continúa con heurísticas deterministas."
                ),
                severity="warning",
                payload={"skipped": True, "reason": "llm_provider_unavailable"},
            )
            return metrics

        index = await analyzer.build_source_index(
            organization_id, source_id, deep=deep
        )
        selected = select_tables_for_analysis(
            index.tables,
            max_tables=settings.RAG_KNOWLEDGE_LLM_MAX_TABLES_PER_RUN,
            relationships=index.relationships,
        )
        metrics["tables_selected"] = len(selected)
        business = BusinessAnalyzer(self._store)

        for table in selected:
            table_id_raw = table.get("id")
            if not table_id_raw:
                continue
            qualified = table.get("qualified_name") or table.get("table_name", "")
            try:
                columns = await self._store.list_columns(
                    organization_id, UUID(table_id_raw)
                )
            except Exception:  # noqa: BLE001
                columns = []
            if not columns:
                metrics["skipped"] += 1
                continue
            try:
                context = await analyzer.build_table_context(
                    organization_id,
                    source_id=source_id,
                    table=table,
                    index=index,
                )
            except Exception as exc:  # noqa: BLE001
                metrics["failed"] += 1
                logger.warning(
                    "LLM table context build failed",
                    table=qualified,
                    error=str(exc)[:200],
                )
                continue

            await self._emit(
                organization_id,
                KnowledgeEventType.LLM_ANALYSIS_STARTED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.LLM_REASONING.value,
                message=f"Analizando {qualified} con el LLM…",
                payload={
                    "table": qualified,
                    "fingerprint": context.fingerprint[:16],
                    "context_digest": context.sanitized.digest,
                    "context_meta": context.sanitized.meta,
                    "model": (
                        settings.RAG_KNOWLEDGE_LLM_MODEL
                        or settings.LITELLM_DEFAULT_MODEL
                    ),
                },
            )
            result = await analyzer.analyze_table(
                organization_id,
                source_id=source_id,
                context=context,
                run_id=run_id,
            )
            status = result.get("status", "failed")
            if status in ("completed", "cached"):
                metrics[status] += 1
            elif status == "skipped":
                metrics["skipped"] += 1
            else:
                metrics["failed"] += 1
            metrics["tokens_input"] += int(result.get("tokens_input") or 0)
            metrics["tokens_output"] += int(result.get("tokens_output") or 0)
            metrics["estimated_cost"] = round(
                float(metrics["estimated_cost"])
                + float(result.get("estimated_cost") or 0.0),
                6,
            )

            enrichment: dict = {}
            if result.get("analysis"):
                try:
                    outcome = await business.apply(
                        organization_id,
                        source_id=source_id,
                        run_id=run_id,
                        analysis=result["analysis"],
                        context=context,
                    )
                    enrichment = outcome.to_metrics()
                    metrics["fields_enriched"] += outcome.fields_enriched
                    metrics["suggestions_created"] += outcome.suggestions_created
                    metrics["questions_detected"] += outcome.questions_detected
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Business analysis apply failed",
                        table=qualified,
                        error=str(exc)[:200],
                    )
                    metrics["enrich_failures"] = (
                        int(metrics.get("enrich_failures", 0)) + 1
                    )

            await self._emit(
                organization_id,
                KnowledgeEventType.LLM_ANALYSIS_COMPLETED,
                run_id=run_id,
                source_id=source_id,
                stage=LearningStage.LLM_REASONING.value,
                message=_llm_completion_message(qualified, result),
                severity=(
                    "success"
                    if status in ("completed", "cached")
                    else ("warning" if status == "failed" else "info")
                ),
                payload={
                    "table": qualified,
                    "status": status,
                    "cached": bool(result.get("cached")),
                    "model": result.get("model"),
                    "confidence": result.get("confidence"),
                    "reasoning_summary": result.get("reasoning_summary"),
                    "tokens_input": result.get("tokens_input"),
                    "tokens_output": result.get("tokens_output"),
                    "latency_ms": result.get("latency_ms"),
                    "estimated_cost": result.get("estimated_cost"),
                    "context_digest": context.sanitized.digest,
                    "context_meta": context.sanitized.meta,
                    "enrichment": enrichment,
                    "error": result.get("error"),
                },
            )
            if metrics["failed"] >= 3:
                metrics["aborted"] = True
                metrics["abort_reason"] = "consecutive_failures"
                await self._emit(
                    organization_id,
                    KnowledgeEventType.LLM_ANALYSIS_COMPLETED,
                    run_id=run_id,
                    source_id=source_id,
                    stage=LearningStage.LLM_REASONING.value,
                    message=(
                        "Análisis LLM detenido por fallos consecutivos; "
                        "el pipeline continúa con heurísticas."
                    ),
                    severity="warning",
                    payload={"aborted": True, "reason": "consecutive_failures"},
                )
                break

        try:
            run = await self._repo.get_run(organization_id, run_id)
            merged = {**(run.get("metrics") or {}), "llm": metrics}
            await self._repo.update_run(organization_id, run_id, metrics=merged)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM run metrics persist failed", error=str(exc)[:200])
        return metrics

    # ---------------------------------------------------------------- failure
    async def _handle_failure(self, job: Any, run: dict, exc: Exception) -> None:
        org: UUID = job.organization_id
        run_id = UUID(run["id"])
        error_text = f"{type(exc).__name__}: {exc}"[:2000]
        stage = run.get("current_stage") or LearningStage.CONNECTING.value
        try:
            await self._repo.fail_step(org, run_id, stage, error_text)
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._repo.update_run(
                org,
                run_id,
                status="failed",
                finished_at=datetime.now(timezone.utc),
                error_summary={
                    "error": error_text,
                    "stage": stage,
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._emit(
                org,
                KnowledgeEventType.LEARNING_FAILED,
                run_id=run_id,
                source_id=(
                    UUID(run["catalog_source_id"])
                    if run.get("catalog_source_id")
                    else None
                ),
                stage=stage,
                message=f"El aprendizaje falló en la etapa {stage_label(stage)}.",
                severity="error",
                payload={"error": error_text, "stage": stage},
            )
        except Exception:  # noqa: BLE001
            pass

        try:
            await self._jobs.record_error(job.id, job.attempts, error_text)
        except Exception:  # noqa: BLE001
            pass
        if job.attempts >= (job.max_attempts or self._max_attempts):
            await self._jobs.update_job(
                job.id,
                status="dead",
                completed_at=datetime.now(timezone.utc),
                error_summary={"error": error_text, "attempts": job.attempts},
            )
        else:
            delay = min(
                self._backoff_base * (2 ** max(job.attempts - 1, 0)), 300
            )
            await self._jobs.update_job(
                job.id,
                status="failed",
                retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
                error_summary={
                    "error": error_text,
                    "attempts": job.attempts,
                    "retry_at_seconds": delay,
                },
            )
        knowledge_learning_failures_total.labels(
            organization_id=str(org)
        ).inc()
        knowledge_learning_runs_total.labels(
            organization_id=str(org),
            trigger=run.get("trigger") or "manual",
            status="failed",
        ).inc()
        logger.warning(
            "Knowledge learning run failed",
            organization_id=str(org),
            run_id=str(run_id),
            stage=stage,
            error=error_text,
        )

    # ---------------------------------------------------------------- helpers
    async def _begin_stage(
        self,
        organization_id: UUID,
        run_id: UUID,
        source_id: UUID,
        stage: LearningStage,
        progress: _StageProgress,
    ) -> None:
        if await self._is_cancelled(organization_id, run_id):
            raise _RunCancelledError(str(run_id))
        await self._repo.start_step(organization_id, run_id, stage.value, reset=True)
        await self._repo.update_run(
            organization_id,
            run_id,
            current_stage=stage.value,
            stage_progress=0,
            overall_progress=progress.overall(stage, 0),
        )
        await self._emit(
            organization_id,
            KnowledgeEventType.STAGE_STARTED,
            run_id=run_id,
            source_id=source_id,
            stage=stage.value,
            message=f"{stage_label(stage)}…",
            payload={"stage": stage.value, "label": stage_label(stage)},
        )

    async def _end_stage(
        self,
        organization_id: UUID,
        run_id: UUID,
        source_id: UUID,
        stage: LearningStage,
        progress: _StageProgress,
        *,
        metrics: dict | None = None,
    ) -> None:
        await self._repo.complete_step(
            organization_id, run_id, stage.value, metrics=metrics
        )
        overall = progress.complete(stage)
        await self._repo.update_run(
            organization_id,
            run_id,
            stage_progress=100,
            overall_progress=overall,
        )
        await self._emit(
            organization_id,
            KnowledgeEventType.STAGE_COMPLETED,
            run_id=run_id,
            source_id=source_id,
            stage=stage.value,
            message=f"{stage_label(stage)}: completado.",
            severity="success",
            payload={
                "stage": stage.value,
                "label": stage_label(stage),
                "metrics": metrics or {},
                "overall_progress": overall,
            },
        )

    async def _is_cancelled(self, organization_id: UUID, run_id: UUID) -> bool:
        try:
            run = await self._repo.get_run(organization_id, run_id)
            return run is not None and run.get("status") == "cancelled"
        except Exception:  # noqa: BLE001
            return False

    async def _emit(
        self,
        organization_id: UUID,
        event_type: KnowledgeEventType,
        *,
        run_id: UUID | None = None,
        source_id: UUID | None = None,
        stage: str | None = None,
        message: str = "",
        severity: str = "info",
        payload: dict | None = None,
    ) -> None:
        try:
            await self._events.emit(
                organization_id=organization_id,
                event_type=event_type.value,
                message=message,
                run_id=run_id,
                source_id=source_id,
                stage=stage,
                severity=severity,
                payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Knowledge event emit failed",
                event_type=event_type.value,
                error=str(exc)[:200],
            )
