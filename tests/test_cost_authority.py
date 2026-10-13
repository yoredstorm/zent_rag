# =============================================================================
# Autoridad de costo — un solo escritor de los totales del run.
# =============================================================================
# Contrato (ADR-003, refinado en S5):
#   * los totales de tokens/costo del run los escribe SOLO el RunBudgetLedger;
#   * los tokens del juez JEV entran por el ledger (no por escritura directa) y
#     no cuentan como llamada LLM ni como paso lógico;
#   * el evento de uso por fase (`jev_judge:*`) NO repite tokens: el consumo
#     viaja una sola vez, en el evento del run;
#   * el costo del juez no se inventa: sin tarifa, no hay costo (nunca 0
#     silencioso presentado como precio conocido).
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.decision.costs import SOURCE_NONE, resolve_cost
from src.decision.judgment import JudgmentContext
from src.decision.usage import DecisionUsageRecorder
from src.runtime.run_accounting import record_judge_call
from src.runtime.run_budget import RunBudgetLedger


def _result(**overrides):
    base = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "cost": 0.02,
        "embedding_tokens": 0,
        "llm_calls": 1,
        "tool_calls": 0,
        "logical_steps": 1,
        "steps": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -----------------------------------------------------------------------------
# El ledger es el escritor único de los totales.
# -----------------------------------------------------------------------------
def test_ledger_es_la_autoridad_de_los_totales() -> None:
    result = _result()
    ledger = RunBudgetLedger.for_totals(result)
    assert ledger.consumed_total_tokens == 150
    assert ledger.consumed_cost_usd == pytest.approx(0.02)


def test_tokens_del_juez_pasan_por_el_ledger() -> None:
    result = _result()
    record_judge_call(
        result, purpose="answer_gate", prompt_tokens=30, completion_tokens=10
    )
    ledger = RunBudgetLedger.for_totals(result)
    assert ledger.consumed_prompt_tokens == 130
    assert ledger.consumed_completion_tokens == 60
    assert ledger.consumed_total_tokens == 190
    assert [step["type"] for step in result.steps] == ["jev_usage"]


def test_tokens_del_juez_no_son_llamada_ni_paso() -> None:
    result = _result()
    record_judge_call(result, purpose="preflight", prompt_tokens=5, completion_tokens=5)
    assert result.llm_calls == 1
    assert result.logical_steps == 1


def test_tokens_del_juez_no_inventan_costo() -> None:
    result = _result()
    record_judge_call(result, purpose="preflight", prompt_tokens=5, completion_tokens=5)
    assert result.cost == pytest.approx(0.02)


def test_juez_sin_tokens_no_escribe_nada() -> None:
    result = _result()
    record_judge_call(result, purpose="preflight", prompt_tokens=0, completion_tokens=0)
    assert result.total_tokens == 150
    assert result.steps == []


def test_propiedad_ledger_y_total_nunca_divergen() -> None:
    for prompt, completion in ((0, 0), (7, 3), (120, 80), (1000, 1)):
        result = _result()
        record_judge_call(
            result, purpose="step", prompt_tokens=prompt, completion_tokens=completion
        )
        ledger = RunBudgetLedger.for_totals(result)
        expected = 150 + prompt + completion if prompt + completion else 150
        assert ledger.consumed_total_tokens == expected


# -----------------------------------------------------------------------------
# El evento por fase no duplica el consumo.
# -----------------------------------------------------------------------------
class _Captured:
    def __init__(self) -> None:
        self.events: list = []


@pytest.mark.asyncio
async def test_evento_del_juez_no_repite_tokens(monkeypatch) -> None:
    captured = _Captured()

    async def fake_record_event(event):  # noqa: ANN001 — doble de test
        captured.events.append(event)
        return True

    import src.platform.usage.usage_engine as usage_engine

    monkeypatch.setattr(usage_engine, "record_event", fake_record_event)

    recorder = DecisionUsageRecorder()
    context = JudgmentContext(
        phase="answer_gate",
        organization_id=uuid4(),
        request_id=uuid4(),
        provider="jev",
        model="jev-latest",
    )
    await recorder.record_judge(
        context,
        {
            "usage": {"input_tokens": 40, "output_tokens": 20},
            "latency_ms": 12.5,
            "estimated_cost": 0.0003,
            "cost_source": "registry",
        },
    )
    assert len(captured.events) == 1
    event = captured.events[0]
    assert event.prompt_tokens == 0
    assert event.completion_tokens == 0
    assert event.total_tokens == 0
    assert event.estimated_cost == pytest.approx(0.0003)
    assert event.routing["token_accounting"] == "run_event"
    assert event.routing["judge_tokens"] == 60
    assert event.routing["cost_source"] == "registry"
    assert event.event_type == "jev_judge:answer_gate"


@pytest.mark.asyncio
async def test_evento_del_juez_sin_tenant_no_existe(monkeypatch) -> None:
    captured = _Captured()

    async def fake_record_event(event):  # noqa: ANN001 — doble de test
        captured.events.append(event)
        return True

    import src.platform.usage.usage_engine as usage_engine

    monkeypatch.setattr(usage_engine, "record_event", fake_record_event)
    recorder = DecisionUsageRecorder()
    await recorder.record_judge(JudgmentContext(phase="answer_gate"), {"usage": {}})
    assert captured.events == []


# -----------------------------------------------------------------------------
# Unknown vs zero: sin tarifa no hay costo presentado como conocido.
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sin_tokens_no_hay_costo_y_la_fuente_lo_declara() -> None:
    cost = await resolve_cost(provider="jev", model="jev-latest")
    assert cost.source == SOURCE_NONE
    assert cost.amount == 0.0


@pytest.mark.asyncio
async def test_registry_caido_no_inventa_costo(monkeypatch) -> None:
    import src.platform.billing.pricing as pricing

    async def boom(*args, **kwargs):  # noqa: ANN002, ANN003 — doble de test
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(pricing, "get_price", boom)
    cost = await resolve_cost(
        provider="jev", model="jev-latest", prompt_tokens=100, completion_tokens=50
    )
    assert cost.source == SOURCE_NONE
    assert cost.amount == 0.0


@pytest.mark.asyncio
async def test_fallback_legacy_declara_su_fuente(monkeypatch) -> None:
    import src.platform.billing.pricing as pricing

    async def boom(*args, **kwargs):  # noqa: ANN002, ANN003 — doble de test
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(pricing, "get_price", boom)
    cost = await resolve_cost(
        provider="jev",
        model="jev-latest",
        prompt_tokens=1000,
        completion_tokens=0,
        legacy_per_1k=0.001,
    )
    assert cost.source == "legacy"
    assert cost.amount == pytest.approx(0.001)
