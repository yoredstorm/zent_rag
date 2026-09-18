# =============================================================================
# Tabular ingestion — resolución exacta sobre la representación estructurada
# =============================================================================
# Prototipo DETERMINISTA de structured lookup (sin LLM, sin embeddings): dado
# el schema + filas persistidas, responde preguntas de valor exacto:
#   - "¿qué posición tiene Carrier Code?"          → fila por label + columna
#   - "¿qué campo empieza en 30?"                  → fila por valor numérico
#   - "¿cuánto mide Tariff Number?"                → fila + columna length
#
# Es la base del futura Query-Time Routing (§16): el router decidirá cuándo
# usar este camino (structured lookup) y cuándo similarity search. Aquí solo se
# demuestra que la representación estructurada produce la respuesta exacta con
# provenance a fila/columna.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass

# Tokens con dígitos, incluyendo códigos con separadores: 1_100, 6-13, R2, CAT10.
_VALUE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]*\d[A-Za-z0-9_./-]*|\d+")


@dataclass(frozen=True, kw_only=True)
class TabularLookupResult:
    value: str | None = None
    table: str | None = None
    sheet: str | None = None
    physical_row: int | None = None
    column: str | None = None
    source_column: str | None = None
    row_label_column: str | None = None
    cell_address: str | None = None
    confidence: float = 0.0
    strategy: str = "none"
    row_matches: int = 0


def resolve_exact_lookup(
    question: str,
    *,
    table: dict,
    columns: list[dict],
    rows: list[dict],
) -> TabularLookupResult:
    """Lookup determinista de valor exacto sobre filas estructuradas."""
    if not rows or not columns:
        return TabularLookupResult()

    normalized_question = _normalize(question)
    matched_column = _match_column(normalized_question, columns)
    label_columns = _label_columns(columns)

    # Caso A: "… de <label>" (fila por nombre) + columna por semántica/alias.
    row_match = _match_row(normalized_question, rows, label_columns)
    if row_match is not None and matched_column is not None:
        _index, row, label_column, row_matches = row_match
        value = str(row.get("values", {}).get(matched_column["normalized_name"], ""))
        if value != "":
            return _result(
                table=table,
                row=row,
                column=matched_column,
                value=value,
                confidence=0.95,
                strategy="row_label+column",
                row_label_column=label_column.get("original_name")
                or label_column.get("normalized_name"),
                row_matches=row_matches,
            )

    # Caso B: valor exacto en la pregunta (28, 1_100, R2, 6-13) + columna
    # numérica → fila que lo contiene; la respuesta es el label de esa fila.
    search_column = matched_column or (
        _first_numeric_column(columns) if label_columns else None
    )
    if search_column is not None:
        for token in _value_tokens(question):
            row_match = _row_with_value(rows, search_column, token)
            if row_match is None:
                continue
            _index, row = row_match
            if not label_columns:
                break
            label_column = _best_label_for_row(row, label_columns, exclude_value=token)
            if label_column is None:
                break
            label = str(row.get("values", {}).get(label_column["normalized_name"], ""))
            if label:
                return _result(
                    table=table,
                    row=row,
                    column=label_column,
                    value=label,
                    confidence=0.85,
                    strategy="value+label",
                    source_column=search_column.get("original_name")
                    or search_column.get("normalized_name"),
                    row_label_column=label_column.get("original_name")
                    or label_column.get("normalized_name"),
                )
    return TabularLookupResult(table=table.get("name"), sheet=table.get("sheet"))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _result(
    *,
    table,
    row,
    column,
    value,
    confidence,
    strategy,
    source_column: str | None = None,
    row_label_column: str | None = None,
    row_matches: int = 0,
) -> TabularLookupResult:
    physical_row = int(row.get("physical_row"))
    physical_column = int(column.get("physical_column") or 0)
    from src.core.domain.tabular import cell_address

    address = (
        cell_address(physical_row, physical_column) if physical_column >= 1 else None
    )
    return TabularLookupResult(
        value=value,
        table=table.get("name"),
        sheet=table.get("sheet"),
        physical_row=physical_row,
        column=column.get("original_name") or column.get("normalized_name"),
        source_column=source_column,
        row_label_column=row_label_column,
        cell_address=address,
        confidence=confidence,
        strategy=strategy,
        row_matches=row_matches,
    )


def _normalize(value: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", (value or "").lower())
    ascii_value = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def normalize_question(value: str) -> str:
    """Normaliza una pregunta para matching determinista (sin acentos)."""
    return _normalize(value)


def column_match_terms(column: dict) -> list[str]:
    """Términos con los que una columna puede ser mencionada (nombre+aliases+semántica)."""
    return [term for term, _semantic in column_match_terms_with_kind(column)]


def column_match_terms_with_kind(column: dict) -> list[tuple[str, bool]]:
    """(término, es_semántico) para priorizar intención sobre nombre literal."""
    terms: list[tuple[str, bool]] = [
        (column.get("normalized_name", "").replace("_", " "), False)
    ]
    terms.extend(
        (str(alias).replace("_", " "), False)
        for alias in column.get("aliases") or []
    )
    terms.extend(
        (term, True)
        for term in _SEMANTIC_TERMS.get(str(column.get("semantic_type")), ())
    )
    return [(term, semantic) for term, semantic in terms if term]


_SEMANTIC_TERMS: dict[str, tuple[str, ...]] = {
    "length": (
        "length", "long", "how long", "size", "longitud", "mide", "cuanto mide",
        "tamano", "tamaño",
    ),
    "position": (
        "position", "start", "offset", "begins", "starts", "posicion", "posición",
        "empieza", "comienza", "inicia", "ubicacion", "ubicación",
    ),
    "amount": ("price", "cost", "amount", "value", "precio", "costo", "importe", "monto"),
    "quantity": ("quantity", "count", "stock", "cantidad"),
    "date": ("date", "when", "fecha", "cuando", "cuándo"),
    "code": ("code", "key", "codigo", "código"),
    "identifier": ("id", "identifier", "identificador"),
    "description": ("description", "meaning", "what is", "descripcion", "descripción", "significa"),
    "name": ("name", "nombre", "campo"),
    "percentage": ("percentage", "percent", "ratio", "porcentaje"),
    "category": ("category", "type", "group", "categoria", "categoría", "tipo"),
    "boolean": ("flag", "active", "activo"),
}

# Semánticas que expresan la MÉTRICA pedida ("how long", "position"): su match
# gana a los nombres de columnas que solo son la entidad de la pregunta.
_METRIC_SEMANTICS = ("length", "position", "amount", "quantity", "percentage")


def _column_terms(column: dict) -> list[str]:
    terms = [column.get("normalized_name", "").replace("_", " ")]
    terms.extend(str(alias).replace("_", " ") for alias in column.get("aliases") or [])
    terms.extend(_SEMANTIC_TERMS.get(str(column.get("semantic_type")), ()))
    return [term for term in terms if term]


def match_column_payload(
    normalized_question: str, columns: list[dict]
) -> dict | None:
    """Columna mencionada en la pregunta (scoring por clases).

    Clases: métrica semántica ("how long", "position") > nombre/alias literal >
    semántica genérica ("type", "code"). Regla anti-colisión: si el término
    métrico es parte de un nombre más largo ("position" ⊂ "end position"), gana
    el nombre. Así:
      - "How long is Effective and Discontinue Dates?" → Length (métrica)
      - "What is the end position of Tariff Number?" → End Position (nombre)
      - "¿Cuál es la location de Record Type?" → Location (nombre, clase media)
    """
    best_metric: tuple[int, str, dict] | None = None
    best_name: tuple[int, str, dict] | None = None
    best_other: tuple[int, str, dict] | None = None
    for column in columns:
        for term, is_semantic in column_match_terms_with_kind(column):
            normalized_term = _normalize(term)
            if not normalized_term or normalized_term not in normalized_question:
                continue
            length = len(normalized_term)
            if is_semantic and str(column.get("semantic_type")) in _METRIC_SEMANTICS:
                if best_metric is None or length > best_metric[0]:
                    best_metric = (length, normalized_term, column)
            elif not is_semantic:
                if best_name is None or length > best_name[0]:
                    best_name = (length, normalized_term, column)
            elif best_other is None or length > best_other[0]:
                best_other = (length, normalized_term, column)
    if best_metric is not None:
        if best_name is not None and best_metric[1] in best_name[1]:
            return best_name[2]
        return best_metric[2]
    if best_name is not None:
        return best_name[2]
    return best_other[2] if best_other else None


def _match_column(normalized_question: str, columns: list[dict]) -> dict | None:
    return match_column_payload(normalized_question, columns)


def _label_column(columns: list[dict]) -> dict | None:
    candidates = _label_columns(columns)
    return candidates[0] if candidates else None


def _label_columns(columns: list[dict]) -> list[dict]:
    """Columnas candidatas a identificar la fila, en orden de preferencia.

    Un Excel real puede tener varias columnas "nombre" (p. ej. Standard Name y
    Field Name): se prueban todas y gana la que matchee el label de la pregunta.
    NUNCA se usan columnas de posición/medida como label (sus números aparecen
    en la pregunta y producirían matches falsos).
    """
    ordered: list[dict] = []
    for semantic in ("name", "identifier", "code", "reference"):
        for column in columns:
            if column.get("semantic_type") == semantic and column not in ordered:
                ordered.append(column)
    if not ordered:
        ordered = [
            column
            for column in columns
            if column.get("inferred_type") == "string"
        ][:2]
    return ordered[:6]


def _first_numeric_column(columns: list[dict]) -> dict | None:
    for column in columns:
        if column.get("inferred_type") in ("integer", "float", "decimal"):
            return column
    return None


def find_label_row(
    question: str, rows: list[dict], label_columns: list[dict]
) -> tuple[int, dict, dict, int] | None:
    """Fila cuyo label aparece en la pregunta; gana el label MÁS LARGO.

    Expuesto para que el servicio pueda paginar filas y quedarse con el mejor
    match global (tablas grandes: el label puede estar más allá de la página 1).
    """
    return _match_row(_normalize(question), rows, label_columns)


def _match_row(
    normalized_question: str, rows: list[dict], label_columns: list[dict]
) -> tuple[int, dict, dict, int] | None:
    """Fila cuyo label aparece en la pregunta; gana el label MÁS LARGO.

    Antes ganaba la primera fila en orden físico: "Carrier" (fila temprana) le
    ganaba a "Carrier Code" (fila 5775). Con scoring por longitud gana la
    mención más específica; `row_matches` cuenta cuántas filas comparten label.
    """
    best: tuple[int, int, int, dict, dict] | None = None
    label_counts: dict[tuple[str, str], int] = {}
    for label_column in label_columns:
        key = label_column.get("normalized_name")
        if not key:
            continue
        for index, row in enumerate(rows):
            label = _normalize(str(row.get("values", {}).get(key, "")))
            if (
                not label
                or len(label) < 3
                or not any(char.isalpha() for char in label)
                or label not in normalized_question
            ):
                continue
            label_counts[(key, label)] = label_counts.get((key, label), 0) + 1
            score = (len(label), -index)
            if best is None or score > (best[0], best[1]):
                best = (len(label), -index, index, row, label_column)
    if best is None:
        return None
    _length, _neg_index, index, row, label_column = best
    key = label_column.get("normalized_name")
    label = _normalize(str(row.get("values", {}).get(key, "")))
    matches = label_counts.get((key, label), 1)
    return index, row, label_column, matches


def _value_tokens(question: str) -> list[str]:
    """Tokens con dígitos de la pregunta (28, 1_100, R2, 6-13), largos primero."""
    tokens: list[str] = []
    for match in _VALUE_TOKEN_RE.finditer(question or ""):
        token = match.group(0)
        if token and token not in tokens:
            tokens.append(token)
    tokens.sort(key=len, reverse=True)
    return tokens[:8]


def _row_with_value(
    rows: list[dict], column: dict, token: str
) -> tuple[int, dict] | None:
    """Primera fila cuyo valor en la columna coincide con el token.

    Compara raw y normalizado (1_100 == 1.100 == 1 100) sin destruir el valor
    original que se responde.
    """
    key = column.get("normalized_name")
    if not key:
        return None
    wanted = token.strip().lower()
    wanted_normalized = _normalize(wanted)
    for index, row in enumerate(rows):
        value = str(row.get("values", {}).get(key, "")).strip()
        if not value:
            continue
        if value.lower() == wanted or _normalize(value) == wanted_normalized:
            return index, row
    return None


def _best_label_for_row(
    row: dict, label_columns: list[dict], *, exclude_value: str
) -> dict | None:
    """Columna label más razonable para una fila (no repite el valor buscado)."""
    excluded = exclude_value.strip().lower()
    fallback: dict | None = None
    for column in label_columns:
        value = str(row.get("values", {}).get(column.get("normalized_name"), "")).strip()
        if not value or value.lower() == excluded:
            continue
        if fallback is None:
            fallback = column
        if column.get("semantic_type") in ("name", "identifier", "code"):
            return column
    return fallback
