# =============================================================================
# Tabular Repository — Postgres (Knowledge Tabular V2)
# =============================================================================
# Persiste el árbol TabularWorkbook en tabular_workbooks/sheets/tables/
# columns/rows. Scoped estricto por organization_id en TODA operación.
#
# Incremental (brief §12): upsert_workbook compara schema_hash + row hashes
# persistidos y:
#   - workbook sin cambios (mismo content_hash) → no escribe nada;
#   - tabla sin cambios → no toca filas (solo actualiza metadata de la tabla);
#   - tabla con cambios → upsert de filas nuevas/actualizadas + delete de las
#     filas que ya no existen (nunca recrea la tabla completa);
#   - tabla eliminada → delete cascade.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.tabular import (
    TableDiff,
    TableFingerprint,
    TabularFingerprint,
    TabularTable,
    TabularWorkbook,
    WorkbookDiff,
)
from src.core.ports.tabular import TabularRepository
from src.infrastructure.postgres.session import get_async_session

_ROW_BATCH = 500
_TABLE_COLUMNS_JOIN = (
    "t.id, t.workbook_id, t.sheet_id, t.organization_id, t.source_id, t.name, "
    "t.title, t.table_range, t.header_rows, t.header_depth, t.detection_method, "
    "t.detection_confidence, t.header_confidence, t.schema_hash, t.content_hash, "
    "t.column_count, t.row_count, t.context, t.metadata, t.updated_at, "
    "s.name AS sheet_name"
)
_RANGE_OPERATORS = {">", ">=", "<", "<=", "=", "!="}
_NUMERIC_GUARD = "(values ->> :{key}) ~ '^[+-]?[0-9]+(\\.[0-9]+)?$'"


class PostgresTabularRepository(TabularRepository):

    # ------------------------------------------------------------------
    # Writer
    # ------------------------------------------------------------------
    async def upsert_workbook(
        self,
        workbook: TabularWorkbook,
        diff: WorkbookDiff,
        *,
        knowledge_base_id: UUID | None = None,
    ) -> None:
        session = await get_async_session()
        try:
            diffs_by_table = {table_diff.table_id: table_diff for table_diff in diff.table_diffs}
            # El workbook debe existir primero (FK de sheets/tables).
            await self._upsert_workbook_row(
                session, workbook, knowledge_base_id=knowledge_base_id
            )
            current_table_ids: set[UUID] = set()
            for sheet in workbook.sheets:
                await self._upsert_sheet(session, workbook, sheet)
                for table in sheet.tables:
                    current_table_ids.add(table.id)
                    table_diff = diffs_by_table.get(table.id)
                    await self._upsert_table(
                        session, workbook, sheet, table, table_diff
                    )

            if diff.deleted_table_ids:
                await session.execute(
                    text(
                        "DELETE FROM tabular_tables WHERE organization_id = :oid "
                        "AND workbook_id = :wid AND id = ANY(:ids)"
                    ),
                    {
                        "oid": str(workbook.organization_id),
                        "wid": str(workbook.id),
                        "ids": [str(table_id) for table_id in diff.deleted_table_ids],
                    },
                )
            await self._delete_missing_sheets(session, workbook)
            await self._upsert_relations(session, workbook)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get_fingerprint(
        self, organization_id: UUID, workbook_id: UUID
    ) -> TabularFingerprint | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT content_hash, CAST(metadata AS jsonb) AS metadata "
                    "FROM tabular_workbooks "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": str(workbook_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            content_hash = row.content_hash if row is not None else None
            pipeline_version = ""
            chunking_policy = ""
            materialization_policy = ""
            materialized_tables: list = []
            representations: dict = {}
            if row is not None and isinstance(row.metadata, dict):
                pipeline_version = str(row.metadata.get("pipeline_version") or "")
                chunking_policy = str(row.metadata.get("chunking_policy") or "")
                materialization_policy = str(
                    row.metadata.get("materialization_policy") or ""
                )
                raw_materialized = row.metadata.get("materialized_tables")
                if isinstance(raw_materialized, list):
                    materialized_tables = raw_materialized
                raw_representations = row.metadata.get("representations")
                if isinstance(raw_representations, dict):
                    representations = raw_representations

            tables_result = await session.execute(
                text(
                    "SELECT id, schema_hash FROM tabular_tables "
                    "WHERE organization_id = :oid AND workbook_id = :wid"
                ),
                {"oid": str(organization_id), "wid": str(workbook_id)},
            )
            table_rows = tables_result.fetchall()
            if content_hash is None and not table_rows:
                return None

            table_hashes: dict[UUID, dict[int, str]] = {}
            if table_rows:
                hashes_result = await session.execute(
                    text(
                        "SELECT table_id, physical_row, content_hash FROM tabular_rows "
                        "WHERE organization_id = :oid AND table_id = ANY(:ids)"
                    ),
                    {
                        "oid": str(organization_id),
                        "ids": [str(table_row.id) for table_row in table_rows],
                    },
                )
                for row_hash in hashes_result.fetchall():
                    table_uuid = UUID(str(row_hash.table_id))
                    table_hashes.setdefault(table_uuid, {})[
                        int(row_hash.physical_row)
                    ] = row_hash.content_hash

            return TabularFingerprint(
                workbook_id=workbook_id,
                content_hash=content_hash,
                pipeline_version=pipeline_version,
                chunking_policy=chunking_policy,
                materialization_policy=materialization_policy,
                materialized_tables=materialized_tables,
                representations=representations,
                tables={
                    UUID(str(table_row.id)): TableFingerprint(
                        table_id=UUID(str(table_row.id)),
                        schema_hash=table_row.schema_hash or "",
                        row_hashes=table_hashes.get(UUID(str(table_row.id)), {}),
                    )
                    for table_row in table_rows
                },
            )
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Readers (organización siempre obligatoria)
    # ------------------------------------------------------------------
    async def get_workbook(
        self, organization_id: UUID, source_id: UUID, external_id: str
    ) -> dict | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, source_id, "
                    "knowledge_base_id, external_id, filename, format, content_hash, "
                    "sheet_count, table_count, row_count, cell_count, profile, quality, "
                    "metadata, created_at, updated_at FROM tabular_workbooks "
                    "WHERE organization_id = :oid AND source_id = :sid "
                    "AND external_id = :eid"
                ),
                {
                    "oid": str(organization_id),
                    "sid": str(source_id),
                    "eid": external_id,
                },
            )
            row = result.fetchone()
            return _workbook_to_dict(row) if row is not None else None
        finally:
            await session.close()

    async def list_workbooks(
        self,
        organization_id: UUID,
        source_id: UUID | None = None,
        *,
        knowledge_base_id: UUID | None = None,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            clauses = ["organization_id = :oid"]
            params: dict = {"oid": str(organization_id)}
            if source_id is not None:
                clauses.append("source_id = :sid")
                params["sid"] = str(source_id)
            if knowledge_base_id is not None:
                clauses.append("knowledge_base_id = :kid")
                params["kid"] = str(knowledge_base_id)
            result = await session.execute(
                text(
                    "SELECT id, external_id, filename, format, content_hash, "  # noqa: S608 (valores parametrizados)
                    "sheet_count, table_count, row_count, cell_count, "
                    "CAST(profile AS jsonb) AS profile, CAST(quality AS jsonb) AS quality, "
                    "CAST(metadata AS jsonb) AS metadata, created_at, updated_at "
                    "FROM tabular_workbooks "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY updated_at DESC LIMIT 50"
                ),
                params,
            )
            return [
                {
                    "id": str(row.id),
                    "external_id": row.external_id,
                    "filename": row.filename,
                    "format": row.format,
                    "content_hash": row.content_hash,
                    "sheet_count": row.sheet_count,
                    "table_count": row.table_count,
                    "row_count": row.row_count,
                    "cell_count": row.cell_count,
                    "quality_score": (
                        (row.quality or {}).get("quality_score")
                        if isinstance(row.quality, dict)
                        else None
                    ),
                    "quality_warnings": (
                        len((row.quality or {}).get("warnings") or [])
                        if isinstance(row.quality, dict)
                        else 0
                    ),
                    "representations": (
                        (row.metadata or {}).get("representations")
                        if isinstance(row.metadata, dict)
                        else None
                    ),
                    "limits_hit": (
                        (row.profile or {}).get("limits_hit", [])
                        if isinstance(row.profile, dict)
                        else []
                    ),
                    "chunk_count": (
                        (row.metadata or {}).get("chunk_count")
                        if isinstance(row.metadata, dict)
                        else None
                    ),
                    "chunking_policy": (
                        (row.metadata or {}).get("chunking_policy")
                        if isinstance(row.metadata, dict)
                        else None
                    ),
                    "pipeline_version": (
                        (row.metadata or {}).get("pipeline_version")
                        if isinstance(row.metadata, dict)
                        else None
                    ),
                    "materialization": (
                        {
                            "status": (row.metadata or {}).get("materialization_status"),
                            "tables": (row.metadata or {}).get("materialized_tables"),
                            "detail": (row.metadata or {}).get("materialization_detail"),
                        }
                        if isinstance(row.metadata, dict)
                        else None
                    ),
                    "updated_at": row.updated_at,
                }
                for row in result.fetchall()
            ]
        finally:
            await session.close()

    async def list_tables(
        self,
        organization_id: UUID,
        source_id: UUID | None = None,
        *,
        workbook_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            clauses = ["t.organization_id = :oid"]
            params: dict = {"oid": str(organization_id)}
            if source_id is not None:
                clauses.append("t.source_id = :sid")
                params["sid"] = str(source_id)
            if workbook_id is not None:
                clauses.append("t.workbook_id = :wid")
                params["wid"] = str(workbook_id)
            if knowledge_base_id is not None:
                clauses.append(
                    "t.workbook_id IN (SELECT id FROM tabular_workbooks "
                    "WHERE organization_id = :oid AND knowledge_base_id = :kid)"
                )
                params["kid"] = str(knowledge_base_id)
            result = await session.execute(
                text(
                    f"SELECT {_TABLE_COLUMNS_JOIN} "  # noqa: S608 (columnas/cláusulas estáticas; valores parametrizados)
                    "FROM tabular_tables t "
                    "LEFT JOIN tabular_sheets s ON s.id = t.sheet_id "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY t.workbook_id, t.name LIMIT 500"
                ),
                params,
            )
            return [_table_to_dict(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def list_columns(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        workbook_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> list[dict]:
        """Columnas (con tabla/hoja) para el mapa tabular, en una sola query."""
        session = await get_async_session()
        try:
            clauses = ["c.organization_id = :oid"]
            params: dict = {"oid": str(organization_id)}
            if source_id is not None:
                clauses.append("t.source_id = :sid")
                params["sid"] = str(source_id)
            if workbook_id is not None:
                clauses.append("t.workbook_id = :wid")
                params["wid"] = str(workbook_id)
            if knowledge_base_id is not None:
                clauses.append(
                    "t.workbook_id IN (SELECT id FROM tabular_workbooks "
                    "WHERE organization_id = :oid AND knowledge_base_id = :kid)"
                )
                params["kid"] = str(knowledge_base_id)
            result = await session.execute(
                text(
                    "SELECT c.id, c.table_id, c.physical_index, c.physical_column, "  # noqa: S608 (valores parametrizados)
                    "c.excel_letter, c.original_name, c.normalized_name, c.aliases, "
                    "c.header_path, c.inferred_type, c.semantic_type, "
                    "c.type_confidence, c.semantic_confidence, c.nullable, "
                    "c.null_ratio, c.unique_ratio, c.sample_values, c.description, "
                    "c.description_origin, c.metadata, "
                    "t.name AS table_name, t.workbook_id, t.source_id, "
                    "s.name AS sheet_name "  # noqa: S608 (cláusulas estáticas; valores parametrizados)
                    "FROM tabular_columns c "
                    "JOIN tabular_tables t ON t.id = c.table_id "
                    "LEFT JOIN tabular_sheets s ON s.id = t.sheet_id "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY t.id, c.physical_index LIMIT 5000"
                ),
                params,
            )
            columns: list[dict] = []
            for row in result.fetchall():
                column = _column_to_dict(row)
                column["table_name"] = row.table_name
                column["workbook_id"] = str(row.workbook_id)
                column["source_id"] = str(row.source_id) if row.source_id else None
                column["sheet_name"] = row.sheet_name
                columns.append(column)
            return columns
        finally:
            await session.close()

    async def get_table(self, organization_id: UUID, table_id: UUID) -> dict | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_TABLE_COLUMNS_JOIN} "  # noqa: S608 (columnas estáticas; valores parametrizados)
                    "FROM tabular_tables t "
                    "LEFT JOIN tabular_sheets s ON s.id = t.sheet_id "
                    "WHERE t.organization_id = :oid AND t.id = :tid"
                ),
                {"oid": str(organization_id), "tid": str(table_id)},
            )
            row = result.fetchone()
            if row is None:
                return None
            table = _table_to_dict(row)
            columns = await session.execute(
                text(
                    "SELECT id, table_id, physical_index, physical_column, excel_letter, "
                    "original_name, normalized_name, aliases, header_path, inferred_type, "
                    "semantic_type, type_confidence, semantic_confidence, nullable, "
                    "null_ratio, unique_ratio, sample_values, description, "
                    "description_origin, metadata FROM tabular_columns "
                    "WHERE organization_id = :oid AND table_id = :tid "
                    "ORDER BY physical_index"
                ),
                {"oid": str(organization_id), "tid": str(table_id)},
            )
            table["columns"] = [_column_to_dict(column) for column in columns.fetchall()]
            return table
        finally:
            await session.close()

    async def fetch_rows(
        self,
        organization_id: UUID,
        table_id: UUID,
        *,
        filters: dict[str, str] | None = None,
        range_filters: list[tuple[str, str, str]] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where_sql, params = _build_where(
                organization_id,
                table_id,
                filters=filters,
                range_filters=range_filters,
            )
            bounded_limit = max(1, min(int(limit), 1000))
            result = await session.execute(
                text(
                    "SELECT physical_row, logical_index, values, cells, content_hash, "  # noqa: S608 (cláusulas estáticas; valores parametrizados)
                    "metadata FROM tabular_rows "
                    f"WHERE {where_sql} "
                    "ORDER BY physical_row LIMIT :limit OFFSET :offset"
                ),
                {**params, "limit": bounded_limit, "offset": max(0, int(offset))},
            )
            return [_row_to_dict(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def count_rows(
        self,
        organization_id: UUID,
        table_id: UUID,
        *,
        filters: dict[str, str] | None = None,
        range_filters: list[tuple[str, str, str]] | None = None,
    ) -> int:
        session = await get_async_session()
        try:
            where_sql, params = _build_where(
                organization_id,
                table_id,
                filters=filters,
                range_filters=range_filters,
            )
            result = await session.execute(
                text(
                    "SELECT COUNT(*) AS total FROM tabular_rows "  # noqa: S608 (cláusulas estáticas; valores parametrizados)
                    f"WHERE {where_sql}"
                ),
                params,
            )
            row = result.fetchone()
            return int(row.total or 0) if row is not None else 0
        finally:
            await session.close()

    async def sample_values(
        self,
        organization_id: UUID,
        table_id: UUID,
        column_id: UUID,
        limit: int = 20,
    ) -> list[str]:
        session = await get_async_session()
        try:
            column = await session.execute(
                text(
                    "SELECT normalized_name FROM tabular_columns "
                    "WHERE organization_id = :oid AND table_id = :tid AND id = :cid"
                ),
                {"oid": str(organization_id), "tid": str(table_id), "cid": str(column_id)},
            )
            column_row = column.fetchone()
            if column_row is None:
                return []
            result = await session.execute(
                text(
                    "SELECT DISTINCT values ->> :column FROM tabular_rows "
                    "WHERE organization_id = :oid AND table_id = :tid "
                    "AND values ->> :column IS NOT NULL "
                    "AND values ->> :column <> '' "
                    "ORDER BY 1 LIMIT :limit"
                ),
                {
                    "oid": str(organization_id),
                    "tid": str(table_id),
                    "column": column_row.normalized_name,
                    "limit": max(1, min(int(limit), 500)),
                },
            )
            return [row[0] for row in result.fetchall() if row[0] is not None]
        finally:
            await session.close()

    async def list_relations(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        workbook_id: UUID | None = None,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            clauses = ["r.organization_id = :oid"]
            params: dict = {"oid": str(organization_id)}
            if workbook_id is not None:
                clauses.append("r.workbook_id = :wid")
                params["wid"] = str(workbook_id)
            if source_id is not None:
                clauses.append(
                    "r.workbook_id IN (SELECT id FROM tabular_workbooks "
                    "WHERE organization_id = :oid AND source_id = :sid)"
                )
                params["sid"] = str(source_id)
            result = await session.execute(
                text(
                    "SELECT r.id, r.workbook_id, r.kind, r.confidence, "  # noqa: S608 (cláusulas estáticas; valores parametrizados)
                    "CAST(r.evidence AS jsonb) AS evidence, "
                    "ft.name AS from_table, tt.name AS to_table, "
                    "fc.original_name AS from_column, tc.original_name AS to_column "
                    "FROM tabular_relations r "
                    "LEFT JOIN tabular_tables ft ON ft.id = r.from_table_id "
                    "LEFT JOIN tabular_tables tt ON tt.id = r.to_table_id "
                    "LEFT JOIN tabular_columns fc ON fc.id = r.from_column_id "
                    "LEFT JOIN tabular_columns tc ON tc.id = r.to_column_id "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY r.confidence DESC LIMIT 500"
                ),
                params,
            )
            return [
                {
                    "id": str(row.id),
                    "workbook_id": str(row.workbook_id),
                    "kind": row.kind,
                    "confidence": row.confidence,
                    "evidence": row.evidence if isinstance(row.evidence, dict) else {},
                    "from_table": row.from_table,
                    "to_table": row.to_table,
                    "from_column": row.from_column,
                    "to_column": row.to_column,
                }
                for row in result.fetchall()
            ]
        finally:
            await session.close()

    async def delete_for_source(self, organization_id: UUID, source_id: UUID) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "DELETE FROM tabular_workbooks "
                    "WHERE organization_id = :oid AND source_id = :sid"
                ),
                {"oid": str(organization_id), "sid": str(source_id)},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def set_representations(
        self,
        organization_id: UUID,
        workbook_id: UUID,
        representations: dict,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE tabular_workbooks "
                    "SET metadata = jsonb_set(metadata, '{representations}', "
                    "CAST(:representations AS jsonb), true), updated_at = now() "
                    "WHERE organization_id = :oid AND id = :wid"
                ),
                {
                    "oid": str(organization_id),
                    "wid": str(workbook_id),
                    "representations": json.dumps(representations, default=str),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def set_runtime_metadata(
        self,
        organization_id: UUID,
        workbook_id: UUID,
        values: dict,
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE tabular_workbooks "
                    "SET metadata = metadata || CAST(:values AS jsonb), "
                    "updated_at = now() "
                    "WHERE organization_id = :oid AND id = :wid"
                ),
                {
                    "oid": str(organization_id),
                    "wid": str(workbook_id),
                    "values": json.dumps(values, default=str),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def delete_missing_workbooks(
        self,
        organization_id: UUID,
        source_id: UUID,
        keep_external_ids: set[str],
    ) -> int:
        session = await get_async_session()
        try:
            if keep_external_ids:
                result = await session.execute(
                    text(
                        "DELETE FROM tabular_workbooks "
                        "WHERE organization_id = :oid AND source_id = :sid "
                        "AND external_id <> ALL(:keep)"
                    ),
                    {
                        "oid": str(organization_id),
                        "sid": str(source_id),
                        "keep": sorted(str(e) for e in keep_external_ids),
                    },
                )
            else:
                result = await session.execute(
                    text(
                        "DELETE FROM tabular_workbooks "
                        "WHERE organization_id = :oid AND source_id = :sid"
                    ),
                    {"oid": str(organization_id), "sid": str(source_id)},
                )
            await session.commit()
            return int(result.rowcount or 0)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _upsert_workbook_row(
        self,
        session,
        workbook: TabularWorkbook,
        *,
        knowledge_base_id: UUID | None,
    ) -> None:
        profile = workbook.profile
        quality = workbook.quality
        await session.execute(
            text(
                """
                INSERT INTO tabular_workbooks (
                    id, organization_id, workspace_id, source_id, knowledge_base_id,
                    external_id, filename, format, content_hash, sheet_count,
                    table_count, row_count, cell_count, profile, quality, metadata,
                    created_at, updated_at
                ) VALUES (
                    :id, :organization_id, :workspace_id, :source_id, :knowledge_base_id,
                    :external_id, :filename, :format, :content_hash, :sheet_count,
                    :table_count, :row_count, :cell_count,
                    CAST(:profile AS jsonb), CAST(:quality AS jsonb), CAST(:metadata AS jsonb),
                    now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    workspace_id = EXCLUDED.workspace_id,
                    source_id = EXCLUDED.source_id,
                    knowledge_base_id = EXCLUDED.knowledge_base_id,
                    filename = EXCLUDED.filename,
                    format = EXCLUDED.format,
                    content_hash = EXCLUDED.content_hash,
                    sheet_count = EXCLUDED.sheet_count,
                    table_count = EXCLUDED.table_count,
                    row_count = EXCLUDED.row_count,
                    cell_count = EXCLUDED.cell_count,
                    profile = EXCLUDED.profile,
                    quality = EXCLUDED.quality,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """
            ),
            {
                "id": str(workbook.id),
                "organization_id": str(workbook.organization_id),
                "workspace_id": _uuid_or_none(workbook.workspace_id),
                "source_id": _uuid_or_none(workbook.source_id),
                "knowledge_base_id": _uuid_or_none(knowledge_base_id),
                "external_id": workbook.external_id,
                "filename": workbook.filename,
                "format": workbook.format.value,
                "content_hash": workbook.content_hash,
                "sheet_count": workbook.sheet_count,
                "table_count": workbook.table_count,
                "row_count": workbook.row_count,
                "cell_count": profile.non_empty_cells if profile else 0,
                "profile": json.dumps(
                    _profile_to_dict(profile), default=str
                ),
                "quality": json.dumps(_quality_to_dict(quality), default=str),
                "metadata": json.dumps(workbook.metadata, default=str),
            },
        )

    async def _upsert_sheet(self, session, workbook: TabularWorkbook, sheet) -> None:
        await session.execute(
            text(
                """
                INSERT INTO tabular_sheets (
                    id, workbook_id, organization_id, sheet_index, name, hidden,
                    state, dimensions, non_empty_cells, merged_ranges, context,
                    metadata, created_at, updated_at
                ) VALUES (
                    :id, :workbook_id, :organization_id, :sheet_index, :name, :hidden,
                    :state, CAST(:dimensions AS jsonb), :non_empty_cells,
                    :merged_ranges, CAST(:context AS jsonb), CAST(:metadata AS jsonb),
                    now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    sheet_index = EXCLUDED.sheet_index,
                    name = EXCLUDED.name,
                    hidden = EXCLUDED.hidden,
                    state = EXCLUDED.state,
                    dimensions = EXCLUDED.dimensions,
                    non_empty_cells = EXCLUDED.non_empty_cells,
                    merged_ranges = EXCLUDED.merged_ranges,
                    context = EXCLUDED.context,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """
            ),
            {
                "id": str(sheet.id),
                "workbook_id": str(workbook.id),
                "organization_id": str(workbook.organization_id),
                "sheet_index": sheet.index,
                "name": sheet.name,
                "hidden": bool(sheet.hidden),
                "state": sheet.state,
                "dimensions": json.dumps(
                    sheet.dimensions.to_dict() if sheet.dimensions else None
                ),
                "non_empty_cells": sheet.non_empty_cells,
                "merged_ranges": len(sheet.merged_ranges),
                "context": json.dumps(
                    [_context_to_dict(block) for block in sheet.context_blocks],
                    default=str,
                ),
                "metadata": json.dumps(sheet.metadata, default=str),
            },
        )

    async def _upsert_table(
        self,
        session,
        workbook: TabularWorkbook,
        sheet,
        table: TabularTable,
        table_diff: TableDiff | None,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO tabular_tables (
                    id, workbook_id, sheet_id, organization_id, source_id, name,
                    title, table_range, header_rows, header_depth, detection_method,
                    detection_confidence, header_confidence, schema_hash,
                    content_hash, column_count, row_count, context, metadata,
                    created_at, updated_at
                ) VALUES (
                    :id, :workbook_id, :sheet_id, :organization_id, :source_id, :name,
                    :title, CAST(:table_range AS jsonb), CAST(:header_rows AS jsonb),
                    :header_depth, :detection_method, :detection_confidence,
                    :header_confidence, :schema_hash, :content_hash, :column_count,
                    :row_count, CAST(:context AS jsonb), CAST(:metadata AS jsonb),
                    now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    sheet_id = EXCLUDED.sheet_id,
                    name = EXCLUDED.name,
                    title = EXCLUDED.title,
                    table_range = EXCLUDED.table_range,
                    header_rows = EXCLUDED.header_rows,
                    header_depth = EXCLUDED.header_depth,
                    detection_method = EXCLUDED.detection_method,
                    detection_confidence = EXCLUDED.detection_confidence,
                    header_confidence = EXCLUDED.header_confidence,
                    schema_hash = EXCLUDED.schema_hash,
                    content_hash = EXCLUDED.content_hash,
                    column_count = EXCLUDED.column_count,
                    row_count = EXCLUDED.row_count,
                    context = EXCLUDED.context,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """
            ),
            {
                "id": str(table.id),
                "workbook_id": str(workbook.id),
                "sheet_id": str(sheet.id),
                "organization_id": str(workbook.organization_id),
                "source_id": _uuid_or_none(workbook.source_id),
                "name": table.name,
                "title": table.title,
                "table_range": json.dumps(table.range.to_dict()),
                "header_rows": json.dumps(list(table.header_rows)),
                "header_depth": table.header_depth,
                "detection_method": table.detection_method.value,
                "detection_confidence": table.detection_confidence,
                "header_confidence": table.header_confidence,
                "schema_hash": table.schema_hash,
                "content_hash": table.content_hash,
                "column_count": table.column_count,
                "row_count": table.row_count,
                "context": json.dumps(
                    [_context_to_dict(block) for block in table.context_blocks],
                    default=str,
                ),
                "metadata": json.dumps(table.metadata, default=str),
            },
        )

        if table_diff is not None and not table_diff.changed:
            return
        await self._upsert_columns(session, workbook, table)
        if table_diff is not None:
            await self._upsert_rows(session, workbook, table, table_diff)
        else:  # pragma: no cover - defensivo: sin diff se escribe todo
            await self._upsert_rows(session, workbook, table, _full_write_diff(table))

    async def _upsert_columns(self, session, workbook: TabularWorkbook, table: TabularTable) -> None:
        if not table.columns:
            return
        rows = [
            {
                "id": str(column.id),
                "table_id": str(table.id),
                "organization_id": str(workbook.organization_id),
                "physical_index": column.physical_index,
                "physical_column": column.physical_column,
                "excel_letter": column.excel_letter,
                "original_name": column.original_name,
                "normalized_name": column.normalized_name,
                "aliases": json.dumps(list(column.aliases), default=str),
                "header_path": json.dumps(list(column.header_path), default=str),
                "inferred_type": column.inferred_type.value,
                "semantic_type": column.semantic_type.value,
                "type_confidence": column.type_confidence,
                "semantic_confidence": column.semantic_confidence,
                "nullable": bool(column.nullable),
                "null_ratio": column.null_ratio,
                "unique_ratio": column.unique_ratio,
                "sample_values": json.dumps(list(column.sample_values), default=str),
                "description": column.description,
                "description_origin": column.description_origin.value,
                "metadata": json.dumps(column.metadata, default=str),
            }
            for column in table.columns
        ]
        await session.execute(
            text(
                """
                INSERT INTO tabular_columns (
                    id, table_id, organization_id, physical_index, physical_column,
                    excel_letter, original_name, normalized_name, aliases, header_path,
                    inferred_type, semantic_type, type_confidence, semantic_confidence,
                    nullable, null_ratio, unique_ratio, sample_values, description,
                    description_origin, metadata, created_at, updated_at
                ) VALUES (
                    :id, :table_id, :organization_id, :physical_index, :physical_column,
                    :excel_letter, :original_name, :normalized_name,
                    CAST(:aliases AS jsonb), CAST(:header_path AS jsonb),
                    :inferred_type, :semantic_type, :type_confidence,
                    :semantic_confidence, :nullable, :null_ratio, :unique_ratio,
                    CAST(:sample_values AS jsonb), :description, :description_origin,
                    CAST(:metadata AS jsonb), now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    physical_index = EXCLUDED.physical_index,
                    physical_column = EXCLUDED.physical_column,
                    excel_letter = EXCLUDED.excel_letter,
                    original_name = EXCLUDED.original_name,
                    normalized_name = EXCLUDED.normalized_name,
                    aliases = EXCLUDED.aliases,
                    header_path = EXCLUDED.header_path,
                    inferred_type = EXCLUDED.inferred_type,
                    semantic_type = EXCLUDED.semantic_type,
                    type_confidence = EXCLUDED.type_confidence,
                    semantic_confidence = EXCLUDED.semantic_confidence,
                    nullable = EXCLUDED.nullable,
                    null_ratio = EXCLUDED.null_ratio,
                    unique_ratio = EXCLUDED.unique_ratio,
                    sample_values = EXCLUDED.sample_values,
                    description = EXCLUDED.description,
                    description_origin = EXCLUDED.description_origin,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """
            ),
            rows,
        )

    async def _upsert_rows(
        self,
        session,
        workbook: TabularWorkbook,
        table: TabularTable,
        table_diff: TableDiff,
    ) -> None:
        if table.rows:
            rows = [
                {
                    "table_id": str(table.id),
                    "organization_id": str(workbook.organization_id),
                    "physical_row": row.physical_row,
                    "logical_index": row.logical_index,
                    "values": json.dumps(row.mapping(table.columns), default=str),
                    "cells": json.dumps(
                        [_cell_to_dict(cell) for cell in row.cell_details],
                        default=str,
                    ),
                    "content_hash": row.content_hash,
                    "metadata": json.dumps(row.metadata, default=str),
                }
                for row in table.rows
            ]
            for start in range(0, len(rows), _ROW_BATCH):
                await session.execute(
                    text(
                        """
                        INSERT INTO tabular_rows (
                            table_id, organization_id, physical_row,
                            logical_index, values, cells, content_hash, metadata,
                            created_at, updated_at
                        ) VALUES (
                            :table_id, :organization_id, :physical_row,
                            :logical_index, CAST(:values AS jsonb),
                            CAST(:cells AS jsonb), :content_hash,
                            CAST(:metadata AS jsonb), now(), now()
                        )
                        ON CONFLICT (table_id, physical_row) DO UPDATE SET
                            logical_index = EXCLUDED.logical_index,
                            values = EXCLUDED.values,
                            cells = EXCLUDED.cells,
                            content_hash = EXCLUDED.content_hash,
                            metadata = EXCLUDED.metadata,
                            updated_at = now()
                        """
                    ),
                    rows[start : start + _ROW_BATCH],
                )
            if table_diff.deleted_rows:
                await session.execute(
                    text(
                        "DELETE FROM tabular_rows "
                        "WHERE organization_id = :oid AND table_id = :tid "
                        "AND physical_row = ANY(:rows)"
                    ),
                    {
                        "oid": str(workbook.organization_id),
                        "tid": str(table.id),
                        "rows": [int(value) for value in table_diff.deleted_rows],
                    },
                )

    async def _upsert_relations(self, session, workbook: TabularWorkbook) -> None:
        await session.execute(
            text(
                "DELETE FROM tabular_relations "
                "WHERE organization_id = :oid AND workbook_id = :wid"
            ),
            {"oid": str(workbook.organization_id), "wid": str(workbook.id)},
        )
        if not workbook.relations:
            return
        rows = [
            {
                "id": str(relation.id),
                "workbook_id": str(workbook.id),
                "organization_id": str(workbook.organization_id),
                "from_table_id": str(relation.from_table_id),
                "from_column_id": str(relation.from_column_id),
                "to_table_id": str(relation.to_table_id),
                "to_column_id": str(relation.to_column_id),
                "kind": relation.kind.value,
                "confidence": relation.confidence,
                "evidence": json.dumps(relation.evidence, default=str),
            }
            for relation in workbook.relations
        ]
        await session.execute(
            text(
                """
                INSERT INTO tabular_relations (
                    id, workbook_id, organization_id, from_table_id, from_column_id,
                    to_table_id, to_column_id, kind, confidence, evidence, created_at
                ) VALUES (
                    :id, :workbook_id, :organization_id, :from_table_id,
                    :from_column_id, :to_table_id, :to_column_id, :kind,
                    :confidence, CAST(:evidence AS jsonb), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    confidence = EXCLUDED.confidence,
                    evidence = EXCLUDED.evidence
                """
            ),
            rows,
        )

    async def _delete_missing_sheets(
        self, session, workbook: TabularWorkbook
    ) -> None:
        sheet_ids = [str(sheet.id) for sheet in workbook.sheets]
        if not sheet_ids:
            return
        await session.execute(
            text(
                "DELETE FROM tabular_sheets WHERE organization_id = :oid "
                "AND workbook_id = :wid AND id <> ALL(:ids)"
            ),
            {
                "oid": str(workbook.organization_id),
                "wid": str(workbook.id),
                "ids": sheet_ids,
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_write_diff(table: TabularTable) -> TableDiff:
    return TableDiff(table_id=table.id, inserted=table.row_count)


def _uuid_or_none(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _build_where(
    organization_id: UUID,
    table_id: UUID,
    *,
    filters: dict[str, str] | None = None,
    range_filters: list[tuple[str, str, str]] | None = None,
) -> tuple[str, dict]:
    """Construye WHERE (scoped) para filas tabulares.

    - Igualdad: `values @> {col: val}` (usa el índice GIN).
    - Rango numérico: guard de formato numérico + CAST a numeric con operador
      en whitelist (el operador nunca viene de input libre sin validar).
    """
    where = ["organization_id = :oid", "table_id = :tid"]
    params: dict = {"oid": str(organization_id), "tid": str(table_id)}
    for index, (column, value) in enumerate((filters or {}).items()):
        key = f"filter_{index}"
        where.append(f"values @> CAST(:{key} AS jsonb)")
        params[key] = json.dumps({str(column): str(value)})
    for index, (column, operator, value) in enumerate(range_filters or []):
        if operator not in _RANGE_OPERATORS:
            raise ValueError(f"unsupported range operator: {operator!r}")
        key = f"range_{index}"
        where.append(_NUMERIC_GUARD.format(key=key))
        where.append(f"(values ->> :{key})::numeric {operator} :{key}_value")
        params[key] = str(column)
        params[f"{key}_value"] = str(value)
    return " AND ".join(where), params


def _profile_to_dict(profile) -> dict:
    if profile is None:
        return {}
    return {
        "filename": profile.filename,
        "format": profile.format.value,
        "sheet_count": profile.sheet_count,
        "sheet_names": list(profile.sheet_names),
        "non_empty_cells": profile.non_empty_cells,
        "merged_cells": profile.merged_cells,
        "formulas": profile.formulas,
        "hidden_rows": profile.hidden_rows,
        "hidden_columns": profile.hidden_columns,
        "candidate_tables": profile.candidate_tables,
        "truncated": profile.truncated,
        "limits_hit": list(profile.limits_hit),
        "sheets": [
            {
                "name": sheet.name,
                "index": sheet.index,
                "row_count": sheet.row_count,
                "column_count": sheet.column_count,
                "non_empty_cells": sheet.non_empty_cells,
                "merged_ranges": sheet.merged_ranges,
                "formulas": sheet.formulas,
                "hidden_rows": sheet.hidden_rows,
                "hidden_columns": sheet.hidden_columns,
                "candidate_header_rows": list(sheet.candidate_header_rows),
                "candidate_tables": sheet.candidate_tables,
                "detected_tables": sheet.detected_tables,
                "hidden": sheet.hidden,
            }
            for sheet in profile.sheets
        ],
        "metadata": profile.metadata,
    }


def _quality_to_dict(quality) -> dict:
    if quality is None:
        return {}
    return {
        "quality_score": quality.quality_score,
        "warnings": [
            {
                "code": warning.code,
                "message": warning.message,
                "severity": warning.severity.value,
                "sheet_name": warning.sheet_name,
                "table_id": str(warning.table_id) if warning.table_id else None,
                "physical_row": warning.physical_row,
                "column_name": warning.column_name,
            }
            for warning in quality.warnings
        ],
        "metrics": quality.metrics,
    }


def _context_to_dict(block) -> dict:
    return {
        "text": block.text,
        "kind": block.kind.value,
        "physical_row": block.physical_row,
        "physical_column": block.physical_column,
        "confidence": block.confidence,
    }


def _cell_to_dict(cell) -> dict:
    return {
        "row": cell.physical_row,
        "col": cell.physical_column,
        "address": cell.address,
        "raw": cell.raw_value,
        "type": cell.inferred_type.value,
        "formula": cell.formula,
        "cached": cell.formula_cached_value,
        "merged": cell.is_merged,
        "merged_range": cell.merged_range.to_dict() if cell.merged_range else None,
    }


def _workbook_to_dict(row) -> dict:
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "source_id": str(row.source_id) if row.source_id else None,
        "knowledge_base_id": str(row.knowledge_base_id) if row.knowledge_base_id else None,
        "external_id": row.external_id,
        "filename": row.filename,
        "format": row.format,
        "content_hash": row.content_hash,
        "sheet_count": row.sheet_count,
        "table_count": row.table_count,
        "row_count": row.row_count,
        "cell_count": row.cell_count,
        "profile": row.profile if isinstance(row.profile, dict) else {},
        "quality": row.quality if isinstance(row.quality, dict) else {},
        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _table_to_dict(row) -> dict:
    return {
        "id": str(row.id),
        "workbook_id": str(row.workbook_id),
        "sheet_id": str(row.sheet_id),
        "sheet": getattr(row, "sheet_name", None),
        "organization_id": str(row.organization_id),
        "source_id": str(row.source_id) if row.source_id else None,
        "name": row.name,
        "title": row.title,
        "range": row.table_range,
        "header_rows": row.header_rows,
        "header_depth": row.header_depth,
        "detection_method": row.detection_method,
        "detection_confidence": row.detection_confidence,
        "header_confidence": row.header_confidence,
        "schema_hash": row.schema_hash,
        "content_hash": row.content_hash,
        "column_count": row.column_count,
        "row_count": row.row_count,
        "context": row.context,
        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
        "updated_at": row.updated_at,
    }


def _column_to_dict(row) -> dict:
    return {
        "id": str(row.id),
        "table_id": str(row.table_id),
        "physical_index": row.physical_index,
        "physical_column": row.physical_column,
        "excel_letter": row.excel_letter,
        "original_name": row.original_name,
        "normalized_name": row.normalized_name,
        "aliases": row.aliases,
        "header_path": row.header_path,
        "inferred_type": row.inferred_type,
        "semantic_type": row.semantic_type,
        "type_confidence": row.type_confidence,
        "semantic_confidence": row.semantic_confidence,
        "nullable": row.nullable,
        "null_ratio": row.null_ratio,
        "unique_ratio": row.unique_ratio,
        "sample_values": row.sample_values,
        "description": row.description,
        "description_origin": row.description_origin,
        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
    }


def _row_to_dict(row) -> dict:
    return {
        "physical_row": row.physical_row,
        "logical_index": row.logical_index,
        "values": row.values if isinstance(row.values, dict) else {},
        "cells": row.cells if isinstance(row.cells, list) else [],
        "content_hash": row.content_hash,
        "metadata": row.metadata if isinstance(row.metadata, dict) else {},
    }
