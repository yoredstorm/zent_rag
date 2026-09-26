# =============================================================================
# Turn intent — capa conversacional (saludo/queja/capacidad/charla).
# =============================================================================
# Regresión real: «hola como estas» con un agente que tiene search_knowledge
# terminaba en INSUFFICIENT_ANSWER. La causa conceptual: el sistema confundía
# «¿necesito conocimiento para responder?» con «¿puedo responder?».
#
# Estos tests fijan:
#   - reglas deterministas para lo obvio (sin gastar JEV);
#   - JEV para la ambigüedad, conservando la DISTRIBUCIÓN COMPLETA;
#   - política de route en código (una intención secundaria material manda);
#   - `needs_external_evidence` explícito y auditable.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.adaptive import AdaptivePlan
from src.rag.adaptive.cache import deserialize_plan, serialize_plan
from src.rag.adaptive.planner import AdaptivePlanner
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.runtime.turn_intent import (
    ROUTE_CLARIFY,
    ROUTE_CONTEXT,
    ROUTE_DIRECT,
    ROUTE_KNOWLEDGE,
    ROUTE_TOOL,
    TURN_INTENTS,
    TurnIntentDecision,
    build_turn_intent_questions,
    capability_answer_block,
    decide_route,
    decision_from_jev,
    resolve_turn_intent,
    rules_turn_intent,
)


class _FakeEngine:
    """JEV fake: responde la intención configurada; cuenta llamadas."""

    def __init__(
        self,
        *,
        intent: str = "greeting",
        confidence: float = 0.84,
        probabilities: dict | None = None,
        needs: float | None = 0.1,
        empty: bool = False,
    ) -> None:
        self.intent = intent
        self.confidence = confidence
        self.probabilities = probabilities or {intent: confidence}
        self.needs = needs
        self.empty = empty
        self.calls = 0

    async def judge(self, *, state, questions, context=None):
        self.calls += 1
        if self.empty:
            return {"model": "fake", "answers": {}}
        answers: dict = {}
        for question_id, spec in (questions or {}).items():
            if question_id == "conversation_intent":
                answers[question_id] = {
                    "type": "choice",
                    "choice": self.intent,
                    "confidence": self.confidence,
                    "probabilities": dict(self.probabilities),
                }
            elif question_id == "needs_external_evidence":
                if self.needs is not None:
                    answers[question_id] = {"type": "noul", "noul": self.needs}
            elif (spec or {}).get("type") == "choice":
                criteria = (spec or {}).get("criteria") or {}
                choice = next(iter(criteria), "documents")
                answers[question_id] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.9,
                    "probabilities": {choice: 0.9},
                }
            elif (spec or {}).get("type") == "score":
                answers[question_id] = {"type": "score", "score": 2.0}
            else:
                answers[question_id] = {"type": "noul", "noul": 0.5}
        return {"model": "fake", "answers": answers}


# ---------------------------------------------------------------------------
# Reglas: casos obvios y señales fuertes (sin JEV)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mensaje", "intent", "route", "needs"),
    [
        ("hola", "greeting", ROUTE_DIRECT, False),
        ("¡Hola!", "greeting", ROUTE_DIRECT, False),
        ("gracias", "gratitude", ROUTE_DIRECT, False),
        ("chau", "farewell", ROUTE_DIRECT, False),
        ("buenas, qué significa byte 105?", "knowledge_question", ROUTE_KNOWLEDGE, True),
        ("gracias, y qué significa valor 5?", "knowledge_question", ROUTE_KNOWLEDGE, True),
        ("esto no sirve", "complaint", ROUTE_DIRECT, False),
        (
            "me estás respondiendo mal, explícame byte 105",
            "knowledge_question",
            ROUTE_KNOWLEDGE,
            True,
        ),
        ("qué puedes hacer?", "capability_question", ROUTE_DIRECT, False),
        ("quién eres", "capability_question", ROUTE_DIRECT, False),
        ("ejecuta el proceso X", "action_request", ROUTE_TOOL, True),
        ("qué significa byte 999?", "knowledge_question", ROUTE_KNOWLEDGE, True),
    ],
)
def test_reglas_clasifican_lo_evidente(
    mensaje: str, intent: str, route: str, needs: bool
) -> None:
    decision = rules_turn_intent(mensaje)
    assert decision is not None
    assert decision.intent == intent
    assert decision.route == route
    assert decision.needs_external_evidence is needs
    assert decision.provider == "rules"


def test_lo_ambiguo_queda_para_jev() -> None:
    """«hola como estas» y «gracias pero no entendi» no son regla: JEV decide."""
    assert rules_turn_intent("hola como estas") is None
    assert rules_turn_intent("gracias, pero no entendí") is None
    assert rules_turn_intent("y entonces?") is None


def test_followup_corto_con_y_sin_contexto() -> None:
    sin_contexto = rules_turn_intent("y el 5?")
    assert sin_contexto is not None
    assert sin_contexto.intent == "clarification"
    assert sin_contexto.route == ROUTE_CLARIFY
    assert sin_contexto.needs_external_evidence is False

    con_contexto = rules_turn_intent("y el 5?", has_context=True)
    assert con_contexto is not None
    assert con_contexto.intent == "contextual_followup"
    assert con_contexto.needs_external_evidence is True  # el 5 es un dato

    social = rules_turn_intent("eso?", has_context=True)
    assert social is not None
    assert social.intent == "contextual_followup"
    assert social.route == ROUTE_CONTEXT
    assert social.needs_external_evidence is False


def test_la_queja_con_pregunta_factual_conserva_la_senal_de_queja() -> None:
    decision = rules_turn_intent("me estás respondiendo mal, explícame byte 105")
    assert decision is not None
    assert decision.intent == "knowledge_question"
    assert "complaint" in decision.signals
    assert "entity" in decision.signals


# ---------------------------------------------------------------------------
# JEV: distribución completa y política
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saludo_obvio_no_gasta_jev() -> None:
    engine = _FakeEngine()
    decision = await resolve_turn_intent(
        engine=engine, message="hola", settings=None
    )
    assert decision is not None
    assert decision.provider == "rules"
    assert engine.calls == 0


@pytest.mark.asyncio
async def test_hola_como_estas_usa_jev_y_conserva_probabilidades() -> None:
    engine = _FakeEngine(
        intent="greeting",
        confidence=0.84,
        probabilities={
            "greeting": 0.84,
            "social_conversation": 0.11,
            "knowledge_question": 0.03,
            "complaint": 0.02,
        },
        needs=0.1,
    )
    decision = await resolve_turn_intent(
        engine=engine, message="hola como estas", settings=None
    )
    assert decision is not None
    assert engine.calls == 1
    assert decision.provider == "jev"
    assert decision.intent == "greeting"
    assert decision.route == ROUTE_DIRECT
    assert decision.needs_external_evidence is False
    assert decision.probabilities["social_conversation"] == 0.11
    assert decision.knowledge_probability == 0.03


def test_la_intencion_material_secundaria_no_se_borra() -> None:
    """«hola, explicame el byte 105»: el saludo no puede apagar el conocimiento."""
    payload = {
        "answers": {
            "conversation_intent": {
                "type": "choice",
                "choice": "greeting",
                "confidence": 0.18,
                "probabilities": {
                    "greeting": 0.18,
                    "knowledge_question": 0.78,
                    "social_conversation": 0.04,
                },
            },
            "needs_external_evidence": {"type": "noul", "noul": 0.9},
        }
    }
    decision = decision_from_jev(payload, settings=None)
    assert decision is not None
    assert decision.intent == "greeting"  # lo más probable
    assert decision.route == ROUTE_KNOWLEDGE  # pero la señal material manda
    assert decision.needs_external_evidence is True
    assert decision.knowledge_probability == 0.78


@pytest.mark.asyncio
async def test_distribucion_plana_sin_contexto_pide_aclaracion() -> None:
    engine = _FakeEngine(
        intent="greeting",
        confidence=0.30,
        probabilities={
            "greeting": 0.30,
            "social_conversation": 0.28,
            "knowledge_question": 0.22,
            "ambiguous": 0.20,
        },
        needs=0.2,
    )
    decision = await resolve_turn_intent(
        engine=engine, message="mmm", settings=None
    )
    assert decision is not None
    assert decision.route == ROUTE_CLARIFY
    assert decision.needs_external_evidence is False


@pytest.mark.asyncio
async def test_modo_off_no_clasifica() -> None:
    class _Settings:
        RUNTIME_TURN_INTENT = "off"

    decision = await resolve_turn_intent(
        engine=_FakeEngine(), message="hola", settings=_Settings()
    )
    assert decision is None


@pytest.mark.asyncio
async def test_modo_rules_no_llama_jev() -> None:
    class _Settings:
        RUNTIME_TURN_INTENT = "rules"

    engine = _FakeEngine()
    decision = await resolve_turn_intent(
        engine=engine, message="hola como estas", settings=_Settings()
    )
    assert decision is not None
    assert decision.provider == "rules_fallback"
    assert decision.route == ROUTE_DIRECT
    assert engine.calls == 0


@pytest.mark.asyncio
async def test_jev_sin_respuesta_cae_al_fallback_seguro() -> None:
    engine = _FakeEngine(empty=True)
    decision = await resolve_turn_intent(
        engine=engine, message="hola como estas", settings=None
    )
    assert decision is not None
    assert decision.route == ROUTE_DIRECT
    assert decision.needs_external_evidence is False


def test_politica_por_distribucion() -> None:
    class _Settings:
        RUNTIME_TURN_INTENT_RULES_CONFIDENCE = 0.80
        RUNTIME_TURN_INTENT_KNOWLEDGE_FLOOR = 0.30
        RUNTIME_TURN_INTENT_ACTION_FLOOR = 0.35
        RUNTIME_TURN_INTENT_CONVERSATIONAL_FLOOR = 0.60
        RUNTIME_TURN_INTENT_AMBIGUOUS_FLOOR = 0.45

    route, needs, _, _ = decide_route(
        intent="greeting",
        confidence=0.84,
        probabilities={"greeting": 0.84, "social_conversation": 0.11},
        has_context=False,
        settings=_Settings(),
    )
    assert (route, needs) == (ROUTE_DIRECT, False)

    route, needs, _, _ = decide_route(
        intent="conversation",
        confidence=0.9,
        probabilities={"action_request": 0.7, "knowledge_question": 0.2},
        settings=_Settings(),
    )
    assert (route, needs) == (ROUTE_TOOL, True)

    route, needs, _, _ = decide_route(
        intent="social_conversation",
        confidence=0.5,
        probabilities={"social_conversation": 0.5, "knowledge_question": 0.4},
        settings=_Settings(),
    )
    assert (route, needs) == (ROUTE_KNOWLEDGE, True)

    route, needs, _, _ = decide_route(
        intent="greeting",
        confidence=0.84,
        probabilities={"greeting": 0.84, "knowledge_question": 0.03},
        settings=_Settings(),
    )
    assert (route, needs) == (ROUTE_DIRECT, False)


def test_decision_from_jev_requiere_choice_valido() -> None:
    payload = {"answers": {"conversation_intent": {"type": "choice", "choice": "bailar"}}}
    assert decision_from_jev(payload) is None


def test_preguntas_incluyen_todo_el_vocabulario() -> None:
    questions = build_turn_intent_questions()
    assert questions["conversation_intent"]["type"] == "choice"
    assert set(questions["conversation_intent"]["criteria"]) == set(TURN_INTENTS)
    assert questions["needs_external_evidence"]["type"] == "noul"


def test_public_dict_no_inventa_probabilidades_en_reglas() -> None:
    decision = TurnIntentDecision(
        intent="greeting",
        confidence=0.95,
        provider="rules",
        route=ROUTE_DIRECT,
        needs_external_evidence=False,
    )
    payload = decision.to_public_dict()
    assert "probabilities" not in payload
    assert payload["retrieval"] == "not_applicable"
    assert payload["answer_gate"] == "not_applicable"


def test_bloque_de_capacidad_usa_configuracion_real() -> None:
    class _Agent:
        name = "atpco-agent"
        config_json = {"purpose": "Resolver consultas ATPCO"}

    class _Tool:
        name = "search_knowledge"

    bloque = capability_answer_block(
        agent=_Agent(),
        tools=[_Tool()],
        org_config={"source_ids": ["a", "b"], "knowledge_base_ids": ["kb"]},
    )
    assert "atpco-agent" in bloque
    assert "Resolver consultas ATPCO" in bloque
    assert "search_knowledge" in bloque
    assert "fuentes configuradas: 3" in bloque


# ---------------------------------------------------------------------------
# Planner: el plan conversacional no hace retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_marca_directo_para_saludo_ambiguo() -> None:
    planner = AdaptivePlanner(
        AdaptiveRagSettings(mode="active"),
        judge=_FakeEngine(intent="greeting", confidence=0.84, needs=0.05),
        high_confidence=0.9,
    )
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="hola como estas",
        sql_enabled=False,
    )
    assert plan.apply is True
    assert plan.source_route == "direct"
    assert plan.skip_retrieval is True
    assert plan.needs_external_evidence is False
    assert plan.turn_intent == "greeting"
    assert plan.turn_route == "direct"
    assert plan.turn_provider == "jev"
    assert plan.intent_probabilities["greeting"] == 0.84


@pytest.mark.asyncio
async def test_planner_no_apaga_el_retrieval_para_conocimiento() -> None:
    planner = AdaptivePlanner(
        AdaptiveRagSettings(mode="active"),
        judge=_FakeEngine(intent="knowledge_question", confidence=0.9, needs=0.95),
        high_confidence=0.9,
    )
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="cuéntame sobre la categoría 31 y el byte 105",
        sql_enabled=False,
    )
    assert plan.skip_retrieval is False
    assert plan.needs_external_evidence is True
    assert plan.turn_intent == "knowledge_question"


@pytest.mark.asyncio
async def test_planner_saludo_obvio_por_regla() -> None:
    engine = _FakeEngine()
    planner = AdaptivePlanner(
        AdaptiveRagSettings(mode="active"), judge=engine, high_confidence=0.9
    )
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="hola",
        sql_enabled=False,
    )
    assert plan.source_route == "direct"
    assert plan.skip_retrieval is True
    assert plan.turn_provider == "rules"
    assert engine.calls == 0


def test_el_plan_cachea_los_campos_del_turno() -> None:
    plan = AdaptivePlan(
        apply=True,
        mode="active",
        turn_intent="greeting",
        intent_probabilities={"greeting": 0.84, "social_conversation": 0.11},
        needs_external_evidence=False,
        turn_route="direct",
        turn_provider="jev",
        model_tier="fast",
        turn_signals=["social"],
    )
    restored = deserialize_plan(serialize_plan(plan), apply=True, mode="active")
    assert restored is not None
    assert restored.turn_intent == "greeting"
    assert restored.needs_external_evidence is False
    assert restored.turn_route == "direct"
    assert restored.turn_provider == "jev"
    assert restored.model_tier == "fast"
    assert restored.intent_probabilities["social_conversation"] == 0.11
