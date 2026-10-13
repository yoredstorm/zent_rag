# =============================================================================
# Run metrics — publicación run-level (F7).
# =============================================================================
# Un run cierra y publica UNA vez: runs por fase, latencia, LLM, tokens, costo
# (known vs unknown), tool calls, suficiencia de evidencia y acción de
# finalización. Labels acotados: nunca ids ni la query.
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.run_metrics import publish_run_metrics
from src.runtime.run_state import AgentRunState, RunIdentity, RunPhase


def _state() -> AgentRunState:
    state = AgentRunState(identity=RunIdentity(run_id="run-metrics"))
    state.phase = RunPhase.FINALIZED
    state.trace.latency_ms = 2500.0
    state.decisions.finalization = {
        "action": "FINALIZE",
        "reason_code": "READY",
        "authority": "GENERATION",
    }
    return state


def _result() -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        cost=0.002,
        llm_calls=2,
        tool_calls=1,
        cost_status="known",
    )


class TestPublicacion:
    def test_runs_y_latencia(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_run_latency_seconds,
            zent_runs_total,
        )

        runs = zent_runs_total.labels(path="agent", phase="FINALIZED")
        before = runs._value.get()
        histogram = zent_run_latency_seconds.labels(path="agent")
        before_count = histogram._sum.get()
        publish_run_metrics(_state(), path="agent", result=_result())
        assert runs._value.get() == before + 1
        assert histogram._sum.get() == before_count + 2.5

    def test_llm_tokens_costo_y_tools(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_llm_calls_total,
            zent_llm_tokens_total,
            zent_run_cost_usd_total,
            zent_run_tool_calls_total,
        )

        calls = zent_llm_calls_total.labels(path="rag")
        prompt = zent_llm_tokens_total.labels(path="rag", kind="prompt")
        completion = zent_llm_tokens_total.labels(path="rag", kind="completion")
        cost = zent_run_cost_usd_total.labels(path="rag")
        tools = zent_run_tool_calls_total.labels(path="rag")
        publish_run_metrics(_state(), path="rag", result=_result())
        assert calls._value.get() == 2
        assert prompt._value.get() == 100
        assert completion._value.get() == 40
        assert round(cost._value.get(), 6) == 0.002
        assert tools._value.get() == 1

    def test_costo_desconocido_no_se_disfraza(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_run_cost_unknown_total,
            zent_run_cost_usd_total,
        )

        unknown = zent_run_cost_unknown_total.labels(path="agent")
        before_unknown = unknown._value.get()
        cost = zent_run_cost_usd_total.labels(path="agent")
        before_cost = cost._value.get()
        result = _result()
        result.cost = 0.0
        result.cost_status = "unknown"
        publish_run_metrics(_state(), path="agent", result=result)
        assert unknown._value.get() == before_unknown + 1
        assert cost._value.get() == before_cost

    def test_evidencia_y_accion_de_finalizacion(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_finalization_actions_total,
            zent_run_evidence_total,
        )

        state = _state()
        state.evidence.retrieval_failed = True
        failed = zent_run_evidence_total.labels(path="agent", status="failed")
        before_failed = failed._value.get()
        action = zent_finalization_actions_total.labels(
            action="FINALIZE", reason_code="READY"
        )
        before_action = action._value.get()
        publish_run_metrics(state, path="agent", result=_result())
        assert failed._value.get() == before_failed + 1
        assert action._value.get() == before_action + 1

    def test_evidencia_completa(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_run_evidence_total,
        )

        state = _state()
        state.evidence.observe(
            sufficiency=SimpleNamespace(
                evidence_complete=True,
                recommended_action="generate",
                missing_entities=(),
                missing_anchors=(),
            )
        )
        counter = zent_run_evidence_total.labels(
            path="agent", status="complete"
        )
        before = counter._value.get()
        publish_run_metrics(state, path="agent", result=_result())
        assert counter._value.get() == before + 1

    def test_fail_soft_con_entradas_rotas(self) -> None:
        publish_run_metrics(None, path="agent")  # no lanza
        publish_run_metrics(SimpleNamespace(), path="rag", result=object())
        publish_run_metrics(_state(), path="agent", result=None)


class TestCardinalidad:
    def test_labels_prohibidos_fuera_de_las_metricas_de_run(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_finalization_actions_total,
            zent_llm_calls_total,
            zent_llm_tokens_total,
            zent_run_cost_unknown_total,
            zent_run_cost_usd_total,
            zent_run_evidence_total,
            zent_run_latency_seconds,
            zent_run_tool_calls_total,
            zent_runs_total,
        )

        forbidden = {"run_id", "user_id", "conversation_id", "query"}
        for metric in (
            zent_runs_total,
            zent_run_latency_seconds,
            zent_llm_calls_total,
            zent_llm_tokens_total,
            zent_run_tool_calls_total,
            zent_run_cost_usd_total,
            zent_run_cost_unknown_total,
            zent_run_evidence_total,
            zent_finalization_actions_total,
        ):
            assert not (forbidden & set(metric._labelnames)), metric._name
