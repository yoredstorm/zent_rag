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

import asyncio
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
    (r"\bbase64_data\b", "", 99),  # Skip — binario/imagen, no indexar en texto
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

        # Truncar textos largos (full text still chunked later at vector upsert)
        if len(value_str) > 2000:
            value_str = value_str[:1997] + "..."

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


def _chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split long text into overlapping chunks. Short texts return as-is."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    step = max(max_chars - overlap, 1)
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return chunks


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
        from src.config import get_settings
        settings = get_settings()
        self._chunk_max_chars = settings.RAG_CHUNK_MAX_CHARS
        self._chunk_overlap = settings.RAG_CHUNK_OVERLAP
        embed_batch, embed_conc, table_conc = settings.ingestion_concurrency()
        self._embed_batch_size = embed_batch
        self._embed_concurrency = embed_conc
        self._table_concurrency = table_conc
        self._upsert_batch_size = settings.INGEST_UPSERT_BATCH_SIZE
        self._page_size = settings.INGEST_PAGE_SIZE
        self._skip_tables = settings.ingest_skip_table_set()
        self._max_rows_per_table = settings.INGEST_MAX_ROWS_PER_TABLE

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
            progress = await self.get_table_progress(tenant_id, s.schema_name, s.table_name)
            results.append({**s.__dict__, "synced": synced, "progress": progress})
        return results

    async def get_table_progress(self, tenant_id: UUID, schema: str, table: str) -> dict | None:
        if not self._cache:
            return None
        import json
        raw = await self._cache.get(f"rag:progress:{tenant_id.hex}:{schema}.{table}")
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass
        return None

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
        """Sincroniza todas las tablas automáticamente (con concurrencia configurable)."""
        start = time.perf_counter()
        sources = await self.discover_sources(tenant_id)
        active_sources = [
            s for s in sources
            if s.row_count > 0 and s.table_name.lower() not in self._skip_tables
        ]
        skipped = [
            s.table_name for s in sources
            if s.row_count > 0 and s.table_name.lower() in self._skip_tables
        ]
        if skipped:
            logger.info("Skipping tables during sync", tables=skipped)

        total_tables = len(active_sources)

        result = IngestionResult(
            tenant_id=tenant_id,
            tables_processed=0,
            rows_indexed=0,
            vectors_upserted=0,
        )

        if full_refresh:
            await self._vector_store.delete_by_tenant(tenant_id)

        if job_id:
            from src.infrastructure.ingestion_queue import update_job_status
            msg = f"Descubiertas {total_tables} tablas"
            if skipped:
                msg += f" (omitidas: {', '.join(skipped)})"
            await update_job_status(
                job_id,
                "running",
                progress=0,
                message=msg if total_tables else "Sin tablas con filas",
                current_table="",
                tables_done=0,
                tables_total=total_tables,
            )

        done_lock = asyncio.Lock()
        tables_done = 0

        async def _run_one(source: DataSource) -> IngestionResult:
            nonlocal tables_done
            table_label = f"{source.schema_name}.{source.table_name}"
            if job_id and total_tables > 0:
                from src.infrastructure.ingestion_queue import update_job_status
                async with done_lock:
                    percent = min(int(tables_done / total_tables * 100), 99)
                    await update_job_status(
                        job_id,
                        "running",
                        progress=percent,
                        message=f"Sincronizando {table_label}",
                        current_table=table_label,
                        tables_done=tables_done,
                        tables_total=total_tables,
                    )

            has_updated_at = any(c.name == "updated_at" for c in source.columns)
            since_ts = None
            if has_updated_at and self._cache and not full_refresh:
                since_ts = await self._cache.get(
                    self._sync_ts_key(tenant_id, source.schema_name, source.table_name)
                )
                if since_ts:
                    logger.info("Incremental sync", table=table_label, since=since_ts)

            table_result = await self._ingest_table(
                tenant_id, source, job_id=job_id, since_timestamp=since_ts
            )

            if has_updated_at and self._cache and table_result.rows_indexed > 0:
                from datetime import datetime, timezone
                await self._cache.set(
                    self._sync_ts_key(tenant_id, source.schema_name, source.table_name),
                    datetime.now(timezone.utc).isoformat(),
                    ttl_seconds=86400 * 30,
                )

            async with done_lock:
                tables_done += 1
                if job_id and total_tables > 0:
                    from src.infrastructure.ingestion_queue import update_job_status
                    percent = min(int(tables_done / total_tables * 100), 100)
                    await update_job_status(
                        job_id,
                        "running",
                        progress=percent,
                        message=f"Completada {table_label} ({tables_done}/{total_tables})",
                        current_table=table_label,
                        tables_done=tables_done,
                        tables_total=total_tables,
                    )
            return table_result

        sem = asyncio.Semaphore(self._table_concurrency)

        async def _bounded(source: DataSource) -> IngestionResult:
            async with sem:
                return await _run_one(source)

        if active_sources:
            outcomes = await asyncio.gather(
                *[_bounded(s) for s in active_sources],
                return_exceptions=True,
            )
            for source, outcome in zip(active_sources, outcomes):
                if isinstance(outcome, Exception):
                    result.errors.append(
                        f"{source.schema_name}.{source.table_name}: {outcome}"
                    )
                    result.tables_processed += 1
                    continue
                result.tables_processed += 1
                result.rows_indexed += outcome.rows_indexed
                result.vectors_upserted += outcome.vectors_upserted
                result.errors.extend(outcome.errors)
                result.failed_rows += outcome.failed_rows

        result.duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "Ingestion sync completed",
            tenant_id=str(tenant_id),
            tables=result.tables_processed,
            rows=result.rows_indexed,
            vectors=result.vectors_upserted,
            duration_ms=result.duration_ms,
            errors=len(result.errors),
            skipped=skipped,
            table_concurrency=self._table_concurrency,
            embed_concurrency=self._embed_concurrency,
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
        self,
        tenant_id: UUID,
        source: DataSource,
        since_timestamp: str | None = None,
        job_id: str | None = None,
    ) -> IngestionResult:
        """Ingiere filas de una tabla a Qdrant (embed paralelo + upsert batch)."""
        result = IngestionResult(tenant_id=tenant_id, tables_processed=1)

        column_templates = [
            _column_to_template(col.name, col.data_type)
            for col in source.columns
            if not col.is_primary_key
        ]

        table_label = source.table_name.replace("_", " ").title()
        schema = source.schema_name
        table = source.table_name
        table_full = f"{schema}.{table}"

        session = await get_async_session()
        try:
            pk_col = next(
                (col for col in source.columns if col.is_primary_key),
                source.columns[0] if source.columns else None,
            )
            if pk_col is None:
                result.errors.append(f"Table {table_full} has no columns")
                return result

            fk_resolutions: dict[str, tuple[str, dict[str, str]]] = {}
            for col in source.columns:
                if col.is_foreign_key and col.fk_table and col.fk_column:
                    resolved = await self._resolve_fk_values(
                        session, schema, col.fk_table, col.fk_column
                    )
                    if resolved:
                        label = col.fk_table.replace("_", " ").title()
                        fk_resolutions[col.name] = (label, resolved)

            product_images: dict[str, str] = {}
            if table == "products":
                try:
                    img_rows = await session.execute(
                        text(
                            "SELECT product_id::text, base64_data "
                            "FROM farmacia.product_images "
                            "WHERE is_primary = true"
                        )
                    )
                    for img_row in img_rows.fetchall():
                        if img_row[0] and img_row[1]:
                            product_images[img_row[0]] = img_row[1]
                    if product_images:
                        logger.info(
                            "Loaded product images for ingestion",
                            count=len(product_images),
                        )
                except Exception:
                    pass

            page_size = self._page_size
            embed_batch_size = self._embed_batch_size
            max_rows = self._max_rows_per_table
            offset = 0
            column_names: list[str] | None = None
            page = 0
            embed_sem = asyncio.Semaphore(self._embed_concurrency)

            while True:
                if max_rows and offset >= max_rows:
                    logger.info(
                        "Hit max rows cap for table",
                        table=table_full,
                        max_rows=max_rows,
                    )
                    break

                limit = page_size
                if max_rows:
                    limit = min(page_size, max_rows - offset)

                if since_timestamp:
                    query = text(
                        f'SELECT * FROM "{schema}"."{table}" '
                        f'WHERE "updated_at" > :since_ts '
                        f'ORDER BY "{pk_col.name}" '
                        f"LIMIT {limit} OFFSET {offset}"
                    )
                    rows = await session.execute(query, {"since_ts": since_timestamp})
                else:
                    rows = await session.execute(
                        text(
                            f'SELECT * FROM "{schema}"."{table}" '
                            f'ORDER BY "{pk_col.name}" '
                            f"LIMIT {limit} OFFSET {offset}"
                        )
                    )
                page_rows = rows.fetchall()
                if not page_rows:
                    break

                if column_names is None:
                    column_names = list(rows.keys())

                page += 1
                if job_id:
                    from src.infrastructure.ingestion_queue import update_job_status
                    await update_job_status(
                        job_id,
                        "running",
                        message=(
                            f"{table_full} página {page}, "
                            f"filas indexadas {result.rows_indexed}+…"
                        ),
                        current_table=table_full,
                    )

                # Build all text chunks for this page, then embed in parallel batches
                page_texts: list[str] = []
                page_doc_ids: list[UUID] = []
                page_metas: list[dict] = []
                rows_in_page = 0

                for row in page_rows:
                    row_dict = dict(zip(column_names, row, strict=True))
                    content_text = _serialize_row(
                        row_dict, column_templates, table_label,
                        fk_resolutions, is_view=source.is_view,
                    )
                    pk_value = row_dict.get(pk_col.name)
                    pk_str = str(pk_value) if pk_value else str(uuid4())
                    parent_id = uuid5(_VECTOR_NS, f"{schema}.{table}:{pk_str}")
                    text_chunks = _chunk_text(
                        content_text, self._chunk_max_chars, self._chunk_overlap
                    )
                    for chunk_index, chunk_text in enumerate(text_chunks):
                        doc_id = (
                            parent_id
                            if len(text_chunks) == 1
                            else uuid5(
                                _VECTOR_NS,
                                f"{schema}.{table}:{pk_str}:chunk:{chunk_index}",
                            )
                        )
                        page_texts.append(chunk_text)
                        page_doc_ids.append(doc_id)
                        row_meta = {
                            "tenant_id": str(tenant_id),
                            "source": table_full,
                            "table_name": table,
                            "schema_name": schema,
                            "parent_row_id": str(parent_id),
                            "chunk_index": str(chunk_index),
                            "chunk_count": str(len(text_chunks)),
                            **{
                                k: str(v)[:500] if v is not None else ""
                                for k, v in row_dict.items()
                            },
                        }
                        if source.is_view:
                            row_meta["doc_type"] = "aggregated"
                            row_meta["visibility"] = "admin"
                        else:
                            row_meta["visibility"] = "public"
                        if product_images and pk_str in product_images:
                            row_meta["image_base64"] = product_images[pk_str]
                            row_meta["has_image"] = "true"
                        page_metas.append(row_meta)
                    rows_in_page += 1

                async def _embed_slice(
                    start: int,
                    end: int,
                    texts: list[str],
                ) -> tuple[int, list[list[float]] | Exception]:
                    batch = texts[start:end]
                    async with embed_sem:
                        try:
                            raw = await self._embeddings.embed(batch)
                            if batch and isinstance(raw[0], float):
                                return start, [raw]  # type: ignore[list-item]
                            return start, raw  # type: ignore[return-value]
                        except Exception as exc:
                            return start, exc

                embed_jobs = [
                    _embed_slice(
                        i,
                        min(i + embed_batch_size, len(page_texts)),
                        page_texts,
                    )
                    for i in range(0, len(page_texts), embed_batch_size)
                ]
                embed_results = await asyncio.gather(*embed_jobs)

                # Reconstruct embeddings in order
                embeddings_by_idx: dict[int, list[float]] = {}
                for start_idx, payload in embed_results:
                    if isinstance(payload, Exception):
                        result.failed_rows += embed_batch_size
                        result.errors.append(f"{table_full} embed@{start_idx}: {payload}")
                        continue
                    for j, emb in enumerate(payload):
                        embeddings_by_idx[start_idx + j] = (
                            list(emb) if not isinstance(emb, list) else emb  # type: ignore[arg-type]
                        )

                # Upsert in batches
                batch_points: list[tuple[UUID, list[float], str, dict | None]] = []
                for idx, (doc_id, content_text, meta) in enumerate(
                    zip(page_doc_ids, page_texts, page_metas)
                ):
                    emb = embeddings_by_idx.get(idx)
                    if emb is None:
                        continue
                    batch_points.append((doc_id, emb, content_text, meta))
                    if len(batch_points) >= self._upsert_batch_size:
                        try:
                            await self._vector_store.upsert_batch(tenant_id, batch_points)
                            result.vectors_upserted += len(batch_points)
                        except Exception as exc:
                            err = f"{type(exc).__name__}: {exc}".strip(": ")
                            result.failed_rows += len(batch_points)
                            result.errors.append(f"{table_full} upsert: {err}")
                            logger.warning(
                                "Upsert batch failed",
                                table=table_full,
                                batch_size=len(batch_points),
                                error=err,
                            )
                        batch_points = []

                if batch_points:
                    try:
                        await self._vector_store.upsert_batch(tenant_id, batch_points)
                        result.vectors_upserted += len(batch_points)
                    except Exception as exc:
                        err = f"{type(exc).__name__}: {exc}".strip(": ")
                        result.failed_rows += len(batch_points)
                        result.errors.append(f"{table_full} upsert: {err}")
                        logger.warning(
                            "Upsert batch failed",
                            table=table_full,
                            batch_size=len(batch_points),
                            error=err,
                        )

                result.rows_indexed += rows_in_page
                offset += limit

                if self._cache and source.row_count and source.row_count > 0:
                    import json
                    pct = min(int(result.rows_indexed / source.row_count * 100), 99)
                    await self._cache.set(
                        f"rag:progress:{tenant_id.hex}:{schema}.{table}",
                        json.dumps({
                            "rows_indexed": result.rows_indexed,
                            "row_count": source.row_count,
                            "page": page,
                            "pct": pct,
                            "status": "running",
                        }),
                        ttl_seconds=3600,
                    )

                logger.info(
                    "Page ingested",
                    table=table_full,
                    page=page,
                    total_rows=result.rows_indexed,
                    vectors=result.vectors_upserted,
                )

            if self._cache and result.rows_indexed > 0:
                await self._cache.set(
                    self._sync_key(tenant_id, schema, table), "1", ttl_seconds=86400
                )
                import json
                await self._cache.set(
                    f"rag:progress:{tenant_id.hex}:{schema}.{table}",
                    json.dumps({
                        "rows_indexed": result.rows_indexed,
                        "row_count": source.row_count,
                        "pct": 100,
                        "status": "completed",
                    }),
                    ttl_seconds=86400,
                )

        except Exception as exc:
            result.errors.append(f"{table_full}: {exc}")
            logger.error(
                "Table ingestion failed",
                table=table_full,
                error=str(exc),
                exc_info=True,
            )
        finally:
            await session.close()

        return result
