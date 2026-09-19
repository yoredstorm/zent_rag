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


@pytest.mark.asyncio
async def test_tool_routing_passthrough_without_engine() -> None:
    tools = [type("T", (), {"name": "search_knowledge", "description": "kb"})()]
    selected, meta = await select_relevant_tools(
        tools, engine=None, user_request="hola", history=[]
    )
    assert selected == tools
    assert meta["mode"] == "passthrough"


@pytest.mark.asyncio
async def test_termination_gate_requires_tool_calls() -> None:
    class Engine:
        async def judge(self, **kwargs):
            raise AssertionError("should not judge")

    out = await original_request_satisfied(
        engine=Engine(), user_request="hola", history=[], tool_calls=0
    )
    assert out["stop"] is False


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
