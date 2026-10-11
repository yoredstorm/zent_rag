# =============================================================================
# Streaming del provider — failover antes del primer token, nunca después.
# =============================================================================
# Extiende la matriz adversarial de providers (hallazgo 10 del audit):
# 429/timeout antes del primer token → fallback; stream cortado tras emitir →
# error (cambiar de modelo duplicaría la respuesta); circuit open → fallback;
# todos fallan → el error del proveedor se propaga. Hermético: sin red.
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.llm import provider as provider_module
from src.infrastructure.resilience.circuit_breaker import CircuitBreakerOpenError


class _NoopLimiter:
    async def acquire(self) -> None:
        return None


class _DirectBreaker:
    """Breaker transparente: el test mide el failover, no el breaker."""

    async def call(self, name: str, fn: Any, **kwargs: Any) -> Any:
        return await fn(**kwargs)


def _install(monkeypatch: pytest.MonkeyPatch, acompletion: Any) -> None:
    monkeypatch.setattr(provider_module, "_llm_rate_limiter", lambda: _NoopLimiter())
    monkeypatch.setattr(provider_module, "_circuit_breaker", _DirectBreaker())
    monkeypatch.setattr(provider_module, "acompletion", acompletion)
    monkeypatch.setattr(
        "src.infrastructure.llm.router.resolve_route",
        lambda requested=None, **kwargs: SimpleNamespace(
            candidates=lambda: ["primary-model", "fallback-model"]
        ),
    )


def _chunk(content: str = "", finish_reason: str | None = None) -> Any:
    choices = []
    if content or finish_reason:
        choices.append(
            SimpleNamespace(
                delta=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        )
    return SimpleNamespace(choices=choices, usage=None)


def _stream(*chunks: Any):
    async def _gen():
        for chunk in chunks:
            yield chunk

    return _gen()


def _provider():
    return provider_module.LiteLLMProvider()


async def _collect(agen) -> list[dict]:
    return [event async for event in agen]


class TestStreamingFailover:
    @pytest.mark.asyncio
    async def test_429_antes_del_primer_token_va_al_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake_acompletion(**kwargs: Any) -> Any:
            model = kwargs["model"]
            calls.append(model)
            if model == "primary-model":
                raise RuntimeError("Error code: 429 - rate limit exceeded")
            return _stream(_chunk("hola "), _chunk("mundo", finish_reason="stop"))

        _install(monkeypatch, fake_acompletion)
        events = await _collect(_provider().generate_stream(prompt="q"))

        assert calls == ["primary-model", "fallback-model"]
        assert [e["type"] for e in events] == ["delta", "delta", "done"]
        assert events[-1]["model"] == "fallback-model"
        assert events[-1]["content"] == "hola mundo"

    @pytest.mark.asyncio
    async def test_circuit_open_antes_del_primer_token_va_al_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake_acompletion(**kwargs: Any) -> Any:
            model = kwargs["model"]
            calls.append(model)
            if model == "primary-model":
                raise CircuitBreakerOpenError("Circuit breaker is OPEN for 'primary-model'")
            return _stream(_chunk("ok", finish_reason="stop"))

        _install(monkeypatch, fake_acompletion)
        events = await _collect(_provider().generate_stream(prompt="q"))

        assert calls == ["primary-model", "fallback-model"]
        assert events[-1]["model"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_timeout_antes_del_primer_token_va_al_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake_acompletion(**kwargs: Any) -> Any:
            model = kwargs["model"]
            calls.append(model)
            if model == "primary-model":
                raise TimeoutError("Request timed out")
            return _stream(_chunk("ok", finish_reason="stop"))

        _install(monkeypatch, fake_acompletion)
        events = await _collect(_provider().generate_stream(prompt="q"))

        assert calls == ["primary-model", "fallback-model"]
        assert events[-1]["model"] == "fallback-model"

    @pytest.mark.asyncio
    async def test_stream_cortado_tras_emitir_no_cambia_de_modelo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake_acompletion(**kwargs: Any) -> Any:
            model = kwargs["model"]
            calls.append(model)
            if model == "primary-model":
                async def _broken():
                    yield _chunk("parcial ")
                    raise RuntimeError("stream interrupted")

                return _broken()
            return _stream(_chunk("no debería usarse", finish_reason="stop"))

        _install(monkeypatch, fake_acompletion)
        received: list[dict] = []
        with pytest.raises(RuntimeError, match="stream interrupted"):
            async for event in _provider().generate_stream(prompt="q"):
                received.append(event)

        # El cliente ya vio texto: no hay failover posible (duplicaría).
        assert received == [{"type": "delta", "text": "parcial "}]
        assert calls == ["primary-model"]

    @pytest.mark.asyncio
    async def test_todos_los_candidatos_fallan_propaga_el_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        async def fake_acompletion(**kwargs: Any) -> Any:
            model = kwargs["model"]
            calls.append(model)
            raise RuntimeError(f"down: {model}")

        _install(monkeypatch, fake_acompletion)
        with pytest.raises(RuntimeError, match="down: fallback-model"):
            await _collect(_provider().generate_stream(prompt="q"))

        assert calls == ["primary-model", "fallback-model"]

    @pytest.mark.asyncio
    async def test_estable_100_runs_misma_secuencia(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Misma entrada × 100: misma secuencia de modelos y mismo resultado."""
        async def fake_acompletion(**kwargs: Any) -> Any:
            if kwargs["model"] == "primary-model":
                raise RuntimeError("Error code: 429 - rate limit exceeded")
            return _stream(_chunk("ok", finish_reason="stop"))

        _install(monkeypatch, fake_acompletion)
        seen: set[tuple[str, str]] = set()
        for _ in range(100):
            events = await _collect(_provider().generate_stream(prompt="q"))
            seen.add((events[-1]["model"], events[-1]["content"]))
        assert seen == {("fallback-model", "ok")}
