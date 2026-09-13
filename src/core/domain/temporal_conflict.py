# =============================================================================
# Domain Layer — Temporal + Conflict intelligence (Phase 5)
# =============================================================================
# Contratos puros para:
#   - Parsear ventanas temporales de claims ("2024", "enero 2025", "2024-2026").
#   - Clasificar conflictos estructurales entre claims (brief §16).
#   - Proponer resolución por temporalidad/autoridad SIN resolver en silencio
#     (siempre `requires_review=True`; la decisión final es humana).
#
# Sin I/O. La autoridad se resuelve por un resolver inyectable en el executor.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from src.core.domain.evidence import ClaimRecord


class ConflictType(StrEnum):
    """Brief §16: tipos de contradicción."""

    DIRECT_CONFLICT = "direct_conflict"
    TEMPORAL_UPDATE = "temporal_update"
    SOURCE_DISAGREEMENT = "source_disagreement"
    AMBIGUITY = "ambiguity"
    DUPLICATE_DIFFERENCE = "duplicate_difference"
    SEMANTIC_CONFLICT = "semantic_conflict"  # reservado (requiere similitud semántica)


class ClaimTemporalState(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class TemporalWindow:
    """Ventana de vigencia derivada de un scope textual."""

    valid_from: datetime | None = None
    valid_to: datetime | None = None
    label: str = ""

    def is_expired(self, now: datetime) -> bool:
        return self.valid_to is not None and self.valid_to < now

    def starts_after(self, other: TemporalWindow | None) -> bool:
        """True si esta ventana empieza después (o es abierta y la otra no)."""
        if other is None or other.valid_from is None:
            return self.valid_from is not None
        if self.valid_from is None:
            return False
        return self.valid_from > other.valid_from

    def overlaps(self, other: TemporalWindow) -> bool:
        if self.valid_to is not None and other.valid_from is not None:
            if self.valid_to < other.valid_from:
                return False
        if other.valid_to is not None and self.valid_from is not None:
            if other.valid_to < self.valid_from:
                return False
        return True


@dataclass(frozen=True, kw_only=True)
class ConflictResolution:
    """Propuesta de resolución; nunca se aplica sin revisión humana."""

    conflict_type: ConflictType
    winning_claim_id: UUID | None = None
    losing_claim_id: UUID | None = None
    reason: str = ""
    authority: str | None = None
    effective_date: datetime | None = None
    confidence: float = 0.0
    requires_review: bool = True

    def to_dict(self) -> dict:
        return {
            "conflict_type": self.conflict_type.value,
            "winning_claim_id": (
                str(self.winning_claim_id) if self.winning_claim_id else None
            ),
            "losing_claim_id": (
                str(self.losing_claim_id) if self.losing_claim_id else None
            ),
            "reason": self.reason,
            "authority": self.authority,
            "effective_date": (
                self.effective_date.isoformat() if self.effective_date else None
            ),
            "confidence": self.confidence,
            "requires_review": self.requires_review,
        }


_MONTHS: dict[str, int] = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "jun": 6, "jul": 7, "ago": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_MONTH_YEAR_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_MONTH_NUM_RE = re.compile(r"\b((?:19|20)\d{2})-(\d{1,2})\b")
_RANGE_RE = re.compile(
    r"\b((?:19|20)\d{2})\s*(?:-|–|a|to)\s*((?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def parse_temporal_window(text: str | None) -> TemporalWindow | None:
    """Parse deterministic ES/EN temporal scopes.

    Supported: "2024", "enero 2025", "jan 2025", "2025-03", "2024-2026",
    "desde 2023", "hasta 2024". Returns None when no temporal signal exists.
    """
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    lowered = raw.lower()

    range_match = _RANGE_RE.search(lowered)
    if range_match:
        start_year, end_year = int(range_match.group(1)), int(range_match.group(2))
        if start_year <= end_year:
            return TemporalWindow(
                valid_from=_utc(start_year, 1, 1),
                valid_to=_utc(end_year, 12, 31),
                label=raw,
            )

    month_year = _MONTH_YEAR_RE.search(lowered)
    if month_year:
        month = _MONTHS[month_year.group(1).lower()]
        year = int(month_year.group(2))
        return TemporalWindow(
            valid_from=_utc(year, month, 1),
            valid_to=_last_day(year, month),
            label=raw,
        )

    month_num = _MONTH_NUM_RE.search(lowered)
    if month_num:
        year, month = int(month_num.group(1)), int(month_num.group(2))
        if 1 <= month <= 12:
            return TemporalWindow(
                valid_from=_utc(year, month, 1),
                valid_to=_last_day(year, month),
                label=raw,
            )

    year_match = _YEAR_RE.search(lowered)
    if year_match:
        year = int(year_match.group(1))
        if "hasta" in lowered and "desde" not in lowered:
            return TemporalWindow(valid_to=_utc(year, 12, 31), label=raw)
        if "desde" in lowered:
            return TemporalWindow(valid_from=_utc(year, 1, 1), label=raw)
        return TemporalWindow(
            valid_from=_utc(year, 1, 1), valid_to=_utc(year, 12, 31), label=raw
        )
    return None


def _last_day(year: int, month: int) -> datetime:
    if month == 12:
        return _utc(year, 12, 31)
    next_month = _utc(year, month + 1, 1)
    from datetime import timedelta

    return next_month - timedelta(days=1)


def claim_window(claim: ClaimRecord) -> TemporalWindow | None:
    return parse_temporal_window(claim.temporal_scope)


def claim_temporal_state(
    claim: ClaimRecord, *, now: datetime
) -> ClaimTemporalState:
    window = claim_window(claim)
    if window is None:
        return ClaimTemporalState.UNKNOWN
    return (
        ClaimTemporalState.HISTORICAL
        if window.is_expired(now)
        else ClaimTemporalState.CURRENT
    )


_AUTHORITY_RANK = {
    "authoritative": 4,
    "approved": 3,
    "informational": 2,
    "external": 1,
}


def classify_conflict(
    *,
    a: ClaimRecord,
    b: ClaimRecord,
    window_a: TemporalWindow | None = None,
    window_b: TemporalWindow | None = None,
    source_a: str | None = None,
    source_b: str | None = None,
) -> ConflictType:
    """Classify a structural conflict (same subject+predicate, different object)."""
    object_a = (a.normalized_object or "").strip()
    object_b = (b.normalized_object or "").strip()
    if object_a and object_a == object_b:
        return ConflictType.DUPLICATE_DIFFERENCE
    if not object_a or not object_b:
        return ConflictType.AMBIGUITY
    window_a = window_a or claim_window(a)
    window_b = window_b or claim_window(b)
    if window_a is not None and window_b is not None:
        if not window_a.overlaps(window_b):
            return ConflictType.TEMPORAL_UPDATE
    if source_a and source_b and source_a != source_b:
        return ConflictType.SOURCE_DISAGREEMENT
    return ConflictType.DIRECT_CONFLICT


def propose_resolution(
    *,
    conflict_type: ConflictType,
    claim_a_id: UUID,
    claim_b_id: UUID,
    window_a: TemporalWindow | None = None,
    window_b: TemporalWindow | None = None,
    authority_a: str | None = None,
    authority_b: str | None = None,
) -> ConflictResolution:
    """Propose a winner by temporal order or authority. Never auto-applies."""
    if conflict_type is ConflictType.TEMPORAL_UPDATE:
        window_a = window_a or TemporalWindow()
        window_b = window_b or TemporalWindow()
        a_wins = window_a.starts_after(window_b)
        winner, loser = (
            (claim_a_id, claim_b_id) if a_wins else (claim_b_id, claim_a_id)
        )
        winner_window = window_a if a_wins else window_b
        return ConflictResolution(
            conflict_type=conflict_type,
            winning_claim_id=winner,
            losing_claim_id=loser,
            reason="temporal update: la versión más reciente (o vigente) prevalece",
            effective_date=winner_window.valid_from,
            confidence=0.7,
            requires_review=True,
        )

    if conflict_type is ConflictType.SOURCE_DISAGREEMENT:
        rank_a = _AUTHORITY_RANK.get((authority_a or "").lower(), 0)
        rank_b = _AUTHORITY_RANK.get((authority_b or "").lower(), 0)
        if rank_a != rank_b:
            a_wins = rank_a > rank_b
            winner, loser = (
                (claim_a_id, claim_b_id) if a_wins else (claim_b_id, claim_a_id)
            )
            return ConflictResolution(
                conflict_type=conflict_type,
                winning_claim_id=winner,
                losing_claim_id=loser,
                reason="source authority prevalece entre fuentes",
                authority=authority_a if a_wins else authority_b,
                confidence=0.6,
                requires_review=True,
            )
        return ConflictResolution(
            conflict_type=conflict_type,
            reason="autoridades equivalentes: requiere revisión humana",
            confidence=0.3,
            requires_review=True,
        )

    return ConflictResolution(
        conflict_type=conflict_type,
        reason=f"{conflict_type.value}: requiere revisión humana",
        confidence=0.2,
        requires_review=True,
    )
