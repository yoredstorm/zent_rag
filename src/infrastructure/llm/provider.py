# =============================================================================
# LiteLLM Adapter — Orquestación de LLMs con trazabilidad completa
# =============================================================================
# LiteLLM actúa como proxy unificado para múltiples proveedores (OpenAI,
# Anthropic, Azure, Ollama, etc.) exponiendo una API compatible con OpenAI.
# Este adaptador envuelve las llamadas con métricas de latencia y tokens.
# =============================================================================
from __future__ import annotations

import asyncio
import random
import time

import litellm
from litellm import acompletion, aembedding
from litellm.types.utils import ModelResponse

from src.core.config import get_settings
from src.core.domain.entities import LLMResponse
from src.core.ports import EmbeddingProvider, LLMProvider
from src.core.runtime_info import describe_model_runtime
from src.infrastructure.observability.embedding_route import set_embedding_route
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    rag_embeddings_fallback_total,
    rag_embeddings_latency,
)
from src.infrastructure.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)

logger = get_logger(__name__)

# Configuración global de LiteLLM (se ejecuta una vez al importar)
_settings = get_settings()
litellm.set_verbose = False
litellm.drop_params = True  # Ignora params no soportados por el modelo destino
litellm.num_retries = _settings.LITELLM_MAX_RETRIES


def _get_llm_kwargs(model_name: str | None = None) -> dict:
    """Construye kwargs para LiteLLM desde Settings.

    El modelo de fallback puede vivir en otro proveedor: si coincide con
    `GATEWAY_FALLBACK_MODEL` y tiene key propia, usa su base y su key.
    """
    settings = get_settings()
    if (
        model_name
        and model_name == settings.GATEWAY_FALLBACK_MODEL
        and settings.GATEWAY_FALLBACK_API_KEY is not None
        and settings.GATEWAY_FALLBACK_API_KEY.get_secret_value()
    ):
        kwargs: dict = {"api_key": settings.GATEWAY_FALLBACK_API_KEY.get_secret_value()}
        if settings.GATEWAY_FALLBACK_API_BASE:
            kwargs["api_base"] = settings.GATEWAY_FALLBACK_API_BASE
        return kwargs
    kwargs = {}
    if settings.LITELLM_API_BASE:
        kwargs["api_base"] = settings.LITELLM_API_BASE
    if settings.LITELLM_API_KEY:
        kwargs["api_key"] = settings.LITELLM_API_KEY.get_secret_value()
    return kwargs


def _thinking_kwargs() -> dict:
    """Apaga el thinking del modelo cuando el gateway lo soporta.

    Los modelos de razonamiento (p. ej. Novita/DeepSeek) emiten
    `reasoning_content` oculto que cuenta dentro de `max_tokens`: con presupuestos
    chicos el tope se consume pensando y la respuesta visible queda cortada a
    mitad de frase. `chat_template_kwargs.thinking=false` lo desactiva sin tocar
    el resto de la generacion. Default apagado: no cambia otros despliegues.
    """
    if not bool(getattr(get_settings(), "LLM_DISABLE_THINKING", False)):
        return {}
    return {"extra_body": {"chat_template_kwargs": {"thinking": False}}}


#: Marcadores de un fallo TRANSITORIO del proveedor. Un 429 por saturación o un
#: 5xx se reintenta; un 400 por payload inválido no.
_TRANSIENT_EMBED_MARKERS = (
    "rate limit",
    "ratelimiterror",
    "server overload",
    "overloaded",
    "try again",
    "temporarily",
    "timeout",
    "timed out",
    "connection",
    "service unavailable",
    "internal server error",
    "bad gateway",
    "502",
    "503",
    "504",
)


def _is_transient_embed_error(exc: BaseException) -> bool:
    """True si vale la pena reintentar el embedding.

    LiteLLM expone excepciones propias (`RateLimitError`, `Timeout`,
    `APIConnectionError`, `ServiceUnavailableError`), pero un proveedor
    compatible OpenAI puede devolver un 429 disfrazado de `OpenAIError`, así que
    la comprobación por tipo se completa con los marcadores del mensaje.
    """
    for name in (
        "RateLimitError",
        "Timeout",
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
    ):
        cls = getattr(litellm, name, None) or getattr(litellm.exceptions, name, None)
        if cls is not None and isinstance(exc, cls):
            return True
    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT_EMBED_MARKERS)


def _embed_backoff_seconds(attempt: int, base: float) -> float:
    """Backoff exponencial con jitter completo (evita reintentos sincronizados)."""
    ceiling = base * (2 ** max(0, attempt - 1))
    return random.uniform(base * 0.5, ceiling)  # noqa: S311 - jitter, no crypto


#: Marcadores de un fallo del PROVEEDOR (no del payload): credenciales, cuota o
#: cuenta. Un respaldo con otra cuenta sí puede resolverlo, igual que un 429/5xx.
_CREDENTIAL_EMBED_MARKERS = (
    "unauthorized",
    "authentication",
    "invalid api key",
    "api key",
    "forbidden",
    "not allowed",
    "permission",
    "quota",
    "insufficient",
    "billing",
    "balance",
    "credit",
    "401",
    "402",
    "403",
)


def _is_provider_embed_error(exc: BaseException) -> bool:
    """True si el fallo es del proveedor: el respaldo vale la pena.

    Un 400 por payload inválido fallaría igual en el respaldo, así que no se
    intenta (sería un reintento disfrazado).
    """
    if _is_transient_embed_error(exc):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _CREDENTIAL_EMBED_MARKERS)


def _get_embed_fallback_kwargs(settings) -> dict | None:
    """Kwargs del proveedor de respaldo. None = respaldo apagado.

    Se apaga si no hay modelo o key: mejor fallar con el primario que intentar
    un endpoint sin credenciales y cambiar el error original.
    """
    model = str(getattr(settings, "EMBEDDING_FALLBACK_MODEL", "") or "").strip()
    key = getattr(settings, "EMBEDDING_FALLBACK_API_KEY", None)
    if not model or key is None or not key.get_secret_value():
        return None
    kwargs: dict = {"model": model}
    base = getattr(settings, "EMBEDDING_FALLBACK_API_BASE", None)
    if base:
        kwargs["api_base"] = base
    kwargs["api_key"] = key.get_secret_value()
    return kwargs


class EmbeddingDimensionMismatchError(RuntimeError):
    """El vector del respaldo no coincide con VECTOR_DIMENSION: no se indexa."""


async def _call_generate(
    model_name: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    timeout: int,
    **kwargs: dict[str, object],
) -> ModelResponse:
    return await acompletion(
        model=model_name,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        **kwargs,
    )


_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)


class LiteLLMProvider(LLMProvider, EmbeddingProvider):
    """Implementación unificada de LLMProvider y EmbeddingProvider vía LiteLLM."""

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        from src.infrastructure.llm.router import generate_routed, resolve_route

        route = resolve_route(requested=model)
        return await generate_routed(
            self._generate_once,
            prompt=prompt,
            route=route,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=system_prompt,
        )

    async def _generate_once(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        settings = get_settings()
        model_name = model or settings.LITELLM_DEFAULT_MODEL
        llm_kwargs = {**_get_llm_kwargs(model_name), **_thinking_kwargs()}

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.perf_counter()
        try:
            response = await _circuit_breaker.call(
                "generate",
                _call_generate,
                model_name=model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=settings.LITELLM_TIMEOUT_SECONDS,
                **llm_kwargs,
            )
        except CircuitBreakerOpenError:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "LLM generation rejected by circuit breaker (circuit is OPEN)",
                model=model_name,
                latency_ms=round(latency_ms, 2),
            )
            raise
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "LLM generation failed",
                model=model_name,
                llm_latency_ms=round(latency_ms, 2),
                error=str(exc),
                exc_info=True,
            )
            raise

        latency_ms = (time.perf_counter() - start) * 1000
        usage = response.usage or litellm.Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        content = response.choices[0].message.content or "" if response.choices else ""
        finish_reason = response.choices[0].finish_reason if response.choices else "error"

        llm_response = LLMResponse(
            content=content,
            model=model_name,
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
            latency_ms=round(latency_ms, 2),
            finish_reason=str(finish_reason),
        )

        logger.info(
            "LLM generation completed",
            model=model_name,
            total_tokens=llm_response.total_tokens,
            llm_latency_ms=llm_response.latency_ms,
            finish_reason=llm_response.finish_reason,
        )

        return llm_response

    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ):
        from src.infrastructure.llm.router import resolve_route

        settings = get_settings()
        candidates = resolve_route(requested=model).candidates()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.perf_counter()
        for attempt, model_name in enumerate(candidates):
            llm_kwargs = {**_get_llm_kwargs(model_name), **_thinking_kwargs()}
            content_parts: list[str] = []
            usage = litellm.Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            finish_reason = "stop"
            emitted = False
            try:
                response = await _circuit_breaker.call(
                    "generate",
                    acompletion,
                    model=model_name,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=settings.LITELLM_TIMEOUT_SECONDS,
                    stream=True,
                    stream_options={"include_usage": True},
                    **llm_kwargs,
                )
                async for chunk in response:
                    choices = chunk.choices or []
                    if choices:
                        delta = choices[0].delta
                        piece = getattr(delta, "content", None) or ""
                        if piece:
                            content_parts.append(piece)
                            emitted = True
                            yield {"type": "delta", "text": piece}
                        if choices[0].finish_reason:
                            finish_reason = str(choices[0].finish_reason)
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage = chunk_usage
            except CircuitBreakerOpenError:
                logger.warning(
                    "LLM streaming generation rejected by circuit breaker (circuit is OPEN)",
                    model=model_name,
                )
                raise
            except Exception as exc:
                # Con tokens ya emitidos no hay failover posible: el cliente vio
                # texto y cambiar de modelo duplicaría la respuesta.
                has_fallback = attempt + 1 < len(candidates)
                if emitted or not has_fallback:
                    logger.error(
                        "LLM streaming generation failed",
                        model=model_name,
                        emitted=emitted,
                        error=str(exc),
                        exc_info=True,
                    )
                    raise
                logger.warning(
                    "LLM streaming failed before first token; trying fallback model",
                    model=model_name,
                    fallback=candidates[attempt + 1],
                    error=str(exc)[:200],
                )
                continue

            latency_ms = (time.perf_counter() - start) * 1000
            yield {
                "type": "done",
                "content": "".join(content_parts),
                "model": model_name,
                "usage": {
                    "prompt_tokens": usage.prompt_tokens or 0,
                    "completion_tokens": usage.completion_tokens or 0,
                    "total_tokens": usage.total_tokens or 0,
                },
                "finish_reason": finish_reason,
                "latency_ms": round(latency_ms, 2),
            }
            return

    async def embed(
        self, text: str | list[str], model: str | None = None
    ) -> list[float] | list[list[float]]:
        """Embeddings con failover a un proveedor de respaldo.

        Fallo del PRIMARIO (429/5xx/timeout/credenciales): el respaldo toma la
        posta y ahí aplican los reintentos con backoff. Un error de payload no
        dispara respaldo (fallaría igual). La ruta aplicada queda disponible en
        `last_embedding_route()` para la traza del agente.
        """
        settings = get_settings()
        requested_model = model or settings.EMBEDDING_MODEL

        is_single = isinstance(text, str)
        texts = [text] if is_single else text

        primary_kwargs = _get_llm_kwargs()
        if requested_model.startswith("ollama/"):
            primary_kwargs.pop("api_base", None)
            primary_kwargs.pop("api_key", None)

        # Un modelo local no tiene respaldo cloud (otra dimensión, otro índice).
        # Si el pedido ya ES el del respaldo, tampoco hay failover consigo mismo.
        fallback = _get_embed_fallback_kwargs(settings)
        if fallback is not None and (
            requested_model.startswith("ollama/") or requested_model == fallback["model"]
        ):
            fallback = None

        route = "primary"
        call_model = requested_model
        call_kwargs = dict(primary_kwargs)
        start = time.perf_counter()
        route_start = start
        route_attempt = 0

        while True:
            route_attempt += 1
            try:
                response = await aembedding(
                    model=call_model,
                    input=texts,
                    timeout=settings.LITELLM_TIMEOUT_SECONDS,
                    # Nuestro retry es el único: se apaga el de LiteLLM para no
                    # multiplicar intentos (2×2) y para que el backoff quede
                    # bajo control y sea observable.
                    num_retries=0,
                    **call_kwargs,
                )
                break
            except Exception as exc:
                retriable = _is_transient_embed_error(exc)
                if (
                    route == "primary"
                    and fallback is not None
                    and _is_provider_embed_error(exc)
                ):
                    # Failover inmediato: un primario caído no se reintenta; el
                    # presupuesto y el backoff pasan al respaldo.
                    route = "fallback"
                    route_attempt = 0
                    route_start = time.perf_counter()
                    call_model = fallback["model"]
                    call_kwargs = {k: v for k, v in fallback.items() if k != "model"}
                    logger.warning(
                        "Embedding primary failed; switching to fallback provider",
                        model=requested_model,
                        fallback_model=call_model,
                        error=str(exc)[:180],
                    )
                    continue

                elapsed = time.perf_counter() - route_start
                budget_left = settings.LITELLM_EMBED_TOTAL_BUDGET_SECONDS - elapsed
                if (
                    not retriable
                    or route_attempt > settings.LITELLM_EMBED_MAX_RETRIES
                    or budget_left <= 0
                ):
                    latency_ms = (time.perf_counter() - start) * 1000
                    if route == "fallback":
                        rag_embeddings_fallback_total.labels(
                            from_model=requested_model,
                            to_model=call_model,
                            outcome="error",
                        ).inc()
                    logger.error(
                        "Embedding generation failed",
                        model=call_model,
                        route=route,
                        fallback_used=route == "fallback",
                        embedding_latency_ms=round(latency_ms, 2),
                        batch_size=len(texts),
                        attempts=route_attempt,
                        transient=retriable,
                        error=str(exc),
                        exc_info=True,
                    )
                    raise
                delay = min(
                    _embed_backoff_seconds(
                        route_attempt, settings.LITELLM_EMBED_BACKOFF_SECONDS
                    ),
                    max(0.0, budget_left),
                )
                logger.warning(
                    "Embedding generation retrying after transient provider failure",
                    model=call_model,
                    route=route,
                    attempt=route_attempt,
                    max_attempts=settings.LITELLM_EMBED_MAX_RETRIES + 1,
                    delay_seconds=round(delay, 3),
                    error=str(exc)[:180],
                )
                await asyncio.sleep(delay)

        latency_ms = (time.perf_counter() - start) * 1000
        rag_embeddings_latency.labels(
            organization_id="unknown", model=call_model
        ).observe(latency_ms / 1000)

        embeddings = [d["embedding"] for d in response.data]  # type: ignore[union-attr]

        if route == "fallback":
            expected = int(getattr(settings, "VECTOR_DIMENSION", 0) or 0)
            if expected and embeddings and len(embeddings[0]) != expected:
                rag_embeddings_fallback_total.labels(
                    from_model=requested_model,
                    to_model=call_model,
                    outcome="error",
                ).inc()
                raise EmbeddingDimensionMismatchError(
                    f"Embedding fallback devolvió dimensión {len(embeddings[0])}; "
                    f"se esperaba {expected} (VECTOR_DIMENSION). No se indexa."
                )
            rag_embeddings_fallback_total.labels(
                from_model=requested_model,
                to_model=call_model,
                outcome="ok",
            ).inc()

        runtime = describe_model_runtime(call_model, call_kwargs.get("api_base"))
        set_embedding_route(
            {
                "route": route,
                "fallback": route == "fallback",
                "model": call_model,
                "provider": runtime["provider"],
                "provider_label": runtime["provider_label"],
                "served_model": runtime["served_model"],
                "base_url_host": runtime["host"],
            }
        )

        logger.info(
            "Embeddings generated",
            model=call_model,
            route=route,
            fallback_used=route == "fallback",
            batch_size=len(texts),
            embedding_latency_ms=round(latency_ms, 2),
        )
        return embeddings[0] if is_single else embeddings

    async def embed_late_chunking(
        self, chunks: list[str], model: str | None = None
    ) -> list[list[float]]:
        """Late chunking REAL: un request con los chunks del MISMO documento.

        El API (Jina-style) contextualiza cada chunk con el documento completo
        cuando `late_chunking=true`. Solo se invoca si el registry declaró la
        capacidad y este método existe; cualquier error lo maneja el caller
        (fallback a contextual embedding). Nunca se simula.
        """
        texts = [str(chunk) for chunk in chunks or ()]
        if not texts:
            return []
        settings = get_settings()
        requested_model = model or settings.EMBEDDING_MODEL
        kwargs = _get_llm_kwargs()
        if requested_model.startswith("ollama/"):
            kwargs.pop("api_base", None)
            kwargs.pop("api_key", None)
        response = await aembedding(
            model=requested_model,
            input=texts,
            timeout=settings.LITELLM_TIMEOUT_SECONDS,
            num_retries=0,
            late_chunking=True,
            **kwargs,
        )
        return [list(item["embedding"]) for item in response.data]  # type: ignore[union-attr]

    async def rerank(
        self,
        query: str,
        documents: list[str],
        model: str | None = None,
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        settings = get_settings()
        model_name = model or settings.RAG_CROSS_ENCODER_MODEL
        if not documents or not model_name:
            return []
        if not hasattr(litellm, "arerank"):
            logger.warning("LiteLLM does not support rerank; returning empty")
            return []

        start = time.perf_counter()
        try:
            response = await litellm.arerank(  # type: ignore[attr-defined]
                model=model_name,
                query=query,
                documents=documents,
                top_n=top_n,
                timeout=settings.LITELLM_TIMEOUT_SECONDS,
                **_get_llm_kwargs(),
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Rerank call failed",
                model=model_name,
                rerank_latency_ms=round(latency_ms, 2),
                error=str(exc),
                exc_info=True,
            )
            raise

        latency_ms = (time.perf_counter() - start) * 1000
        ranked = [(int(r["index"]), float(r["relevance_score"])) for r in response.results]
        ranked.sort(key=lambda x: x[1], reverse=True)
        logger.info(
            "Rerank complete",
            model=model_name,
            documents=len(documents),
            ranked=len(ranked),
            rerank_latency_ms=round(latency_ms, 2),
        )
        return ranked
