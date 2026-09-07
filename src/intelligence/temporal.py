# =============================================================================
# Temporal Semantic Intelligence — as-of + Spanish phrases (Phase 28A)
# =============================================================================
# "hoy" solo = current (no past). Resolver versiones por effective_from/to.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


@dataclass
class TimePhraseResult:
    """Resultado estructurado del parser temporal."""

    phrase: str
    scope: str  # current | past | period | range | quarter | ytd | mtd
    start: date | None
    end: date | None
    label: str


class TemporalResolver:
    """Resuelve versiones vigentes y parsea frases temporales en español."""

    def __init__(self, *, today: date | None = None) -> None:
        self.today = today or datetime.now(timezone.utc).date()

    def resolve_version(
        self,
        objects_with_effective_from_to: list[dict[str, Any]],
        as_of: date | datetime | str,
    ) -> dict[str, Any] | None:
        """Primera versión vigente en as_of (effective_from <= as_of < effective_to)."""
        target = _as_date(as_of)
        if target is None:
            return None
        candidates: list[tuple[date, dict[str, Any]]] = []
        for obj in objects_with_effective_from_to:
            start = _as_date(obj.get("effective_from"))
            end = _as_date(obj.get("effective_to"))
            if start and target < start:
                continue
            if end and target >= end:
                continue
            # open-ended: no start treated as -inf, no end as +inf
            rank = start or date.min
            candidates.append((rank, obj))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def parse_time_phrase(
        self, text: str, *, today: date | None = None
    ) -> TimePhraseResult | None:
        """Parser estructurado de frases temporales (ES)."""
        ref = today or self.today
        lowered = (text or "").strip().lower()
        if not lowered:
            return None

        # "hoy" = current (never past). Checked before other past markers.
        if re.search(r"\bhoy\b", lowered) and not re.search(
            r"\b(ayer|anteayer|mes pasado|semana pasada|año anterior)\b", lowered
        ):
            return TimePhraseResult("hoy", "current", ref, ref, "hoy")

        if re.search(r"\banteayer\b", lowered):
            d = ref - timedelta(days=2)
            return TimePhraseResult("anteayer", "past", d, d, "anteayer")
        if re.search(r"\bayer\b", lowered):
            d = ref - timedelta(days=1)
            return TimePhraseResult("ayer", "past", d, d, "ayer")

        if re.search(r"\besta semana\b", lowered):
            start = ref - timedelta(days=ref.weekday())
            return TimePhraseResult("esta semana", "period", start, ref, "esta_semana")
        if re.search(r"\bsemana pasada\b", lowered):
            end = ref - timedelta(days=ref.weekday() + 1)
            start = end - timedelta(days=6)
            return TimePhraseResult("semana pasada", "past", start, end, "semana_pasada")

        if re.search(r"\beste mes\b", lowered):
            start = ref.replace(day=1)
            return TimePhraseResult("este mes", "mtd", start, ref, "este_mes")
        if re.search(r"\bmes pasado\b", lowered):
            first_this = ref.replace(day=1)
            end = first_this - timedelta(days=1)
            start = end.replace(day=1)
            return TimePhraseResult("mes pasado", "past", start, end, "mes_pasado")

        m = re.search(r"\bq([1-4])\b", lowered)
        if m:
            q = int(m.group(1))
            year = ref.year
            ym = re.search(r"\b(20\d{2})\b", lowered)
            if ym:
                year = int(ym.group(1))
            start_month = (q - 1) * 3 + 1
            start = date(year, start_month, 1)
            end_month = start_month + 2
            if end_month == 12:
                end = date(year, 12, 31)
            else:
                end = date(year, end_month + 1, 1) - timedelta(days=1)
            return TimePhraseResult(f"Q{q}", "quarter", start, end, f"Q{q}_{year}")

        if re.search(r"\bytd\b|\baño hasta la fecha\b|\bdel año\b", lowered):
            start = date(ref.year, 1, 1)
            return TimePhraseResult("YTD", "ytd", start, ref, "YTD")
        if re.search(r"\bmtd\b|\bmes hasta la fecha\b", lowered):
            start = ref.replace(day=1)
            return TimePhraseResult("MTD", "mtd", start, ref, "MTD")

        if re.search(r"\búltimos?\s+30\s+d[ií]as\b|\bultimos?\s+30\s+dias\b", lowered):
            start = ref - timedelta(days=29)
            return TimePhraseResult("últimos 30 días", "period", start, ref, "last_30_days")

        if re.search(r"\baño anterior\b|\baño pasado\b", lowered):
            year = ref.year - 1
            return TimePhraseResult(
                "año anterior", "past", date(year, 1, 1), date(year, 12, 31), f"year_{year}"
            )

        if re.search(r"\bactualmente\b|\bactual\b|\bhasta ahora\b", lowered):
            return TimePhraseResult("actual", "current", ref, ref, "current")

        if re.search(
            r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
            r"octubre|noviembre|diciembre)\b|\b20\d\d\b|\b[úu]ltimo mes\b|"
            r"\b[úu]ltimos? (d[ií]as|meses)\b",
            lowered,
        ):
            return TimePhraseResult("period", "past", None, None, "past_marker")

        if re.search(r"\bproyecci[oó]n\b|\bpr[oó]ximo\b|\bfuturo\b|\bestimaci[oó]n\b", lowered):
            return TimePhraseResult("future", "future", None, None, "future")

        return None

    def detect_scope(self, text: str) -> str | None:
        """Compat wrapper for QueryUnderstanding time_scope."""
        parsed = self.parse_time_phrase(text)
        return parsed.scope if parsed else None
