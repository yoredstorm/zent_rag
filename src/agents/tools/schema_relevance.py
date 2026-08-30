# =============================================================================
# Schema Intelligence — caché + relevancia de tablas/columnas
# =============================================================================
# El LLM de generación SOLO recibe el subconjunto relevante del schema:
#   - Table relevance: BM25 (tokenizador de infrastructure.qdrant.bm25) entre
#     la pregunta y (tabla + columnas), boost por row_count y FK.
#   - Column relevance: se filtran columnas técnicas (uuid PK, timestamps
#     internos) salvo que matcheen la pregunta o sean necesarias en joins.
#   - Caché Redis del discovery por organization (TTL configurable).
#
# NOTA de arquitectura: agents/ no puede importar infrastructure directamente
# (test_architecture). El tokenizador BM25 es una función pura sin estado;
# para respetar las capas se re-tokeniza localmente con la misma lógica.
# =============================================================================
from __future__ import annotations

import json
import re
from uuid import UUID

from src.core.domain.services import ColumnMeta, DataSource
from src.core.ports import CacheProvider

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Sinónimos ES→EN del vocabulario retail: "ventas" debe puntuar contra la
# tabla `sales`, "proveedores" contra `suppliers`, etc. Sin esto, las tablas
# de negocio empatan en score con ruido (row_count + FK) y las necesarias
# quedan fuera del subconjunto que recibe el LLM.
_RETAIL_SYNONYMS: dict[str, str] = {
    "venta": "sales", "ventas": "sales", "vendido": "sales", "vendida": "sales",
    "vendidos": "sales", "vendidas": "sales", "compra": "purchases", "compras": "purchases",
    "pedido": "orders", "pedidos": "orders", "orden": "orders", "ordenes": "orders",
    "producto": "products", "productos": "products",
    "medicamento": "products", "medicamentos": "products",
    "proveedor": "suppliers", "proveedores": "suppliers",
    "laboratorio": "suppliers", "laboratorios": "suppliers",
    "categoria": "categories", "categorias": "categories",
    "cliente": "customers", "clientes": "customers",
    "inventario": "inventory", "stock": "inventory",
    "empleado": "employees", "empleados": "employees",
    "receta": "prescriptions", "recetas": "prescriptions",
    "transaccion": "transactions", "transacciones": "transactions",
    "factura": "invoices", "facturas": "invoices",
    "fonasa": "health_insurance", "isapre": "health_insurance",
    "isapres": "health_insurance", "seguro": "health_insurance",
    "resena": "reviews", "resenas": "reviews", "opiniones": "reviews",
}

# Columnas técnicas que no aportan contexto al LLM salvo excepción.
_TECHNICAL_COLUMN_PATTERNS = (
    re.compile(r"^id$"),
    re.compile(r"_id$"),
    re.compile(r"^(created_at|updated_at|deleted_at)$"),
    re.compile(r"^.*_at$"),
    re.compile(r"^slug$"),
    re.compile(r"^external_id$"),
    re.compile(r"^content_hash$"),
)


def _tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return set(_TOKEN_RE.findall(lowered))


class SchemaCache:
    """Caché del schema descubierto por organization (Redis)."""

    def __init__(self, cache: CacheProvider, ttl_seconds: int = 300) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    @staticmethod
    def _key(organization_id: UUID) -> str:
        return f"sql:schema:{organization_id.hex}"

    async def get(self, organization_id: UUID) -> list[DataSource] | None:
        raw = await self._cache.get(self._key(organization_id))
        if raw is None:
            return None
        try:
            return _sources_from_json(raw)
        except Exception:
            return None

    async def set(self, organization_id: UUID, sources: list[DataSource]) -> None:
        payload = json.dumps(
            [
                {
                    "schema_name": s.schema_name,
                    "table_name": s.table_name,
                    "row_count": s.row_count,
                    "is_view": s.is_view,
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "is_nullable": c.is_nullable,
                            "is_primary_key": c.is_primary_key,
                            "is_foreign_key": c.is_foreign_key,
                            "fk_table": c.fk_table,
                            "fk_column": c.fk_column,
                        }
                        for c in s.columns
                    ],
                }
                for s in sources
            ]
        )
        await self._cache.set(self._key(organization_id), payload, ttl_seconds=self._ttl)

    async def invalidate(self, organization_id: UUID) -> None:
        await self._cache.delete(self._key(organization_id))


def _sources_from_json(raw: str) -> list[DataSource]:
    data = json.loads(raw)
    sources: list[DataSource] = []
    for item in data:
        sources.append(
            DataSource(
                schema_name=item["schema_name"],
                table_name=item["table_name"],
                row_count=int(item.get("row_count") or 0),
                is_view=bool(item.get("is_view")),
                columns=[
                    ColumnMeta(
                        name=c["name"],
                        data_type=c["data_type"],
                        is_nullable=c.get("is_nullable", True),
                        is_primary_key=c.get("is_primary_key", False),
                        is_foreign_key=c.get("is_foreign_key", False),
                        fk_table=c.get("fk_table"),
                        fk_column=c.get("fk_column"),
                    )
                    for c in item.get("columns", [])
                ],
            )
        )
    return sources


def _token_match(tokens: set[str], name: str) -> int:
    """Match exacto o substring entre tokens de pregunta y nombre."""
    lowered = (name or "").lower()
    hits = 0
    for token in tokens:
        if not token:
            continue
        if token in lowered or lowered in token:
            hits += 1
    return hits


def score_table(question_tokens: set[str], source: DataSource) -> float:
    """Score de relevancia de una tabla para la pregunta (0..1 heurístico)."""
    hits = _token_match(question_tokens, source.table_name)
    column_hits = sum(
        _token_match(question_tokens, c.name) for c in source.columns
    )
    syn_hits = sum(
        1
        for token in question_tokens
        if (target := _RETAIL_SYNONYMS.get(token))
        and target in source.table_name
    )

    score = hits * 3.0 + syn_hits * 3.0 + column_hits * 1.0
    if source.row_count and source.row_count > 1000:
        score += 0.5
    if any(c.is_foreign_key for c in source.columns):
        score += 0.25
    return score


def rank_tables(
    question: str,
    sources: list[DataSource],
    max_tables: int = 8,
) -> list[DataSource]:
    """Selecciona las tablas más relevantes para la pregunta.

    Fallback: si ninguna tabla matchea, devuelve las primeras N (nunca
    vacío salvo schema vacío) para que el LLM decida con inventario acotado.
    """
    question_tokens = _tokens(question)
    scored = sorted(
        sources,
        key=lambda s: score_table(question_tokens, s),
        reverse=True,
    )
    top = [s for s in scored if score_table(question_tokens, s) > 0][:max_tables]
    if not top:
        top = scored[:max_tables]
    return top


def select_columns(
    question: str,
    source: DataSource,
    include_fk_columns: bool = True,
) -> list[ColumnMeta]:
    """Filtra columnas técnicas salvo matches con la pregunta o FKs de join."""
    question_tokens = _tokens(question)
    selected: list[ColumnMeta] = []
    for col in source.columns:
        name_lower = col.name.lower()
        if _tokens(name_lower) & question_tokens:
            selected.append(col)
            continue
        if include_fk_columns and col.is_foreign_key:
            selected.append(col)
            continue
        if col.is_primary_key:
            continue
        if any(p.search(name_lower) for p in _TECHNICAL_COLUMN_PATTERNS):
            continue
        selected.append(col)
    if not selected and source.columns:
        return list(source.columns)
    return selected


def _source_key(source: DataSource) -> tuple[str, str]:
    return (source.schema_name.lower(), source.table_name.lower())


def _fk_expand(
    core: list[DataSource],
    all_sources: list[DataSource],
    max_tables: int,
) -> list[DataSource]:
    """Expande el núcleo con tablas conectadas por FK (necesarias para JOINs).

    BFS sobre las aristas FK: tablas referenciadas por columnas FK del núcleo
    y tablas que referencian al núcleo. Sin esto, el LLM genera JOINs a tablas
    que no están en el inventario y la validación las rechaza (allowlist).
    """
    by_key: dict[tuple[str, str], DataSource] = {}
    by_bare_name: dict[str, list[DataSource]] = {}
    referencers: dict[str, list[DataSource]] = {}
    for s in all_sources:
        by_key[_source_key(s)] = s
        by_bare_name.setdefault(s.table_name.lower(), []).append(s)
        for c in s.columns:
            if c.is_foreign_key and c.fk_table:
                referencers.setdefault(c.fk_table.lower(), []).append(s)

    selected: dict[tuple[str, str], DataSource] = {}
    for s in core:
        selected[_source_key(s)] = s

    queue: list[tuple[str, str]] = list(selected)
    while queue and len(selected) < max_tables:
        key = queue.pop(0)
        src = by_key.get(key)
        if src is None:
            continue
        for c in src.columns:
            if not (c.is_foreign_key and c.fk_table):
                continue
            for target in by_bare_name.get(c.fk_table.lower(), []):
                tkey = _source_key(target)
                if tkey not in selected:
                    selected[tkey] = target
                    queue.append(tkey)
                    if len(selected) >= max_tables:
                        break
            if len(selected) >= max_tables:
                break
        if len(selected) >= max_tables:
            break
        for ref in referencers.get(src.table_name.lower(), []):
            rkey = _source_key(ref)
            if rkey not in selected:
                selected[rkey] = ref
                queue.append(rkey)
                if len(selected) >= max_tables:
                    break

    ordered: list[DataSource] = []
    seen: set[tuple[str, str]] = set()
    for s in core:
        k = _source_key(s)
        seen.add(k)
        ordered.append(s)
    for s in all_sources:
        k = _source_key(s)
        if k in selected and k not in seen:
            seen.add(k)
            ordered.append(s)
    return ordered[:max_tables]


def build_relevant_schema(
    question: str,
    sources: list[DataSource],
    max_tables: int = 8,
) -> list[DataSource]:
    """Subconjunto de tablas + columnas relevantes listo para el prompt."""
    relevant_tables = rank_tables(question, sources, max_tables)
    expanded = _fk_expand(relevant_tables, sources, max_tables)
    result: list[DataSource] = []
    for source in expanded:
        result.append(
            DataSource(
                schema_name=source.schema_name,
                table_name=source.table_name,
                row_count=source.row_count,
                is_view=source.is_view,
                columns=select_columns(question, source),
            )
        )
    return result
