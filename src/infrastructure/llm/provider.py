# =============================================================================
# LiteLLM Adapter — Orquestación de LLMs con trazabilidad completa
# =============================================================================
# LiteLLM actúa como proxy unificado para múltiples proveedores (OpenAI,
# Anthropic, Azure, Ollama, etc.) exponiendo una API compatible con OpenAI.
# Este adaptador envuelve las llamadas con métricas de latencia y tokens.
# =============================================================================
from __future__ import annotations

import time

import litellm
from litellm import acompletion, aembedding
from litellm.types.utils import ModelResponse

from src.core.config import get_settings
from src.core.domain.entities import LLMResponse
from src.core.ports import EmbeddingProvider, LLMProvider
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import rag_embeddings_latency
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


def _get_llm_kwargs() -> dict:
    """Construye kwargs para LiteLLM desde Settings."""
    settings = get_settings()
    kwargs: dict = {}
    if settings.LITELLM_API_BASE:
        kwargs["api_base"] = settings.LITELLM_API_BASE
    if settings.LITELLM_API_KEY:
        kwargs["api_key"] = settings.LITELLM_API_KEY.get_secret_value()
    return kwargs


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
        llm_kwargs = _get_llm_kwargs()

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
        model_name = resolve_route(requested=model).primary
        llm_kwargs = _get_llm_kwargs()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.perf_counter()
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
        except CircuitBreakerOpenError:
            logger.warning(
                "LLM streaming generation rejected by circuit breaker (circuit is OPEN)",
                model=model_name,
            )
            raise
        except Exception as exc:
            logger.error(
                "LLM streaming generation failed to start",
                model=model_name,
                error=str(exc),
                exc_info=True,
            )
            raise

        content_parts: list[str] = []
        usage = litellm.Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        finish_reason = "stop"
        try:
            async for chunk in response:
                choices = chunk.choices or []
                if choices:
                    delta = choices[0].delta
                    piece = getattr(delta, "content", None) or ""
                    if piece:
                        content_parts.append(piece)
                        yield {"type": "delta", "text": piece}
                    if choices[0].finish_reason:
                        finish_reason = str(choices[0].finish_reason)
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage
        except Exception as exc:
            logger.error(
                "LLM streaming generation failed mid-stream",
                model=model_name,
                error=str(exc),
                exc_info=True,
            )
            raise

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

    async def embed(
        self, text: str | list[str], model: str | None = None
    ) -> list[float] | list[list[float]]:
        settings = get_settings()
        model_name = model or settings.EMBEDDING_MODEL

        is_single = isinstance(text, str)
        texts = [text] if is_single else text

        llm_kwargs = _get_llm_kwargs()
        if model_name.startswith("ollama/"):
            llm_kwargs.pop("api_base", None)
            llm_kwargs.pop("api_key", None)

        start = time.perf_counter()
        try:
            response = await aembedding(
                model=model_name,
                input=texts,
                timeout=settings.LITELLM_TIMEOUT_SECONDS,
                **llm_kwargs,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Embedding generation failed",
                model=model_name,
                embedding_latency_ms=round(latency_ms, 2),
                batch_size=len(texts),
                error=str(exc),
                exc_info=True,
            )
            raise

        latency_ms = (time.perf_counter() - start) * 1000
        rag_embeddings_latency.labels(
            organization_id="unknown", model=model_name
        ).observe(latency_ms / 1000)

        embeddings = [d["embedding"] for d in response.data]  # type: ignore[union-attr]

        logger.info(
            "Embeddings generated",
            model=model_name,
            batch_size=len(texts),
            embedding_latency_ms=round(latency_ms, 2),
        )

        return embeddings[0] if is_single else embeddings

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
