# =============================================================================
# Zent AI Runtime — unit tests (no live JEV, no Postgres).
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.decision import RoutingDecision
from src.core.domain.runtime import ExecutionState
from src.decision.capabilities import InMemoryCapabilityRegistry
from src.runtime.ai_decision import apply_low_confidence, interpret, parse_config, questions_for
from src.runtime.efficiency import DEFAULT_WEIGHTS, composite_score, from_dashboard, normalize_weights
from src.runtime.engine import ZentRuntime
from src.runtime.executor import CapabilityExecutor
from src.runtime.experiments import summarize
from src.runtime.termination import original_request_satisfied
from src.runtime.tool_routing import select_relevant_tools


def test_execution_state_is_not_a_prompt_dump() -> None:
    state = ExecutionState(
        request="secret token=abc " * 200,
        evidence=[{"content": "x" * 5000, "source_type": "doc", "score": 0.9}],
        budget={"remaining": 12.5, "api_key": "sk-secret"},
    )
    slim = state.sanitized_for_model()
    blob = str(slim)
    assert "sk-secret" not in blob
    assert "api_key" not in blob
    assert len(blob) < 8000
    assert slim["budget_remaining"] == 12.5


def test_capability_registry_has_handlers_and_delegate() -> None:
    registry = InMemoryCapabilityRegistry()
    spec = registry.get("agent.delegate")
    assert spec is not None
    assert spec.handler == "agent_runtime"
    assert registry.get("workflow.start") is not None
    assert registry.get("knowledge.answer").handler == "rag_orchestrator"


def test_executor_names_existing_handlers() -> None:
    ex = CapabilityExecutor()
    assert ex.handler_name("knowledge.answer") == "rag_orchestrator"
    assert ex.handler_name("agent.delegate") == "agent_runtime"
    assert ex.handler_name("api.request") == "tool_registry"


@pytest.mark.asyncio
async def test_runtime_decide_delegates(monkeypatch) -> None:
    async def fake_budget(_oid):
        return {"remaining": 9.0, "remaining_ok": True, "prefer_cheap": False, "on_limit": "block"}

    monkeypatch.setattr("src.runtime.engine.snapshot_budget", fake_budget)

    class FakeEngine:
        async def decide(self, context):
            assert context.budget["remaining"] == 9.0
            return RoutingDecision(
                capability="knowledge.answer",
                resolved=True,
                confidence=0.91,
                provider="rules",
            )

    runtime = ZentRuntime(engine=FakeEngine())
    org = uuid4()
    state = runtime.new_state(request="¿Cuál es la política?", organization_id=org)
    assert state.current_step == "understand"
    decision = await runtime.decide(state, permissions=frozenset({"*"}))
    assert decision.capability == "knowledge.answer"
    assert state.selected_capability == "knowledge.answer"
    assert state.decisions[-1]["handler"] == "rag_orchestrator"
    runtime.finish(state)
    assert state.steps[-1].name == "finish"


def test_ai_decision_route_and_low_confidence_human() -> None:
    cfg = parse_config(
        {
            "decision_kind": "route",
            "question": "Determinar si el cliente requiere revisión manual",
            "options": [
                {"id": "approve", "label": "Aprobar"},
                {"id": "reject", "label": "Rechazar"},
                {"id": "review", "label": "Revisar"},
            ],
            "confidence_min": 0.8,
            "on_low_confidence": "human_review",
        }
    )
    qs = questions_for(cfg)
    assert qs["route"]["type"] == "choice"
    payload = {
        "answers": {
            "route": {"choice": "review", "confidence": 0.4, "probabilities": {"approve": 0.3}},
        }
    }
    outcome = interpret(cfg, payload)
    assert outcome.choice == "review"
    assert outcome.low_confidence is True
    outcome = apply_low_confidence(outcome, cfg)
    assert outcome.on_low_confidence == "human_review"
    assert "Choice" not in cfg.question


def test_ai_decision_yes_no_and_score() -> None:
    yes = parse_config({"decision_kind": "yes_no", "question": "El stock es crítico"})
    yes_out = interpret(yes, {"answers": {"yes": {"noul": 0.9}}})
    assert yes_out.result is True
    assert yes_out.route == "then"
    score = parse_config({"decision_kind": "score", "score_threshold": 0.5})
    score_out = interpret(score, {"answers": {"score": {"score": 0.2, "confidence": 0.9}}})
    assert score_out.result is False
    assert score_out.route == "else"


# ---------------------------------------------------------------------------
# P0.1 — Choice confidence y Noul "route warranted" son métricas separadas
# ---------------------------------------------------------------------------


def _route_config(confidence_min: float = 0.65):
    return parse_config(
        {
            "decision_kind": "route",
            "question": "Elegir la ruta",
            "options": [{"id": "approve"}, {"id": "reject"}],
            "confidence_min": confidence_min,
            "on_low_confidence": "fallback",
        }
    )


def _route_payload(choice_conf: float, warranted_noul: float | None) -> dict:
    answers: dict = {
        "route": {"choice": "approve", "confidence": choice_conf, "probabilities": {}},
    }
    if warranted_noul is not None:
        answers["confidence_ok"] = {"type": "noul", "noul": warranted_noul}
    return {"answers": answers}


def test_ai_decision_route_confidence_ok_alta() -> None:
    """Caso A: Choice 0.90 + warranted 0.95 → alta confianza."""
    outcome = interpret(_route_config(), _route_payload(0.90, 0.95))
    assert outcome.confidence == 0.90
    assert outcome.choice_confidence == 0.90
    assert outcome.warranted is True
    assert outcome.warranted_certainty == pytest.approx(0.90)
    assert outcome.low_confidence is False


def test_ai_decision_route_confidence_ok_negativo_no_infla() -> None:
    """Caso B: Choice 0.90 + warranted 0.05 → low confidence, nunca 0.90."""
    outcome = interpret(_route_config(), _route_payload(0.90, 0.05))
    assert outcome.warranted is False
    assert outcome.confidence <= 0.05
    assert outcome.low_confidence is True
    assert outcome.warranted_certainty == pytest.approx(0.90)


def test_ai_decision_route_choice_bajo_sigue_low_aunque_warranted() -> None:
    """Caso C: Choice 0.58 no alcanza el threshold aunque el Noul sea 0.95."""
    outcome = interpret(_route_config(), _route_payload(0.58, 0.95))
    assert outcome.warranted is True
    assert outcome.confidence == 0.58
    assert outcome.low_confidence is True


def test_ai_decision_route_confidence_ok_incierto() -> None:
    """Caso D: warranted ~0.50 → uncertain activa la política de low confidence."""
    outcome = interpret(_route_config(), _route_payload(0.90, 0.50))
    assert outcome.warranted is None
    assert outcome.confidence == 0.90
    assert outcome.low_confidence is True


def test_ai_decision_route_sin_confidence_ok_backward_compatible() -> None:
    """Caso E: sin confidence_ok manda solo el Choice."""
    high = interpret(_route_config(), _route_payload(0.90, None))
    assert high.warranted is None
    assert high.warranted_certainty is None
    assert high.confidence == 0.90
    assert high.low_confidence is False
    low = interpret(_route_config(), _route_payload(0.40, None))
    assert low.confidence == 0.40
    assert low.low_confidence is True


def test_ai_decision_route_noul_cero_es_negativo() -> None:
    """Noul 0.0 válido no se confunde con missing ni con incertidumbre."""
    outcome = interpret(_route_config(), _route_payload(0.90, 0.0))
    assert outcome.warranted is False
    assert outcome.confidence == 0.0
    assert outcome.low_confidence is True


def test_ai_decision_low_confidence_preserva_semantica_de_ruta() -> None:
    outcome = interpret(_route_config(), _route_payload(0.90, 0.05))
    applied = apply_low_confidence(outcome, _route_config())
    assert applied.warranted is False
    assert applied.choice_confidence == 0.90
    assert applied.warranted_certainty == pytest.approx(0.90)
    assert applied.low_confidence is True


def test_ai_decision_output_expone_semantica_separada() -> None:
    from src.runtime.ai_decision import to_output

    payload = to_output(interpret(_route_config(), _route_payload(0.90, 0.05)))
    assert payload["confidence"] == 0.05
    assert payload["choice_confidence"] == 0.90
    assert payload["warranted"] is False
    assert payload["warranted_certainty"] == pytest.approx(0.90)


@pytest.mark.asyncio
async def test_tool_routing_passthrough_without_engine() -> None:
    tools = [type("T", (), {"name": "search_knowledge", "description": "kb"})()]
    selected, meta = await select_relevant_tools(
        tools, engine=None, user_request="hola", history=[]
    )
    assert selected == tools
    assert meta["mode"] == "passthrough"
    assert meta["skip_reason"] == "no_engine"


@pytest.mark.asyncio
async def test_tool_routing_passthrough_con_pocas_herramientas() -> None:
    engine = _FakeJudge(_needs(0.9))
    tools = [_Tool("search_knowledge"), _Tool("query_database")]
    selected, meta = await select_relevant_tools(
        tools, engine=engine, user_request="hola", history=[]
    )
    assert selected == tools
    assert meta["mode"] == "passthrough"
    assert meta["skip_reason"] == "too_few_tools"
    assert meta["tools_count"] == 2
    assert engine.calls == 0


@pytest.mark.asyncio
async def test_tool_routing_min_tools_1_consulta_con_una_herramienta() -> None:
    engine = _FakeJudge(
        {
            **_needs(0.9),
            "tool": {
                "type": "choice",
                "choice": "search_knowledge",
                "confidence": 0.9,
                "probabilities": {"search_knowledge": 0.9},
            },
        }
    )
    tools = [_Tool("search_knowledge")]
    selected, meta = await select_relevant_tools(
        tools, engine=engine, user_request="hola", history=[], min_tools=1
    )
    assert engine.calls == 1
    assert meta["mode"] == "jev"
    assert meta["certain"] is True
    assert selected == tools


@pytest.mark.asyncio
async def test_termination_gate_requires_tool_calls() -> None:
    class Engine:
        async def judge(self, **kwargs):
            raise AssertionError("should not judge")

    out = await original_request_satisfied(
        engine=Engine(), user_request="hola", history=[], tool_calls=0
    )
    assert out["stop"] is False


def test_agent_runtime_flags_can_be_overridden_per_agent() -> None:
    """config.runtime del agente manda sobre el flag del tenant."""
    from types import SimpleNamespace

    from src.runtime.termination import gate_enabled
    from src.runtime.tool_routing import routing_enabled

    settings = SimpleNamespace(RUNTIME_TOOL_ROUTING_MODE="off", RUNTIME_TERMINATION_GATE="off")
    assert routing_enabled(settings, {}) is False
    assert routing_enabled(settings, {"runtime": {"tool_routing": True}}) is True
    assert routing_enabled(settings, {"runtime": {"tool_routing": False}}) is False
    assert gate_enabled(settings, {}) is False
    assert gate_enabled(settings, {"runtime": {"termination_gate": True}}) is True
    assert gate_enabled(settings, {"runtime": {"termination_gate": False}}) is False

    on = SimpleNamespace(RUNTIME_TOOL_ROUTING_MODE="experimental", RUNTIME_TERMINATION_GATE="on")
    assert routing_enabled(on, {"runtime": {"tool_routing": False}}) is False
    assert gate_enabled(on, {"runtime": {"termination_gate": False}}) is False


def test_efficiency_score_uses_visible_components() -> None:
    weights = normalize_weights({"quality": 1, "cost": 1, "latency": 1, "fallback": 1})
    assert abs(sum(weights.values()) - 1.0) < 0.02
    components, score, documented = from_dashboard(
        average_confidence=0.8,
        fallback_rate=0.1,
        average_latency_ms=200,
        cost_index=1.0,
    )
    assert documented == DEFAULT_WEIGHTS
    assert 0 <= score <= 1
    assert composite_score(components, weights) >= 0


def test_experiment_summary_routing_accuracy() -> None:
    report = {
        "results": [
            {
                "jev": {
                    "match": True,
                    "confidence": 0.9,
                    "latency_ms": 10,
                    "tokens": 2,
                    "cost": 0.01,
                    "fallback": False,
                }
            },
            {
                "jev": {
                    "match": False,
                    "confidence": 0.4,
                    "latency_ms": 20,
                    "tokens": 2,
                    "cost": 0.02,
                    "fallback": True,
                }
            },
        ]
    }
    summary = summarize(report)
    assert summary["jev"]["routing_accuracy"] == 0.5
    assert summary["jev"]["fallback_rate"] == 0.5


# ---------------------------------------------------------------------------
# JEV: estado con presupuesto, fusion de herramienta y verificador
# ---------------------------------------------------------------------------


class _FakeJudge:
    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.last_state: dict | None = None
        self.last_questions: dict | None = None
        self.calls = 0

    async def judge(self, *, state, questions):
        self.calls += 1
        self.last_state = state
        self.last_questions = questions
        return {"model": "jev-latest", "answers": self.answers}


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"tool {name}"


def _needs(noul: float) -> dict:
    return {"needs_tool": {"type": "noul", "noul": noul}}


def test_build_jev_state_respeta_presupuesto_por_prioridad() -> None:
    from src.runtime.jev_state import StateSection, build_jev_state

    built = build_jev_state(
        [
            StateSection("critical", 1, "A" * 2000),
            StateSection("secondary", 2, "B" * 5000),
            StateSection("last", 3, "C" * 5000),
        ],
        max_chars=4000,
    )
    assert built.state["critical"] == "A" * 2000
    assert len(built.state["secondary"]) == 2000
    assert "last" not in built.state
    assert "secondary" in built.truncated and "last" in built.truncated


@pytest.mark.asyncio
async def test_tool_routing_fusion_elige_con_certeza() -> None:
    from src.runtime.tool_routing import select_relevant_tools

    engine = _FakeJudge(
        {
            **_needs(0.9),
            "tool": {
                "type": "choice",
                "choice": "query_database",
                "confidence": 0.6,
                "probabilities": {"query_database": 0.6, "search_knowledge": 0.3},
            },
        }
    )
    tools = [_Tool("search_knowledge"), _Tool("query_database"), _Tool("call_api")]
    selected, meta = await select_relevant_tools(
        tools,
        engine=engine,
        user_request="cuantas ventas hubo",
        history=["USER QUESTION: cuantas ventas hubo"],
    )
    assert meta["mode"] == "jev"
    assert meta["certain"] is True
    assert meta["score"] >= 0.6
    assert selected[0].name == "query_database"
    assert engine.last_questions is not None
    assert "needs_more_evidence" in engine.last_questions
    assert engine.last_state is not None and "agent_instructions" not in engine.last_state


@pytest.mark.asyncio
async def test_tool_routing_sin_certeza_no_impone_nada() -> None:
    from src.runtime.tool_routing import select_relevant_tools

    engine = _FakeJudge(
        {
            **_needs(0.5),
            "tool": {
                "type": "choice",
                "choice": "search_knowledge",
                "confidence": 0.2,
                "probabilities": {},
            },
        }
    )
    tools = [_Tool("search_knowledge"), _Tool("query_database"), _Tool("call_api")]
    selected, meta = await select_relevant_tools(
        tools, engine=engine, user_request="hola", history=[]
    )
    assert meta["certain"] is False
    assert [t.name for t in selected] == [t.name for t in tools]


@pytest.mark.asyncio
async def test_tool_routing_confia_en_no_usar_herramientas() -> None:
    from src.runtime.tool_routing import select_relevant_tools

    engine = _FakeJudge(
        {
            **_needs(0.05),
            "tool": {
                "type": "choice",
                "choice": "none",
                "confidence": 0.9,
                "probabilities": {"none": 0.9},
            },
        }
    )
    tools = [_Tool("search_knowledge"), _Tool("query_database"), _Tool("call_api")]
    selected, meta = await select_relevant_tools(
        tools, engine=engine, user_request="hola", history=[]
    )
    assert meta["mode"] == "jev_no_tools"
    assert selected == []


def test_answer_gate_mode_respeta_override_del_agente() -> None:
    from types import SimpleNamespace

    from src.runtime.answer_gate import answer_gate_mode

    off = SimpleNamespace(RUNTIME_ANSWER_GATE="off")
    on = SimpleNamespace(RUNTIME_ANSWER_GATE="on")
    assert answer_gate_mode(off, {"runtime": {"answer_gate": True}}) == "on"
    assert answer_gate_mode(on, {"runtime": {"answer_gate": False}}) == "off"
    assert answer_gate_mode(on, {}) == "on"
    assert answer_gate_mode(off, {}) == "off"


def _gate_answers(grounded: float, complete: float, quality: float) -> dict:
    return {
        "answer_grounded": {"type": "noul", "noul": grounded},
        "answer_complete": {"type": "noul", "noul": complete},
        "answer_quality": {"type": "score", "score": quality},
    }


@pytest.mark.asyncio
async def test_answer_gate_aprueba_respuesta_respaldada() -> None:
    from src.runtime.answer_gate import judge_answer

    engine = _FakeJudge(_gate_answers(0.95, 0.9, 3))
    out = await judge_answer(
        engine=engine,
        mode="on",
        user_request="quien es el gerente",
        draft="El gerente es X (fuente: doc.pdf)",
        observations=["OBSERVATION: doc.pdf dice que el gerente es X"],
        settings=object(),
    )
    assert out.verdict == "approve"
    assert out.grounded is True and out.complete is True
    assert out.score >= 0.66
    assert out.latency_ms >= 0
    step = out.to_step()
    assert step["type"] == "answer_gate" and step["verdict"] == "approve"


@pytest.mark.asyncio
async def test_answer_gate_pide_revision_o_se_abstiene() -> None:
    from src.runtime.answer_gate import judge_answer

    revise = await judge_answer(
        engine=_FakeJudge(_gate_answers(0.8, 0.2, 2)),
        mode="on",
        user_request="quien es el gerente",
        draft="El gerente es X",
        observations=[],
        settings=object(),
    )
    assert revise.verdict == "revise"
    assert "Verificador JEV" in revise.feedback

    abstain = await judge_answer(
        engine=_FakeJudge(_gate_answers(0.5, 0.5, 0)),
        mode="on",
        user_request="quien es el gerente",
        draft="Puede ser cualquiera",
        observations=[],
        settings=object(),
    )
    assert abstain.verdict == "abstain"


@pytest.mark.asyncio
async def test_answer_gate_apagado_o_sin_jev_no_cambia_nada() -> None:
    from src.runtime.answer_gate import judge_answer

    off = await judge_answer(
        engine=_FakeJudge(_gate_answers(0.0, 0.0, 0)),
        mode="off",
        user_request="x",
        draft="y",
        observations=[],
        settings=object(),
    )
    assert off.verdict == "skipped"

    no_engine = await judge_answer(
        engine=None,
        mode="on",
        user_request="x",
        draft="y",
        observations=[],
        settings=object(),
    )
    assert no_engine.verdict == "skipped"


def test_agent_steps_to_flow_mapea_verificador() -> None:
    from src.runtime.agent_flow import steps_to_flow

    mapped = steps_to_flow(
        [
            {
                "type": "tool_routing",
                "choice": "search_knowledge",
                "confidence": 0.45,
                "score": 0.55,
                "certain": False,
                "latency_ms": 790,
            },
            {
                "type": "answer_gate",
                "verdict": "approve",
                "score": 0.9,
                "grounded": True,
                "complete": True,
                "quality": 3,
                "latency_ms": 850,
            },
            {"type": "final"},
        ]
    )
    assert mapped["steps"][0]["name"] == "JEV elige herramienta"
    assert "sin certeza" in mapped["steps"][0]["detail"]
    assert mapped["steps"][0]["ms"] == 790
    assert mapped["steps"][1]["name"] == "JEV verifica respuesta"
    assert "aprobada" in mapped["steps"][1]["detail"]
    assert "calidad 3/3" in mapped["steps"][1]["detail"]
    # El resumen JEV declara llamadas y fases reales además del veredicto.
    assert mapped["jev"] == {
        "used": True,
        "calls": 2,
        "phases": ["tool_routing", "answer_gate"],
        "score": 0.9,
        "verdict": "approve",
        "grounded": True,
        "complete": True,
        "quality": 3.0,
    }


def test_agent_steps_to_flow_passthrough_no_finge_jev() -> None:
    from src.runtime.agent_flow import steps_to_flow

    mapped = steps_to_flow(
        [
            {
                "type": "tool_routing",
                "mode": "passthrough",
                "skip_reason": "too_few_tools",
                "tools_count": 1,
                "choice": None,
                "confidence": 0.0,
                "score": 0.0,
                "certain": False,
                "latency_ms": 0.2,
            },
            {
                "type": "tool_routing",
                "mode": "passthrough",
                "skip_reason": "no_engine",
                "latency_ms": 0.0,
            },
            {"type": "final"},
        ]
    )
    first, second = mapped["steps"][0], mapped["steps"][1]
    assert first["name"] == "JEV elige herramienta"
    assert "JEV no consultado" in first["detail"]
    assert "1 herramienta activa" in first["detail"]
    assert "sin certeza" not in first["detail"]
    assert second["detail"] == "JEV no configurado"
    assert mapped["jev"]["used"] is False


def test_agent_steps_to_flow_gate_skip_no_finge_jev() -> None:
    from src.runtime.agent_flow import steps_to_flow

    only_skip = steps_to_flow(
        [
            {
                "type": "answer_gate",
                "verdict": "skipped",
                "provider": "skip",
                "mode": "on",
            },
            {"type": "final"},
        ]
    )
    assert only_skip["jev"]["used"] is False

    judged = steps_to_flow(
        [
            {
                "type": "termination_gate",
                "stop": True,
                "provider": "jev",
                "latency_ms": 80,
            },
            {"type": "final"},
        ]
    )
    assert judged["jev"]["used"] is True


def test_agent_steps_to_flow_marca_tools_omitidas() -> None:
    from src.runtime.agent_flow import steps_to_flow

    mapped = steps_to_flow(
        [
            {
                "type": "tool_filter",
                "omitted": [
                    {"tool": "query_database", "reason": "no_data_sources"},
                    {"tool": "call_api", "reason": "no_api_allowlist"},
                ],
            },
            {"type": "final"},
        ]
    )
    step = mapped["steps"][0]
    assert step["name"] == "Herramientas omitidas"
    assert step["status"] == "warn"
    assert "query_database (el agente no tiene fuentes de datos)" in step["detail"]
    assert "call_api (no hay APIs permitidas configuradas)" in step["detail"]
