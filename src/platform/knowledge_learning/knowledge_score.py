# =============================================================================
# Knowledge Readiness Score — composición explicable (FASE 33A)
# =============================================================================
# Nunca un % aislado: el score siempre expone dimensiones, pesos y razones.
#
# Dimensiones (configurables por tenant):
#   schema_discovery 15% | semantic_understanding 20% | relationships 15%
#   human_validation 15% | knowledge_coverage 15% | rag_evaluation 15%
#   data_freshness 5%
#
# Gate: NOT_READY | LEARNING | NEEDS_INPUT | READY | DEGRADED.
# El score NO se calcula según cantidad de embeddings: mide entendimiento.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.core.domain.knowledge_learning import (
    DEFAULT_GATE_THRESHOLDS,
    DEFAULT_SCORE_WEIGHTS,
    KnowledgeGate,
    KnowledgeScoreResult,
    ScoreDimension,
    compute_overall,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import knowledge_readiness_score
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_DIMENSION_LABELS = {
    "schema_discovery": "Descubrimiento de schema",
    "semantic_understanding": "Entendimiento semántico",
    "relationships": "Relaciones",
    "human_validation": "Validación humana",
    "knowledge_coverage": "Cobertura de conocimiento",
    "rag_evaluation": "Calidad RAG (evaluación)",
    "data_freshness": "Frescura de datos",
}


class KnowledgeScoreService:
    """Calcula Knowledge Readiness real con razones accionables."""

    def __init__(
        self,
        catalog_store: PostgresCatalogStore,
        *,
        repository=None,
    ) -> None:
        self._store = catalog_store
        self._repo = repository

    # ------------------------------------------------------------------ public
    async def compute(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        run_id: UUID | None = None,
        active_run: dict | None = None,
        persist: bool = True,
    ) -> KnowledgeScoreResult:
        settings = (
            await self._repo.get_settings(organization_id) if self._repo else None
        )
        weights = dict(DEFAULT_SCORE_WEIGHTS)
        thresholds = dict(DEFAULT_GATE_THRESHOLDS)
        if settings:
            weights.update(
                {
                    k: float(v)
                    for k, v in (settings.get("weights") or {}).items()
                    if k in weights and isinstance(v, (int, float))
                }
            )
            thresholds.update(
                {
                    k: float(v)
                    for k, v in (settings.get("thresholds") or {}).items()
                    if k in thresholds and isinstance(v, (int, float))
                }
            )

        stats = await self._collect(organization_id, source_id)
        dimensions = self._dimensions(stats, thresholds, weights)
        score_map = {d.key: (d.score if d.measured else 0.0) for d in dimensions}
        overall = compute_overall(score_map, weights)

        if active_run is None and self._repo is not None:
            try:
                active_run = await self._repo.find_active_run(
                    organization_id, source_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Active run lookup failed", error=str(exc)[:200])

        gate = self._gate(
            overall=overall,
            dimensions={d.key: d for d in dimensions},
            thresholds=thresholds,
            active_run=active_run,
            stats=stats,
        )
        reasons = self._reasons(dimensions, thresholds, stats, gate)

        result = KnowledgeScoreResult(
            organization_id=organization_id,
            source_id=source_id,
            run_id=run_id,
            overall=overall,
            gate=gate,
            dimensions=dimensions,
            reasons=reasons,
            weights=weights,
            computed_at=datetime.now(timezone.utc),
        )
        try:
            knowledge_readiness_score.labels(
                organization_id=str(organization_id),
                scope="source" if source_id else "organization",
            ).set(result.overall)
        except Exception:  # noqa: BLE001
            pass
        if persist and self._repo is not None:
            try:
                await self._repo.upsert_score(
                    organization_id,
                    overall=result.overall,
                    gate=result.gate.value,
                    dimensions=[d.to_dict() for d in result.dimensions],
                    reasons=result.reasons,
                    weights=result.weights,
                    source_id=source_id,
                    run_id=run_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Score persistence failed", error=str(exc)[:200])
        return result

    # ----------------------------------------------------------------- collect
    async def _collect(self, organization_id: UUID, source_id: UUID | None) -> dict:
        """Agregados reales del catálogo (org o fuente). Una query por bloque."""
        source_clause = "AND t.source_id = :sid" if source_id else ""
        q_clause = "AND q.source_id = :sid" if source_id else ""
        params: dict = {"oid": organization_id}
        if source_id:
            params["sid"] = source_id

        stats: dict = {"source_id": str(source_id) if source_id else None}
        session = await get_async_session()
        try:
            schema_row = (
                await session.execute(
                    text(
                        f"""
                        SELECT
                          COUNT(*)::int AS tables_total,
                          COUNT(*) FILTER (WHERE EXISTS (
                            SELECT 1 FROM catalog_columns c
                            WHERE c.table_id = t.id AND c.organization_id = :oid
                          ))::int AS tables_with_columns,
                          COUNT(*) FILTER (WHERE t.table_comment IS NOT NULL
                            AND t.table_comment <> '')::int AS tables_documented
                        FROM catalog_tables t
                        WHERE t.organization_id = :oid AND t.removed_at IS NULL
                          {source_clause}
                        """  # noqa: S608 — source_clause es constante interna
                    ),
                    params,
                )
            ).fetchone()
            stats.update(
                {
                    "tables_total": int(schema_row.tables_total or 0),
                    "tables_with_columns": int(schema_row.tables_with_columns or 0),
                    "tables_documented": int(schema_row.tables_documented or 0),
                }
            )

            col_row = (
                await session.execute(
                    text(
                        f"""
                        SELECT
                          COUNT(*)::int AS columns_total,
                          COUNT(*) FILTER (WHERE c.column_comment IS NOT NULL
                            AND c.column_comment <> '')::int AS columns_documented,
                          COUNT(*) FILTER (WHERE c.is_sensitive)::int AS columns_sensitive
                        FROM catalog_columns c
                        JOIN catalog_tables t ON c.table_id = t.id
                        WHERE c.organization_id = :oid AND t.removed_at IS NULL
                          {source_clause}
                        """  # noqa: S608
                    ),
                    params,
                )
            ).fetchone()
            stats.update(
                {
                    "columns_total": int(col_row.columns_total or 0),
                    "columns_documented": int(col_row.columns_documented or 0),
                    "columns_sensitive": int(col_row.columns_sensitive or 0),
                }
            )

            sem_row = (
                await session.execute(
                    text(
                        f"""
                        SELECT
                          COUNT(f.id)::int AS fields_total,
                          COUNT(f.id) FILTER (WHERE f.status = 'approved')::int
                            AS fields_approved,
                          COUNT(f.id) FILTER (WHERE f.mapped_column_id IS NOT NULL)::int
                            AS fields_mapped
                        FROM catalog_fields f
                        LEFT JOIN catalog_columns c ON f.mapped_column_id = c.id
                        LEFT JOIN catalog_tables t ON c.table_id = t.id
                        WHERE f.organization_id = :oid
                          AND (f.mapped_column_id IS NULL OR t.removed_at IS NULL)
                          {source_clause}
                        """  # noqa: S608
                    ),
                    params,
                )
            ).fetchone()
            stats.update(
                {
                    "fields_total": int(sem_row.fields_total or 0),
                    "fields_approved": int(sem_row.fields_approved or 0),
                    "fields_mapped": int(sem_row.fields_mapped or 0),
                }
            )

            ent_row = (
                await session.execute(
                    text(
                        f"""
                        SELECT
                          COUNT(DISTINCT e.id)::int AS entities_total,
                          COUNT(DISTINCT e.id) FILTER (WHERE e.status = 'approved')::int
                            AS entities_approved,
                          COUNT(DISTINCT e.id) FILTER (WHERE EXISTS (
                            SELECT 1 FROM catalog_fields f
                            WHERE f.entity_id = e.id AND f.organization_id = :oid
                          ))::int AS entities_with_fields,
                          COUNT(DISTINCT e.id) FILTER (WHERE EXISTS (
                            SELECT 1 FROM catalog_relationships r
                            WHERE r.organization_id = :oid AND r.status = 'confirmed'
                              AND (r.from_table_id = e.mapped_table_id
                                   OR r.to_table_id = e.mapped_table_id)
                          ))::int AS entities_with_relationship
                        FROM catalog_entities e
                        LEFT JOIN catalog_tables t ON e.mapped_table_id = t.id
                        WHERE e.organization_id = :oid
                          {source_clause}
                        """  # noqa: S608
                    ),
                    params,
                )
            ).fetchone()
            stats.update(
                {
                    "entities_total": int(ent_row.entities_total or 0),
                    "entities_approved": int(ent_row.entities_approved or 0),
                    "entities_with_fields": int(ent_row.entities_with_fields or 0),
                    "entities_with_relationship": int(
                        ent_row.entities_with_relationship or 0
                    ),
                }
            )

            rel_clause = "AND r.source_id = :sid" if source_id else ""
            rel_row = (
                await session.execute(
                    text(
                        f"""
                        SELECT
                          COUNT(*)::int AS relationships_total,
                          COUNT(*) FILTER (WHERE r.status = 'confirmed')::int
                            AS relationships_confirmed,
                          COUNT(*) FILTER (WHERE r.status = 'suggested')::int
                            AS relationships_suggested
                        FROM catalog_relationships r
                        WHERE r.organization_id = :oid {rel_clause}
                        """  # noqa: S608
                    ),
                    params,
                )
            ).fetchone()
            stats.update(
                {
                    "relationships_total": int(rel_row.relationships_total or 0),
                    "relationships_confirmed": int(rel_row.relationships_confirmed or 0),
                    "relationships_suggested": int(rel_row.relationships_suggested or 0),
                }
            )

            artifact_row = (
                await session.execute(
                    text(
                        f"""
                        SELECT
                          (SELECT COUNT(*) FROM catalog_metrics m
                             WHERE m.organization_id = :oid AND m.status = 'approved')
                            ::int AS metrics_approved,
                          (SELECT COUNT(*) FROM business_definitions d
                             WHERE d.organization_id = :oid AND d.status = 'approved')
                            ::int AS definitions_approved,
                          (SELECT COUNT(*) FROM context_gaps g
                             WHERE g.organization_id = :oid AND g.status = 'open')
                            ::int AS open_gaps,
                          (SELECT COUNT(*) FROM knowledge_questions q
                             WHERE q.organization_id = :oid AND q.status = 'pending'
                             {q_clause})::int AS pending_questions,
                          (SELECT COUNT(*) FROM knowledge_questions q
                             WHERE q.organization_id = :oid AND q.status = 'pending'
                             AND q.priority IN ('critical','high') {q_clause})
                            ::int AS blocking_questions,
                          (SELECT COUNT(*) FROM knowledge_questions q
                             WHERE q.organization_id = :oid AND q.status = 'pending'
                             AND q.priority = 'critical' {q_clause})
                            ::int AS critical_questions
                        """  # noqa: S608 — q_clause es constante interna
                    ),
                    params,
                )
            ).fetchone()
            stats.update(
                {
                    "metrics_approved": int(artifact_row.metrics_approved or 0),
                    "definitions_approved": int(artifact_row.definitions_approved or 0),
                    "open_gaps": int(artifact_row.open_gaps or 0),
                    "pending_questions": int(artifact_row.pending_questions or 0),
                    "blocking_questions": int(artifact_row.blocking_questions or 0),
                    "critical_questions": int(artifact_row.critical_questions or 0),
                }
            )

            # Evaluación: prefiere auto-evaluaciones del Learning Engine
            # (knowledge-auto); cae a cualquier run completado si no existen.
            source_eval_clause = ""
            eval_params = dict(params)
            if source_id:
                source_eval_clause = (
                    "AND summary->'version_snapshot'->>'source_id' = :sid_str"
                )
                eval_params["sid_str"] = str(source_id)
            auto_sql = (
                "SELECT summary FROM eval_runs "
                "WHERE organization_id = :oid AND status = 'completed' "
                "AND dataset_name LIKE 'knowledge-auto%' "
                f"{source_eval_clause} ORDER BY created_at DESC LIMIT 1"  # noqa: S608
            )
            any_sql = (
                "SELECT summary FROM eval_runs "
                "WHERE organization_id = :oid AND status = 'completed' "
                "ORDER BY created_at DESC LIMIT 1"
            )
            eval_row = None
            for sql in (auto_sql, any_sql):
                eval_row = (
                    await session.execute(text(sql), eval_params)
                ).fetchone()
                if eval_row is not None:
                    break
            evaluation: float | None = None
            if eval_row is not None and isinstance(eval_row.summary, dict):
                quality = eval_row.summary.get("quality") or {}
                raw = quality.get("composite_score")
                if isinstance(raw, (int, float)):
                    evaluation = round(float(raw) * 100, 2)
            stats["evaluation_score"] = evaluation

            if source_id:
                fresh_row = (
                    await session.execute(
                        text(
                            "SELECT last_scan_at, phase FROM catalog_sources "
                            "WHERE organization_id = :oid AND id = :sid"
                        ),
                        {"oid": organization_id, "sid": source_id},
                    )
                ).fetchone()
            else:
                fresh_row = (
                    await session.execute(
                        text(
                            "SELECT MAX(last_scan_at) AS last_scan_at, "
                            "COUNT(*) FILTER (WHERE phase IN ('FAILED','PARTIAL'))::int "
                            "AS unhealthy FROM catalog_sources "
                            "WHERE organization_id = :oid"
                        ),
                        {"oid": organization_id},
                    )
                ).fetchone()
            stats["last_scan_at"] = (
                fresh_row.last_scan_at.isoformat()
                if fresh_row is not None and fresh_row.last_scan_at
                else None
            )
            stats["source_unhealthy"] = bool(
                fresh_row is not None
                and getattr(fresh_row, "phase", None) in ("FAILED", "PARTIAL")
            ) or bool(
                fresh_row is not None
                and getattr(fresh_row, "unhealthy", 0)
                and int(getattr(fresh_row, "unhealthy", 0)) > 0
            )
            stats["sources_total"] = 1 if source_id else 0
            if not source_id:
                stats["sources_total"] = int(
                    (
                        await session.execute(
                            text(
                                "SELECT COUNT(*)::int AS n FROM catalog_sources "
                                "WHERE organization_id = :oid"
                            ),
                            {"oid": organization_id},
                        )
                    ).fetchone().n
                    or 0
                )
        finally:
            await session.close()

        # Estado del último run (para LEARNING/DEGRADED).
        if self._repo is not None:
            try:
                runs = await self._repo.list_runs(
                    organization_id,
                    catalog_source_id=source_id,
                    limit=1,
                )
                stats["last_run"] = runs[0] if runs else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Last run lookup failed", error=str(exc)[:200])
                stats["last_run"] = None
        else:
            stats["last_run"] = None
        return stats

    # -------------------------------------------------------------- dimensions
    def _dimensions(
        self, stats: dict, thresholds: dict, weights: dict[str, float]
    ) -> list[ScoreDimension]:
        dims: list[ScoreDimension] = []

        def weight_for(key: str) -> float:
            return round(float(weights.get(key, DEFAULT_SCORE_WEIGHTS.get(key, 0.0))), 4)

        tables_total = stats["tables_total"]
        tables_with_columns = stats["tables_with_columns"]
        schema_score = (
            round(tables_with_columns / tables_total * 100, 2)
            if tables_total
            else 0.0
        )
        dims.append(
            ScoreDimension(
                key="schema_discovery",
                label=_DIMENSION_LABELS["schema_discovery"],
                score=schema_score,
                weight=weight_for("schema_discovery"),
                detail=(
                    f"{tables_with_columns}/{tables_total} tablas con columnas"
                    if tables_total
                    else "Sin tablas descubiertas"
                ),
                measured=tables_total > 0,
            )
        )

        columns_total = stats["columns_total"]
        if columns_total:
            mapped_ratio = stats["fields_mapped"] / columns_total
            description_ratio = (
                stats["tables_documented"] / max(tables_total, 1) * 0.5
                + stats["columns_documented"] / columns_total * 0.5
            )
            semantic_score = round(
                (mapped_ratio * 0.6 + description_ratio * 0.4) * 100, 2
            )
        else:
            semantic_score = 0.0
        dims.append(
            ScoreDimension(
                key="semantic_understanding",
                label=_DIMENSION_LABELS["semantic_understanding"],
                score=semantic_score,
                weight=weight_for("semantic_understanding"),
                detail=(
                    f"{stats['fields_mapped']}/{columns_total} columnas con campo de negocio; "
                    f"{stats['tables_documented']}/{tables_total} tablas documentadas"
                    if columns_total
                    else "Sin columnas registradas"
                ),
                measured=columns_total > 0,
            )
        )

        rels_total = stats["relationships_total"]
        rels_confirmed = stats["relationships_confirmed"]
        if tables_total <= 1:
            relationship_score = 100.0 if tables_total else 0.0
            rel_detail = (
                "Fuente de una sola tabla: sin relaciones posibles"
                if tables_total == 1
                else "Sin tablas"
            )
        else:
            detection = min(1.0, rels_total / max(tables_total - 1, 1))
            confirmation = rels_confirmed / max(rels_total, 1)
            relationship_score = round((detection * 0.5 + confirmation * 0.5) * 100, 2)
            rel_detail = (
                f"{rels_total} detectadas, {rels_confirmed} confirmadas "
                f"({stats['relationships_suggested']} por revisar)"
            )
        dims.append(
            ScoreDimension(
                key="relationships",
                label=_DIMENSION_LABELS["relationships"],
                score=relationship_score,
                weight=weight_for("relationships"),
                detail=rel_detail,
                measured=tables_total > 0,
            )
        )

        entities_total = stats["entities_total"]
        fields_total = stats["fields_total"]
        validation_parts: list[tuple[float, int, int]] = [
            (0.4, stats["entities_approved"], entities_total),
            (0.4, stats["fields_approved"], fields_total),
            (0.2, rels_confirmed, max(rels_total, 0)),
        ]
        validation_score = 0.0
        validation_detail = "Sin conocimiento que validar"
        if entities_total or fields_total or rels_total:
            acc = 0.0
            for weight, approved, total in validation_parts:
                if total:
                    acc += weight * (approved / total)
            validation_score = round(acc * 100, 2)
            validation_detail = (
                f"{stats['entities_approved']}/{entities_total} entidades, "
                f"{stats['fields_approved']}/{fields_total} campos y "
                f"{rels_confirmed}/{rels_total} relaciones validados"
            )
        dims.append(
            ScoreDimension(
                key="human_validation",
                label=_DIMENSION_LABELS["human_validation"],
                score=validation_score,
                weight=weight_for("human_validation"),
                detail=validation_detail,
                measured=bool(entities_total or fields_total or rels_total),
            )
        )

        if entities_total:
            artifacts = stats["metrics_approved"] + stats["definitions_approved"]
            coverage_score = round(
                (
                    stats["entities_with_fields"] / entities_total * 0.4
                    + stats["entities_with_relationship"] / entities_total * 0.3
                    + min(1.0, artifacts / entities_total) * 0.3
                )
                * 100,
                2,
            )
            coverage_detail = (
                f"{stats['entities_with_fields']}/{entities_total} entidades con campos; "
                f"{stats['entities_with_relationship']}/{entities_total} con relaciones; "
                f"{artifacts} métricas/términos aprobados"
            )
        else:
            coverage_score = 0.0
            coverage_detail = "Sin entidades de negocio"
        dims.append(
            ScoreDimension(
                key="knowledge_coverage",
                label=_DIMENSION_LABELS["knowledge_coverage"],
                score=coverage_score,
                weight=weight_for("knowledge_coverage"),
                detail=coverage_detail,
                measured=entities_total > 0,
            )
        )

        evaluation = stats.get("evaluation_score")
        dims.append(
            ScoreDimension(
                key="rag_evaluation",
                label=_DIMENSION_LABELS["rag_evaluation"],
                score=float(evaluation) if evaluation is not None else 0.0,
                weight=weight_for("rag_evaluation"),
                detail=(
                    f"Última evaluación: {round(float(evaluation), 1)}%"
                    if evaluation is not None
                    else "Sin evaluación RAG ejecutada"
                ),
                measured=evaluation is not None,
            )
        )

        freshness = 0.0
        freshness_detail = "Fuente sin escanear"
        stale_days = max(float(thresholds.get("stale_source_days", 14.0)), 1.0)
        last_scan = stats.get("last_scan_at")
        if last_scan:
            try:
                scanned_at = datetime.fromisoformat(last_scan)
                if scanned_at.tzinfo is None:
                    scanned_at = scanned_at.replace(tzinfo=timezone.utc)
                days = max(
                    (datetime.now(timezone.utc) - scanned_at).total_seconds() / 86400,
                    0.0,
                )
                freshness = round(max(0.0, 1.0 - days / stale_days) * 100, 2)
                freshness_detail = f"Último scan hace {round(days, 1)} días"
            except ValueError:
                freshness = 0.0
        dims.append(
            ScoreDimension(
                key="data_freshness",
                label=_DIMENSION_LABELS["data_freshness"],
                score=freshness,
                weight=weight_for("data_freshness"),
                detail=freshness_detail,
                measured=bool(last_scan),
            )
        )
        return dims

    # -------------------------------------------------------------------- gate
    def _gate(
        self,
        *,
        overall: float,
        dimensions: dict[str, ScoreDimension],
        thresholds: dict,
        active_run: dict | None,
        stats: dict,
    ) -> KnowledgeGate:
        last_run = stats.get("last_run") or {}
        if stats.get("source_unhealthy") or last_run.get("status") == "failed":
            return KnowledgeGate.DEGRADED
        if active_run is not None and active_run.get("status") in (
            "queued",
            "running",
            "awaiting_validation",
        ):
            return KnowledgeGate.LEARNING
        if stats.get("critical_questions", 0) > int(
            thresholds.get("critical_questions_max", 0)
        ):
            return KnowledgeGate.NEEDS_INPUT
        evaluation = dimensions["rag_evaluation"]
        if not evaluation.measured:
            return KnowledgeGate.NOT_READY
        schema_ok = dimensions["schema_discovery"].score >= thresholds.get(
            "schema_coverage", 90.0
        )
        semantic_ok = dimensions["semantic_understanding"].score >= thresholds.get(
            "semantic_coverage", 70.0
        )
        eval_ok = evaluation.score >= thresholds.get("evaluation_score", 75.0)
        if (
            overall >= thresholds.get("ready_overall", 80.0)
            and schema_ok
            and semantic_ok
            and eval_ok
        ):
            return KnowledgeGate.READY
        return KnowledgeGate.NOT_READY

    def _reasons(
        self,
        dimensions: list[ScoreDimension],
        thresholds: dict,
        stats: dict,
        gate: KnowledgeGate,
    ) -> list[str]:
        reasons: list[str] = []
        ranked = sorted(
            dimensions,
            key=lambda d: (1 if d.measured else 0, d.score),
        )
        for dim in ranked:
            if dim.score >= 99.0 and dim.measured:
                continue
            if not dim.measured:
                reasons.append(f"{dim.label}: sin medición todavía.")
                continue
            if dim.key == "relationships":
                pending = stats.get("relationships_suggested", 0)
                if pending:
                    reasons.append(
                        f"Faltan confirmar {pending} relaciones importantes."
                    )
                elif dim.score < 100:
                    reasons.append(
                        "Hay tablas sin relaciones descubiertas; revisa el Knowledge Map."
                    )
            elif dim.key == "semantic_understanding":
                reasons.append(
                    f"Entendimiento semántico al {round(dim.score)}%: "
                    f"{dim.detail}."
                )
            elif dim.key == "human_validation":
                reasons.append(
                    f"Validación humana al {round(dim.score)}%: {dim.detail}."
                )
            elif dim.key == "knowledge_coverage":
                reasons.append(
                    f"Cobertura de conocimiento al {round(dim.score)}%: {dim.detail}."
                )
            elif dim.key == "schema_discovery":
                reasons.append(
                    f"Schema al {round(dim.score)}%: {dim.detail}."
                )
            elif dim.key == "rag_evaluation":
                if dim.measured:
                    reasons.append(
                        f"Calidad RAG {round(dim.score)}% "
                        f"(mínimo {round(float(thresholds.get('evaluation_score', 75.0)))}%)."
                    )
            elif dim.key == "data_freshness":
                reasons.append(f"Frescura: {dim.detail}.")
        open_gaps = stats.get("open_gaps", 0)
        if open_gaps:
            reasons.append(f"Hay {open_gaps} gaps de contexto abiertos.")
        blocking = stats.get("blocking_questions", 0)
        if blocking:
            reasons.append(
                f"Hay {blocking} preguntas críticas/altas sin responder."
            )
        if gate == KnowledgeGate.DEGRADED:
            reasons.insert(0, "La fuente está degradada o el último aprendizaje falló.")
        if gate == KnowledgeGate.READY and not reasons:
            reasons.append("Conocimiento listo para producción.")
        return reasons[:8]
