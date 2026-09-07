"""Phase 29 — Analytical reasoning."""
from __future__ import annotations

from src.core.domain.research import ResearchStepStatus
from src.intelligence.analytical import AnalyticalReasoningEngine


def test_build_research_plan_for_why_question() -> None:
    engine = AnalyticalReasoningEngine()
    plan = engine.build_research_plan("¿Por qué cayeron las ventas en agosto?")
    assert plan.question.startswith("¿Por qué")
    assert len(plan.steps) >= 5
    assert len(plan.steps) <= plan.budgets.max_steps
    assert all(s.status == ResearchStepStatus.PENDING for s in plan.steps)
    assert plan.budget_exceeded() is None


def test_decompose_operations() -> None:
    engine = AnalyticalReasoningEngine()
    ops = {o["operation"] for o in engine.decompose("varianza por canal")}
    assert "period_comparison" in ops
    assert "variance" in ops
    assert "dimension_decomposition" in ops
    assert "top_contributors" in ops


def test_driver_analysis_shares_and_causality() -> None:
    engine = AnalyticalReasoningEngine()
    result = engine.driver_analysis(
        total_delta=-0.18,
        contributions=[
            {"name": "Corporate Channel", "delta": -0.11},
            {"name": "North Region", "delta": -0.03},
            {"name": "Product X", "delta": -0.02},
            {"name": "Other", "delta": -0.02},
        ],
    )
    assert result["causality"] == "not_established"
    assert result["primary_drivers"][0]["name"] == "Corporate Channel"
    shares = sum(abs(d["share_abs"]) for d in result["primary_drivers"] + result["secondary_drivers"])
    assert abs(shares - 1.0) < 1e-6

    causal = engine.driver_analysis(
        -0.1,
        [{"name": "A", "delta": -0.1}],
        causal_evidence=True,
    )
    assert causal["causality"] == "established"


def test_step_budget_with_loop_guard() -> None:
    engine = AnalyticalReasoningEngine()
    plan = engine.build_research_plan("¿Por qué bajaron las ventas?")
    assert engine.can_execute_step(plan, plan.steps[0].name) is True
    # identical retry without new info blocked
    assert engine.can_execute_step(plan, plan.steps[0].name) is False
