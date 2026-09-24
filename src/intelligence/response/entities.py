# =============================================================================
# Entidades de la pregunta y cobertura REAL de la evidencia.
# =============================================================================
# Determinista y barato: qué pidió el usuario («categoría 31», «byte 105»,
# «record 4», «tabla 961», «campo X») y si la evidencia consultada lo menciona.
#
# Es un DATO (regex + contención de texto), no una inferencia: sirve para que el
# generador no rellene de memoria lo que la evidencia no cubre, y para que el
# agente pueda volver a buscar con una consulta mejor.
# =============================================================================
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_ENTITIES = 4

#: Palabra clave → patrón que captura el identificador pedido.
#: `categor\w{0,6}` tolera la escritura real del usuario (categoría, categorria,
#: category): el objetivo es reconocer lo que se pregunta, no corregir ortografía.
_ENTITY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("categoría", r"\b(?:categor\w{0,6}|cat)[\s._-]*(\d{1,3})\b"),
    ("byte", r"\bbytes?[\s._-]*(\d{1,3})\b"),
    ("record", r"\b(?:records?|registros?)[\s._-]*(\d{1,2})\b"),
    ("tabla", r"\b(?:tablas?|tables?|tbl)[\s._-]*(\d{1,4})\b"),
    ("campo", r"\bcampos?\s+((?:[\wÁÉÍÓÚÑáéíóúñ][\w.-]{1,24})(?:\s+[\wÁÉÍÓÚÑáéíóúñ][\w.-]{0,24}){0,2})"),
)

#: Nombres genéricos que no son una entidad («campo de la tabla»).
_CAMPO_STOPWORDS = frozenset(
    {"de", "del", "la", "el", "los", "las", "un", "una", "en", "para", "con", "que"}
)

#: Palabras que, si aparecen, permiten aceptar el número suelto como cobertura.
_NUMERIC_CONTEXT: dict[str, tuple[str, ...]] = {
    "categoría": ("categoria", "category", "cat"),
    "byte": ("byte",),
    "record": ("record", "registro"),
    "tabla": ("tabla", "table", "tbl"),
}


@dataclass(frozen=True)
class AskedEntity:
    """Entidad concreta pedida en la pregunta, con sus formas equivalentes."""

    kind: str
    value: str
    label: str
    variants: tuple[str, ...]

    def to_public_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value, "label": self.label}


def normalize(text: str) -> str:
    """Minúsculas, sin acentos y con separadores unificados."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    plain = plain.lower()
    plain = re.sub(r"[._/\\-]+", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


def _trim_campo(value: str) -> str:
    """Nombre del campo sin palabras vacías al final («Fare Basis del» → «Fare Basis»)."""
    tokens = [token for token in value.split() if token]
    while tokens and tokens[-1].lower() in _CAMPO_STOPWORDS:
        tokens.pop()
    if not tokens or tokens[0].lower() in _CAMPO_STOPWORDS:
        return ""
    return " ".join(tokens[:3])


def _variants(kind: str, value: str) -> tuple[str, ...]:
    if kind == "categoría":
        forms = [f"cat {value}", f"cat{value}", f"categoria {value}", f"category {value}"]
    elif kind == "byte":
        forms = [f"byte {value}", f"byte{value}", f"bytes {value}"]
    elif kind == "record":
        forms = [f"record {value}", f"registro {value}"]
    elif kind == "tabla":
        forms = [f"tabla {value}", f"table {value}", f"tbl {value}", f"tbl{value}"]
    else:  # campo / field: el nombre en sí es la señal
        forms = [f"campo {value}", f"field {value}", value]
    return tuple(dict.fromkeys(normalize(form) for form in forms if form.strip()))


def asked_entities(question: str) -> list[AskedEntity]:
    """Entidades concretas de la pregunta, en orden de aparición y sin repetir."""
    text = question or ""
    found: list[AskedEntity] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _ENTITY_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = (match.group(1) or "").strip()
            if kind == "campo":
                value = _trim_campo(value)
            if not value:
                continue
            key = (kind, value.lower())
            if key in seen:
                continue
            seen.add(key)
            label = f"{kind} {value}"
            found.append(
                AskedEntity(
                    kind=kind,
                    value=value,
                    label=label,
                    variants=_variants(kind, value),
                )
            )
            if len(found) >= MAX_ENTITIES:
                return found
    return found


def entity_covered(entity: AskedEntity, evidence_text: str) -> bool:
    """¿La evidencia menciona esta entidad? Es contención de texto, no opinión."""
    haystack = normalize(evidence_text)
    if not haystack:
        return False
    if any(variant and variant in haystack for variant in entity.variants):
        return True
    # El número suelto cuenta sólo si la evidencia habla del tipo de dato
    # (una tabla de bytes cubre "byte 105" aunque no repita la palabra pegada).
    context = _NUMERIC_CONTEXT.get(entity.kind, ())
    if context and any(word in haystack for word in context):
        return re.search(rf"\b{re.escape(entity.value)}\b", haystack) is not None
    return False


def uncovered_entities(question: str, evidence_text: str) -> list[AskedEntity]:
    """Entidades pedidas que la evidencia NO menciona."""
    return [
        entity
        for entity in asked_entities(question)
        if not entity_covered(entity, evidence_text)
    ]


def coverage_note(question: str, evidence_text: str) -> str:
    """Bloque factual para el generador. Vacío cuando todo está cubierto.

    No pide nada que no sea verificable: dice qué falta y qué hacer con eso.
    """
    missing = uncovered_entities(question, evidence_text)
    if not missing:
        return ""
    labels = ", ".join(entity.label for entity in missing)
    return (
        "## COBERTURA DE LA EVIDENCIA (dato, no instrucción)\n"
        f"La evidencia consultada no menciona: {labels}.\n"
        "No lo expliques de memoria: decí que no está en la documentación "
        "consultada y qué fuente haría falta. Nada de cifras, porcentajes, "
        "subcategorías ni ejemplos que la evidencia no sostenga."
    )


# -----------------------------------------------------------------------------
# Fechas y años: verificación determinista contra la evidencia
# -----------------------------------------------------------------------------
# Un número inventado es el error más caro y el más difícil de detectar leyendo:
# «a partir del 12 de julio de 2026» cuando la fuente dice «10 July 2024». Acá no
# se opina sobre el texto: se compara lo que la respuesta AFIRMA con lo que la
# evidencia CONTIENE, y se devuelve la lista de referencias sin respaldo.
_MONTHS: dict[str, int] = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"(?:19|20)\d{2}"

#: Cada patrón viene con el orden de sus grupos: "dmy", "mdy" o "ymd".
_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"\b(\d{{1,2}})\s*(?:de\s+)?({_MONTH_ALT})\.?\s*(?:de\s+|,\s*|\s+)({_YEAR})\b", re.I), "dmy"),
    (re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+({_YEAR})\b", re.I), "mdy"),
    (re.compile(rf"\b({_YEAR})-(\d{{1,2}})-(\d{{1,2}})\b"), "ymd"),
    (re.compile(rf"\b(\d{{1,2}})/(\d{{1,2}})/({_YEAR})\b"), "dmy"),
    (re.compile(rf"\b(\d{{1,2}})-(\d{{1,2}})-({_YEAR})\b"), "dmy"),
)


@dataclass(frozen=True)
class StatedDate:
    """Fecha concreta afirmada en un texto, con su forma canónica comparable."""

    canonical: str
    original: str
    span: tuple[int, int]


def _date_parts(match: re.Match[str], order: str) -> tuple[int, int, int] | None:
    """(día, mes, año) del match, o None si no es una fecha válida."""
    groups = match.groups()
    try:
        if order == "ymd":
            year, month, day = (
                int(groups[0]),
                int(groups[1]),
                int(groups[2]),
            )
        elif order == "mdy":
            month = _MONTHS[groups[0].lower().rstrip(".")]
            day, year = int(groups[1]), int(groups[2])
        else:
            day = int(groups[0])
            month = _MONTHS[groups[1].lower().rstrip(".")]
            year = int(groups[2])
    except (KeyError, ValueError, IndexError):
        return None
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return day, month, year


def stated_dates(text: str) -> list[StatedDate]:
    """Fechas completas (día + mes + año) del texto, sin repetir."""
    found: list[StatedDate] = []
    seen: set[str] = set()
    for pattern, order in _DATE_PATTERNS:
        for match in pattern.finditer(text or ""):
            parts = _date_parts(match, order)
            if parts is None:
                continue
            day, month, year = parts
            canonical = f"{year:04d}-{month:02d}-{day:02d}"
            if canonical in seen:
                continue
            seen.add(canonical)
            found.append(StatedDate(canonical, match.group(0).strip(), match.span()))
    return sorted(found, key=lambda item: item.span[0])


def ungrounded_figures(
    answer: str,
    evidence_text: str,
    question: str = "",
) -> list[str]:
    """Fechas y años que la respuesta afirma y la evidencia (ni la pregunta) contiene.

    Devuelve las formas tal como las escribió la respuesta, para poder citarlas en
    el pedido de corrección. Vacío = todo lo afirmado tiene respaldo.
    """
    allowed_text = f"{evidence_text or ''}\n{question or ''}"
    allowed_dates = {item.canonical for item in stated_dates(allowed_text)}
    allowed_years = set(re.findall(_YEAR, allowed_text))

    flagged: list[str] = []
    flagged_spans: list[tuple[int, int]] = []
    for item in stated_dates(answer or ""):
        if item.canonical in allowed_dates:
            continue
        flagged.append(item.original)
        flagged_spans.append(item.span)

    for match in re.finditer(_YEAR, answer or ""):
        year = match.group(0)
        if year in allowed_years:
            continue
        if any(start <= match.start() < end for start, end in flagged_spans):
            continue
        flagged.append(year)

    return list(dict.fromkeys(flagged))


def figures_note(figures: list[str]) -> str:
    """Pedido de corrección determinista para figuras sin respaldo."""
    if not figures:
        return ""
    listed = ", ".join(figures[:5])
    return (
        f"La evidencia consultada no contiene: {listed}. "
        "No afirmes fechas, años ni cifras que no estén en la evidencia, ni los "
        "aproximimes: si el valor no está, decí que no está en la documentación "
        "consultada; si está, repetí el valor exacto de la fuente."
    )


__all__ = [
    "MAX_ENTITIES",
    "AskedEntity",
    "StatedDate",
    "asked_entities",
    "coverage_note",
    "entity_covered",
    "figures_note",
    "normalize",
    "stated_dates",
    "uncovered_entities",
    "ungrounded_figures",
]
