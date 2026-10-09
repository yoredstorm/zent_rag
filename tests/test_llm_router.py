# =============================================================================
# AI Gateway router — aliases, org override, primary → fallback
# =============================================================================
from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.core.domain.entities import LLMResponse
from src.platform.gateway.router import generate_routed, resolve_route


class _FakeLLM:
    def __init__(self, fail_models: set[str] | None = None) -> None:
        self.fail_models = fail_models or set()
        self.calls: list[str] = []

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        name = model or "missing"
        self.calls.append(name)
        if name in self.fail_models:
            raise RuntimeError(f"primary down: {name}")
        return LLMResponse(
            content=f"ok:{name}",
            model=name,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1.0,
            finish_reason="stop",
        )


def test_org_override_wins_over_alias() -> None:
    route = resolve_route(
        requested="zent-default",
        org_override="openai/gpt-4o",
    )
    assert route.primary == "openai/gpt-4o"
    assert route.alias == "override"


def test_zent_default_resolves_to_settings_primary() -> None:
    from src.core.config import get_settings

    route = resolve_route(requested="zent-default", org_override=None)
    assert route.alias == "zent-default"
    assert route.primary == get_settings().LITELLM_DEFAULT_MODEL


def test_passthrough_concrete_model() -> None:
    route = resolve_route(requested="deepseek/chat", org_override=None)
    assert route.primary == "deepseek/chat"
    assert route.alias is None


@pytest.mark.asyncio
async def test_generate_routed_uses_fallback_when_primary_fails() -> None:
    fake = _FakeLLM(fail_models={"bad-primary"})
    route = resolve_route(
        requested="zent-default",
        org_override=None,
        primary_override="bad-primary",
        fallback_override="good-fallback",
    )
    response = await generate_routed(
        fake.generate,
        prompt="hola",
        route=route,
    )
    assert response.model == "good-fallback"
    assert response.content == "ok:good-fallback"
    assert fake.calls == ["bad-primary", "good-fallback"]


@pytest.mark.asyncio
async def test_generate_routed_does_not_fallback_when_primary_ok() -> None:
    fake = _FakeLLM()
    route = resolve_route(
        requested="ok-model",
        fallback_override="unused-fallback",
    )
    response = await generate_routed(fake.generate, prompt="hola", route=route)
    assert response.model == "ok-model"
    assert fake.calls == ["ok-model"]


class _RateLimitError(Exception):
    status_code = 429


@pytest.mark.asyncio
async def test_generate_routed_retries_transient_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un 429 transitorio reintenta el MISMO modelo una vez antes del fallback."""
    from src.infrastructure.llm import router as router_module

    monkeypatch.setattr(router_module, "_TRANSIENT_RETRY_SECONDS", 0.0)
    calls: list[str] = []

    async def generate(prompt: str, model: str | None = None, **kwargs) -> LLMResponse:
        calls.append(str(model))
        if len(calls) == 1:
            raise _RateLimitError("Model busy, retry later")
        return LLMResponse(content="ok", model=model)

    route = resolve_route(requested="primary", fallback_override="fallback")
    response = await generate_routed(generate, prompt="hola", route=route)
    assert response.model == "primary"
    assert calls == ["primary", "primary"]


@pytest.mark.asyncio
async def test_generate_routed_transient_retry_then_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.llm import router as router_module

    monkeypatch.setattr(router_module, "_TRANSIENT_RETRY_SECONDS", 0.0)
    calls: list[str] = []

    async def generate(prompt: str, model: str | None = None, **kwargs) -> LLMResponse:
        calls.append(str(model))
        if model == "primary":
            raise _RateLimitError("Model busy")
        return LLMResponse(content="ok", model=model)

    route = resolve_route(requested="primary", fallback_override="fallback")
    response = await generate_routed(generate, prompt="hola", route=route)
    assert response.model == "fallback"
    assert calls == ["primary", "primary", "fallback"]


@pytest.mark.asyncio
async def test_generate_routed_non_transient_goes_straight_to_fallback() -> None:
    fake = _FakeLLM(fail_models={"bad-primary"})
    route = resolve_route(
        requested="zent-default",
        org_override=None,
        primary_override="bad-primary",
        fallback_override="good-fallback",
    )
    response = await generate_routed(fake.generate, prompt="hola", route=route)
    assert response.model == "good-fallback"
    assert fake.calls == ["bad-primary", "good-fallback"]


@pytest.mark.asyncio
async def test_circuit_breaker_es_por_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un modelo caído no abre el circuito del fallback."""
    from types import SimpleNamespace

    from src.core.config import get_settings
    from src.infrastructure.llm import provider as provider_module
    from src.infrastructure.resilience.circuit_breaker import CircuitBreaker

    settings = get_settings()
    monkeypatch.setattr(settings, "GATEWAY_FALLBACK_MODEL", "")
    monkeypatch.setattr(
        provider_module,
        "_circuit_breaker",
        CircuitBreaker(failure_threshold=3, recovery_timeout=30.0),
    )

    async def _call_generate(
        model_name: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout: int,
        **kwargs: object,
    ):
        if model_name == "bad-model":
            raise RuntimeError("boom")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    monkeypatch.setattr(provider_module, "_call_generate", _call_generate)
    provider = provider_module.LiteLLMProvider()

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await provider.generate(prompt="hola", model="bad-model")

    # El breaker del modelo malo está abierto; el otro modelo sigue disponible.
    good = await provider.generate(prompt="hola", model="good-model")
    assert good.content == "ok"
    with pytest.raises(Exception) as exc_info:
        await provider.generate(prompt="hola", model="bad-model")
    assert "Circuit breaker is OPEN" in str(exc_info.value)


def test_fallback_model_uses_own_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """El modelo de fallback usa su base/key propias; el resto, las primarias."""
    from src.core.config import get_settings
    from src.infrastructure.llm import provider as provider_module

    settings = get_settings().model_copy(
        update={
            "LITELLM_API_BASE": "https://api.novita.ai/openai",
            "LITELLM_API_KEY": SecretStr("novita-key"),
            "GATEWAY_FALLBACK_MODEL": "openai/deepseek-ai/DeepSeek-V4.1-Flash",
            "GATEWAY_FALLBACK_API_BASE": "https://api.deepinfra.com/v1/openai",
            "GATEWAY_FALLBACK_API_KEY": SecretStr("deepinfra-key"),
        }
    )
    monkeypatch.setattr(provider_module, "get_settings", lambda: settings)

    assert provider_module._get_llm_kwargs(settings.GATEWAY_FALLBACK_MODEL) == {
        "api_key": "deepinfra-key",
        "api_base": "https://api.deepinfra.com/v1/openai",
    }
    assert provider_module._get_llm_kwargs(settings.LITELLM_DEFAULT_MODEL) == {
        "api_key": "novita-key",
        "api_base": "https://api.novita.ai/openai",
    }

    # Sin key propia, el fallback cae a las credenciales primarias.
    without_key = settings.model_copy(update={"GATEWAY_FALLBACK_API_KEY": None})
    monkeypatch.setattr(provider_module, "get_settings", lambda: without_key)
    assert provider_module._get_llm_kwargs(without_key.GATEWAY_FALLBACK_MODEL) == {
        "api_key": "novita-key",
        "api_base": "https://api.novita.ai/openai",
    }
