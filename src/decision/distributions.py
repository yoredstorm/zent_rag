# =============================================================================
# Distributions — leer Choice/Score/Noul sin perder la distribución.
# =============================================================================
# Guardar solo `choice + confidence` descarta información material: una
# alternativa segunda con peso alto, un score con vecindad repartida o un Noul
# en 0.51 no son casos borde, son señales. Acá se leen:
#
#   Choice   ganador + runner-up + margen + entropía normalizada + ambigüedad
#   Score    score + nivel ganador + vecindad de niveles + confianza
#   Noul     valor + certeza (|v-0.5|*2) + dirección YES/NO/UNCERTAIN
#
# Noul NO tiene confidence separado y 0.0 es un NO fuerte: nunca se convierte en
# default ni en incertidumbre (`safe_noul` conserva 0.0 y False).
# =============================================================================
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.decision.questions import noul_certainty, safe_noul

DIRECTION_YES = "yes"
DIRECTION_NO = "no"
DIRECTION_UNCERTAIN = "uncertain"

#: Opción elegida sin margen material: es un ganador técnico, no un veredicto.
DEFAULT_AMBIGUITY_MARGIN = 0.12
#: Confianza mínima para tratar la opción ganadora como clara.
DEFAULT_CHOICE_HIGH = 0.70


def _probabilities(raw: Any) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, value in list(raw.items())[:32]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number != number:  # NaN
            continue
        out[str(key)] = min(1.0, max(0.0, number))
    return out


def _entropy(probabilities: Mapping[str, float]) -> float:
    """Entropía normalizada 0..1 (0 = certeza total, 1 = reparto uniforme)."""
    values = [value for value in probabilities.values() if value > 0]
    if len(values) <= 1:
        return 0.0
    total = sum(values)
    if total <= 0:
        return 0.0
    shares = [value / total for value in values]
    raw = -sum(share * math.log(share) for share in shares)
    return min(1.0, max(0.0, raw / math.log(len(shares))))


# -----------------------------------------------------------------------------
# Choice
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ChoiceReading:
    """Choice con su distribución: ganador, alternativas y ambigüedad."""

    choice: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)
    runner_up: str | None = None
    runner_up_probability: float = 0.0
    margin: float = 0.0
    entropy: float = 0.0
    ambiguous: bool = False
    certain: bool = False

    @property
    def alternatives(self) -> list[tuple[str, float]]:
        return sorted(
            (
                (option, probability)
                for option, probability in self.probabilities.items()
                if option != self.choice
            ),
            key=lambda item: item[1],
            reverse=True,
        )

    def to_public_dict(self, *, max_probabilities: int = 8) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "choice",
            "choice": self.choice,
            "confidence": round(self.confidence, 4),
            "margin": round(self.margin, 4),
            "entropy": round(self.entropy, 4),
            "ambiguous": self.ambiguous,
            "certain": self.certain,
        }
        if self.runner_up:
            payload["runner_up"] = self.runner_up
            payload["runner_up_probability"] = round(self.runner_up_probability, 4)
        if self.probabilities:
            ordered = sorted(
                self.probabilities.items(), key=lambda item: item[1], reverse=True
            )[:max_probabilities]
            payload["probabilities"] = {key: round(value, 4) for key, value in ordered}
        return payload


def read_choice(
    answer: Any,
    *,
    ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
    high_confidence: float = DEFAULT_CHOICE_HIGH,
) -> ChoiceReading | None:
    """Lee un Choice (`{"type": "choice", "choice": ..., ...}`)."""
    if not isinstance(answer, Mapping):
        return None
    choice = str(answer.get("choice") or "").strip()
    if not choice:
        return None
    probabilities = _probabilities(answer.get("probabilities"))
    try:
        confidence = float(answer.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    others = [
        (option, probability)
        for option, probability in probabilities.items()
        if option != choice
    ]
    runner_up, runner_up_probability = (
        max(others, key=lambda item: item[1]) if others else (None, 0.0)
    )
    margin = confidence - runner_up_probability
    probability_gap = 0.0
    if probabilities:
        own = max(probabilities.get(choice, confidence), 0.0)
        probability_gap = own - runner_up_probability
        margin = min(margin, probability_gap)
    ambiguous = bool(
        runner_up is not None
        and (
            margin < float(ambiguity_margin)
            or (confidence < high_confidence and probability_gap < 2 * float(ambiguity_margin))
        )
    )
    return ChoiceReading(
        choice=choice,
        confidence=confidence,
        probabilities=probabilities,
        runner_up=runner_up,
        runner_up_probability=round(runner_up_probability, 4),
        margin=round(margin, 4),
        entropy=round(_entropy(probabilities), 4),
        ambiguous=ambiguous,
        certain=confidence >= float(high_confidence) and not ambiguous,
    )


# -----------------------------------------------------------------------------
# Score
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreReading:
    """Score ordinal con vecindad de niveles y confianza."""

    score: float
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)
    level: str | None = None
    neighbourhood: list[tuple[str, float]] = field(default_factory=list)
    neighbourhood_mass: float = 0.0
    certain: bool = False

    def to_public_dict(self, *, max_probabilities: int = 8) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "score",
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "certain": self.certain,
        }
        if self.level:
            payload["level"] = self.level
        if self.neighbourhood:
            payload["neighbourhood"] = [
                {"level": level, "probability": round(probability, 4)}
                for level, probability in self.neighbourhood
            ]
            payload["neighbourhood_mass"] = round(self.neighbourhood_mass, 4)
        if self.probabilities:
            ordered = sorted(
                self.probabilities.items(), key=lambda item: item[1], reverse=True
            )[:max_probabilities]
            payload["probabilities"] = {key: round(value, 4) for key, value in ordered}
        return payload


def read_score(
    answer: Any,
    *,
    high_confidence: float = DEFAULT_CHOICE_HIGH,
) -> ScoreReading | None:
    """Lee un Score (`{"type": "score", "score": N, "probabilities": {...}}`)."""
    if not isinstance(answer, Mapping) or "score" not in answer:
        return None
    try:
        score = float(answer.get("score"))
    except (TypeError, ValueError):
        return None
    if score != score:  # NaN
        return None
    try:
        confidence = float(answer.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    probabilities = _probabilities(answer.get("probabilities"))
    neighbourhood: list[tuple[str, float]] = []
    level: str | None = None
    if probabilities:
        ordered = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        level = ordered[0][0]
        neighbourhood = ordered[:3]
        mass = sum(probability for _, probability in neighbourhood[1:])
    else:
        mass = 0.0
    return ScoreReading(
        score=score,
        confidence=confidence,
        probabilities=probabilities,
        level=level,
        neighbourhood=neighbourhood,
        neighbourhood_mass=round(min(1.0, mass), 4),
        certain=confidence >= float(high_confidence) and mass < 0.5,
    )


# -----------------------------------------------------------------------------
# Noul
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class NoulReading:
    """Noul con certeza derivada y dirección de tres vías.

    `certainty` NO es una confianza: es la distancia a 0.5. Un Noul 0.51 es
    `uncertain` con certeza 0.02, no un YES débil.
    """

    value: float
    certainty: float
    direction: str

    def is_yes(self, yes_threshold: float) -> bool:
        return self.direction == DIRECTION_YES and self.value >= float(yes_threshold)

    def is_no(self, no_threshold: float) -> bool:
        return self.direction == DIRECTION_NO and self.value <= float(no_threshold)

    def is_uncertain(self, yes_threshold: float, no_threshold: float) -> bool:
        """Un Noul en la banda media es incierto: 0.51 no es un YES débil."""
        return not (self.is_yes(yes_threshold) or self.is_no(no_threshold))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "type": "noul",
            "noul": round(self.value, 4),
            "certainty": round(self.certainty, 4),
            "direction": self.direction,
        }


def read_noul(
    answer: Any,
    *,
    yes_threshold: float = 0.65,
    no_threshold: float = 0.35,
    default: float | None = None,
) -> NoulReading | None:
    """Lee un Noul (`{"type": "noul", "noul": X}`). 0.0 sigue siendo NO fuerte."""
    if not isinstance(answer, Mapping) or "noul" not in answer:
        if default is None:
            return None
        value = float(default)
    else:
        value = safe_noul(answer.get("noul"), float(default if default is not None else 0.5))
    return noul_reading(value, yes_threshold=yes_threshold, no_threshold=no_threshold)


def noul_reading(
    value: float,
    *,
    yes_threshold: float = 0.65,
    no_threshold: float = 0.35,
) -> NoulReading:
    number = safe_noul(value, 0.5)
    if number >= float(yes_threshold):
        direction = DIRECTION_YES
    elif number <= float(no_threshold):
        direction = DIRECTION_NO
    else:
        direction = DIRECTION_UNCERTAIN
    return NoulReading(
        value=round(number, 6),
        certainty=round(noul_certainty(number), 6),
        direction=direction,
    )


__all__ = [
    "DEFAULT_AMBIGUITY_MARGIN",
    "DEFAULT_CHOICE_HIGH",
    "DIRECTION_NO",
    "DIRECTION_UNCERTAIN",
    "DIRECTION_YES",
    "ChoiceReading",
    "NoulReading",
    "ScoreReading",
    "noul_reading",
    "read_choice",
    "read_noul",
    "read_score",
]
