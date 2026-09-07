# =============================================================================
# Verified Query Store — Phase 26C
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.verified_query import (
    MappingSuggestion,
    MappingSuggestionStatus,
    VerifiedQuery,
    VerifiedQueryStatus,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS verified_queries (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        name VARCHAR(200) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        canonical_question TEXT NOT NULL,
        question_variants JSONB NOT NULL DEFAULT '[]'::jsonb,
        semantic_ast JSONB NOT NULL DEFAULT '{}'::jsonb,
        verified_sql TEXT NOT NULL,
        dialect VARCHAR(40) NOT NULL DEFAULT 'postgres',
        source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        table_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
        column_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
        metric_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
        concept_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
        status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
        version INT NOT NULL DEFAULT 1,
        approved_by UUID,
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_verified_at TIMESTAMPTZ,
        execution_fingerprint VARCHAR(128)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mapping_suggestions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        concept VARCHAR(160) NOT NULL,
        entity_type VARCHAR(40) NOT NULL DEFAULT 'ENTITY',
        physical_predicate TEXT NOT NULL,
        evidence_count INT NOT NULL DEFAULT 0,
        evidence_sample JSONB NOT NULL DEFAULT '[]'::jsonb,
        status VARCHAR(20) NOT NULL DEFAULT 'INFERRED',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        reviewed_by UUID,
        reviewed_at TIMESTAMPTZ,
        UNIQUE (organization_id, concept, physical_predicate)
    )
    """,
]


def _parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _row_to_vq(row: Any) -> VerifiedQuery:
    return VerifiedQuery(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        description=row.description or "",
        canonical_question=row.canonical_question,
        question_variants=_parse_json(row.question_variants, []),
        semantic_ast=_parse_json(row.semantic_ast, {}),
        verified_sql=row.verified_sql,
        dialect=row.dialect or "postgres",
        source_ids=_parse_json(row.source_ids, []),
        table_dependencies=_parse_json(row.table_dependencies, []),
        column_dependencies=_parse_json(row.column_dependencies, []),
        metric_dependencies=_parse_json(row.metric_dependencies, []),
        concept_dependencies=_parse_json(row.concept_dependencies, []),
        status=VerifiedQueryStatus(row.status),
        version=int(row.version or 1),
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_verified_at=row.last_verified_at,
        execution_fingerprint=row.execution_fingerprint,
    )


class PostgresVerifiedQueryStore:
    """Org-scoped persistence for verified queries + mapping suggestions."""

    async def ensure_tables(self) -> None:
        session: AsyncSession = await get_async_session()
        try:
            for stmt in _CREATE_TABLES:
                await session.execute(text(stmt))
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("VerifiedQuery ensure_tables failed", error=str(exc))
        finally:
            await session.close()

    async def upsert(self, item: VerifiedQuery) -> VerifiedQuery:
        session: AsyncSession = await get_async_session()
        now = datetime.now(timezone.utc)
        item.updated_at = now
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO verified_queries (
                        id, organization_id, name, description, canonical_question,
                        question_variants, semantic_ast, verified_sql, dialect,
                        source_ids, table_dependencies, column_dependencies,
                        metric_dependencies, concept_dependencies, status, version,
                        approved_by, approved_at, created_at, updated_at,
                        last_verified_at, execution_fingerprint
                    ) VALUES (
                        :id, :oid, :name, :description, :canonical_question,
                        CAST(:variants AS jsonb), CAST(:ast AS jsonb), :sql, :dialect,
                        CAST(:sources AS jsonb), CAST(:tables AS jsonb), CAST(:cols AS jsonb),
                        CAST(:metrics AS jsonb), CAST(:concepts AS jsonb), :status, :version,
                        :approved_by, :approved_at, :created_at, :updated_at,
                        :last_verified_at, :fingerprint
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        canonical_question = EXCLUDED.canonical_question,
                        question_variants = EXCLUDED.question_variants,
                        semantic_ast = EXCLUDED.semantic_ast,
                        verified_sql = EXCLUDED.verified_sql,
                        dialect = EXCLUDED.dialect,
                        source_ids = EXCLUDED.source_ids,
                        table_dependencies = EXCLUDED.table_dependencies,
                        column_dependencies = EXCLUDED.column_dependencies,
                        metric_dependencies = EXCLUDED.metric_dependencies,
                        concept_dependencies = EXCLUDED.concept_dependencies,
                        status = EXCLUDED.status,
                        version = EXCLUDED.version,
                        approved_by = EXCLUDED.approved_by,
                        approved_at = EXCLUDED.approved_at,
                        updated_at = EXCLUDED.updated_at,
                        last_verified_at = EXCLUDED.last_verified_at,
                        execution_fingerprint = EXCLUDED.execution_fingerprint
                    """
                ),
                {
                    "id": item.id,
                    "oid": item.organization_id,
                    "name": item.name[:200],
                    "description": item.description or "",
                    "canonical_question": item.canonical_question,
                    "variants": json.dumps(item.question_variants or []),
                    "ast": json.dumps(item.semantic_ast or {}),
                    "sql": item.verified_sql,
                    "dialect": item.dialect[:40],
                    "sources": json.dumps(item.source_ids or []),
                    "tables": json.dumps(item.table_dependencies or []),
                    "cols": json.dumps(item.column_dependencies or []),
                    "metrics": json.dumps(item.metric_dependencies or []),
                    "concepts": json.dumps(item.concept_dependencies or []),
                    "status": (
                        item.status.value
                        if isinstance(item.status, VerifiedQueryStatus)
                        else str(item.status)
                    ),
                    "version": item.version,
                    "approved_by": item.approved_by,
                    "approved_at": item.approved_at,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                    "last_verified_at": item.last_verified_at,
                    "fingerprint": item.execution_fingerprint,
                },
            )
            await session.commit()
            return item
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("VerifiedQuery upsert failed", error=str(exc))
            raise
        finally:
            await session.close()

    async def get(
        self, organization_id: UUID, query_id: UUID
    ) -> VerifiedQuery | None:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT * FROM verified_queries "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {"oid": organization_id, "id": query_id},
            )
            row = result.fetchone()
            return _row_to_vq(row) if row else None
        finally:
            await session.close()

    async def list(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[VerifiedQuery]:
        session: AsyncSession = await get_async_session()
        try:
            sql = "SELECT * FROM verified_queries WHERE organization_id = :oid"
            params: dict[str, Any] = {"oid": organization_id, "lim": limit}
            if status:
                sql += " AND status = :status"
                params["status"] = status
            sql += " ORDER BY updated_at DESC LIMIT :lim"
            result = await session.execute(text(sql), params)
            return [_row_to_vq(r) for r in result.fetchall()]
        finally:
            await session.close()

    async def list_verified(
        self, organization_id: UUID, *, dialect: str | None = None
    ) -> list[VerifiedQuery]:
        items = await self.list(
            organization_id, status=VerifiedQueryStatus.VERIFIED.value, limit=500
        )
        if dialect:
            items = [i for i in items if i.dialect == dialect]
        return items

    async def upsert_mapping_suggestion(
        self, suggestion: MappingSuggestion
    ) -> MappingSuggestion:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO mapping_suggestions (
                        id, organization_id, concept, entity_type, physical_predicate,
                        evidence_count, evidence_sample, status, created_at,
                        reviewed_by, reviewed_at
                    ) VALUES (
                        :id, :oid, :concept, :etype, :pred,
                        :count, CAST(:sample AS jsonb), :status, :created_at,
                        :reviewed_by, :reviewed_at
                    )
                    ON CONFLICT (organization_id, concept, physical_predicate) DO UPDATE SET
                        evidence_count = EXCLUDED.evidence_count,
                        evidence_sample = EXCLUDED.evidence_sample,
                        status = CASE
                            WHEN mapping_suggestions.status = 'INFERRED'
                            THEN EXCLUDED.status
                            ELSE mapping_suggestions.status
                        END
                    """
                ),
                {
                    "id": suggestion.id,
                    "oid": suggestion.organization_id,
                    "concept": suggestion.concept[:160],
                    "etype": suggestion.entity_type[:40],
                    "pred": suggestion.physical_predicate,
                    "count": suggestion.evidence_count,
                    "sample": json.dumps(suggestion.evidence_sample or []),
                    "status": (
                        suggestion.status.value
                        if isinstance(suggestion.status, MappingSuggestionStatus)
                        else str(suggestion.status)
                    ),
                    "created_at": suggestion.created_at,
                    "reviewed_by": suggestion.reviewed_by,
                    "reviewed_at": suggestion.reviewed_at,
                },
            )
            await session.commit()
            return suggestion
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Mapping suggestion upsert failed", error=str(exc))
            raise
        finally:
            await session.close()

    async def list_mapping_suggestions(
        self, organization_id: UUID, *, status: str | None = "INFERRED"
    ) -> list[MappingSuggestion]:
        session: AsyncSession = await get_async_session()
        try:
            sql = (
                "SELECT * FROM mapping_suggestions WHERE organization_id = :oid"
            )
            params: dict[str, Any] = {"oid": organization_id}
            if status:
                sql += " AND status = :status"
                params["status"] = status
            sql += " ORDER BY evidence_count DESC"
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
            out: list[MappingSuggestion] = []
            for row in rows:
                out.append(
                    MappingSuggestion(
                        id=row.id,
                        organization_id=row.organization_id,
                        concept=row.concept,
                        entity_type=row.entity_type,
                        physical_predicate=row.physical_predicate,
                        evidence_count=int(row.evidence_count or 0),
                        evidence_sample=_parse_json(row.evidence_sample, []),
                        status=MappingSuggestionStatus(row.status),
                        created_at=row.created_at,
                        reviewed_by=row.reviewed_by,
                        reviewed_at=row.reviewed_at,
                    )
                )
            return out
        finally:
            await session.close()

    async def review_mapping_suggestion(
        self,
        organization_id: UUID,
        suggestion_id: UUID,
        *,
        action: str,
        reviewed_by: UUID | None,
        physical_predicate: str | None = None,
    ) -> MappingSuggestion | None:
        status_map = {
            "APPROVE": MappingSuggestionStatus.APPROVED,
            "REJECT": MappingSuggestionStatus.REJECTED,
            "EDIT_AND_APPROVE": MappingSuggestionStatus.EDITED_APPROVED,
        }
        new_status = status_map.get(action.upper())
        if new_status is None:
            raise ValueError(f"Invalid action: {action}")
        session: AsyncSession = await get_async_session()
        now = datetime.now(timezone.utc)
        try:
            result = await session.execute(
                text(
                    "SELECT * FROM mapping_suggestions "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {"oid": organization_id, "id": suggestion_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            pred = physical_predicate or row.physical_predicate
            await session.execute(
                text(
                    "UPDATE mapping_suggestions SET status = :status, "
                    "physical_predicate = :pred, reviewed_by = :uid, "
                    "reviewed_at = :ts WHERE organization_id = :oid AND id = :id"
                ),
                {
                    "status": new_status.value,
                    "pred": pred,
                    "uid": reviewed_by,
                    "ts": now,
                    "oid": organization_id,
                    "id": suggestion_id,
                },
            )
            await session.commit()
            return MappingSuggestion(
                id=row.id,
                organization_id=row.organization_id,
                concept=row.concept,
                entity_type=row.entity_type,
                physical_predicate=pred,
                evidence_count=int(row.evidence_count or 0),
                evidence_sample=_parse_json(row.evidence_sample, []),
                status=new_status,
                created_at=row.created_at,
                reviewed_by=reviewed_by,
                reviewed_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Mapping review failed", error=str(exc))
            raise
        finally:
            await session.close()
