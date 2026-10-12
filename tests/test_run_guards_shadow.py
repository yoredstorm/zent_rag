# =============================================================================
# Run Guards — shadow tabla↔loop y flag de enforcement (F3).
# =============================================================================
# La tabla (`src/runtime/run_guards.py`) es la fuente declarada; el runtime la
# consulta y registra divergencias. Con `RUNTIME_RUN_GUARDS_ENFORCE=on` el
# veredicto manda en ejecución.
from __future__ import annotations

from types import SimpleNamespace

from src.agents.runtime.agent_runtime import (
    emit_guard_divergence,
    guard_verdict_for,
    guards_enforced,
    observe_guard_transition,
)
from src.runtime.run_state import AgentRunState, RunIdentity, RunPhase


def _state(phase: RunPhase = RunPhase.REASONING) -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id="run-guard"))
    state.phase = phase
    return state


class TestGuardVerdict:
    def test_sin_estado_no_hay_veredicto(self) -> None:
        assert guard_verdict_for(None, "REQUEST_TOOL", tool_authorized=True) is None

    def test_tool_autorizada(self) -> None:
        verdict = guard_verdict_for(
            _state(), "REQUEST_TOOL", tool_authorized=True
        )
        assert verdict is not None
        assert verdict.allowed is True
        assert verdict.reason_code == "TOOL_AUTHORIZED"
        assert verdict.to_phase is RunPhase.ACTING

    def test_tool_sin_autorizacion_no_avanza(self) -> None:
        verdict = guard_verdict_for(
            _state(), "REQUEST_TOOL", tool_authorized=False
        )
        assert verdict.allowed is False
        assert verdict.reason_code == "TOOL_NOT_AUTHORIZED"
        assert verdict.to_phase is RunPhase.REASONING

    def test_budget_agotado_no_gasta(self) -> None:
        verdict = guard_verdict_for(
            _state(), "REQUEST_RETRIEVAL", budget_exhausted=True
        )
        assert verdict.allowed is False
        assert verdict.reason_code == "BUDGET_EXHAUSTED"
        assert verdict.to_phase is RunPhase.READY_TO_FINALIZE

    def test_ejecutable_sin_autoridad_es_undetermined(self) -> None:
        verdict = guard_verdict_for(
            _state(RunPhase.READY_TO_FINALIZE),
            "REQUEST_FINALIZE",
            requires_deterministic=True,
            authority_present=False,
        )
        assert verdict.allowed is True
        assert verdict.to_phase is RunPhase.UNDETERMINED
        assert verdict.reason_code == "AUTHORITY_MISSING_FOR_EXECUTABLE"

    def test_fase_terminal_no_transiciona(self) -> None:
        verdict = guard_verdict_for(
            _state(RunPhase.FINALIZED), "REQUEST_TOOL", tool_authorized=True
        )
        assert verdict.allowed is False
        assert verdict.reason_code == "TERMINAL_NO_TRANSITIONS"


class TestShadowDivergence:
    def test_acompanado_no_emite_metrica(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_guard_divergence_total,
        )

        counter = zent_guard_divergence_total.labels(
            event="REQUEST_TOOL",
            guard_reason="TOOL_NOT_AUTHORIZED",
            legacy_reason="TOOL_NOT_AUTHORIZED",
        )
        before = counter._value.get()
        diverged = observe_guard_transition(
            _state(),
            "REQUEST_TOOL",
            legacy_reason="TOOL_NOT_AUTHORIZED",
            tool_authorized=False,
        )
        assert diverged is False
        assert counter._value.get() == before

    def test_deriva_emite_metrica_y_devuelve_true(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_guard_divergence_total,
        )

        # La ruta vigente registra TOOL_NOT_AUTHORIZED pero el guard dice que la
        # tool SÍ está autorizada: deriva real entre tabla y loop.
        counter = zent_guard_divergence_total.labels(
            event="REQUEST_TOOL",
            guard_reason="TOOL_AUTHORIZED",
            legacy_reason="TOOL_NOT_AUTHORIZED",
        )
        before = counter._value.get()
        diverged = observe_guard_transition(
            _state(),
            "REQUEST_TOOL",
            legacy_reason="TOOL_NOT_AUTHORIZED",
            tool_authorized=True,
        )
        assert diverged is True
        assert counter._value.get() == before + 1

    def test_emision_directa_de_divergencia(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_guard_divergence_total,
        )

        counter = zent_guard_divergence_total.labels(
            event="REQUEST_TOOL",
            guard_reason="BUDGET_EXHAUSTED",
            legacy_reason="TOOL_AUTHORIZED",
        )
        before = counter._value.get()
        emit_guard_divergence(
            _state(),
            "REQUEST_TOOL",
            guard_reason="BUDGET_EXHAUSTED",
            legacy_reason="TOOL_AUTHORIZED",
        )
        assert counter._value.get() == before + 1


class TestFlagDeEnforcement:
    def test_default_apagado(self) -> None:
        assert guards_enforced(SimpleNamespace()) is False
        assert (
            guards_enforced(SimpleNamespace(RUNTIME_RUN_GUARDS_ENFORCE="off"))
            is False
        )

    def test_encendido(self) -> None:
        for raw in ("on", "ON", "1", "true", "yes"):
            assert (
                guards_enforced(SimpleNamespace(RUNTIME_RUN_GUARDS_ENFORCE=raw))
                is True
            )
