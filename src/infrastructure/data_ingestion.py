# =============================================================================
# Data Ingestion Engine — Database → Vector Store (Modular, Domain-Agnostic)
# =============================================================================
# Descubre automáticamente todas las tablas de PostgreSQL, serializa cada fila
# en texto enriquecido usando heurísticas de columnas, genera embeddings y
# los indexa en Qdrant con payload completo para filtrado semántico.
#
# Principio: Cero configuración manual. Funciona para retail, farmacia,
# cafetería o cualquier dominio — el discovery de esquema es automático.
# =============================================================================
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports import CacheProvider, EmbeddingProvider, VectorStore
from src.domain.services import ColumnMeta, DataSource, IngestionResult, IngestionService
from src.infrastructure.logging_config import get_logger
from src.infrastructure.relational_db import get_async_session

logger = get_logger(__name__)

# Namespace fijo para UUID v5 — garantiza unicidad entre tablas
_VECTOR_NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# -----------------------------------------------------------------------------
# Tablas del sistema que NUNCA se indexan (metadatos de la plataforma)
# -----------------------------------------------------------------------------
SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}
SYSTEM_TABLES = {
    "tenants", "users", "rate_limit_counters", "usage_logs",
    "query_audit_log", "documents", "alembic_version",
}

# -----------------------------------------------------------------------------
# Heurísticas de serialización: patrón de columna → template de texto
# Cada fila se convierte en una oración en lenguaje natural.
# -----------------------------------------------------------------------------
COLUMN_HEURISTICS: list[tuple[str, str, int]] = [
    # (regex_pattern, label_es, priority) — menor prioridad = más relevante
    # Patrones específicos deben ir ANTES de los genéricos
    (r"\btotal_sales\b", "número de ventas", 3),
    (r"\btotal_revenue\b", "ingresos totales", 3),
    (r"\btotal_units\b", "unidades vendidas", 3),
    (r"\blast_sale_date\b", "última venta", 11),
    (r"\bfirst_sale_date\b", "primera venta", 11),
    (r"\bis_in_stock\b", "en stock", 10),
    (r"\breview_count\b", "total de reseñas", 9),
    (r"\bcategory_name\b", "categoría", 7),
    (r"\bparent_category_name\b", "categoría principal", 7),
    (r"\bname\b", "nombre", 1),
    (r"\btitle\b", "título", 1),
    (r"\bproduct_name\b", "producto", 1),
    (r"\bfull_name\b", "nombre completo", 1),
    (r"\bdescription\b", "descripción", 2),
    (r"\bsummary\b", "resumen", 2),
    (r"\bdetails\b", "detalles", 2),
    (r"\bprice\b", "precio", 3),
    (r"\bcost\b", "costo", 3),
    (r"\bunit_price\b", "precio unitario", 3),
    (r"\bsale_price\b", "precio de venta", 3),
    (r"\bamount\b", "monto", 3),
    (r"\btotal\b", "total", 3),
    (r"\brevenue\b", "ingresos", 3),
    (r"\bquantity\b", "cantidad", 4),
    (r"\bstock\b", "stock", 4),
    (r"\binventory\b", "inventario", 4),
    (r"\bavailable\b", "disponible", 4),
    (r"\bsku\b", "SKU", 5),
    (r"\bcode\b", "código", 5),
    (r"\bbarcode\b", "código de barras", 5),
    (r"\bbrand\b", "marca", 6),
    (r"\bmanufacturer\b", "fabricante", 6),
    (r"\bsupplier\b", "proveedor", 6),
    (r"\bcategory\b", "categoría", 7),
    (r"\bdepartment\b", "departamento", 7),
    (r"\bsection\b", "sección", 7),
    (r"\btype\b", "tipo", 7),
    (r"\btags\b", "etiquetas", 8),
    (r"\bkeywords\b", "palabras clave", 8),
    (r"\brating\b", "calificación", 9),
    (r"\bscore\b", "puntuación", 9),
    (r"\breview\b", "reseña", 9),
    (r"\bstatus\b", "estado", 10),
    (r"\bactive\b", "activo", 10),
    (r"\bcreated_at\b", "fecha de creación", 11),
    (r"\bupdated_at\b", "fecha de actualización", 11),
    (r"\bdate\b", "fecha", 11),
    (r"\bdelivery_time\b", "tiempo de entrega", 12),
    (r"\bshipping\b", "envío", 12),
    (r"\bdelivery\b", "entrega", 12),
    (r"\bweight\b", "peso", 13),
    (r"\bdimensions\b", "dimensiones", 13),
    (r"\bsize\b", "tamaño", 13),
    (r"\bcolor\b", "color", 13),
    (r"\bemail\b", "", 99),  # Skip — PCI/PII, no indexar
    (r"\bphone\b", "", 99),  # Skip — PCI/PII
    (r"\bpassword\b", "", 99),  # Skip — secreto
    (r"\bhash\b", "", 99),  # Skip — irrelevante para búsqueda
    (r"\bid$", "", 0),  # ID primario — se usa como key, no en texto
    (r"_id$", "", 0),  # FK — se usa como metadata, no en texto
]


@dataclass
class _ColumnTemplate:
    """Resultado del mapeo heurístico de una columna a una etiqueta legible."""

    column: str
    label: str | None  # None = skip (PII o FK)
    priority: int
    is_monetary: bool = False

    @property
    def is_skipped(self) -> bool:
        return self.label is None or self.label == ""


def _column_to_template(col_name: str, col_type: str) -> _ColumnTemplate:
    """Mapea una columna de BD a una etiqueta de texto usando heurísticas."""
    col_lower = col_name.lower().strip()

    for pattern, label, priority in COLUMN_HEURISTICS:
        if re.search(pattern, col_lower, re.IGNORECASE):
            is_monetary = any(
                kw in col_type.lower()
                for kw in ("money", "decimal", "numeric", "float", "double")
            )
            if priority >= 99:
                return _ColumnTemplate(col_name, None, priority)
            return _ColumnTemplate(col_name, label, priority, is_monetary)

    # Columna desconocida → incluir con nombre original
    return _ColumnTemplate(col_name, col_lower.replace("_", " "), 50)


def _serialize_row(
    row: dict,
    column_templates: list[_ColumnTemplate],
    table_label: str,
    fk_resolutions: dict[str, tuple[str, dict[str, str]]] | None = None,
    is_view: bool = False,
) -> str:
    """Convierte una fila SQL en texto en lenguaje natural para embedding.

    Genera oraciones como:
    "Producto: Smartphone XYZ. Precio: $599.990. Categoría: Electrónica.
     Stock: 45 unidades. Descripción: Smartphone de última generación..."
    """
    parts: list[str] = []
    monetary_parts: list[str] = []

    for ct in sorted(column_templates, key=lambda x: x.priority):
        if ct.is_skipped:
            continue
        raw_value = row.get(ct.column)
        if raw_value is None:
            continue

        value_str = str(raw_value).strip()
        if not value_str or value_str.lower() in ("none", "null", ""):
            continue

        # Truncar textos largos
        if len(value_str) > 500:
            value_str = value_str[:497] + "..."

        label = ct.label or ct.column

        if ct.is_monetary and value_str.replace(".", "").replace("-", "").isdigit():
            try:
                value_str = f"${float(value_str):,.2f}"
            except ValueError:
                pass

        if ct.priority <= 2:
            # Nombre/título: prefijo principal
            parts.insert(0, f"{label.capitalize()}: {value_str}")
            parts.insert(1, f"[Tabla: {table_label}]")
        elif ct.is_monetary:
            monetary_parts.append(f"{label.capitalize()}: {value_str}")
        else:
            parts.append(f"{label.capitalize()}: {value_str}")

    # FK resolution: inject resolved display names for foreign key columns
    if fk_resolutions:
        for fk_col, (label, mapping) in sorted(fk_resolutions.items()):
            fk_value = str(row.get(fk_col, ""))
            if fk_value in mapping:
                parts.insert(0, f"{label}: {mapping[fk_value]}")

    parts.extend(monetary_parts)
    if is_view:
        parts.insert(0, "[Datos agregados]")
    return ". ".join(parts) + "."


# =============================================================================
# Ingestion Engine Implementation
# =============================================================================
class PostgresIngestionService(IngestionService):
    """Implementación del servicio de ingesta usando PostgreSQL + Qdrant.

    El discovery de esquema es automático: consulta information_schema para
    descubrir tablas, columnas, tipos y foreign keys. No requiere mapeo
    manual de ningún tipo.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        cache_provider: CacheProvider | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._embeddings = embedding_provider
        self._cache = cache_provider

    def _sync_key(self, tenant_id: UUID, schema: str, table: str) -> str:
        return f"rag:synced:{tenant_id.hex}:{schema}.{table}"

    async def is_synced(self, tenant_id: UUID, schema: str, table: str) -> bool:
        if not self._cache:
            return False
        return await self._cache.exists(self._sync_key(tenant_id, schema, table))

    async def get_sync_statuses(self, tenant_id: UUID, sources: list[DataSource]) -> list[dict]:
        results = []
        for s in sources:
            synced = await self.is_synced(tenant_id, s.schema_name, s.table_name)
            results.append({**s.__dict__, "synced": synced})
        return results

    async def discover_sources(self, tenant_id: UUID) -> list[DataSource]:
        """Descubre todas las tablas indexables para un tenant."""
        session: AsyncSession = await get_async_session()
        try:
            rows = await session.execute(
                text(
                    "SELECT table_schema, table_name, table_type "
                    "FROM information_schema.tables "
                    "WHERE table_type IN ('BASE TABLE', 'VIEW') "
                    "AND table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast') "
                    "AND table_name NOT IN ("
                    "  'tenants', 'users', 'rate_limit_counters', 'usage_logs', "
                    "  'query_audit_log', 'documents', 'alembic_version'"
                    ") "
                    "ORDER BY table_schema, table_name"
                )
            )
            tables = rows.fetchall()

            sources: list[DataSource] = []
            for schema_name, table_name, table_type in tables:
                columns = await self._discover_columns(session, schema_name, table_name)
                count_result = await session.execute(
                    text(f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"')
                )
                row_count = count_result.scalar() or 0
                sources.append(DataSource(
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                    row_count=row_count,
                    is_view=(table_type == "VIEW"),
                ))

            return sources
        finally:
            await session.close()

    async def _discover_columns(
        self, session: AsyncSession, schema: str, table: str
    ) -> list[ColumnMeta]:
        """Descubre columnas, tipos, PKs y FKs de una tabla."""
        rows = await session.execute(
            text(
                "SELECT "
                "  c.column_name, c.data_type, c.is_nullable, "
                "  CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_pk, "
                "  CASE WHEN fk.column_name IS NOT NULL THEN true ELSE false END AS is_fk, "
                "  fk.foreign_table_name AS fk_table, "
                "  fk.foreign_column_name AS fk_column "
                "FROM information_schema.columns c "
                "LEFT JOIN ("
                "  SELECT ku.table_schema, ku.table_name, ku.column_name "
                "  FROM information_schema.table_constraints tc "
                "  JOIN information_schema.key_column_usage ku "
                "    ON tc.constraint_name = ku.constraint_name "
                "  WHERE tc.constraint_type = 'PRIMARY KEY'"
                ") pk ON c.table_schema = pk.table_schema "
                "     AND c.table_name = pk.table_name "
                "     AND c.column_name = pk.column_name "
                "LEFT JOIN ("
                "  SELECT kcu.table_schema, kcu.table_name, kcu.column_name, "
                "    ccu.table_name AS foreign_table_name, "
                "    ccu.column_name AS foreign_column_name "
                "  FROM information_schema.table_constraints tc "
                "  JOIN information_schema.key_column_usage kcu "
                "    ON tc.constraint_name = kcu.constraint_name "
                "  JOIN information_schema.constraint_column_usage ccu "
                "    ON tc.constraint_name = ccu.constraint_name "
                "  WHERE tc.constraint_type = 'FOREIGN KEY'"
                ") fk ON c.table_schema = fk.table_schema "
                "     AND c.table_name = fk.table_name "
                "     AND c.column_name = fk.column_name "
                "WHERE c.table_schema = :schema AND c.table_name = :table "
                "ORDER BY c.ordinal_position"
            ),
            {"schema": schema, "table": table},
        )
        return [
            ColumnMeta(
                name=row.column_name,
                data_type=str(row.data_type),
                is_nullable=row.is_nullable == "YES",
                is_primary_key=row.is_pk,
                is_foreign_key=row.is_fk,
                fk_table=row.fk_table,
                fk_column=row.fk_column,
            )
            for row in rows.fetchall()
        ]

    async def sync_all(
        self, tenant_id: UUID, full_refresh: bool = False, job_id: str | None = None
    ) -> IngestionResult:
        """Sincroniza todas las tablas automáticamente."""
        start = time.perf_counter()
        sources = await self.discover_sources(tenant_id)
        active_sources = [s for s in sources if s.row_count > 0]
        total_tables = len(active_sources)

        result = IngestionResult(
            tenant_id=tenant_id,
            tables_processed=0,
            rows_indexed=0,
            vectors_upserted=0,
        )

        if full_refresh:
            await self._vector_store.delete_by_tenant(tenant_id)

        for i, source in enumerate(active_sources):
            table_result = await self._ingest_table(tenant_id, source)
            result.tables_processed += 1
            result.rows_indexed += table_result.rows_indexed
            result.vectors_upserted += table_result.vectors_upserted
            result.errors.extend(table_result.errors)

            if job_id and total_tables > 0:
                from src.infrastructure.ingestion_queue import update_job_status
                percent = min(int((i + 1) / total_tables * 100), 100)
                await update_job_status(job_id, "running", progress=percent)

        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "Ingestion sync completed",
            tenant_id=str(tenant_id),
            tables=result.tables_processed,
            rows=result.rows_indexed,
            vectors=result.vectors_upserted,
            duration_ms=result.duration_ms,
            errors=len(result.errors),
        )

        return result

    def _sync_ts_key(self, tenant_id: UUID, schema_name: str, table_name: str) -> str:
        return f"rag:sync_ts:{tenant_id.hex}:{schema_name}.{table_name}"

    async def sync_table(
        self, tenant_id: UUID, schema_name: str, table_name: str, full_refresh: bool = False
    ) -> IngestionResult:
        """Sincroniza una tabla específica."""
        start = time.perf_counter()
        session = await get_async_session()
        try:
            columns = await self._discover_columns(session, schema_name, table_name)
            count_result = await session.execute(
                text(f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"')
            )
            row_count = count_result.scalar() or 0
        finally:
            await session.close()

        source = DataSource(
            schema_name=schema_name,
            table_name=table_name,
            columns=columns,
            row_count=row_count,
        )

        sync_ts_key = self._sync_ts_key(tenant_id, schema_name, table_name)
        has_updated_at = any(c.name == "updated_at" for c in columns)
        since_ts: str | None = None

        if full_refresh:
            await self._vector_store.delete_by_tenant(tenant_id)
            if self._cache:
                await self._cache.delete(sync_ts_key)
            logger.info(
                "Full sync (full_refresh=True)",
                table=f"{schema_name}.{table_name}",
            )
        elif has_updated_at and self._cache:
            since_ts = await self._cache.get(sync_ts_key)
            if since_ts:
                logger.info(
                    "Incremental sync",
                    table=f"{schema_name}.{table_name}",
                    since=since_ts,
                )
            else:
                logger.info(
                    "Full sync (no previous sync timestamp)",
                    table=f"{schema_name}.{table_name}",
                )
        else:
            if not has_updated_at:
                logger.info(
                    "Full sync (no updated_at column)",
                    table=f"{schema_name}.{table_name}",
                )

        result = IngestionResult(
            tenant_id=tenant_id,
            tables_processed=1,
            rows_indexed=0,
            vectors_upserted=0,
        )

        table_result = await self._ingest_table(
            tenant_id, source, since_timestamp=since_ts
        )
        result.rows_indexed = table_result.rows_indexed
        result.vectors_upserted = table_result.vectors_upserted
        result.errors = table_result.errors
        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)

        if has_updated_at and self._cache:
            from datetime import datetime, timezone

            await self._cache.set(
                sync_ts_key,
                datetime.now(timezone.utc).isoformat(),
                ttl_seconds=86400 * 30,
            )

        return result

    async def _resolve_fk_values(
        self,
        session: AsyncSession,
        schema_name: str,
        fk_table: str,
        fk_column: str,
    ) -> dict[str, str] | None:
        """Resuelve valores de FK (UUIDs) a nombres legibles.

        Consulta la tabla referenciada, detecta la mejor columna de
        display (name, title, etc.) y devuelve un mapeo PK→display_name.
        """
        cols_result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"schema": schema_name, "table": fk_table},
        )
        ref_columns = [row[0] for row in cols_result.fetchall()]

        display_col: str | None = None
        for pattern in [
            r"\bname\b", r"\btitle\b", r"\bproduct_name\b",
            r"\bfull_name\b", r"\blabel\b", r"\bdescription\b",
        ]:
            for col_name in ref_columns:
                if re.search(pattern, col_name, re.IGNORECASE):
                    display_col = col_name
                    break
            if display_col:
                break

        if not display_col:
            return None

        fk_rows = await session.execute(
            text(
                f'SELECT "{fk_column}", "{display_col}" '
                f'FROM "{schema_name}"."{fk_table}"'
            )
        )
        mapping: dict[str, str] = {}
        for row in fk_rows.fetchall():
            key = str(row[0]) if row[0] is not None else ""
            val = str(row[1]) if row[1] is not None else ""
            if key and val:
                mapping[key] = val

        return mapping if mapping else None

    async def _ingest_table(
        self, tenant_id: UUID, source: DataSource, since_timestamp: str | None = None
    ) -> IngestionResult:
        """Ingiere todas las filas de una tabla a Qdrant."""
        result = IngestionResult(tenant_id=tenant_id, tables_processed=1)

        # Mapeo heurístico de columnas
        column_templates = [
            _column_to_template(col.name, col.data_type)
            for col in source.columns
            if not col.is_primary_key  # PKs no van en el texto (son metadata)
        ]

        table_label = source.table_name.replace("_", " ").title()

        session = await get_async_session()
        try:
            schema = source.schema_name
            table = source.table_name

            # Descubrir columna PK para usarla como document_id
            pk_col = next(
                (col for col in source.columns if col.is_primary_key),
                source.columns[0] if source.columns else None,
            )
            if pk_col is None:
                result.errors.append(f"Table {schema}.{table} has no columns")
                return result

            # FK resolution: resolve foreign key UUIDs to display names
            fk_resolutions: dict[str, tuple[str, dict[str, str]]] = {}
            for col in source.columns:
                if col.is_foreign_key and col.fk_table and col.fk_column:
                    resolved = await self._resolve_fk_values(
                        session, schema, col.fk_table, col.fk_column
                    )
                    if resolved:
                        label = col.fk_table.replace("_", " ").title()
                        fk_resolutions[col.name] = (label, resolved)

            # Paginated fetch: load rows in pages of 500 to avoid OOM
            page_size = 500
            embed_batch_size = 50
            offset = 0
            column_names: list[str] | None = None
            page = 0

            while True:
                if since_timestamp:
                    query = text(
                        f'SELECT * FROM "{schema}"."{table}" '
                        f'WHERE "updated_at" > :since_ts '
                        f'ORDER BY "{pk_col.name}" '
                        f"LIMIT {page_size} OFFSET {offset}"
                    )
                    rows = await session.execute(query, {"since_ts": since_timestamp})
                else:
                    rows = await session.execute(
                        text(
                            f'SELECT * FROM "{schema}"."{table}" '
                            f'ORDER BY "{pk_col.name}" '
                            f"LIMIT {page_size} OFFSET {offset}"
                        )
                    )
                page_rows = rows.fetchall()
                if not page_rows:
                    break

                if column_names is None:
                    column_names = list(rows.keys())

                page += 1

                # Split each page into embed-batches of 50
                for batch_start in range(0, len(page_rows), embed_batch_size):
                    batch_rows = page_rows[batch_start : batch_start + embed_batch_size]
                    texts: list[str] = []
                    doc_ids: list[UUID] = []
                    metadata_list: list[dict] = []

                    for row in batch_rows:
                        row_dict = dict(zip(column_names, row, strict=True))

                        content_text = _serialize_row(
                            row_dict, column_templates, table_label,
                            fk_resolutions, is_view=source.is_view,
                        )
                        texts.append(content_text)

                        pk_value = row_dict.get(pk_col.name)
                        pk_str = str(pk_value) if pk_value else str(uuid4())
                        doc_id = uuid5(_VECTOR_NS, f"{schema}.{table}:{pk_str}")

                        doc_ids.append(doc_id)

                        row_meta = {
                            "tenant_id": str(tenant_id),
                            "source": f"{schema}.{table}",
                            "table_name": table,
                            "schema_name": schema,
                            **{k: str(v)[:500] if v is not None else "" for k, v in row_dict.items()},
                        }
                        if source.is_view:
                            row_meta["doc_type"] = "aggregated"
                            row_meta["visibility"] = "admin"
                        else:
                            row_meta["visibility"] = "public"
                        metadata_list.append(row_meta)

                    raw_embeddings = await self._embeddings.embed(texts)
                    if isinstance(raw_embeddings[0], float):
                        embeddings_list = [raw_embeddings]  # type: ignore[list-item]
                    else:
                        embeddings_list = raw_embeddings  # type: ignore[assignment]

                    for content_text, doc_id, embedding, meta in zip(
                        texts, doc_ids, embeddings_list, metadata_list
                    ):
                        try:
                            await self._vector_store.upsert(
                                tenant_id=tenant_id,
                                document_id=doc_id,
                                embedding=list(embedding) if not isinstance(embedding, list) else embedding,  # type: ignore[arg-type]
                                content=content_text,
                                metadata=meta,
                            )
                            result.vectors_upserted += 1
                        except Exception as exc:
                            result.failed_rows += 1
                            result.errors.append(
                                f"{schema}.{table} row {doc_id}: {exc}"
                            )
                            logger.warning(
                                "Row upsert failed, continuing",
                                table=f"{schema}.{table}",
                                doc_id=str(doc_id),
                                error=str(exc),
                            )

                    result.rows_indexed += len(batch_rows)

                offset += page_size

                logger.info(
                    "Page ingested",
                    table=f"{schema}.{table}",
                    page=page,
                    total_rows=result.rows_indexed,
                )

            # Marcar tabla como sincronizada en cache
            if self._cache and result.rows_indexed > 0:
                await self._cache.set(
                    self._sync_key(tenant_id, schema, table), "1", ttl_seconds=86400
                )

        except Exception as exc:
            result.errors.append(f"{schema}.{table}: {exc}")
            logger.error(
                "Table ingestion failed",
                table=f"{schema}.{table}",
                error=str(exc),
                exc_info=True,
            )
        finally:
            await session.close()

        return result
