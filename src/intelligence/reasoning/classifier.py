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
    QueryMode,
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
            # «cierre», «secuencia» o «record» solos NO puntúan: son tópico.
            # Hace falta verbo de transición o un hueco explícito en la secuencia.
            (r"\bfalta\b.*\bregistro", 1.0),
            (r"\brenumer", 0.9),
            (r"\bestado\s+anterior", 0.6),
            (r"\bpas[oó]\s+de\b", 0.9),
            (r"\bde\s+abierto\s+a\s+cerrad", 1.0),
            (r"\btransici[oó]n", 0.8),
            (r"\btransition", 0.8),
            (r"\bdeber[ií]a\s+haber", 0.5),
            (r"\bpor\s+qu[ée]\s+cerr", 1.0),
            (r"\bqu[ée]\s+registro\s+caus", 0.9),
            (r"\bqu[ée]\s+secuencia\s+cerr", 0.9),
            (r"\bdespu[ée]s\s+de\s+cerrar\b", 0.9),
            (r"\bc[oó]mo\s+cambi[oó]\s+el\s+estado", 0.9),
        ),
    ),
    (
        ReasoningShape.TEMPORAL_SEQUENCE,
        (
            # «fecha», «vigencia», «Eff Date» solos son tópico, no cronología.
            (r"\borden\b", 0.7),
            (r"\bcronolog", 0.8),
            (r"\bantes\s+de\b", 0.5),
            (r"\bdespu[ée]s\s+de\b", 0.5),
            (r"\bel\s+a[ñn]o\s+pasado\b", 0.8),
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

#: Pedido de explicación. El tópico (record, cierre, fecha) no basta.
_INFORMATIONAL_RE = re.compile(
    r"(?:"
    r"\bcu[eé]ntame\s+(?:sobre|de)\b|"
    r"\bh[aá]blame\s+(?:de|sobre)\b|"
    r"\bexpl[ií]came\b|"
    r"\bc[oó]mo\s+funciona(?:n)?\b|"
    r"\bhow\s+does\b.{0,60}\bwork\b|"
    r"\bqu[eé]\s+es\b|"
    r"\bqu[eé]\s+significa\b|"
    r"\bdame\s+una\s+explicaci[oó]n\b|"
    r"\ben\s+general\b|"
    r"\boverview\b|"
    r"\btell\s+me\s+about\b|"
    r"\bexplain\b"
    r")",
    re.IGNORECASE,
)
_PROCEDURAL_RE = re.compile(
    r"\b(?:c[oó]mo\s+(?:hago|se\s+hace|puedo|procedo)|pasos\s+para|"
    r"how\s+(?:do\s+i|to)|procedimiento)\b",
    re.IGNORECASE,
)
_WHY_RE = re.compile(
    r"\b(?:por\s+qu[eé]|why\s+did|why\s+does|why\s+was)\b",
    re.IGNORECASE,
)
_INSTANCE_RE = re.compile(
    r"\b(?:tengo|tenemos|me\s+viene|me\s+lleg\w*|recib[ií]|en\s+este\s+caso|"
    r"con\s+estos\s+datos|i\s+have|i\s+received|in\s+this\s+case)\b",
    re.IGNORECASE,
)
_DEICTIC_RE = re.compile(
    r"\b(?:esta\s+secuencia|este\s+registro|estos\s+registros|"
    r"this\s+sequence|this\s+record)\b",
    re.IGNORECASE,
)
_TRANSITIONISH_RE = re.compile(
    r"\b(?:falt\w*|cerr\w*|aplic\w*|termin\w*|ocurri\w*|pas[oó]|caus\w*|cambi[oó])\b",
    re.IGNORECASE,
)
_EXPLICIT_TRANSITION_RE = re.compile(
    r"(?:"
    r"\bpas[oó]\s+de\b.{0,80}\ba\b|"
    r"\bde\s+abierto\s+a\s+cerrad\w*|"
    r"\bqu[ée]\s+registro\s+caus\w*|"
    r"\bqu[ée]\s+secuencia\s+cerr\w*|"
    r"\bdespu[ée]s\s+de\s+cerrar\b|"
    r"\bc[oó]mo\s+cambi[oó]\s+el\s+estado|"
    r"\bpor\s+qu[ée]\s+cerr\w*"
    r")",
    re.IGNORECASE,
)
_DATE_TOKEN_RE = re.compile(
    r"\b\d{1,2}(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\d{0,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    re.IGNORECASE,
)
_MASK_RE = re.compile(r"[&%#*]{2,}")
_ROW_RE = re.compile(r"\|.+\|")
_RECORD_TYPE_RE = re.compile(r"\b(?:record|registro)\s+\d{1,2}\b", re.IGNORECASE)
_EXECUTABLE_INTENTS = frozenset(
    {"APPLY_RULE", "VALIDATE", "COMPARE", "CALCULATE", "TRANSFORM", "INFER"}
)
_STRONG_VERDICT_RE = re.compile(
    r"\b(?:cumpl\w*|valid\w*|verific\w*|coincid\w*|matche\w*|"
    r"elegib\w*|permitid\w*|prohibid\w*|aprob\w*)\b",
    re.IGNORECASE,
)
_BROAD_PAIR_RE = re.compile(
    r"\b(?:eff(?:ective)?\s+date|disc(?:ontinue)?\s+date)\b",
    re.IGNORECASE,
)

REASON_INFORMATIONAL = "informational_request_without_concrete_scenario"
REASON_SCENARIO = "concrete_scenario_payload"
REASON_EXECUTABLE = "executable_rule_application"
REASON_PROCEDURAL = "procedural_request"
REASON_DIAGNOSTIC = "diagnostic_request"
REASON_LEXICAL = "lexical_shape"

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


def is_informational_request(text: str) -> bool:
    """¿El turno pide explicación o conocimiento, no una instancia?"""
    return bool(_INFORMATIONAL_RE.search(text or ""))


def _enumerated_sequences(text: str) -> bool:
    if not re.search(r"\b(?:secuencias?|sequences?|seq)\b", text or "", re.IGNORECASE):
        return False
    return len(re.findall(r"\b\d{3,}\b", text or "")) >= 2


def _broad_explanation(text: str) -> bool:
    names = _BROAD_PAIR_RE.findall(text or "")
    if len({name.lower().replace(" ", "") for name in names}) >= 2:
        return True
    return bool(
        re.search(
            r"\b(?:varias\s+fuentes|seg[uú]n\s+los\s+documentos|combinando)\b",
            text or "",
            re.IGNORECASE,
        )
    )


def has_concrete_scenario_payload(question: str) -> bool:
    """¿Hay una instancia concreta, no sólo el nombre de una entidad técnica?

    «Record 2» es un tipo. Una secuencia con valores, una fila, un par
    campo=valor o una transición explícita sí es escenario.
    """
    text = question or ""
    if not text.strip():
        return False
    if _ROW_RE.search(text):
        return True
    if _enumerated_sequences(text):
        return True
    if _EXPLICIT_TRANSITION_RE.search(text):
        return True
    if _DEICTIC_RE.search(text) and _TRANSITIONISH_RE.search(text):
        return True
    stripped = _RECORD_TYPE_RE.sub(" ", text)
    has_value = bool(
        _DATE_TOKEN_RE.search(stripped)
        or _MASK_RE.search(text)
        or re.search(r"\b\d{3,}\b", stripped)
    )
    if _INSTANCE_RE.search(text) and has_value:
        return True
    return False


def has_raw_scenario(text: str) -> bool:
    """Compatibilidad: escenario crudo == payload concreto, no la palabra record."""
    return has_concrete_scenario_payload(text)


def why_instance_not_executable(text: str) -> bool:
    """«¿Por qué terminó aplicando la 3000?» no es un veredicto binario.

    Un patrón (`&&&F`) o un verbo de comprobación fuerte siguen siendo
    ejecutables aunque haya un «por qué».
    """
    body = text or ""
    if not _WHY_RE.search(body):
        return False
    if _MASK_RE.search(body) or _STRONG_VERDICT_RE.search(body):
        return False
    return has_concrete_scenario_payload(body)


def instance_diagnosis_not_executable(text: str) -> bool:
    """Transición o secuencia concreta sin veredicto binario.

    La palabra «match» como tópico no convierte «qué secuencia cerró» en
    una comprobación ejecutable. ``&&&F`` y «cumple» sí lo siguen siendo.
    """
    if why_instance_not_executable(text):
        return True
    body = text or ""
    if _MASK_RE.search(body) or _STRONG_VERDICT_RE.search(body):
        return False
    if not has_concrete_scenario_payload(body):
        return False
    return bool(_EXPLICIT_TRANSITION_RE.search(body) or _enumerated_sequences(body))


def _is_executable_query(question: str) -> bool:
    if instance_diagnosis_not_executable(question):
        return False
    try:
        from src.intelligence.query_semantics import classify_query_semantics
    except Exception:  # noqa: BLE001 — sin semántica no se inventa un ejecutable
        return False
    semantics = classify_query_semantics(question)
    intent = str(getattr(semantics, "intent", "") or "").upper()
    if intent in _EXECUTABLE_INTENTS:
        return True
    return bool(tuple(getattr(semantics, "runtime_patterns", ()) or ()))


def _lexical_scores(text: str) -> tuple[dict[ReasoningShape, float], list[str]]:
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
    concrete = has_concrete_scenario_payload(text)
    if concrete and re.search(r"\b(?:secuencia|sequence)s?\b", text, re.IGNORECASE):
        if re.search(r"\b(?:aplic|termin|falt|cerr|por\s+qu)\b", text, re.IGNORECASE):
            scores[ReasoningShape.STATE_TRANSITION] = (
                scores.get(ReasoningShape.STATE_TRANSITION, 0.0) + 0.9
            )
            signals.append("concrete_sequence")
    if concrete and _DATE_TOKEN_RE.search(text) and re.search(
        r"\b(?:orden|cronolog|antes|despu|timeline)\b", text, re.IGNORECASE
    ):
        scores[ReasoningShape.TEMPORAL_SEQUENCE] = (
            scores.get(ReasoningShape.TEMPORAL_SEQUENCE, 0.0) + 0.85
        )
        signals.append("concrete_dates")
    return scores, signals


def _classification(
    *,
    shape: ReasoningShape,
    intent: str,
    confidence: float,
    signals: tuple[str, ...],
    uncertain: bool,
    query_mode: QueryMode | None,
    scenario_payload: bool,
    routing_reason: str,
) -> ReasoningClassification:
    return ReasoningClassification(
        shape=shape,
        intent=intent,
        confidence=round(confidence, 4),
        signals=signals,
        uncertain=uncertain,
        query_mode=query_mode,
        scenario_payload=scenario_payload,
        routing_reason=routing_reason,
    )


def deterministic_shape(question: str, *, intent: str = "general") -> ReasoningClassification:
    """Clasificación léxica. Devuelve también la banda de incertidumbre.

    QueryMode es un eje aparte: una explicación sobre Record 2 no hereda
    el modo del turno anterior ni activa el pipeline de escenario.
    """
    original = question or ""
    text = " ".join(original.lower().split())
    concrete = has_concrete_scenario_payload(original)
    informational = (
        is_informational_request(original)
        and not concrete
        and not _MASK_RE.search(original)
    )
    if informational:
        shape = (
            ReasoningShape.MULTI_EVIDENCE
            if _broad_explanation(original)
            else ReasoningShape.SIMPLE_LOOKUP
        )
        return _classification(
            shape=shape,
            intent=intent,
            confidence=0.9,
            signals=tuple(sig for sig in ("informational_request",) if sig),
            uncertain=False,
            query_mode=QueryMode.INFORMATIONAL,
            scenario_payload=False,
            routing_reason=REASON_INFORMATIONAL,
        )

    executable = _is_executable_query(original)
    scores, signals = _lexical_scores(text)
    if not scores:
        shape: ReasoningShape = ReasoningShape.SIMPLE_LOOKUP
        best = 0.0
        runner_up = 0.0
    else:
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        shape, best = ordered[0]
        runner_up = ordered[1][1] if len(ordered) > 1 else 0.0
    if not scores:
        confidence = 0.4
        uncertain = False
    else:
        confidence = min(0.95, 0.35 + 0.25 * min(best, 2.0) + 0.3 * (best - runner_up))
        if shape is ReasoningShape.SIMPLE_LOOKUP and concrete and best < 1.0:
            confidence = min(confidence, UNCERTAIN_LOW)
        if shape is ReasoningShape.SIMPLE_LOOKUP and not concrete:
            confidence = max(confidence, UNCERTAIN_HIGH)
        uncertain = UNCERTAIN_LOW <= confidence < UNCERTAIN_HIGH

    scenario_material = concrete and (
        _enumerated_sequences(original)
        or bool(_EXPLICIT_TRANSITION_RE.search(original))
        or (bool(_WHY_RE.search(original)) and not executable)
        or (bool(_DEICTIC_RE.search(original)) and bool(_TRANSITIONISH_RE.search(original)))
    )
    if scenario_material and not executable:
        if shape not in {
            ReasoningShape.STATE_TRANSITION,
            ReasoningShape.TEMPORAL_SEQUENCE,
            ReasoningShape.CONSISTENCY_CHECK,
            ReasoningShape.DIAGNOSTIC,
            ReasoningShape.CAUSAL_ANALYSIS,
            ReasoningShape.HYPOTHESIS_TEST,
        }:
            shape = ReasoningShape.STATE_TRANSITION
        if _enumerated_sequences(original) or _EXPLICIT_TRANSITION_RE.search(original):
            shape = ReasoningShape.STATE_TRANSITION
        return _classification(
            shape=shape,
            intent=intent,
            confidence=max(confidence, 0.86),
            signals=tuple(signals[:6]),
            uncertain=False,
            query_mode=QueryMode.SCENARIO,
            scenario_payload=True,
            routing_reason=REASON_SCENARIO,
        )
    if executable:
        return _classification(
            shape=shape,
            intent=intent,
            confidence=max(confidence, 0.8),
            signals=tuple(signals[:6]),
            uncertain=False,
            query_mode=QueryMode.EXECUTABLE,
            scenario_payload=concrete,
            routing_reason=REASON_EXECUTABLE,
        )
    procedural = bool(_PROCEDURAL_RE.search(original)) and not concrete
    if procedural:
        return _classification(
            shape=ReasoningShape.SIMPLE_LOOKUP,
            intent=intent,
            confidence=0.84,
            signals=tuple(signals[:6]),
            uncertain=False,
            query_mode=QueryMode.PROCEDURAL,
            scenario_payload=False,
            routing_reason=REASON_PROCEDURAL,
        )
    mode: QueryMode | None = None
    reason = REASON_LEXICAL
    if shape is ReasoningShape.STATE_TRANSITION:
        mode = QueryMode.SCENARIO
        reason = REASON_SCENARIO if concrete else REASON_LEXICAL
    elif shape is ReasoningShape.DIAGNOSTIC:
        mode = QueryMode.DIAGNOSTIC
        reason = REASON_DIAGNOSTIC
    elif concrete and shape in {
        ReasoningShape.TEMPORAL_SEQUENCE,
        ReasoningShape.CONSISTENCY_CHECK,
        ReasoningShape.HYPOTHESIS_TEST,
    }:
        mode = QueryMode.SCENARIO
        reason = REASON_SCENARIO
    return _classification(
        shape=shape,
        intent=intent,
        confidence=confidence,
        signals=tuple(signals[:6]),
        uncertain=uncertain,
        query_mode=mode,
        scenario_payload=concrete,
        routing_reason=reason,
    )


def format_query_route(
    *,
    query_mode: str,
    shape: str,
    blueprint: str,
    scenario_payload: bool,
    complex_reasoning_activated: bool,
    routing_reason: str,
) -> str:
    """Bloque de telemetría del turno. Una línea por campo, sin abreviar."""
    return (
        f"Query mode:\n{query_mode}\n\n"
        f"Reasoning shape:\n{shape}\n\n"
        f"Response blueprint:\n{blueprint}\n\n"
        f"Scenario payload:\n{str(bool(scenario_payload)).lower()}\n\n"
        f"Complex reasoning activated:\n{str(bool(complex_reasoning_activated)).lower()}\n\n"
        f"routing_reason:\n{routing_reason}"
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
        # JEV no decide si una explicación o un ejecutable es análisis de escenario.
        if base.query_mode in {QueryMode.INFORMATIONAL, QueryMode.EXECUTABLE}:
            return base
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
            query_mode=base.query_mode,
            scenario_payload=base.scenario_payload,
            routing_reason=base.routing_reason,
        )


__all__ = [
    "REASON_DIAGNOSTIC",
    "REASON_EXECUTABLE",
    "REASON_INFORMATIONAL",
    "REASON_LEXICAL",
    "REASON_PROCEDURAL",
    "REASON_SCENARIO",
    "ReasoningClassifier",
    "UNCERTAIN_HIGH",
    "UNCERTAIN_LOW",
    "atomic_questions",
    "deterministic_shape",
    "format_query_route",
    "has_concrete_scenario_payload",
    "has_raw_scenario",
    "instance_diagnosis_not_executable",
    "is_informational_request",
    "shape_from_atomic_answers",
    "why_instance_not_executable",
]
