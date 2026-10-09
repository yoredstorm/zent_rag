# =============================================================================
# Narrative Fast Path usa el mismo registro que el loop.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunResult
from src.rag.trace_diagnostics import run_invariants
from src.runtime.agent_flow import generation_summary, telemetry_completeness
from src.runtime.run_accounting import (
    PURPOSE_NARRATIVE,
    normalize_finish_reason,
    record_llm_call,
    record_search_call,
)
from src.runtime.run_budget import RunBudgetLedger


def _result() -> AgentRunResult:
    return AgentRunResult(
        run_id=uuid4(),
        agent_id=uuid4(),
        organization_id=None,
        status="running",
        answer="",
    )


class _Response:
    def __init__(self, *, finish_reason: str = "stop", cost: float | None = None) -> None:
        self.prompt_tokens = 1593
        self.completion_tokens = 1200
        self.total_tokens = 2793
        self.finish_reason = finish_reason
        self.model = "zent-default"
        self.content = "respuesta"
        self.cost = cost


def test_finish_reason_normalizes_provider_codes() -> None:
    assert normalize_finish_reason("stop") == "stop"
    assert normalize_finish_reason("length") == "length"
    assert normalize_finish_reason("max_tokens") == "max_tokens"


@pytest.mark.asyncio
async def test_narrative_call_is_generation_not_reasoning() -> None:
    result = _result()
    ledger = RunBudgetLedger.from_config(
        result, {"max_tokens": 8000, "max_steps": 8, "max_cost": 1.0}
    )
    await record_llm_call(
        result,
        ledger,
        _Response(),
        purpose=PURPOSE_NARRATIVE,
        model="zent-default",
        latency_ms=1800,
    )
    record_search_call(
        result,
        query="record 2",
        latency_ms=40,
        evidence_added=5,
        result_count=5,
    )
    assert result.prompt_tokens == 1593
    assert result.completion_tokens == 1200
    assert result.total_tokens == 2793
    assert ledger.consumed_total_tokens == 2793
    assert ledger.llm_calls == 1
    assert result.cost_status == "known"
    assert result.cost > 0
    generation = generation_summary(result, result.steps)
    assert generation["calls"] == 1
    assert generation["answer_calls"] == 1
    assert generation["reasoning_calls"] == 0
    assert generation["ms"] == pytest.approx(1800)
    assert generation["finish_reason"] == "stop"
    assert generation["cost_status"] == "known"
    tools = [step for step in result.steps if step.get("type") == "tool_call"]
    assert tools[0]["tool"] == "search_knowledge"
    found = run_invariants(
        evidence={},
        jev={},
        generation={},
        controls={},
        verification={},
        timeline=[
            {"type": "narrative_fast_path", "llm_calls": 1, "retrieval_rounds": 1},
            *result.steps,
        ],
    )
    codes = {item["code"] for item in found}
    assert "NARRATIVE_LLM_CALL_TRACE_CONSISTENCY" not in codes
    assert "NARRATIVE_TOOL_TRACE_CONSISTENCY" not in codes


@pytest.mark.asyncio
async def test_unknown_cost_is_not_a_silent_zero() -> None:
    result = _result()
    ledger = RunBudgetLedger.from_config(
        result, {"max_tokens": 8000, "max_steps": 4, "max_cost": 1.0}
    )

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("pricing down")

    from src.runtime import run_accounting

    original = run_accounting.resolve_call_cost

    async def _unknown(model, prompt_tokens, completion_tokens, *, provider_cost=None):
        if provider_cost is None:
            return None, "unknown", "pricing down"
        return await original(
            model,
            prompt_tokens,
            completion_tokens,
            provider_cost=provider_cost,
        )

    run_accounting.resolve_call_cost = _unknown
    try:
        await record_llm_call(
            result,
            ledger,
            _Response(),
            purpose=PURPOSE_NARRATIVE,
            model="zent-default",
            latency_ms=10,
        )
    finally:
        run_accounting.resolve_call_cost = original
    generation = generation_summary(result, result.steps)
    assert generation["cost_status"] == "unknown"
    assert "cost" not in generation
    assert result.total_tokens > 0


def test_missing_llm_step_breaks_the_narrative_invariant() -> None:
    found = run_invariants(
        evidence={},
        jev={},
        generation={},
        controls={},
        verification={},
        timeline=[
            {
                "type": "narrative_fast_path",
                "llm_calls": 1,
                "retrieval_rounds": 2,
            }
        ],
    )
    codes = {item["code"] for item in found}
    assert "NARRATIVE_LLM_CALL_TRACE_CONSISTENCY" in codes
    assert "NARRATIVE_TOOL_TRACE_CONSISTENCY" in codes


def test_two_searches_are_two_tools_and_one_generation() -> None:
    result = _result()
    record_search_call(
        result, query="record 2", latency_ms=10, evidence_added=5, result_count=5
    )
    record_search_call(
        result,
        query="record 2 effective date",
        latency_ms=12,
        evidence_added=2,
        result_count=3,
    )
    result.steps.append(
        {
            "type": "llm",
            "purpose": "narrative_generation",
            "latency_ms": 100,
            "action": {},
        }
    )
    result.steps.append(
        {
            "type": "narrative_fast_path",
            "llm_calls": 1,
            "retrieval_rounds": 2,
        }
    )
    generation = generation_summary(result, result.steps)
    assert generation["calls"] == 1
    assert generation["answer_calls"] == 1
    assert generation["reasoning_calls"] == 0
    tools = [step for step in result.steps if step.get("tool") == "search_knowledge"]
    assert len(tools) == 2
    telemetry = telemetry_completeness(
        steps=result.steps,
        jev={},
        generation=generation,
        verification={},
        sources=[],
        timings={"span_stages": {"retrieval": 22}},
        cost=0,
        decision={},
        agent_tools=("search_knowledge",),
    )
    assert telemetry["tools"] == "observed"


def test_deterministic_path_does_not_look_like_narrative() -> None:
    found = run_invariants(
        evidence={},
        jev={},
        generation={},
        controls={},
        verification={"narrative_verification": {"status": "VERIFIED_DETERMINISTIC"}},
        timeline=[{"type": "deterministic_verifier", "verified": True}],
    )
    codes = {item["code"] for item in found}
    assert "NARRATIVE_LLM_CALL_TRACE_CONSISTENCY" not in codes
    assert "NARRATIVE_TOOL_TRACE_CONSISTENCY" not in codes
    assert "NARRATIVE_FAST_PATH_VERIFICATION_MISSING" not in codes
