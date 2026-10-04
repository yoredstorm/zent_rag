# =============================================================================
# Knowledge Nutrition — store Postgres (estado + acciones)
# =============================================================================
# Una fila de estado por (organization_id, scope, scope_id) con dimensiones
# JSONB. Las acciones son append-only con evidencia; nunca se borra evidencia
# contradictoria.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

from .contracts import NutritionAction, NutritionScore

logger = get_logger(__name__)


class PostgresNutritionStore:
    async def save_state(
        self,
        score: NutritionScore,
        *,
        organization_id: UUID,
        workspace_id: UUID | None = None,
        source_id: UUID | None = None,
        document_id: UUID | None = None,
        demand_profile: dict | None = None,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_nutrition_state (
                        id, organization_id, workspace_id, source_id, document_id,
                        scope, scope_id, dimensions, nutrition_score,
                        formula_version, measured_dimensions, total_dimensions,
                        coverage, demand_profile, details, computed_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :organization_id, :workspace_id, :source_id,
                        :document_id, :scope, :scope_id, CAST(:dimensions AS jsonb),
                        :nutrition_score, :formula_version, :measured_dimensions,
                        :total_dimensions, :coverage, CAST(:demand_profile AS jsonb),
                        CAST(:details AS jsonb), :computed_at, now()
                    )
                    ON CONFLICT (organization_id, scope, scope_id) DO UPDATE SET
                        workspace_id = EXCLUDED.workspace_id,
                        source_id = EXCLUDED.source_id,
                        document_id = EXCLUDED.document_id,
                        dimensions = EXCLUDED.dimensions,
                        nutrition_score = EXCLUDED.nutrition_score,
                        formula_version = EXCLUDED.formula_version,
                        measured_dimensions = EXCLUDED.measured_dimensions,
                        total_dimensions = EXCLUDED.total_dimensions,
                        coverage = EXCLUDED.coverage,
                        demand_profile = EXCLUDED.demand_profile,
                        details = EXCLUDED.details,
                        computed_at = EXCLUDED.computed_at,
                        updated_at = now()
                    """
                ),
                {
                    "organization_id": str(organization_id),
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "source_id": str(source_id) if source_id else None,
                    "document_id": str(document_id) if document_id else None,
                    "scope": score.scope,
                    "scope_id": score.scope_id,
                    "dimensions": json.dumps(score.to_dict(), default=str),
                    "nutrition_score": score.nutrition_score,
                    "formula_version": score.formula_version,
                    "measured_dimensions": int(score.measured_dimensions),
                    "total_dimensions": int(score.total_dimensions),
                    "coverage": score.coverage,
                    "demand_profile": json.dumps(demand_profile or {}, default=str),
                    "details": json.dumps(score.details or {}, default=str),
                    "computed_at": score.computed_at,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_state(
        self,
        organization_id: UUID,
        *,
        scope: str = "document",
        scope_id: str | None = None,
        document_id: UUID | None = None,
    ) -> dict | None:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid", "scope = :scope"]
            params: dict = {"oid": str(organization_id), "scope": scope}
            if scope_id:
                where.append("scope_id = :sid")
                params["sid"] = str(scope_id)
            if document_id is not None:
                where.append("document_id = :did")
                params["did"] = str(document_id)
            row = (
                await session.execute(
                    text(
                        "SELECT scope, scope_id, workspace_id, source_id, document_id, "
                        "dimensions, nutrition_score, formula_version, "
                        "measured_dimensions, total_dimensions, coverage, "
                        "demand_profile, details, computed_at, updated_at "
                        "FROM knowledge_nutrition_state WHERE "
                        + " AND ".join(where)
                        + " ORDER BY updated_at DESC LIMIT 1"
                    ),
                    params,
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "scope": row.scope,
                "scope_id": row.scope_id,
                "workspace_id": str(row.workspace_id) if row.workspace_id else None,
                "source_id": str(row.source_id) if row.source_id else None,
                "document_id": str(row.document_id) if row.document_id else None,
                "dimensions": row.dimensions or {},
                "nutrition_score": row.nutrition_score,
                "formula_version": row.formula_version,
                "measured_dimensions": int(row.measured_dimensions or 0),
                "total_dimensions": int(row.total_dimensions or 0),
                "coverage": row.coverage,
                "demand_profile": row.demand_profile or {},
                "details": row.details or {},
                "computed_at": row.computed_at.isoformat() if row.computed_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        finally:
            await session.close()

    async def save_action(
        self, action: NutritionAction, *, organization_id: UUID
    ) -> str | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_nutrition_actions (
                            id, organization_id, workspace_id, source_id, document_id,
                            failure_type, action_type, status, confidence, reason,
                            query, evidence, policy_version, model_version,
                            destructive, requires_review, duration_ms, created_at, updated_at
                        ) VALUES (
                            gen_random_uuid(), :organization_id, :workspace_id, :source_id,
                            :document_id, :failure_type, :action_type, :status, :confidence,
                            :reason, :query, CAST(:evidence AS jsonb), :policy_version,
                            :model_version, :destructive, :requires_review, :duration_ms,
                            now(), now()
                        ) RETURNING id
                        """
                    ),
                    {
                        "organization_id": str(organization_id),
                        "workspace_id": action.workspace_id,
                        "source_id": action.source_id,
                        "document_id": action.document_id,
                        "failure_type": action.failure_type,
                        "action_type": action.action_type,
                        "status": action.status,
                        "confidence": float(action.confidence),
                        "reason": action.reason[:1000],
                        "query": action.query,
                        "evidence": json.dumps(action.evidence or {}, default=str),
                        "policy_version": action.policy_version,
                        "model_version": action.model_version,
                        "destructive": bool(action.destructive),
                        "requires_review": bool(action.requires_review),
                        "duration_ms": float(action.duration_ms),
                    },
                )
            ).fetchone()
            await session.commit()
            return str(row.id) if row else None
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_actions(
        self,
        organization_id: UUID,
        *,
        document_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid"]
            params: dict = {"oid": str(organization_id), "limit": max(1, min(limit, 500))}
            if document_id is not None:
                where.append("document_id = :did")
                params["did"] = str(document_id)
            if status:
                where.append("status = :status")
                params["status"] = status
            rows = (
                await session.execute(
                    text(
                        "SELECT id, workspace_id, source_id, document_id, failure_type, "  # noqa: S608
                        "action_type, status, confidence, reason, query, evidence, "
                        "policy_version, model_version, destructive, requires_review, "
                        "created_at FROM knowledge_nutrition_actions WHERE "
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY created_at DESC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [
                {
                    "id": str(row.id),
                    "workspace_id": str(row.workspace_id) if row.workspace_id else None,
                    "source_id": str(row.source_id) if row.source_id else None,
                    "document_id": str(row.document_id) if row.document_id else None,
                    "failure_type": row.failure_type,
                    "action_type": row.action_type,
                    "status": row.status,
                    "confidence": row.confidence,
                    "reason": row.reason,
                    "query": row.query,
                    "evidence": row.evidence or {},
                    "policy_version": row.policy_version,
                    "model_version": row.model_version,
                    "destructive": bool(row.destructive),
                    "requires_review": bool(row.requires_review),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
        finally:
            await session.close()
