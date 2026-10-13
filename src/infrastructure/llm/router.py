# =============================================================================
# AI Gateway — virtual model aliases → real LiteLLM models + one fallback
# =============================================================================
from __future__ import annotations

import asyncio
import time
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
    """429/overloaded transitorio. Un rate limit explícito va al fallback ya."""
    name = type(exc).__name__.lower()
    if "circuitbreaker" in name:
        return False
    message = str(exc).lower()
    if "exceeded the request rate limit" in message or "rate limit exceeded" in message:
        # Cuota/rate limit del proveedor: reintentar en 1.5s solo lo empeora.
        return False
    if "ratelimit" in name or "overloaded" in name or "timeout" in name:
        return True
    if getattr(exc, "status_code", None) == 429:
        return True
    return "model busy" in message or "overloaded" in message


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

    Cada intento queda registrado en `response.attempts` (incluido el éxito):
    el failover no se esconde y el ledger puede reconstruir «429 → 429 →
    success» sin inventar tokens ni costo por intento fallido.
    """
    attempts: list[dict] = []
    last_error: Exception | None = None
    candidates = route.candidates()
    for index, model in enumerate(candidates):
        for retry in range(2):
            started = time.perf_counter()
            try:
                response = await generate(
                    prompt,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_prompt=system_prompt,
                )
            except Exception as exc:
                last_error = exc
                attempts.append(
                    _attempt_record(
                        model=model,
                        status=_attempt_status(exc),
                        retry=bool(retry),
                        fallback=index > 0,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        error=str(exc),
                    )
                )
                logger.warning(
                    "Gateway model attempt failed",
                    model=model,
                    attempt=index + 1,
                    retry=retry,
                    has_fallback=index == 0 and len(candidates) > 1,
                    error=str(exc),
                )
                if retry == 0 and _retryable_provider_error(exc):
                    await asyncio.sleep(_TRANSIENT_RETRY_SECONDS)
                    continue
                break
            attempts.append(
                _attempt_record(
                    model=model,
                    status="success",
                    retry=bool(retry),
                    fallback=index > 0,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            )
            _attach_attempts(response, attempts)
            return response
    assert last_error is not None
    try:
        last_error.llm_attempts = list(attempts)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — el error original manda
        pass
    raise last_error


def _provider_of(model: str) -> str:
    text = str(model or "")
    return text.split("/", 1)[0] if "/" in text else ""


def _attempt_status(exc: Exception) -> str:
    """Clasifica el fallo del intento (sin exponer secretos ni payloads)."""
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "circuitbreaker" in name:
        return "circuit_open"
    if (
        getattr(exc, "status_code", None) == 429
        or "ratelimit" in name
        or "429" in message
        or "rate limit" in message
    ):
        return "rate_limited"
    if "timeout" in name or "timeout" in message or "timed out" in message:
        return "timeout"
    code = getattr(exc, "status_code", None)
    if code in (401, 403) or "authentication" in name:
        return "auth_error"
    if isinstance(code, int) and code >= 500:
        return "provider_error"
    if "overloaded" in name or "model busy" in message or "overloaded" in message:
        return "provider_error"
    return "error"


def _attempt_record(
    *,
    model: str,
    status: str,
    retry: bool,
    fallback: bool,
    latency_ms: float,
    error: str = "",
) -> dict:
    record: dict = {
        "provider": _provider_of(model),
        "model": str(model or ""),
        "status": status,
        "retry": bool(retry),
        "fallback": bool(fallback),
        "latency_ms": round(float(latency_ms or 0.0), 2),
    }
    if error:
        record["error"] = error[:200]
    return record


def _attach_attempts(response: LLMResponse, attempts: list[dict]) -> None:
    """Adjunta los intentos a la respuesta (fail-soft si el doble no los acepta)."""
    try:
        existing = getattr(response, "attempts", None)
        if isinstance(existing, list):
            existing.extend(attempts)
        else:
            response.attempts = list(attempts)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — observabilidad, nunca rompe la generación
        pass
