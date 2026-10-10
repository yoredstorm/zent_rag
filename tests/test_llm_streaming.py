# =============================================================================
# Streaming — failover primario→DeepInfra antes del primer token + extracción
# del texto visible cuando el modelo responde JSON (`{"answer": "…"}`).
# =============================================================================
# Hermético: nunca se llama a un proveedor, se reemplaza `acompletion`.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from src.agents.runtime.agent_runtime import AgentRuntime, _AnswerStreamExtractor
from src.core.config import get_settings
from src.infrastructure.llm import provider as provider_module
from src.infrastructure.llm import router as router_module

NOVITA_BASE = "https://api.novita.ai/openai"
DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"
PRIMARY = "openai/deepseek/deepseek-v4.1-flash"
FALLBACK = "openai/deepseek-ai/DeepSeek-V4.1-Flash"


def _install_settings(monkeypatch: pytest.MonkeyPatch, **extra: Any) -> None:
    settings = get_settings().model_copy(
        update={
            "LITELLM_API_BASE": NOVITA_BASE,
            "LITELLM_API_KEY": SecretStr("novita-key"),
            "LITELLM_DEFAULT_MODEL": PRIMARY,
            "GATEWAY_FALLBACK_MODEL": FALLBACK,
            "GATEWAY_FALLBACK_API_BASE": DEEPINFRA_BASE,
            "GATEWAY_FALLBACK_API_KEY": SecretStr("deepinfra-key"),
            **extra,
        }
    )
    monkeypatch.setattr(provider_module, "get_settings", lambda: settings)
    monkeypatch.setattr(router_module, "get_settings", lambda: settings)


@pytest.fixture(autouse=True)
def _reset_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """El circuito es de proceso: un test con fallos no debe abrir el del otro."""
    breaker = provider_module._circuit_breaker
    monkeypatch.setattr(breaker, "_states", {})
    monkeypatch.setattr(breaker, "_failure_counts", {})
    monkeypatch.setattr(breaker, "_open_since", {})


async def _stream(chunks: list[Any]):
    """Iterador async estilo `acompletion(stream=True)`; errores van en la lista."""
    for chunk in chunks:
        if isinstance(chunk, BaseException):
            raise chunk
        yield chunk


def _delta_chunk(text: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)],
        usage=None,
    )


def _usage_chunk() -> Any:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
    )


@pytest.mark.asyncio
async def test_stream_failover_antes_del_primer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_settings(monkeypatch)
    bases: list[str] = []

    async def fake_acompletion(**kwargs: Any):
        bases.append(str(kwargs.get("api_base") or ""))
        if kwargs.get("api_base") == NOVITA_BASE:
            return _stream([RuntimeError("novita caído")])  # falla en el 1er __anext__
        return _stream([_delta_chunk("Hola "), _delta_chunk("mundo"), _usage_chunk()])

    monkeypatch.setattr(provider_module, "acompletion", fake_acompletion)

    events = [
        event
        async for event in provider_module.LiteLLMProvider().generate_stream(prompt="hola")
    ]

    deltas = [event["text"] for event in events if event["type"] == "delta"]
    done = next(event for event in events if event["type"] == "done")
    assert deltas == ["Hola ", "mundo"]
    assert done["model"] == FALLBACK
    assert done["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert bases == [NOVITA_BASE, DEEPINFRA_BASE]


@pytest.mark.asyncio
async def test_stream_no_failover_con_tokens_ya_emitidos(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_settings(monkeypatch)
    bases: list[str] = []

    async def fake_acompletion(**kwargs: Any):
        bases.append(str(kwargs.get("api_base") or ""))
        return _stream([_delta_chunk("parcial"), RuntimeError("cortado a mitad")])

    monkeypatch.setattr(provider_module, "acompletion", fake_acompletion)

    stream = provider_module.LiteLLMProvider().generate_stream(prompt="hola")
    assert await anext(stream) == {"type": "delta", "text": "parcial"}
    with pytest.raises(RuntimeError):
        await anext(stream)
    assert bases == [NOVITA_BASE]


@pytest.mark.asyncio
async def test_stream_failover_con_breaker_abierto_del_primario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Breaker del primario abierto: el stream prueba el fallback, no aborta."""
    _install_settings(monkeypatch)
    breaker = provider_module._circuit_breaker
    for _ in range(3):
        breaker._on_failure(f"generate:{PRIMARY}")

    bases: list[str] = []

    async def fake_acompletion(**kwargs: Any):
        bases.append(str(kwargs.get("api_base") or ""))
        return _stream([_delta_chunk("Hola"), _usage_chunk()])

    monkeypatch.setattr(provider_module, "acompletion", fake_acompletion)

    events = [
        event
        async for event in provider_module.LiteLLMProvider().generate_stream(prompt="hola")
    ]
    done = next(event for event in events if event["type"] == "done")
    assert done["model"] == FALLBACK
    assert bases == [DEEPINFRA_BASE]


def test_thinking_no_se_pasa_si_esta_apagado(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_settings(monkeypatch, LLM_DISABLE_THINKING=False)

    assert provider_module._thinking_kwargs() == {}


def test_thinking_kwargs_con_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_settings(monkeypatch, LLM_DISABLE_THINKING=True)

    assert provider_module._thinking_kwargs() == {
        "extra_body": {"chat_template_kwargs": {"thinking": False}}
    }


@pytest.mark.asyncio
async def test_stream_pasa_thinking_apagado_al_proveedor(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_settings(monkeypatch, LLM_DISABLE_THINKING=True)
    seen: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any):
        seen.update(kwargs)
        return _stream([_delta_chunk("ok"), _usage_chunk()])

    monkeypatch.setattr(provider_module, "acompletion", fake_acompletion)

    _ = [event async for event in provider_module.LiteLLMProvider().generate_stream(prompt="hola")]

    assert seen["extra_body"] == {"chat_template_kwargs": {"thinking": False}}


def test_answer_extractor_decodifica_json_por_partes() -> None:
    extractor = _AnswerStreamExtractor()
    chunks = ['{"ans', 'wer": "Hola', ' \\"mundo\\"', "\\nli", "nea \\u00", "e9", '"}']
    out = "".join(extractor.feed(chunk) for chunk in chunks)
    assert out == 'Hola "mundo"\nlinea é'


def test_answer_extractor_ignora_tool_calls() -> None:
    extractor = _AnswerStreamExtractor()
    out = "".join(
        extractor.feed(part)
        for part in ['{"tool"', ': "search_knowledge", "arguments": {}}']
    )
    assert out == ""


class _FakeStreamLLM:
    """Provider falso: sólo `generate_stream`; `generate` no debe usarse."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def generate_stream(self, **_kwargs: Any):
        for event in self._events:
            yield event

    async def generate(self, **_kwargs: Any):
        raise AssertionError("no debe caer a generate con stream sano")


def _runtime_with(events: list[dict[str, Any]]) -> AgentRuntime:
    runtime = object.__new__(AgentRuntime)
    runtime._llm = _FakeStreamLLM(events)
    return runtime


@pytest.mark.asyncio
async def test_stream_response_emite_solo_el_valor_de_answer() -> None:
    runtime = _runtime_with(
        [
            {"type": "delta", "text": '{"answer": "'},
            {"type": "delta", "text": "Hola"},
            {"type": "delta", "text": '"}'},
            {
                "type": "done",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        ]
    )
    seen: list[str] = []

    async def on_delta(text: str) -> None:
        seen.append(text)

    resp = await runtime._stream_response(
        prompt="p", model="m", max_tokens=10, temperature=0.0, on_delta=on_delta
    )
    assert seen == ["Hola"]
    assert resp.content == '{"answer": "Hola"}'
    assert resp.total_tokens == 2


@pytest.mark.asyncio
async def test_stream_response_emite_prosa_tal_cual() -> None:
    runtime = _runtime_with(
        [
            {"type": "delta", "text": "Hola "},
            {"type": "delta", "text": "mundo"},
            {"type": "done", "usage": {}},
        ]
    )
    seen: list[str] = []

    async def on_delta(text: str) -> None:
        seen.append(text)

    await runtime._stream_response(
        prompt="p", model="m", max_tokens=10, temperature=0.0, on_delta=on_delta
    )
    assert seen == ["Hola ", "mundo"]
