# =============================================================================
# Knowledge Model Service — agregación para la API del Knowledge OS (FASE 34)
# =============================================================================
# Command Center, Explorer, Quality, Gaps, Conflicts, Health.
#
# Reglas:
#   - ERROR != ZERO: si una lectura falla se propaga KnowledgeModelUnavailable
#     (la ruta responde 503 tipado); nunca se devuelve 0 inventado.
#   - Dimensión no medida: measured=False, score=None, excluida del global.
#   - El grafo se deriva del modelo canónico; no hay dataset paralelo.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.core.domain.knowledge_model import (
    BUSINESS_OBJECT_TYPES,
    HealthDimension,
    HealthDimensionKey,
    KnowledgeErrorCode,
    KnowledgeHealth,
    KnowledgeState,
    aggregate_health,
)
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


class KnowledgeModelUnavailable(RuntimeError):
    """Lectura del modelo de conocimiento falló. La UI debe mostrar error."""

    code = KnowledgeErrorCode.MODEL_UNAVAILABLE.value


def _pct(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(1.0, part / total)) * 100.0, 2)


class KnowledgeModelService:
    def __init__(self, repository, materializer) -> None:
        self._repo = repository
        self._materializer = materializer

    # ----------------------------------------------------------- materializar
    async def ensure_materialized(self, organization_id: UUID) -> dict | None:
        """Materializa si el tenant tiene fuentes y aún no hay objetos.

        Idempotente y acotado: si ya hay objetos no hace nada.
        """
        try:
            total = await self._repo.count_objects(
                organization_id, kinds=[t.value for t in BUSINESS_OBJECT_TYPES]
            )
            if total > 0:
                return None
            stats = await self._repo.stats(organization_id)
            if stats["sources"]["total"] <= 0:
                return None
            return await self._materializer.materialize(organization_id)
        except Exception as exc:  # noqa: BLE001
            self._record_failure()
            logger.warning("ensure_materialized failed", error=str(exc)[:240])
            raise KnowledgeModelUnavailable(str(exc)[:240]) from exc

    async def materialize(self, organization_id: UUID, *, source_id: UUID | None = None) -> dict:
        try:
            return await self._materializer.materialize(
                organization_id, source_id=source_id
            )
        except Exception as exc:  # noqa: BLE001
            self._record_failure()
            logger.warning("materialize failed", error=str(exc)[:240])
            raise KnowledgeModelUnavailable(str(exc)[:240]) from exc

    @staticmethod
    def _record_failure() -> None:
        try:
            from src.infrastructure.observability.metrics import (
                knowledge_model_materializations_total,
            )

            knowledge_model_materializations_total.labels(status="failed").inc()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- overview
    async def overview(self, organization_id: UUID) -> dict:
        try:
            stats = await self._repo.stats(organization_id)
            from src.core.config import get_settings

            if (
                stats["objects"]["total"] == 0
                and stats["sources"]["total"] > 0
                and get_settings().KNOWLEDGE_MODEL_AUTO_MATERIALIZE
            ):
                await self._materializer.materialize(organization_id)
                stats = await self._repo.stats(organization_id)
            health = await self.health(organization_id, stats=stats)
            domains = await self._repo.domains(organization_id)
            conflicts = await self._repo.list_conflicts(
                organization_id, status="open", limit=5
            )
            gaps = await self._repo.list_gaps(
                organization_id, status="open", limit=5
            )
            activity = await self._repo.activity(organization_id, limit=12)
            last_run = await self._repo.last_run_summary(organization_id)
        except KnowledgeModelUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("overview failed", error=str(exc)[:240])
            raise KnowledgeModelUnavailable(str(exc)[:240]) from exc

        objects = stats["objects"]
        assertions = stats["assertions"]
        attention: list[dict] = []
        if conflicts:
            attention.append(
                {
                    "kind": "conflict",
                    "severity": "high",
                    "count": stats["conflicts"]["open"],
                    "title": f"{stats['conflicts']['open']} conflicto(s) sin resolver",
                    "href": "/knowledge/quality?tab=conflicts",
                }
            )
        if assertions["low_confidence"]:
            attention.append(
                {
                    "kind": "low_confidence",
                    "severity": "medium",
                    "count": assertions["low_confidence"],
                    "title": (
                        f"{assertions['low_confidence']} afirmación(es) con baja confianza"
                    ),
                    "href": "/knowledge/quality?tab=confidence",
                }
            )
        if assertions["unsupported"]:
            attention.append(
                {
                    "kind": "unsupported",
                    "severity": "medium",
                    "count": assertions["unsupported"],
                    "title": (
                        f"{assertions['unsupported']} afirmación(es) sin evidencia"
                    ),
                    "href": "/knowledge/quality?tab=evidence",
                }
            )
        if stats["sources"]["degraded"]:
            attention.append(
                {
                    "kind": "source_failure",
                    "severity": "high",
                    "count": stats["sources"]["degraded"],
                    "title": f"{stats['sources']['degraded']} fuente(s) con problemas",
                    "href": "/knowledge/sources",
                }
            )
        if stats["gaps"]["high"]:
            attention.append(
                {
                    "kind": "gap",
                    "severity": "high",
                    "count": stats["gaps"]["high"],
                    "title": f"{stats['gaps']['high']} gap(s) de alto impacto",
                    "href": "/knowledge/quality?tab=gaps",
                }
            )
        if objects["undescribed"]:
            attention.append(
                {
                    "kind": "missing_description",
                    "severity": "low",
                    "count": objects["undescribed"],
                    "title": f"{objects['undescribed']} objeto(s) sin descripción",
                    "href": "/knowledge/quality?tab=descriptions",
                }
            )

        domains_with_objects = [d for d in domains if d["objects"] > 0]
        indexed = stats["indexed"]
        state = KnowledgeState.EMPTY.value
        if objects["total"] > 0:
            overall = health.overall
            state = (
                KnowledgeState.READY.value
                if overall is not None and overall >= 75 and stats["conflicts"]["open"] == 0
                else KnowledgeState.PARTIAL.value
            )
        if state != KnowledgeState.EMPTY.value:
            headline = f"Zent entiende {len(domains_with_objects)} área(s) de tu negocio"
        elif indexed["documents"] > 0:
            headline = (
                f"Zent indexó {indexed['documents']} documento(s) de "
                f"{indexed['sources']} fuente(s); todavía no tiene modelo de negocio."
            )
        else:
            headline = "Zent todavía no tiene conocimiento de tu negocio."
        return {
            "state": state,
            "headline": headline,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "health": health.to_dict(),
            "domains": domains,
            "attention": attention,
            "counts": {
                "objects": objects["total"],
                "verified": objects["verified"],
                "inferred": objects["inferred"],
                "discovered": objects["discovered"],
                "assertions": assertions["total"],
                "evidence": stats["evidence"]["total"],
                "edges": stats["edges"]["total"],
                "sources": stats["sources"]["total"],
                "indexed_sources": indexed["sources"],
                "indexed_documents": indexed["documents"],
                "by_type": stats["by_kind"],
            },
            "recent": activity,
            "last_learning": last_run,
            "conflicts_preview": conflicts,
            "gaps_preview": gaps,
            "materialized": objects["total"] > 0,
        }

    # --------------------------------------------------------------- health
    async def health(self, organization_id: UUID, *, stats: dict | None = None) -> KnowledgeHealth:
        stats = stats or await self._repo.stats(organization_id)
        retrieval = await self._repo.retrieval_signals(organization_id)
        objects = stats["objects"]
        assertions = stats["assertions"]
        edges = stats["edges"]
        sources = stats["sources"]
        by_kind = stats["by_kind"]

        entities = int(by_kind.get("entity", {}).get("total", 0))
        attributes = int(by_kind.get("attribute", {}).get("total", 0))
        rules = int(by_kind.get("business_rule", {}).get("total", 0))
        metrics = int(by_kind.get("metric", {}).get("total", 0))
        rules_metrics_verified = int(
            by_kind.get("business_rule", {}).get("verified", 0)
        ) + int(by_kind.get("metric", {}).get("verified", 0))
        terms = int(by_kind.get("term", {}).get("total", 0))
        processes = int(by_kind.get("process", {}).get("total", 0))

        dimensions: list[HealthDimension] = []

        # Cobertura empresarial: conocimiento con evidencia real.
        coverage_measured = objects["total"] > 0
        coverage = _pct(
            objects["total"] - objects["unsupported"], objects["total"]
        ) if coverage_measured else None
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.COVERAGE.value,
                label="Cobertura empresarial",
                score=coverage,
                weight=0.20,
                measured=coverage_measured,
                reason=(
                    f"{objects['total'] - objects['unsupported']} de "
                    f"{objects['total']} objetos tienen evidencia."
                    if coverage_measured
                    else "Todavía no hay objetos de negocio."
                ),
                formula="(objetos con evidencia / objetos de negocio) * 100",
                signals={
                    "objects_total": objects["total"],
                    "objects_with_evidence": objects["total"] - objects["unsupported"],
                    "entities": entities,
                    "attributes": attributes,
                    "terms": terms,
                    "processes": processes,
                },
                missing=[] if coverage_measured else ["objetos de negocio"],
                issues=(
                    [f"{objects['unsupported']} objetos sin evidencia"]
                    if objects["unsupported"]
                    else []
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Comprensión semántica: descripciones + atributos mapeados.
        semantic_measured = objects["total"] > 0
        described = objects["total"] - objects["undescribed"]
        semantic = _pct(described, objects["total"]) if semantic_measured else None
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.SEMANTIC.value,
                label="Comprensión semántica",
                score=semantic,
                weight=0.20,
                measured=semantic_measured,
                reason=(
                    f"{described} de {objects['total']} objetos tienen descripción."
                    if semantic_measured
                    else "Sin objetos que medir."
                ),
                formula="(objetos con descripción / objetos) * 100",
                signals={
                    "described": described,
                    "undescribed": objects["undescribed"],
                    "attributes": attributes,
                    "entities": entities,
                },
                missing=[] if semantic_measured else ["objetos"],
                issues=(
                    [f"{objects['undescribed']} objetos sin descripción"]
                    if objects["undescribed"]
                    else []
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Relaciones: verificadas + comprensión semántica (no solo FKs).
        rel_measured = edges["total"] > 0
        rel_score = None
        if rel_measured:
            verified_share = edges["verified"] / edges["total"]
            semantic_share = edges["semantic"] / edges["total"]
            rel_score = round((verified_share * 0.6 + semantic_share * 0.4) * 100, 2)
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.RELATIONSHIPS.value,
                label="Relaciones",
                score=rel_score,
                weight=0.15,
                measured=rel_measured,
                reason=(
                    f"{edges['verified']} de {edges['total']} relaciones verificadas; "
                    f"{edges['semantic']} son semánticas/negocio."
                    if rel_measured
                    else "Aún no hay relaciones entre objetos."
                ),
                formula="(verificadas/total)*60 + (semánticas/total)*40",
                signals={
                    "edges_total": edges["total"],
                    "verified": edges["verified"],
                    "physical": edges["physical"],
                    "semantic": edges["semantic"],
                },
                missing=[] if rel_measured else ["relaciones"],
                issues=[] if rel_measured else ["Sin relaciones descubiertas"],
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Reglas y métricas.
        rm_total = rules + metrics
        rm_measured = rm_total > 0
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.RULES_METRICS.value,
                label="Reglas y métricas",
                score=_pct(rules_metrics_verified, rm_total) if rm_measured else None,
                weight=0.15,
                measured=rm_measured,
                reason=(
                    f"{rules_metrics_verified} de {rm_total} reglas/métricas verificadas."
                    if rm_measured
                    else "No hay reglas ni métricas definidas."
                ),
                formula="(reglas+métricas verificadas / total reglas+métricas) * 100",
                signals={"rules": rules, "metrics": metrics, "verified": rules_metrics_verified},
                missing=[] if rm_measured else ["reglas", "métricas"],
                issues=(
                    ["Sin métricas definidas"] if metrics == 0 else []
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Calidad de retrieval: evaluación real; si no existe, NO MEDIDO.
        evaluation = retrieval.get("evaluation")
        retrieval_score = None
        retrieval_signals: dict = {
            "traces_total": retrieval["traces"]["total"],
            "traces_failed": retrieval["traces"]["failed"],
        }
        retrieval_reason = "Sin evaluación RAG ejecutada para esta organización."
        if evaluation:
            quality = (evaluation.get("summary") or {}).get("quality") or {}
            composite = quality.get("composite_score")
            if composite is not None:
                retrieval_score = round(float(composite) * 100, 2)
                retrieval_reason = "Última evaluación RAG del tenant."
                retrieval_signals["composite_score"] = composite
                retrieval_signals["evaluated_at"] = evaluation.get("created_at")
        if retrieval["traces"]["total"] > 0:
            failed = retrieval["traces"]["failed"]
            retrieval_signals["failure_rate"] = round(
                failed / retrieval["traces"]["total"], 4
            )
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.RETRIEVAL.value,
                label="Calidad de recuperación",
                score=retrieval_score,
                weight=0.15,
                measured=retrieval_score is not None,
                reason=retrieval_reason,
                formula="composite_score de la última evaluación RAG * 100",
                signals=retrieval_signals,
                missing=[] if retrieval_score is not None else ["evaluación RAG"],
                issues=(
                    [f"{retrieval['traces']['failed']} consultas sin respuesta (30d)"]
                    if retrieval["traces"]["failed"]
                    else []
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Freshness: fuentes escaneadas dentro de la ventana.
        fresh_measured = sources["total"] > 0
        fresh_score = (
            _pct(sources["total"] - sources["stale"], sources["total"])
            if fresh_measured
            else None
        )
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.FRESHNESS.value,
                label="Actualización",
                score=fresh_score,
                weight=0.05,
                measured=fresh_measured,
                reason=(
                    f"{sources['total'] - sources['stale']} de {sources['total']} "
                    "fuentes actualizadas en 14 días."
                    if fresh_measured
                    else "Sin fuentes conectadas."
                ),
                formula="(fuentes frescas / fuentes) * 100",
                signals={"sources_total": sources["total"], "stale": sources["stale"]},
                missing=[] if fresh_measured else ["fuentes"],
                issues=(
                    [f"{sources['stale']} fuentes desactualizadas"]
                    if sources["stale"]
                    else []
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Validación humana.
        validation_measured = objects["total"] > 0
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.VALIDATION.value,
                label="Validación humana",
                score=_pct(objects["verified"], objects["total"]) if validation_measured else None,
                weight=0.10,
                measured=validation_measured,
                reason=(
                    f"{objects['verified']} de {objects['total']} objetos verificados."
                    if validation_measured
                    else "Sin objetos que validar."
                ),
                formula="(objetos verificados / objetos) * 100",
                signals={
                    "verified": objects["verified"],
                    "assertions_verified": assertions["verified"],
                    "assertions_total": assertions["total"],
                },
                missing=[] if validation_measured else ["objetos"],
                issues=(
                    ["Ningún objeto verificado por una persona"]
                    if validation_measured and objects["verified"] == 0
                    else []
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Conflictos: 100 sin conflictos, baja con cada conflicto abierto.
        conflicts_measured = objects["total"] > 0
        conflicts_score = (
            round(max(0.0, 1.0 - min(1.0, stats["conflicts"]["open"] / 5.0)) * 100, 2)
            if conflicts_measured
            else None
        )
        dimensions.append(
            HealthDimension(
                key=HealthDimensionKey.CONFLICTS.value,
                label="Conflictos",
                score=conflicts_score,
                weight=0.05,
                measured=conflicts_measured,
                reason=(
                    f"{stats['conflicts']['open']} conflicto(s) abiertos."
                    if conflicts_measured
                    else "Sin conocimiento que pueda entrar en conflicto."
                ),
                formula="100 * (1 - min(1, conflictos_abiertos / 5))",
                signals={
                    "open_conflicts": stats["conflicts"]["open"],
                    "conflicted_assertions": assertions["conflicted"],
                },
                missing=[] if conflicts_measured else ["objetos"],
                issues=(
                    [f"{stats['conflicts']['open']} conflictos sin resolver"]
                    if stats["conflicts"]["open"]
                    else []
                ),
                updated_at=datetime.now(timezone.utc),
            )
        )

        overall, measured_count = aggregate_health(dimensions)
        state = (
            KnowledgeState.EMPTY.value
            if objects["total"] == 0 and sources["total"] == 0
            else KnowledgeState.PARTIAL.value
        )
        if state != KnowledgeState.EMPTY.value and measured_count == len(dimensions):
            state = KnowledgeState.READY.value
        return KnowledgeHealth(
            overall=overall,
            measured_dimensions=measured_count,
            total_dimensions=len(dimensions),
            dimensions=dimensions,
            state=state,
        )

    # ---------------------------------------------------------------- objetos
    async def get_object(self, organization_id: UUID, object_id: UUID) -> dict | None:
        return await self._repo.get_object(organization_id, object_id)

    async def object_edges(
        self,
        organization_id: UUID,
        object_id: UUID,
        *,
        limit: int = 200,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> dict:
        return await self._repo.object_edges(
            organization_id, object_id, limit=limit, source_ids=source_ids
        )

    async def object_assertions(
        self,
        organization_id: UUID,
        object_id: UUID,
        *,
        limit: int = 100,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> list[dict]:
        return await self._repo.object_assertions(
            organization_id, object_id, limit=limit, source_ids=source_ids
        )

    async def object_evidence(self, organization_id: UUID, object_id: UUID) -> list[dict]:
        return await self._repo.object_evidence(organization_id, object_id)

    async def object_versions(self, organization_id: UUID, object_id: UUID) -> list[dict]:
        return await self._repo.object_versions(organization_id, object_id)

    async def lineage(self, organization_id: UUID, object_id: UUID) -> dict:
        return await self._repo.lineage(organization_id, object_id)

    async def impact(self, organization_id: UUID, object_id: UUID) -> dict:
        return await self._repo.impact(organization_id, object_id)

    async def domains(self, organization_id: UUID) -> list[dict]:
        return await self._repo.domains(organization_id)

    # ------------------------------------------------------------------ delta
    #: Ventanas soportadas por Knowledge Delta (horas reales).
    DELTA_WINDOWS: dict[str, int] = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}

    async def delta(
        self,
        organization_id: UUID,
        *,
        window: str = "24h",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict:
        """Qué cambió en la ventana: agregado real, sin inventar variaciones."""
        now = datetime.now(timezone.utc)
        until_dt = until or now
        if window == "custom":
            if since is None:
                raise ValueError("window=custom requiere since")
            since_dt = since
        else:
            hours = self.DELTA_WINDOWS.get(window)
            if hours is None:
                raise ValueError(f"window inválida: {window}")
            since_dt = since or (until_dt - timedelta(hours=hours))
        if since_dt >= until_dt:
            raise ValueError("since debe ser anterior a until")
        span_hours = (until_dt - since_dt).total_seconds() / 3600
        bucket = "hour" if span_hours <= 72 else "day"
        try:
            raw = await self._repo.delta(
                organization_id, since=since_dt, until=until_dt, bucket=bucket
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("delta failed", error=str(exc)[:240])
            raise KnowledgeModelUnavailable(str(exc)[:240]) from exc

        by_kind = {row["kind"]: row["total"] for row in raw["objects"]}
        totals = {
            "objects": sum(row["total"] for row in raw["objects"]),
            "entities": by_kind.get("entity", 0),
            "concepts": by_kind.get("concept", 0),
            "relationships": raw["relationships"]["total"],
            "facts": raw["facts"]["total"],
            "rules": by_kind.get("business_rule", 0),
            "metrics": by_kind.get("metric", 0) + by_kind.get("kpi", 0),
            "terms": by_kind.get("term", 0) + by_kind.get("synonym", 0),
            "processes": by_kind.get("process", 0),
            "evidence": raw["evidence"],
            "sources": raw["sources"],
            "conflicts_resolved": raw["conflicts"]["resolved"],
            "conflicts_detected": raw["conflicts"]["detected"],
        }
        return {
            "window": window,
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "bucket": bucket,
            "totals": totals,
            "by_type": raw["objects"],
            "enriched": raw["enriched"],
            "enriched_total": raw["enriched_total"],
            "by_domain": raw["by_domain"],
            "timeline": raw["timeline"],
            "computed_at": now.isoformat(),
        }

    async def search(self, organization_id: UUID, q: str, *, limit: int = 10) -> dict:
        return await self._repo.search(organization_id, q, limit=limit)

    async def lookup_aliases(
        self,
        organization_id: UUID,
        normalized: list[str],
        *,
        limit: int = 50,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> list[dict]:
        return await self._repo.lookup_aliases(
            organization_id, normalized, limit=limit, source_ids=source_ids
        )

    async def find_objects_by_names(
        self,
        organization_id: UUID,
        names: list[str],
        *,
        kinds: tuple[str, ...] | None = None,
        limit: int = 20,
        source_ids: tuple[UUID, ...] | None = None,
    ) -> list[dict]:
        kwargs: dict = {"limit": limit, "source_ids": source_ids}
        if kinds is not None:
            kwargs["kinds"] = tuple(kinds)
        return await self._repo.find_objects_by_names(
            organization_id, names, **kwargs
        )

    async def graph(self, organization_id: UUID, **kwargs) -> dict:
        return await self._repo.graph(organization_id, **kwargs)

    async def object_detail(self, organization_id: UUID, object_id: UUID) -> dict | None:
        obj = await self._repo.get_object(organization_id, object_id)
        if obj is None:
            return None
        edges = await self._repo.object_edges(organization_id, object_id)
        assertions = await self._repo.object_assertions(organization_id, object_id)
        evidence = await self._repo.object_evidence(organization_id, object_id)
        versions = await self._repo.object_versions(organization_id, object_id)
        lineage = await self._repo.lineage(organization_id, object_id)
        impact = await self._repo.impact(organization_id, object_id)
        questions = [
            q
            for q in await self._repo.pending_questions(organization_id, limit=100)
            if q.get("entity_id") == str(object_id)
        ]
        return {
            "object": obj,
            "edges": edges["edges"],
            "assertions": assertions,
            "evidence": evidence,
            "versions": versions,
            "lineage": lineage,
            "impact": impact,
            "questions": questions,
        }

    async def list_objects(self, organization_id: UUID, **filters) -> dict:
        kinds = filters.pop("types", None)
        kind_list = None
        if kinds:
            kind_list = [k.strip().lower() for k in kinds if k.strip()]
        items = await self._repo.list_objects(
            organization_id, kinds=kind_list, **filters
        )
        total = await self._repo.count_objects(
            organization_id,
            kinds=kind_list,
            domain=filters.get("domain"),
            status=filters.get("status"),
            source_id=filters.get("source_id"),
        )
        return {"items": items, "count": len(items), "total": total}

    # ----------------------------------------------------------------- gaps
    async def gaps(
        self,
        organization_id: UUID,
        *,
        status: str | None = "open",
        gap_type: str | None = None,
        priority: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        gaps = await self._repo.list_gaps(
            organization_id,
            status=status,
            gap_type=gap_type,
            priority=priority,
            limit=limit,
            offset=offset,
        )
        questions = await self._repo.pending_questions(organization_id, limit=limit)
        question_gaps = [
            {
                "id": q["id"],
                "type": _question_gap_type(q["question_type"]),
                "concept": q["title"],
                "title": q["title"],
                "description": q["body"],
                "priority": q["priority"],
                "priority_score": q["priority_score"],
                "status": "open",
                "occurrences": 1,
                "question": q["title"],
                "impact": q["impact"],
                "impact_objects": int(q["impact"].get("affected_objects", 0) or 0),
                "object_id": q["entity_id"],
                "source_id": q["source_id"],
                "evidence_hints": q["evidence"] if isinstance(q["evidence"], list) else [],
                "first_seen_at": q["created_at"],
                "last_seen_at": q["created_at"],
                "origin": "knowledge_question",
            }
            for q in questions
        ]
        merged = [{**g, "origin": "context_gap"} for g in gaps] + question_gaps
        merged.sort(key=lambda g: g.get("priority_score") or 0, reverse=True)
        return {
            "gaps": merged,
            "count": len(merged),
            "open": len(merged),
            "critical": len([g for g in merged if g["priority"] == "critical"]),
        }

    async def resolve_gap(
        self,
        organization_id: UUID,
        gap_id: UUID,
        *,
        user_id: UUID | None,
        status: str,
        note: str | None,
    ) -> bool:
        return await self._repo.resolve_gap(
            organization_id, gap_id, user_id=user_id, status=status, note=note
        )

    # ------------------------------------------------------------ conflictos
    async def conflicts(
        self, organization_id: UUID, *, status: str | None = "open", limit: int = 100
    ) -> dict:
        items = await self._repo.list_conflicts(
            organization_id, status=status, limit=limit
        )
        return {"conflicts": items, "count": len(items)}

    async def resolve_conflict(
        self,
        organization_id: UUID,
        conflict_id: UUID,
        *,
        resolution: str,
        resolved_value: str | None,
        user_id: UUID | None,
        reason: str | None,
    ) -> dict | None:
        return await self._repo.resolve_conflict(
            organization_id,
            conflict_id,
            resolution=resolution,
            resolved_value=resolved_value,
            user_id=user_id,
            reason=reason,
        )

    # -------------------------------------------------------------- quality
    async def quality(self, organization_id: UUID, *, limit: int = 25) -> dict:
        findings = await self._repo.quality_findings(organization_id, limit=limit)
        issues: list[dict] = []

        def add(
            kind: str,
            severity: str,
            title: str,
            items: list[dict],
            action: str,
        ) -> None:
            if not items:
                return
            issues.append(
                {
                    "kind": kind,
                    "severity": severity,
                    "title": title,
                    "count": len(items),
                    "action": action,
                    "items": items,
                }
            )

        add(
            "conflict",
            "high",
            "Conflictos de conocimiento",
            (await self._repo.list_conflicts(organization_id, status="open", limit=limit)),
            "Resolver conflicto",
        )
        add(
            "low_confidence",
            "medium",
            "Afirmaciones de baja confianza",
            findings["low_confidence_assertions"],
            "Verificar o corregir",
        )
        add(
            "unsupported",
            "high",
            "Afirmaciones sin evidencia",
            findings["unsupported_assertions"],
            "Aportar evidencia",
        )
        add(
            "stale",
            "medium",
            "Conocimiento desactualizado",
            findings["stale_objects"],
            "Reprocesar fuente",
        )
        add(
            "orphan",
            "medium",
            "Entidades sin atributos",
            findings["orphan_entities"],
            "Mapear campos",
        )
        add(
            "missing_description",
            "low",
            "Objetos sin descripción",
            findings["missing_descriptions"],
            "Completar definición",
        )
        add(
            "retrieval_failure",
            "high",
            "Consultas sin respuesta (30d)",
            findings["retrieval_failures"],
            "Crear gap de aprendizaje",
        )
        add(
            "source_failure",
            "high",
            "Fuentes con problemas",
            findings["source_failures"],
            "Revisar fuente",
        )
        severity_order = {"high": 0, "medium": 1, "low": 2}
        issues.sort(key=lambda i: severity_order.get(i["severity"], 3))
        return {
            "issues": issues,
            "total": sum(i["count"] for i in issues),
            "by_severity": {
                sev: sum(i["count"] for i in issues if i["severity"] == sev)
                for sev in ("high", "medium", "low")
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # -------------------------------------------------------------- activity
    async def activity(self, organization_id: UUID, *, limit: int = 50) -> dict:
        items = await self._repo.activity(organization_id, limit=limit)
        return {"items": items, "count": len(items)}

    # ------------------------------------------------------ verificación
    async def verify_object(
        self, organization_id: UUID, object_id: UUID, *, user_id: UUID | None
    ) -> dict | None:
        obj = await self._repo.verify_object(organization_id, object_id, user_id=user_id)
        if obj is None:
            return None
        await self._repo.record_version(
            organization_id,
            object_id,
            change_kind="verified",
            snapshot=obj,
            changed_by=user_id,
            reason="Verificación humana",
        )
        return obj

    async def verify_assertion(
        self, organization_id: UUID, assertion_id: UUID, *, user_id: UUID | None
    ) -> dict | None:
        return await self._repo.verify_assertion(
            organization_id, assertion_id, user_id=user_id
        )


_QUESTION_GAP_TYPES: dict[str, str] = {
    "enum_meaning": "UNKNOWN_DEFINITION",
    "field_ambiguity": "AMBIGUOUS_TERM",
    "table_variant": "UNKNOWN_DEFINITION",
    "tax_inclusion": "UNKNOWN_DEFINITION",
    "relationship_meaning": "MISSING_RELATIONSHIP",
    "business_rule": "MISSING_BUSINESS_RULE",
    "metric_definition": "MISSING_METRIC_DEFINITION",
    "llm_question": "UNKNOWN_DEFINITION",
    "other": "UNKNOWN_DEFINITION",
}


def _question_gap_type(question_type: str) -> str:
    return _QUESTION_GAP_TYPES.get(question_type, "UNKNOWN_DEFINITION")
