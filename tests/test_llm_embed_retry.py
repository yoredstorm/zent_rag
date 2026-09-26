# =============================================================================
# Embeddings — retry acotado ante fallos transitorios del proveedor
# =============================================================================
# Caso real (2026-09-26): Novita devolvió 429 «server overload» en la ruta de
# embeddings. `Provider.embed` hacía UNA sola llamada y propagaba el error, así
# que `search_knowledge` se quedaba sin fragmentos y el run abstenía. El retry
# global de LiteLLM no ayudaba: `litellm.num_retries` quedaba en None en runtime
# aunque el módulo lo asignara al importar.
#
# Hermético: nunca se llama al proveedor, se reemplaza `aembedding`.
# =============================================================================
from __future__ import annotations

from typing import Any

import pytest

from src.core.config import get_settings
from src.infrastructure.llm import provider as provider_module
from src.infrastructure.llm.provider import (
    _embed_backoff_seconds,
    _is_transient_embed_error,
)

OVERLOAD = (
    "litellm.RateLimitError: RateLimitError: OpenAIException - Error code: 429 - "
    "{'message': 'server overload, please try again later', 'type': 'server_overload'}"
)


class _ProviderError(RuntimeError):
    """Error del proveedor simulado: el tipo real lo pone LiteLLM."""


class _Provider:
    """Instancia del provider real sin pasar por su `__init__`.

    El retry vive en `LiteLLMProvider.embed` y no depende de la construcción, así
    que el test no toca métricas ni estado de la clase.
    """

    def __init__(self) -> None:
        self.embed = provider_module.LiteLLMProvider.embed.__get__(self)


def _embedding_response(count: int = 1) -> Any:
    class _Item:
        def __getitem__(self, key: str) -> Any:
            assert key == "embedding"
            return [0.0] * 1024

    class _Response:
        data = [_Item() for _ in range(count)]

    return _Response()


@pytest.fixture
def hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin esperas reales: el test mide la política, no el reloj.

    Se parchea `get_settings` en el módulo del provider (`embed` lo resuelve por
    su namespace) en vez de tocar variables de entorno: así el valor que ve el
    código bajo prueba es exactamente el que declara el test.
    """

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(provider_module.asyncio, "sleep", _no_sleep)
    _install_settings(monkeypatch, LITELLM_EMBED_BACKOFF_SECONDS=0.0, LITELLM_EMBED_TOTAL_BUDGET_SECONDS=60.0)


def _install_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    base = get_settings()
    monkeypatch.setattr(
        provider_module, "get_settings", lambda: base.model_copy(update=overrides)
    )


def test_marcadores_de_fallo_transitorio() -> None:
    assert _is_transient_embed_error(Exception(OVERLOAD))
    assert _is_transient_embed_error(Exception("connection reset by peer"))
    assert _is_transient_embed_error(Exception("Request timed out"))
    assert _is_transient_embed_error(Exception("503 Service Unavailable"))
    # Un error de payload no se reintenta: reintentarlo no lo arregla.
    assert not _is_transient_embed_error(Exception("invalid input: too many tokens"))


def test_backoff_crece_con_jitter() -> None:
    primero = [_embed_backoff_seconds(1, 1.0) for _ in range(50)]
    cuarto = [_embed_backoff_seconds(4, 1.0) for _ in range(50)]
    assert all(0.5 <= value <= 1.0 for value in primero)
    assert all(0.5 <= value <= 8.0 for value in cuarto)
    # Jitter: no todos los intentos esperan lo mismo (evita reintentos en manada).
    assert len(set(primero)) > 1


@pytest.mark.asyncio
async def test_reintenta_y_termina_bien_tras_un_429(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    intentos: list[int] = []

    async def fake_aembedding(**_kwargs: Any) -> Any:
        intentos.append(1)
        if len(intentos) == 1:
            raise _ProviderError(OVERLOAD)
        return _embedding_response(1)

    monkeypatch.setattr(provider_module, "aembedding", fake_aembedding)
    vector = await _Provider().embed("categoria 31 byte 105")

    assert len(intentos) == 2
    assert isinstance(vector, list) and len(vector) == 1024


@pytest.mark.asyncio
async def test_apaga_el_retry_interno_de_litellm(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    """Sin esto, el retry de LiteLLM se multiplica con el nuestro (2×2)."""
    capturado: dict[str, Any] = {}

    async def fake_aembedding(**kwargs: Any) -> Any:
        capturado.update(kwargs)
        return _embedding_response(1)

    monkeypatch.setattr(provider_module, "aembedding", fake_aembedding)
    await _Provider().embed("categoria 31")
    assert capturado["num_retries"] == 0


@pytest.mark.asyncio
async def test_se_rinde_al_agotar_los_reintentos(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    intentos: list[int] = []

    async def fake_aembedding(**_kwargs: Any) -> Any:
        intentos.append(1)
        raise _ProviderError(OVERLOAD)

    monkeypatch.setattr(provider_module, "aembedding", fake_aembedding)
    _install_settings(
        monkeypatch,
        LITELLM_EMBED_BACKOFF_SECONDS=0.0,
        LITELLM_EMBED_TOTAL_BUDGET_SECONDS=60.0,
        LITELLM_EMBED_MAX_RETRIES=1,
    )
    with pytest.raises(_ProviderError):
        await _Provider().embed("categoria 31")
    # 1 intento + 1 reintento configurado, no infinitos.
    assert len(intentos) == 2


@pytest.mark.asyncio
async def test_no_reintenta_un_error_no_transitorio(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    intentos: list[int] = []

    async def fake_aembedding(**_kwargs: Any) -> Any:
        intentos.append(1)
        raise _ProviderError("invalid request: input must be a non-empty string")

    monkeypatch.setattr(provider_module, "aembedding", fake_aembedding)
    with pytest.raises(_ProviderError):
        await _Provider().embed("categoria 31")
    assert len(intentos) == 1


@pytest.mark.asyncio
async def test_el_presupuesto_corta_los_reintentos(
    monkeypatch: pytest.MonkeyPatch, hermetic: None
) -> None:
    """Un proveedor caído no puede comerse el turno entero a reintentos."""
    intentos: list[int] = []

    async def fake_aembedding(**_kwargs: Any) -> Any:
        intentos.append(1)
        raise _ProviderError(OVERLOAD)

    class _Clock:
        """Reloj falso: cada lectura avanza más que el presupuesto entero."""

        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            self.now += 5.0
            return self.now

    monkeypatch.setattr(provider_module, "aembedding", fake_aembedding)
    monkeypatch.setattr(provider_module.time, "perf_counter", _Clock())
    _install_settings(
        monkeypatch,
        LITELLM_EMBED_BACKOFF_SECONDS=0.0,
        LITELLM_EMBED_MAX_RETRIES=5,
        LITELLM_EMBED_TOTAL_BUDGET_SECONDS=1.0,
    )
    with pytest.raises(_ProviderError):
        await _Provider().embed("categoria 31")
    assert len(intentos) == 1
