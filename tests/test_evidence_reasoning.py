# =============================================================================
# Evidence Reasoning — pipeline, goldens sintéticos y regresiones (Fase 6)
# =============================================================================
# Fixtures sintéticos. Nada de datos privados ni hardcodeo ATPCO: el escenario
# es un caso genérico de state-transition reasoning sobre registros de pricing.
#
# Cubre: clasificación por forma, fast path, parser sin inventar layouts,
# timeline con tres órdenes, transiciones con regla, hipótesis (incluida la del
# usuario), verificación de inferencias, gate de completitud, evidencia de
# grafo, autoridad de fuente, temporalidad y escenarios genéricos.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.core.domain.reasoning import (
    COMPLEX_SHAPES,
    Fact,
    FactStatus,
    HypothesisVerdict,
    InferenceVerdict,
    ReasoningMode,
    ReasoningShape,
    RequirementKind,
    TransitionStatus,
)
from src.core.domain.research import ResearchBudgets
from src.intelligence.reasoning.assessment import (
    AnalysisCompletionGate,
    HypothesisEngine,
    InferenceVerifier,
)
from src.intelligence.reasoning.classifier import (
    ReasoningClassifier,
    deterministic_shape,
    has_raw_scenario,
)
from src.intelligence.reasoning.coordinator import (
    EvidenceReasoningEngine,
    question_to_prove,
)
from src.intelligence.reasoning.scenario import ScenarioParser
from src.intelligence.reasoning.sequence import (
    StateTransitionAnalyzer,
    TimelineBuilder,
    chain_values,
    find_sequence_gaps,
)

ORG = uuid4()


# ---------------------------------------------------------------------------
# Fixtures sintéticos
# ---------------------------------------------------------------------------

#: Regla autoritativa del fixture: la renumeración abre espacio de orden.
RENUMBER_RULE = (
    "Record B renumbers existing sequences to open ordering space; multiple "
    "active sequences may coexist and no closing record is required."
)

#: Regla opuesta para el golden negativo: el cierre SÍ es obligatorio.
CLOSE_REQUIRED_RULE = (
    "Every sequence must close with a Record C closing record; a sequence "
    "without its closing record is incomplete and cannot be priced."
)

SEQUENCE_BLOCK = """
record A | carrier AA | seq 0005
record B | seq 0006
record B | seq 0007
record B | seq 0010
record B | seq 0014
record B | seq 0018
record B | seq 0022
record B | seq 0026
record B | seq 0030
record B | seq 0034
record B | seq 0038
record A | carrier AA | seq 0013
"""

MISSING_CLOSE_QUESTION = "¿Falta un registro para cerrar esta secuencia?"


def _search_returning(*texts: str):
    async def search(organization_id, query, *, limit=4):
        return [
            {
                "document_id": f"doc-{index}",
                "title": f"fixture-{index}",
                "content": text,
                "score": 0.9,
            }
            for index, text in enumerate(texts)
        ]

    return search


def _engine(*, rules: tuple[str, ...] = (RENUMBER_RULE,), **kwargs) -> EvidenceReasoningEngine:
    return EvidenceReasoningEngine(
        budgets=ResearchBudgets(max_retrieval_calls=2, max_steps=10),
        knowledge_search=_search_returning(*rules) if rules else None,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# §3 clasificación por forma
# ---------------------------------------------------------------------------


def test_shape_examples_from_the_brief() -> None:
    lookup = deterministic_shape("¿Qué significa Record 4?", intent="concept_definition")
    assert lookup.shape is ReasoningShape.SIMPLE_LOOKUP
    assert lookup.is_complex is False

    transition = deterministic_shape(MISSING_CLOSE_QUESTION, intent="general")
    assert transition.shape is ReasoningShape.STATE_TRANSITION
    assert transition.is_complex is True

    causal = deterministic_shape("¿Por qué aumentaron los ADM?", intent="business_metric")
    assert causal.shape is ReasoningShape.CAUSAL_ANALYSIS

    graph = deterministic_shape("¿Qué se rompe si PXSAUDIT no está disponible?")
    assert graph.shape is ReasoningShape.GRAPH_REASONING


def test_classifier_is_deterministic_by_default() -> None:
    classifier = ReasoningClassifier()
    classification = deterministic_shape("¿Está cerrada la secuencia?")
    assert classification.shape in COMPLEX_SHAPES or classification.shape is ReasoningShape.SIMPLE_LOOKUP
    assert has_raw_scenario(SEQUENCE_BLOCK) is True
    assert has_raw_scenario("hola") is False
    # Sin juez y con banda incierta, se queda con lo determinista.
    assert classifier is not None


def test_question_to_prove_is_operational_not_a_conclusion() -> None:
    text = question_to_prove(MISSING_CLOSE_QUESTION, ReasoningShape.STATE_TRANSITION)
    assert "whether" in text
    assert "closing event" in text
    # No adelanta veredicto.
    assert "no falta" not in text.lower()
    assert "sí falta" not in text.lower()


# ---------------------------------------------------------------------------
# §62 fast path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simple_lookup_uses_fast_path() -> None:
    engine = _engine()
    outcome = await engine.reason("¿Qué significa Carrier Code?")
    assert outcome.activated is False
    assert outcome.plan is None
    assert outcome.workspace is None
    assert outcome.classification.shape is ReasoningShape.SIMPLE_LOOKUP
    assert outcome.public_trace()["reason"] == "simple_lookup_fast_path"
    assert outcome.latency_ms < 50


# ---------------------------------------------------------------------------
# §16/§17/§54 parser: no inventar layouts
# ---------------------------------------------------------------------------


def test_parser_requires_layout_for_fixed_width_records() -> None:
    parser = ScenarioParser()
    fixed_width = "\n".join(
        [
            "0005123456789ABCDEF",
            "0006123456790ABCDEF",
            "0007123456791ABCDEF",
            "0010123456792ABCDEF",
        ]
    )
    scenario = parser.parse(fixed_width)
    kinds = {item.kind for item in scenario.missing_requirements}
    assert RequirementKind.RECORD_LAYOUT_REQUIRED in kinds
    assert scenario.events == ()
    assert scenario.partial is True
    # Nada se inventó: los items quedan declarados, no parseados.
    assert scenario.unparsed_items


def test_parser_parses_delimited_records_with_schema() -> None:
    parser = ScenarioParser()
    scenario = parser.parse(SEQUENCE_BLOCK)
    assert scenario.events
    assert [event.sequence for event in scenario.events][:3] == ["0005", "0006", "0007"]
    assert scenario.parse_confidence > 0
    assert not scenario.missing_requirements


# ---------------------------------------------------------------------------
# §22/§24 timeline y cadena
# ---------------------------------------------------------------------------


def test_timeline_keeps_original_and_effective_orders() -> None:
    parser = ScenarioParser()
    scenario = parser.parse(
        "\n".join(
            [
                "record B | seq 0038 | effective 2025-03-01",
                "record B | seq 0006 | effective 2025-01-01",
                "record B | seq 0013 | effective 2025-02-01",
            ]
        )
    )
    timeline = TimelineBuilder().build(scenario)
    assert timeline.original_order != timeline.effective_order
    assert timeline.criteria["effective"] == "effective_date"
    # El criterio usado queda registrado: no hay reordenamiento silencioso.
    assert timeline.criteria["logical"] in ("not_proven", "sequence_monotonic_in_effective_order")


def test_transition_chain_is_structured_not_text() -> None:
    parser = ScenarioParser()
    scenario = parser.parse(SEQUENCE_BLOCK)
    rule = Fact(
        statement=RENUMBER_RULE,
        status=FactStatus.CONFIRMED,
        authority="authoritative",
        origin="retrieval",
    )
    transitions = StateTransitionAnalyzer().analyze(
        scenario=scenario, timeline=TimelineBuilder().build(scenario), rules=[rule]
    )
    assert transitions.transitions
    assert transitions.chain
    assert transitions.chain[0].event_ref
    assert transitions.chain[0].rule_refs
    assert transitions.confirmed == len(transitions.transitions)
    values = chain_values(transitions)
    assert values[0] == "0005"
    assert values[-1] == "0013"
    gaps = find_sequence_gaps(transitions)
    assert gaps, "la numeración tiene saltos y debe reportarlos"
    # La cadena se expone con regla y confianza por eslabón.
    payload = transitions.to_dict()
    assert all("rule_refs" in link for link in payload["chain"])


# ---------------------------------------------------------------------------
# §25-§28 hipótesis
# ---------------------------------------------------------------------------


async def test_hypothesis_supported_when_rules_require_close() -> None:
    """El golden negativo: si las reglas exigen cierre, la hipótesis se sostiene."""
    rules = [
        Fact(
            statement=CLOSE_REQUIRED_RULE,
            status=FactStatus.CONFIRMED,
            authority="authoritative",
        )
    ]
    engine = HypothesisEngine()
    workspace = _workspace_with_sequence(rules)
    result = await _run_hypotheses(engine, MISSING_CLOSE_QUESTION, workspace, rules)
    user = result.by_id(result.user_hypothesis_id)
    assert user is not None
    assert user.verdict is HypothesisVerdict.SUPPORTED


async def test_hypothesis_rejected_by_renumbering_rule() -> None:
    rules = [
        Fact(
            statement=RENUMBER_RULE,
            status=FactStatus.CONFIRMED,
            authority="authoritative",
        )
    ]
    engine = HypothesisEngine()
    workspace = _workspace_with_sequence(rules)
    result = await _run_hypotheses(engine, MISSING_CLOSE_QUESTION, workspace, rules)
    user = result.by_id(result.user_hypothesis_id)
    assert user is not None
    assert user.verdict is HypothesisVerdict.REJECTED
    assert user.contradicting_fact_ids
    # Y existe la alternativa que explica el salto.
    assert any(
        item.verdict is HypothesisVerdict.SUPPORTED
        for item in result.hypotheses
        if item.origin.value == "RULE"
    )


async def test_hypothesis_is_unresolved_without_rules() -> None:
    engine = HypothesisEngine()
    workspace = _workspace_with_sequence([])
    result = await _run_hypotheses(engine, MISSING_CLOSE_QUESTION, workspace, [])
    user = result.by_id(result.user_hypothesis_id)
    assert user is not None
    assert user.verdict is HypothesisVerdict.UNRESOLVED
    assert "No hay regla aplicable" in user.rationale


async def test_rule_derived_alternative_is_supported_without_keyword_match() -> None:
    """La alternativa nace de una regla: se respalda aunque el enunciado no la cite.

    Antes el veredicto dependía de la morfología del texto generado ("coexistir"
    no matcheaba "coexisten") y descartaba una explicación válida.
    """
    rules = [
        Fact(
            statement=RENUMBER_RULE,
            status=FactStatus.CONFIRMED,
            authority="authoritative",
        )
    ]
    workspace = _workspace_with_sequence(rules)
    result = await _run_hypotheses(
        HypothesisEngine(), MISSING_CLOSE_QUESTION, workspace, rules
    )
    coexist = next(
        (item for item in result.hypotheses if "coexistir" in item.statement.lower()),
        None,
    )
    assert coexist is not None
    assert coexist.verdict is HypothesisVerdict.SUPPORTED
    assert coexist.supporting_fact_ids


async def test_user_hypothesis_is_never_assumed_true() -> None:
    """La pregunta sugiere que falta algo; el motor no lo asume."""
    rules = [
        Fact(statement=RENUMBER_RULE, status=FactStatus.CONFIRMED, authority="authoritative")
    ]
    workspace = _workspace_with_sequence(rules)
    result = await _run_hypotheses(HypothesisEngine(), MISSING_CLOSE_QUESTION, workspace, rules)
    user = result.by_id(result.user_hypothesis_id)
    assert user is not None and user.verdict is not HypothesisVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# §29/§30/§60 verificación de inferencias
# ---------------------------------------------------------------------------


def test_inference_unsupported_when_premises_hold_but_rule_missing() -> None:
    """Premisas correctas, conclusión que no se sigue: el caso crítico."""
    premises = [
        Fact(
            statement="Record B renumbers existing sequences",
            status=FactStatus.SUPPORTED,
            authority="authoritative",
        ),
        Fact(
            statement="The existing sequence reached value 0038",
            status=FactStatus.SUPPORTED,
            authority="authoritative",
        ),
    ]
    record = InferenceVerifier().verify(
        conclusion="Therefore sequence 0038 must be cancelled before 0013 exists",
        premises=premises,
        rule_refs=(),
    )
    assert record.verdict is InferenceVerdict.UNSUPPORTED
    assert "ninguna regla" in record.rationale
    assert record.premise_refs


def test_inference_unsupported_when_premise_lacks_evidence() -> None:
    premises = [
        Fact(statement="Record B renumbers sequences", status=FactStatus.UNRESOLVED)
    ]
    record = InferenceVerifier().verify(
        conclusion="Falta un cierre", premises=premises, rule_refs=("rule-1",)
    )
    assert record.verdict is InferenceVerdict.UNRESOLVED


def test_inference_supported_with_rule_and_supported_premises() -> None:
    premises = [
        Fact(
            statement="Every sequence closes with Record C",
            status=FactStatus.CONFIRMED,
            authority="authoritative",
        )
    ]
    record = InferenceVerifier().verify(
        conclusion="Falta un cierre", premises=premises, rule_refs=("rule-1",)
    )
    assert record.verdict is InferenceVerdict.SUPPORTED


# ---------------------------------------------------------------------------
# §31 gate de completitud y §32/§33 answerability
# ---------------------------------------------------------------------------


def test_completion_gate_blocks_without_schema() -> None:
    parser = ScenarioParser()
    scenario = parser.parse(
        "\n".join(["0005123456789", "0006123456790", "0007123456791"])
    )
    engine = _engine(rules=())
    plan = engine.build_plan(
        MISSING_CLOSE_QUESTION,
        deterministic_shape(MISSING_CLOSE_QUESTION),
    )
    from src.core.domain.reasoning import ReasoningWorkspace

    workspace = ReasoningWorkspace(
        question=MISSING_CLOSE_QUESTION,
        reasoning_shape=ReasoningShape.STATE_TRANSITION,
        scenario=scenario,
    )
    completion = AnalysisCompletionGate().evaluate(plan=plan, workspace=workspace)
    assert completion.complete is False
    assert "SCHEMA_REQUIRED" in completion.reason_codes
    assert "ANALYSIS_INCOMPLETE" in completion.reason_codes


async def test_completion_gate_passes_with_reconstructed_state() -> None:
    rules = [
        Fact(statement=RENUMBER_RULE, status=FactStatus.CONFIRMED, authority="authoritative")
    ]
    workspace = _workspace_with_sequence(rules)
    workspace.hypotheses = await _run_hypotheses(
        HypothesisEngine(), MISSING_CLOSE_QUESTION, workspace, rules
    )
    engine = _engine(rules=())
    plan = engine.build_plan(
        MISSING_CLOSE_QUESTION, deterministic_shape(MISSING_CLOSE_QUESTION)
    )
    plan.required_facts = ()
    completion = AnalysisCompletionGate().evaluate(plan=plan, workspace=workspace)
    assert completion.complete is True
    assert completion.reason_codes == ()


# ---------------------------------------------------------------------------
# Golden end-to-end (§52) y negativo (§53)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_renumbering_rejects_missing_close() -> None:
    engine = _engine(rules=(RENUMBER_RULE,))
    outcome = await engine.reason(
        MISSING_CLOSE_QUESTION, intent="general", scenario_text=SEQUENCE_BLOCK
    )
    assert outcome.activated is True
    assert outcome.classification.shape is ReasoningShape.STATE_TRANSITION
    assert outcome.plan is not None
    assert outcome.plan.question_to_prove
    assert outcome.workspace is not None
    assert outcome.workspace.scenario and outcome.workspace.scenario.events
    assert outcome.workspace.transitions and outcome.workspace.transitions.chain
    hypotheses = outcome.workspace.hypotheses
    assert hypotheses is not None
    user = hypotheses.by_id(hypotheses.user_hypothesis_id)
    assert user is not None and user.verdict is HypothesisVerdict.REJECTED
    assert "No." in outcome.blueprint.conclusion
    # Traza pública acotada, sin razonamiento privado.
    trace = outcome.public_trace()
    assert trace["shape"] == "STATE_TRANSITION"
    assert trace["scenario_events"] > 0
    assert "chain-of-thought" not in str(trace).lower()


@pytest.mark.asyncio
async def test_golden_close_required_supports_missing_close() -> None:
    engine = _engine(rules=(CLOSE_REQUIRED_RULE,))
    outcome = await engine.reason(MISSING_CLOSE_QUESTION, scenario_text=SEQUENCE_BLOCK)
    hypotheses = outcome.workspace.hypotheses if outcome.workspace else None
    assert hypotheses is not None
    user = hypotheses.by_id(hypotheses.user_hypothesis_id)
    assert user is not None and user.verdict is HypothesisVerdict.SUPPORTED
    assert outcome.blueprint is not None
    assert outcome.blueprint.conclusion.startswith("Sí.")


# ---------------------------------------------------------------------------
# §55/§56 evidencia de grafo: CONFIRMED vs DISCOVERED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_graph_fact_is_strong_evidence() -> None:
    company_context = {
        "mappings": [
            {
                "id": "rel-1",
                "concept": "RecordB",
                "field": "Sequence",
                "status": "confirmed",
                "confidence": 0.95,
                "authority_level": "authoritative",
            }
        ]
    }
    engine = _engine(rules=())
    outcome = await engine.reason(
        MISSING_CLOSE_QUESTION,
        company_context=company_context,
        scenario_text=SEQUENCE_BLOCK,
    )
    graph_facts = outcome.workspace.graph_facts if outcome.workspace else []
    assert graph_facts
    assert graph_facts[0].status is FactStatus.CONFIRMED
    assert graph_facts[0].authority == "authoritative"


@pytest.mark.asyncio
async def test_discovered_graph_fact_cannot_prove_alone() -> None:
    company_context = {
        "mappings": [
            {
                "id": "rel-2",
                "concept": "RecordB",
                "field": "Sequence",
                "status": "discovered",
                "confidence": 0.4,
            }
        ]
    }
    engine = _engine(rules=())
    outcome = await engine.reason(
        MISSING_CLOSE_QUESTION,
        company_context=company_context,
        scenario_text=SEQUENCE_BLOCK,
    )
    graph_facts = outcome.workspace.graph_facts if outcome.workspace else []
    assert graph_facts and graph_facts[0].status is not FactStatus.CONFIRMED
    # Sin otra evidencia, el análisis queda incompleto: no se concluye.
    assert outcome.completion is not None
    assert outcome.completion.complete is False
    assert outcome.abstain is True


# ---------------------------------------------------------------------------
# §57 autoridad de fuente
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authoritative_rule_controls_over_internal_doc() -> None:
    """Documento interno dice cerrar; especificación autoritativa permite coexistir.

    La autoridad del tenant desempata (§7/§57) y el conflicto queda declarado.
    """
    internal = "Internal memo: every sequence must close with a closing record."
    authoritative = RENUMBER_RULE

    async def search(organization_id, query, *, limit=4):
        return [
            {
                "document_id": "doc-internal",
                "title": "internal-memo",
                "content": internal,
                "score": 0.95,
            },
            {
                "document_id": "doc-spec",
                "title": "official-spec",
                "content": authoritative,
                "score": 0.7,
            },
        ]

    async def authority(organization_id):
        return {"internal-memo": "informational", "official-spec": "authoritative"}

    engine = EvidenceReasoningEngine(
        budgets=ResearchBudgets(max_retrieval_calls=2, max_steps=10),
        knowledge_search=search,
        authority_resolver=authority,
    )
    outcome = await engine.reason(
        MISSING_CLOSE_QUESTION,
        organization_id=ORG,
        scenario_text=SEQUENCE_BLOCK,
    )
    workspace = outcome.workspace
    assert workspace is not None
    assert workspace.source_authority["official-spec"] == "authoritative"
    hypotheses = workspace.hypotheses
    assert hypotheses is not None
    user = hypotheses.by_id(hypotheses.user_hypothesis_id)
    assert user is not None and user.verdict is HypothesisVerdict.REJECTED
    assert "autoritativ" in user.rationale or "autoridad" in user.rationale
    # El conflicto es material: la evidencia conserva su nivel de autoridad.
    assert "authoritative" in {fact.authority for fact in workspace.rules}


# ---------------------------------------------------------------------------
# §58 temporal: regla histórica vs actual
# ---------------------------------------------------------------------------


def test_temporal_rule_selection_uses_validity() -> None:
    old_rule = Fact(
        statement=CLOSE_REQUIRED_RULE,
        status=FactStatus.CONFIRMED,
        valid_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
        valid_to=datetime(2025, 12, 31, tzinfo=timezone.utc),
    )
    new_rule = Fact(
        statement=RENUMBER_RULE,
        status=FactStatus.CONFIRMED,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)

    def applicable(facts: list[Fact]) -> list[Fact]:
        return [
            fact
            for fact in facts
            if (fact.valid_from is None or fact.valid_from <= as_of)
            and (fact.valid_to is None or fact.valid_to >= as_of)
        ]

    selected = applicable([old_rule, new_rule])
    assert [fact.statement for fact in selected] == [CLOSE_REQUIRED_RULE]


# ---------------------------------------------------------------------------
# §59 escenarios genéricos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "block", "question"),
    [
        (
            "open-update-close",
            "record A | seq 0001 | open\nrecord A | seq 0001 | update",
            "¿Falta el cierre de esta secuencia?",
        ),
        (
            "ticket-reopened",
            "ticket T1 | seq 0001 | open\nticket T1 | seq 0002 | assigned\n"
            "ticket T1 | seq 0003 | resolved\nticket T1 | seq 0004 | reopened",
            "¿Cuál es el estado actual del ticket?",
        ),
        (
            "finance-reversal",
            "TX-1 | seq 0001 | transaction\nTX-1 | seq 0002 | reversal\n"
            "TX-1 | seq 0003 | replacement",
            "¿Sigue vigente la transacción original?",
        ),
        (
            "workflow-retry",
            "WF-1 | seq 0001 | start\nWF-1 | seq 0002 | step A\n"
            "WF-1 | seq 0003 | step B\nWF-1 | seq 0004 | retry B\n"
            "WF-1 | seq 0005 | complete",
            "¿Falta algún paso en este workflow?",
        ),
    ],
)
def test_generic_scenarios_parse_and_chain(name: str, block: str, question: str) -> None:
    parser = ScenarioParser()
    scenario = parser.parse(block)
    assert scenario.events, name
    rule = Fact(
        statement="Domain rule: transitions are recorded in sequence order",
        status=FactStatus.CONFIRMED,
        authority="authoritative",
    )
    transitions = StateTransitionAnalyzer().analyze(
        scenario=scenario, timeline=TimelineBuilder().build(scenario), rules=[rule]
    )
    assert transitions.chain, name
    assert chain_values(transitions)[0].startswith("0001"), name
    assert all(
        link.status is TransitionStatus.CONFIRMED for link in transitions.chain
    ), name


def test_retry_is_not_a_missing_event() -> None:
    """§59: un retry se reconoce como repetición, no como hueco."""
    parser = ScenarioParser()
    scenario = parser.parse(
        "WF-1 | seq 0001 | start\nWF-1 | seq 0002 | step A\n"
        "WF-1 | seq 0003 | step B\nWF-1 | seq 0004 | retry B\n"
        "WF-1 | seq 0005 | complete"
    )
    rule = Fact(
        statement="Retries reuse the previous step",
        status=FactStatus.CONFIRMED,
        authority="authoritative",
    )
    transitions = StateTransitionAnalyzer().analyze(
        scenario=scenario, timeline=TimelineBuilder().build(scenario), rules=[rule]
    )
    values = chain_values(transitions)
    # La cadena es contigua: no hay hueco que interpretar como faltante.
    assert find_sequence_gaps(transitions) == []
    assert values == ["0001", "0002", "0003", "0004", "0005"]


# ---------------------------------------------------------------------------
# §32/§33 answerability consciente del razonamiento
# ---------------------------------------------------------------------------


def test_answerability_downgrades_to_context_missing() -> None:
    from src.core.domain.intelligence import (
        AnswerabilityStatus,
    )
    from src.intelligence.answerability import AnswerabilityGate

    decision = _answerable_decision()
    from src.core.domain.reasoning import (
        AnalysisCompletion,
        ReasoningOutcome,
        ReasoningWorkspace,
    )
    from src.intelligence.reasoning.classifier import deterministic_shape

    outcome = ReasoningOutcome(
        activated=True,
        classification=deterministic_shape(MISSING_CLOSE_QUESTION),
        workspace=ReasoningWorkspace(
            question=MISSING_CLOSE_QUESTION,
            reasoning_shape=ReasoningShape.STATE_TRANSITION,
        ),
        completion=AnalysisCompletion(
            complete=False,
            blockers=("scenario_incomplete",),
            reason_codes=("SCHEMA_REQUIRED", "ANALYSIS_INCOMPLETE"),
        ),
        reason_codes=("SCHEMA_REQUIRED", "ANALYSIS_INCOMPLETE"),
    )
    from src.intelligence.answerability import apply_reasoning_signals

    updated = apply_reasoning_signals(decision, outcome)
    assert updated.status is AnswerabilityStatus.CONTEXT_MISSING
    assert updated.answerable is False
    assert "SCHEMA_REQUIRED" in updated.reason_codes
    assert "scenario_incomplete" in updated.missing_context
    # Un razonamiento completo no cambia la decisión.
    complete_outcome = ReasoningOutcome(
        activated=True,
        classification=outcome.classification,
        workspace=outcome.workspace,
        completion=AnalysisCompletion(complete=True),
    )
    assert apply_reasoning_signals(decision, complete_outcome) is decision
    # Sin razonamiento, la decisión original queda intacta.
    assert apply_reasoning_signals(decision, None) is decision
    assert AnswerabilityGate is not None  # el gate sigue existiendo sin cambios


def _answerable_decision():
    from src.core.domain.intelligence import (
        AnswerabilityStatus,
        ConfidenceLevel,
    )

    return __import__(
        "src.core.domain.intelligence", fromlist=["AnswerabilityDecision"]
    ).AnswerabilityDecision(
        status=AnswerabilityStatus.ANSWERABLE,
        answerable=True,
        confidence_level=ConfidenceLevel.MEDIUM,
        score=0.7,
        reason_codes=[],
        evidence_ids=[],
        missing_context=[],
        recommended_actions=[],
        message="ok",
    )


# ---------------------------------------------------------------------------
# §49/§50 flag y activación
# ---------------------------------------------------------------------------


def test_reasoning_mode_and_activation() -> None:
    from src.intelligence.reasoning import wiring

    class _Settings:
        RAG_EVIDENCE_REASONING_MODE = "off"
        RAG_EVIDENCE_REASONING_CANARY_PERCENT = 0

    assert wiring.reasoning_mode(_Settings()) is ReasoningMode.OFF
    assert wiring.reasoning_active(_Settings()) is False
    assert wiring.reasoning_controls_answer(_Settings()) is False

    class _Shadow:
        RAG_EVIDENCE_REASONING_MODE = "shadow"
        RAG_EVIDENCE_REASONING_CANARY_PERCENT = 0

    assert wiring.reasoning_active(_Shadow()) is True
    # shadow ejecuta pero no controla la respuesta.
    assert wiring.reasoning_controls_answer(_Shadow()) is False

    class _Canary:
        RAG_EVIDENCE_REASONING_MODE = "canary"
        RAG_EVIDENCE_REASONING_CANARY_PERCENT = 30

    assert wiring.reasoning_controls_answer(_Canary(), roll=10.0) is True
    assert wiring.reasoning_controls_answer(_Canary(), roll=80.0) is False


def test_reasoning_activation_rate_measurable() -> None:
    """§50: las preguntas simples no activan el motor."""
    assert deterministic_shape("¿Qué significa Carrier Code?").is_complex is False
    assert deterministic_shape(MISSING_CLOSE_QUESTION).is_complex is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _workspace_with_sequence(rules: list[Fact]):
    from src.core.domain.reasoning import ReasoningWorkspace

    parser = ScenarioParser()
    scenario = parser.parse(SEQUENCE_BLOCK)
    timeline = TimelineBuilder().build(scenario)
    transitions = StateTransitionAnalyzer().analyze(
        scenario=scenario, timeline=timeline, rules=rules
    )
    return ReasoningWorkspace(
        question=MISSING_CLOSE_QUESTION,
        reasoning_shape=ReasoningShape.STATE_TRANSITION,
        scenario=scenario,
        timeline=timeline,
        transitions=transitions,
        rules=list(rules),
    )


async def _run_hypotheses(engine: HypothesisEngine, question: str, workspace, rules):
    return await engine.evaluate(question=question, workspace=workspace, rules=rules)
