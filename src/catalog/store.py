# =============================================================================
# Catalog Store — persistencia del Discovery Engine & Semantic Catalog
# =============================================================================
# Raw-SQL fail-soft (convención del repo), org-scoped estricto, paginado.
# Tablas creadas por la migración 080 (ensure_tables es idempotente).
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.domain.catalog import (
    CatalogAuthority,
    CatalogEntity,
    CatalogField,
    CatalogMetric,
    CatalogSuggestion,
    LineageEdge,
    RelationshipStatus,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_CREATE_TABLES = [
    "CREATE TABLE IF NOT EXISTS catalog_sources (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, connector_id UUID NOT NULL, kb_source_id UUID, workspace_id UUID, engine VARCHAR(30) NOT NULL DEFAULT '', phase VARCHAR(30) NOT NULL DEFAULT 'QUEUED', budgets JSONB NOT NULL DEFAULT '{}'::jsonb, last_scan_at TIMESTAMPTZ, next_scan_at TIMESTAMPTZ, scan_interval_hours INT NOT NULL DEFAULT 0, content_signature VARCHAR(64), scan_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, connector_id))",
    "CREATE TABLE IF NOT EXISTS catalog_scans (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, source_id UUID NOT NULL, scan_type VARCHAR(20) NOT NULL DEFAULT 'initial', status VARCHAR(20) NOT NULL DEFAULT 'completed', tables_scanned INT NOT NULL DEFAULT 0, changes JSONB NOT NULL DEFAULT '[]'::jsonb, error TEXT, duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0, started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "CREATE TABLE IF NOT EXISTS catalog_tables (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, source_id UUID NOT NULL, schema_name VARCHAR(128) NOT NULL DEFAULT '', table_name VARCHAR(128) NOT NULL, is_view BOOLEAN NOT NULL DEFAULT false, row_count_approx BIGINT, table_comment TEXT, indexes JSONB NOT NULL DEFAULT '[]'::jsonb, content_hash VARCHAR(64), detected_at TIMESTAMPTZ NOT NULL DEFAULT now(), removed_at TIMESTAMPTZ, UNIQUE (organization_id, source_id, schema_name, table_name))",
    "CREATE TABLE IF NOT EXISTS catalog_columns (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, table_id UUID NOT NULL, column_name VARCHAR(128) NOT NULL, ordinal_position INT NOT NULL DEFAULT 0, data_type VARCHAR(128) NOT NULL DEFAULT '', nullable BOOLEAN NOT NULL DEFAULT true, is_primary_key BOOLEAN NOT NULL DEFAULT false, column_default TEXT, column_comment TEXT, null_ratio DOUBLE PRECISION, cardinality_approx BIGINT, pii_flags JSONB NOT NULL DEFAULT '[]'::jsonb, is_sensitive BOOLEAN NOT NULL DEFAULT false, sample_disabled BOOLEAN NOT NULL DEFAULT false, UNIQUE (organization_id, table_id, column_name))",
    "CREATE TABLE IF NOT EXISTS catalog_relationships (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, source_id UUID NOT NULL, from_table_id UUID NOT NULL, from_column VARCHAR(128) NOT NULL, to_table_id UUID NOT NULL, to_column VARCHAR(128) NOT NULL, relation_type VARCHAR(20) NOT NULL DEFAULT 'foreign_key', confidence VARCHAR(10) NOT NULL DEFAULT 'high', status VARCHAR(20) NOT NULL DEFAULT 'suggested', evidence JSONB NOT NULL DEFAULT '[]'::jsonb, reviewed_by UUID, reviewed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, from_table_id, from_column, to_table_id, to_column, relation_type))",
    "CREATE TABLE IF NOT EXISTS catalog_entities (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, name VARCHAR(160) NOT NULL, display_name VARCHAR(160) NOT NULL DEFAULT '', description TEXT, provenance VARCHAR(20) NOT NULL DEFAULT 'INFERRED', confidence VARCHAR(10) NOT NULL DEFAULT 'low', evidence JSONB NOT NULL DEFAULT '[]'::jsonb, mapped_table_id UUID, status VARCHAR(20) NOT NULL DEFAULT 'draft', created_by UUID, approved_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, name))",
    "CREATE TABLE IF NOT EXISTS catalog_fields (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, entity_id UUID NOT NULL, name VARCHAR(160) NOT NULL, description TEXT, provenance VARCHAR(20) NOT NULL DEFAULT 'INFERRED', confidence VARCHAR(10) NOT NULL DEFAULT 'low', mapped_column_id UUID, status VARCHAR(20) NOT NULL DEFAULT 'draft', created_by UUID, approved_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, entity_id, name))",
    "CREATE TABLE IF NOT EXISTS catalog_metrics (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, metric_key VARCHAR(160) NOT NULL, name VARCHAR(160) NOT NULL, definition TEXT NOT NULL, formula TEXT, semantic_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb, physical_mappings JSONB NOT NULL DEFAULT '[]'::jsonb, filters JSONB NOT NULL DEFAULT '[]'::jsonb, time_semantics VARCHAR(40), currency_semantics VARCHAR(40), owner VARCHAR(120), status VARCHAR(20) NOT NULL DEFAULT 'draft', version INT NOT NULL DEFAULT 1, definition_id UUID, created_by UUID, approved_by UUID, effective_from TIMESTAMPTZ, effective_to TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, metric_key))",
    "CREATE TABLE IF NOT EXISTS catalog_authority (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, domain VARCHAR(120) NOT NULL DEFAULT 'general', concept VARCHAR(160) NOT NULL, source_name VARCHAR(200) NOT NULL, source_type VARCHAR(20) NOT NULL DEFAULT 'connector', connector_id UUID, authority_level VARCHAR(20) NOT NULL DEFAULT 'authoritative', priority INT NOT NULL DEFAULT 1, effective_from TIMESTAMPTZ, effective_to TIMESTAMPTZ, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, domain, concept, source_name))",
    "CREATE TABLE IF NOT EXISTS catalog_suggestions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, type VARCHAR(40) NOT NULL, title VARCHAR(300) NOT NULL, description TEXT, evidence JSONB NOT NULL DEFAULT '[]'::jsonb, confidence VARCHAR(10) NOT NULL DEFAULT 'low', payload JSONB NOT NULL DEFAULT '{}'::jsonb, status VARCHAR(20) NOT NULL DEFAULT 'pending', affected_sources JSONB NOT NULL DEFAULT '[]'::jsonb, affected_agents JSONB NOT NULL DEFAULT '[]'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), reviewed_by UUID, reviewed_at TIMESTAMPTZ)",
    "CREATE TABLE IF NOT EXISTS catalog_enum_values (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, column_id UUID NOT NULL, value VARCHAR(200) NOT NULL, occurrence_count INT NOT NULL DEFAULT 0, documented_meaning TEXT, provenance VARCHAR(20) NOT NULL DEFAULT 'OBSERVED', confidence VARCHAR(10) NOT NULL DEFAULT 'low', status VARCHAR(20) NOT NULL DEFAULT 'pending', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, column_id, value))",
    "CREATE TABLE IF NOT EXISTS catalog_lineage (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, upstream_type VARCHAR(40) NOT NULL, upstream_id VARCHAR(64) NOT NULL, downstream_type VARCHAR(40) NOT NULL, downstream_id VARCHAR(64) NOT NULL, relation VARCHAR(30) NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "CREATE TABLE IF NOT EXISTS catalog_abbrev_lexicon (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, token VARCHAR(80) NOT NULL, meaning VARCHAR(160) NOT NULL, role VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN', status VARCHAR(20) NOT NULL DEFAULT 'signal', created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (organization_id, token, meaning))",
    "CREATE TABLE IF NOT EXISTS catalog_mapping_versions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), organization_id UUID NOT NULL, field_id UUID, column_id UUID, old_mapping JSONB NOT NULL DEFAULT '{}'::jsonb, new_mapping JSONB NOT NULL DEFAULT '{}'::jsonb, reason TEXT, source VARCHAR(40) NOT NULL DEFAULT 'studio', version INT NOT NULL DEFAULT 1, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
]

_ALTER_COLUMNS = [
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS role VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN'",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS mapping_type VARCHAR(40) NOT NULL DEFAULT 'DIRECT'",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS unit VARCHAR(40)",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS currency VARCHAR(12)",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS grain VARCHAR(40)",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS aggregation_behavior VARCHAR(40)",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS synonyms JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS signal_scores JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ",
    "ALTER TABLE catalog_fields ADD COLUMN IF NOT EXISTS effective_to TIMESTAMPTZ",
    "ALTER TABLE catalog_relationships ADD COLUMN IF NOT EXISTS business_from VARCHAR(160)",
    "ALTER TABLE catalog_relationships ADD COLUMN IF NOT EXISTS business_to VARCHAR(160)",
    "ALTER TABLE catalog_relationships ADD COLUMN IF NOT EXISTS business_verb VARCHAR(40)",
    "ALTER TABLE catalog_sources ADD COLUMN IF NOT EXISTS workspace_id UUID",
]


class PostgresCatalogStore:
    """Persistencia del catálogo (org-scoped, fail-soft)."""

    async def ensure_tables(self) -> None:
        session: AsyncSession = await get_async_session()
        try:
            for stmt in _CREATE_TABLES:
                await session.execute(text(stmt))
            await session.commit()
            for stmt in _ALTER_COLUMNS:
                try:
                    await session.execute(text(stmt))
                    await session.commit()
                except Exception as alter_exc:  # noqa: BLE001
                    await session.rollback()
                    logger.warning("Catalog alter skipped", error=str(alter_exc)[:200])
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog ensure_tables failed", error=str(exc))
        finally:
            await session.close()

    # ------------------------------------------------------------- catalog_sources
    async def upsert_source(
        self,
        *,
        organization_id: UUID,
        connector_id: UUID,
        kb_source_id: UUID | None = None,
        engine: str = "",
        budgets: dict | None = None,
        workspace_id: UUID | None = None,
    ) -> dict:
        session: AsyncSession = await get_async_session()
        source_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            result = await session.execute(
                text(
                    "INSERT INTO catalog_sources "
                    "(id, organization_id, connector_id, kb_source_id, workspace_id, engine, "
                    "phase, budgets, created_at, updated_at) "
                    "VALUES (:id, :oid, :connector, :kb, :wid, :engine, 'QUEUED', "
                    "CAST(:budgets AS jsonb), :now, :now) "
                    "ON CONFLICT (organization_id, connector_id) DO UPDATE SET "
                    "kb_source_id = EXCLUDED.kb_source_id, "
                    "workspace_id = COALESCE(EXCLUDED.workspace_id, catalog_sources.workspace_id), "
                    "budgets = EXCLUDED.budgets, "
                    "updated_at = EXCLUDED.updated_at "
                    "RETURNING id, phase, budgets"
                ),
                {
                    "id": source_id,
                    "oid": organization_id,
                    "connector": connector_id,
                    "kb": kb_source_id,
                    "wid": workspace_id,
                    "engine": engine[:30],
                    "budgets": json.dumps(budgets or {}),
                    "now": now,
                },
            )
            row = result.fetchone()
            await session.commit()
            if row is not None:
                source_id = UUID(str(row.id))
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog source upsert failed", error=str(exc))
        finally:
            await session.close()
        return {"id": source_id, "organization_id": organization_id}

    async def get_source(self, organization_id: UUID, source_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, connector_id, kb_source_id, "
                        "engine, phase, budgets, last_scan_at, next_scan_at, "
                        "scan_interval_hours, content_signature, scan_error, "
                        "created_at, updated_at FROM catalog_sources "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": source_id},
                )
            ).fetchone()
            return self._source_row(row) if row else None
        finally:
            await session.close()

    async def get_source_by_connector(
        self, organization_id: UUID, connector_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, connector_id, kb_source_id, "
                        "engine, phase, budgets, last_scan_at, next_scan_at, "
                        "scan_interval_hours, content_signature, scan_error, "
                        "created_at, updated_at FROM catalog_sources "
                        "WHERE organization_id = :oid AND connector_id = :connector"
                    ),
                    {"oid": organization_id, "connector": connector_id},
                )
            ).fetchone()
            return self._source_row(row) if row else None
        finally:
            await session.close()

    @staticmethod
    def _source_row(row) -> dict:
        return {
            "id": str(row.id),
            "organization_id": str(row.organization_id),
            "connector_id": str(row.connector_id),
            "kb_source_id": str(row.kb_source_id) if row.kb_source_id else None,
            "engine": row.engine,
            "phase": row.phase,
            "budgets": row.budgets or {},
            "last_scan_at": row.last_scan_at.isoformat() if row.last_scan_at else None,
            "next_scan_at": row.next_scan_at.isoformat() if row.next_scan_at else None,
            "scan_interval_hours": row.scan_interval_hours,
            "content_signature": row.content_signature,
            "scan_error": row.scan_error,
            "workspace_id": str(getattr(row, "workspace_id", None))
            if getattr(row, "workspace_id", None)
            else None,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    async def list_sources(
        self, organization_id: UUID, workspace_id: UUID | None = None
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, organization_id, connector_id, kb_source_id, workspace_id, "
                "engine, phase, budgets, last_scan_at, next_scan_at, "
                "scan_interval_hours, content_signature, scan_error, "
                "created_at, updated_at FROM catalog_sources "
                "WHERE organization_id = :oid"
            )
            params: dict = {"oid": organization_id}
            if workspace_id is not None:
                query += " AND workspace_id = :wid"
                params["wid"] = workspace_id
            query += " ORDER BY created_at DESC"
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._source_row(r) for r in rows]
        finally:
            await session.close()

    async def update_source(
        self, organization_id: UUID, source_id: UUID, **fields
    ) -> None:
        allowed = {
            "phase",
            "last_scan_at",
            "next_scan_at",
            "scan_interval_hours",
            "content_signature",
            "scan_error",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        session: AsyncSession = await get_async_session()
        try:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            await session.execute(
                text(
                    f"UPDATE catalog_sources SET {set_clause}, "
                    f"updated_at = now() "
                    f"WHERE organization_id = :oid AND id = :id"  # noqa: S608
                ),
                {"oid": organization_id, "id": source_id, **updates},
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog source update failed", error=str(exc))
        finally:
            await session.close()

    async def list_due_scans(self, now: datetime, limit: int = 20) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, connector_id FROM catalog_sources "
                        "WHERE next_scan_at IS NOT NULL AND next_scan_at <= :now "
                        "ORDER BY next_scan_at LIMIT :limit"
                    ),
                    {"now": now, "limit": limit},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "organization_id": str(r.organization_id),
                    "connector_id": str(r.connector_id),
                }
                for r in rows
            ]
        finally:
            await session.close()

    # -------------------------------------------------------------- catalog_scans
    async def create_scan(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        scan_type: str = "initial",
    ) -> UUID:
        scan_id = uuid4()
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_scans "
                    "(id, organization_id, source_id, scan_type, status, "
                    "started_at, created_at) "
                    "VALUES (:id, :oid, :source, :type, 'running', now(), now())"
                ),
                {"id": scan_id, "oid": organization_id, "source": source_id, "type": scan_type},
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog scan create failed", error=str(exc))
        finally:
            await session.close()
        return scan_id

    async def update_scan(
        self, scan_id: UUID, *, status: str, changes: list[dict] | None = None,
        tables_scanned: int | None = None, error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            terminal = status in ("completed", "partial", "failed", "cancelled")
            await session.execute(
                text(
                    "UPDATE catalog_scans SET status = :status, "
                    "changes = COALESCE(CAST(:changes AS jsonb), changes), "
                    "tables_scanned = COALESCE(:tables, tables_scanned), "
                    "error = COALESCE(:error, error), "
                    "duration_ms = COALESCE(:duration, duration_ms), "
                    "completed_at = CASE WHEN :terminal THEN now() "
                    "ELSE completed_at END WHERE id = :id"
                ),
                {
                    "id": scan_id,
                    "status": status,
                    "changes": json.dumps(changes or []),
                    "tables": tables_scanned,
                    "error": error,
                    "duration": duration_ms,
                    "terminal": terminal,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog scan update failed", error=str(exc))
        finally:
            await session.close()

    async def list_scans(
        self, organization_id: UUID, source_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, source_id, scan_type, status, tables_scanned, "
                        "changes, error, duration_ms, started_at, completed_at, "
                        "created_at FROM catalog_scans "
                        "WHERE organization_id = :oid AND source_id = :source "
                        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    {"oid": organization_id, "source": source_id, "limit": limit, "offset": offset},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "scan_type": r.scan_type,
                    "status": r.status,
                    "tables_scanned": r.tables_scanned,
                    "changes": r.changes or [],
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    # ------------------------------------------------------------- catalog_tables
    async def upsert_table(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        schema_name: str,
        table_name: str,
        is_view: bool = False,
        row_count_approx: int | None = None,
        table_comment: str | None = None,
        indexes: list[dict] | None = None,
        content_hash: str | None = None,
    ) -> tuple[UUID, bool]:
        """Inserta/actualiza; retorna (table_id, is_new)."""
        table_id = uuid4()
        session: AsyncSession = await get_async_session()
        try:
            existing = (
                await session.execute(
                    text(
                        "SELECT id FROM catalog_tables "
                        "WHERE organization_id = :oid AND source_id = :source "
                        "AND schema_name = :schema AND table_name = :table"
                    ),
                    {
                        "oid": organization_id,
                        "source": source_id,
                        "schema": schema_name,
                        "table": table_name,
                    },
                )
            ).fetchone()
            if existing:
                await session.execute(
                    text(
                        "UPDATE catalog_tables SET is_view = :view, "
                        "row_count_approx = :rows, table_comment = COALESCE(:comment, table_comment), "
                        "indexes = COALESCE(CAST(:indexes AS jsonb), indexes), "
                        "content_hash = :hash, removed_at = NULL, detected_at = now() "
                        "WHERE id = :id"
                    ),
                    {
                        "view": is_view,
                        "rows": row_count_approx,
                        "comment": table_comment,
                        "indexes": json.dumps(indexes or []),
                        "hash": content_hash,
                        "id": existing[0],
                    },
                )
                await session.commit()
                return UUID(str(existing[0])), False
            await session.execute(
                text(
                    "INSERT INTO catalog_tables "
                    "(id, organization_id, source_id, schema_name, table_name, "
                    "is_view, row_count_approx, table_comment, indexes, content_hash) "
                    "VALUES (:id, :oid, :source, :schema, :table, :view, :rows, "
                    ":comment, CAST(:indexes AS jsonb), :hash)"
                ),
                {
                    "id": table_id,
                    "oid": organization_id,
                    "source": source_id,
                    "schema": schema_name,
                    "table": table_name,
                    "view": is_view,
                    "rows": row_count_approx,
                    "comment": table_comment,
                    "indexes": json.dumps(indexes or []),
                    "hash": content_hash,
                },
            )
            await session.commit()
            return table_id, True
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog table upsert failed", error=str(exc))
            return table_id, False
        finally:
            await session.close()

    async def get_table(
        self, organization_id: UUID, table_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, source_id, schema_name, "
                        "table_name, is_view, row_count_approx, table_comment, "
                        "indexes, content_hash, detected_at, removed_at "
                        "FROM catalog_tables WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": table_id},
                )
            ).fetchone()
            return self._table_row(row) if row else None
        finally:
            await session.close()

    @staticmethod
    def _table_row(row) -> dict:
        return {
            "id": str(row.id),
            "source_id": str(row.source_id),
            "schema_name": row.schema_name,
            "table_name": row.table_name,
            "qualified_name": f"{row.schema_name}.{row.table_name}" if row.schema_name else row.table_name,
            "is_view": row.is_view,
            "row_count_approx": row.row_count_approx,
            "table_comment": row.table_comment,
            "indexes": row.indexes or [],
            "content_hash": row.content_hash,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            "removed_at": row.removed_at.isoformat() if row.removed_at else None,
        }

    async def list_tables(
        self,
        organization_id: UUID,
        source_id: UUID,
        *,
        include_removed: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, organization_id, source_id, schema_name, table_name, "
                "is_view, row_count_approx, table_comment, indexes, content_hash, "
                "detected_at, removed_at FROM catalog_tables "
                "WHERE organization_id = :oid AND source_id = :source "
            )
            if not include_removed:
                query += "AND removed_at IS NULL "
            query += "ORDER BY schema_name, table_name LIMIT :limit OFFSET :offset"
            rows = (
                await session.execute(
                    text(query),
                    {
                        "oid": organization_id,
                        "source": source_id,
                        "limit": limit,
                        "offset": offset,
                    },
                )
            ).fetchall()
            return [self._table_row(r) for r in rows]
        finally:
            await session.close()

    async def list_tables_by_ids(
        self, organization_id: UUID, table_ids: list[UUID]
    ) -> dict[UUID, dict]:
        if not table_ids:
            return {}
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, source_id, schema_name, "
                        "table_name, is_view, row_count_approx, table_comment, "
                        "indexes, content_hash, detected_at, removed_at "
                        "FROM catalog_tables WHERE organization_id = :oid "
                        "AND id = ANY(:ids)"
                    ),
                    {"oid": organization_id, "ids": table_ids},
                )
            ).fetchall()
            return {UUID(str(r.id)): self._table_row(r) for r in rows}
        finally:
            await session.close()

    async def mark_tables_removed(
        self,
        organization_id: UUID,
        source_id: UUID,
        active_ids: list[UUID],
    ) -> list[dict]:
        """Marca como removidas las tablas activas no vistas en el scan (drift)."""
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, schema_name, table_name FROM catalog_tables "
                        "WHERE organization_id = :oid AND source_id = :source "
                        "AND removed_at IS NULL AND NOT (id = ANY(:active))"
                    ),
                    {"oid": organization_id, "source": source_id, "active": active_ids or [UUID(int=0)]},
                )
            ).fetchall()
            removed = [{"id": str(r.id), "qualified_name": f"{r.schema_name}.{r.table_name}"} for r in rows]
            if rows:
                await session.execute(
                    text(
                        "UPDATE catalog_tables SET removed_at = now() "
                        "WHERE organization_id = :oid AND source_id = :source "
                        "AND removed_at IS NULL AND NOT (id = ANY(:active))"
                    ),
                    {"oid": organization_id, "source": source_id, "active": active_ids or [UUID(int=0)]},
                )
                await session.commit()
            return removed
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog mark removed failed", error=str(exc))
            return []
        finally:
            await session.close()

    # ------------------------------------------------------------ catalog_columns
    async def upsert_column(
        self,
        *,
        organization_id: UUID,
        table_id: UUID,
        column_name: str,
        ordinal_position: int = 0,
        data_type: str = "",
        nullable: bool = True,
        is_primary_key: bool = False,
        column_default: str | None = None,
        column_comment: str | None = None,
        null_ratio: float | None = None,
        cardinality_approx: int | None = None,
        pii_flags: list[str] | None = None,
        is_sensitive: bool = False,
        sample_disabled: bool = False,
    ) -> UUID:
        column_id = uuid4()
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_columns "
                    "(id, organization_id, table_id, column_name, ordinal_position, "
                    "data_type, nullable, is_primary_key, column_default, "
                    "column_comment, null_ratio, cardinality_approx, pii_flags, "
                    "is_sensitive, sample_disabled) "
                    "VALUES (:id, :oid, :table, :name, :ord, :dtype, :nullable, "
                    ":pk, :default, :comment, :null_ratio, :cardinality, "
                    "CAST(:pii AS jsonb), :sensitive, :sample_disabled) "
                    "ON CONFLICT (organization_id, table_id, column_name) DO UPDATE SET "
                    "ordinal_position = EXCLUDED.ordinal_position, "
                    "data_type = EXCLUDED.data_type, "
                    "nullable = EXCLUDED.nullable, "
                    "is_primary_key = EXCLUDED.is_primary_key, "
                    "column_default = EXCLUDED.column_default, "
                    "column_comment = COALESCE(EXCLUDED.column_comment, catalog_columns.column_comment), "
                    "null_ratio = EXCLUDED.null_ratio, "
                    "cardinality_approx = EXCLUDED.cardinality_approx, "
                    "pii_flags = EXCLUDED.pii_flags, "
                    "is_sensitive = EXCLUDED.is_sensitive, "
                    "sample_disabled = EXCLUDED.sample_disabled"
                ),
                {
                    "id": column_id,
                    "oid": organization_id,
                    "table": table_id,
                    "name": column_name,
                    "ord": ordinal_position,
                    "dtype": data_type[:128],
                    "nullable": nullable,
                    "pk": is_primary_key,
                    "default": column_default,
                    "comment": column_comment,
                    "null_ratio": null_ratio,
                    "cardinality": cardinality_approx,
                    "pii": json.dumps(pii_flags or []),
                    "sensitive": is_sensitive,
                    "sample_disabled": sample_disabled,
                },
            )
            existing = (
                await session.execute(
                    text(
                        "SELECT id FROM catalog_columns "
                        "WHERE organization_id = :oid AND table_id = :table "
                        "AND column_name = :name"
                    ),
                    {"oid": organization_id, "table": table_id, "name": column_name},
                )
            ).fetchone()
            await session.commit()
            if existing:
                column_id = UUID(str(existing[0]))
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog column upsert failed", error=str(exc))
        finally:
            await session.close()
        return column_id

    async def list_columns(
        self, organization_id: UUID, table_id: UUID
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, table_id, column_name, ordinal_position, "
                        "data_type, nullable, is_primary_key, column_default, "
                        "column_comment, null_ratio, cardinality_approx, pii_flags, "
                        "is_sensitive, sample_disabled FROM catalog_columns "
                        "WHERE organization_id = :oid AND table_id = :table "
                        "ORDER BY ordinal_position"
                    ),
                    {"oid": organization_id, "table": table_id},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "table_id": str(r.table_id),
                    "column_name": r.column_name,
                    "ordinal_position": r.ordinal_position,
                    "data_type": r.data_type,
                    "nullable": r.nullable,
                    "is_primary_key": r.is_primary_key,
                    "column_default": r.column_default,
                    "column_comment": r.column_comment,
                    "null_ratio": r.null_ratio,
                    "cardinality_approx": r.cardinality_approx,
                    "pii_flags": r.pii_flags or [],
                    "is_sensitive": r.is_sensitive,
                    "sample_disabled": r.sample_disabled,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def get_column(self, organization_id: UUID, column_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, table_id, column_name, ordinal_position, "
                        "data_type, nullable, is_primary_key, column_default, "
                        "column_comment, null_ratio, cardinality_approx, pii_flags, "
                        "is_sensitive, sample_disabled FROM catalog_columns "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": column_id},
                )
            ).fetchone()
            return self._column_row(row) if row else None
        finally:
            await session.close()

    @staticmethod
    def _column_row(row) -> dict:
        return {
            "id": str(row.id),
            "table_id": str(row.table_id),
            "column_name": row.column_name,
            "ordinal_position": row.ordinal_position,
            "data_type": row.data_type,
            "nullable": row.nullable,
            "is_primary_key": row.is_primary_key,
            "column_default": row.column_default,
            "column_comment": row.column_comment,
            "null_ratio": row.null_ratio,
            "cardinality_approx": row.cardinality_approx,
            "pii_flags": row.pii_flags or [],
            "is_sensitive": row.is_sensitive,
            "sample_disabled": row.sample_disabled,
        }

    # --------------------------------------------------------- catalog_relationships
    async def upsert_relationship(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        from_table_id: UUID,
        from_column: str,
        to_table_id: UUID,
        to_column: str,
        relation_type: str = "foreign_key",
        confidence: str = "high",
        status: RelationshipStatus = RelationshipStatus.SUGGESTED,
        evidence: list[str] | None = None,
    ) -> UUID:
        rel_id = uuid4()
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_relationships "
                    "(id, organization_id, source_id, from_table_id, from_column, "
                    "to_table_id, to_column, relation_type, confidence, status, evidence) "
                    "VALUES (:id, :oid, :source, :from_table, :from_col, :to_table, "
                    ":to_col, :rtype, :confidence, :status, CAST(:evidence AS jsonb)) "
                    "ON CONFLICT (organization_id, from_table_id, from_column, "
                    "to_table_id, to_column, relation_type) DO UPDATE SET "
                    "confidence = EXCLUDED.confidence, "
                    "evidence = EXCLUDED.evidence, "
                    "status = CASE WHEN catalog_relationships.status = 'confirmed' "
                    "THEN catalog_relationships.status ELSE EXCLUDED.status END"
                ),
                {
                    "id": rel_id,
                    "oid": organization_id,
                    "source": source_id,
                    "from_table": from_table_id,
                    "from_col": from_column,
                    "to_table": to_table_id,
                    "to_col": to_column,
                    "rtype": relation_type,
                    "confidence": confidence,
                    "status": status.value,
                    "evidence": json.dumps(evidence or []),
                },
            )
            existing = (
                await session.execute(
                    text(
                        "SELECT id FROM catalog_relationships "
                        "WHERE organization_id = :oid AND from_table_id = :from_table "
                        "AND from_column = :from_col AND to_table_id = :to_table "
                        "AND to_column = :to_col AND relation_type = :rtype"
                    ),
                    {
                        "oid": organization_id,
                        "from_table": from_table_id,
                        "from_col": from_column,
                        "to_table": to_table_id,
                        "to_col": to_column,
                        "rtype": relation_type,
                    },
                )
            ).fetchone()
            await session.commit()
            if existing:
                rel_id = UUID(str(existing[0]))
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog relationship upsert failed", error=str(exc))
        finally:
            await session.close()
        return rel_id

    async def list_relationships(
        self,
        organization_id: UUID,
        source_id: UUID,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, source_id, from_table_id, from_column, to_table_id, "
                "to_column, relation_type, confidence, status, evidence, "
                "reviewed_by, reviewed_at, created_at, business_from, business_to, "
                "business_verb FROM catalog_relationships "
                "WHERE organization_id = :oid AND source_id = :source "
            )
            params: dict = {"oid": organization_id, "source": source_id, "limit": limit, "offset": offset}
            if status:
                query += "AND status = :status "
                params["status"] = status
            query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            rows = (
                await session.execute(text(query), params)
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "source_id": str(r.source_id),
                    "from_table_id": str(r.from_table_id),
                    "from_column": r.from_column,
                    "to_table_id": str(r.to_table_id),
                    "to_column": r.to_column,
                    "relation_type": r.relation_type,
                    "confidence": r.confidence,
                    "status": r.status,
                    "evidence": r.evidence or [],
                    "reviewed_by": str(r.reviewed_by) if r.reviewed_by else None,
                    "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                    "business_from": getattr(r, "business_from", None),
                    "business_to": getattr(r, "business_to", None),
                    "business_verb": getattr(r, "business_verb", None),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def update_relationship_status(
        self,
        organization_id: UUID,
        rel_id: UUID,
        *,
        status: str,
        reviewed_by: UUID | None = None,
    ) -> bool:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE catalog_relationships SET status = :status, "
                    "reviewed_by = :reviewed, reviewed_at = now() "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {"status": status, "reviewed": reviewed_by, "oid": organization_id, "id": rel_id},
            )
            await session.commit()
            return (result.rowcount or 0) > 0
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog relationship update failed", error=str(exc))
            return False
        finally:
            await session.close()

    # ------------------------------------------------------------ catalog_entities
    async def list_entities(
        self, organization_id: UUID, *, limit: int = 200, offset: int = 0
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, name, display_name, description, provenance, "
                        "confidence, evidence, mapped_table_id, status, created_by, "
                        "approved_by, created_at, updated_at FROM catalog_entities "
                        "WHERE organization_id = :oid "
                        "ORDER BY name LIMIT :limit OFFSET :offset"
                    ),
                    {"oid": organization_id, "limit": limit, "offset": offset},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "display_name": r.display_name,
                    "description": r.description,
                    "provenance": r.provenance,
                    "confidence": r.confidence,
                    "evidence": r.evidence or [],
                    "mapped_table_id": str(r.mapped_table_id) if r.mapped_table_id else None,
                    "status": r.status,
                    "created_by": str(r.created_by) if r.created_by else None,
                    "approved_by": str(r.approved_by) if r.approved_by else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def get_entity(self, organization_id: UUID, entity_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, name, display_name, description, provenance, "
                        "confidence, evidence, mapped_table_id, status, created_by, "
                        "approved_by, created_at, updated_at FROM catalog_entities "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": entity_id},
                )
            ).fetchone()
            return self._entity_row(row) if row else None
        finally:
            await session.close()

    @staticmethod
    def _entity_row(row) -> dict:
        return {
            "id": str(row.id),
            "name": row.name,
            "display_name": row.display_name,
            "description": row.description,
            "provenance": row.provenance,
            "confidence": row.confidence,
            "evidence": row.evidence or [],
            "mapped_table_id": str(row.mapped_table_id) if row.mapped_table_id else None,
            "status": row.status,
            "created_by": str(row.created_by) if row.created_by else None,
            "approved_by": str(row.approved_by) if row.approved_by else None,
        }

    async def upsert_entity(
        self, entity: CatalogEntity
    ) -> UUID:
        session: AsyncSession = await get_async_session()
        now = datetime.now(timezone.utc)
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_entities "
                    "(id, organization_id, name, display_name, description, "
                    "provenance, confidence, evidence, mapped_table_id, status, "
                    "created_by, approved_by, created_at, updated_at) "
                    "VALUES (:id, :oid, :name, :display, :description, :provenance, "
                    ":confidence, CAST(:evidence AS jsonb), :mapped, :status, "
                    ":created_by, :approved_by, :now, :now) "
                    "ON CONFLICT (organization_id, name) DO UPDATE SET "
                    "display_name = EXCLUDED.display_name, "
                    "description = COALESCE(EXCLUDED.description, catalog_entities.description), "
                    "provenance = EXCLUDED.provenance, "
                    "confidence = EXCLUDED.confidence, "
                    "evidence = EXCLUDED.evidence, "
                    "mapped_table_id = EXCLUDED.mapped_table_id, "
                    "status = EXCLUDED.status, "
                    "approved_by = EXCLUDED.approved_by, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": entity.id,
                    "oid": entity.organization_id,
                    "name": entity.name,
                    "display": entity.display_name or entity.name,
                    "description": entity.description,
                    "provenance": entity.provenance.value,
                    "confidence": entity.confidence,
                    "evidence": json.dumps(entity.evidence),
                    "mapped": entity.mapped_table_id,
                    "status": entity.status,
                    "created_by": entity.created_by,
                    "approved_by": entity.approved_by,
                    "now": now,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog entity upsert failed", error=str(exc))
        finally:
            await session.close()
        return entity.id

    async def delete_entity(self, organization_id: UUID, entity_id: UUID) -> bool:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "DELETE FROM catalog_entities "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {"oid": organization_id, "id": entity_id},
            )
            await session.commit()
            return (result.rowcount or 0) > 0
        finally:
            await session.close()

    # -------------------------------------------------------------- catalog_fields
    async def list_fields(
        self, organization_id: UUID, entity_id: UUID
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, entity_id, name, description, provenance, "
                        "confidence, mapped_column_id, status, created_by, approved_by, "
                        "role, mapping_type, unit, currency, grain, aggregation_behavior, "
                        "synonyms, signal_scores "
                        "FROM catalog_fields WHERE organization_id = :oid "
                        "AND entity_id = :entity ORDER BY name"
                    ),
                    {"oid": organization_id, "entity": entity_id},
                )
            ).fetchall()
            return [
                self._field_row(r)
                for r in rows
            ]
        finally:
            await session.close()

    @staticmethod
    def _field_row(r) -> dict:
        synonyms = getattr(r, "synonyms", None) or []
        if isinstance(synonyms, str):
            try:
                synonyms = json.loads(synonyms)
            except (TypeError, ValueError):
                synonyms = []
        scores = getattr(r, "signal_scores", None) or {}
        if isinstance(scores, str):
            try:
                scores = json.loads(scores)
            except (TypeError, ValueError):
                scores = {}
        return {
            "id": str(r.id),
            "entity_id": str(r.entity_id),
            "name": r.name,
            "description": r.description,
            "provenance": r.provenance,
            "confidence": r.confidence,
            "mapped_column_id": str(r.mapped_column_id) if r.mapped_column_id else None,
            "status": r.status,
            "role": getattr(r, "role", None) or "UNKNOWN",
            "mapping_type": getattr(r, "mapping_type", None) or "DIRECT",
            "unit": getattr(r, "unit", None),
            "currency": getattr(r, "currency", None),
            "grain": getattr(r, "grain", None),
            "aggregation_behavior": getattr(r, "aggregation_behavior", None),
            "synonyms": synonyms if isinstance(synonyms, list) else [],
            "signal_scores": scores if isinstance(scores, dict) else {},
            "created_by": str(r.created_by) if r.created_by else None,
            "approved_by": str(r.approved_by) if r.approved_by else None,
        }

    async def get_field(self, organization_id: UUID, field_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, entity_id, name, description, provenance, "
                        "confidence, mapped_column_id, status, created_by, approved_by, "
                        "role, mapping_type, unit, currency, grain, aggregation_behavior, "
                        "synonyms, signal_scores "
                        "FROM catalog_fields WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": field_id},
                )
            ).fetchone()
            return self._field_row(row) if row else None
        finally:
            await session.close()

    async def upsert_field(self, field: CatalogField) -> UUID:
        session: AsyncSession = await get_async_session()
        now = datetime.now(timezone.utc)
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_fields "
                    "(id, organization_id, entity_id, name, description, "
                    "provenance, confidence, mapped_column_id, status, created_by, "
                    "approved_by, created_at, updated_at, role, mapping_type, unit, "
                    "currency, grain, aggregation_behavior, synonyms, signal_scores) "
                    "VALUES (:id, :oid, :entity, :name, :description, :provenance, "
                    ":confidence, :mapped, :status, :created_by, :approved_by, :now, :now, "
                    ":role, :mapping_type, :unit, :currency, :grain, :agg, "
                    "CAST(:synonyms AS jsonb), CAST(:scores AS jsonb)) "
                    "ON CONFLICT (organization_id, entity_id, name) DO UPDATE SET "
                    "description = COALESCE(EXCLUDED.description, catalog_fields.description), "
                    "provenance = EXCLUDED.provenance, "
                    "confidence = EXCLUDED.confidence, "
                    "mapped_column_id = EXCLUDED.mapped_column_id, "
                    "status = EXCLUDED.status, "
                    "approved_by = EXCLUDED.approved_by, "
                    "role = EXCLUDED.role, "
                    "mapping_type = EXCLUDED.mapping_type, "
                    "unit = EXCLUDED.unit, "
                    "currency = EXCLUDED.currency, "
                    "grain = EXCLUDED.grain, "
                    "aggregation_behavior = EXCLUDED.aggregation_behavior, "
                    "synonyms = EXCLUDED.synonyms, "
                    "signal_scores = EXCLUDED.signal_scores, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": field.id,
                    "oid": field.organization_id,
                    "entity": field.entity_id,
                    "name": field.name,
                    "description": field.description,
                    "provenance": field.provenance.value,
                    "confidence": field.confidence,
                    "mapped": field.mapped_column_id,
                    "status": field.status,
                    "created_by": field.created_by,
                    "approved_by": field.approved_by,
                    "now": now,
                    "role": field.role or "UNKNOWN",
                    "mapping_type": field.mapping_type or "DIRECT",
                    "unit": field.unit,
                    "currency": field.currency,
                    "grain": field.grain,
                    "agg": field.aggregation_behavior,
                    "synonyms": json.dumps(field.synonyms or []),
                    "scores": json.dumps(field.signal_scores or {}),
                },
            )
            existing = (
                await session.execute(
                    text(
                        "SELECT id FROM catalog_fields "
                        "WHERE organization_id = :oid AND entity_id = :entity AND name = :name"
                    ),
                    {
                        "oid": field.organization_id,
                        "entity": field.entity_id,
                        "name": field.name,
                    },
                )
            ).fetchone()
            await session.commit()
            if existing:
                field.id = UUID(str(existing[0]))
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog field upsert failed", error=str(exc))
        finally:
            await session.close()
        return field.id

    # ------------------------------------------------------------- catalog_metrics
    async def list_metrics(
        self, organization_id: UUID, *, status: str | None = None,
        limit: int = 200, offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, metric_key, name, definition, formula, "
                "semantic_dependencies, physical_mappings, filters, time_semantics, "
                "currency_semantics, owner, status, version, definition_id, "
                "created_by, approved_by, effective_from, effective_to, "
                "created_at, updated_at FROM catalog_metrics "
                "WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if status:
                query += "AND status = :status "
                params["status"] = status
            query += "ORDER BY name LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [self._metric_row(r) for r in rows]
        finally:
            await session.close()

    @staticmethod
    def _metric_row(row) -> dict:
        return {
            "id": str(row.id),
            "metric_key": row.metric_key,
            "name": row.name,
            "definition": row.definition,
            "formula": row.formula,
            "semantic_dependencies": row.semantic_dependencies or [],
            "physical_mappings": row.physical_mappings or [],
            "filters": row.filters or [],
            "time_semantics": row.time_semantics,
            "currency_semantics": row.currency_semantics,
            "owner": row.owner,
            "status": row.status,
            "version": row.version,
            "definition_id": str(row.definition_id) if row.definition_id else None,
            "created_by": str(row.created_by) if row.created_by else None,
            "approved_by": str(row.approved_by) if row.approved_by else None,
            "effective_from": row.effective_from.isoformat() if row.effective_from else None,
            "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        }

    async def get_metric(self, organization_id: UUID, metric_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, metric_key, name, definition, formula, "
                        "semantic_dependencies, physical_mappings, filters, "
                        "time_semantics, currency_semantics, owner, status, version, "
                        "definition_id, created_by, approved_by, effective_from, "
                        "effective_to, created_at, updated_at FROM catalog_metrics "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": metric_id},
                )
            ).fetchone()
            return self._metric_row(row) if row else None
        finally:
            await session.close()

    async def upsert_metric(self, metric: CatalogMetric) -> UUID:
        session: AsyncSession = await get_async_session()
        now = datetime.now(timezone.utc)
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_metrics "
                    "(id, organization_id, metric_key, name, definition, formula, "
                    "semantic_dependencies, physical_mappings, filters, "
                    "time_semantics, currency_semantics, owner, status, version, "
                    "definition_id, created_by, approved_by, effective_from, "
                    "effective_to, created_at, updated_at) "
                    "VALUES (:id, :oid, :mkey, :name, :definition, :formula, "
                    "CAST(:deps AS jsonb), CAST(:mappings AS jsonb), "
                    "CAST(:filters AS jsonb), :time_sem, :currency, :owner, :status, "
                    ":version, :def_id, :created_by, :approved_by, :eff_from, "
                    ":eff_to, :now, :now) "
                    "ON CONFLICT (organization_id, metric_key) DO UPDATE SET "
                    "name = EXCLUDED.name, "
                    "definition = EXCLUDED.definition, "
                    "formula = EXCLUDED.formula, "
                    "semantic_dependencies = EXCLUDED.semantic_dependencies, "
                    "physical_mappings = EXCLUDED.physical_mappings, "
                    "filters = EXCLUDED.filters, "
                    "time_semantics = EXCLUDED.time_semantics, "
                    "currency_semantics = EXCLUDED.currency_semantics, "
                    "owner = EXCLUDED.owner, "
                    "status = EXCLUDED.status, "
                    "version = catalog_metrics.version + 1, "
                    "definition_id = EXCLUDED.definition_id, "
                    "approved_by = EXCLUDED.approved_by, "
                    "effective_from = EXCLUDED.effective_from, "
                    "effective_to = EXCLUDED.effective_to, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": metric.id,
                    "oid": metric.organization_id,
                    "mkey": metric.metric_key,
                    "name": metric.name,
                    "definition": metric.definition,
                    "formula": metric.formula,
                    "deps": json.dumps(metric.semantic_dependencies),
                    "mappings": json.dumps(metric.physical_mappings),
                    "filters": json.dumps(metric.filters),
                    "time_sem": metric.time_semantics,
                    "currency": metric.currency_semantics,
                    "owner": metric.owner,
                    "status": metric.status,
                    "version": metric.version,
                    "def_id": metric.definition_id,
                    "created_by": metric.created_by,
                    "approved_by": metric.approved_by,
                    "eff_from": metric.effective_from,
                    "eff_to": metric.effective_to,
                    "now": now,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog metric upsert failed", error=str(exc))
        finally:
            await session.close()
        return metric.id

    # ------------------------------------------------------------ catalog_authority
    async def list_authority(self, organization_id: UUID) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, domain, concept, source_name, source_type, "
                        "connector_id, authority_level, priority, effective_from, "
                        "effective_to, created_by, created_at FROM catalog_authority "
                        "WHERE organization_id = :oid ORDER BY domain, concept, priority"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "domain": r.domain,
                    "concept": r.concept,
                    "source_name": r.source_name,
                    "source_type": r.source_type,
                    "connector_id": str(r.connector_id) if r.connector_id else None,
                    "authority_level": r.authority_level,
                    "priority": r.priority,
                    "effective_from": r.effective_from.isoformat() if r.effective_from else None,
                    "effective_to": r.effective_to.isoformat() if r.effective_to else None,
                    "created_by": str(r.created_by) if r.created_by else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def get_authority_for_concepts(
        self, organization_id: UUID, concepts: list[str], domain: str = "general"
    ) -> list[dict]:
        """Fuentes autoritativas activas para los conceptos dados."""
        if not concepts:
            return []
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, domain, concept, source_name, source_type, "
                        "connector_id, authority_level, priority, effective_from, "
                        "effective_to FROM catalog_authority "
                        "WHERE organization_id = :oid AND domain = :domain "
                        "AND concept = ANY(:concepts) "
                        "AND (effective_from IS NULL OR effective_from <= now()) "
                        "AND (effective_to IS NULL OR effective_to >= now()) "
                        "ORDER BY priority DESC"
                    ),
                    {"oid": organization_id, "domain": domain, "concepts": concepts},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "domain": r.domain,
                    "concept": r.concept,
                    "source_name": r.source_name,
                    "source_type": r.source_type,
                    "authority_level": r.authority_level,
                    "priority": r.priority,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def upsert_authority(self, authority: CatalogAuthority) -> UUID:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_authority "
                    "(id, organization_id, domain, concept, source_name, source_type, "
                    "connector_id, authority_level, priority, effective_from, "
                    "effective_to, created_by, created_at) "
                    "VALUES (:id, :oid, :domain, :concept, :source, :stype, "
                    ":connector, :level, :priority, :eff_from, :eff_to, :created_by, now()) "
                    "ON CONFLICT (organization_id, domain, concept, source_name) "
                    "DO UPDATE SET source_type = EXCLUDED.source_type, "
                    "connector_id = EXCLUDED.connector_id, "
                    "authority_level = EXCLUDED.authority_level, "
                    "priority = EXCLUDED.priority, "
                    "effective_from = EXCLUDED.effective_from, "
                    "effective_to = EXCLUDED.effective_to"
                ),
                {
                    "id": authority.id,
                    "oid": authority.organization_id,
                    "domain": authority.domain,
                    "concept": authority.concept,
                    "source": authority.source_name,
                    "stype": authority.source_type,
                    "connector": authority.connector_id,
                    "level": authority.authority_level,
                    "priority": authority.priority,
                    "eff_from": authority.effective_from,
                    "eff_to": authority.effective_to,
                    "created_by": authority.created_by,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog authority upsert failed", error=str(exc))
        finally:
            await session.close()
        return authority.id

    # ----------------------------------------------------------- catalog_suggestions
    async def create_suggestion(self, suggestion: CatalogSuggestion) -> UUID:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_suggestions "
                    "(id, organization_id, type, title, description, evidence, "
                    "confidence, payload, status, affected_sources, affected_agents, "
                    "created_at) "
                    "VALUES (:id, :oid, :type, :title, :description, "
                    "CAST(:evidence AS jsonb), :confidence, CAST(:payload AS jsonb), "
                    ":status, CAST(:sources AS jsonb), CAST(:agents AS jsonb), now())"
                ),
                {
                    "id": suggestion.id,
                    "oid": suggestion.organization_id,
                    "type": suggestion.type.value,
                    "title": suggestion.title,
                    "description": suggestion.description,
                    "evidence": json.dumps(suggestion.evidence),
                    "confidence": suggestion.confidence,
                    "payload": json.dumps(suggestion.payload),
                    "status": suggestion.status.value,
                    "sources": json.dumps(suggestion.affected_sources),
                    "agents": json.dumps(suggestion.affected_agents),
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog suggestion create failed", error=str(exc))
        finally:
            await session.close()
        return suggestion.id

    async def list_suggestions(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        type: str | None = None,  # noqa: A002
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, type, title, description, evidence, confidence, payload, "
                "status, affected_sources, affected_agents, created_at, reviewed_by, "
                "reviewed_at FROM catalog_suggestions WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
            if status:
                query += "AND status = :status "
                params["status"] = status
            if type:
                query += "AND type = :type "
                params["type"] = type
            query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            rows = (await session.execute(text(query), params)).fetchall()
            return [
                {
                    "id": str(r.id),
                    "type": r.type,
                    "title": r.title,
                    "description": r.description,
                    "evidence": r.evidence or [],
                    "confidence": r.confidence,
                    "payload": r.payload or {},
                    "status": r.status,
                    "affected_sources": r.affected_sources or [],
                    "affected_agents": r.affected_agents or [],
                    "created_at": r.created_at.isoformat(),
                    "reviewed_by": str(r.reviewed_by) if r.reviewed_by else None,
                    "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def get_suggestion(
        self, organization_id: UUID, suggestion_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, type, title, description, evidence, confidence, "
                        "payload, status, affected_sources, affected_agents, "
                        "created_at, reviewed_by, reviewed_at FROM catalog_suggestions "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": suggestion_id},
                )
            ).fetchone()
            return self._suggestion_row(row) if row else None
        finally:
            await session.close()

    @staticmethod
    def _suggestion_row(row) -> dict:
        return {
            "id": str(row.id),
            "type": row.type,
            "title": row.title,
            "description": row.description,
            "evidence": row.evidence or [],
            "confidence": row.confidence,
            "payload": row.payload or {},
            "status": row.status,
            "affected_sources": row.affected_sources or [],
            "affected_agents": row.affected_agents or [],
            "created_at": row.created_at.isoformat(),
            "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        }

    async def update_suggestion_status(
        self,
        organization_id: UUID,
        suggestion_id: UUID,
        *,
        status: str,
        reviewed_by: UUID | None = None,
        edited_payload: dict | None = None,
    ) -> bool:
        session: AsyncSession = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "UPDATE catalog_suggestions SET status = :status, "
                    "reviewed_by = :reviewed, reviewed_at = now(), "
                    "payload = COALESCE(CAST(:payload AS jsonb), payload) "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {
                    "status": status,
                    "reviewed": reviewed_by,
                    "payload": json.dumps(edited_payload) if edited_payload is not None else None,
                    "oid": organization_id,
                    "id": suggestion_id,
                },
            )
            await session.commit()
            return (result.rowcount or 0) > 0
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog suggestion update failed", error=str(exc))
            return False
        finally:
            await session.close()

    # ------------------------------------------------------------ catalog_enum_values
    async def upsert_enum_values(
        self,
        *,
        organization_id: UUID,
        column_id: UUID,
        values: list[str],
        counts: dict[str, int] | None = None,
    ) -> None:
        if not values:
            return
        counts = counts or {}
        session: AsyncSession = await get_async_session()
        try:
            for value in values:
                await session.execute(
                    text(
                        "INSERT INTO catalog_enum_values "
                        "(id, organization_id, column_id, value, occurrence_count, "
                        "provenance, status, created_at, updated_at) "
                        "VALUES (:id, :oid, :column, :value, :count, 'OBSERVED', "
                        "'pending', now(), now()) "
                        "ON CONFLICT (organization_id, column_id, value) DO UPDATE SET "
                        "occurrence_count = EXCLUDED.occurrence_count, "
                        "updated_at = now()"
                    ),
                    {
                        "id": uuid4(),
                        "oid": organization_id,
                        "column": column_id,
                        "value": value[:200],
                        "count": counts.get(value, 0),
                    },
                )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog enum upsert failed", error=str(exc))
        finally:
            await session.close()

    async def list_enum_values(
        self, organization_id: UUID, column_id: UUID
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, column_id, value, occurrence_count, "
                        "documented_meaning, provenance, confidence, status, "
                        "created_at, updated_at FROM catalog_enum_values "
                        "WHERE organization_id = :oid AND column_id = :column "
                        "ORDER BY value"
                    ),
                    {"oid": organization_id, "column": column_id},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "column_id": str(r.column_id),
                    "value": r.value,
                    "occurrence_count": r.occurrence_count,
                    "documented_meaning": r.documented_meaning,
                    "provenance": r.provenance,
                    "confidence": r.confidence,
                    "status": r.status,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def upsert_enum_meaning(
        self,
        *,
        organization_id: UUID,
        column_id: UUID,
        value: str,
        meaning: str,
        reviewed_by: UUID | None = None,
    ) -> None:
        """Documenta el significado de un valor de enum (aprobación humana)."""
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE catalog_enum_values SET documented_meaning = :meaning, "
                    "provenance = 'APPROVED', status = 'approved', "
                    "confidence = 'high', updated_at = now() "
                    "WHERE organization_id = :oid AND column_id = :column "
                    "AND value = :value"
                ),
                {
                    "meaning": meaning,
                    "oid": organization_id,
                    "column": column_id,
                    "value": value,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog enum meaning update failed", error=str(exc))
        finally:
            await session.close()

    # ------------------------------------------------------------------- lineage
    async def add_lineage_edge(self, edge: LineageEdge) -> None:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_lineage "
                    "(id, organization_id, upstream_type, upstream_id, "
                    "downstream_type, downstream_id, relation, metadata, created_at) "
                    "VALUES (:id, :oid, :up_type, :up_id, :down_type, :down_id, "
                    ":relation, CAST(:metadata AS jsonb), now())"
                ),
                {
                    "id": edge.id,
                    "oid": edge.organization_id,
                    "up_type": edge.upstream_type,
                    "up_id": edge.upstream_id,
                    "down_type": edge.downstream_type,
                    "down_id": edge.downstream_id,
                    "relation": edge.relation.value,
                    "metadata": json.dumps(edge.metadata),
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog lineage add failed", error=str(exc))
        finally:
            await session.close()

    async def list_lineage(
        self, organization_id: UUID, *, object_type: str | None = None,
        object_id: str | None = None, limit: int = 200,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT upstream_type, upstream_id, downstream_type, downstream_id, "
                "relation, metadata, created_at FROM catalog_lineage "
                "WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit}
            if object_type and object_id:
                query += (
                    "AND ((upstream_type = :otype AND upstream_id = :oid2) "
                    "OR (downstream_type = :otype AND downstream_id = :oid2)) "
                )
                params["otype"] = object_type
                params["oid2"] = object_id
            query += "ORDER BY created_at DESC LIMIT :limit"
            rows = (await session.execute(text(query), params)).fetchall()
            return [
                {
                    "upstream_type": r.upstream_type,
                    "upstream_id": r.upstream_id,
                    "downstream_type": r.downstream_type,
                    "downstream_id": r.downstream_id,
                    "relation": r.relation,
                    "metadata": r.metadata or {},
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def list_fields_all(
        self,
        organization_id: UUID,
        *,
        limit: int = 2000,
        workspace_id: UUID | None = None,
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            sql = (
                "SELECT f.id, f.entity_id, f.name, f.description, f.provenance, "
                "f.confidence, f.mapped_column_id, f.status, f.created_by, f.approved_by, "
                "f.role, f.mapping_type, f.unit, f.currency, f.grain, f.aggregation_behavior, "
                "f.synonyms, f.signal_scores "
                "FROM catalog_fields f "
            )
            params: dict = {"oid": organization_id, "limit": limit}
            if workspace_id is not None:
                sql += (
                    "JOIN catalog_columns c ON f.mapped_column_id = c.id "
                    "JOIN catalog_tables t ON c.table_id = t.id "
                    "JOIN catalog_sources s ON t.source_id = s.id "
                    "WHERE f.organization_id = :oid AND s.workspace_id = :wid "
                )
                params["wid"] = workspace_id
            else:
                sql += "WHERE f.organization_id = :oid "
            sql += "ORDER BY f.name LIMIT :limit"
            rows = (await session.execute(text(sql), params)).fetchall()
            return [self._field_row(r) for r in rows]
        finally:
            await session.close()

    async def list_lexicon(self, organization_id: UUID) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, token, meaning, role, status, created_by, "
                        "created_at, updated_at FROM catalog_abbrev_lexicon "
                        "WHERE organization_id = :oid ORDER BY token, meaning"
                    ),
                    {"oid": organization_id},
                )
            ).fetchall()
            return [
                {
                    "id": str(r.id),
                    "token": r.token,
                    "meaning": r.meaning,
                    "role": r.role,
                    "status": r.status,
                    "created_by": str(r.created_by) if r.created_by else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def upsert_lexicon_entry(
        self,
        *,
        organization_id: UUID,
        token: str,
        meaning: str,
        role: str = "UNKNOWN",
        status: str = "signal",
        created_by: UUID | None = None,
    ) -> dict:
        session: AsyncSession = await get_async_session()
        entry_id = uuid4()
        try:
            await session.execute(
                text(
                    "INSERT INTO catalog_abbrev_lexicon "
                    "(id, organization_id, token, meaning, role, status, created_by, "
                    "created_at, updated_at) "
                    "VALUES (:id, :oid, :token, :meaning, :role, :status, :created_by, "
                    "now(), now()) "
                    "ON CONFLICT (organization_id, token, meaning) DO UPDATE SET "
                    "role = EXCLUDED.role, status = EXCLUDED.status, updated_at = now()"
                ),
                {
                    "id": entry_id,
                    "oid": organization_id,
                    "token": token.strip().upper()[:80],
                    "meaning": meaning.strip()[:160],
                    "role": role[:40],
                    "status": status[:20],
                    "created_by": created_by,
                },
            )
            row = (
                await session.execute(
                    text(
                        "SELECT id, token, meaning, role, status FROM catalog_abbrev_lexicon "
                        "WHERE organization_id = :oid AND token = :token AND meaning = :meaning"
                    ),
                    {
                        "oid": organization_id,
                        "token": token.strip().upper()[:80],
                        "meaning": meaning.strip()[:160],
                    },
                )
            ).fetchone()
            await session.commit()
            if row:
                return {
                    "id": str(row.id),
                    "token": row.token,
                    "meaning": row.meaning,
                    "role": row.role,
                    "status": row.status,
                }
            return {
                "id": str(entry_id),
                "token": token.strip().upper(),
                "meaning": meaning.strip(),
                "role": role,
                "status": status,
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog lexicon upsert failed", error=str(exc))
            raise
        finally:
            await session.close()

    def lexicon_as_signals(self, rows: list[dict]) -> dict[str, list[tuple[str, str, float]]]:
        out: dict[str, list[tuple[str, str, float]]] = {}
        for row in rows:
            token = str(row.get("token") or "").upper()
            meaning = str(row.get("meaning") or "")
            role = str(row.get("role") or "UNKNOWN")
            score = 0.88 if row.get("status") == "approved" else 0.62
            out.setdefault(token, []).append((meaning, role, score))
        return out

    async def record_mapping_version(
        self,
        *,
        organization_id: UUID,
        field_id: UUID | None,
        column_id: UUID | None,
        old_mapping: dict,
        new_mapping: dict,
        reason: str | None = None,
        source: str = "studio",
        created_by: UUID | None = None,
    ) -> None:
        session: AsyncSession = await get_async_session()
        try:
            version_row = (
                await session.execute(
                    text(
                        "SELECT COALESCE(MAX(version), 0) + 1 AS v "
                        "FROM catalog_mapping_versions "
                        "WHERE organization_id = :oid AND field_id IS NOT DISTINCT FROM :fid"
                    ),
                    {"oid": organization_id, "fid": field_id},
                )
            ).fetchone()
            version = int(version_row[0]) if version_row else 1
            await session.execute(
                text(
                    "INSERT INTO catalog_mapping_versions "
                    "(id, organization_id, field_id, column_id, old_mapping, new_mapping, "
                    "reason, source, version, created_by, created_at) "
                    "VALUES (:id, :oid, :fid, :cid, CAST(:old AS jsonb), CAST(:new AS jsonb), "
                    ":reason, :source, :version, :created_by, now())"
                ),
                {
                    "id": uuid4(),
                    "oid": organization_id,
                    "fid": field_id,
                    "cid": column_id,
                    "old": json.dumps(old_mapping or {}),
                    "new": json.dumps(new_mapping or {}),
                    "reason": reason,
                    "source": source[:40],
                    "version": version,
                    "created_by": created_by,
                },
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog mapping version write failed", error=str(exc))
        finally:
            await session.close()

    async def list_mapping_versions(
        self, organization_id: UUID, field_id: UUID | None = None, limit: int = 50
    ) -> list[dict]:
        session: AsyncSession = await get_async_session()
        try:
            query = (
                "SELECT id, field_id, column_id, old_mapping, new_mapping, reason, "
                "source, version, created_by, created_at FROM catalog_mapping_versions "
                "WHERE organization_id = :oid "
            )
            params: dict = {"oid": organization_id, "limit": limit}
            if field_id:
                query += "AND field_id = :fid "
                params["fid"] = field_id
            query += "ORDER BY created_at DESC LIMIT :limit"
            rows = (await session.execute(text(query), params)).fetchall()
            return [
                {
                    "id": str(r.id),
                    "field_id": str(r.field_id) if r.field_id else None,
                    "column_id": str(r.column_id) if r.column_id else None,
                    "old_mapping": r.old_mapping or {},
                    "new_mapping": r.new_mapping or {},
                    "reason": r.reason,
                    "source": r.source,
                    "version": r.version,
                    "created_by": str(r.created_by) if r.created_by else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        finally:
            await session.close()

    async def get_enum_value(self, organization_id: UUID, value_id: UUID) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, column_id, value, occurrence_count, "
                        "documented_meaning, provenance, confidence, status "
                        "FROM catalog_enum_values "
                        "WHERE organization_id = :oid AND id = :id"
                    ),
                    {"oid": organization_id, "id": value_id},
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "id": str(row.id),
                "column_id": str(row.column_id),
                "value": row.value,
                "occurrence_count": row.occurrence_count,
                "documented_meaning": row.documented_meaning,
                "provenance": row.provenance,
                "confidence": row.confidence,
                "status": row.status,
            }
        finally:
            await session.close()

    async def update_enum_meaning_by_id(
        self,
        *,
        organization_id: UUID,
        value_id: UUID,
        meaning: str,
        reviewed_by: UUID | None = None,
    ) -> dict | None:
        del reviewed_by
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE catalog_enum_values SET documented_meaning = :meaning, "
                    "provenance = 'APPROVED', status = 'approved', "
                    "confidence = 'high', updated_at = now() "
                    "WHERE organization_id = :oid AND id = :id"
                ),
                {"meaning": meaning[:400], "oid": organization_id, "id": value_id},
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.warning("Catalog enum meaning by id failed", error=str(exc))
            return None
        finally:
            await session.close()
        return await self.get_enum_value(organization_id, value_id)

    async def get_pending_suggestion_for_column(
        self, organization_id: UUID, column_id: UUID
    ) -> dict | None:
        session: AsyncSession = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, type, title, description, evidence, confidence, "
                        "payload, status FROM catalog_suggestions "
                        "WHERE organization_id = :oid AND status = 'pending' "
                        "AND type = 'field_mapping' "
                        "AND (payload->>'column_id' = :cid OR payload->>'mapped_column_id' = :cid) "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"oid": organization_id, "cid": str(column_id)},
                )
            ).fetchone()
            if row is None:
                return None
            return {
                "id": str(row.id),
                "type": row.type,
                "title": row.title,
                "description": row.description,
                "evidence": row.evidence or [],
                "confidence": row.confidence,
                "payload": row.payload or {},
                "status": row.status,
            }
        finally:
            await session.close()
