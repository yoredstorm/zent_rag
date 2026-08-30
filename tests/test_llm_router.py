# =============================================================================
# AI Gateway router — aliases, org override, primary → fallback
# =============================================================================
from __future__ import annotations

import pytest

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
