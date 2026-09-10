# =============================================================================
# Knowledge Evaluation — auto-evaluación RAG del catálogo aprendido (F33G)
# =============================================================================
# Después del aprendizaje, Zent se examina a sí mismo: genera preguntas
# sintéticas SOLO cuando el catálogo lo justifica (medida + identificador,
# fecha + entidad, dimensión + medida), las ejecuta contra el RAG pipeline
# real y persiste el run en el sistema de evaluación existente (eval_runs).
#
# Métricas reales: retrieval_precision/recall, context_relevance,
# answer_relevance, faithfulness (juez opcional), citation_accuracy.
# La dimensión rag_evaluation del score lee estos runs.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    knowledge_evaluation_composite,
    knowledge_evaluation_runs_total,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_learning.repository import (
    PostgresKnowledgeLearningRepository,
)

logger = get_logger(__name__)

_SYSTEM_USER = UUID("00000000-0000-0000-0000-000000000002")
_DATASET_PREFIX = "knowledge-auto"


async def _resolve_orchestrator():
    """Orquestador RAG real (inyectable en tests vía monkeypatch)."""
    from src.api.deps import get_rag_orchestrator

    return get_rag_orchestrator()


async def _resolve_llm_provider():
    from src.api.deps import get_llm_provider

    return get_llm_provider()


def _make_candidate(
    entity: dict,
    label: str,
    field_names: list[str],
    kind: str,
    question: str,
    keywords: list[str],
    evidence: list[str],
) -> dict:
    clean_keywords = [str(k).strip() for k in keywords if str(k).strip()]
    return {
        "kind": kind,
        "question": question,
        "keywords": clean_keywords,
        "evidence": evidence,
        "entity": entity["name"],
        "entity_display": label,
        "entity_id": entity["id"],
        "fields": list(field_names),
    }


async def generate_synthetic_questions(
    store: PostgresCatalogStore,
    organization_id: UUID,
    source_id: UUID,
    *,
    limit: int = 10,
) -> list[dict]:
    """Preguntas de negocio justificadas por el catálogo (nunca inventadas).

    Regla: cada pregunta requiere los roles reales de sus campos (IDENTIFIER,
    MEASURE, DATE, CATEGORY) y cita la evidencia en metadata.evidence.
    """
    tables = await store.list_tables(organization_id, source_id, limit=5000)
    table_ids = {t["id"] for t in tables}
    entities = await store.list_entities(organization_id, limit=1000)
    candidates: list[dict] = []

    for entity in entities:
        if entity.get("mapped_table_id") not in table_ids:
            continue
        fields = await store.list_fields(organization_id, UUID(entity["id"]))
        mapped = [
            f
            for f in fields
            if f.get("mapped_column_id") and f.get("status") != "deprecated"
        ]
        if not mapped:
            continue
        by_role: dict[str, dict] = {}
        for fld in mapped:
            by_role.setdefault(fld.get("role") or "UNKNOWN", fld)
        identifier = by_role.get("IDENTIFIER")
        measure = by_role.get("MEASURE")
        date = by_role.get("DATE")
        category = by_role.get("CATEGORY")
        label = entity.get("display_name") or entity.get("name") or "entidad"
        field_names = [f["name"] for f in mapped[:8]]

        if identifier is not None:
            candidates.append(
                _make_candidate(
                    entity,
                    label,
                    field_names,
                    "count",
                    f"¿Cuántos {label} hay en total?",
                    [label, "total"],
                    [f"entidad con identificador {identifier['name']}"],
                )
            )
            if date is not None:
                candidates.append(
                    _make_candidate(
                        entity,
                        label,
                        field_names,
                        "recent",
                        f"¿Cuántos {label} se registraron en los últimos 30 días?",
                        [label, "días"],
                        [f"campo de fecha {date['name']}"],
                    )
                )
            if measure is not None:
                candidates.append(
                    _make_candidate(
                        entity,
                        label,
                        field_names,
                        "top",
                        f"¿Cuáles son los {label} con mayor {measure['name']}?",
                        [label, measure["name"]],
                        [f"medida del negocio {measure['name']}"],
                    )
                )
            if measure is not None and category is not None:
                candidates.append(
                    _make_candidate(
                        entity,
                        label,
                        field_names,
                        "by_dimension",
                        f"¿Qué {category['name']} generan mayor {measure['name']}?",
                        [category["name"], measure["name"]],
                        [
                            f"dimensión {category['name']}",
                            f"medida del negocio {measure['name']}",
                        ],
                    )
                )
    return candidates[: max(1, min(int(limit), 200))]


class KnowledgeEvaluationService:
    """Auto-evaluación RAG integrada con el sistema de evaluación existente."""

    def __init__(
        self,
        store: PostgresCatalogStore | None = None,
        repository: PostgresKnowledgeLearningRepository | None = None,
        *,
        orchestrator=None,
        llm_provider=None,
        judge=None,
    ) -> None:
        self._store = store or PostgresCatalogStore()
        self._repo = repository
        self._orchestrator = orchestrator
        self._llm = llm_provider
        self._judge = judge

    async def latest(
        self,
        organization_id: UUID,
        source_id: UUID | None = None,
    ) -> dict | None:
        """Última auto-evaluación (dataset knowledge-auto) del tenant/fuente."""
        session = await get_async_session()
        try:
            query = (
                "SELECT id, dataset_name, target_name, status, summary, created_at "
                "FROM eval_runs "
                "WHERE organization_id = :oid AND dataset_name LIKE :prefix "
                "AND status = 'completed'"
            )
            params: dict = {
                "oid": organization_id,
                "prefix": f"{_DATASET_PREFIX}%",
            }
            if source_id is not None:
                query += " AND summary->'version_snapshot'->>'source_id' = :sid"
                params["sid"] = str(source_id)
            query += " ORDER BY created_at DESC LIMIT 1"
            row = (await session.execute(text(query), params)).fetchone()
            if row is None:
                return None
            summary = row.summary if isinstance(row.summary, dict) else {}
            return {
                "id": str(row.id),
                "dataset_name": row.dataset_name,
                "target_name": row.target_name,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "overall": (
                    round(float((summary.get("quality") or {}).get("composite_score") or 0) * 100, 2)
                ),
                "composite_score": (summary.get("quality") or {}).get("composite_score"),
                "quality": summary.get("quality") or {},
                "performance": summary.get("performance") or {},
                "total_cases": summary.get("total_cases") or 0,
                "failed_cases": summary.get("failed_cases") or 0,
                "target_id": summary.get("target_id"),
            }
        finally:
            await session.close()

    async def run(
        self,
        organization_id: UUID,
        *,
        source_id: UUID,
        run_id: UUID | None = None,
        limit: int | None = None,
    ) -> dict:
        settings = get_settings()
        max_questions = limit or settings.RAG_KNOWLEDGE_EVALUATION_MAX_QUESTIONS
        try:
            from src.rag.evaluation.store import ensure_eval_engine_tables

            await ensure_eval_engine_tables()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Eval tables ensure failed", error=str(exc)[:200])
            return {"status": "skipped", "reason": "eval_store_unavailable", "candidates": 0}

        try:
            candidates = await generate_synthetic_questions(
                self._store,
                organization_id,
                source_id,
                limit=max_questions,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Synthetic questions generation failed", error=str(exc)[:200])
            return {"status": "skipped", "reason": "catalog_unavailable", "candidates": 0}
        if not candidates:
            return {
                "status": "skipped",
                "reason": "no_synthetic_questions",
                "candidates": 0,
            }

        from src.rag.evaluation.datasets import load_dataset
        from src.rag.evaluation.judge import LLMJudge
        from src.rag.evaluation.runner import EvalRunner
        from src.rag.evaluation.store import save_eval_run
        from src.rag.evaluation.targets import RAGTarget

        payload: list[dict] = []
        for index, candidate in enumerate(candidates):
            keywords = list(candidate.get("keywords") or [])
            payload.append(
                {
                    "id": f"kl-{str(source_id)[:8]}-{index + 1:03d}",
                    "question": candidate["question"],
                    "expected_sources": keywords,
                    "metadata": {
                        "expected_keywords": keywords,
                        "role": "admin",
                        "top_k": 20,
                        "category": "knowledge_learning",
                        "source_id": str(source_id),
                        "entity": candidate.get("entity"),
                        "evidence": candidate.get("evidence") or [],
                        "kind": candidate.get("kind"),
                    },
                }
            )

        dataset = load_dataset(payload, name=f"{_DATASET_PREFIX}-{str(source_id)[:8]}")
        orchestrator = self._orchestrator or await _resolve_orchestrator()

        judge = self._judge
        if judge is None and settings.RAG_KNOWLEDGE_EVALUATION_JUDGE:
            try:
                llm = self._llm or await _resolve_llm_provider()
                judge = LLMJudge(
                    llm,
                    model=settings.EVAL_JUDGE_MODEL,
                    enabled=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Judge init failed; deterministic metrics only", error=str(exc)[:200])

        target = RAGTarget(
            orchestrator,
            organization_id,
            _SYSTEM_USER,
            target_id=source_id,
            target_name=f"{_DATASET_PREFIX}:{str(source_id)[:8]}",
        )
        runner = EvalRunner(target, judge)
        try:
            summary = await runner.run(
                dataset,
                version_snapshot={
                    "engine": "knowledge_learning",
                    "source_id": str(source_id),
                    "run_id": str(run_id) if run_id else None,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-evaluation run failed", error=str(exc)[:300])
            knowledge_evaluation_runs_total.labels(
                organization_id=str(organization_id), status="failed"
            ).inc()
            return {
                "status": "failed",
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                "candidates": len(candidates),
                "summary": None,
            }

        summary["dataset_id"] = None
        await save_eval_run(organization_id, summary)
        run_status = (
            "completed"
            if int(summary.get("failed_cases") or 0) == 0
            else "partial"
        )
        knowledge_evaluation_runs_total.labels(
            organization_id=str(organization_id), status=run_status
        ).inc()
        quality = summary.get("quality") or {}
        composite = quality.get("composite_score")
        if isinstance(composite, (int, float)):
            try:
                knowledge_evaluation_composite.labels(
                    organization_id=str(organization_id)
                ).set(float(composite))
            except Exception:  # noqa: BLE001
                pass

        performance = summary.get("performance") or {}
        cases: list[dict] = []
        for case in summary.get("cases") or []:
            cases.append(
                {
                    "question": case.get("question"),
                    "status": case.get("status"),
                    "error": case.get("error"),
                    "scores": case.get("scores") or {},
                    "metrics": {
                        key: (case.get("metrics") or {}).get(key)
                        for key in (
                            "retrieval_precision",
                            "retrieval_recall",
                            "context_relevance",
                            "answer_relevance",
                            "faithfulness",
                            "citation_accuracy",
                            "hallucinated",
                        )
                    },
                }
            )
        return {
            "status": "completed",
            "run_id": summary.get("run_id"),
            "candidates": len(candidates),
            "questions": len(cases),
            "failed_cases": summary.get("failed_cases") or 0,
            "composite_score": composite,
            "quality": {
                key: quality.get(key)
                for key in (
                    "composite_score",
                    "retrieval_precision",
                    "retrieval_recall",
                    "context_relevance",
                    "answer_relevance",
                    "faithfulness",
                    "citation_accuracy",
                    "hallucination_rate",
                    "judge_enabled",
                )
            },
            "performance": {
                "total_tokens": performance.get("total_tokens") or 0,
                "total_cost": performance.get("total_cost") or 0.0,
                "latency": performance.get("latency") or {},
            },
            "cases": cases,
        }
