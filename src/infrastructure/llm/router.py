# =============================================================================
# AI Gateway — virtual model aliases → real LiteLLM models + one fallback
# =============================================================================
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.core.config import get_settings
from src.core.domain.entities import LLMResponse
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

ROUTE_ALIASES = ("zent-fast", "zent-cheap", "zent-default", "zent-quality")

GenerateFn = Callable[..., Awaitable[LLMResponse]]

#: Retry corto para errores transitorios del proveedor (429 / overloaded).
_TRANSIENT_RETRY_SECONDS = 1.5


def _retryable_provider_error(exc: Exception) -> bool:
    """429/overloaded transitorio. Un circuit breaker abierto no se reintenta."""
    name = type(exc).__name__.lower()
    if "circuitbreaker" in name:
        return False
    if "ratelimit" in name or "overloaded" in name or "timeout" in name:
        return True
    if getattr(exc, "status_code", None) == 429:
        return True
    message = str(exc).lower()
    return "429" in message or "model busy" in message or "overloaded" in message


@dataclass(frozen=True, kw_only=True)
class ResolvedRoute:
    primary: str
    fallback: str | None
    alias: str | None

    def candidates(self) -> list[str]:
        names = [self.primary]
        if self.fallback and self.fallback != self.primary:
            names.append(self.fallback)
        return names


def list_route_catalog() -> list[dict[str, str]]:
    return [
        {
            "name": "zent-cheap",
            "description": "Ruta económica (primary configurable).",
        },
        {
            "name": "zent-default",
            "description": "Ruta por defecto de la plataforma.",
        },
        {
            "name": "zent-quality",
            "description": "Ruta de mayor calidad (primary configurable).",
        },
    ]


def resolve_route(
    requested: str | None = None,
    *,
    org_override: str | None = None,
    primary_override: str | None = None,
    fallback_override: str | None = None,
) -> ResolvedRoute:
    settings = get_settings()
    default_model = settings.LITELLM_DEFAULT_MODEL
    configured_fallback = (fallback_override or settings.GATEWAY_FALLBACK_MODEL or "").strip()
    fallback = configured_fallback or None

    if org_override and org_override.strip():
        return ResolvedRoute(
            primary=org_override.strip(),
            fallback=fallback,
            alias="override",
        )

    name = (requested or "").strip()
    if primary_override:
        return ResolvedRoute(
            primary=primary_override,
            fallback=fallback,
            alias=name if name in ROUTE_ALIASES else None,
        )

    if name == "zent-fast":
        primary = (settings.GATEWAY_FAST_MODEL or "").strip() or default_model
        return ResolvedRoute(primary=primary, fallback=fallback, alias="zent-fast")
    if name == "zent-cheap":
        primary = (settings.GATEWAY_CHEAP_MODEL or "").strip() or default_model
        return ResolvedRoute(primary=primary, fallback=fallback, alias="zent-cheap")
    if name == "zent-quality":
        primary = (settings.GATEWAY_QUALITY_MODEL or "").strip() or default_model
        return ResolvedRoute(primary=primary, fallback=fallback, alias="zent-quality")
    if name == "zent-default" or not name:
        return ResolvedRoute(
            primary=default_model, fallback=fallback, alias="zent-default" if name else None
        )
    return ResolvedRoute(primary=name, fallback=fallback, alias=None)


async def generate_routed(
    generate: GenerateFn,
    *,
    prompt: str,
    route: ResolvedRoute,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    system_prompt: str | None = None,
) -> LLMResponse:
    """Try primary, then one fallback. Usage of the HTTP request is the success.

    Un 429/overloaded transitorio reintenta UNA vez el mismo modelo tras una
    pausa corta; si sigue fallando, pasa al fallback. El circuit breaker es por
    modelo: un primario caído no bloquea al fallback.
    """
    last_error: Exception | None = None
    for index, model in enumerate(route.candidates()):
        for retry in range(2):
            try:
                return await generate(
                    prompt,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_prompt=system_prompt,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Gateway model attempt failed",
                    model=model,
                    attempt=index + 1,
                    retry=retry,
                    has_fallback=index == 0 and len(route.candidates()) > 1,
                    error=str(exc),
                )
                if retry == 0 and _retryable_provider_error(exc):
                    await asyncio.sleep(_TRANSIENT_RETRY_SECONDS)
                    continue
                break
    assert last_error is not None
    raise last_error
