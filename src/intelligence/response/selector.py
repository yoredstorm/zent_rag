# =============================================================================
# Selección del blueprint (§4): determinista primero, JEV sólo con ambigüedad.
# =============================================================================
# El intent, la forma de razonamiento y la estructura de la pregunta alcanzan
# para elegir la forma de explicar en la enorme mayoría de los casos. JEV sólo
# entra cuando dos formas quedan empatadas de verdad.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from src.core.domain.reasoning import ReasoningShape
from src.intelligence.response.blueprints import (
    COMPARISON,
    DATA_INTERPRETATION,
    DEFINITION_EXPLANATION,
    DIAGNOSTIC,
    DIRECT_FACT,
    EXECUTIVE_SUMMARY,
    PROCEDURE,
    SCENARIO_ANALYSIS,
    TECHNICAL_EXPLANATION,
    TUTORIAL,
)

DECIDED_BY_RULES = "deterministic"
DECIDED_BY_JEV = "jev"
DECIDED_BY_PROFILE = "profile"

#: Preguntas de definición: «¿qué es X?», «¿qué significa X?»
_DEFINITION_RE = re.compile(
    r"\b(qu[eé] es|qu[eé] son|qu[eé] significa|definici[oó]n|what is|what does .* mean|"
    r"define|significado de)\b",
    re.IGNORECASE,
)
#: Preguntas sobre un campo/valor concreto: «¿qué significa el campo X con valor 2?»
_FIELD_VALUE_RE = re.compile(
    r"\b(campo|field|byte|bit|flag|indicador|valor|value|c[oó]digo de (?:acci[oó]n|estado)|"
    r"record 2|record 4)\b",
    re.IGNORECASE,
)
#: Diagnóstico: «¿por qué falló/pasó ocurrió?»
_DIAGNOSTIC_RE = re.compile(
    r"\b(por qu[eé]|qu[eé] caus[oó]|why did|why does|causa (?:de|ra[ií]z)|"
    r"motivo por el (?:que|cual))\b",
    re.IGNORECASE,
)
#: Procedimiento: «¿cómo hago X?», «pasos para X»
_PROCEDURE_RE = re.compile(
    r"\b(c[oó]mo (?:hago|se hace|puedo|procedo|solicito|cargo|creo|configuro)|"
    r"pasos para|how (?:do i|to)|procedimiento|tutorial de|gu[ií]a para)\b",
    re.IGNORECASE,
)
#: Comparación: «X vs Y», «diferencia entre X e Y»
_COMPARISON_RE = re.compile(
    r"\b(vs\.?|versus|diferencia entre|comparar|comparaci[oó]n|cu[aá]l conviene|"
    r"which is better|difference between)\b",
    re.IGNORECASE,
)
#: Resumen ejecutivo: pide lo esencial.
_EXECUTIVE_RE = re.compile(
    r"\b(resumen|en breve|en una l[ií]nea|tl;?dr|executive summary|lo esencial)\b",
    re.IGNORECASE,
)
#: Dato puntual: pide un valor concreto.
_DIRECT_FACT_RE = re.compile(
    r"\b(cu[aá]l es (?:el|la|los|las)?\s*(?:c[oó]digo|valor|precio|nombre|id)|"
    r"qu[eé] valor tiene|d[oó]nde est[aá]|cu[aá]ndo (?:fue|se)|what is the (?:code|value|price))\b",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"\b(tabla|table)\b", re.IGNORECASE)

#: Umbral de margen para considerar que dos formas están empatadas (§10 del
#: diseño de JEV: un ganador técnico no es un veredicto).
AMBIGUITY_MARGIN = 0.12


@dataclass(frozen=True)
class BlueprintSelection:
    """Forma elegida + de dónde salió + alternativas con peso."""

    blueprint: str
    decided_by: str
    confidence: float = 0.0
    ambiguous: bool = False
    runner_up: str = ""
    candidates: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def needs_jev(self) -> bool:
        return self.ambiguous or not self.signals

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "blueprint": self.blueprint,
            "decided_by": self.decided_by,
            "confidence": round(float(self.confidence), 4),
        }
        if self.ambiguous:
            payload["ambiguous"] = True
        if self.runner_up:
            payload["runner_up"] = self.runner_up
        if self.candidates:
            payload["candidates"] = list(self.candidates)
        if self.signals:
            payload["signals"] = list(self.signals)
        return payload


def deterministic_candidates(
    *,
    question: str,
    intent: str = "",
    shape: str = "",
    has_records: bool = False,
    has_data_rows: bool = False,
    is_followup: bool = False,
) -> tuple[str, ...]:
    """Formas plausibles en orden de preferencia, sin JEV.

    Devuelve más de una cuando la pregunta admite dos lecturas legítimas: ahí el
    código decide si hace falta JEV.
    """
    text = (question or "").strip()
    normalized_shape = str(shape or "").strip().upper()
    normalized_intent = str(intent or "").strip().lower()
    candidates: list[str] = []

    def add(candidate: str) -> None:
        if candidate not in candidates:
            candidates.append(candidate)

    if _EXECUTIVE_RE.search(text):
        add(EXECUTIVE_SUMMARY)
    if _COMPARISON_RE.search(text):
        add(COMPARISON)
    if _PROCEDURE_RE.search(text):
        add(PROCEDURE)
    if _DIAGNOSTIC_RE.search(text):
        add(DIAGNOSTIC)
    if normalized_shape == ReasoningShape.STATE_TRANSITION.value or has_records:
        add(SCENARIO_ANALYSIS)
    if normalized_shape == ReasoningShape.HYPOTHESIS_TEST.value:
        add(DIAGNOSTIC)
        add(SCENARIO_ANALYSIS)
    if normalized_shape in {
        ReasoningShape.TEMPORAL_SEQUENCE.value,
        ReasoningShape.CONSISTENCY_CHECK.value,
    }:
        add(SCENARIO_ANALYSIS)
    if normalized_shape in {
        ReasoningShape.MULTI_EVIDENCE.value,
        ReasoningShape.COMPARATIVE_REASONING.value,
    }:
        add(DATA_INTERPRETATION)
    asks_meaning = bool(_DEFINITION_RE.search(text))
    asks_value = bool(_DIRECT_FACT_RE.search(text))
    if _FIELD_VALUE_RE.search(text) and asks_meaning:
        add(TECHNICAL_EXPLANATION)
    if asks_value and not asks_meaning:
        # «¿cuál es el código/valor?» se responde directo, no con un ensayo.
        add(DIRECT_FACT)
    if _FIELD_VALUE_RE.search(text):
        add(TECHNICAL_EXPLANATION)
    if asks_meaning:
        add(DEFINITION_EXPLANATION)
    if has_data_rows and DATA_INTERPRETATION not in candidates:
        add(DATA_INTERPRETATION)
    if re.search(r"\b(ense[nñ]ame|expl[ií]came (?:todo|desde cero)|tutorial)\b", text, re.I):
        add(TUTORIAL)
    if _DIRECT_FACT_RE.search(text):
        add(DIRECT_FACT)
    if normalized_intent in {"policy", "definition"} and DEFINITION_EXPLANATION not in candidates:
        add(DEFINITION_EXPLANATION)
    if not candidates:
        # Pregunta abierta sin señal: lo más honesto es explicar técnicamente.
        add(TECHNICAL_EXPLANATION)
    elif TECHNICAL_EXPLANATION not in candidates and len(candidates) == 1:
        add(TECHNICAL_EXPLANATION)
    if is_followup and candidates and candidates[0] == DIRECT_FACT and len(candidates) > 1:
        # Un seguimiento sobre un dato puntual suele pedir algo de explicación.
        candidates = [candidates[0], *candidates[1:]]
    return tuple(candidates)


def select_blueprint(
    *,
    question: str,
    intent: str = "",
    shape: str = "",
    has_records: bool = False,
    has_data_rows: bool = False,
    is_followup: bool = False,
    preferred_blueprints: tuple[str, ...] = (),
) -> BlueprintSelection:
    """Selección determinista. `needs_jev` marca cuándo conviene preguntarle."""
    candidates = deterministic_candidates(
        question=question,
        intent=intent,
        shape=shape,
        has_records=has_records,
        has_data_rows=has_data_rows,
        is_followup=is_followup,
    )
    if preferred_blueprints:
        ordered = tuple(
            candidate for candidate in preferred_blueprints if candidate in candidates
        )
        if ordered:
            chosen = ordered[0]
            return BlueprintSelection(
                blueprint=chosen,
                decided_by=DECIDED_BY_PROFILE,
                confidence=0.9,
                candidates=candidates,
                signals=candidates,
                reasons=("preferred_blueprint",),
            )
    chosen = candidates[0]
    second = candidates[1] if len(candidates) > 1 else ""
    ambiguous = bool(second) and _is_ambiguous(chosen, second, question, shape)
    confidence = 0.85 if not ambiguous else 0.5
    if len(candidates) == 1:
        confidence = 0.9
    return BlueprintSelection(
        blueprint=chosen,
        decided_by=DECIDED_BY_RULES,
        confidence=confidence,
        ambiguous=ambiguous,
        runner_up=second if ambiguous else "",
        candidates=candidates,
        signals=candidates,
    )


def _is_ambiguous(
    chosen: str,
    second: str,
    question: str,
    shape: str,
) -> bool:
    """Dos lecturas legítimas de la misma pregunta: JEV decide la forma."""
    pairs = {
        frozenset({TECHNICAL_EXPLANATION, DEFINITION_EXPLANATION}),
        frozenset({SCENARIO_ANALYSIS, DIAGNOSTIC}),
        frozenset({DIRECT_FACT, TECHNICAL_EXPLANATION}),
        frozenset({DEFINITION_EXPLANATION, TUTORIAL}),
        frozenset({COMPARISON, DATA_INTERPRETATION}),
    }
    if frozenset({chosen, second}) not in pairs:
        return False
    # Un campo/valor concreto con forma compleja es la ambigüedad típica.
    if _FIELD_VALUE_RE.search(question) and _DEFINITION_RE.search(question):
        return True
    if frozenset({SCENARIO_ANALYSIS, DIAGNOSTIC}) == frozenset({chosen, second}):
        return bool(_DIAGNOSTIC_RE.search(question))
    return frozenset({chosen, second}) in pairs and len(question) < 140


def selection_from_jev(
    *,
    choice: str,
    confidence: float,
    ambiguous: bool,
    runner_up: str = "",
    detail: str = "",
    deterministic: BlueprintSelection | None = None,
) -> BlueprintSelection:
    """Forma elegida por JEV, con la señal determinista como respaldo."""
    return BlueprintSelection(
        blueprint=choice,
        decided_by=DECIDED_BY_JEV,
        confidence=confidence,
        ambiguous=ambiguous,
        runner_up=runner_up,
        candidates=(deterministic.candidates if deterministic is not None else ()),
        signals=(deterministic.blueprint,) if deterministic is not None else (),
    )


__all__ = [
    "AMBIGUITY_MARGIN",
    "BlueprintSelection",
    "DECIDED_BY_JEV",
    "DECIDED_BY_PROFILE",
    "DECIDED_BY_RULES",
    "deterministic_candidates",
    "select_blueprint",
    "selection_from_jev",
]
