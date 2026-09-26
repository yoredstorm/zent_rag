# =============================================================================
# Turn intent — qué está haciendo el usuario en este turno (antes de retrieval).
# =============================================================================
# Regresión real: «hola como estas» con un agente que tiene search_knowledge
# terminaba en INSUFFICIENT_ANSWER porque el Answer Gate documental exigía
# fuentes para un saludo. El problema conceptual era uno solo:
#
#     «¿necesito conocimiento para responder?» != «¿puedo responder?»
#
# Esta capa produce una SEÑAL (no un route): intención conversacional + su
# distribución + si el turno necesita evidencia externa. La política compone el
# route en código (`decide_route`). JEV clasifica; el generador escribe.
#
# Reglas no negociables:
#   - Reglas para lo obvio, JEV para la ambigüedad semántica (nunca JEV siempre).
#   - Sólo se publican probabilidades que JEV devuelve; las reglas publican
#     confianza, no una distribución inventada.
#   - Un turno mixto («me estás respondiendo mal, explicame el byte 105»)
#     conserva la intención material (conocimiento) y registra la secundaria.
#   - Sin evidencia externa requerida, el gate documental no aplica (§7).
# =============================================================================
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.decision.batch import answer_for, noul_for
from src.decision.judgment import PHASE_PRE_RETRIEVAL, JudgmentContext, call_phase_judge
from src.infrastructure.observability.logging_config import get_logger
from src.runtime.jev_state import StateSection, build_jev_state

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Vocabulario e intención funcional (sin sentiment analysis)
# -----------------------------------------------------------------------------

TURN_INTENTS: tuple[str, ...] = (
    "knowledge_question",
    "social_conversation",
    "greeting",
    "gratitude",
    "farewell",
    "complaint",
    "capability_question",
    "action_request",
    "contextual_followup",
    "clarification",
    "ambiguous",
)

#: Descripciones para el Choice de JEV. `knowledge_question` primero: los fakes
#: que devuelven la primera opción no alteran el comportamiento documental.
INTENT_CRITERIA: dict[str, str] = {
    "knowledge_question": (
        "The user asks for information, an explanation, a definition, a value, or "
        "data that lives in documents or databases."
    ),
    "social_conversation": (
        "Small talk, pleasantries, or a social check-in (how are you, how is it "
        "going) that does not request information."
    ),
    "greeting": "An opening salutation (hello, hi, good morning). Not a request.",
    "gratitude": "Thanks or appreciation for something already done.",
    "farewell": "A goodbye or closing of the conversation.",
    "complaint": (
        "The user expresses dissatisfaction with the assistant, the answer, or "
        "the service. Not a factual question by itself."
    ),
    "capability_question": (
        "Asks what the assistant can do, who it is, which tools or sources it "
        "has, or how to use it."
    ),
    "action_request": (
        "Asks the assistant to perform an action: run a process, create, send, "
        "update, delete, or execute a tool/workflow."
    ),
    "contextual_followup": (
        "A short follow-up that refers to the previous turn without restating "
        "its topic ('y el 5?', 'and then?', 'por que?')."
    ),
    "clarification": (
        "Too short or vague to tell what the user wants and there is no "
        "conversation context to resolve it."
    ),
    "ambiguous": "None of the above is clear from the request and the state.",
}

CONVERSATIONAL_INTENTS = frozenset(
    {"greeting", "gratitude", "farewell", "social_conversation"}
)
DIRECT_INTENTS = CONVERSATIONAL_INTENTS | {
    "complaint",
    "capability_question",
    "clarification",
}
FACTUAL_INTENTS = frozenset({"knowledge_question", "action_request"})

ROUTE_DIRECT = "direct"
ROUTE_CONTEXT = "context"
ROUTE_KNOWLEDGE = "knowledge"
ROUTE_TOOL = "tool"
ROUTE_CLARIFY = "clarify"

DIRECT_ROUTES = frozenset({ROUTE_DIRECT, ROUTE_CONTEXT, ROUTE_CLARIFY})

MODEL_TIER_FAST = "fast"
MODEL_TIER_DEFAULT = "default"

#: Confianza de las reglas por familia (no es una probabilidad de JEV).
_RULES_OBVIOUS_CONFIDENCE = 0.95
_RULES_KNOWLEDGE_CONFIDENCE = 0.85
_RULES_ACTION_CONFIDENCE = 0.85
_RULES_COMPLAINT_CONFIDENCE = 0.80
_RULES_FOLLOWUP_CONFIDENCE = 0.70
_RULES_FALLBACK_CONFIDENCE = 0.50

# -----------------------------------------------------------------------------
# Reglas deterministas (chicas a propósito: lo obvio, no una lista infinita)
# -----------------------------------------------------------------------------

#: Casos absolutamente obvios: el mensaje ES el acto conversacional.
_OBVIOUS_INTENT: dict[str, str] = {
    "hola": "greeting",
    "hello": "greeting",
    "hi": "greeting",
    "hey": "greeting",
    "buenas": "greeting",
    "buenos dias": "greeting",
    "buenas tardes": "greeting",
    "buenas noches": "greeting",
    "gracias": "gratitude",
    "muchas gracias": "gratitude",
    "mil gracias": "gratitude",
    "thanks": "gratitude",
    "thank you": "gratitude",
    "chau": "farewell",
    "adios": "farewell",
    "bye": "farewell",
    "nos vemos": "farewell",
    "hasta luego": "farewell",
}
_OBVIOUS_CLEAN_RE = re.compile(r"[^\wáéíóúñü\s]+", re.IGNORECASE)

_CAPABILITY_RE = re.compile(
    r"(?:\b(?:qu[eé]|que)\s+(?:puedes|pod[eé]s|sabes)\s+hacer\b)"
    r"|(?:\ben\s+qu[eé]\s+me\s+(?:puedes|pod[eé]s)\s+ayudar\b)"
    r"|(?:\b(?:qui[eé]n|que|qu[eé])\s+eres\b)"
    r"|(?:\bqu[eé]\s+(?:herramientas|fuentes|archivos|documentos|datos)\b)"
    r"|(?:\bqu[eé]\s+sabes\s+hacer\b)"
    r"|(?:\bpara\s+qu[eé]\s+sirves\b)"
    r"|(?:\bwhat\s+can\s+you\s+do\b)"
    r"|(?:\bwho\s+are\s+you\b)",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"\b(ejecuta|ejecut[aá]|ejecutar|corre|corr[eé]|lanza|lanz[aá]|dispara|"
    r"crea|cre[aá]|env[ií]a|envi[aá]|actualiza|elimina|borra|programa|agenda|"
    r"inicia|inici[aá]|run|execute|deploy|usa|us[aá]|usar|llama|llam[aá]|"
    r"invoca|graba|grab[aá]|guarda|guard[aá]|registra|registr[aá]|manda|"
    r"mand[aá]|procesa|proces[aá])\b",
    re.IGNORECASE,
)
_KNOWLEDGE_RE = re.compile(
    r"\b(significa|significan|explica|expl[ií]came|explicame|definici[oó]n|"
    r"definime|dime|detalla|detallame|describe|descripci[oó]n|diferencia|"
    r"funciona|qu[eé]\s+es|que\s+es|qu[eé]\s+son|que\s+son|cu[aá]nto|cuanto|"
    r"cu[aá]ntos|cuantos|pol[ií]tica|regla|tabla|record|campo|valor)\b",
    re.IGNORECASE,
)
_QUESTION_WORD_RE = re.compile(
    r"\b(qu[eé]|que|qui[eé]n|quien|cu[aá]l|cual|cu[aá]les|cuales|cu[aá]ndo|"
    r"cuando|d[oó]nde|donde|por\s+qu[eé]|por\s+que|porque|para\s+qu[eé]|"
    r"para\s+que)\b",
    re.IGNORECASE,
)
_SOCIAL_FALSE_KNOWLEDGE_RE = re.compile(
    r"(?:c[oó]mo\s+est[aá]s|como\s+estas|c[oó]mo\s+and[aá]s|como\s+andas|"
    r"qu[eé]\s+tal|que\s+tal|c[oó]mo\s+va\b|como\s+va\b|c[oó]mo\s+te\s+va|"
    r"todo\s+bien|qu[eé]\s+haces|que\s+haces|qu[eé]\s+onda|que\s+onda)",
    re.IGNORECASE,
)
_COMPLAINT_RE = re.compile(
    r"(?:no\s+sirve|no\s+funciona|no\s+me\s+sirve|no\s+(?:est[aá]|esta)\s+"
    r"funcionando|no\s+me\s+est[aá]\s+funcionando|respondes\s+mal|me\s+est[aá]s\s+"
    r"respondiendo|respuesta\s+tan\s+(?:mala|p[eé]sima|horrible)|respuesta\s+"
    r"(?:mala|p[eé]sima|horrible)|qu[eé]\s+mal|que\s+mal|est[aá]\s+mal|esta\s+mal|"
    r"no\s+entendiste|no\s+entend[eé]s|no\s+entendes|no\s+me\s+entendiste|"
    r"otra\s+vez\s+(?:est[aá]|esta|falla)|est[aá]\s+fallando|esta\s+fallando|"
    r"es\s+una\s+(?:basura|porquer[ií]a|porqueria)|decepcionante|"
    r"no\s+me\s+gusta\s+(?:la|tu)\s+respuesta)",
    re.IGNORECASE,
)
#: Referencias de follow-up: SIEMPRE al arranque («y el 5?», «eso?»). Un «el»
#: suelto en una pregunta normal («quién es el gerente») no es un follow-up.
_FOLLOWUP_START_RE = re.compile(
    r"^\s*(?:y\s+)?(?:eso|esto|esa|ese|aquello|aquella|el\s+\d+|la\s+\d+|\d+)\b",
    re.IGNORECASE,
)

#: Señales de que un follow-up pide un dato y no sólo compañía.
_FACTUAL_FOLLOWUP_RE = re.compile(
    r"\b(\d+|valor|significa|significan|cu[aá]l|cual|por\s+qu[eé]|por\s+que|"
    r"c[oó]mo|como|d[oó]nde|donde|cu[aá]ndo|cuando)\b",
    re.IGNORECASE,
)


def identify_obvious_intent(message: str) -> str | None:
    """El mensaje ES un saludo/agradecimiento/despedida y nada más."""
    limpio = _OBVIOUS_CLEAN_RE.sub(" ", (message or "").strip().lower())
    normalizado = " ".join(limpio.split())
    return _OBVIOUS_INTENT.get(normalizado)


def _signals(message: str) -> list[str]:
    """Señales deterministas presentes (hechos del texto, no opiniones)."""
    texto = message or ""
    señales: list[str] = []
    if _CAPABILITY_RE.search(texto):
        señales.append("capability")
    if _ACTION_RE.search(texto):
        señales.append("action")
    if _COMPLAINT_RE.search(texto):
        señales.append("complaint")
    if _KNOWLEDGE_RE.search(texto):
        señales.append("knowledge_verb")
    if _QUESTION_WORD_RE.search(texto):
        señales.append("question_word")
    if _SOCIAL_FALSE_KNOWLEDGE_RE.search(texto):
        señales.append("social")
    try:
        from src.intelligence.response.entities import asked_entities

        entidades = asked_entities(texto)
    except Exception:  # noqa: BLE001 — las reglas nunca rompen por un import
        entidades = []
    if entidades:
        señales.append("entity")
    return señales


def _decision(
    *,
    intent: str,
    confidence: float,
    provider: str,
    route: str,
    needs_external_evidence: bool,
    evidence_source: str,
    model_tier: str,
    signals: list[str] | tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    probabilities: Mapping[str, float] | None = None,
    knowledge_probability: float | None = None,
    latency_ms: float = 0.0,
    answers: Mapping[str, Any] | None = None,
) -> "TurnIntentDecision":
    return TurnIntentDecision(
        intent=intent,
        confidence=round(float(confidence), 4),
        probabilities=dict(probabilities or {}),
        provider=provider,
        needs_external_evidence=bool(needs_external_evidence),
        evidence_source=evidence_source,
        route=route,
        model_tier=model_tier,
        knowledge_probability=(
            round(float(knowledge_probability), 4)
            if knowledge_probability is not None
            else (
                round(float(dict(probabilities or {}).get("knowledge_question") or 0.0), 4)
                if probabilities
                else (1.0 if intent == "knowledge_question" else 0.0)
            )
        ),
        signals=tuple(signals),
        reasons=tuple(reasons),
        latency_ms=round(float(latency_ms), 2),
        answers=dict(answers or {}),
    )


def rules_turn_intent(message: str, *, has_context: bool = False) -> "TurnIntentDecision | None":
    """Clasificación determinista. `None` = ambiguo: decide JEV.

    Casos obvios (el mensaje ES el acto), entidades, verbos de conocimiento,
    acciones y quejas. «hola como estas», «gracias pero no entendi» y demás
    mixturas quedan para JEV a propósito.
    """
    texto = (message or "").strip()
    if not texto:
        return None
    señales = _signals(texto)
    obvio = identify_obvious_intent(texto)

    if "capability" in señales:
        return _decision(
            intent="capability_question",
            confidence=_RULES_OBVIOUS_CONFIDENCE,
            provider="rules",
            route=ROUTE_DIRECT,
            needs_external_evidence=False,
            evidence_source="rules",
            model_tier=MODEL_TIER_DEFAULT,
            signals=señales,
            reasons=("configuracion_del_agente_no_documentos",),
        )
    if "entity" in señales or "knowledge_verb" in señales:
        return _decision(
            intent="knowledge_question",
            confidence=_RULES_KNOWLEDGE_CONFIDENCE,
            provider="rules",
            route=ROUTE_KNOWLEDGE,
            needs_external_evidence=True,
            evidence_source="rules",
            model_tier=MODEL_TIER_DEFAULT,
            signals=señales,
            reasons=("entidad_o_verbo_de_conocimiento",),
        )
    if "question_word" in señales and "social" not in señales:
        tokens = [token for token in re.split(r"\s+", texto) if token]
        if len(tokens) <= 2:
            # «¿quién?», «¿qué?» sin objeto: cabe pedir aclaración, no buscar.
            return _decision(
                intent="clarification",
                confidence=_RULES_FOLLOWUP_CONFIDENCE,
                provider="rules",
                route=ROUTE_CLARIFY,
                needs_external_evidence=False,
                evidence_source="rules",
                model_tier=MODEL_TIER_FAST,
                signals=señales,
                reasons=("pregunta_sin_objeto",),
            )
        if len(tokens) >= 3:
            return _decision(
                intent="knowledge_question",
                confidence=_RULES_KNOWLEDGE_CONFIDENCE - 0.05,
                provider="rules",
                route=ROUTE_KNOWLEDGE,
                needs_external_evidence=True,
                evidence_source="rules",
                model_tier=MODEL_TIER_DEFAULT,
                signals=señales,
                reasons=("pregunta_con_objeto",),
            )
    if "action" in señales:
        return _decision(
            intent="action_request",
            confidence=_RULES_ACTION_CONFIDENCE,
            provider="rules",
            route=ROUTE_TOOL,
            needs_external_evidence=True,
            evidence_source="rules",
            model_tier=MODEL_TIER_DEFAULT,
            signals=señales,
            reasons=("verbo_de_accion",),
        )
    if "complaint" in señales and "?" not in texto:
        return _decision(
            intent="complaint",
            confidence=_RULES_COMPLAINT_CONFIDENCE,
            provider="rules",
            route=ROUTE_DIRECT,
            needs_external_evidence=False,
            evidence_source="rules",
            model_tier=MODEL_TIER_DEFAULT,
            signals=señales,
            reasons=("queja_sin_pregunta_factual",),
        )
    if obvio is not None:
        return _decision(
            intent=obvio,
            confidence=_RULES_OBVIOUS_CONFIDENCE,
            provider="rules",
            route=ROUTE_DIRECT,
            needs_external_evidence=False,
            evidence_source="rules",
            model_tier=MODEL_TIER_FAST,
            signals=señales,
            reasons=("acto_conversacional_obvio",),
        )
    # Follow-up corto («y el 5?», «eso?»): con contexto se puede resolver; sin
    # contexto sólo cabe pedir una aclaración. La referencia tiene que ABRIR el
    # mensaje: «quién es el gerente» no es un follow-up.
    tokens = [token for token in re.split(r"\s+", texto) if token]
    if len(tokens) <= 6 and _FOLLOWUP_START_RE.match(texto):
        if has_context:
            factual = bool(_FACTUAL_FOLLOWUP_RE.search(texto))
            return _decision(
                intent="contextual_followup",
                confidence=_RULES_FOLLOWUP_CONFIDENCE,
                provider="rules",
                route=ROUTE_KNOWLEDGE if factual else ROUTE_CONTEXT,
                needs_external_evidence=factual,
                evidence_source="rules",
                model_tier=MODEL_TIER_DEFAULT,
                signals=señales,
                reasons=(
                    "followup_factual_con_contexto"
                    if factual
                    else "followup_social_con_contexto",
                ),
            )
        return _decision(
            intent="clarification",
            confidence=_RULES_FOLLOWUP_CONFIDENCE - 0.05,
            provider="rules",
            route=ROUTE_CLARIFY,
            needs_external_evidence=False,
            evidence_source="rules",
            model_tier=MODEL_TIER_DEFAULT,
            signals=señales,
            reasons=("referencia_sin_contexto",),
        )
    return None


# -----------------------------------------------------------------------------
# Preguntas JEV (misma fase PRE_RETRIEVAL, misma llamada batcheada)
# -----------------------------------------------------------------------------


def build_turn_intent_questions() -> dict[str, dict]:
    """Choice de intención + Noul de necesidad de evidencia externa."""
    return {
        "conversation_intent": {
            "type": "choice",
            "instructions": (
                "What is the user DOING in `user_request` given "
                "`conversation_state`? Classify the conversational act, not the "
                "topic. If the message mixes acts, pick the one that determines "
                "what the turn needs (a factual request keeps knowledge_question)."
            ),
            "criteria": INTENT_CRITERIA,
        },
        "needs_external_evidence": {
            "type": "noul",
            "instructions": (
                "Does answering `user_request` require facts from private "
                "documents, databases or tools that are not in the request or in "
                "`conversation_state`? Greetings, thanks, goodbyes, small talk, "
                "complaints about the conversation, clarification requests and "
                "questions about the assistant's own capabilities do NOT require "
                "external evidence."
            ),
        },
    }


def build_turn_intent_state(
    *,
    message: str,
    conversation_state: Mapping[str, Any] | None = None,
    agent_purpose: str = "",
    max_chars: int = 4000,
) -> Any:
    """Estado chico: request + resumen de conversación + propósito del agente."""
    import json

    try:
        resumen = json.dumps(
            {str(key): value for key, value in (conversation_state or {}).items()},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError):
        resumen = str(conversation_state or {})
    sections = [
        StateSection("user_request", 1, (message or "")[:2000]),
        StateSection("conversation_state", 2, resumen[:1500]),
        StateSection("agent_purpose", 3, (agent_purpose or "")[:600]),
    ]
    return build_jev_state(sections, max_chars=max_chars)


# -----------------------------------------------------------------------------
# Política (señal -> route; el código decide, JEV no ejecuta)
# -----------------------------------------------------------------------------


def _thresholds(settings: Any) -> tuple[float, float, float, float, float]:
    def _leer(nombre: str, default: float) -> float:
        try:
            return float(getattr(settings, nombre, default) or default)
        except (TypeError, ValueError):
            return default

    return (
        _leer("RUNTIME_TURN_INTENT_RULES_CONFIDENCE", 0.80),
        _leer("RUNTIME_TURN_INTENT_KNOWLEDGE_FLOOR", 0.30),
        _leer("RUNTIME_TURN_INTENT_ACTION_FLOOR", 0.35),
        _leer("RUNTIME_TURN_INTENT_CONVERSATIONAL_FLOOR", 0.60),
        _leer("RUNTIME_TURN_INTENT_AMBIGUOUS_FLOOR", 0.45),
    )


def _conversational_mass(probabilities: Mapping[str, float]) -> float:
    return sum(
        float(probabilities.get(intent) or 0.0) for intent in CONVERSATIONAL_INTENTS
    )


def decide_route(
    *,
    intent: str,
    confidence: float,
    probabilities: Mapping[str, float] | None = None,
    needs_external_evidence: bool | None = None,
    has_context: bool = False,
    settings: Any = None,
) -> tuple[str, bool, str, str]:
    """Compone (route, needs_external_evidence, evidence_source, model_tier).

    No alcanza con `choice == greeting`: se mira la distribución completa. Una
    intención secundaria material (conocimiento por encima del piso) manda.
    """
    (
        rules_confidence,
        knowledge_floor,
        action_floor,
        conversational_floor,
        ambiguous_floor,
    ) = _thresholds(settings)
    probs = {str(key): float(value or 0.0) for key, value in (probabilities or {}).items()}
    knowledge_prob = float(
        probs.get("knowledge_question")
        or (1.0 if intent == "knowledge_question" else 0.0)
    )
    action_prob = float(
        probs.get("action_request") or (1.0 if intent == "action_request" else 0.0)
    )
    capability_prob = float(probs.get("capability_question") or 0.0)
    conv_mass = _conversational_mass(probs) if probs else (
        1.0 if intent in CONVERSATIONAL_INTENTS else 0.0
    )

    factual = intent in FACTUAL_INTENTS or knowledge_prob >= knowledge_floor
    if intent == "contextual_followup":
        # Un follow-up factual necesita evidencia; uno social no.
        factual = bool(needs_external_evidence) if needs_external_evidence is not None else False
    if intent == "complaint":
        factual = knowledge_prob >= knowledge_floor
    if action_prob >= action_floor:
        # Pedir una acción no es responder de memoria: el route TOOL ejecuta.
        factual = True
    needs = bool(factual)
    if needs_external_evidence is True:
        needs = True
        knowledge_prob = max(knowledge_prob, 1.0)
    elif (
        needs_external_evidence is False
        and intent in DIRECT_INTENTS
        and knowledge_prob < knowledge_floor
        and action_prob < action_floor
    ):
        needs = False

    if needs and action_prob >= action_floor and action_prob >= knowledge_prob:
        return ROUTE_TOOL, True, "policy", MODEL_TIER_DEFAULT
    if needs:
        return ROUTE_KNOWLEDGE, True, "policy", MODEL_TIER_DEFAULT
    if intent == "capability_question" or capability_prob >= 0.5:
        return ROUTE_DIRECT, False, "policy", MODEL_TIER_DEFAULT
    if intent == "clarification":
        return ROUTE_CLARIFY, False, "policy", MODEL_TIER_FAST
    if intent == "contextual_followup":
        if has_context:
            return ROUTE_CONTEXT, False, "policy", MODEL_TIER_DEFAULT
        return ROUTE_CLARIFY, False, "policy", MODEL_TIER_FAST
    if conv_mass >= conversational_floor:
        tier = MODEL_TIER_FAST if intent in CONVERSATIONAL_INTENTS else MODEL_TIER_DEFAULT
        return ROUTE_DIRECT, False, "policy", tier
    if intent in DIRECT_INTENTS and float(confidence or 0.0) >= ambiguous_floor:
        # Queja/aclaración con confianza suficiente: respuesta directa, aunque su
        # familia no sume masa conversacional.
        tier = MODEL_TIER_FAST if intent in CONVERSATIONAL_INTENTS else MODEL_TIER_DEFAULT
        return ROUTE_DIRECT, False, "policy", tier
    if float(confidence or 0.0) < ambiguous_floor:
        if has_context:
            return ROUTE_CONTEXT, False, "policy", MODEL_TIER_DEFAULT
        return ROUTE_CLARIFY, False, "policy", MODEL_TIER_FAST
    # Conservador: sin señal conversacional clara no se apaga el retrieval.
    return ROUTE_KNOWLEDGE, True, "policy", MODEL_TIER_DEFAULT


def decision_from_jev(
    payload: Mapping[str, Any] | None,
    *,
    rules: "TurnIntentDecision | None" = None,
    has_context: bool = False,
    settings: Any = None,
    latency_ms: float = 0.0,
) -> "TurnIntentDecision | None":
    """Compone la decisión con las respuestas de JEV (código decide el route)."""
    raw = answer_for(payload, "conversation_intent") or {}
    intent = str(raw.get("choice") or "").strip().lower()
    if intent not in TURN_INTENTS:
        return None
    confidence = float(raw.get("confidence") or 0.0)
    probabilities = raw.get("probabilities") if isinstance(raw.get("probabilities"), Mapping) else {}
    probabilities = {
        str(key): float(value or 0.0)
        for key, value in probabilities.items()
        if str(key) in TURN_INTENTS
    }
    if not probabilities:
        probabilities = {intent: confidence}
    needs_noul = noul_for(payload, "needs_external_evidence", default=None)
    needs_jev = None
    if needs_noul is not None:
        yes = float(getattr(settings, "DECISION_NOUL_YES", 0.65) or 0.65)
        no = float(getattr(settings, "DECISION_NOUL_NO", 0.35) or 0.35)
        if needs_noul >= yes:
            needs_jev = True
        elif needs_noul <= no:
            needs_jev = False
    route, needs, source, tier = decide_route(
        intent=intent,
        confidence=confidence,
        probabilities=probabilities,
        needs_external_evidence=needs_jev,
        has_context=has_context,
        settings=settings,
    )
    señales = list(rules.signals) if rules is not None else []
    razones = ["jev_conversation_intent"]
    if needs_jev is not None:
        razones.append("jev_needs_external_evidence_yes" if needs_jev else "jev_needs_external_evidence_no")
    if rules is not None and rules.intent != intent:
        razones.append(f"reglas_veian_{rules.intent}")
    return _decision(
        intent=intent,
        confidence=confidence,
        provider="jev",
        route=route,
        needs_external_evidence=needs,
        evidence_source="jev" if needs_jev is not None else "policy",
        model_tier=tier,
        signals=señales,
        reasons=tuple(razones),
        probabilities=probabilities,
        knowledge_probability=float(probabilities.get("knowledge_question") or 0.0),
        latency_ms=latency_ms,
        answers={"conversation_intent": dict(raw)},
    )


def fallback_turn_intent(
    message: str,
    *,
    rules: "TurnIntentDecision | None" = None,
    has_context: bool = False,
) -> "TurnIntentDecision":
    """Sin JEV: sólo se apaga el retrieval para charla sin señal de conocimiento."""
    if rules is not None:
        return rules
    señales = _signals(message or "")
    if not any(s in señales for s in ("entity", "knowledge_verb", "question_word", "action")):
        tokens = [token for token in re.split(r"\s+", message or "") if token]
        if len(tokens) > 6:
            # Mensaje largo sin señal clara: conservador, no charla.
            return _decision(
                intent="ambiguous",
                confidence=_RULES_FALLBACK_CONFIDENCE,
                provider="rules_fallback",
                route=ROUTE_KNOWLEDGE,
                needs_external_evidence=True,
                evidence_source="rules",
                model_tier=MODEL_TIER_DEFAULT,
                signals=señales,
                reasons=("sin_jev_mensaje_largo_sin_senal",),
            )
        return _decision(
            intent="social_conversation",
            confidence=_RULES_FALLBACK_CONFIDENCE,
            provider="rules_fallback",
            route=ROUTE_DIRECT,
            needs_external_evidence=False,
            evidence_source="rules",
            model_tier=MODEL_TIER_FAST,
            signals=señales,
            reasons=("sin_senal_de_conocimiento",),
        )
    return _decision(
        intent="ambiguous",
        confidence=_RULES_FALLBACK_CONFIDENCE,
        provider="rules_fallback",
        route=ROUTE_KNOWLEDGE,
        needs_external_evidence=True,
        evidence_source="rules",
        model_tier=MODEL_TIER_DEFAULT,
        signals=señales,
        reasons=("sin_jev_con_senal_factual",),
    )


async def resolve_turn_intent(
    *,
    engine: Any,
    message: str,
    conversation_state: Mapping[str, Any] | None = None,
    agent_purpose: str = "",
    has_context: bool = False,
    settings: Any = None,
    context: JudgmentContext | None = None,
    rules: "TurnIntentDecision | None" = None,
) -> "TurnIntentDecision | None":
    """Rules-first, JEV-on-ambiguity. `None` = modo off (comportamiento previo)."""
    if settings is None:
        try:
            from src.core.config import get_settings

            settings = get_settings()
        except Exception:  # noqa: BLE001
            settings = None
    mode = str(getattr(settings, "RUNTIME_TURN_INTENT", "on") or "on").lower()
    if mode not in {"rules", "on"}:
        return None
    prior = rules if rules is not None else rules_turn_intent(message, has_context=has_context)
    rules_floor = _thresholds(settings)[0]
    if prior is not None and prior.confidence >= rules_floor:
        observe_turn_intent(prior)
        return prior
    if mode == "rules" or engine is None:
        decision = fallback_turn_intent(message, rules=prior, has_context=has_context)
        observe_turn_intent(decision)
        return decision
    started = time.perf_counter()
    state = build_turn_intent_state(
        message=message,
        conversation_state=conversation_state,
        agent_purpose=agent_purpose,
    )
    try:
        payload = await call_phase_judge(
            engine,
            phase=PHASE_PRE_RETRIEVAL,
            state=state.state,
            questions=build_turn_intent_questions(),
            context=context
            or JudgmentContext(phase=PHASE_PRE_RETRIEVAL),
        )
    except Exception as exc:  # noqa: BLE001 — la clasificación nunca rompe el run
        logger.warning("turn intent judge failed", error=str(exc)[:150])
        payload = None
    latency_ms = (time.perf_counter() - started) * 1000
    decision = (
        decision_from_jev(
            payload,
            rules=prior,
            has_context=has_context,
            settings=settings,
            latency_ms=latency_ms,
        )
        if isinstance(payload, dict)
        else None
    )
    if decision is None:
        decision = fallback_turn_intent(message, rules=prior, has_context=has_context)
    observe_turn_intent(decision)
    return decision


def observe_turn_intent(decision: "TurnIntentDecision") -> None:
    """Métricas del turno (fail-silent): intención, proveedor, route, skips."""
    try:
        from src.infrastructure.observability.metrics import (
            zent_turn_intent_latency_seconds,
            zent_turn_intent_total,
            zent_turn_retrieval_skipped_total,
        )

        zent_turn_intent_total.labels(
            intent=decision.intent,
            provider=decision.provider,
            route=decision.route,
            needs_evidence=str(bool(decision.needs_external_evidence)).lower(),
        ).inc()
        if decision.direct and not decision.needs_external_evidence:
            zent_turn_retrieval_skipped_total.labels(intent=decision.intent).inc()
        if decision.latency_ms:
            zent_turn_intent_latency_seconds.labels(provider=decision.provider).observe(
                decision.latency_ms / 1000.0
            )
    except Exception:  # noqa: BLE001 — métricas nunca rompen el turno
        pass


@dataclass(frozen=True)
class TurnIntentDecision:
    """Señal del turno: intención + distribución + necesidad de evidencia + route."""

    intent: str
    confidence: float = 0.0
    probabilities: Mapping[str, float] = field(default_factory=dict)
    provider: str = "rules"
    needs_external_evidence: bool = True
    evidence_source: str = "rules"
    route: str = ROUTE_KNOWLEDGE
    model_tier: str = MODEL_TIER_DEFAULT
    knowledge_probability: float = 0.0
    signals: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    latency_ms: float = 0.0
    answers: Mapping[str, Any] = field(default_factory=dict)

    @property
    def direct(self) -> bool:
        return self.route in DIRECT_ROUTES and not self.needs_external_evidence

    def certain(self, floor: float = 0.80) -> bool:
        return self.provider == "rules" and self.confidence >= float(floor)

    def to_public_dict(self) -> dict[str, Any]:
        """Bloque de «Ver flujo»: sin probabilidades inventadas (sólo JEV)."""
        payload: dict[str, Any] = {
            "intent": self.intent,
            "confidence": round(float(self.confidence), 4),
            "provider": self.provider,
            "route": self.route,
            "model_tier": self.model_tier,
            "needs_external_evidence": bool(self.needs_external_evidence),
            "evidence_source": self.evidence_source,
            "knowledge_probability": round(float(self.knowledge_probability), 4),
            "retrieval": "not_applicable" if self.direct else "required",
            "answer_gate": "not_applicable" if self.direct else "applicable",
        }
        if self.probabilities:
            payload["probabilities"] = {
                key: round(float(value), 4)
                for key, value in self.probabilities.items()
            }
        if self.signals:
            payload["signals"] = list(self.signals)
        if self.reasons:
            payload["reasons"] = list(self.reasons)
        if self.latency_ms:
            payload["latency_ms"] = round(float(self.latency_ms), 2)
        return payload


def capability_answer_block(
    *,
    agent: Any,
    tools: Any = (),
    org_config: Mapping[str, Any] | None = None,
) -> str:
    """Bloque de CONFIGURACIÓN para preguntas de capacidad (no son hechos de negocio).

    `qué puedes hacer` se responde con nombre, propósito, herramientas y fuentes
    configuradas del agente. No se inventan capacidades ni se buscan en documentos.
    """
    config = getattr(agent, "config_json", None) or {}
    purpose = str(config.get("purpose") or "").strip()
    nombre = str(getattr(agent, "name", "") or "").strip() or "(sin nombre)"
    nombres_tools: list[str] = []
    for tool in tools or ():
        name = str(getattr(tool, "name", "") or "").strip()
        if name and name not in nombres_tools:
            nombres_tools.append(name)
    org = org_config if isinstance(org_config, Mapping) else {}
    fuentes = len(list(org.get("source_ids") or ())) + len(
        list(org.get("knowledge_base_ids") or ())
    )
    perfil = config.get("response_profile") if isinstance(config.get("response_profile"), dict) else {}
    idioma = str(perfil.get("language") or "es")
    lineas = [
        "## CONFIGURACIÓN REAL DEL AGENTE (para responder sobre tus capacidades; no son datos de negocio)",
        f"nombre: {nombre}",
        f"propósito: {purpose or 'no definido'}",
        "herramientas habilitadas: "
        + (", ".join(nombres_tools) if nombres_tools else "ninguna"),
        f"fuentes configuradas: {fuentes}",
        f"idioma de respuesta: {idioma}",
        "Usá SOLO estos datos para describir qué podés hacer. No prometas acciones "
        "que las herramientas o fuentes configuradas no cubran.",
    ]
    return "\n".join(lineas)


__all__ = [
    "CONVERSATIONAL_INTENTS",
    "DIRECT_INTENTS",
    "DIRECT_ROUTES",
    "FACTUAL_INTENTS",
    "INTENT_CRITERIA",
    "MODEL_TIER_DEFAULT",
    "MODEL_TIER_FAST",
    "ROUTE_CLARIFY",
    "ROUTE_CONTEXT",
    "ROUTE_DIRECT",
    "ROUTE_KNOWLEDGE",
    "ROUTE_TOOL",
    "TURN_INTENTS",
    "TurnIntentDecision",
    "build_turn_intent_questions",
    "build_turn_intent_state",
    "capability_answer_block",
    "decide_route",
    "decision_from_jev",
    "fallback_turn_intent",
    "identify_obvious_intent",
    "observe_turn_intent",
    "resolve_turn_intent",
    "rules_turn_intent",
]
