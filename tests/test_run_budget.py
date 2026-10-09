# =============================================================================
# Presupuesto jerárquico del run: el max_tokens del agente manda.
# La llamada pide un target derivado, nunca un techo paralelo de 800.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunResult
from src.runtime.narrative_fast_path import narrative_route
from src.runtime.run_budget import (
    CRITICAL,
    EXHAUSTED,
    NORMAL,
    RunBudgetLedger,
    concept_count_for_budget,
    desired_output_token_budget,
    plan_response_budget,
    retrieval_rounds_allowed,
)

MULTI = "cuentame sobre el record 2 y el cambio de fechas de efectividad"
SINGLE = "qué es record 2"


def _result(**overrides) -> AgentRunResult:
    payload = {
        "run_id": uuid4(),
        "agent_id": uuid4(),
        "organization_id": None,
        "status": "running",
        "answer": "",
    }
    payload.update(overrides)
    return AgentRunResult(**payload)


def _ledger(
    result: AgentRunResult | None = None,
    *,
    max_tokens: int = 8000,
    max_cost_usd: float = 1.0,
    max_steps: int = 8,
) -> RunBudgetLedger:
    return RunBudgetLedger.from_config(
        result or _result(),
        {
            "max_tokens": max_tokens,
            "max_cost": max_cost_usd,
            "max_steps": max_steps,
        },
    )


def _plan(ledger: RunBudgetLedger, **overrides):
    params = {
        "estimated_prompt_tokens": 1600,
        "blueprint": "technical_explanation",
        "question": MULTI,
        "model_output_limit": 4096,
        "followup_llm": False,
    }
    params.update(overrides)
    return plan_response_budget(ledger, **params)


def test_ledger_reads_agent_run_result_metrics() -> None:
    result = _result(prompt_tokens=100, completion_tokens=40, total_tokens=140, cost=0.02)
    ledger = _ledger(result, max_tokens=8000, max_cost_usd=1.0, max_steps=5)
    assert ledger.consumed_prompt_tokens == 100
    assert ledger.consumed_completion_tokens == 40
    assert ledger.consumed_total_tokens == 140
    assert ledger.consumed_cost_usd == pytest.approx(0.02)
    assert ledger.remaining_tokens == 7860
    assert ledger.remaining_cost_usd == pytest.approx(0.98)
    assert ledger.remaining_steps == 5
    ledger.charge_tool_step()
    ledger.account_llm_usage(
        prompt_tokens=10, completion_tokens=5, total_tokens=15, cost_usd=0.01
    )
    assert result.total_tokens == 155
    assert result.cost == pytest.approx(0.03)
    assert result.tool_calls == 1
    assert result.llm_calls == 1
    assert result.logical_steps == 2
    assert ledger.remaining_steps == 3


def test_multi_concept_technical_cap_exceeds_legacy_800() -> None:
    route = narrative_route(MULTI)
    assert route.blueprint == "technical_explanation"
    assert concept_count_for_budget(MULTI) >= 2
    assert concept_count_for_budget(SINGLE) < concept_count_for_budget(MULTI)
    single = desired_output_token_budget(
        "definition_explanation",
        concept_count=concept_count_for_budget(SINGLE),
    )
    multi = desired_output_token_budget(
        "technical_explanation",
        concept_count=concept_count_for_budget(MULTI),
    )
    assert multi == 1800
    assert multi > single
    assert multi > 800
    concise = desired_output_token_budget(
        "technical_explanation",
        concept_count=2,
        personality="muy conciso",
    )
    assert 800 < concise < multi
    plan = _plan(_ledger(max_tokens=8000))
    assert plan.desired_completion_tokens == 1800
    assert plan.allowed_completion_tokens == 1800
    assert plan.allowed_completion_tokens > 800
    assert plan.budget_pressure == NORMAL
    assert plan.agent_max_tokens == 8000
    assert plan.tokens_consumed_before_call == 0
    assert plan.estimated_prompt_tokens == 1600


def test_tight_run_budget_caps_completion_to_remaining() -> None:
    plan = _plan(
        _ledger(max_tokens=2000),
        estimated_prompt_tokens=1500,
        safety_reserve_tokens=200,
        followup_llm=True,
    )
    room = 2000 - 1500 - 200
    assert plan.allowed_completion_tokens <= room
    assert plan.allowed_completion_tokens < plan.desired_completion_tokens
    assert plan.budget_pressure in {CRITICAL, "CONSTRAINED"}
    assert "compacta" in plan.compact_instruction
    assert "No abras una sección" in plan.compact_instruction


def test_tiny_budget_exhausts_or_compacts() -> None:
    exhausted = _plan(
        _ledger(max_tokens=500),
        estimated_prompt_tokens=450,
        followup_llm=False,
    )
    assert exhausted.allowed_completion_tokens == 0
    assert exhausted.budget_pressure == EXHAUSTED
    assert exhausted.budget_reason == "budget_exhausted_tokens"

    compact = _plan(
        _ledger(max_tokens=500),
        estimated_prompt_tokens=100,
        followup_llm=False,
    )
    assert compact.allowed_completion_tokens <= 400
    assert compact.allowed_completion_tokens > 0
    assert compact.budget_pressure == CRITICAL
    assert compact.compact_instruction


def test_low_max_cost_reduces_or_exhausts_call() -> None:
    reduced = _plan(
        _ledger(max_tokens=8000, max_cost_usd=0.001),
        input_cost_per_1k=0.00015,
        output_cost_per_1k=0.00060,
    )
    assert reduced.allowed_completion_tokens < reduced.desired_completion_tokens
    assert reduced.allowed_completion_tokens > 0
    assert reduced.budget_reason == "cost_reduced_completion"
    assert reduced.estimated_prompt_cost > 0
    assert reduced.estimated_max_completion_cost <= 0.001

    exhausted = _plan(
        _ledger(max_tokens=8000, max_cost_usd=0.00001),
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.03,
    )
    assert exhausted.allowed_completion_tokens == 0
    assert exhausted.budget_pressure == EXHAUSTED
    assert exhausted.budget_reason == "budget_exhausted_cost"


def test_deterministic_fast_path_does_not_consume_decision_tokens() -> None:
    result = _result()
    ledger = _ledger(result)
    plan = plan_response_budget(
        ledger,
        estimated_prompt_tokens=0,
        question="&&&F vs ABCFGEGE cumple?",
        decision_llm=False,
        model_output_limit=4096,
    )
    assert plan.allowed_completion_tokens == 0
    assert plan.desired_completion_tokens == 0
    assert plan.budget_reason == "deterministic_no_decision_llm"
    assert ledger.consumed_total_tokens == 0
    assert ledger.llm_calls == 0
    assert result.total_tokens == 0


def test_personality_polish_uses_the_same_ledger() -> None:
    result = _result(total_tokens=7600, prompt_tokens=7000, completion_tokens=600, cost=0.2)
    ledger = _ledger(result, max_tokens=8000, max_cost_usd=1.0)
    plan = plan_response_budget(
        ledger,
        estimated_prompt_tokens=250,
        desired_completion_tokens=400,
        model_output_limit=1200,
        followup_llm=False,
        personality="explica con detalle",
        blueprint="direct_fact",
    )
    room = 8000 - 7600 - 250
    assert plan.allowed_completion_tokens <= room
    assert plan.allowed_completion_tokens <= 400
    assert plan.tokens_consumed_before_call == 7600
    capped = plan_response_budget(
        _ledger(max_tokens=100_000),
        estimated_prompt_tokens=100,
        question=MULTI,
        blueprint="technical_explanation",
        personality="explica con detalle y a fondo",
        model_output_limit=500,
        followup_llm=False,
    )
    assert capped.allowed_completion_tokens <= 500
    assert capped.desired_completion_tokens > 800


def test_table_signal_raises_desired_without_passing_the_run() -> None:
    plain = desired_output_token_budget(
        "technical_explanation", concept_count=1
    )
    table = desired_output_token_budget(
        "technical_explanation",
        concept_count=1,
        needs_table=True,
        needs_list=True,
        needs_example=True,
    )
    assert table > plain
    plan = _plan(
        _ledger(max_tokens=8000),
        needs_table=True,
        estimated_prompt_tokens=7000,
        followup_llm=False,
    )
    assert plan.allowed_completion_tokens <= 8000 - 7000
    assert plan.allowed_completion_tokens <= plan.desired_completion_tokens


def test_future_retrieval_round_stops_when_steps_are_gone() -> None:
    assert retrieval_rounds_allowed(rounds_left=3, steps_left=0) == 0
    assert retrieval_rounds_allowed(rounds_left=3, steps_left=1) == 1
    assert retrieval_rounds_allowed(rounds_left=1, steps_left=5) == 1


def test_call_limit_never_exceeds_remaining_run_room() -> None:
    plan = _plan(
        _ledger(max_tokens=2500),
        estimated_prompt_tokens=1600,
        safety_reserve_tokens=200,
        followup_llm=True,
    )
    assert plan.safety_reserve_tokens == 200
    assert plan.allowed_completion_tokens <= 700
    assert plan.allowed_completion_tokens < 1800
    assert plan.compact_instruction
    assert plan.remaining_tokens_after_call >= plan.safety_reserve_tokens
