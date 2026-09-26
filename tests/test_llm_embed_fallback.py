# =============================================================================
# Embeddings — failover a DeepInfra cuando Novita falla
# =============================================================================
# Caso real (2026-09-26): Novita devolvió 429 «server overload» de forma
# sostenida. `embed` reintentaba y terminaba sin vectores, así que la búsqueda
# quedaba vacía. Con respaldo configurado, el PRIMER fallo de proveedor pasa a
# DeepInfra (mismo BGE-m3, misma dimensión) y la ruta aplicada queda visible en
# el flow del agente vía `last_embedding_route()`.
#
# Hermético: nunca se llama al proveedor, se reemplaza `aembedding`.
# =============================================================================
from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from src.core.config import get_settings
from src.infrastructure.llm import provider as provider_module
from src.infrastructure.llm.provider import (
    EmbeddingDimensionMismatchError,
    _get_embed_fallback_kwargs,
    _is_provider_embed_error,
)
from src.infrastructure.observability.embedding_route import last_embedding_route

OVERLOAD = (
    "litellm.RateLimitError: RateLimitError: OpenAIException - Error code: 429 - "
    "{'message': 'server overload, please try again later', 'type': 'server_overload'}"
)
PAYLOAD = (
    "litellm.BadRequestError: BadRequestError: OpenAIException - Error code: 400 - "
    "invalid input: too many tokens"
)
DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"


class _ProviderError(RuntimeError):
    """Error del proveedor simulado: el tipo real lo pone LiteLLM."""


class _Provider:
    """Instancia del provider real sin pasar por su `__init__`."""

    def __init__(self) -> None:
        self.embed = provider_module.LiteLLMProvider.embed.__get__(self)


def _embedding_response(count: int = 1, dim: int = 1024) -> Any:
    class _Item:
        def __getitem__(self, key: str) -> Any:
            assert key == "embedding"
            return [0.0] * dim

    class _Response:
        data = [_Item() for _ in range(count)]

    return _Response()


def _install_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    base = get_settings()
    defaults: dict[str, Any] = {
        "LITELLM_API_BASE": "https://api.novita.ai/openai",
        "EMBEDDING_MODEL": "openai/baai/bge-m3",
        "VECTOR_DIMENSION": 1024,
        "EMBEDDING_FALLBACK_MODEL": "openai/BAAI/bge-m3",
        "EMBEDDING_FALLBACK_API_BASE": DEEPINFRA_BASE,
        "EMBEDDING_FALLBACK_API_KEY": SecretStr("deepinfra-test-key"),
        "LITELLM_EMBED_MAX_RETRIES": 2,
        "LITELLM_EMBED_BACKOFF_SECONDS": 0.0,
        "LITELLM_EMBED_TOTAL_BUDGET_SECONDS": 60.0,
    }
    defaults.update(overrides)
    monkeypatch.setattr(
        provider_module, "get_settings", lambda: base.model_copy(update=defaults)
    )


@pytest.fixture
def hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin esperas reales: el test mide la política, no el reloj."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(provider_module.asyncio, "sleep", _no_sleep)
    _install_settings(monkeypatch)


def _fake_embedding(
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary: Any,
    fallback: Any = None,
) -> list[dict[str, Any]]:
    """Reemplaza `aembedding`: primario y respaldo se distinguen por `api_base`."""
    calls: list[dict[str, Any]] = []

    async def fake_aembedding(**kwargs: Any) -> Any:
        calls.append(kwargs)
        is_fallback = str(kwargs.get("api_base") or "") == DEEPINFRA_BASE
        behavior = fallback if is_fallback else primary
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior

    monkeypatch.setattr(provider_module, "aembedding", fake_aembedding)
    return calls


def test_marcadores_de_fallo_de_proveedor() -> None:
    assert _is_provider_embed_error(Exception(OVERLOAD))
    assert _is_provider_embed_error(Exception("Error code: 401 - invalid api key"))
    assert _is_provider_embed_error(Exception("quota exceeded for this account"))
    # Un error de payload fallaría igual en el respaldo: no lo dispara.
    assert not _is_provider_embed_error(Exception(PAYLOAD))


def test_fallback_kwargs_exige_key() -> None:
    base = get_settings()
    sin_key = base.model_copy(
        update={
            "EMBEDDING_FALLBACK_MODEL": "openai/BAAI/bge-m3",
            "EMBEDDING_FALLBACK_API_KEY": None,
        }
    )
    assert _get_embed_fallback_kwargs(sin_key) is None

    con_key = base.model_copy(
        update={
            "EMBEDDING_FALLBACK_MODEL": "openai/BAAI/bge-m3",
            "EMBEDDING_FALLBACK_API_BASE": DEEPINFRA_BASE,
            "EMBEDDING_FALLBACK_API_KEY": SecretStr("k"),
        }
    )
    assert _get_embed_fallback_kwargs(con_key) == {
        "model": "openai/BAAI/bge-m3",
        "api_base": DEEPINFRA_BASE,
        "api_key": "k",
    }


@pytest.mark.asyncio
async def test_failover_al_primer_fallo_del_primario(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    calls = _fake_embedding(
        monkeypatch,
        primary=_ProviderError(OVERLOAD),
        fallback=_embedding_response(),
    )
    vector = await _Provider().embed("categoria 31 byte 105")

    assert isinstance(vector, list) and len(vector) == 1024
    # El primario se intenta UNA vez; el respaldo toma la posta.
    assert len(calls) == 2
    assert calls[0]["model"] == "openai/baai/bge-m3"
    assert calls[1]["model"] == "openai/BAAI/bge-m3"
    assert calls[1]["api_base"] == DEEPINFRA_BASE
    assert calls[1]["api_key"] == "deepinfra-test-key"
    assert calls[1]["num_retries"] == 0

    route = last_embedding_route()
    assert route is not None
    assert route["fallback"] is True
    assert route["provider"] == "deepinfra"
    assert route["provider_label"] == "DeepInfra (hosted)"
    assert route["served_model"] == "BAAI/bge-m3"
    assert route["base_url_host"] == "api.deepinfra.com"


@pytest.mark.asyncio
async def test_el_respaldo_tambien_reintenta_y_se_rinde(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    _install_settings(monkeypatch, LITELLM_EMBED_MAX_RETRIES=1)
    calls = _fake_embedding(
        monkeypatch,
        primary=_ProviderError(OVERLOAD),
        fallback=_ProviderError("503 Service Unavailable"),
    )
    with pytest.raises(_ProviderError):
        await _Provider().embed("categoria 31")
    # 1 primario + 1 respaldo + 1 reintento del respaldo (MAX_RETRIES=1).
    assert len(calls) == 3
    assert calls[1]["api_base"] == DEEPINFRA_BASE
    assert calls[2]["api_base"] == DEEPINFRA_BASE


@pytest.mark.asyncio
async def test_error_de_payload_no_dispara_respaldo(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    calls = _fake_embedding(
        monkeypatch,
        primary=_ProviderError(PAYLOAD),
        fallback=_embedding_response(),
    )
    with pytest.raises(_ProviderError):
        await _Provider().embed("categoria 31")
    assert len(calls) == 1
    assert calls[0]["model"] == "openai/baai/bge-m3"


@pytest.mark.asyncio
async def test_sin_key_no_hay_respaldo(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    _install_settings(
        monkeypatch,
        EMBEDDING_FALLBACK_API_KEY=None,
        LITELLM_EMBED_MAX_RETRIES=0,
    )
    calls = _fake_embedding(monkeypatch, primary=_ProviderError(OVERLOAD))
    with pytest.raises(_ProviderError):
        await _Provider().embed("categoria 31")
    assert len(calls) == 1
    assert calls[0]["model"] == "openai/baai/bge-m3"


@pytest.mark.asyncio
async def test_dimension_del_respaldo_no_coincide(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    calls = _fake_embedding(
        monkeypatch,
        primary=_ProviderError(OVERLOAD),
        fallback=_embedding_response(dim=768),
    )
    with pytest.raises(EmbeddingDimensionMismatchError):
        await _Provider().embed("categoria 31")
    # No se indexa nada con la dimensión equivocada.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_modelo_local_no_tiene_respaldo(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    calls = _fake_embedding(monkeypatch, primary=_ProviderError("connection refused"))
    with pytest.raises(_ProviderError):
        await _Provider().embed("categoria 31", model="ollama/bge-m3")
    assert {call["model"] for call in calls} == {"ollama/bge-m3"}
    assert all("api_base" not in call for call in calls)


@pytest.mark.asyncio
async def test_trace_del_primario_cuando_no_hay_fallo(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    calls = _fake_embedding(monkeypatch, primary=_embedding_response())
    vector = await _Provider().embed("categoria 31")

    assert isinstance(vector, list) and len(vector) == 1024
    assert len(calls) == 1
    route = last_embedding_route()
    assert route is not None
    assert route["fallback"] is False
    assert route["provider"] == "novita"
    assert route["served_model"] == "baai/bge-m3"
