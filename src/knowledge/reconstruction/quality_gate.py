# =============================================================================
# Semantic Reconstruction Layer — Semantic Quality Gate
# =============================================================================
# Toda Semantic Unit pasa por el gate. Resultados posibles:
#   VALID, RECONSTRUCTED, AMBIGUOUS, INCOMPLETE, LOW_QUALITY,
#   STRUCTURAL_ARTIFACT, DUPLICATE, REQUIRES_REPAIR, REJECTED
#
# Solo VALID / RECONSTRUCTED con respaldo pasan al Knowledge Compiler. Todo lo
# demás queda como INGESTION_QUALITY: un problema de ingesta nunca se convierte
# en entidad, hecho, conflicto o gap canónico.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.knowledge.quality.fragments import TextQualityStatus, analyze_text_quality

from .contracts import (
    ConfidenceSignals,
    RawTable,
    ReconstructionStatus,
)
from .fragments import FragmentVerdict

_MIN_RECONSTRUCTED_CONFIDENCE = 0.55
_MIN_VALID_CONFIDENCE = 0.45

INGESTION_QUALITY_KIND = "INGESTION_QUALITY"


@dataclass(frozen=True, kw_only=True)
class GateDecision:
    """Veredicto del gate para un elemento."""

    element_id: object
    status: str
    knowledge: bool
    index_semantic: bool
    signals: ConfidenceSignals
    reasons: tuple[str, ...] = ()
    fragment_kinds: tuple[str, ...] = ()

    @property
    def quality_kind(self) -> str:
        return INGESTION_QUALITY_KIND


def gate_element(verdict: FragmentVerdict) -> GateDecision:
    """Aplica el gate a un veredicto del Fragment Detector."""
    status = verdict.status
    if status == ReconstructionStatus.RECONSTRUCTED.value:
        if verdict.signals.continuity_confidence >= _MIN_RECONSTRUCTED_CONFIDENCE:
            return GateDecision(
                element_id=verdict.element_id,
                status=status,
                knowledge=True,
                index_semantic=True,
                signals=verdict.signals,
                reasons=verdict.reasons,
            )
        return GateDecision(
            element_id=verdict.element_id,
            status=ReconstructionStatus.AMBIGUOUS.value,
            knowledge=False,
            index_semantic=False,
            signals=verdict.signals,
            reasons=("reconstruction_below_threshold",),
        )
    if status == ReconstructionStatus.VALID.value:
        if verdict.signals.reconstruction_confidence >= _MIN_VALID_CONFIDENCE:
            return GateDecision(
                element_id=verdict.element_id,
                status=status,
                knowledge=True,
                index_semantic=True,
                signals=verdict.signals,
                reasons=verdict.reasons,
            )
        return GateDecision(
            element_id=verdict.element_id,
            status=ReconstructionStatus.LOW_QUALITY.value,
            knowledge=False,
            index_semantic=False,
            signals=verdict.signals,
            reasons=("below_confidence_threshold",),
        )
    return GateDecision(
        element_id=verdict.element_id,
        status=status,
        knowledge=False,
        index_semantic=False,
        signals=verdict.signals,
        reasons=verdict.reasons,
        fragment_kinds=verdict.fragment_kinds,
    )


@dataclass(frozen=True, kw_only=True)
class TableGateDecision:
    """Veredicto del gate para una tabla reconstruida."""

    table_id: str
    status: str
    rejected_headers: tuple[str, ...] = ()
    repeated_header_rows: tuple[int, ...] = ()
    signals: ConfidenceSignals = field(default_factory=ConfidenceSignals)

    @property
    def index_semantic(self) -> bool:
        return self.status in {
            ReconstructionStatus.VALID.value,
            ReconstructionStatus.RECONSTRUCTED.value,
        }


def gate_table(
    table: RawTable,
    *,
    references: tuple[str, ...] = (),
    vocabulary: frozenset[str] = frozenset(),
) -> TableGateDecision:
    """Un header fragmentado no se convierte en columna de conocimiento."""
    rejected: list[str] = []
    for header in table.headers:
        text = " ".join((header or "").split())
        if not text:
            continue
        quality = analyze_text_quality(
            text,
            references=references,
            min_length=2,
            allow_code=True,
            max_words=12,
            max_length=160,
        )
        if quality.status != TextQualityStatus.OK.value:
            rejected.append(header)
            continue
        # Header que es pedazo de una palabra de la fuente: CATEG, CONT, ORD 2.
        lowered = text.lower()
        if lowered not in vocabulary and any(
            word.startswith(lowered) or word.endswith(lowered)
            for word in vocabulary
            if len(word) > len(lowered) >= 3
        ):
            rejected.append(header)

    repeated_rows: list[int] = []
    if table.headers and table.rows:
        header_key = tuple(" ".join(cell.lower().split()) for cell in table.headers)
        for position, row in enumerate(table.rows):
            if tuple(" ".join(cell.lower().split()) for cell in row) == header_key:
                repeated_rows.append(position)

    if rejected and len(rejected) >= max(1, len(table.headers) // 2):
        status = ReconstructionStatus.REQUIRES_REPAIR.value
    elif rejected:
        status = ReconstructionStatus.RECONSTRUCTED.value
    else:
        status = ReconstructionStatus.VALID.value
    signals = ConfidenceSignals.compute(
        structure_confidence=float(table.confidence or 0.8),
        semantic_completeness=(
            1.0
            if not rejected
            else 1.0 - (len(rejected) / max(len(table.headers), 1))
        ),
        schema_confidence=float(table.confidence or 0.8),
    )
    return TableGateDecision(
        table_id=table.id,
        status=status,
        rejected_headers=tuple(rejected),
        repeated_header_rows=tuple(repeated_rows),
        signals=signals,
    )


def quality_score(decisions: list[GateDecision]) -> float:
    """Distribución de calidad en un único score explicable (no un gate)."""
    if not decisions:
        return 1.0
    knowledge = [decision for decision in decisions if decision.knowledge]
    ratio = len(knowledge) / len(decisions)
    if not knowledge:
        return round(ratio, 4)
    mean_confidence = sum(
        decision.signals.reconstruction_confidence for decision in knowledge
    ) / len(knowledge)
    return round(0.6 * ratio + 0.4 * mean_confidence, 4)


def gate_distribution(decisions: list[GateDecision]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for decision in decisions:
        distribution[decision.status] = distribution.get(decision.status, 0) + 1
    return distribution


__all__ = [
    "GateDecision",
    "INGESTION_QUALITY_KIND",
    "TableGateDecision",
    "gate_distribution",
    "gate_element",
    "gate_table",
    "quality_score",
]
