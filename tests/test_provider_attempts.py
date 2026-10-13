# =============================================================================
# Intentos de provider — el failover del router no se esconde (F5).
# =============================================================================
# Regla: cada intento del router (429, timeout, circuit open, fallback) queda
# como línea `provider_attempt` del ledger, sin sumar tokens ni costo. La línea
# `llm` factura solo el intento exitoso. «unknown != 0» en los intentos.
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.domain.entities import LLMResponse
from src.infrastructure.llm import router as router_module
from src.infrastructure.llm.router import ResolvedRoute, generate_routed
from src.runtime.run_accounting import record_provider_attempt
from src.runtime.run_budget import RunBudgetLedger


class _RateLimited(Exception):
    """429 transitorio (reintentable): no es la cuota explícita del proveedor."""

    status_code = 429

    def __init__(self) -> None:
        super().__init__("429 too many requests")


class _AuthError(Exception):
    status_code = 401


def _result() -> SimpleNamespace:
    return SimpleNamespace(
        steps=[],
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        cost=0.0,
        llm_calls=0,
        logical_steps=0,
        cost_status="",
        cost_reason="",
        model="",
        provider="",
    )


def _route() -> ResolvedRoute:
    return ResolvedRoute(
        primary="prov-a/model-x", fallback="prov-b/model-y", alias=None
    )


def _response(model: str) -> LLMResponse:
    return LLMResponse(
        content="ok",
        model=model,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )


class TestRouterAttempts:
    async def test_429_retry_y_fallback_exitoso(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(router_module, "_TRANSIENT_RETRY_SECONDS", 0.0)
        calls: list[str] = []

        async def fake_generate(prompt: str, *, model: str, **kwargs: object):
            calls.append(model)
            if len(calls) <= 2:
                raise _RateLimited()
            return _response(model)

        response = await generate_routed(
            fake_generate, prompt="p", route=_route(), max_tokens=64
        )

        assert [item["status"] for item in response.attempts] == [
            "rate_limited",
            "rate_limited",
            "success",
        ]
        assert [item["provider"] for item in response.attempts] == [
            "prov-a",
            "prov-a",
            "prov-b",
        ]
        assert response.attempts[0]["retry"] is False
        assert response.attempts[1]["retry"] is True
        assert response.attempts[2]["fallback"] is True
        assert response.content == "ok"

    async def test_error_no_reintentable_va_directo_al_fallback(self) -> None:
        calls: list[str] = []

        async def fake_generate(prompt: str, *, model: str, **kwargs: object):
            calls.append(model)
            if model == "prov-a/model-x":
                raise _AuthError("invalid api key")
            return _response(model)

        response = await generate_routed(
            fake_generate, prompt="p", route=_route(), max_tokens=64
        )

        assert calls == ["prov-a/model-x", "prov-b/model-y"]
        assert [item["status"] for item in response.attempts] == [
            "auth_error",
            "success",
        ]

    async def test_todos_los_candidatos_fallan_propaga_con_intentos(self) -> None:
        async def fake_generate(prompt: str, *, model: str, **kwargs: object):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError) as excinfo:
            await generate_routed(
                fake_generate, prompt="p", route=_route(), max_tokens=64
            )
        attempts = getattr(excinfo.value, "llm_attempts", None)
        assert isinstance(attempts, list) and len(attempts) == 2
        assert [item["provider"] for item in attempts] == ["prov-a", "prov-b"]


class TestLedgerDelFailover:
    async def test_lineas_provider_attempt_sin_doble_conteo(self) -> None:
        from src.runtime.run_accounting import record_llm_call

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(router_module, "_TRANSIENT_RETRY_SECONDS", 0.0)
        try:
            calls: list[str] = []

            async def fake_generate(prompt: str, *, model: str, **kwargs: object):
                calls.append(model)
                if len(calls) <= 2:
                    raise _RateLimited()
                return _response(model)

            response = await generate_routed(
                fake_generate, prompt="p", route=_route(), max_tokens=64
            )
        finally:
            monkeypatch.undo()

        result = _result()
        ledger = RunBudgetLedger(result, max_steps=5, max_tokens=1000, max_cost_usd=1.0)
        await record_llm_call(
            result,
            ledger,
            response=response,
            purpose="generation",
            model=response.model,
            latency_ms=12.0,
        )

        types = [step["type"] for step in result.steps]
        assert types.count("provider_attempt") == 2
        assert types.count("llm") == 1
        # Solo el intento exitoso suma tokens/costo al ledger.
        assert ledger.consumed_total_tokens == 15
        assert ledger.llm_calls == 1
        for step in result.steps:
            if step["type"] == "provider_attempt":
                assert step["cost_status"] == "unknown"
                assert "cost" not in step

    def test_metrica_de_intentos(self) -> None:
        from src.infrastructure.observability.metrics import (
            zent_provider_attempts_total,
        )

        result = _result()
        counter = zent_provider_attempts_total.labels(
            provider="prov-a", status="rate_limited", retry="1"
        )
        before = counter._value.get()
        record_provider_attempt(
            result,
            provider="prov-a",
            model="prov-a/model-x",
            status="rate_limited",
            latency_ms=3.5,
            retry=True,
        )
        assert counter._value.get() == before + 1
