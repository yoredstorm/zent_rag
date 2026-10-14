# =============================================================================
# Certification battery — cadena contable (Parte I del checklist de canary).
# =============================================================================
# Invariante a demostrar con matemática conocida:
#
#   ledger total == usage total == billing input == observability total
#
# para los componentes que comparten unidad monetaria, y:
#
#   unknown != zero
#
# El test usa los writers REALES (run_accounting / RunBudgetLedger / usage
# engine / reconcile / run_metrics), con precio determinista inyectado, y
# verifica la cadena completa incluida la fila en `usage_events` y el counter
# de Prometheus.
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.agents.runtime.orchestrator import _build_usage_event
from src.core.domain.entities import LLMResponse, RAGQueryResult
from src.platform.billing.pricing import PriceRecord, estimate_cost_from_price
from src.platform.billing.reconciliation import reconcile
from src.platform.usage.usage_engine import UsageEvent, record_event
from src.runtime.run_accounting import (
    account_rag_result,
    record_embedding_call,
    record_judge_call,
    record_llm_call,
)
from src.runtime.run_budget import RunBudgetLedger
from src.runtime.run_metrics import publish_run_metrics

PRICE = PriceRecord(
    provider="test",
    model="test-model",
    input_cost_per_1k=0.001,
    output_cost_per_1k=0.002,
    embedding_cost_per_1k=0.0005,
)
# Matemática a mano: 1000 tok in * 0.001/1k + 500 tok out * 0.002/1k
#                    + 4 tok embedding * 0.0005/1k
EXPECTED_SINGLE_CALL_USD = 0.001 + 0.001 + 0.000002


class _Chunks:
    chunks = [1, 2]


def _fake_price(price: PriceRecord = PRICE):
    async def _get(model: str) -> PriceRecord:
        return price

    return _get


def _counter(name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name != name:
                continue
            if all(sample.labels.get(k) == v for k, v in labels.items()):
                return float(sample.value)
    return 0.0


def _rag_result(*, cognitive: float = 0.0) -> RAGQueryResult:
    return RAGQueryResult(
        query="cert-chain-query",
        llm_response=LLMResponse(
            content="respuesta",
            model="test-model",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            latency_ms=12.5,
        ),
        retrieval_context=_Chunks(),
        cognitive_cost_usd=cognitive,
    )


@pytest.mark.asyncio
async def test_ledger_usage_billing_observability_chain(monkeypatch) -> None:
    """Una llamada, matemática conocida: la cadena completa cuadra."""
    monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
    org, user = uuid4(), uuid4()

    result = _rag_result()
    await account_rag_result(
        result, query=result.query, model="test-model", reranking_count=1
    )

    # 1) ledger
    ledger = RunBudgetLedger(result, max_steps=0, max_tokens=0, max_cost_usd=None)
    assert ledger.consumed_prompt_tokens == 1000
    assert ledger.consumed_completion_tokens == 500
    assert ledger.consumed_total_tokens == 1500
    assert ledger.consumed_cost_usd == pytest.approx(EXPECTED_SINGLE_CALL_USD)

    # 2) usage event (el evento LEE el ledger, no recalcula)
    event = _build_usage_event(
        result,
        organization_id=org,
        user_id=user,
        effective_model="test-model",
        reranking_count=1,
    )
    assert event.total_tokens == ledger.consumed_total_tokens
    assert event.estimated_cost == pytest.approx(ledger.consumed_cost_usd)
    assert event.actual_cost == pytest.approx(ledger.consumed_cost_usd)
    assert event.reranking_count == 1

    # 3) billing input: la fila persiste y reconcile la lee como uso.
    assert await record_event(event) is True
    report = await reconcile(org, days=1)
    row = next((r for r in report if str(r["organization_id"]) == str(org)), None)
    assert row is not None, "reconcile no ve la fila de usage recién escrita"
    assert row["usage_cost"] == pytest.approx(EXPECTED_SINGLE_CALL_USD)
    # Sin facturas todavía: el delta uso-facturado es el uso. El reporte redondea
    # a centavos (round(...,2)): un run de 0.002 USD cae a 0.00 por diseño.
    assert row["delta_usage_vs_invoiced"] == 0.0

    # 4) observabilidad: el counter sube exactamente el costo conocido.
    before = _counter("zent_run_cost_usd_total", path="rag")
    publish_run_metrics(
        SimpleNamespace(
            phase="FINALIZED",
            trace=SimpleNamespace(latency_ms=123.0),
            decisions=None,
            evidence=None,
        ),
        path="rag",
        result=result,
    )
    after = _counter("zent_run_cost_usd_total", path="rag")
    assert after - before == pytest.approx(EXPECTED_SINGLE_CALL_USD)


@pytest.mark.asyncio
async def test_retry_and_fallback_are_visible_without_double_count(monkeypatch) -> None:
    monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
    result = RAGQueryResult(query="cert-retry", llm_response=None, retrieval_context=_Chunks())
    ledger = RunBudgetLedger(result, max_steps=0, max_tokens=0, max_cost_usd=None)

    step = await record_llm_call(
        result,
        ledger,
        response=LLMResponse(
            content="ok",
            model="test-model",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            attempts=[
                {"provider": "p1", "model": "m1", "status": "rate_limited", "retry": False, "latency_ms": 5.0},
                {"provider": "p2", "model": "m2", "status": "success", "retry": True, "latency_ms": 9.0},
            ],
        ),
        purpose="answer",
        model="test-model",
        latency_ms=12.0,
    )
    await record_embedding_call(result, ledger, model="test-model", tokens=4)
    record_judge_call(result, purpose="jev", prompt_tokens=200, completion_tokens=50)

    # El intento fallido queda visible y SIN costo (no factura el intento).
    attempts = [s for s in result.steps if s["type"] == "provider_attempt"]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "rate_limited"
    assert "cost" not in attempts[0]
    assert attempts[0]["cost_status"] == "unknown"

    # El ledger factura solo el éxito: una llamada LLM + embeddings.
    assert step["cost"] == pytest.approx(0.002)
    assert result.llm_calls == 1
    assert result.cost == pytest.approx(EXPECTED_SINGLE_CALL_USD)
    # JEV suma tokens al ledger, sin costo inventado.
    assert result.total_tokens == 1500 + 250
    assert result.cost == pytest.approx(EXPECTED_SINGLE_CALL_USD)

    event = _build_usage_event(
        result,
        organization_id=uuid4(),
        user_id=uuid4(),
        effective_model="test-model",
        reranking_count=0,
    )
    assert event.total_tokens == result.total_tokens
    assert event.estimated_cost == pytest.approx(result.cost)


@pytest.mark.asyncio
async def test_unknown_cost_is_not_zero(monkeypatch) -> None:
    """Sin tarifa: unknown explícito, cero tokens facturados, counter separado."""

    async def _broken(model: str, prompt: int, completion: int) -> float:
        raise RuntimeError("pricing registry unavailable")

    monkeypatch.setattr("src.runtime.run_budget.usage_cost", _broken)
    result = RAGQueryResult(query="cert-unknown", llm_response=None, retrieval_context=_Chunks())
    ledger = RunBudgetLedger(result, max_steps=0, max_tokens=0, max_cost_usd=None)

    step = await record_llm_call(
        result,
        ledger,
        response=LLMResponse(
            content="ok", model="unpriced-model", prompt_tokens=10, completion_tokens=5,
            total_tokens=15,
        ),
        purpose="answer",
        model="unpriced-model",
        latency_ms=1.0,
    )
    assert step["cost_status"] == "unknown"
    assert "cost" not in step  # unknown no se imputa como 0 en la línea
    assert result.cost_status == "unknown"
    assert result.cost_reason == "RuntimeError"
    assert result.cost == 0.0  # el total no inventa precio

    before_known = _counter("zent_run_cost_usd_total", path="rag")
    before_unknown = _counter("zent_run_cost_unknown_total", path="rag")
    publish_run_metrics(
        SimpleNamespace(
            phase="FINALIZED",
            trace=SimpleNamespace(latency_ms=50.0),
            decisions=None,
            evidence=None,
        ),
        path="rag",
        result=result,
    )
    assert _counter("zent_run_cost_usd_total", path="rag") == before_known
    assert _counter("zent_run_cost_unknown_total", path="rag") == before_unknown + 1


@pytest.mark.asyncio
async def test_hand_math_matches_pricing_helper(monkeypatch) -> None:
    """La fórmula del test y la del código coinciden (sin deriva silenciosa)."""
    monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
    esperado = estimate_cost_from_price(PRICE, 1000, 500, 4)
    assert esperado == pytest.approx(EXPECTED_SINGLE_CALL_USD)


@pytest.mark.asyncio
async def test_usage_write_survives_transient_db_disconnect(monkeypatch) -> None:
    """Postgres transitoriamente caído: el write de usage es fail-silent.

    La contabilidad no puede tumbar el run (chaos F: desconexión transitoria de
    PostgreSQL). El evento se pierde, pero el run responde y el fallo es visible
    por logs/metrics, nunca por excepción hacia el usuario.
    """

    class _BrokenSession:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("server closed the connection unexpectedly")

        async def commit(self):
            raise RuntimeError("server closed the connection unexpectedly")

        async def rollback(self):
            return None

        async def close(self):
            return None

    async def _broken_session():
        return _BrokenSession()

    monkeypatch.setattr(
        "src.platform.usage.usage_engine.get_async_session", _broken_session
    )
    event = UsageEvent(
        request_id=uuid4(),
        event_type="rag_query",
        organization_id=uuid4(),
        total_tokens=10,
        estimated_cost=0.001,
        model="test-model",
    )
    assert await record_event(event) is False  # no lanza
