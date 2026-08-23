# =============================================================================
# Tool Guards — validación de input, rate limit y timeout (runtime)
# =============================================================================
# El runtime envuelve TODA ejecución de tool con estos guards. Ningún tool
# corre directo: input validado contra input_schema, rate limit por tenant,
# timeout duro. Los errores son controlados (ToolError) y auditados.
# =============================================================================
from __future__ import annotations

import asyncio
import time

from src.agents.tools.base import (
    Tool,
    ToolContext,
    ToolInputError,
    ToolRateLimitedError,
    ToolResult,
)
from src.core.config import get_settings
from src.core.ports import CacheProvider
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_SCHEMA_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def validate_arguments(tool: Tool, arguments: dict) -> dict:
    """Valida args contra input_schema (subconjunto JSON Schema).

    Lanza ToolInputError. Nunca muta arguments.
    """
    schema = tool.input_schema or {}
    if schema.get("type", "object") != "object":
        raise ToolInputError(f"Tool {tool.name} schema must be object")
    clean: dict = {}
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    for key in required:
        if key not in arguments or arguments[key] is None:
            raise ToolInputError(f"Missing required argument: {key}")
    for key, value in arguments.items():
        if key not in properties:
            continue  # extras se descartan (no pasan al tool)
        spec = properties[key]
        expected = _SCHEMA_TYPE_MAP.get(spec.get("type"))
        if expected is not None and not isinstance(value, expected):
            raise ToolInputError(
                f"Argument '{key}' must be {spec.get('type')}, got {type(value).__name__}"
            )
        if spec.get("type") == "string":
            min_length = spec.get("minLength")
            if min_length is not None and len(value) < min_length:
                raise ToolInputError(f"Argument '{key}' too short")
            max_length = spec.get("maxLength")
            if max_length is not None and len(value) > max_length:
                raise ToolInputError(f"Argument '{key}' too long")
            value = value[: spec.get("maxLength") or 10000]
        if spec.get("type") == "integer" and isinstance(value, int):
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and value < minimum:
                raise ToolInputError(f"Argument '{key}' below minimum {minimum}")
            if maximum is not None and value > maximum:
                raise ToolInputError(f"Argument '{key}' above maximum {maximum}")
        clean[key] = value
    return clean


class ToolRateLimiter:
    """Rate limit por tenant+tool usando Redis (fail-open si Redis cae)."""

    def __init__(self, cache: CacheProvider | None) -> None:
        self._cache = cache

    async def check(self, tenant_id, tool_name: str) -> None:
        settings = get_settings()
        limit = settings.RAG_AGENT_TOOL_RATE_LIMIT_PER_MINUTE
        key = f"agent:tool:{tenant_id.hex}:{tool_name}"
        if self._cache is None:
            return
        try:
            count = await self._cache.incr(key, ttl_seconds=60, by=1)
            if count > limit:
                raise ToolRateLimitedError(
                    f"Tool '{tool_name}' rate limited ({limit}/min)"
                )
        except ToolRateLimitedError:
            raise
        except Exception as exc:
            logger.warning("Tool rate limit check failed (fail-open)", error=str(exc))


async def execute_tool_guarded(
    tool: Tool,
    ctx: ToolContext,
    arguments: dict,
    rate_limiter: ToolRateLimiter | None = None,
) -> ToolResult:
    """Valida, rate-limita y ejecuta una tool con timeout. Nunca lanza
    excepciones no controladas hacia el runtime: todo se traduce a
    ToolResult.error."""
    start = time.perf_counter()
    try:
        clean_args = validate_arguments(tool, arguments)
    except ToolInputError as exc:
        return ToolResult(
            error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
        )

    if rate_limiter is not None:
        try:
            await rate_limiter.check(ctx.tenant_id, tool.name)
        except ToolRateLimitedError as exc:
            return ToolResult(
                error=str(exc), latency_ms=(time.perf_counter() - start) * 1000
            )

    try:
        result = await asyncio.wait_for(
            tool.execute(ctx, clean_args),
            timeout=tool.timeout_seconds,
        )
        if result.latency_ms == 0.0:
            result.latency_ms = (time.perf_counter() - start) * 1000
        return result
    except asyncio.TimeoutError:
        return ToolResult(
            error=f"Tool '{tool.name}' timed out after {tool.timeout_seconds:.0f}s",
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        logger.warning(
            "Tool execution failed", tool=tool.name, error=str(exc)
        )
        return ToolResult(
            error=f"{type(exc).__name__}: {exc}",
            latency_ms=(time.perf_counter() - start) * 1000,
        )


def tool_timeout_error_message(tool: Tool) -> str:  # pragma: no cover
    """Mensaje estándar de timeout (referencia para tests)."""
    return f"Tool '{tool.name}' timed out after {tool.timeout_seconds:.0f}s"
