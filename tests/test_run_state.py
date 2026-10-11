# =============================================================================
# AgentRunState — contrato canónico, lifecycle, invariantes y wiring runtime
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar
from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import (
    AgentRunRequest,
    AgentRunResult,
    AgentRuntime,
)
from src.agents.tools.base import Tool, ToolContext, ToolResult
from src.agents.tools.registry import register_tool
from src.core.domain.entities import Agent, LLMResponse
from src.core.ports import LLMProvider
from src.runtime.run_state import (
    AgentRunState,
    RunIdentity,
    RunPhase,
    finalize_state,
    terminal_phase_for,
)


@pytest.fixture(autouse=True)
def _runtime_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests no dependen de los flags demo del .env local."""
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RUNTIME_TOOL_ROUTING_MODE", "off")
    monkeypatch.setattr(settings, "RUNTIME_TERMINATION_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_ANSWER_GATE", "off")
    monkeypatch.setattr(settings, "RUNTIME_AGENT_JEV_LOOP", "off")
    monkeypatch.setattr(settings, "RUNTIME_SOURCE_AWARE_TOOLS", False)


def _identity() -> RunIdentity:
    return RunIdentity(run_id=str(uuid4()), organization_id=str(uuid4()))


def _state() -> AgentRunState:
    return AgentRunState(identity=_identity())


class _FakeLLM(LLMProvider):
    def __init__(self, contents: list[str], tokens: int = 10) -> None:
        self.contents = contents
        self.tokens = tokens
        self.calls = 0

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        idx = min(self.calls, len(self.contents) - 1)
        self.calls += 1
        return LLMResponse(
            content=self.contents[idx],
            model="fake",
            prompt_tokens=self.tokens,
            completion_tokens=self.tokens,
            total_tokens=self.tokens * 2,
        )

    async def generate_stream(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model=None):  # pragma: no cover
        raise NotImplementedError

    async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
        return []


class _EchoTool(Tool):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Devuelve el input."
    input_schema: ClassVar[dict] = {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
    }

    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        return ToolResult(output=f"echo: {arguments['text']}")


def _agent(**overrides) -> Agent:
    params = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "name": "test-agent",
        "tools": ["echo"],
    }
    params.update(overrides)
    return Agent(**params)


def _request(agent: Agent, message: str = "hola") -> AgentRunRequest:
    return AgentRunRequest(agent=agent, message=message, role="admin")


# -----------------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------------
class TestLifecycle:
    def test_happy_path_avanza_y_registra(self) -> None:
        state = _state()
        path = [
            RunPhase.CLASSIFIED,
            RunPhase.PLANNED,
            RunPhase.EVIDENCE_REQUIRED,
            RunPhase.RETRIEVING,
            RunPhase.REASONING,
            RunPhase.ACTION_REQUIRED,
            RunPhase.ACTING,
            RunPhase.REASONING,
            RunPhase.READY_TO_FINALIZE,
            RunPhase.FINALIZED,
        ]
        for phase in path:
            assert state.try_advance(phase), f"transición rechazada: {phase}"
        assert state.phase is RunPhase.FINALIZED
        assert state.terminal is True
        assert [entry["phase"] for entry in state.trace.phase_history] == [
            str(phase) for phase in path
        ]
        assert state.trace.notes == []

    def test_transicion_invalida_se_registra_y_no_mueve(self) -> None:
        state = _state()
        assert state.try_advance(RunPhase.FINALIZED) is True  # terminal desde CREATED
        assert state.try_advance(RunPhase.REASONING) is False
        assert state.phase is RunPhase.FINALIZED
        assert any(note.startswith("phase_rejected:") for note in state.trace.notes)

    def test_salto_invalido_entre_fases_no_terminales(self) -> None:
        state = _state()
        assert state.try_advance(RunPhase.CLASSIFIED)
        assert state.try_advance(RunPhase.ACTING) is False  # falta PLANNED
        assert state.phase is RunPhase.CLASSIFIED

    def test_misma_fase_es_idempotente(self) -> None:
        state = _state()
        assert state.try_advance(RunPhase.CREATED)


class TestTerminalPhaseMapping:
    @pytest.mark.parametrize(
        ("status", "answer", "answer_state", "expected"),
        [
            ("error", "", None, RunPhase.FAILED),
            ("limit_reached", "parcial", None, RunPhase.LIMIT_REACHED),
            ("awaiting_approval", "", None, RunPhase.BLOCKED),
            ("completed", "ok", None, RunPhase.FINALIZED),
            ("completed", "", None, RunPhase.BLOCKED),
            (
                "completed",
                "mensaje",
                {"state": "INSUFFICIENT_EVIDENCE"},
                RunPhase.ABSTAINED,
            ),
            (
                "completed",
                "mensaje",
                {"state": "CONFLICTING_EVIDENCE"},
                RunPhase.ABSTAINED,
            ),
            (
                "completed",
                "mensaje",
                {"state": "UNDETERMINED_RULE"},
                RunPhase.UNDETERMINED,
            ),
            (
                "completed",
                "mensaje",
                {"state": "RETRIEVAL_UNAVAILABLE"},
                RunPhase.BLOCKED,
            ),
            (
                "completed",
                "mensaje",
                {"state": "GROUNDING_ENGINE_FAILED"},
                RunPhase.BLOCKED,
            ),
        ],
    )
    def test_mapeo(self, status, answer, answer_state, expected) -> None:
        assert (
            terminal_phase_for(status=status, answer=answer, answer_state=answer_state)
            is expected
        )


# -----------------------------------------------------------------------------
# Invariantes
# -----------------------------------------------------------------------------
class TestInvariants:
    def test_finalized_sin_answer_viola(self) -> None:
        state = _state()
        assert state.try_advance(RunPhase.CLASSIFIED)
        assert state.try_advance(RunPhase.READY_TO_FINALIZE)
        assert state.try_advance(RunPhase.FINALIZED)
        violations = state.check_invariants()
        assert "terminal_phase_without_answer:FINALIZED" in violations

    def test_finalized_con_answer_es_consistente(self) -> None:
        state = _state()
        violations = finalize_state(state, status="completed", answer="ok", answer_state=None)
        assert violations == ()
        assert state.phase is RunPhase.FINALIZED

    def test_determinista_sin_envelope_viola(self) -> None:
        state = _state()
        state.decisions.requires_deterministic = True
        violations = finalize_state(state, status="completed", answer="MATCH", answer_state=None)
        assert "deterministic_finalized_without_envelope" in violations

    def test_envelope_autoritativo_contradicho_viola(self) -> None:
        state = _state()
        state.decisions.set_envelope(SimpleNamespace(authoritative=True, state="MATCH"))
        state.decisions.guard = SimpleNamespace(action="internal_conflict")
        violations = finalize_state(state, status="completed", answer="x", answer_state=None)
        assert "authoritative_decision_contradicted" in violations

    def test_presupuesto_agotado_sin_llamadas_extra(self) -> None:
        state = _state()
        state.budget.ledger = SimpleNamespace(remaining_tokens=10, remaining_cost_usd=None)
        assert state.budget.note_expensive_call("llm") is True
        state.budget.ledger = SimpleNamespace(remaining_tokens=0, remaining_cost_usd=None)
        assert state.budget.note_expensive_call("llm") is False
        violations = finalize_state(state, status="completed", answer="ok", answer_state=None)
        assert "expensive_calls_after_budget_exhausted:1" in violations

    def test_tool_fuera_de_allowlist_viola(self) -> None:
        state = _state()
        state.tools.set_allowed(["echo"])
        assert state.tools.note_call("echo") is True
        assert state.tools.note_call("search_knowledge") is False
        violations = finalize_state(state, status="completed", answer="ok", answer_state=None)
        assert "tool_executed_outside_allowlist:search_knowledge" in violations

    def test_cadena_de_evidencia_citado_implica_uso(self) -> None:
        state = _state()
        state.evidence.observe_usage(selected=frozenset({"E1", "E2"}))
        state.evidence.observe_usage(cited=frozenset({"E3"}))
        violations = finalize_state(state, status="completed", answer="ok", answer_state=None)
        assert "evidence_chain:cited_not_used" in violations

    def test_cadena_de_evidencia_usado_implica_seleccionado(self) -> None:
        state = _state()
        state.evidence.observe_usage(used=frozenset({"E9"}))
        violations = finalize_state(state, status="completed", answer="ok", answer_state=None)
        assert "evidence_chain:used_not_selected" in violations

    def test_analisis_incompleto_no_cierra_normal(self) -> None:
        state = _state()
        state.reasoning.run = SimpleNamespace(
            enabled=True,
            is_complex=True,
            analysis_complete=False,
            blocks_early_answer=True,
        )
        violations = finalize_state(state, status="completed", answer="ok", answer_state=None)
        assert "incomplete_analysis_finalized" in violations

    def test_analisis_incompleto_con_limite_no_viola(self) -> None:
        state = _state()
        state.reasoning.run = SimpleNamespace(
            enabled=True,
            is_complex=True,
            analysis_complete=False,
            blocks_early_answer=True,
        )
        violations = finalize_state(
            state, status="limit_reached", answer="parcial", answer_state=None
        )
        assert "incomplete_analysis_finalized" not in violations

    def test_retrieval_failed_no_es_insuficiencia(self) -> None:
        state = _state()
        state.evidence.retrieval_failed = True
        violations = finalize_state(
            state,
            status="completed",
            answer="mensaje",
            answer_state={"state": "INSUFFICIENT_EVIDENCE"},
        )
        assert "retrieval_failure_reported_as_insufficiency" in violations

    def test_envelope_reemplazado_con_contenido_distinto_viola(self) -> None:
        state = _state()
        first = SimpleNamespace(authoritative=True, state="MATCH")
        second = SimpleNamespace(authoritative=True, state="NO_MATCH")
        state.decisions.set_envelope(first)
        state.decisions.set_envelope(first)
        assert state.decisions.envelope_conflict is False
        state.decisions.set_envelope(second)
        violations = finalize_state(state, status="completed", answer="ok", answer_state=None)
        assert "authoritative_decision_replaced" in violations


# -----------------------------------------------------------------------------
# Agregador: envuelve, no duplica
# -----------------------------------------------------------------------------
class TestAggregation:
    def test_referencias_son_las_mismas_instancias(self) -> None:
        state = _state()
        registry = object()
        selection = object()
        sufficiency = object()
        state.evidence.observe(
            registry=registry, selection=selection, sufficiency=sufficiency
        )
        assert state.evidence.registry is registry
        assert state.evidence.selection is selection
        assert state.evidence.sufficiency is sufficiency

    def test_evidence_complete_delega_en_sufficiency(self) -> None:
        state = _state()
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=True, recommended_action="generate"
            )
        )
        assert state.evidence.complete is True
        assert state.evidence.insufficient is False
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=False, recommended_action="retrieve_more"
            )
        )
        assert state.evidence.complete is False
        assert state.evidence.insufficient is True

    def test_observation_usage_no_pisa_ejes_ausentes(self) -> None:
        state = _state()
        state.evidence.observe_usage(selected=frozenset({"E1"}))
        state.evidence.observe_usage(cited=frozenset({"E1"}))
        assert state.evidence.selected == frozenset({"E1"})
        assert state.evidence.cited == frozenset({"E1"})

    def test_public_dict_serializable(self) -> None:
        state = _state()
        payload = state.to_public_dict()
        assert payload["contract"] == "agent-run-state-1"
        assert payload["phase"] == "CREATED"
        json.dumps(payload)

    def test_agent_run_result_sin_state_es_none(self) -> None:
        result = AgentRunResult(
            run_id=uuid4(),
            agent_id=uuid4(),
            organization_id=None,
            status="error",
            answer="",
        )
        assert result.run_state is None


# -----------------------------------------------------------------------------
# Wiring del AgentRuntime
# -----------------------------------------------------------------------------
class TestRuntimeWiring:
    @pytest.mark.asyncio
    async def test_run_publica_estado_canonico(self) -> None:
        register_tool(_EchoTool())
        llm = _FakeLLM(
            [
                '{"tool": "echo", "arguments": {"text": "hello"}}',
                '{"answer": "Todo listo"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(), "cuentame sobre el record 4"))

        state = result.run_state
        assert isinstance(state, AgentRunState)
        assert state.phase is RunPhase.FINALIZED
        assert state.terminal is True
        assert state.answer.present is True
        assert state.answer.text == "Todo listo"
        assert state.answer.status == "completed"
        # Tools: allowlist efectiva y ejecución real quedan en el estado.
        assert "echo" in state.tools.allowed
        assert state.tools.used == frozenset({"echo"})
        assert state.tools.calls == 1
        # Lifecycle: pasó por razonamiento y por una acción real.
        phases = [entry["phase"] for entry in state.trace.phase_history]
        assert "CLASSIFIED" in phases
        assert "PLANNED" in phases
        assert "REASONING" in phases
        assert "ACTING" in phases
        # Sin violaciones y sin step de diagnóstico.
        assert state.trace.violations == []
        assert all(step.get("type") != "run_invariants" for step in result.steps)
        # Proyección pública serializable.
        json.dumps(state.to_public_dict())

    @pytest.mark.asyncio
    async def test_run_directo_sin_tools_tambien_cierra(self) -> None:
        llm = _FakeLLM(['{"answer": "Sin tools"}'])
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(tools=[])))

        state = result.run_state
        assert isinstance(state, AgentRunState)
        assert state.phase is RunPhase.FINALIZED
        assert state.tools.used == frozenset()
        assert state.trace.violations == []
        assert result.answer == "Sin tools"

    @pytest.mark.asyncio
    async def test_run_state_no_altera_payload_existente(self) -> None:
        """Compatibilidad: los campos históricos del resultado siguen igual."""
        register_tool(_EchoTool())
        llm = _FakeLLM(
            [
                '{"tool": "echo", "arguments": {"text": "x"}}',
                '{"answer": "ok"}',
            ]
        )
        runtime = AgentRuntime(llm_provider=llm)
        result = await runtime.run(_request(_agent(), "cuentame sobre el record 4"))

        assert result.status == "completed"
        assert result.answer == "ok"
        assert any(s["type"] == "tool_call" for s in result.steps)
        assert result.evidence is not None
        # El estado canónico no reemplaza ni reescribe los campos de contrato.
        assert result.run_state.answer.text == result.answer
        assert result.run_state.answer.status == result.status


# -----------------------------------------------------------------------------
# Fase D/E: autoridad reutilizada, métrica de invariantes y modo estricto
# -----------------------------------------------------------------------------
class TestStrictModeAndMetrics:
    def test_critical_violations_filtra_solo_riesgo_de_correccion(self) -> None:
        state = _state()
        state.trace.violations = [
            "evidence_chain:cited_not_used",
            "authoritative_decision_contradicted",
            "terminal_phase_without_answer:FINALIZED",
        ]
        assert state.critical_violations() == ("authoritative_decision_contradicted",)

    def test_observe_violations_emite_metrica(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_run_state_violations_total,
        )
        from src.runtime.run_state import observe_violations

        counter = zent_run_state_violations_total.labels(
            path="agent", kind="evidence_chain"
        )
        before = counter._value.get()
        observe_violations("agent", ["evidence_chain:cited_not_used"])
        assert counter._value.get() == before + 1

    def test_strict_block_reemplaza_respuesta_por_estado_no_concluyente(self) -> None:
        from src.agents.runtime.agent_runtime import _strict_block_run_state

        state = _state()
        state.trace.violations = ["authoritative_decision_contradicted"]
        result = AgentRunResult(
            run_id=uuid4(),
            agent_id=uuid4(),
            organization_id=None,
            status="completed",
            answer="Sí, cumple.",
        )
        assert _strict_block_run_state(state, result) is True
        assert result.answer != "Sí, cumple."
        assert result.answer_state["blocked"] is True
        assert state.phase is RunPhase.UNDETERMINED
        assert result.run_state is None  # el helper no inventa estado en el result
        assert any(note.startswith("strict_block:") for note in state.trace.notes)

    def test_strict_block_no_actua_sin_violaciones_criticas(self) -> None:
        from src.agents.runtime.agent_runtime import _strict_block_run_state

        state = _state()
        state.trace.violations = ["evidence_chain:cited_not_used"]
        result = AgentRunResult(
            run_id=uuid4(),
            agent_id=uuid4(),
            organization_id=None,
            status="completed",
            answer="Sí, cumple.",
        )
        assert _strict_block_run_state(state, result) is False
        assert result.answer == "Sí, cumple."

    def test_flag_estricto_off_por_defecto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.agents.runtime.agent_runtime as runtime_module
        from src.agents.runtime.agent_runtime import _strict_run_state_enabled

        monkeypatch.setattr(
            runtime_module,
            "get_settings",
            lambda: SimpleNamespace(RUNTIME_RUN_STATE_STRICT="on"),
        )
        assert _strict_run_state_enabled() is True
        monkeypatch.setattr(
            runtime_module,
            "get_settings",
            lambda: SimpleNamespace(RUNTIME_RUN_STATE_STRICT="off"),
        )
        assert _strict_run_state_enabled() is False
