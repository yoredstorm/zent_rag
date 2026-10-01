# =============================================================================
# Knowledge Compiler — TEMPORAL UNDERSTANDING
# =============================================================================
# El conocimiento empresarial cambia. La vigencia se extrae de la propia fuente
# (fechas explícitas, etiquetas de versión, ventanas declaradas) y se conserva
# en el hecho. Nunca se inventa una fecha: sin evidencia, la ventana queda
# abierta y el hecho es "vigente y sin versión declarada".
# =============================================================================
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.compiler.model import TemporalScope

_MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
    "jan": 1, "apr": 4, "aug": 8, "dec": 12,
}

_DATE_PATTERNS = (
    re.compile(r"(?P<y>20\d{2})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})"),
    re.compile(r"(?P<d>\d{1,2})[-/](?P<m>\d{1,2})[-/](?P<y>20\d{2})"),
    re.compile(
        r"(?P<d>\d{1,2})\s+(?:de\s+)?(?P<mon>[A-Za-zÁÉÍÓÚáéíóú]{3,10})\.?\s+(?:de\s+)?(?P<y>20\d{2})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?P<mon>[A-Za-zÁÉÍÓÚáéíóú]{3,10})\.?\s+(?P<d>\d{1,2}),?\s+(?P<y>20\d{2})",
        flags=re.IGNORECASE,
    ),
)

_MONTH_YEAR = re.compile(
    r"(?P<mon>[A-Za-zÁÉÍÓÚáéíóú]{3,10})\.?\s+(?:de\s+)?(?P<y>20\d{2})",
    flags=re.IGNORECASE,
)

_FROM_MARKERS = (
    "effective from", "effective since", "valid from", "in effect from",
    "vigente desde", "vigente a partir de", "aplicable desde", "desde el",
    "entra en vigor", "entrada en vigor",
)
_TO_MARKERS = (
    "effective until", "valid until", "in effect until", "superseded on",
    "vigente hasta", "hasta el", "derogado el", "reemplazado el",
    "queda sin efecto",
)
_VERSION_MARKERS = re.compile(
    r"\b(?:rev(?:ision)?\.?|revisi[oó]n|version|versi[oó]n|v|ed\.?|edici[oó]n)\s*"
    r"(?P<label>\d{1,3}(?:\.\d{1,3})*)\b",
    flags=re.IGNORECASE,
)
_SCOPE_MARKERS = re.compile(
    r"\b(?:scope|alcance|ambito|ámbito|aplica a|applies to|para)\s*:?\s*"
    r"(?P<scope>[A-Za-zÁÉÍÓÚáéíóú0-9 _-]{3,80})",
    flags=re.IGNORECASE,
)


def parse_date(text: str) -> date | None:
    """Primera fecha absoluta reconocible del texto. None si no hay evidencia."""
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            try:
                month_raw = groups.get("mon")
                if month_raw:
                    month = _MESES.get(month_raw[:3].lower())
                    if month is None:
                        continue
                else:
                    month = int(groups["m"])
                day = int(groups["d"])
                year = int(groups["y"])
                if not 1 <= month <= 12 or not 1 <= day <= 31:
                    continue
                return date(year, month, day)
            except (TypeError, ValueError):
                continue
    return None


def parse_month(text: str) -> date | None:
    """Primer mes/año del texto, normalizado al día 1 (vigencias declaradas)."""
    if not text:
        return None
    for match in _MONTH_YEAR.finditer(text):
        month = _MESES.get(match.group("mon")[:3].lower())
        if month is None:
            continue
        try:
            return date(int(match.group("y")), month, 1)
        except (TypeError, ValueError):
            continue
    return None


def _window(text: str, markers: tuple[str, ...]) -> date | None:
    lowered = (text or "").lower()
    for marker in markers:
        position = lowered.find(marker)
        if position < 0:
            continue
        fragment = text[position : position + 90]
        found = parse_date(fragment) or parse_month(fragment)
        if found is not None:
            return found
    return None


def infer_version_label(*texts: str) -> str | None:
    for text in texts:
        match = _VERSION_MARKERS.search(text or "")
        if match:
            return match.group("label")
    return None


def infer_scope(text: str) -> str | None:
    match = _SCOPE_MARKERS.search(text or "")
    if match is None:
        return None
    scope = " ".join(match.group("scope").split())
    return scope[:200] or None


def infer_temporal_scope(
    document: StructuredDocument, *, sample_text: str = ""
) -> TemporalScope:
    """Vigencia del documento: ventana declarada + versión + alcance.

    Sin marcadores explícitos la ventana queda abierta: el hecho es "vigente"
    y su versión solo existe si la fuente la declara.
    """
    header = " ".join(
        str(value)
        for value in (
            document.title,
            document.metadata.get("filename"),
            document.metadata.get("version"),
            document.metadata.get("effective_from"),
        )
        if value
    )
    if not sample_text:
        sample_text = "\n".join(
            (block.text or "") for block in document.blocks[:200]
        )[:8000]
    haystack = f"{header}\n{sample_text}"
    return TemporalScope(
        effective_from=_window(haystack, _FROM_MARKERS),
        effective_to=_window(haystack, _TO_MARKERS),
        observed_at=datetime.now(timezone.utc),
        version_label=infer_version_label(header, sample_text)
        or (
            str(document.metadata["version"])
            if document.metadata.get("version")
            else None
        ),
        scope=infer_scope(sample_text),
    )
