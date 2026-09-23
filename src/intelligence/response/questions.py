# =============================================================================
# Pack de composición (JEV) — una sola llamada para decidir la forma (§5).
# =============================================================================
# Choice  response_blueprint
# Score   required_detail
# Noul    needs_example, needs_table, needs_step_by_step, needs_warning,
#         needs_definition, needs_practical_implication, needs_source_explanation,
#         needs_citations
#
# JEV NO redacta la respuesta: sólo responde cómo explicarla. El código compone
# el contrato y el generador escribe.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.decision.batch import build_response_composition_questions
from src.decision.distributions import read_choice, read_noul, read_score
from src.decision.registry import REQUIRED_DETAIL_OPTIONS, RESPONSE_BLUEPRINT_OPTIONS

#: Preguntas Noul del pack, en orden estable.
NUOL_QUESTIONS: tuple[str, ...] = (
    "needs_example",
    "needs_table",
    "needs_step_by_step",
    "needs_warning",
    "needs_definition",
    "needs_practical_implication",
    "needs_source_explanation",
    "needs_citations",
)


@dataclass(frozen=True)
class CompositionAnswers:
    """Lectura del pack: forma, detalle y necesidades, sin inventar valores."""

    blueprint: str = ""
    blueprint_confidence: float = 0.0
    blueprint_ambiguous: bool = False
    blueprint_runner_up: str = ""
    detail: str = ""
    detail_confidence: float = 0.0
    needs: tuple[str, ...] = field(default_factory=tuple)
    uncertain: tuple[str, ...] = field(default_factory=tuple)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def answered(self) -> bool:
        return bool(self.blueprint or self.detail or self.needs)

    def needs_flag(self, question_id: str) -> bool:
        return question_id in self.needs

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.blueprint:
            payload["blueprint"] = self.blueprint
            payload["confidence"] = round(self.blueprint_confidence, 4)
        if self.blueprint_ambiguous:
            payload["ambiguous"] = True
            if self.blueprint_runner_up:
                payload["runner_up"] = self.blueprint_runner_up
        if self.detail:
            payload["detail"] = self.detail
        if self.needs:
            payload["needs"] = list(self.needs)
        if self.uncertain:
            payload["uncertain"] = list(self.uncertain)
        return payload


def build_composition_questions() -> dict[str, dict[str, Any]]:
    """Payload del pack (ids estables, criteria declarados)."""
    return build_response_composition_questions().to_jevy()


def read_composition_answers(
    payload: Mapping[str, Any] | None,
    *,
    yes_threshold: float = 0.65,
    no_threshold: float = 0.35,
) -> CompositionAnswers:
    """Interpreta las respuestas del pack. Un Noul 0.51 no es un YES."""
    if not isinstance(payload, Mapping):
        return CompositionAnswers()
    answers = payload.get("answers") if isinstance(payload.get("answers"), Mapping) else payload
    if not isinstance(answers, Mapping):
        return CompositionAnswers()

    raw: dict[str, Any] = {}
    for key, value in answers.items():
        if isinstance(value, Mapping):
            raw[str(key)] = dict(value)

    blueprint = ""
    confidence = 0.0
    ambiguous = False
    runner_up = ""
    choice = read_choice(answers.get("response_blueprint"))
    if choice is not None and choice.choice in RESPONSE_BLUEPRINT_OPTIONS:
        blueprint = choice.choice
        confidence = choice.confidence
        ambiguous = choice.ambiguous
        runner_up = choice.runner_up or ""

    detail = ""
    detail_confidence = 0.0
    score = read_score(answers.get("required_detail"))
    if score is not None:
        level = str(score.level or "").strip().lower()
        if level in REQUIRED_DETAIL_OPTIONS:
            detail = level
            detail_confidence = score.confidence

    needs: list[str] = []
    uncertain: list[str] = []
    for question_id in NUOL_QUESTIONS:
        reading = read_noul(answers.get(question_id), default=None)
        if reading is None:
            continue
        if reading.is_yes(yes_threshold):
            needs.append(question_id)
        elif reading.is_uncertain(yes_threshold, no_threshold):
            uncertain.append(question_id)
    if ambiguous:
        uncertain.append("response_blueprint")
    return CompositionAnswers(
        blueprint=blueprint,
        blueprint_confidence=confidence,
        blueprint_ambiguous=ambiguous,
        blueprint_runner_up=runner_up,
        detail=detail,
        detail_confidence=detail_confidence,
        needs=tuple(needs),
        uncertain=tuple(uncertain),
        raw=raw,
    )


__all__ = [
    "CompositionAnswers",
    "NUOL_QUESTIONS",
    "build_composition_questions",
    "read_composition_answers",
]
