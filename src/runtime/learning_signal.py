# =============================================================================
# Learning signals — observaciones del turno para Knowledge Health (S10, C4).
# =============================================================================
# Determinista: entidades sin resolver, conflictos retenidos, claims sin
# respaldo y falta de evidencia. No entrena pesos: alimenta gaps/health.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.evidence_assembly import EvidencePackage
    from src.runtime.verification import AnswerVerification

PERSISTABLE_KINDS = frozenset({"unresolved_entity", "evidence_gap"})


@dataclass(frozen=True)
class LearningSignal:
    kind: str
    concept: str
    detail: str
    priority: float

    def to_public_dict(self) -> dict:
        return {
            "kind": self.kind,
            "concept": self.concept[:160],
            "detail": self.detail[:240],
            "priority": round(float(self.priority), 4),
        }


def build_learning_signals(
    *,
    entities: "EntityResolution | None" = None,
    package: "EvidencePackage | None" = None,
    verification: "AnswerVerification | None" = None,
    requires_knowledge: bool = False,
    max_signals: int = 6,
) -> tuple[LearningSignal, ...]:
    """Señales medibles del turno, en orden determinista de prioridad."""
    signals: list[LearningSignal] = []
    if entities is not None:
        for mention in entities.mentions:
            if mention.status != "resolved":
                signals.append(
                    LearningSignal(
                        kind="unresolved_entity",
                        concept=mention.mention,
                        detail=f"entidad no resuelta ({mention.status})",
                        priority=0.7 if mention.status == "ambiguous" else 0.6,
                    )
                )
    if package is not None:
        for conflict in package.conflicts:
            signals.append(
                LearningSignal(
                    kind="conflict",
                    concept=conflict.key,
                    detail="valores en conflicto: " + ", ".join(conflict.values[:3]),
                    priority=0.65,
                )
            )
        if requires_knowledge and not package.units:
            signals.append(
                LearningSignal(
                    kind="evidence_gap",
                    concept="sin_evidencia",
                    detail="la consulta requiere conocimiento y no hubo evidencia",
                    priority=0.55,
                )
            )
    if verification is not None:
        unsupported = [
            verdict
            for verdict in verification.verdicts
            if verdict.status == "unsupported"
        ]
        for verdict in unsupported[:3]:
            signals.append(
                LearningSignal(
                    kind="verification_failure",
                    concept=verdict.text[:120],
                    detail="claim sin respaldo en la evidencia del turno",
                    priority=0.5,
                )
            )
    signals.sort(key=lambda signal: (-signal.priority, signal.kind, signal.concept))
    return tuple(signals[: max(0, int(max_signals))])
