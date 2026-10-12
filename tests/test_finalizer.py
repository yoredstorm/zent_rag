# =============================================================================
# Finalizer — presupuesto del cierre (un ledger, un plan).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace

from src.runtime.finalizer import FinalizeBudget, plan_finalize_budget


def _result():
    return SimpleNamespace(
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        cost=0.0,
        llm_calls=0,
        logical_steps=0,
        tool_calls=0,
    )


class TestPlanFinalizeBudget:
    async def test_con_presupuesto_devuelve_plan(self) -> None:
        budget = await plan_finalize_budget(
            _result(),
            {"model": "m", "max_total_tokens": 8000, "max_steps": 10},
            prompt="p" * 100,
            question="q",
            configured_max_tokens=0,
            answer_max_tokens=1024,
        )
        assert isinstance(budget, FinalizeBudget)
        assert budget.max_tokens > 0
        assert budget.ledger.max_tokens == 8000

    async def test_sin_presupuesto_devuelve_none(self) -> None:
        budget = await plan_finalize_budget(
            _result(),
            {"model": "m", "max_total_tokens": 0, "max_steps": 10},
            prompt="p",
            question="q",
            configured_max_tokens=0,
            answer_max_tokens=1024,
        )
        assert budget is None

    async def test_configured_cap_limita_el_desired(self) -> None:
        budget = await plan_finalize_budget(
            _result(),
            {"model": "m", "max_total_tokens": 8000, "max_steps": 10},
            prompt="p" * 100,
            question="q",
            configured_max_tokens=256,
            answer_max_tokens=1024,
        )
        assert budget is not None
        assert budget.call_plan.desired_completion_tokens == 256

    async def test_consumo_previo_reduce_el_margen(self) -> None:
        result = _result()
        result.total_tokens = 7900
        budget = await plan_finalize_budget(
            result,
            {"model": "m", "max_total_tokens": 8000, "max_steps": 10},
            prompt="p" * 400,
            question="q",
            configured_max_tokens=0,
            answer_max_tokens=1024,
        )
        assert budget is None
