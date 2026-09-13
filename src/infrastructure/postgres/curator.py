# =============================================================================
# Knowledge Curator Repository — Postgres (Phase 7)
# =============================================================================
# Sugerencias gobernadas, org-scoped. `decide` solo acepta decisiones finales
# (approved/rejected) con actor explícito; la DB refuerza la ley de aprobación.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.curator import (
    KnowledgeSuggestion,
    SuggestionKind,
    SuggestionStatus,
)
from src.core.ports.curator import CuratorRepository
from src.infrastructure.postgres.session import get_async_session

_COLUMNS = (
    "id, organization_id, workspace_id, run_id, kind, status, title, reasoning, "
    "payload, claim_ids, provenance, confidence, created_by, decided_by, "
    "decided_at, decision_reason, created_at"
)

_FINAL_STATUSES = {SuggestionStatus.APPROVED, SuggestionStatus.REJECTED}


class PostgresCuratorRepository(CuratorRepository):

    async def propose(self, suggestion: KnowledgeSuggestion) -> KnowledgeSuggestion:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO knowledge_curator_suggestions ({_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :run_id, :kind,
                        :status, :title, :reasoning, CAST(:payload AS jsonb),
                        CAST(:claim_ids AS uuid[]), :provenance, :confidence,
                        :created_by, :decided_by, :decided_at, :decision_reason,
                        now()
                    )
                    RETURNING {_COLUMNS}
                    """
                ),
                _params(suggestion),
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_suggestion(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get(
        self, organization_id: UUID, suggestion_id: UUID
    ) -> KnowledgeSuggestion | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM knowledge_curator_suggestions "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(suggestion_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_suggestion(row) if row is not None else None
        finally:
            await session.close()

    async def list(
        self,
        organization_id: UUID,
        *,
        status: SuggestionStatus | None = None,
        run_id: UUID | None = None,
        limit: int = 100,
    ) -> list[KnowledgeSuggestion]:
        session = await get_async_session()
        try:
            clauses = ["organization_id = :oid"]
            params: dict = {"oid": str(organization_id), "limit": limit}
            if status is not None:
                clauses.append("status = :status")
                params["status"] = status.value
            if run_id is not None:
                clauses.append("run_id = :rid")
                params["rid"] = str(run_id)
            result = await session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM knowledge_curator_suggestions "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC, id LIMIT :limit"
                ),
                params,
            )
            return [_row_to_suggestion(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def decide(
        self,
        organization_id: UUID,
        suggestion_id: UUID,
        *,
        status: SuggestionStatus,
        decided_by: UUID,
        reason: str = "",
    ) -> KnowledgeSuggestion | None:
        if status not in _FINAL_STATUSES:
            raise ValueError("decide() only accepts approved/rejected")
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    UPDATE knowledge_curator_suggestions
                    SET status = :status, decided_by = :decided_by,
                        decided_at = now(), decision_reason = :reason
                    WHERE id = :id AND organization_id = :oid
                    RETURNING {_COLUMNS}
                    """
                ),
                {
                    "status": status.value,
                    "decided_by": str(decided_by),
                    "reason": reason,
                    "id": str(suggestion_id),
                    "oid": str(organization_id),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_suggestion(row) if row is not None else None
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _params(suggestion: KnowledgeSuggestion) -> dict:
    return {
        "id": str(suggestion.id),
        "organization_id": str(suggestion.organization_id),
        "workspace_id": (
            str(suggestion.workspace_id) if suggestion.workspace_id else None
        ),
        "run_id": str(suggestion.run_id) if suggestion.run_id else None,
        "kind": suggestion.kind.value,
        "status": suggestion.status.value,
        "title": suggestion.title,
        "reasoning": suggestion.reasoning,
        "payload": json.dumps(suggestion.payload, default=str),
        "claim_ids": [str(c) for c in suggestion.claim_ids],
        "provenance": suggestion.provenance.value,
        "confidence": suggestion.confidence,
        "created_by": (
            str(suggestion.created_by) if suggestion.created_by else None
        ),
        "decided_by": (
            str(suggestion.decided_by) if suggestion.decided_by else None
        ),
        "decided_at": suggestion.decided_at,
        "decision_reason": "",
    }


def _row_to_suggestion(row) -> KnowledgeSuggestion:
    return KnowledgeSuggestion(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        kind=SuggestionKind(row.kind),
        status=SuggestionStatus(row.status),
        title=row.title,
        reasoning=row.reasoning or "",
        payload=row.payload if isinstance(row.payload, dict) else {},
        claim_ids=tuple(row.claim_ids or ()),
        provenance=CatalogProvenance(row.provenance),
        confidence=row.confidence,
        created_by=row.created_by,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )
