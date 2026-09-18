# =============================================================================
# Tabular ingestion — SQL-first para preguntas sobre Excel/CSV
# =============================================================================
# Router determinista (sin LLM) + ejecución sobre la representación
# estructurada (tabular_rows en Postgres). Devuelve un `SqlQueryResult` con SQL
# real, filas exactas y provenance a tabla/hoja/fila/celda. Si la pregunta es
# semántica o ambigua, retorna None y el flujo normal (dense/sparse) continúa.
#
# Prioridad SQL: el orquestador intenta este camino ANTES del SQL Expert LLM.
# =============================================================================
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from uuid import UUID

from src.core.ports.sql_expert import SqlQueryResult
from src.core.ports.tabular import TabularRepository
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.tabular.lookup import (
    find_label_row,
    match_column_payload,
    normalize_question,
    resolve_exact_lookup,
)
from src.knowledge.tabular.map import (
    TabularMap,
    TabularMapColumn,
    TabularMapTable,
    build_tabular_map,
    find_candidate_tables,
)

logger = get_logger(__name__)

_INTENT_EXACT_LOOKUP = "exact_lookup"
_INTENT_AGGREGATION = "aggregation"
_INTENT_LIST = "list"
_INTENT_FILTER = "filter"
_INTENT_DICTIONARY = "dictionary"
_INTENT_SEMANTIC = "semantic"
_INTENT_UNKNOWN = "unknown"

_AGGREGATION_TERMS = (
    "cuantos", "cuantas", "how many", "count", "numero de", "number of",
    "total de", "suma", "sum of", "promedio", "average", "maximo", "maximum",
    "max ", "minimo", "minimum", "min ",
)
_SEMANTIC_TERMS = (
    "significa", "meaning", "mean", "define", "definir", "que es", "what is",
    "para que sirve", "definicion", "definition", "describe", "explica",
    "explain", "significado",
)
_METRIC_SEMANTIC_TYPES = ("length", "position", "amount", "quantity", "percentage")
_FILTER_TERMS = (
    "entre", "between", "mayor", "menor", "greater", "less", "mas de",
    "menos de", "desde", "hasta", "range", "rango",
)
_LIST_TERMS = (
    "which", "cuales", "cuáles", "list", "lista", "todos", "todas", "all ",
    "ejemplos", "examples", "muestra", "muestrame", "show me", "dame los",
    "dame las",
)
_NUMBER_RE = re.compile(r"(?<![\w])(\d{1,9}(?:[.,]\d+)?)(?![\w])")
_LABEL_SEMANTICS = ("name", "identifier", "code", "reference")
_NUMERIC_TYPES = ("integer", "float", "decimal", "currency", "percentage")


@dataclass(frozen=True, kw_only=True)
class TabularIntent:
    """Clasificación determinista de una pregunta sobre una tabla."""

    kind: str = _INTENT_UNKNOWN
    column: TabularMapColumn | None = None
    numeric_column: TabularMapColumn | None = None
    filter_value: str | None = None
    range_bounds: tuple[str, str] | None = None
    confidence: float = 0.0
    reason: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class _CachedMap:
    tabular_map: TabularMap
    expires_at: float


def _observe_stage(organization_id: UUID, stage: str, seconds: float) -> None:
    try:
        from src.infrastructure.observability.metrics import (
            rag_retrieval_stage_latency,
        )

        rag_retrieval_stage_latency.labels(
            organization_id=str(organization_id), stage=stage
        ).observe(max(0.0, seconds))
    except Exception:  # pragma: no cover - métricas nunca rompen la query
        pass


def classify_tabular_question(question: str, table: TabularMapTable) -> TabularIntent:
    """Clasifica la pregunta contra una tabla: lookup / agregación / filtro / semántica."""
    normalized = normalize_question(question)
    if not normalized:
        return TabularIntent(reason="empty_question")

    numeric_columns = [c for c in table.columns if c.inferred_type in _NUMERIC_TYPES]
    matched_column = _match_column(normalized, table)
    numbers = [match.group(1) for match in _NUMBER_RE.finditer(normalized)]

    is_aggregation = any(term in normalized for term in _AGGREGATION_TERMS)
    is_semantic = any(term in normalized for term in _SEMANTIC_TERMS)
    has_filter_term = any(term in normalized for term in _FILTER_TERMS)

    # Diccionario: "¿qué significa X?" / "define X" → fila por label + columnas
    # de documentación (Description/Specifications). Las preguntas de métrica
    # ("posición de X", "cuánto mide X") NO van acá: son lookup exacto.
    metric_question = (
        matched_column is not None
        and matched_column.semantic_type in _METRIC_SEMANTIC_TYPES
    )
    if is_semantic and not is_aggregation and not has_filter_term and not metric_question:
        return TabularIntent(
            kind=_INTENT_DICTIONARY, confidence=0.7, reason="semantic_terms"
        )

    if is_aggregation:
        column = matched_column or (numeric_columns[0] if numeric_columns else None)
        filter_value = numbers[0] if column is not None and numbers else None
        return TabularIntent(
            kind=_INTENT_AGGREGATION,
            column=column,
            numeric_column=column if column and column.inferred_type in _NUMERIC_TYPES else None,
            filter_value=filter_value,
            confidence=0.9 if column is not None else 0.75,
            reason="aggregation_terms",
        )

    # Lista: "¿qué campos tienen longitud 2?" → N filas con ese valor + total.
    is_list = any(term in normalized for term in _LIST_TERMS)
    if is_list and not has_filter_term and matched_column is not None and numbers:
        return TabularIntent(
            kind=_INTENT_LIST,
            column=matched_column,
            numeric_column=(
                matched_column if matched_column.inferred_type in _NUMERIC_TYPES else None
            ),
            filter_value=numbers[0],
            confidence=0.85,
            reason="list_terms",
        )

    if has_filter_term and len(numbers) >= 2:
        column = matched_column or (numeric_columns[0] if numeric_columns else None)
        if column is not None:
            return TabularIntent(
                kind=_INTENT_FILTER,
                column=column,
                numeric_column=column if column.inferred_type in _NUMERIC_TYPES else None,
                range_bounds=(numbers[0], numbers[1]),
                confidence=0.85,
                reason="range_terms",
            )

    if matched_column is not None:
        # "¿qué campo empieza en 30?" → columna numérica + número: lookup inverso.
        return TabularIntent(
            kind=_INTENT_EXACT_LOOKUP,
            column=matched_column,
            numeric_column=matched_column if matched_column.inferred_type in _NUMERIC_TYPES else None,
            filter_value=numbers[0] if numbers else None,
            confidence=0.9 if numbers else 0.85,
            reason="column_match",
        )

    return TabularIntent(kind=_INTENT_UNKNOWN, confidence=0.2, reason="no_signal")


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


class TabularQueryService:
    """Ejecuta preguntas tabulares exactas contra la representación estructurada."""

    def __init__(
        self,
        repository: TabularRepository,
        *,
        lazy_ingestion: object | None = None,
        max_lookup_rows: int = 20_000,
        max_result_rows: int = 50,
        min_confidence: float = 0.7,
        max_candidates: int = 3,
        map_ttl_seconds: float = 30.0,
    ) -> None:
        self._repository = repository
        self._lazy = lazy_ingestion
        self._max_lookup_rows = max_lookup_rows
        self._max_result_rows = max_result_rows
        self._min_confidence = min_confidence
        self._max_candidates = max_candidates
        self._map_ttl_seconds = max(0.0, float(map_ttl_seconds))
        self._map_cache: dict[tuple, _CachedMap] = {}

    def invalidate_map(self) -> None:
        """Invalida el mapa cacheado (tras auto-ingesta o reindex)."""
        self._map_cache.clear()

    async def try_answer(
        self,
        organization_id: UUID,
        question: str,
        *,
        source_ids: list[UUID] | None = None,
        knowledge_base_id: UUID | None = None,
        role: str = "admin",
        user_id: UUID | None = None,
    ) -> SqlQueryResult | None:
        """Respuesta exacta o None (el caller continúa con RAG normal)."""


        started = time.perf_counter()
        try:
            return await self._try_answer_inner(
                organization_id,
                question,
                source_ids=source_ids,
                knowledge_base_id=knowledge_base_id,
                role=role,
                user_id=user_id,
            )
        finally:
            _observe_stage(
                organization_id, "tabular_sql_first", time.perf_counter() - started
            )

    async def _try_answer_inner(
        self,
        organization_id: UUID,
        question: str,
        *,
        source_ids: list[UUID] | None,
        knowledge_base_id: UUID | None,
        role: str,
        user_id: UUID | None,
    ) -> SqlQueryResult | None:
        tabular_map = await self._get_map(
            organization_id,
            source_ids=source_ids,
            knowledge_base_id=knowledge_base_id,
        )
        candidates = find_candidate_tables(
            tabular_map, question, max_candidates=self._max_candidates
        )
        # Autoingesta al consultar: si no hay representación estructurada para
        # fuentes excel/csv pendientes, se ingesta (bounded) y se reintenta.
        if not candidates and self._lazy is not None:
            await self._lazy.ensure_ingested(
                organization_id,
                knowledge_base_id=knowledge_base_id,
                source_ids=source_ids,
            )
            self.invalidate_map()
            tabular_map = await self._get_map(
                organization_id,
                source_ids=source_ids,
                knowledge_base_id=knowledge_base_id,
            )
            candidates = find_candidate_tables(
                tabular_map, question, max_candidates=self._max_candidates
            )
        if not candidates:
            return None

        allow_aggregations = role != "customer"
        top_label = str(candidates[0][0].id)
        for table, _score in candidates:
            result = await self._answer_for_table(
                organization_id,
                question,
                table,
                allow_aggregations=allow_aggregations,
            )
            if result is None:
                continue
            # Ambigüedad: segunda tabla con score cercano y respuesta distinta.
            if (
                str(table.id) == top_label
                and len(candidates) > 1
                and candidates[1][1] >= candidates[0][1] - 0.75
            ):
                second = await self._answer_for_table(
                    organization_id,
                    question,
                    candidates[1][0],
                    allow_aggregations=allow_aggregations,
                )
                if second is not None and second.rows != result.rows:
                    logger.info(
                        "Tabular SQL-first ambiguous, falling back to RAG",
                        organization_id=str(organization_id),
                        tables=[candidates[0][0].name, candidates[1][0].name],
                    )
                    return None
            result.metadata = {
                **result.metadata,
                "role": role,
                "user_id": str(user_id) if user_id else None,
            }
            return result
        return None

    # ------------------------------------------------------------------
    # Mapa con caché TTL (evita 3 queries por consulta)
    # ------------------------------------------------------------------
    async def _get_map(
        self,
        organization_id: UUID,
        *,
        source_ids: list[UUID] | None,
        knowledge_base_id: UUID | None,
    ) -> TabularMap:


        key = (
            str(organization_id),
            tuple(sorted(str(source_id) for source_id in source_ids or [])),
            str(knowledge_base_id) if knowledge_base_id else "",
        )
        cached = self._map_cache.get(key)
        now = time.monotonic()
        if cached is not None and cached.expires_at > now:
            return cached.tabular_map
        started = time.perf_counter()
        tabular_map = await build_tabular_map(
            self._repository,
            organization_id,
            source_ids=source_ids,
            knowledge_base_id=knowledge_base_id,
        )
        _observe_stage(organization_id, "tabular_map", time.perf_counter() - started)
        self._map_cache[key] = _CachedMap(
            tabular_map=tabular_map, expires_at=now + self._map_ttl_seconds
        )
        return tabular_map

    # ------------------------------------------------------------------
    # Ejecución por tabla
    # ------------------------------------------------------------------
    async def _answer_for_table(
        self,
        organization_id: UUID,
        question: str,
        table: TabularMapTable,
        *,
        allow_aggregations: bool,
    ) -> SqlQueryResult | None:
        intent = classify_tabular_question(question, table)
        if intent.kind == _INTENT_SEMANTIC or intent.confidence < self._min_confidence:
            return None
        try:
            if intent.kind == _INTENT_AGGREGATION:
                if not allow_aggregations:
                    return None
                return await self._answer_aggregation(organization_id, table, intent)
            if intent.kind == _INTENT_DICTIONARY:
                return await self._answer_dictionary(organization_id, table, question)
            if intent.kind == _INTENT_LIST:
                return await self._answer_list(organization_id, table, intent, question)
            if intent.kind == _INTENT_FILTER:
                return await self._answer_filter(organization_id, table, intent, question)
            if intent.kind == _INTENT_EXACT_LOOKUP:
                return await self._answer_lookup(organization_id, table, intent, question)
        except Exception as exc:  # noqa: BLE001 - nunca rompe el flujo RAG
            logger.warning(
                "Tabular structured query failed",
                table_id=table.id,
                table=table.name,
                error=str(exc)[:300],
            )
        return None

    async def _answer_lookup(
        self,
        organization_id: UUID,
        table: TabularMapTable,
        intent: TabularIntent,
        question: str,
    ) -> SqlQueryResult | None:
        table_id = UUID(table.id)
        columns = [_column_payload(column) for column in table.columns]
        # El label puede estar más allá de la primera página (tablas grandes):
        # se pagina con cap y se conserva el match de label MÁS LARGO global.
        found = await self._find_best_label_row(organization_id, table, question)
        if found is None:
            first_page = await self._repository.fetch_rows(
                organization_id, table_id, limit=1_000
            )
            if not first_page:
                return None
            rows = first_page
            best_matches = 0
        else:
            best_row, _label_column_found, best_matches = found
            rows = [best_row]
        lookup = resolve_exact_lookup(
            question,
            table=_table_payload(table),
            columns=columns,
            rows=rows,
        )
        if not lookup.value:
            return None
        label_column = _label_column(table, question)
        if lookup.row_label_column:
            wanted_label = lookup.row_label_column.strip().lower()
            label_column = next(
                (
                    column
                    for column in table.columns
                    if column.original_name.strip().lower() == wanted_label
                    or column.normalized_name
                    == normalize_question(wanted_label).replace(" ", "_")
                ),
                label_column,
            )
        value_column = intent.column
        if value_column is None and lookup.column:
            wanted = lookup.column.strip().lower()
            value_column = next(
                (
                    column
                    for column in table.columns
                    if column.original_name.strip().lower() == wanted
                    or column.normalized_name
                    == normalize_question(wanted).replace(" ", "_")
                ),
                None,
            )
        # Lookup inverso ("¿qué campo empieza en 30?"): la columna respondida es
        # la buscada (Start Position) y la cita apunta al label (Field Name).
        answer_column = value_column or (
            table.column_by_name(normalize_question(lookup.source_column or "").replace(" ", "_"))
            if lookup.source_column
            else None
        )
        sql = _lookup_sql(
            table,
            label_column=label_column,
            row_label=_row_label_for(rows, label_column, lookup.physical_row),
            value_column=answer_column,
            value=lookup.value,
        )
        row_label = _row_label_for(rows, label_column, lookup.physical_row)
        answer_value = lookup.value
        if answer_column is not None and lookup.strategy == "value+label":
            # Lookup inverso: la celda respuesta es el valor de la columna
            # buscada en la fila (p. ej. Start Position = 30).
            answer_value = (
                _row_value_for(rows, lookup.physical_row, answer_column.normalized_name)
                or lookup.value
            )
        return SqlQueryResult(
            sql=sql,
            columns=[
                label_column.display_name if label_column else "field",
                (answer_column.display_name if answer_column else None)
                or lookup.column
                or "value",
            ],
            rows=[[row_label, answer_value]],
            row_count=1,
            metadata={
                "strategy": f"tabular_lookup:{lookup.strategy}",
                "confidence": lookup.confidence,
                "tables": [table.name],
                "row_matches": best_matches if found is not None else lookup.row_matches,
                "provenance": [
                    _provenance(
                        table,
                        physical_row=lookup.physical_row,
                        cell=lookup.cell_address,
                        column=(
                            answer_column.display_name if answer_column else lookup.column
                        ),
                    )
                ],
            },
        )

    async def _find_best_label_row(
        self, organization_id: UUID, table: TabularMapTable, question: str
    ) -> tuple[dict, TabularMapColumn, int] | None:
        """Fila cuyo label matchea la pregunta (pageando y conservando el mejor).

        El adaptador limita cada fetch a 1000 filas: páginas de 1000 hasta
        `max_lookup_rows`. Devuelve (fila, columna label, ocurrencias).
        """
        label_columns = [
            _column_payload(column) for column in _label_columns_of(table)
        ]
        if not label_columns:
            return None
        table_id = UUID(table.id)
        page_size = 1_000
        best: tuple[int, dict] | None = None
        best_key: tuple[str, str] | None = None
        best_column: TabularMapColumn | None = None
        best_matches = 0
        scanned = 0
        offset = 0
        while scanned < self._max_lookup_rows:
            batch = await self._repository.fetch_rows(
                organization_id, table_id, limit=page_size, offset=offset
            )
            if not batch:
                break
            candidate = find_label_row(question, batch, label_columns)
            if candidate is not None:
                _index, candidate_row, candidate_column, matches = candidate
                candidate_label = str(
                    candidate_row.get("values", {}).get(
                        candidate_column.get("normalized_name"), ""
                    )
                )
                length = len(normalize_question(candidate_label))
                candidate_key = (
                    str(candidate_column.get("normalized_name")),
                    normalize_question(candidate_label),
                )
                candidate_row_number = int(candidate_row.get("physical_row") or 0)
                if (
                    best is None
                    or length > best[0]
                    or (
                        length == best[0]
                        and candidate_row_number < int(best[1].get("physical_row") or 0)
                    )
                ):
                    best = (length, candidate_row)
                    best_key = candidate_key
                    best_matches = matches
                    best_column = next(
                        (
                            column
                            for column in table.columns
                            if column.normalized_name
                            == str(candidate_column.get("normalized_name"))
                        ),
                        None,
                    )
                elif candidate_key == best_key:
                    # Mismo label en la misma columna: suma ocurrencias.
                    best_matches += matches
            scanned += len(batch)
            offset += len(batch)
            if len(batch) < page_size:
                break
        if best is None or best_column is None:
            return None
        return best[1], best_column, best_matches

    async def _answer_dictionary(
        self, organization_id: UUID, table: TabularMapTable, question: str
    ) -> SqlQueryResult | None:
        """Definición documental de un campo: fila por label + columnas de doc.

        Determinista y sin embeddings: "¿qué significa Carrier Code?" devuelve
        la Description/Specifications de esa fila con procedencia a la celda.
        """
        doc_columns = _doc_columns(table)
        if not doc_columns:
            return None
        found = await self._find_best_label_row(organization_id, table, question)
        if found is None:
            return None
        row, label_column, row_matches = found
        label = str(row.get("values", {}).get(label_column.normalized_name, ""))
        if not label or not _label_specific_enough(label, question):
            # Labels muy cortos/parciales ("Name" dentro de "Standard Name") no
            # son el sujeto de la pregunta: mejor que responda RAG.
            return None
        rendered: list[list[str]] = []
        provenance: list[dict] = []
        for column in doc_columns:
            value = str(row.get("values", {}).get(column.normalized_name, "")).strip()
            if not value:
                continue
            rendered.append([label, column.display_name, value])
            provenance.append(
                _provenance(
                    table,
                    physical_row=int(row.get("physical_row") or 0),
                    cell=_cell_for_row(row, column),
                    column=column.display_name,
                )
            )
        if not rendered:
            return None
        return SqlQueryResult(
            sql=_dictionary_sql(table, label_column, label, doc_columns),
            columns=[label_column.display_name, "column", "definition"],
            rows=rendered,
            row_count=len(rendered),
            metadata={
                "strategy": "tabular_dictionary",
                "confidence": 0.8,
                "tables": [table.name],
                "row_matches": row_matches,
                "provenance": provenance,
            },
        )

    async def _answer_aggregation(
        self, organization_id: UUID, table: TabularMapTable, intent: TabularIntent
    ) -> SqlQueryResult | None:
        filters: dict[str, str] = {}
        range_filters: list[tuple[str, str, str]] = []
        if intent.column is not None and intent.filter_value is not None:
            if intent.column.inferred_type in _NUMERIC_TYPES:
                range_filters.append(
                    (intent.column.normalized_name, "=", intent.filter_value)
                )
            else:
                filters[intent.column.normalized_name] = intent.filter_value
        total = await self._repository.count_rows(
            organization_id,
            UUID(table.id),
            filters=filters or None,
            range_filters=range_filters or None,
        )
        sql = _count_sql(
            table,
            column=intent.column.normalized_name if intent.column else None,
            value=intent.filter_value if intent.column else None,
            numeric=bool(range_filters),
        )
        return SqlQueryResult(
            sql=sql,
            columns=["count"],
            rows=[[str(total)]],
            row_count=1,
            metadata={
                "strategy": "tabular_aggregation",
                "confidence": 0.9,
                "tables": [table.name],
                "provenance": [_provenance(table)],
            },
        )

    async def _answer_list(
        self,
        organization_id: UUID,
        table: TabularMapTable,
        intent: TabularIntent,
        question: str = "",
    ) -> SqlQueryResult | None:
        """Lista de filas con un valor exacto (p. ej. "campos con longitud 2")."""
        if intent.column is None or intent.filter_value is None:
            return None
        numeric = intent.column.inferred_type in _NUMERIC_TYPES
        range_filters = (
            [(intent.column.normalized_name, "=", intent.filter_value)]
            if numeric
            else None
        )
        filters = (
            None
            if numeric
            else {intent.column.normalized_name: intent.filter_value}
        )
        total = await self._repository.count_rows(
            organization_id,
            UUID(table.id),
            filters=filters,
            range_filters=range_filters,
        )
        if not total:
            return None
        rows = await self._repository.fetch_rows(
            organization_id,
            UUID(table.id),
            filters=filters,
            range_filters=range_filters,
            limit=self._max_result_rows,
        )
        label_column = _label_column(table, question)
        label_name = label_column.display_name if label_column else "row"
        rendered: list[list[str]] = []
        provenance: list[dict] = []
        for row in rows:
            label = (
                str(row.get("values", {}).get(label_column.normalized_name, ""))
                if label_column
                else ""
            )
            value = str(row.get("values", {}).get(intent.column.normalized_name, ""))
            rendered.append([label, value])
            provenance.append(
                _provenance(
                    table,
                    physical_row=int(row.get("physical_row")),
                    cell=None,
                    column=intent.column.display_name,
                )
            )
        if not rendered:
            return None
        sql = _list_sql(table, intent.column.normalized_name, intent.filter_value, numeric)
        return SqlQueryResult(
            sql=sql,
            columns=[label_name, intent.column.display_name],
            rows=rendered,
            row_count=len(rendered),
            metadata={
                # Lookup inverso en modo lista: la respuesta es el label.
                "strategy": "tabular_lookup:value+label:list",
                "confidence": 0.85,
                "tables": [table.name],
                "total": total,
                "truncated": total > len(rendered),
                "provenance": provenance,
            },
        )

    async def _answer_filter(
        self,
        organization_id: UUID,
        table: TabularMapTable,
        intent: TabularIntent,
        question: str = "",
    ) -> SqlQueryResult | None:
        if intent.column is None or intent.range_bounds is None:
            return None
        if intent.column.inferred_type not in _NUMERIC_TYPES:
            return None
        low, high = intent.range_bounds
        rows = await self._repository.fetch_rows(
            organization_id,
            UUID(table.id),
            range_filters=[
                (intent.column.normalized_name, ">=", low),
                (intent.column.normalized_name, "<=", high),
            ],
            limit=self._max_result_rows,
        )
        label_column = _label_column(table, question)
        label_name = label_column.display_name if label_column else "row"
        rendered: list[list[str]] = []
        provenance: list[dict] = []
        for row in rows:
            label = (
                str(row.get("values", {}).get(label_column.normalized_name, ""))
                if label_column
                else ""
            )
            value = str(row.get("values", {}).get(intent.column.normalized_name, ""))
            rendered.append([label, value])
            provenance.append(
                _provenance(
                    table,
                    physical_row=int(row.get("physical_row")),
                    cell=None,
                    column=intent.column.display_name,
                )
            )
        if not rendered:
            return None
        sql = _range_sql(table, intent.column.normalized_name, low, high)
        return SqlQueryResult(
            sql=sql,
            columns=[label_name, intent.column.display_name],
            rows=rendered,
            row_count=len(rendered),
            metadata={
                "strategy": "tabular_filter_range",
                "confidence": 0.85,
                "tables": [table.name],
                "provenance": provenance,
            },
        )


# ---------------------------------------------------------------------------
# Helpers de clasificación/mapeo
# ---------------------------------------------------------------------------


def _match_column(normalized_question: str, table: TabularMapTable) -> TabularMapColumn | None:
    """Columna mencionada (scoring compartido con lookup.py)."""
    candidates: list[tuple[dict, TabularMapColumn]] = []
    for column in table.columns:
        payload = {
            "normalized_name": column.normalized_name,
            "aliases": list(column.aliases),
            "semantic_type": column.semantic_type,
        }
        candidates.append((payload, column))
    matched = match_column_payload(
        normalized_question, [payload for payload, _column in candidates]
    )
    if matched is None:
        return None
    for payload, column in candidates:
        if payload is matched:
            return column
    return None


def _label_columns_of(table: TabularMapTable) -> list[TabularMapColumn]:
    """Columnas candidatas a identificar la fila, en orden de preferencia."""
    ordered: list[TabularMapColumn] = []
    for semantic in _LABEL_SEMANTICS:
        for column in table.columns:
            if column.semantic_type == semantic and column not in ordered:
                ordered.append(column)
    return ordered or list(table.columns[:1])


def _label_column(
    table: TabularMapTable, question: str = ""
) -> TabularMapColumn | None:
    """Columna label para la respuesta; prefiere la mencionada en la pregunta.

    "Which field starts at position 30?" → Field Name (el usuario pidió el
    campo), no Standard Name. Sin mención explícita, orden semántico habitual.
    """
    candidates = _label_columns_of(table)
    normalized = normalize_question(question)
    if normalized:
        words = set(normalized.split())
        for column in candidates:
            name_tokens = set(normalize_question(column.original_name).split())
            if name_tokens and name_tokens & words:
                return column
    for semantic in _LABEL_SEMANTICS:
        for column in table.columns:
            if column.semantic_type == semantic:
                return column
    return table.columns[0] if table.columns else None


def _column_payload(column: TabularMapColumn) -> dict:
    return {
        "normalized_name": column.normalized_name,
        "original_name": column.original_name,
        "aliases": list(column.aliases),
        "semantic_type": column.semantic_type,
        "physical_column": column.physical_column,
        "excel_letter": column.excel_letter,
    }


def _table_payload(table: TabularMapTable) -> dict:
    return {"name": table.name, "sheet": table.sheet}


def _row_label_for(
    rows: list[dict], label_column: TabularMapColumn | None, physical_row: int | None
) -> str:
    if label_column is None:
        return ""
    for row in rows:
        if physical_row is not None and int(row.get("physical_row")) != int(physical_row):
            continue
        return str(row.get("values", {}).get(label_column.normalized_name, ""))
    return ""


def _row_value_for(
    rows: list[dict], physical_row: int | None, normalized_column: str
) -> str:
    for row in rows:
        if physical_row is not None and int(row.get("physical_row")) != int(physical_row):
            continue
        return str(row.get("values", {}).get(normalized_column, ""))
    return ""


def _provenance(
    table: TabularMapTable,
    *,
    physical_row: int | None = None,
    cell: str | None = None,
    column: str | None = None,
) -> dict:
    return {
        "workbook": table.workbook,
        "sheet": table.sheet,
        "table": table.name,
        "row": physical_row,
        "cell": cell,
        "column": column,
    }


def _doc_columns(table: TabularMapTable) -> list[TabularMapColumn]:
    """Columnas de documentación (Description/Specifications) para el diccionario."""
    by_semantic = [
        column
        for column in table.columns
        if column.semantic_type in ("description", "free_text")
    ]
    if by_semantic:
        return by_semantic
    hints = ("descrip", "definition", "definicion", "spec", "nota", "comment", "observ")
    return [
        column
        for column in table.columns
        if any(hint in column.normalized_name for hint in hints)
    ]


def _label_specific_enough(label: str, question: str) -> bool:
    """Filtra labels parciales: "Name" no es el sujeto de "Standard Name"."""
    normalized_label = normalize_question(label)
    if len(normalized_label) >= 8:
        return True
    normalized_question = normalize_question(question)
    if not normalized_question:
        return False
    return len(normalized_label) / len(normalized_question) >= 0.2


def _cell_for_row(row: dict, column: TabularMapColumn) -> str | None:
    from src.core.domain.tabular import cell_address

    physical_column = int(column.physical_column or 0)
    if physical_column < 1:
        return None
    return cell_address(int(row.get("physical_row") or 0), physical_column)


def _dictionary_sql(
    table: TabularMapTable,
    label_column: TabularMapColumn | None,
    label: str,
    doc_columns: list[TabularMapColumn],
) -> str:
    label_name = label_column.normalized_name if label_column else "row"
    doc_names = ", ".join(
        f"values->>{_quote(column.normalized_name)} AS {_quote(column.display_name)}"
        for column in doc_columns
    )
    return (
        f"-- zent tabular:{table.sheet}.{table.name}\n"
        f"SELECT values->>{_quote(label_name)} AS field, {doc_names} "
        f"FROM tabular_rows WHERE table_id = {_quote(table.id)} "
        f"AND values->>{_quote(label_name)} = {_quote(label)} LIMIT 1;"
    )


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _lookup_sql(
    table: TabularMapTable,
    *,
    label_column: TabularMapColumn | None,
    row_label: str,
    value_column: TabularMapColumn | None,
    value: str,
) -> str:
    """SQL equivalente (auditoría/UX) del lookup ejecutado en Python."""
    label = label_column.normalized_name if label_column else "row"
    target = value_column.normalized_name if value_column else "value"
    return (
        f"-- zent tabular:{table.sheet}.{table.name}\n"
        f"SELECT values->>{_quote(label)} AS label, values->>{_quote(target)} AS value "
        f"FROM tabular_rows WHERE table_id = {_quote(table.id)} "
        f"AND values->>{_quote(label)} = {_quote(row_label)} LIMIT 1;"
    )


def _count_sql(
    table: TabularMapTable,
    *,
    column: str | None,
    value: str | None,
    numeric: bool,
) -> str:
    where = f"table_id = {_quote(table.id)}"
    if column and value is not None:
        if numeric:
            where += (
                f" AND (values->>{_quote(column)}) ~ '^[+-]?[0-9]+(\\.[0-9]+)?$'"
                f" AND (values->>{_quote(column)})::numeric = {_quote(value)}::numeric"
            )
        else:
            where += f" AND values->>{_quote(column)} = {_quote(value)}"
    return (
        f"-- zent tabular:{table.sheet}.{table.name}\n"
        f"SELECT COUNT(*) FROM tabular_rows WHERE {where};"
    )


def _range_sql(table: TabularMapTable, column: str, low: str, high: str) -> str:
    return (
        f"-- zent tabular:{table.sheet}.{table.name}\n"
        f"SELECT * FROM tabular_rows WHERE table_id = {_quote(table.id)} "
        f"AND (values->>{_quote(column)})::numeric BETWEEN {_quote(low)}::numeric "
        f"AND {_quote(high)}::numeric ORDER BY physical_row;"
    )


def _list_sql(
    table: TabularMapTable, column: str, value: str, numeric: bool
) -> str:
    if numeric:
        where = (
            f"(values->>{_quote(column)}) ~ '^[+-]?[0-9]+(\\.[0-9]+)?$'"
            f" AND (values->>{_quote(column)})::numeric = {_quote(value)}::numeric"
        )
    else:
        where = f"values->>{_quote(column)} = {_quote(value)}"
    return (
        f"-- zent tabular:{table.sheet}.{table.name}\n"
        f"SELECT * FROM tabular_rows WHERE table_id = {_quote(table.id)} "
        f"AND {where} ORDER BY physical_row;"
    )
