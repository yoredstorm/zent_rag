# =============================================================================
# Contabilidad única del run — ledger == usage event (agente y RAG).
# Un writer (`run_accounting`), un ledger (`RunBudgetLedger`); el evento LEE.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.agents.runtime.agent_runtime import AgentRunResult
from src.agents.runtime.orchestrator import _build_usage_event
from src.core.domain.entities import LLMResponse, RAGQueryResult
from src.platform.billing.pricing import PriceRecord, estimate_cost_from_price
from src.runtime.run_accounting import (
    account_rag_result,
    record_judge_call,
    record_llm_call,
)
from src.runtime.run_budget import RunBudgetLedger

PRICE = PriceRecord(
    provider="test",
    model="test-model",
    input_cost_per_1k=0.001,
    output_cost_per_1k=0.002,
    embedding_cost_per_1k=0.0005,
)


class _Chunks:
    chunks = [1, 2]


def _fake_price(price: PriceRecord = PRICE):
    async def _get(model: str) -> PriceRecord:
        return price

    return _get


def _rag_result(
    *,
    query: str = "a" * 16,
    cognitive: float = 0.0,
    flow: dict | None = None,
) -> RAGQueryResult:
    return RAGQueryResult(
        query=query,
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
        flow=flow,
    )


class TestRagLedgerEqualsEvent:
    @pytest.mark.asyncio
    async def test_ledger_totales_igualan_el_evento(self, monkeypatch) -> None:
        monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
        result = _rag_result()
        await account_rag_result(
            result, query=result.query, model="test-model", reranking_count=1
        )
        ledger = RunBudgetLedger(result, max_steps=0, max_tokens=0, max_cost_usd=None)
        event = _build_usage_event(
            result,
            organization_id=uuid4(),
            user_id=uuid4(),
            effective_model="test-model",
            reranking_count=1,
        )
        assert event.prompt_tokens == ledger.consumed_prompt_tokens == 1000
        assert event.completion_tokens == ledger.consumed_completion_tokens == 500
        assert event.total_tokens == ledger.consumed_total_tokens == 1500
        assert event.embedding_tokens == ledger.consumed_embedding_tokens == 4
        assert event.estimated_cost == pytest.approx(ledger.consumed_cost_usd)
        assert event.actual_cost == pytest.approx(ledger.consumed_cost_usd)
        assert event.reranking_count == 1

    @pytest.mark.asyncio
    async def test_costo_igual_a_la_formula_historica(self, monkeypatch) -> None:
        monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
        result = _rag_result(cognitive=0.002)
        await account_rag_result(result, query=result.query, model="test-model")

        esperado = estimate_cost_from_price(PRICE, 1000, 500, 4) + 0.002
        assert result.cost == pytest.approx(esperado)

    @pytest.mark.asyncio
    async def test_idempotente_no_doble_cuenta(self, monkeypatch) -> None:
        monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
        result = _rag_result()
        await account_rag_result(result, query=result.query, model="test-model")
        primero = (result.total_tokens, result.cost, result.llm_calls)
        await account_rag_result(result, query=result.query, model="test-model")
        assert (result.total_tokens, result.cost, result.llm_calls) == primero


class TestRagLineasExplicitas:
    @pytest.mark.asyncio
    async def test_embedding_linea_y_costo_explicito(self, monkeypatch) -> None:
        monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
        result = _rag_result()
        await account_rag_result(result, query=result.query, model="test-model")
        linea = [s for s in result.steps if s["type"] == "embedding"]
        assert linea
        assert linea[0]["tokens"] == 4
        assert linea[0]["cost_status"] == "known"
        assert linea[0]["cost"] == pytest.approx(4 / 1000 * 0.0005)

    @pytest.mark.asyncio
    async def test_sin_tarifa_el_costo_es_desconocido_no_cero(self, monkeypatch) -> None:
        async def _boom(model: str) -> PriceRecord:
            raise RuntimeError("no db")

        monkeypatch.setattr("src.platform.billing.pricing.get_price", _boom)
        result = _rag_result()
        await account_rag_result(result, query=result.query, model="test-model")
        emb = [s for s in result.steps if s["type"] == "embedding"][0]
        assert emb["cost_status"] == "unknown"
        assert "cost" not in emb
        assert result.cost_status == "unknown"

    @pytest.mark.asyncio
    async def test_rerank_linea_solo_cuando_corresponde(self, monkeypatch) -> None:
        monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
        sin_rerank = _rag_result()
        await account_rag_result(sin_rerank, query=sin_rerank.query, model="test-model")
        assert not [s for s in sin_rerank.steps if s["type"] == "rerank"]

        con_rerank = _rag_result()
        await account_rag_result(
            con_rerank, query=con_rerank.query, model="test-model", reranking_count=1
        )
        linea = [s for s in con_rerank.steps if s["type"] == "rerank"]
        assert linea and linea[0]["count"] == 1
        assert linea[0]["cost_status"] == "unknown"

    @pytest.mark.asyncio
    async def test_jev_observado_no_toca_totales(self, monkeypatch) -> None:
        monkeypatch.setattr("src.platform.billing.pricing.get_price", _fake_price())
        result = _rag_result(
            flow={"jev_preflight": {"tokens": {"input": 10, "output": 5}, "cost_usd": 0.0}}
        )
        await account_rag_result(result, query=result.query, model="test-model")

        assert result.total_tokens == 1500
        assert result.cost == pytest.approx(0.002002)
        jev = [s for s in result.steps if s["type"] == "jev_usage"][0]
        assert jev["tokens"] == 15
        assert jev["billed_separately"] is True
        event = _build_usage_event(
            result,
            organization_id=uuid4(),
            user_id=uuid4(),
            effective_model="test-model",
        )
        assert event.cost_tags.get("jev_tokens") == 15
        assert event.total_tokens == 1500


class TestAgentSingleWriter:
    @pytest.mark.asyncio
    async def test_ledger_y_result_en_sincronia(self) -> None:
        result = AgentRunResult(
            run_id=uuid4(),
            agent_id=uuid4(),
            organization_id=None,
            status="completed",
            answer="ok",
        )
        ledger = RunBudgetLedger.from_config(
            result, {"max_total_tokens": 1000, "max_steps": 10}
        )

        class _Resp:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150
            model = "test-model"
            finish_reason = "stop"

        await record_llm_call(
            result,
            ledger,
            response=_Resp(),
            purpose="generation",
            model="test-model",
            latency_ms=5.0,
        )
        record_judge_call(
            result, purpose="answer_gate", prompt_tokens=10, completion_tokens=5
        )

        assert ledger.consumed_total_tokens == result.total_tokens == 165
        assert ledger.consumed_prompt_tokens == result.prompt_tokens == 110
        assert ledger.consumed_completion_tokens == result.completion_tokens == 55
        assert ledger.llm_calls == result.llm_calls == 1
        assert [s for s in result.steps if s["type"] == "llm"]
        assert [s for s in result.steps if s["type"] == "jev_usage"]
