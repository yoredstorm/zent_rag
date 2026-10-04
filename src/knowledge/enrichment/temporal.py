# =============================================================================
# Enrichment — qualifiers temporales
# =============================================================================
# Detecta fechas, rangos y vigencias con patrón determinista. NUNCA crea
# temporal assertions canónicas: eso es del compilador con evidencia. Si una
# fecha es ambigua (01/02/2024) se marca `ambiguous=True` en vez de decidir.
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.enrichment.contracts import TemporalQualifier
from src.knowledge.enrichment.profiling import EnrichmentContext
from src.knowledge.enrichment.versioning import POLICY_VERSION

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_DOTTED_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")
_MONTH_NAME = re.compile(
    r"\b(\d{1,2})\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{4})\b",
    re.IGNORECASE,
)
_RANGE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2})\s*(?:to|a|hasta|through|-|–)\s*(\d{4}-\d{2}-\d{2})\b"
)
_VALIDITY = re.compile(
    r"\b(effective(?:\s+from)?|valid(?:\s+from)?|vigente(?:\s+desde)?|"
    r"v[aá]lido(?:\s+desde)?|as\s+of|a\s+partir\s+de|desde|hasta)\b"
    r"[:\s]+([0-9A-Za-z/\-\. ]{4,32})",
    re.IGNORECASE,
)
_COMPACT_DATE = re.compile(r"\b(\d{4})(\d{2})(\d{2})\b")
_DATE_HINT = re.compile(
    r"(fecha|date|effective|vigencia|v[aá]lido|period|per[ií]odo|yyyymmdd)", re.IGNORECASE
)


def _ambiguous(day: int, month: int) -> bool:
    return day <= 12 and month <= 12


def build_temporal_qualifiers(
    context: EnrichmentContext,
    *,
    max_total: int = 200,
) -> tuple[TemporalQualifier, ...]:
    found: dict[str, TemporalQualifier] = {}

    def add(
        value: str,
        *,
        units: tuple[str, ...],
        kind: str,
        normalized: str | None = None,
        ambiguous: bool = False,
        confidence: float = 0.8,
    ) -> None:
        cleaned = " ".join(str(value or "").split())
        if not cleaned or not units:
            return
        key = cleaned.casefold()
        if key in found:
            return
        found[key] = TemporalQualifier(
            value=cleaned,
            qualifier_type=kind,
            normalized_value=normalized,
            ambiguous=ambiguous,
            source_unit_ids=units,
            confidence=max(0.0, min(1.0, confidence)),
            derivation_method="deterministic",
            policy_version=POLICY_VERSION,
        )

    for block in context.document.blocks:
        text = block.text or ""
        units = context.valid_units([str(block.id)])
        if not units:
            continue
        for match in _RANGE.finditer(text):
            add(
                match.group(0),
                units=units,
                kind="range",
                normalized=f"{match.group(1)}..{match.group(2)}",
                confidence=0.95,
            )
        for match in _ISO_DATE.finditer(text):
            add(match.group(0), units=units, kind="date", normalized=match.group(0), confidence=0.95)
        for match in _SLASH_DATE.finditer(text):
            day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
            add(
                match.group(0),
                units=units,
                kind="date",
                normalized=f"{year.zfill(4)}-{month:02d}-{day:02d}",
                ambiguous=_ambiguous(day, month),
                confidence=0.6 if _ambiguous(day, month) else 0.8,
            )
        for match in _DOTTED_DATE.finditer(text):
            day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
            add(
                match.group(0),
                units=units,
                kind="date",
                normalized=f"{year.zfill(4)}-{month:02d}-{day:02d}",
                ambiguous=_ambiguous(day, month),
                confidence=0.6 if _ambiguous(day, month) else 0.8,
            )
        for match in _MONTH_NAME.finditer(text):
            add(
                match.group(0),
                units=units,
                kind="date",
                normalized=f"{match.group(3)}-{match.group(2)[:3].lower()}-{int(match.group(1)):02d}",
                confidence=0.85,
            )
        for match in _VALIDITY.finditer(text):
            add(
                match.group(0),
                units=units,
                kind="validity",
                confidence=0.72,
            )
        if _DATE_HINT.search(text):
            for match in _COMPACT_DATE.finditer(text):
                year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    continue
                add(
                    match.group(0),
                    units=units,
                    kind="format",
                    normalized=f"{year}-{month:02d}-{day:02d}",
                    confidence=0.75,
                )

    result = sorted(
        found.values(), key=lambda item: (item.qualifier_type, item.value)
    )
    return tuple(result[:max_total])
