import pytest

from src.platform.workflows.planner_budget import estimate_tokens, preflight_budget
from src.platform.workflows.planner_diagnostics import (
    budget_diagnostic,
    user_diagnostic,
)
from src.platform.workflows.planner_session import PlannerBudget


def test_preflight_reserves_enough_for_plan_and_verify() -> None:
    budget = PlannerBudget()
    estimate = preflight_budget(
        budget,
        prompt="Quiero un mentor de Python con progreso",
        system_prompt="catálogo " * 200,
        catalog_chars=2000,
    )
    assert estimate.feasible is True
    assert estimate.reserves["understand"] > 0
    assert estimate.reserves["plan_verify"] > 0
    assert estimate.total_tokens <= budget.max_tokens
    assert estimate.as_dict()["feasible"] is True


def test_preflight_reports_token_shortfall_without_pretending_success() -> None:
    budget = PlannerBudget(max_tokens=2000, max_llm_calls=2)
    estimate = preflight_budget(
        budget,
        prompt="x" * 4000,
        system_prompt="contrato " * 400,
        catalog_chars=8000,
    )
    assert estimate.feasible is False
    assert estimate.reason in ("tokens", "llm_calls")
    assert estimate.shortfall_tokens > 0
    diagnostic = user_diagnostic("planner.budget_insufficient")
    assert diagnostic["action"]
    assert "presupuesto" in diagnostic["message"].lower()


def test_budget_reason_maps_to_human_cta() -> None:
    tokens = budget_diagnostic("tokens")
    calls = budget_diagnostic("tool_calls")
    assert "tokens" in tokens["action"].lower()
    assert "herramientas" in calls["action"].lower()
    assert tokens["retryable"] is True


def test_token_estimator_is_conservative() -> None:
    assert estimate_tokens("cuatro") == 2
    assert estimate_tokens("") == 1


@pytest.mark.asyncio
async def test_planner_result_exposes_preflight_estimate() -> None:
    from tests.test_workflow_planner_agentic import (
        _SPEC,
        FakeProvider,
        _session,
    )

    provider = FakeProvider(
        [_SPEC, {"action": "clarify", "questions": ["¿Qué fuente uso?"]}]
    )
    result = await _session(provider).run("Quiero un mentor de Python")
    assert result["state"] == "NEEDS_CLARIFICATION"
    assert result["budget_estimate"]["feasible"] is True
    assert result["planner"]["budget_estimate"]["reserves"]["plan_verify"] > 0
