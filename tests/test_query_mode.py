# =============================================================================
# QueryMode — tópico no es instancia. Explicación no abre el pipeline de escenario.
# =============================================================================
from __future__ import annotations

import pytest

from src.core.domain.reasoning import QueryMode, ReasoningShape
from src.intelligence.reasoning.classifier import (
    REASON_EXECUTABLE,
    REASON_INFORMATIONAL,
    REASON_SCENARIO,
    ReasoningClassifier,
    deterministic_shape,
    has_concrete_scenario_payload,
    has_raw_scenario,
    is_informational_request,
)
from src.intelligence.response.blueprints import SCENARIO_ANALYSIS, TECHNICAL_EXPLANATION
from src.intelligence.response.selector import select_blueprint
from src.runtime.deterministic_authority import requires_deterministic_decision

CASE_A = "cuentame sobre el record 2 en general sobre el cierre de fechas"
CASE_B = "explicame en general como funcionan Eff Date y Disc Date"
CASE_C = "tengo Eff Date 01JAN26 y Disc Date 31JAN26; una tarifa del 15FEB26 aplica?"
CASE_D = "tengo las secuencias 1000, 2000 y 3000; por qué terminó aplicando la 3000?"
CASE_E = "qué significa byte 105 con valor 2"
CASE_F = "&&&F vs ABCFGEGE cumple?"
EXECUTABLE_EXAMPLE = (
    "yo tengo en el record 2 &&&F y en el farebasis me viene ABCFGEGE cumple o no cumple"
)

_TOPICS = (
    "record",
    "registro",
    "secuencia",
    "cierre",
    "fecha",
    "estado",
    "vigencia",
    "regla",
    "match",
    "effective date",
)
_INFO_FRAMES = (
    "cuentame sobre {topic} en general",
    "hablame de {topic}",
    "explicame {topic}",
    "explicame en general como funciona {topic}",
    "como funciona {topic}",
    "que es {topic}",
    "que significa {topic}",
    "dame una explicacion de {topic}",
    "overview de {topic}",
    "tell me about {topic}",
)
_SCENARIO_FRAMES = (
    "tengo {topic} con secuencias 1000, 2000 y 3000; por qué terminó aplicando la 3000?",
    "me viene {topic} con seq 1000 y seq 2000; por qué ocurrió el cierre?",
    "en este caso {topic} secuencia 1000, 2000 y 3000; qué secuencia cerró la anterior?",
    "recibí {topic} con Eff Date 01JAN26 y Disc Date 31JAN26; por qué cerró?",
    "con estos datos de {topic}: 1000 | 2000 | 3000; por qué terminó la 3000?",
    "esta secuencia de {topic} 1000 luego 2000; por qué pasó de abierto a cerrado?",
    "este registro {topic} seq 2000; qué registro causó el cierre?",
    "I have {topic} sequences 1000, 2000 and 3000; why did 3000 apply?",
    "in this case {topic} changed; por qué pasó de abierto a cerrado después de la secuencia 2000?",
    "por qué ocurrió el cierre de {topic} con secuencias 1000, 2000 y 3000?",
)


def _informational_queries() -> list[str]:
    return [frame.format(topic=topic) for frame in _INFO_FRAMES for topic in _TOPICS]


def _scenario_queries() -> list[str]:
    return [frame.format(topic=topic) for frame in _SCENARIO_FRAMES for topic in _TOPICS]


def test_topic_words_are_not_a_raw_scenario() -> None:
    for word in ("record", "record 2", "registro", "secuencia", "fecha", "cierre", "estado"):
        assert has_raw_scenario(word) is False
        assert has_concrete_scenario_payload(word) is False
    assert has_raw_scenario("hola") is False


def test_case_a_is_informational_not_scenario() -> None:
    classification = deterministic_shape(CASE_A)
    assert classification.query_mode is QueryMode.INFORMATIONAL
    assert classification.shape in {ReasoningShape.SIMPLE_LOOKUP, ReasoningShape.MULTI_EVIDENCE}
    assert classification.shape is ReasoningShape.SIMPLE_LOOKUP
    assert classification.scenario_payload is False
    assert classification.is_complex is False
    assert classification.routing_reason == REASON_INFORMATIONAL
    assert classification.uncertain is False
    selection = select_blueprint(question=CASE_A, shape="STATE_TRANSITION")
    assert selection.blueprint == TECHNICAL_EXPLANATION
    assert selection.blueprint != SCENARIO_ANALYSIS
    assert selection.needs_jev is False


def test_case_b_eff_disc_is_informational() -> None:
    classification = deterministic_shape(CASE_B)
    assert classification.query_mode is QueryMode.INFORMATIONAL
    assert classification.is_complex is False
    assert classification.scenario_payload is False
    assert classification.shape is not ReasoningShape.TEMPORAL_SEQUENCE
    assert classification.shape is not ReasoningShape.STATE_TRANSITION
    assert select_blueprint(question=CASE_B).blueprint != SCENARIO_ANALYSIS


def test_case_c_dates_are_executable() -> None:
    classification = deterministic_shape(CASE_C)
    assert classification.query_mode is QueryMode.EXECUTABLE
    assert classification.routing_reason == REASON_EXECUTABLE
    assert requires_deterministic_decision(CASE_C) is True
    assert classification.is_complex is False


def test_case_d_sequences_are_scenario_analysis() -> None:
    classification = deterministic_shape(CASE_D)
    assert classification.query_mode is QueryMode.SCENARIO
    assert classification.scenario_payload is True
    assert classification.is_complex is True
    assert classification.routing_reason == REASON_SCENARIO
    assert requires_deterministic_decision(CASE_D) is False
    selection = select_blueprint(question=CASE_D, shape=classification.shape.value)
    assert selection.blueprint == SCENARIO_ANALYSIS
    assert selection.needs_jev is False


def test_case_e_byte_value_is_technical_explanation() -> None:
    classification = deterministic_shape(CASE_E)
    assert classification.query_mode is QueryMode.INFORMATIONAL
    assert classification.is_complex is False
    selection = select_blueprint(question=CASE_E, shape=classification.shape.value)
    assert selection.blueprint == TECHNICAL_EXPLANATION


def test_case_f_mask_stays_executable() -> None:
    classification = deterministic_shape(CASE_F)
    assert classification.query_mode is QueryMode.EXECUTABLE
    assert requires_deterministic_decision(CASE_F) is True
    assert is_informational_request(CASE_F) is False
    lived = deterministic_shape(EXECUTABLE_EXAMPLE)
    assert lived.query_mode is QueryMode.EXECUTABLE
    assert requires_deterministic_decision(EXECUTABLE_EXAMPLE) is True


def test_followup_reclassifies_the_turn() -> None:
    first = deterministic_shape(CASE_F)
    second = deterministic_shape("ahora cuéntame cómo funciona Record 2")
    assert first.query_mode is QueryMode.EXECUTABLE
    assert second.query_mode is QueryMode.INFORMATIONAL
    assert second.is_complex is False
    assert second.scenario_payload is False


def test_isolated_cierre_is_not_state_transition() -> None:
    classification = deterministic_shape("explícame el cierre de fechas")
    assert classification.shape is not ReasoningShape.STATE_TRANSITION
    assert classification.query_mode is QueryMode.INFORMATIONAL
    assert classification.is_complex is False


@pytest.mark.asyncio
async def test_informational_skips_scenario_pipeline_and_judge() -> None:
    async def judge(**_kwargs):
        return {"answers": {"describes_transitions": {"type": "noul", "noul": 0.99}}}

    classifier = ReasoningClassifier(judge=judge, use_judge=True)
    classification = await classifier.classify(CASE_A)
    assert classification.query_mode is QueryMode.INFORMATIONAL
    assert classification.shape is ReasoningShape.SIMPLE_LOOKUP
    assert classification.source.value == "deterministic"

    from src.intelligence.reasoning.coordinator import EvidenceReasoningEngine

    outcome = await EvidenceReasoningEngine().reason(CASE_A)
    assert outcome.activated is False
    assert outcome.plan is None
    trace = outcome.public_trace()
    assert trace["complex_reasoning_activated"] is False
    assert trace["query_mode"] == "INFORMATIONAL"
    assert trace["routing_reason"] == REASON_INFORMATIONAL
    assert "scenario_events" not in trace


@pytest.mark.asyncio
async def test_scenario_question_still_activates_reasoning() -> None:
    from src.intelligence.reasoning.coordinator import EvidenceReasoningEngine

    outcome = await EvidenceReasoningEngine().reason(CASE_D)
    assert outcome.activated is True
    assert outcome.plan is not None
    assert outcome.plan.requires_scenario_parse is True
    assert outcome.classification.query_mode is QueryMode.SCENARIO


def test_markdown_lane_feeds_narrative_context_without_replacing_canonical() -> None:
    from src.knowledge.structure.document_bundle import narrative_context_text

    canonical = '{"byte": 105, "value": "Fee Application"}'
    metadata = {
        "llm_markdown": "Fee Application (byte 105)\n\nEl byte indica cómo se cobra.",
        "canonical_evidence_ids": ["ev-1"],
    }
    narrative = narrative_context_text(
        question=CASE_A, canonical=canonical, metadata=metadata
    )
    assert "Fee Application" in narrative
    assert narrative != canonical
    kept = narrative_context_text(
        question=CASE_F, canonical=canonical, metadata=metadata
    )
    assert kept == canonical


@pytest.mark.parametrize("question", _informational_queries())
def test_topic_words_never_activate_scenario_pipeline(question: str) -> None:
    classification = deterministic_shape(question)
    assert classification.query_mode is QueryMode.INFORMATIONAL, question
    assert classification.scenario_payload is False, question
    assert classification.is_complex is False, question
    assert classification.shape not in {
        ReasoningShape.STATE_TRANSITION,
        ReasoningShape.TEMPORAL_SEQUENCE,
    }, question
    assert select_blueprint(question=question).blueprint != SCENARIO_ANALYSIS, question


@pytest.mark.parametrize("question", _scenario_queries())
def test_concrete_payload_is_scenario(question: str) -> None:
    classification = deterministic_shape(question)
    assert classification.scenario_payload is True, question
    assert classification.query_mode is QueryMode.SCENARIO, question
    assert classification.is_complex is True, question
    selection = select_blueprint(question=question, shape=classification.shape.value)
    assert selection.blueprint == SCENARIO_ANALYSIS, question


def test_positional_match_still_matches() -> None:
    from src.intelligence.reasoning.grounded_engine import reason_over_evidence
    from src.runtime.decision_envelope import build_decision_envelope
    from tests.test_production_consistency import _Item, compile_pattern_rules

    rules = compile_pattern_rules()
    grounded = reason_over_evidence(
        question=CASE_F,
        evidence_items=[_Item("Matching is positional, left to right.")],
        canonical_rules=rules,
    )
    envelope = build_decision_envelope(grounded)
    assert envelope is not None
    assert envelope.operation == "POSITIONAL_MATCH"
    assert envelope.normalized_result == "MATCH"
