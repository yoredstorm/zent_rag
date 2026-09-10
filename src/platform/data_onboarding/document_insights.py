# =============================================================================
# Data Onboarding — persistencia de hechos extraídos de documentos
# =============================================================================
# document_insights guarda los datos clave detectados en un documento
# (partes, fechas, montos, cláusulas, identificadores) con su evidencia.
# Cada insight nace 'pending' y solo cambia por revisión humana
# (approved / edited / rejected). Nada se auto-aprueba.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_CREATE = """
CREATE TABLE IF NOT EXISTS document_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    session_id UUID,
    source_id UUID,
    insight_type VARCHAR(40) NOT NULL,
    key VARCHAR(200) NOT NULL,
    value TEXT NOT NULL,
    normalized_value TEXT,
    evidence TEXT,
    page INTEGER,
    confidence VARCHAR(10) NOT NULL DEFAULT 'medium',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewed_by UUID,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_document_insights_org_source "
    "ON document_insights(organization_id, source_id, status)"
)


class DocumentInsightsStore:
    _ready = False

    async def ensure_tables(self) -> None:
        if self._ready:
            return
        session = await get_async_session()
        try:
            await session.execute(text(_CREATE))
            await session.execute(text(_INDEX))
            await session.commit()
            self._ready = True
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("document_insights ensure failed", error=str(exc)[:200])
        finally:
            await session.close()

    @staticmethod
    def _row(row: Any) -> dict:
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "session_id": str(row.session_id) if row.session_id else None,
            "source_id": str(row.source_id) if row.source_id else None,
            "insight_type": row.insight_type,
            "key": row.key,
            "value": row.value,
            "normalized_value": row.normalized_value,
            "evidence": row.evidence,
            "page": row.page,
            "confidence": row.confidence,
            "status": row.status,
            "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "created_at": row.created_at.isoformat(),
        }

    async def create(
        self,
        organization_id: UUID,
        fact: dict,
        *,
        session_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> dict:
        await self.ensure_tables()
        sid = uuid4()
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO document_insights "
                        "(id, organization_id, session_id, source_id, insight_type, key, value, "
                        "normalized_value, evidence, page, confidence) "
                        "VALUES (:id, :oid, :sid, :src, :itype, :key, :value, :norm, :ev, :page, :conf) "
                        "RETURNING id, organization_id, session_id, source_id, insight_type, key, value, "
                        "normalized_value, evidence, page, confidence, status, reviewed_by, reviewed_at, created_at"
                    ),
                    {
                        "id": sid,
                        "oid": organization_id,
                        "sid": session_id,
                        "src": source_id,
                        "itype": str(fact.get("fact_type") or "fact")[:40],
                        "key": str(fact.get("key") or "Dato")[:200],
                        "value": str(fact.get("value") or ""),
                        "norm": fact.get("normalized_value"),
                        "ev": str(fact.get("evidence") or "")[:2000],
                        "page": fact.get("page"),
                        "conf": str(fact.get("confidence") or "medium")[:10],
                    },
                )
            ).fetchone()
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
        return self._row(row)

    async def list_by_session(self, organization_id: UUID, session_id: UUID) -> list[dict]:
        await self.ensure_tables()
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, session_id, source_id, insight_type, key, value, "
                        "normalized_value, evidence, page, confidence, status, reviewed_by, reviewed_at, created_at "
                        "FROM document_insights WHERE organization_id = :oid AND session_id = :sid "
                        "ORDER BY created_at ASC"
                    ),
                    {"oid": organization_id, "sid": session_id},
                )
            ).fetchall()
        finally:
            await session.close()
        return [self._row(r) for r in rows]

    async def list_by_source(self, organization_id: UUID, source_id: UUID) -> list[dict]:
        await self.ensure_tables()
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, session_id, source_id, insight_type, key, value, "
                        "normalized_value, evidence, page, confidence, status, reviewed_by, reviewed_at, created_at "
                        "FROM document_insights WHERE organization_id = :oid AND source_id = :src "
                        "ORDER BY created_at ASC"
                    ),
                    {"oid": organization_id, "src": source_id},
                )
            ).fetchall()
        finally:
            await session.close()
        return [self._row(r) for r in rows]

    async def update_status(
        self,
        organization_id: UUID,
        insight_id: UUID,
        status: str,
        *,
        value: str | None = None,
        normalized_value: str | None = None,
        key: str | None = None,
        reviewed_by: UUID | None = None,
    ) -> dict | None:
        await self.ensure_tables()
        session = await get_async_session()
        try:
            sets = ["status = :status", "reviewed_at = NOW()"]
            params: dict[str, Any] = {
                "oid": organization_id,
                "id": insight_id,
                "status": status,
                "rb": reviewed_by,
            }
            if value is not None:
                sets.append("value = :value")
                params["value"] = value
            if normalized_value is not None:
                sets.append("normalized_value = :norm")
                params["norm"] = normalized_value
            if key is not None:
                sets.append('"key" = :key')
                params["key"] = key
            if reviewed_by is not None:
                sets.append("reviewed_by = :rb")
            await session.execute(
                text(
                    "UPDATE document_insights SET "  # noqa: S608 — column names fijos
                    + ", ".join(sets)
                    + ", updated_at = NOW() WHERE organization_id = :oid AND id = :id"
                ),
                params,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
        return await self.get(organization_id, insight_id)

    async def get(self, organization_id: UUID, insight_id: UUID) -> dict | None:
        await self.ensure_tables()
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, session_id, source_id, insight_type, key, value, "
                        "normalized_value, evidence, page, confidence, status, reviewed_by, reviewed_at, created_at "
                        "FROM document_insights WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": insight_id},
                )
            ).fetchone()
        finally:
            await session.close()
        return self._row(row) if row else None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
