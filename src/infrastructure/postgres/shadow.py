# =============================================================================
# Shadow Repository — Postgres (Phase 8)
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.cognitive import ComplexityLevel
from src.core.domain.shadow import (
    ShadowComparison,
    ShadowMetrics,
    ShadowVerdict,
)
from src.core.ports.shadow import ShadowRepository
from src.infrastructure.postgres.session import get_async_session

_COLUMNS = (
    "id, organization_id, workspace_id, query, complexity, baseline_run_id, "
    "cognitive_run_id, baseline_metrics, cognitive_metrics, verdict, reasons, "
    "created_at"
)


class PostgresShadowRepository(ShadowRepository):

    async def save(self, comparison: ShadowComparison) -> ShadowComparison:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO cognitive_shadow_runs ({_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :query, :complexity,
                        :baseline_run_id, :cognitive_run_id,
                        CAST(:baseline_metrics AS jsonb),
                        CAST(:cognitive_metrics AS jsonb), :verdict,
                        CAST(:reasons AS jsonb), now()
                    )
                    ON CONFLICT (id) DO NOTHING
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "id": str(comparison.id),
                    "organization_id": str(comparison.organization_id),
                    "workspace_id": (
                        str(comparison.workspace_id)
                        if comparison.workspace_id
                        else None
                    ),
                    "query": comparison.query,
                    "complexity": comparison.level.value,
                    "baseline_run_id": _uuid_or_none(comparison.baseline_run_id),
                    "cognitive_run_id": _uuid_or_none(comparison.cognitive_run_id),
                    "baseline_metrics": json.dumps(
                        comparison.baseline.to_dict()
                    ),
                    "cognitive_metrics": json.dumps(
                        comparison.cognitive.to_dict()
                    ),
                    "verdict": comparison.verdict.value,
                    "reasons": json.dumps(list(comparison.reasons)),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_comparison(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list(
        self, organization_id: UUID, limit: int = 50
    ) -> list[ShadowComparison]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM cognitive_shadow_runs "
                    "WHERE organization_id = :oid "
                    "ORDER BY created_at DESC, id LIMIT :limit"
                ),
                {"oid": str(organization_id), "limit": limit},
            )
            return [_row_to_comparison(row) for row in result.fetchall()]
        finally:
            await session.close()


def _uuid_or_none(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _row_to_metrics(value) -> ShadowMetrics:
    data = value if isinstance(value, dict) else {}
    return ShadowMetrics(
        evidence_count=int(data.get("evidence_count", 0)),
        claims=int(data.get("claims", 0)),
        supported=int(data.get("supported", 0)),
        partial=int(data.get("partial", 0)),
        unsupported=int(data.get("unsupported", 0)),
        outdated=int(data.get("outdated", 0)),
        conflicted=int(data.get("conflicted", 0)),
        conflicts=int(data.get("conflicts", 0)),
        critique_issues=int(data.get("critique_issues", 0)),
        debate_outcomes=int(data.get("debate_outcomes", 0)),
        llm_calls=int(data.get("llm_calls", 0)),
        tokens=int(data.get("tokens", 0)),
        cost_usd=float(data.get("cost_usd", 0.0)),
        latency_ms=float(data.get("latency_ms", 0.0)),
        has_answer=bool(data.get("has_answer", False)),
    )


def _row_to_comparison(row) -> ShadowComparison:
    return ShadowComparison(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        query=row.query,
        level=ComplexityLevel(row.complexity),
        baseline=_row_to_metrics(row.baseline_metrics),
        cognitive=_row_to_metrics(row.cognitive_metrics),
        verdict=ShadowVerdict(row.verdict),
        reasons=tuple(row.reasons or ()),
        baseline_run_id=row.baseline_run_id,
        cognitive_run_id=row.cognitive_run_id,
        created_at=row.created_at,
    )
