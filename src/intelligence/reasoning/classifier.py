# =============================================================================
# Reasoning Shape Classifier (§3/§9/§10)
# =============================================================================
# Eje ortogonal al intent: no "qué pide" sino "qué hay que probar".
# Determinista primero; el JEV sólo entra en la banda incierta y responde
# PREGUNTAS ATÓMICAS, nunca "resolvé el problema".
#
# El fast path es parte del contrato: si la forma es SIMPLE_LOOKUP, no se
# construye plan, ni workspace, ni hipótesis.
# =============================================================================
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from src.core.domain.reasoning import (
    ReasoningClassification,
    ReasoningClassificationSource,
    ReasoningShape,
)

#: Banda donde el determinismo no alcanza y conviene una segunda señal.
UNCERTAIN_LOW = 0.45
UNCERTAIN_HIGH = 0.75

# Señales léxicas por forma: (patrón, peso). El orden no importa; gana el score.
_SHAPE_SIGNALS: tuple[tuple[ReasoningShape, tuple[tuple[str, float], ...]], ...] = (
    (
        ReasoningShape.STATE_TRANSITION,
        (
            (r"\bfalta\b.*\bregistro", 1.0),
            (r"\bsecuencia\b", 0.9),
            (r"\bsequence\b", 0.9),
            (r"\brenumer", 0.9),
            (r"\bcierre\b", 0.7),
            (r"\bcerrar\b", 0.7),
            (r"\bclose\b", 0.7),
            (r"\bestado\s+anterior", 0.6),
            (r"\bpas[oó]\s+de\b", 0.5),
            (r"\btransici[oó]n", 0.8),
            (r"\btransition", 0.8),
            (r"\bdeber[ií]a\s+haber", 0.5),
        ),
    ),
    (
        ReasoningShape.TEMPORAL_SEQUENCE,
        (
            (r"\borden\b", 0.7),
            (r"\bcronolog", 0.8),
            (r"\bantes\s+de\b", 0.5),
            (r"\bdespu[ée]s\s+de\b", 0.5),
            (r"\bvigen", 0.7),
            (r"\bel\s+a[ñn]o\s+pasado\b", 0.8),
            (r"\bfecha\s+de\s+vigencia", 0.8),
            (r"\btimeline\b", 0.7),
        ),
    ),
    (
        ReasoningShape.CONSISTENCY_CHECK,
        (
            (r"\bconsistenc", 0.9),
            (r"\bcontradic", 0.8),
            (r"\bconflicto\b", 0.7),
            (r"\bcuadra\b", 0.7),
            (r"\bcoincide\b", 0.6),
            (r"\bse\s+contradice", 0.9),
        ),
    ),
    (
        ReasoningShape.DIAGNOSTIC,
        (
            (r"\bpor\s+qu[ée]\s+fall", 0.9),
            (r"\bdiagn[oó]stic", 0.9),
            (r"\bqu[ée]\s+sali[oó]\s+mal", 0.8),
            (r"\bcausa\s+ra[ií]z", 0.9),
            (r"\bro[oó]t\s+cause", 0.9),
            (r"\bfailed\b", 0.5),
            (r"\brechazad", 0.5),
        ),
    ),
    (
        ReasoningShape.HYPOTHESIS_TEST,
        (
            (r"\bes\s+cierto\s+que\b", 0.9),
            (r"\bhip[oó]tesis\b", 0.9),
            (r"\bpodr[ií]a\s+ser\s+que\b", 0.7),
            (r"\bsospech", 0.6),
            (r"\bsuponiendo\s+que\b", 0.7),
        ),
    ),
    (
        ReasoningShape.CAUSAL_ANALYSIS,
        (
            (r"\bpor\s+qu[ée]\b", 0.9),
            (r"\bwhy\b", 0.9),
            (r"\bporque\b", 0.5),
            (r"\bmotivo\b", 0.6),
            (r"\bimpacto\s+de\b", 0.5),
            (r"\bexplica\b", 0.5),
        ),
    ),
    (
        ReasoningShape.COMPARATIVE_REASONING,
        (
            (r"\bcompar", 0.8),
            (r"\bdiferencia\s+entre\b", 0.9),
            (r"\bversus\b", 0.7),
            (r"\bmejor\s+que\b", 0.6),
        ),
    ),
    (
        ReasoningShape.GRAPH_REASONING,
        (
            (r"\bqu[ée]\s+se\s+rompe\b", 0.9),
            (r"\bqu[ée]\s+se\s+ve\s+afectado", 0.9),
            (r"\bdepende\s+de\b", 0.8),
            (r"\bdepends\s+on\b", 0.8),
            (r"\bno\s+est[áa]\s+disponible", 0.8),
            (r"\bafectad", 0.6),
            (r"\baguas\s+abajo\b", 0.7),
            (r"\bdownstream\b", 0.7),
        ),
    ),
    (
        ReasoningShape.MULTI_EVIDENCE,
        (
            (r"\bseg[uú]n\s+los\s+documentos\b", 0.6),
            (r"\bcombinando\b", 0.6),
            (r"\bcon\s+base\s+en\s+todo\b", 0.6),
            (r"\bvarias\s+fuentes\b", 0.7),
        ),
    ),
    (
        ReasoningShape.SIMPLE_LOOKUP,
        (
            (r"\bqu[ée]\s+significa\b", 0.9),
            (r"\bqu[ée]\s+es\b", 0.8),
            (r"\bdefinici[oó]n\s+de\b", 0.9),
            (r"\bhow\s+is\s+it\s+defined\b", 0.8),
            (r"\bd[oó]nde\s+est[áa]\b", 0.7),
        ),
    ),
)

#: Señal de que hay un escenario crudo en el input: sin esto, la mayoría de las
#: formas complejas no tienen material para trabajar.
_RAW_SCENARIO_RE = re.compile(
    r"(\brecord\b|\bregistro\b|\bevento\b|\bevent\b|\brow\b|\bfila\b|"
    r"\bsecuencia\b|\bsequence\b|\bA(\d{3})\b|\bB(\d{3})\b|\n\s*\d{1,3}[\s|;,\t])",
    re.IGNORECASE,
)

#: Pregunta atómica por forma (§9). El código compone la forma; el juez sólo
#: confirma o corrige dentro de la banda incierta.
_ATOMIC_QUESTIONS = {
    "combine_multiple_evidence": (
        "Does answering require combining several independent evidence items?"
    ),
    "chronology_matters": "Does chronological order materially affect the answer?",
    "describes_transitions": "Does the input describe state transitions?",
    "user_asks_hypothesis": "Does the user ask whether a hypothesis is true?",
    "consistency_between_events": (
        "Does the answer require checking consistency between events?"
    ),
    "single_authoritative_item": (
        "Can one authoritative evidence item directly answer the question?"
    ),
    "graph_contributes": "Does graph traversal materially contribute?",
}

_QUESTION_TO_SHAPE = {
    "describes_transitions": ReasoningShape.STATE_TRANSITION,
    "chronology_matters": ReasoningShape.TEMPORAL_SEQUENCE,
    "consistency_between_events": ReasoningShape.CONSISTENCY_CHECK,
    "user_asks_hypothesis": ReasoningShape.HYPOTHESIS_TEST,
    "graph_contributes": ReasoningShape.GRAPH_REASONING,
    "combine_multiple_evidence": ReasoningShape.MULTI_EVIDENCE,
}


def has_raw_scenario(text: str) -> bool:
    return bool(_RAW_SCENARIO_RE.search(text or ""))


def deterministic_shape(question: str, *, intent: str = "general") -> ReasoningClassification:
    """Clasificación léxica. Devuelve también la banda de incertidumbre."""
    text = " ".join((question or "").lower().split())
    scores: dict[ReasoningShape, float] = {}
    signals: list[str] = []
    for shape, patterns in _SHAPE_SIGNALS:
        score = 0.0
        for pattern, weight in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                score += weight
                signals.append(pattern)
        if score:
            scores[shape] = score
    if not scores:
        return ReasoningClassification(
            shape=ReasoningShape.SIMPLE_LOOKUP,
            intent=intent,
            confidence=0.4,
            signals=(),
            uncertain=False,
        )
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    shape, best = ordered[0]
    runner_up = ordered[1][1] if len(ordered) > 1 else 0.0
    total = sum(scores.values()) or 1.0
    confidence = min(0.95, 0.35 + 0.25 * min(best, 2.0) + 0.3 * (best - runner_up))
    # Una señal fuerte de lookup con material crudo no alcanza: hay escenario.
    raw = has_raw_scenario(question)
    if shape is ReasoningShape.SIMPLE_LOOKUP and raw and best < 1.0:
        confidence = min(confidence, UNCERTAIN_LOW)
    if shape is ReasoningShape.SIMPLE_LOOKUP and not raw:
        confidence = max(confidence, UNCERTAIN_HIGH)
    uncertain = UNCERTAIN_LOW <= confidence < UNCERTAIN_HIGH
    return ReasoningClassification(
        shape=shape,
        intent=intent,
        confidence=round(confidence, 4),
        signals=tuple(signals[:6]),
        uncertain=uncertain,
    )


def atomic_questions() -> dict[str, dict[str, Any]]:
    """Preguntas atómicas para el juez. Nunca "resolvé el problema"."""
    return {
        key: {
            "type": "noul",
            "instructions": text,
        }
        for key, text in _ATOMIC_QUESTIONS.items()
    }


def shape_from_atomic_answers(answers: dict[str, Any]) -> ReasoningShape | None:
    """Compone la forma desde señales atómicas (noul > 0.5 = sí)."""
    from src.decision.batch import noul_for

    def _noul(key: str) -> float:
        value = noul_for(answers, key, default=0.0)
        return float(value) if value is not None else 0.0

    best: ReasoningShape | None = None
    best_score = 0.0
    for key, shape in _QUESTION_TO_SHAPE.items():
        value = _noul(key)
        if value > 0.5 and value > best_score:
            best, best_score = shape, value
    if best is None:
        return None
    single = _noul("single_authoritative_item")
    graph = _noul("graph_contributes")
    if graph > 0.5 and best_score <= 0.7:
        return ReasoningShape.GRAPH_REASONING
    if single > 0.7 and best_score < 0.6:
        return ReasoningShape.SIMPLE_LOOKUP
    return best


Judge = Callable[..., Awaitable[dict | None]]


class ReasoningClassifier:
    """Clasificador de forma. Determinista; JEV sólo en banda incierta."""

    def __init__(
        self,
        *,
        judge: Judge | None = None,
        use_judge: bool = True,
    ) -> None:
        self._judge = judge
        self._use_judge = use_judge

    async def classify(
        self,
        question: str,
        *,
        intent: str = "general",
        state: dict | None = None,
    ) -> ReasoningClassification:
        base = deterministic_shape(question, intent=intent)
        if not self._use_judge or self._judge is None or not base.uncertain:
            return base
        try:
            payload = await self._judge(
                state={"user_request": (question or "")[:2000], **(state or {})},
                questions=atomic_questions(),
            )
        except Exception:  # noqa: BLE001 - el juez nunca bloquea la clasificación
            return base
        if not isinstance(payload, dict):
            return base
        answers = payload.get("answers") or {}
        shape = shape_from_atomic_answers(answers if isinstance(answers, dict) else {})
        if shape is None or shape is base.shape:
            return base
        return ReasoningClassification(
            shape=shape,
            intent=intent,
            confidence=0.7,
            source=ReasoningClassificationSource.HYBRID,
            signals=base.signals,
            uncertain=False,
        )


__all__ = [
    "ReasoningClassifier",
    "UNCERTAIN_HIGH",
    "UNCERTAIN_LOW",
    "atomic_questions",
    "deterministic_shape",
    "has_raw_scenario",
    "shape_from_atomic_answers",
]
