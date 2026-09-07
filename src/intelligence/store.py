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
                understanding_payload = dict(trace.understanding or {})
                if trace.semantic_compile:
                    # Nested until a dedicated column exists (no migration in 26B).
                    understanding_payload = {
                        **understanding_payload,
                        "semantic_compile": trace.semantic_compile,
                    }
                await session.execute(
                    text(
                        "INSERT INTO intelligence_traces "
                        "(trace_id, organization_id, query_id, user_id, user_query, role, "
                        "understanding, query_plan, evidence, decision, status, "
                        "answer, method, model, budget, latency_ms) "
                        "VALUES (:trace_id, :oid, :qid, :uid, :query, :role, "
                        "CAST(:understanding AS jsonb), CAST(:plan AS jsonb), "
                        "CAST(:evidence AS jsonb), CAST(:decision AS jsonb), "
                        ":status, :answer, :method, :model, CAST(:budget AS jsonb), "
                        ":latency)"
                    ),
                    {
                        "trace_id": trace.trace_id,
                        "oid": trace.organization_id,
                        "qid": trace.query_id,
                        "uid": trace.user_id,
                        "query": trace.user_query[:32000],
                        "role": trace.role,
                        "understanding": json.dumps(understanding_payload),
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

    async def get_trace_by_query_id(
        self, organization_id: UUID, query_id: UUID
    ) -> dict | None:
        """Traza por query_id (para Why does Zent know this?)."""
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT trace_id, organization_id, query_id, user_query, role, "
                    "understanding, query_plan, evidence, decision, status, answer, "
                    "method, model, budget, latency_ms, created_at "
                    "FROM intelligence_traces "
                    "WHERE organization_id = :oid AND query_id = :qid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": organization_id, "qid": query_id},
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
            synonyms=list(row.synonyms or []) if hasattr(row, "synonyms") else [],
            owner=row.owner if hasattr(row, "owner") else None,
            version=int(row.version or 1) if hasattr(row, "version") else 1,
            effective_from=row.effective_from if hasattr(row, "effective_from") else None,
            effective_to=row.effective_to if hasattr(row, "effective_to") else None,
            approved_by=UUID(str(row.approved_by)) if getattr(row, "approved_by", None) else None,
            provenance=getattr(row, "provenance", "APPROVED") or "APPROVED",
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _definition_select() -> str:
        return (
            "id, organization_id, concept, definition, expression, data_type, "
            "status, authoritative_source_id, created_by, synonyms, owner, "
            "version, effective_from, effective_to, approved_by, provenance, "
            "created_at, updated_at"
        )

    async def list_definitions(
        self, organization_id: UUID, *, status: str | None = None,
        limit: int | None = None, offset: int = 0,
    ) -> list[BusinessDefinition]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                f"SELECT {self._definition_select()} FROM business_definitions "
                "WHERE organization_id = :oid"
            )
            params: dict = {"oid": organization_id, "offset": offset}
            if status:
                query += " AND status = :status"
                params["status"] = status
            query += " ORDER BY concept"
            if limit:
                query += " LIMIT :limit"
                params["limit"] = limit
            query += " OFFSET :offset"
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
                    f"SELECT {self._definition_select()} FROM business_definitions "
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
        synonyms: list[str] | None = None,
        owner: str | None = None,
        version: int = 1,
        effective_from=None,
        effective_to=None,
        approved_by: UUID | None = None,
        provenance: str = "APPROVED",
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
                    "synonyms, owner, version, effective_from, effective_to, "
                    "approved_by, provenance, created_at, updated_at) "
                    "VALUES (:id, :oid, :concept, :definition, :expression, "
                    ":data_type, :status, :auth_source, :created_by, "
                    "CAST(:synonyms AS jsonb), :owner, :version, :eff_from, "
                    ":eff_to, :approved_by, :provenance, :created_at, :updated_at) "
                    "ON CONFLICT (organization_id, concept) DO UPDATE SET "
                    "definition = EXCLUDED.definition, "
                    "expression = EXCLUDED.expression, "
                    "data_type = EXCLUDED.data_type, "
                    "status = EXCLUDED.status, "
                    "authoritative_source_id = EXCLUDED.authoritative_source_id, "
                    "synonyms = EXCLUDED.synonyms, "
                    "owner = EXCLUDED.owner, "
                    "version = EXCLUDED.version, "
                    "effective_from = EXCLUDED.effective_from, "
                    "effective_to = EXCLUDED.effective_to, "
                    "approved_by = EXCLUDED.approved_by, "
                    "provenance = EXCLUDED.provenance, "
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
                    "synonyms": json.dumps(synonyms or []),
                    "owner": owner,
                    "version": version,
                    "eff_from": effective_from,
                    "eff_to": effective_to,
                    "approved_by": approved_by,
                    "provenance": provenance,
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
            synonyms=synonyms or [],
            owner=owner,
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
            approved_by=approved_by,
            provenance=provenance,
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
        question: str | None = None,
        impact: dict | None = None,
    ) -> None:
        try:
            session: AsyncSession = await get_async_session()
            try:
                await session.execute(
                    text(
                        "INSERT INTO context_gaps "
                        "(organization_id, gap_type, concept, evidence_hints, "
                        "question, impact, occurrences, status, first_seen_at, last_seen_at) "
                        "VALUES (:oid, :gap_type, :concept, CAST(:hints AS jsonb), "
                        ":question, CAST(:impact AS jsonb), 1, 'open', now(), now()) "
                        "ON CONFLICT (organization_id, gap_type, concept) DO UPDATE SET "
                        "occurrences = context_gaps.occurrences + 1, "
                        "last_seen_at = now(), "
                        "question = COALESCE(EXCLUDED.question, context_gaps.question), "
                        "impact = EXCLUDED.impact, "
                        "evidence_hints = EXCLUDED.evidence_hints, "
                        "status = 'open'"
                    ),
                    {
                        "oid": organization_id,
                        "gap_type": gap_type[:30],
                        "concept": concept[:160],
                        "hints": json.dumps(hints or []),
                        "question": (question or "")[:2000] or None,
                        "impact": json.dumps(impact or {}),
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

    async def count_traces_by_status(
        self, organization_id: UUID, status, days: int = 30
    ) -> int:
        """Consultas (traces) con el mismo estado en la ventana."""
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM intelligence_traces "
                        "WHERE organization_id = :oid AND status = :status "
                        "AND created_at >= now() - make_interval(days => :days)"
                    ),
                    {
                        "oid": organization_id,
                        "status": status.value,
                        "days": days,
                    },
                )
            ).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            await session.close()

    async def count_trace_users(
        self, organization_id: UUID, status, days: int = 30
    ) -> int:
        """Usuarios distintos detrás de ese estado en la ventana."""
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(DISTINCT user_id) FROM intelligence_traces "
                        "WHERE organization_id = :oid AND status = :status "
                        "AND user_id IS NOT NULL "
                        "AND created_at >= now() - make_interval(days => :days)"
                    ),
                    {
                        "oid": organization_id,
                        "status": status.value,
                        "days": days,
                    },
                )
            ).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            await session.close()

    async def list_gaps(
        self,
        organization_id: UUID,
        *,
        gap_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Gaps de contexto/datos registrados (org-scoped, paginado)."""
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, gap_type, concept, evidence_hints, question, impact, "
                "occurrences, status, first_seen_at, last_seen_at, resolved_by, "
                "resolved_at FROM context_gaps WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if gap_type:
                query += "AND gap_type = :gap_type "
                params["gap_type"] = gap_type
            if status:
                query += "AND status = :status "
                params["status"] = status
            query += "ORDER BY last_seen_at DESC LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [
                {
                    "id": str(r.id),
                    "gap_type": r.gap_type,
                    "concept": r.concept,
                    "evidence_hints": r.evidence_hints or [],
                    "question": r.question,
                    "impact": r.impact or {},
                    "occurrences": r.occurrences,
                    "status": r.status,
                    "first_seen_at": r.first_seen_at.isoformat(),
                    "last_seen_at": r.last_seen_at.isoformat(),
                    "resolved_by": str(r.resolved_by) if r.resolved_by else None,
                    "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def resolve_gap(
        self,
        organization_id: UUID,
        gap_id: UUID,
        *,
        resolved_by: UUID | None = None,
    ) -> bool:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE context_gaps SET status = 'resolved', "
                    "resolved_by = :resolved_by, resolved_at = now() "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {"oid": organization_id, "id": gap_id, "resolved_by": resolved_by},
            )
            await session.commit()
            return (result.rowcount or 0) > 0
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Gap resolve failed", error=str(exc))
            return False
        finally:
            await session.close()
