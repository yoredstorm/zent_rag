# =============================================================================
# Agent Runtime — razonamiento: regresiones de early answer (§34/§61/§62/§63)
# =============================================================================
# El runtime no debe responder con evidencia parcial cuando el escenario está
# incompleto, y debe seguir siendo rápido cuando la pregunta es simple.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from src.agents.runtime.reasoning_step import (
    ANALYSIS_ANSWER_RULE,
    DEFAULT_ANSWER_RULE,
    ReasoningRunState,
    abstention_answer,
    answer_rule,
    reasoning_steps,
    record_termination_skipped,
    should_block_direct_answer,
    workspace_block,
)

ORG = uuid4()

SEQUENCE_BLOCK = """
record A | carrier AA | seq 0005
record B | seq 0006
record B | seq 0010
record B | seq 0038
record A | carrier AA | seq 0013
"""

RENUMBER_RULE = (
    "Record B renumbers existing sequences to open ordering space; multiple "
    "active sequences may coexist and no closing record is required."
)


def _complex_state(analysis_complete: bool = False) -> ReasoningRunState:
    return ReasoningRunState(
        enabled=True,
        mode="on",
        shape="STATE_TRANSITION",
        is_complex=True,
        analysis_complete=analysis_complete,
    )


# ---------------------------------------------------------------------------
# §34/§62 regla del prompt
# ---------------------------------------------------------------------------


def test_simple_lookup_keeps_current_answer_rule() -> None:
    """Sin razonamiento activo, la regla 8 es la de siempre."""
    assert answer_rule(None) == DEFAULT_ANSWER_RULE
    state = ReasoningRunState(enabled=True, shape="SIMPLE_LOOKUP", is_complex=False)
    assert answer_rule(state) == DEFAULT_ANSWER_RULE
    assert "After a tool observation" in DEFAULT_ANSWER_RULE


def test_complex_shape_replaces_answer_rule() -> None:
    state = _complex_state()
    rule = answer_rule(state)
    assert rule == ANALYSIS_ANSWER_RULE
    assert "NOT enough to answer" in rule
    assert "missing evidence" in rule


# ---------------------------------------------------------------------------
# §61 el agente no responde apenas ve un documento relevante
# ---------------------------------------------------------------------------


def test_direct_answer_is_withheld_while_analysis_incomplete() -> None:
    state = _complex_state()
    assert should_block_direct_answer(state, step_index=0, max_steps=8) is True
    # Cada bloqueo queda contabilizado para observabilidad.
    assert state.blocked_direct_answers == 1


def test_direct_answer_allowed_when_analysis_complete() -> None:
    state = _complex_state(analysis_complete=True)
    assert should_block_direct_answer(state, step_index=0, max_steps=8) is False
    assert state.blocked_direct_answers == 0


def test_budget_exhaustion_allows_answering() -> None:
    """Con presupuesto agotado se permite responder: no hay loop abierto."""
    state = _complex_state()
    assert should_block_direct_answer(state, step_index=7, max_steps=8) is False


def test_simple_lookup_never_blocks() -> None:
    state = ReasoningRunState(enabled=True, shape="SIMPLE_LOOKUP", is_complex=False)
    assert should_block_direct_answer(state, step_index=0, max_steps=8) is False


# ---------------------------------------------------------------------------
# §37 termination gate analysis-aware
# ---------------------------------------------------------------------------


def test_termination_gate_held_when_incomplete() -> None:
    state = _complex_state()
    step = record_termination_skipped(state, reason="termination_gate")
    assert step is not None
    assert step["type"] == "reasoning_incomplete"
    assert "STATE_TRANSITION" in step["detail"]


def test_termination_gate_not_held_when_complete() -> None:
    state = _complex_state(analysis_complete=True)
    assert record_termination_skipped(state, reason="termination_gate") is None
    assert record_termination_skipped(None, reason="termination_gate") is None


# ---------------------------------------------------------------------------
# §38/§46 workspace en la respuesta final y traza pública
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_block_reports_facts_and_hypotheses() -> None:
    from src.core.domain.reasoning import (
        AnalysisCompletion,
        AnswerBlueprint,
        CompletionCheck,
        ReasoningOutcome,
        ReasoningShape,
        ReasoningWorkspace,
    )
    from src.intelligence.reasoning.classifier import deterministic_shape

    outcome = ReasoningOutcome(
        activated=True,
        classification=deterministic_shape("¿Falta un registro para cerrar esta secuencia?"),
        workspace=ReasoningWorkspace(
            question="¿Falta un registro?",
            reasoning_shape=ReasoningShape.STATE_TRANSITION,
            unknowns=["Salto de numeración entre 0010 y 0038"],
            source_authority={"official-spec": "authoritative"},
        ),
        completion=AnalysisCompletion(
            complete=False,
            checks=(CompletionCheck(name="scenario_parsed", satisfied=False),),
            blockers=("scenario_incomplete",),
            reason_codes=("SCHEMA_REQUIRED",),
        ),
        blueprint=AnswerBlueprint(conclusion="No puedo determinarlo todavía."),
    )
    state = ReasoningRunState(
        enabled=True,
        mode="on",
        shape="STATE_TRANSITION",
        is_complex=True,
        outcome=outcome,
    )
    block = workspace_block(state)
    assert "ANALYSIS WORKSPACE" in block
    assert "CRITICAL UNKNOWNS" in block
    assert "SOURCE AUTHORITY" in block
    assert "INCOMPLETE ANALYSIS BLOCKERS" in block
    # Nunca razonamiento privado: sólo hechos, veredictos y límites.
    for forbidden in ("chain-of-thought", "let me think", "internal reasoning"):
        assert forbidden not in block.lower()


@pytest.mark.asyncio
async def test_reasoning_steps_are_public_and_bounded() -> None:
    from src.core.domain.reasoning import ReasoningOutcome, ReasoningShape
    from src.intelligence.reasoning.classifier import deterministic_shape

    outcome = ReasoningOutcome(
        activated=False,
        classification=deterministic_shape("¿Qué significa Carrier Code?"),
    )
    state = ReasoningRunState(
        enabled=True, shape="SIMPLE_LOOKUP", is_complex=False, outcome=outcome
    )
    steps = reasoning_steps(state)
    types = [step["type"] for step in steps]
    assert types[0] == "reasoning_classification"
    assert "reasoning_plan" not in types  # fast path: sin plan
    assert "scenario_parse" not in types

    complex_state = _complex_state()
    complex_state.outcome = ReasoningOutcome(
        activated=True,
        classification=deterministic_shape(
            "¿Falta un registro para cerrar esta secuencia?"
        ),
        workspace=__import__(
            "src.core.domain.reasoning", fromlist=["ReasoningWorkspace"]
        ).ReasoningWorkspace(
            question="q", reasoning_shape=ReasoningShape.STATE_TRANSITION
        ),
    )
    complex_steps = [step["type"] for step in reasoning_steps(complex_state)]
    assert "scenario_parse" in complex_steps
    assert "state_reconstruction" in complex_steps
    assert "hypothesis_test" in complex_steps
    assert "analysis_completion" in complex_steps


def test_abstention_answer_states_what_is_missing() -> None:
    from src.core.domain.reasoning import (
        AnalysisCompletion,
        AnswerBlueprint,
        ReasoningOutcome,
    )
    from src.intelligence.reasoning.classifier import deterministic_shape

    outcome = ReasoningOutcome(
        activated=True,
        classification=deterministic_shape("¿Falta un registro?"),
        completion=AnalysisCompletion(
            complete=False,
            blockers=("scenario_incomplete",),
            reason_codes=("SCHEMA_REQUIRED",),
        ),
        blueprint=AnswerBlueprint(
            conclusion="No puedo determinarlo todavía.",
            limitations=("Falta el layout de los registros",),
        ),
    )
    state = ReasoningRunState(
        enabled=True, shape="STATE_TRANSITION", is_complex=True, outcome=outcome
    )
    answer = abstention_answer(state)
    assert "No puedo determinarlo todavía" in answer
    assert "scenario_incomplete" in answer
    assert "layout" in answer


# ---------------------------------------------------------------------------
# §63 Company Context automático y explícito
# ---------------------------------------------------------------------------


@dataclass
class _FakeAgent:
    id: UUID = field(default_factory=uuid4)
    organization_id: UUID = ORG


@pytest.mark.asyncio
async def test_company_context_is_compiled_when_absent(monkeypatch) -> None:
    """El caller no tiene que poblar request.context: se compila solo."""
    from src.agents.runtime import reasoning_step as step
    from src.intelligence.reasoning import wiring

    compiled_calls: list[str] = []

    class _Settings:
        RAG_EVIDENCE_REASONING_MODE = "on"
        RAG_EVIDENCE_REASONING_CANARY_PERCENT = 100

    class _Engine:
        company_context_provider = object()

        class classifier:
            @staticmethod
            async def classify(message: str):
                from src.core.domain.reasoning import ReasoningShape

                class _C:
                    shape = ReasoningShape.STATE_TRANSITION
                    is_complex = True
                    intent = "general"

                return _C()

        async def _compile_company_context(self, organization_id, question, **kwargs):
            compiled_calls.append(question)
            return {"concepts": [{"name": "RecordB"}], "memories": [{"id": "m1"}]}

        async def reason(self, message, **kwargs):
            from src.core.domain.reasoning import ReasoningOutcome
            from src.intelligence.reasoning.classifier import deterministic_shape

            assert kwargs.get("company_context"), "el contexto compilado debe llegar"
            return ReasoningOutcome(
                activated=True,
                classification=deterministic_shape(message),
                workspace=None,
                completion=None,
            )

    monkeypatch.setattr(wiring, "reasoning_mode", lambda settings=None: type(
        "M", (), {"value": "on"}
    )())
    monkeypatch.setattr(wiring, "reasoning_active", lambda settings=None, roll=None: True)
    monkeypatch.setattr(wiring, "evidence_reasoning_engine", lambda settings=None: _Engine())

    state = await step.prepare_reasoning_state(
        organization_id=ORG,
        message="¿Falta un registro para cerrar esta secuencia?",
        request_context=None,
        agent_id=uuid4(),
    )
    assert compiled_calls, "debe compilar Company Context sin que el caller lo pase"
    assert state.company_context_used is True
    assert state.memory_hits == 1
    assert "concepts" in state.company_context_sections


@pytest.mark.asyncio
async def test_explicit_request_context_wins_and_is_not_recompiled(monkeypatch) -> None:
    from src.agents.runtime import reasoning_step as step
    from src.intelligence.reasoning import wiring

    calls: list[str] = []

    class _Engine:
        company_context_provider = object()

        class classifier:
            @staticmethod
            async def classify(message: str):
                from src.core.domain.reasoning import ReasoningShape

                class _C:
                    shape = ReasoningShape.STATE_TRANSITION
                    is_complex = True
                    intent = "general"

                return _C()

        async def _compile_company_context(self, *args, **kwargs):
            calls.append("compiled")
            return {"concepts": [{"name": "should-not-be-used"}]}

        async def reason(self, message, **kwargs):
            from src.core.domain.reasoning import ReasoningOutcome
            from src.intelligence.reasoning.classifier import deterministic_shape

            assert kwargs["company_context"]["concepts"] == [{"name": "from-workflow"}]
            return ReasoningOutcome(
                activated=True, classification=deterministic_shape(message)
            )

    monkeypatch.setattr(
        wiring, "reasoning_mode", lambda settings=None: type("M", (), {"value": "on"})()
    )
    monkeypatch.setattr(wiring, "reasoning_active", lambda settings=None, roll=None: True)
    monkeypatch.setattr(wiring, "evidence_reasoning_engine", lambda settings=None: _Engine())

    state = await step.prepare_reasoning_state(
        organization_id=ORG,
        message="¿Falta un registro para cerrar esta secuencia?",
        request_context={"company_context": {"concepts": [{"name": "from-workflow"}]}},
    )
    assert calls == [], "no se compila dos veces si el contexto ya viene"
    assert state.company_context_used is True


@pytest.mark.asyncio
async def test_simple_lookup_skips_company_context_and_reasoning(monkeypatch) -> None:
    from src.agents.runtime import reasoning_step as step
    from src.intelligence.reasoning import wiring

    class _Engine:
        company_context_provider = object()

        class classifier:
            @staticmethod
            async def classify(message: str):
                from src.core.domain.reasoning import ReasoningShape

                class _C:
                    shape = ReasoningShape.SIMPLE_LOOKUP
                    is_complex = False
                    intent = "concept_definition"

                return _C()

        async def _compile_company_context(self, *args, **kwargs):
            raise AssertionError("no debe compilar contexto en fast path")

        async def reason(self, *args, **kwargs):
            raise AssertionError("no debe razonar en fast path")

    monkeypatch.setattr(
        wiring, "reasoning_mode", lambda settings=None: type("M", (), {"value": "on"})()
    )
    monkeypatch.setattr(wiring, "reasoning_active", lambda settings=None, roll=None: True)
    monkeypatch.setattr(wiring, "evidence_reasoning_engine", lambda settings=None: _Engine())

    state = await step.prepare_reasoning_state(
        organization_id=ORG,
        message="¿Qué significa Carrier Code?",
        request_context=None,
    )
    assert state.enabled is True
    assert state.is_complex is False
    assert state.company_context_used is False
    assert state.outcome is None


@pytest.mark.asyncio
async def test_reasoning_is_off_by_default(monkeypatch) -> None:
    """Con el flag en off, el runtime no cambia de comportamiento."""
    from src.agents.runtime import reasoning_step as step

    monkeypatch.setattr(
        "src.core.config.get_settings",
        lambda: type("S", (), {"RAG_EVIDENCE_REASONING_MODE": "off"})(),
    )
    state = await step.prepare_reasoning_state(
        organization_id=ORG, message="¿Qué significa Carrier Code?", request_context=None
    )
    assert state.enabled is False
    assert state.outcome is None
    assert answer_rule(state) == DEFAULT_ANSWER_RULE
