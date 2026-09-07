# =============================================================================
# Intelligence Store — persistencia de traces, definiciones y gaps
# =============================================================================
# Patrón raw-SQL fail-soft (convención del repo: nunca romper el flujo RAG).
# Tablas creadas por la migración 079 (idempotente también en runtime).
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.intelligence import BusinessDefinition, IntelligenceTrace
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_CREATE_TABLES = [
    """
CREATE TABLE IF NOT EXISTS business_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    concept VARCHAR(160) NOT NULL,
    definition TEXT NOT NULL,
    expression TEXT,
    data_type VARCHAR(20) NOT NULL DEFAULT 'concept',
    status VARCHAR(20) NOT NULL DEFAULT 'approved',
    authoritative_source_id VARCHAR(120),
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, concept)
)
""",
    """
CREATE TABLE IF NOT EXISTS intelligence_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(64) NOT NULL UNIQUE,
    organization_id UUID NOT NULL,
    query_id UUID,
    user_query TEXT NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    understanding JSONB NOT NULL DEFAULT '{}'::jsonb,
    query_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(40) NOT NULL,
    answer TEXT,
    method VARCHAR(20) NOT NULL DEFAULT 'rag',
    model VARCHAR(120),
    budget JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    """
CREATE TABLE IF NOT EXISTS context_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    gap_type VARCHAR(30) NOT NULL,
    concept VARCHAR(160) NOT NULL,
    evidence_hints JSONB NOT NULL DEFAULT '[]'::jsonb,
    occurrences INT NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, gap_type, concept)
)
""",
]


class PostgresIntelligenceStore:
    """Persistencia de la Intelligence Layer (org-scoped, fail-soft)."""

    async def ensure_tables(self) -> None:
        session: AsyncSession = await get_async_session()
        try:
            for stmt in _CREATE_TABLES:
                await session.execute(text(stmt))
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Intelligence store ensure_tables failed", error=str(exc))
        finally:
            await session.close()

    # ------------------------------------------------------------------ traces
    async def save_trace(self, trace: IntelligenceTrace) -> None:
        try:
            session: AsyncSession = await get_async_session()
            try:
                await session.execute(
                    text(
                        "INSERT INTO intelligence_traces "
                        "(trace_id, organization_id, query_id, user_query, role, "
                        "understanding, query_plan, evidence, decision, status, "
                        "answer, method, model, budget, latency_ms) "
                        "VALUES (:trace_id, :oid, :qid, :query, :role, "
                        "CAST(:understanding AS jsonb), CAST(:plan AS jsonb), "
                        "CAST(:evidence AS jsonb), CAST(:decision AS jsonb), "
                        ":status, :answer, :method, :model, CAST(:budget AS jsonb), "
                        ":latency)"
                    ),
                    {
                        "trace_id": trace.trace_id,
                        "oid": trace.organization_id,
                        "qid": trace.query_id,
                        "query": trace.user_query[:32000],
                        "role": trace.role,
                        "understanding": json.dumps(trace.understanding or {}),
                        "plan": json.dumps(trace.query_plan or {}),
                        "evidence": json.dumps(trace.evidence or []),
                        "decision": json.dumps(trace.decision or {}),
                        "status": trace.status[:40],
                        "answer": (trace.answer or "")[:32000] or None,
                        "method": trace.method[:20],
                        "model": (trace.model or "")[:120] or None,
                        "budget": json.dumps(trace.budget or {}),
                        "latency": round(trace.latency_ms, 2),
                    },
                )
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("Intelligence trace save failed", error=str(exc))
            finally:
                await session.close()
        except Exception:  # noqa: BLE001
            pass

    async def get_trace(
        self, organization_id: UUID, trace_id: str
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT trace_id, organization_id, query_id, user_query, role, "
                    "understanding, query_plan, evidence, decision, status, answer, "
                    "method, model, budget, latency_ms, created_at "
                    "FROM intelligence_traces "
                    "WHERE organization_id = :oid AND trace_id = :trace_id"
                ),
                {"oid": organization_id, "trace_id": trace_id[:64]},
            )
            row = result.fetchone()
            if row is None:
                return None
            return {
                "trace_id": row.trace_id,
                "organization_id": str(row.organization_id),
                "query_id": str(row.query_id) if row.query_id else None,
                "user_query": row.user_query,
                "role": row.role,
                "understanding": row.understanding,
                "query_plan": row.query_plan,
                "evidence": row.evidence,
                "decision": row.decision,
                "status": row.status,
                "answer": row.answer,
                "method": row.method,
                "model": row.model,
                "budget": row.budget,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at.isoformat(),
            }
        finally:
            await session.close()

    # ------------------------------------------------------------- definitions
    @staticmethod
    def _row_to_definition(row) -> BusinessDefinition:
        return BusinessDefinition(
            id=UUID(str(row.id)),
            organization_id=UUID(str(row.organization_id)),
            concept=row.concept,
            definition=row.definition,
            expression=row.expression,
            data_type=row.data_type,
            status=row.status,
            authoritative_source_id=row.authoritative_source_id,
            created_by=UUID(str(row.created_by)) if row.created_by else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_definitions(
        self, organization_id: UUID, *, status: str | None = None
    ) -> list[BusinessDefinition]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, organization_id, concept, definition, expression, "
                "data_type, status, authoritative_source_id, created_by, "
                "created_at, updated_at FROM business_definitions "
                "WHERE organization_id = :oid"
            )
            params: dict = {"oid": organization_id}
            if status:
                query += " AND status = :status"
                params["status"] = status
            query += " ORDER BY concept"
            result = await session.execute(text(query), params)
            return [self._row_to_definition(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def get_definition(
        self, organization_id: UUID, concept: str
    ) -> BusinessDefinition | None:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, concept, definition, expression, "
                    "data_type, status, authoritative_source_id, created_by, "
                    "created_at, updated_at FROM business_definitions "
                    "WHERE organization_id = :oid AND concept = :concept"
                ),
                {"oid": organization_id, "concept": concept.strip().lower()},
            )
            row = result.fetchone()
            return self._row_to_definition(row) if row else None
        finally:
            await session.close()

    async def upsert_definition(
        self,
        *,
        organization_id: UUID,
        concept: str,
        definition: str,
        expression: str | None = None,
        data_type: str = "concept",
        status: str = "approved",
        authoritative_source_id: str | None = None,
        created_by: UUID | None = None,
    ) -> BusinessDefinition:
        session: AsyncSession = await get_async_session()
        definition_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            await session.execute(
                text(
                    "INSERT INTO business_definitions "
                    "(id, organization_id, concept, definition, expression, "
                    "data_type, status, authoritative_source_id, created_by, "
                    "created_at, updated_at) "
                    "VALUES (:id, :oid, :concept, :definition, :expression, "
                    ":data_type, :status, :auth_source, :created_by, :created_at, :updated_at) "
                    "ON CONFLICT (organization_id, concept) DO UPDATE SET "
                    "definition = EXCLUDED.definition, "
                    "expression = EXCLUDED.expression, "
                    "data_type = EXCLUDED.data_type, "
                    "status = EXCLUDED.status, "
                    "authoritative_source_id = EXCLUDED.authoritative_source_id, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": definition_id,
                    "oid": organization_id,
                    "concept": concept.strip().lower(),
                    "definition": definition,
                    "expression": expression,
                    "data_type": data_type,
                    "status": status,
                    "auth_source": authoritative_source_id,
                    "created_by": created_by,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Business definition upsert failed", error=str(exc))
        finally:
            await session.close()
        return BusinessDefinition(
            id=definition_id,
            organization_id=organization_id,
            concept=concept.strip().lower(),
            definition=definition,
            expression=expression,
            data_type=data_type,
            status=status,
            authoritative_source_id=authoritative_source_id,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )

    async def delete_definition(
        self, organization_id: UUID, concept: str
    ) -> bool:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "DELETE FROM business_definitions "
                    "WHERE organization_id = :oid AND concept = :concept"
                ),
                {"oid": organization_id, "concept": concept.strip().lower()},
            )
            await session.commit()
            return (result.rowcount or 0) > 0
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Business definition delete failed", error=str(exc))
            return False
        finally:
            await session.close()

    # ------------------------------------------------------------------- gaps
    async def record_gap(
        self,
        *,
        organization_id: UUID,
        gap_type: str,
        concept: str,
        hints: list[str] | None = None,
    ) -> None:
        try:
            session: AsyncSession = await get_async_session()
            try:
                await session.execute(
                    text(
                        "INSERT INTO context_gaps "
                        "(organization_id, gap_type, concept, evidence_hints, "
                        "occurrences, status, first_seen_at, last_seen_at) "
                        "VALUES (:oid, :gap_type, :concept, CAST(:hints AS jsonb), "
                        "1, 'open', now(), now()) "
                        "ON CONFLICT (organization_id, gap_type, concept) DO UPDATE SET "
                        "occurrences = context_gaps.occurrences + 1, "
                        "last_seen_at = now(), "
                        "evidence_hints = EXCLUDED.evidence_hints, "
                        "status = 'open'"
                    ),
                    {
                        "oid": organization_id,
                        "gap_type": gap_type[:30],
                        "concept": concept[:160],
                        "hints": json.dumps(hints or []),
                    },
                )
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("Context gap record failed", error=str(exc))
            finally:
                await session.close()
        except Exception:  # noqa: BLE001
            pass
