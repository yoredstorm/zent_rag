# =============================================================================
# Tabular ingestion — inferencia determinista de tipos y semántica de columnas
# =============================================================================
# Sin LLM: patrones + estadística ligera sobre muestras. Cada inferencia lleva
# confidence y TODO se calcula sobre los valores exactos (nunca se normaliza
# destruyendo códigos: raw_value y normalized_value conviven).
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from src.core.domain.tabular import TabularSemanticType, TabularValueType

# ---------------------------------------------------------------------------
# Patrones
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?\d{1,18}$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)[.,]\d+$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$")
_DMY_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})(?:[ T](\d{2}):(\d{2}))?$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
_BOOL_VALUES = {
    "true", "false", "yes", "no", "si", "sí", "s", "n", "y", "t", "f",
    "verdadero", "falso", "activo", "inactivo",
}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_URL_RE = re.compile(r"^(?:https?|ftp)://[^\s]+$", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"^[^\d\s]{0,3}\s?\d[\d.,\s]*$")
_PERCENT_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?\s?%$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/&#*!+-]{0,23}$")
_ERROR_VALUES = {
    "#ref!", "#div/0!", "#n/a", "#value!", "#name?", "#null!", "#num!", "#getting_data",
}
_LEADING_ZERO_RE = re.compile(r"^0\d+$")

_SAMPLE_LIMIT = 200


@dataclass(frozen=True, kw_only=True)
class ColumnProfile:
    """Estadísticas ligeras de una columna (sin guardar todos los valores)."""

    non_empty: int = 0
    empty: int = 0
    distinct: int = 0
    inferred_type: TabularValueType = TabularValueType.UNKNOWN
    type_confidence: float = 0.0
    mixed_values: tuple[str, ...] = ()
    error_values: tuple[str, ...] = ()
    malformed_dates: tuple[str, ...] = ()
    samples: tuple[str, ...] = ()
    numeric_ratio: float = 0.0
    date_ratio: float = 0.0
    text_ratio: float = 0.0
    max_length: int = 0
    metadata: dict = field(default_factory=dict)

    @property
    def null_ratio(self) -> float:
        total = self.non_empty + self.empty
        return (self.empty / total) if total else 0.0

    @property
    def unique_ratio(self) -> float:
        return (self.distinct / self.non_empty) if self.non_empty else 0.0


def profile_values(values: list[str], *, sample_limit: int = _SAMPLE_LIMIT) -> ColumnProfile:
    """Perfila los valores de UNA columna (lista alineada a las filas de datos)."""
    non_empty: list[str] = []
    empty = 0
    distinct: set[str] = set()
    for value in values:
        if value is None or value == "":
            empty += 1
            continue
        non_empty.append(value)
        distinct.add(value)

    if not non_empty:
        return ColumnProfile(empty=empty, inferred_type=TabularValueType.UNKNOWN)

    samples = _even_samples(non_empty, sample_limit)
    type_counts: dict[TabularValueType, int] = {}
    mixed: list[str] = []
    errors: list[str] = []
    malformed_dates: list[str] = []
    max_length = 0
    for value in samples:
        max_length = max(max_length, len(value))
        lowered = value.strip().lower()
        if lowered in _ERROR_VALUES:
            errors.append(value)
            continue
        value_type = classify_value(value)
        type_counts[value_type] = type_counts.get(value_type, 0) + 1
        if value_type is TabularValueType.MIXED:
            mixed.append(value)

    dominant, dominant_count = max(type_counts.items(), key=lambda item: item[1])
    confidence = dominant_count / max(1, len(samples))
    if dominant is not TabularValueType.MIXED and confidence < 0.9:
        # Un 10-25% de valores fuera de tipo no convierte la columna en mixta,
        # pero baja la confianza y se registra como valor anómalo.
        dominant_values = [
            value for value in samples if classify_value(value) is dominant
        ]
        mixed = [value for value in samples if classify_value(value) is not dominant][:5]
        if dominant in (TabularValueType.DATE, TabularValueType.DATETIME):
            malformed_dates = mixed
        if not dominant_values:  # pragma: no cover - defensivo
            dominant = TabularValueType.MIXED

    errors = list(dict.fromkeys(errors))[:5]
    numeric = sum(
        count
        for value_type, count in type_counts.items()
        if value_type
        in (
            TabularValueType.INTEGER,
            TabularValueType.FLOAT,
            TabularValueType.DECIMAL,
            TabularValueType.CURRENCY,
            TabularValueType.PERCENTAGE,
        )
    )
    dates = sum(
        count
        for value_type, count in type_counts.items()
        if value_type in (TabularValueType.DATE, TabularValueType.DATETIME, TabularValueType.TIME)
    )
    text_types = (
        TabularValueType.STRING,
        TabularValueType.CODE,
        TabularValueType.IDENTIFIER,
        TabularValueType.URL,
        TabularValueType.EMAIL,
        TabularValueType.MIXED,
    )
    text = sum(count for value_type, count in type_counts.items() if value_type in text_types)

    return ColumnProfile(
        non_empty=len(non_empty),
        empty=empty,
        distinct=len(distinct),
        inferred_type=dominant,
        type_confidence=round(confidence, 3),
        mixed_values=tuple(mixed[:5]),
        error_values=tuple(errors),
        malformed_dates=tuple(malformed_dates[:5]),
        samples=tuple(_even_samples(non_empty, 8)),
        numeric_ratio=round(numeric / max(1, len(samples)), 3),
        date_ratio=round(dates / max(1, len(samples)), 3),
        text_ratio=round(text / max(1, len(samples)), 3),
        max_length=max_length,
        metadata={"sampled": len(samples)},
    )


@lru_cache(maxsize=4096)
def classify_value(value: str) -> TabularValueType:
    """Clasifica un valor individual (prioridad: error/especial > número > fecha).

    Cacheado: los workbooks reales repiten miles de valores (categorías,
    flags, códigos) y la clasificación usa varias regex.
    """
    text = value.strip()
    if not text:
        return TabularValueType.UNKNOWN
    lowered = text.lower()
    if lowered in _ERROR_VALUES:
        return TabularValueType.STRING
    if lowered in _BOOL_VALUES and lowered not in {"0", "1"}:
        return TabularValueType.BOOLEAN
    if _PERCENT_RE.match(text):
        return TabularValueType.PERCENTAGE
    if _EMAIL_RE.match(text):
        return TabularValueType.EMAIL
    if _URL_RE.match(text):
        return TabularValueType.URL
    if _ISO_DATE_RE.match(text):
        return TabularValueType.DATE if " " not in text and "T" not in text else TabularValueType.DATETIME
    if _TIME_RE.match(text):
        return TabularValueType.TIME
    if _DMY_RE.match(text):
        return TabularValueType.DATE
    # Moneda: símbolo antes de número (€, $, S/, USD 10, ...)
    if _looks_currency(text):
        return TabularValueType.CURRENCY
    if _INT_RE.match(text):
        if _LEADING_ZERO_RE.match(text):
            return TabularValueType.CODE
        return TabularValueType.INTEGER
    if _FLOAT_RE.match(text):
        return TabularValueType.FLOAT
    if _looks_identifier(text):
        return TabularValueType.IDENTIFIER
    if _looks_code(text):
        return TabularValueType.CODE
    if any(char.isdigit() for char in text) and any(char.isalpha() for char in text):
        return TabularValueType.STRING
    return TabularValueType.STRING


# ---------------------------------------------------------------------------
# Semántica de columnas
# ---------------------------------------------------------------------------

# (claves, tipo semántico, alias). El orden importa: primero los más específicos.
_SEMANTIC_RULES: tuple[tuple[tuple[str, ...], TabularSemanticType, tuple[str, ...]], ...] = (
    (
        ("start position", "start pos", "startpos", "start offset", "byte position", "from position", "begin position"),
        TabularSemanticType.POSITION,
        ("position", "start", "start_position", "starting position", "begin"),
    ),
    (
        ("end position", "end pos", "endpos", "end offset", "to position"),
        TabularSemanticType.POSITION,
        ("position", "end", "end_position", "ending position"),
    ),
    (
        ("position", "posicion", "posición", "pos ", "offset", "byte", "bit", "start", "end", "inicio", "fin"),
        TabularSemanticType.POSITION,
        ("position", "start", "offset"),
    ),
    (
        ("length", "longitud", "len ", "size", "largo", "width"),
        TabularSemanticType.LENGTH,
        ("length", "size", "len"),
    ),
    (
        (
            "description", "descripcion", "descripción", "definition",
            "definicion", "meaning", "significado", "comment", "observacion",
            "observación", "notes", "nota",
        ),
        TabularSemanticType.DESCRIPTION,
        ("description", "definition", "notes"),
    ),
    (
        ("field name", "fieldname", "nombre", "name", "label", "etiqueta", "title", "titulo", "título"),
        TabularSemanticType.NAME,
        ("name", "field", "label"),
    ),
    (
        ("carrier code", "code", "codigo", "código", "cod ", "fclass", "tarno", "sku", "clave", "key"),
        TabularSemanticType.CODE,
        ("code", "identifier", "key"),
    ),
    (
        ("identifier", "id ", " id", "uuid", "guid", "record id", "primary key", "foreign key"),
        TabularSemanticType.IDENTIFIER,
        ("id", "identifier", "key"),
    ),
    (
        ("quantity", "cantidad", "qty", "count", "conteo", "units", "unidades", "stock"),
        TabularSemanticType.QUANTITY,
        ("quantity", "count", "stock"),
    ),
    (
        (
            "amount", "importe", "monto", "precio", "price", "cost", "costo",
            "fare", "tarifa", "valor", "value", "revenue",
        ),
        TabularSemanticType.AMOUNT,
        ("amount", "price", "value"),
    ),
    (
        ("percentage", "porcentaje", "percent", "pct", "ratio", "tasa", "rate"),
        TabularSemanticType.PERCENTAGE,
        ("percentage", "percent", "ratio"),
    ),
    (
        ("date", "fecha", "effective", "vigencia", "valid from", "valid to", "expiry", "vencimiento"),
        TabularSemanticType.DATE,
        ("date", "effective", "validity"),
    ),
    (
        ("flag", "boolean", "activo", "active", "enabled", "is "),
        TabularSemanticType.BOOLEAN,
        ("flag", "boolean"),
    ),
    (
        ("category", "categoria", "categoría", "type", "tipo", "group", "grupo", "class", "clase", "status", "estado"),
        TabularSemanticType.CATEGORY,
        ("category", "type", "group"),
    ),
    (
        ("reference", "referencia", "ref ", "rel ", "related", "parent", "child", "lookup"),
        TabularSemanticType.REFERENCE,
        ("reference", "related"),
    ),
)


def infer_semantic_type(
    header: str,
    *,
    value_type: TabularValueType = TabularValueType.UNKNOWN,
    max_length: int = 0,
) -> tuple[TabularSemanticType, float, tuple[str, ...]]:
    """(semantic_type, confidence, aliases) determinista a partir del header."""
    normalized = " " + normalize_name(header).replace("_", " ") + " "
    raw = " " + (header or "").strip().lower() + " "
    tokens = {token for token in normalize_name(header).split("_") if token}

    conditional = _conditional_semantic(
        header, value_type=value_type, max_length=max_length
    )
    if conditional is not None:
        return conditional

    for keys, semantic, aliases in _SEMANTIC_RULES:
        for key in keys:
            candidate = key.strip()
            if not candidate:
                continue
            if " " in candidate:
                if candidate in normalized or candidate in raw:
                    matched = True
                else:
                    continue
            else:
                matched = candidate in tokens or (
                    len(candidate) >= 4
                    and any(token.startswith(candidate) for token in tokens)
                )
            if matched:
                confidence = 0.85 if " " in candidate else 0.7
                if semantic is TabularSemanticType.POSITION and value_type in (
                    TabularValueType.INTEGER,
                    TabularValueType.FLOAT,
                ):
                    confidence = min(0.95, confidence + 0.1)
                return semantic, confidence, aliases
    if value_type in (TabularValueType.STRING, TabularValueType.MIXED) and max_length > 60:
        return TabularSemanticType.FREE_TEXT, 0.6, ("text", "notes")
    if value_type in (TabularValueType.DATE, TabularValueType.DATETIME):
        return TabularSemanticType.DATE, 0.6, ("date",)
    if value_type in (TabularValueType.INTEGER, TabularValueType.FLOAT, TabularValueType.CURRENCY):
        return TabularSemanticType.UNKNOWN, 0.3, ()
    return TabularSemanticType.UNKNOWN, 0.2, ()


def header_aliases(header: str) -> tuple[str, ...]:
    """Aliases genéricos derivados del nombre (sin LLM)."""
    normalized = normalize_name(header)
    if not normalized:
        return ()
    tokens = [token for token in normalized.split("_") if token and token not in _STOPWORDS]
    aliases = {normalized, normalized.replace("_", " ")}
    if tokens:
        aliases.add(tokens[-1])
        aliases.add(" ".join(tokens))
        for token in tokens:
            if len(token) > 3:
                aliases.add(token)
    if normalized.endswith("_code"):
        aliases.add("code")
    if normalized.endswith("_name"):
        aliases.add("name")
    if normalized.endswith("_id"):
        aliases.add("id")
    aliases.discard("")
    return tuple(sorted(aliases - {header.strip().lower()}))


_STOPWORDS = {"de", "del", "la", "el", "los", "las", "the", "of", "for", "y", "and", "to"}


def _key_matches(
    candidate: str, normalized: str, raw: str, tokens: set[str]
) -> bool:
    """Match de una clave contra el nombre: frase exacta o token completo."""
    candidate = candidate.strip()
    if not candidate:
        return False
    if " " in candidate:
        return candidate in normalized or candidate in raw
    return candidate in tokens or (
        len(candidate) >= 4
        and any(token.startswith(candidate) for token in tokens)
    )


def _conditional_semantic(
    header: str,
    *,
    value_type: TabularValueType,
    max_length: int,
) -> tuple[TabularSemanticType, float, tuple[str, ...]] | None:
    """Reglas por nombre + tipo de valor (evitan falsos positivos).

    Ej.: "Location" con enteros es una posición de bytes; con texto es una
    referencia (ciudad/sede). "Required" solo es booleano si sus valores lo son.
    """
    normalized = " " + normalize_name(header).replace("_", " ") + " "
    raw = " " + (header or "").strip().lower() + " "
    tokens = {token for token in normalize_name(header).split("_") if token}
    numeric = value_type in (
        TabularValueType.INTEGER,
        TabularValueType.FLOAT,
        TabularValueType.DECIMAL,
        TabularValueType.CURRENCY,
    )

    if _key_matches("data row", normalized, raw, tokens) or _key_matches(
        "item row", normalized, raw, tokens
    ) or _key_matches("row no", normalized, raw, tokens) or _key_matches(
        "row number", normalized, raw, tokens
    ) or _key_matches("nro", normalized, raw, tokens) or _key_matches(
        "std", normalized, raw, tokens
    ):
        if numeric or value_type in (TabularValueType.CODE, TabularValueType.IDENTIFIER):
            return TabularSemanticType.IDENTIFIER, 0.75, ("row", "identifier")

    if _key_matches("location", normalized, raw, tokens) or _key_matches(
        "loc", normalized, raw, tokens
    ) or _key_matches("ubicacion", normalized, raw, tokens):
        if numeric:
            return TabularSemanticType.POSITION, 0.8, ("position", "location")
        return TabularSemanticType.REFERENCE, 0.5, ("location",)

    if _key_matches("required", normalized, raw, tokens) or _key_matches(
        "requerido", normalized, raw, tokens
    ) or _key_matches("obligatorio", normalized, raw, tokens):
        if value_type is TabularValueType.BOOLEAN:
            return TabularSemanticType.BOOLEAN, 0.8, ("required", "boolean")

    if _key_matches("area", normalized, raw, tokens):
        return TabularSemanticType.CATEGORY, 0.6, ("category", "area")

    if _key_matches("action", normalized, raw, tokens) or _key_matches(
        "accion", normalized, raw, tokens
    ):
        if max_length <= 24:
            return TabularSemanticType.CODE, 0.6, ("code", "action")

    if _key_matches("layout", normalized, raw, tokens) or _key_matches(
        "lay out", normalized, raw, tokens
    ):
        if max_length <= 16:
            return TabularSemanticType.CATEGORY, 0.55, ("category", "layout")

    return None


def normalize_name(value: str) -> str:
    """snake_case ascii determinista (no destructivo: es solo un índice)."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).strip().lower())
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")
    return cleaned[:120]


def is_probable_header_row(values: tuple[str, ...] | list[str]) -> bool:
    """Heurística barata: fila de encabezado vs fila de datos.

    No exige encabezados únicos: los archivos reales repiten nombres de columna
    (p. ej. "Data Row" dos veces). La unicidad es una señal suave, no un veto.
    """
    non_empty = [value.strip() for value in values if value and value.strip()]
    if len(non_empty) < 1:
        return False
    text_like = sum(
        1
        for value in non_empty
        if classify_value(value)
        in (
            TabularValueType.STRING,
            TabularValueType.CODE,
            TabularValueType.IDENTIFIER,
        )
    )
    short = sum(1 for value in non_empty if len(value) <= 60)
    return (
        text_like / len(non_empty) >= 0.6
        and short / len(non_empty) >= 0.8
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _looks_currency(text: str) -> bool:
    if _PERCENT_RE.match(text):
        return False
    return bool(_CURRENCY_RE.match(text)) and any(
        symbol in text for symbol in ("€", "$", "£", "¥", "S/", "USD", "EUR", "MXN", "COP", "ARS", "CLP", "PEN")
    )


def _looks_identifier(text: str) -> bool:
    digits = sum(1 for char in text if char.isdigit())
    if digits < 4:
        return False
    if not all(char.isalnum() or char in "-_./" for char in text):
        return False
    return len(text) <= 64 and not any(char.isspace() for char in text)


def _looks_code(text: str) -> bool:
    if len(text) > 32 or not text:
        return False
    if " " in text and len(text) <= 24:
        # "R&&&&&E&" no tiene espacios; "CAT 14" sí: aceptar una palabra corta
        parts = text.split()
        if len(parts) <= 2 and all(part.isalnum() for part in parts if part):
            return bool(re.search(r"[A-Za-z]", text)) and bool(re.search(r"\d", text))
        return False
    if not _CODE_RE.match(text):
        return False
    has_alpha = any(char.isalpha() for char in text)
    has_digit = any(char.isdigit() for char in text)
    has_symbol = any(not char.isalnum() for char in text)
    return (has_alpha and has_digit) or (has_alpha and has_symbol) or (
        has_symbol and has_digit
    )


def _even_samples(values: list[str], limit: int) -> list[str]:
    if len(values) <= limit:
        return list(values)
    stride = len(values) / limit
    return [values[min(int(index * stride), len(values) - 1)] for index in range(limit)]
