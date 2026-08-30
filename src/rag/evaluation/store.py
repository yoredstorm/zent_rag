# =============================================================================
# Evaluation Storage — Feedback collection and RAG quality metrics
# =============================================================================
# Stores thumbs up/down feedback with optional comments and computes
# aggregated quality scores per organization/role.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# SQL Migration (applied by `ensure_eval_table`)
# ---------------------------------------------------------------------------
_EVAL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rag_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    query_id UUID,
    conversation_id UUID,
    query TEXT NOT NULL,
    answer TEXT,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    rating VARCHAR(10) NOT NULL CHECK (rating IN ('up', 'down')),
    comment TEXT,
    model VARCHAR(100),
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latency_ms DOUBLE PRECISION DEFAULT 0,
    method VARCHAR(10) DEFAULT 'rag',
    lazy_ingested BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_evals_organization ON rag_evaluations(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rag_evals_role ON rag_evaluations(organization_id, role, created_at DESC);
"""


async def ensure_eval_table() -> None:
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_evaluations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL,
                query_id UUID,
                conversation_id UUID,
                query TEXT NOT NULL,
                answer TEXT,
                role VARCHAR(20) NOT NULL DEFAULT 'admin',
                rating VARCHAR(10) NOT NULL CHECK (rating IN ('up', 'down')),
                comment TEXT,
                model VARCHAR(100),
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_ms DOUBLE PRECISION DEFAULT 0,
                method VARCHAR(10) DEFAULT 'rag',
                lazy_ingested BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_rag_evals_organization "
            "ON rag_evaluations(organization_id, created_at DESC)"
        ))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_rag_evals_role "
            "ON rag_evaluations(organization_id, role, created_at DESC)"
        ))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(
            "ALTER TABLE rag_evaluations "
            "ADD COLUMN IF NOT EXISTS lazy_ingested BOOLEAN DEFAULT FALSE"
        ))
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


async def store_feedback(
    organization_id: UUID,
    query: str,
    rating: str,
    query_id: UUID | None = None,
    conversation_id: UUID | None = None,
    answer: str = "",
    role: str = "admin",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: float = 0.0,
    method: str = "rag",
    comment: str = "",
    lazy_ingested: bool = False,
) -> None:
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO rag_evaluations (organization_id, query_id, conversation_id, "
                "query, answer, role, rating, comment, model, "
                "prompt_tokens, completion_tokens, total_tokens, latency_ms, method, "
                "lazy_ingested) "
                "VALUES (:organization_id, :query_id, :conversation_id, "
                ":query, :answer, :role, :rating, :comment, :model, "
                ":prompt_tokens, :completion_tokens, :total_tokens, :latency_ms, :method, "
                ":lazy_ingested)"
            ),
            {
                "organization_id": organization_id,
                "query_id": query_id,
                "conversation_id": conversation_id,
                "query": query,
                "answer": answer,
                "role": role,
                "rating": rating,
                "comment": comment,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": latency_ms,
                "method": method,
                "lazy_ingested": lazy_ingested,
            },
        )
        await session.commit()
        logger.info("Feedback stored", organization_id=str(organization_id), rating=rating)
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to store feedback", error=str(exc))
    finally:
        await session.close()


async def get_stats(
    organization_id: UUID,
    role: str | None = None,
    days: int = 30,
) -> dict:
    session: AsyncSession = await get_async_session()
    try:
        role_filter = "AND role = :role" if role else ""
        params: dict[str, str | int] = {
            "organization_id": str(organization_id),
            "days": str(days),
        }
        if role:
            params["role"] = role

        result = await session.execute(
            text(
                "SELECT "
                "  COUNT(*) FILTER (WHERE rating = 'up') AS thumbs_up, "
                "  COUNT(*) FILTER (WHERE rating = 'down') AS thumbs_down, "
                "  COUNT(*) AS total, "
                "  ROUND(AVG(latency_ms)) AS avg_latency_ms, "
                "  ROUND(AVG(total_tokens)) AS avg_tokens, "
                "  COUNT(DISTINCT model) AS models_used "
                "FROM rag_evaluations "
                "WHERE organization_id = CAST(:organization_id AS uuid) "
                "  AND created_at >= NOW() - (:days || ' days')::interval "
                + role_filter
            ),
            params,
        )
        row = result.fetchone()
        total = row.total or 0
        thumbs_up = row.thumbs_up or 0
        return {
            "organization_id": str(organization_id),
            "role": role or "all",
            "period_days": days,
            "total_evaluations": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": row.thumbs_down or 0,
            "approval_rate": round(thumbs_up / total * 100, 1) if total > 0 else 0.0,
            "avg_latency_ms": round(row.avg_latency_ms, 1) if row.avg_latency_ms else 0,
            "avg_tokens": round(row.avg_tokens) if row.avg_tokens else 0,
            "models_used": row.models_used or 0,
        }
    finally:
        await session.close()


async def get_recent(
    organization_id: UUID,
    limit: int = 20,
) -> list[dict]:
    session: AsyncSession = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT id, query_id, query, answer, role, rating, comment, "
                "model, total_tokens, latency_ms, method, created_at "
                "FROM rag_evaluations "
                "WHERE organization_id = :organization_id "
                "ORDER BY created_at DESC "
                "LIMIT :limit"
            ),
            {"organization_id": organization_id, "limit": limit},
        )
        return [
            {
                "id": str(row.id),
                "query_id": str(row.query_id) if row.query_id else None,
                "query": row.query[:200],
                "answer": row.answer[:300] if row.answer else "",
                "role": row.role,
                "rating": row.rating,
                "comment": row.comment,
                "model": row.model,
                "total_tokens": row.total_tokens,
                "latency_ms": row.latency_ms,
                "method": row.method,
                "created_at": row.created_at.isoformat(),
            }
            for row in result.fetchall()
        ]
    finally:
        await session.close()


# =============================================================================
# Evaluation Engine — persistencia de datasets, runs y resultados por caso
# =============================================================================
# Tablas creadas por la migración 011_evaluation_engine; ensure_* es
# idempotente como red de seguridad en ambientes sin alembic aplicado.
# =============================================================================

_EVAL_ENGINE_DDL = """
CREATE TABLE IF NOT EXISTS eval_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 2,
    cases JSONB NOT NULL DEFAULT '[]',
    weights JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_datasets_org
    ON eval_datasets(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS eval_runs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    dataset_id UUID,
    dataset_name TEXT,
    target_type VARCHAR(10) NOT NULL,
    target_id UUID,
    target_name TEXT,
    version_snapshot JSONB NOT NULL DEFAULT '{}',
    version_id TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    summary JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_org
    ON eval_runs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_runs_version
    ON eval_runs(version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS eval_case_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    question TEXT,
    answer TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    target JSONB NOT NULL DEFAULT '{}',
    metrics JSONB NOT NULL DEFAULT '{}',
    scores JSONB NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_cases_run
    ON eval_case_results(run_id, created_at);
"""


async def ensure_eval_engine_tables() -> None:
    """Crea tablas del eval engine si no existen (idempotente)."""
    session: AsyncSession = await get_async_session()
    try:
        for statement in _EVAL_ENGINE_DDL.split(";"):
            if statement.strip():
                await session.execute(text(statement))
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.warning("Failed to ensure eval engine tables", error=str(exc))
    finally:
        await session.close()


async def save_dataset(
    organization_id: UUID,
    name: str,
    cases: list[dict],
    *,
    schema_version: int = 2,
    weights: dict | None = None,
    metadata: dict | None = None,
) -> UUID:
    """Importa un dataset (nueva versión en cada import) y devuelve su id."""
    import json as _json

    dataset_id = uuid4()
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO eval_datasets "
                "(id, organization_id, name, schema_version, cases, weights, metadata) "
                "VALUES (:id, :oid, :name, :schema_version, "
                "CAST(:cases AS jsonb), CAST(:weights AS jsonb), CAST(:metadata AS jsonb))"
            ),
            {
                "id": dataset_id,
                "oid": organization_id,
                "name": name[:200],
                "schema_version": schema_version,
                "cases": _json.dumps(cases),
                "weights": _json.dumps(weights or {}),
                "metadata": _json.dumps(metadata or {}),
            },
        )
        await session.commit()
        logger.info("Eval dataset imported", organization_id=str(organization_id), name=name)
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to import eval dataset", error=str(exc))
        raise
    finally:
        await session.close()
    return dataset_id


async def list_datasets(organization_id: UUID) -> list[dict]:
    session: AsyncSession = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT id, name, schema_version, "
                "jsonb_array_length(cases) AS case_count, created_at "
                "FROM eval_datasets "
                "WHERE organization_id = :oid "
                "ORDER BY created_at DESC"
            ),
            {"oid": organization_id},
        )
        return [
            {
                "id": str(row.id),
                "name": row.name,
                "schema_version": row.schema_version,
                "case_count": row.case_count or 0,
                "created_at": row.created_at.isoformat(),
            }
            for row in result.fetchall()
        ]
    finally:
        await session.close()


async def get_dataset(organization_id: UUID, dataset_id: UUID) -> dict | None:
    session: AsyncSession = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, schema_version, cases, weights, metadata, created_at "
                    "FROM eval_datasets "
                    "WHERE organization_id = :oid AND id = :did"
                ),
                {"oid": organization_id, "did": dataset_id},
            )
        ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row.id),
            "name": row.name,
            "schema_version": row.schema_version,
            "cases": row.cases if isinstance(row.cases, list) else [],
            "weights": row.weights if isinstance(row.weights, dict) else {},
            "metadata": row.metadata if isinstance(row.metadata, dict) else {},
            "created_at": row.created_at.isoformat(),
        }
    finally:
        await session.close()


async def save_eval_run(
    organization_id: UUID,
    summary: dict,
) -> None:
    """Persiste run + resultados por caso (transacción única, fail-silent)."""
    import json as _json

    cases = summary.get("cases") or []
    run_id = _optional_uuid(summary.get("run_id"))
    if run_id is None:
        logger.warning("Eval run save skipped: missing run_id")
        return
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO eval_runs "
                "(id, organization_id, dataset_id, dataset_name, target_type, "
                "target_id, target_name, version_snapshot, version_id, status, summary) "
                "VALUES (:id, :oid, :dataset_id, :dataset_name, :target_type, "
                ":target_id, :target_name, CAST(:snapshot AS jsonb), :version_id, "
                ":status, CAST(:summary AS jsonb))"
            ),
            {
                "id": run_id,
                "oid": organization_id,
                "dataset_id": _optional_uuid(summary.get("dataset_id")),
                "dataset_name": summary.get("dataset_name"),
                "target_type": summary.get("target_type") or "rag",
                "target_id": _optional_uuid(summary.get("target_id")),
                "target_name": summary.get("target_name"),
                "snapshot": _json.dumps(summary.get("version_snapshot") or {}),
                "version_id": summary.get("version_id"),
                "status": "completed" if summary.get("failed_cases", 0) == 0 else "partial",
                "summary": _json.dumps({k: v for k, v in summary.items() if k != "cases"}),
            },
        )
        for case in cases:
            metrics = dict(case.get("metrics") or {})
            for key in ("expected_answer", "expected_sources", "retrieved"):
                if key in case and key not in metrics:
                    metrics[key] = case[key]
            await session.execute(
                text(
                    "INSERT INTO eval_case_results "
                    "(run_id, case_id, question, answer, status, target, metrics, scores, error) "
                    "VALUES (:run_id, :case_id, :question, :answer, :status, "
                    "CAST(:target AS jsonb), CAST(:metrics AS jsonb), "
                    "CAST(:scores AS jsonb), :error)"
                ),
                {
                    "run_id": run_id,
                    "case_id": str(case.get("case_id") or "")[:200],
                    "question": str(case.get("question") or "")[:4000],
                    "answer": str(case.get("answer") or "")[:8000],
                    "status": case.get("status") or "completed",
                    "target": _json.dumps(case.get("target") or {}),
                    "metrics": _json.dumps(metrics),
                    "scores": _json.dumps(case.get("scores") or {}),
                    "error": str(case.get("error") or "")[:2000] or None,
                },
            )
        await session.commit()
        logger.info("Eval run saved", run_id=str(run_id))
    except Exception as exc:
        await session.rollback()
        logger.warning("Eval run save failed", error=str(exc))
    finally:
        await session.close()


def _case_row_to_payload(c) -> dict:
    metrics = c.metrics if isinstance(c.metrics, dict) else {}
    expected_sources = metrics.get("expected_sources") or []
    if not isinstance(expected_sources, list):
        expected_sources = []
    retrieved = metrics.get("retrieved") or []
    if not isinstance(retrieved, list):
        retrieved = []
    return {
        "case_id": c.case_id,
        "question": c.question,
        "answer": c.answer,
        "actual": c.answer,
        "expected_answer": metrics.get("expected_answer"),
        "expected_sources": expected_sources,
        "retrieved": retrieved,
        "status": c.status,
        "target": c.target if isinstance(c.target, dict) else {},
        "metrics": metrics,
        "scores": c.scores if isinstance(c.scores, dict) else {},
        "latency_ms": metrics.get("latency_ms"),
        "cost": metrics.get("cost"),
        "error": c.error,
    }


def _optional_uuid(value) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


async def get_eval_run(organization_id: UUID, run_id: UUID) -> dict | None:
    session: AsyncSession = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, dataset_id, dataset_name, target_type, target_id, "
                    "target_name, version_snapshot, version_id, status, summary, created_at "
                    "FROM eval_runs "
                    "WHERE organization_id = :oid AND id = :rid"
                ),
                {"oid": organization_id, "rid": run_id},
            )
        ).fetchone()
        if row is None:
            return None
        cases_result = await session.execute(
            text(
                "SELECT case_id, question, answer, status, target, metrics, scores, error "
                "FROM eval_case_results WHERE run_id = :rid ORDER BY created_at"
            ),
            {"rid": run_id},
        )
        summary = dict(row.summary) if isinstance(row.summary, dict) else {}
        summary["run_id"] = str(row.id)
        summary["created_at"] = row.created_at.isoformat()
        summary["cases"] = [
            _case_row_to_payload(c) for c in cases_result.fetchall()
        ]
        return summary
    finally:
        await session.close()


async def list_eval_runs(organization_id: UUID, limit: int = 20) -> list[dict]:
    session: AsyncSession = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT id, dataset_name, target_type, target_name, version_id, "
                "status, summary, created_at "
                "FROM eval_runs "
                "WHERE organization_id = :oid "
                "ORDER BY created_at DESC "
                "LIMIT :limit"
            ),
            {"oid": organization_id, "limit": min(limit, 100)},
        )
        runs = []
        for row in result.fetchall():
            summary = row.summary if isinstance(row.summary, dict) else {}
            quality = summary.get("quality") or {}
            performance = summary.get("performance") or {}
            runs.append(
                {
                    "id": str(row.id),
                    "dataset_name": row.dataset_name,
                    "target_type": row.target_type,
                    "target_name": row.target_name,
                    "version_id": row.version_id,
                    "status": row.status,
                    "composite_score": quality.get("composite_score"),
                    "avg_latency_ms": (performance.get("latency") or {}).get("avg_ms"),
                    "avg_cost": performance.get("avg_cost"),
                    "created_at": row.created_at.isoformat(),
                }
            )
        return runs
    finally:
        await session.close()
